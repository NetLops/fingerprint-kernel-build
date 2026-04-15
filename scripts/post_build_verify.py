#!/usr/bin/env python3
import argparse
import json
import sqlite3
import subprocess
import sys
import tempfile
import textwrap
import time
from pathlib import Path


def default_runner_python() -> str:
    repo_python = Path(__file__).resolve().parents[1] / ".venv" / "bin" / "python"
    if repo_python.is_file():
        return str(repo_python)
    return sys.executable


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Wait for a workflow run to finish installing a built Chromium.app into Ant Browser, "
            "then run smoke checks and a basic headless fingerprint probe."
        )
    )
    parser.add_argument("--run-id", required=True, help="GitHub Actions run id to watch.")
    parser.add_argument(
        "--repo",
        default="NetLops/fingerprint-kernel-build",
        help="GitHub repository slug. Default: NetLops/fingerprint-kernel-build",
    )
    parser.add_argument(
        "--state-root",
        default=str(Path.home() / "Library/Application Support/ant-browser"),
        help="Ant Browser state root. Default: ~/Library/Application Support/ant-browser",
    )
    parser.add_argument(
        "--core-path",
        required=True,
        help="Relative core path under the Ant Browser state root, e.g. chrome/chromium-146.0.7680.177-fk.1",
    )
    parser.add_argument(
        "--runner-python",
        default=default_runner_python(),
        help="Python interpreter used to invoke run_smoke_checks.py. Default: repo .venv python if present, else current Python",
    )
    parser.add_argument(
        "--smoke-script",
        default=str(Path(__file__).resolve().parents[0] / "run_smoke_checks.py"),
        help="Path to run_smoke_checks.py",
    )
    parser.add_argument(
        "--log-path",
        help="Optional log file path. Default: <repo>/logs/post-build-verify-<run-id>.log",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=8 * 60 * 60,
        help="How long to wait before failing. Default: 8 hours",
    )
    parser.add_argument(
        "--poll-seconds",
        type=int,
        default=60,
        help="Polling interval. Default: 60",
    )
    return parser.parse_args()


def append_log(log_path: Path, message: str) -> None:
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{stamp}] {message}"
    print(line, flush=True)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def gh_status(repo: str, run_id: str) -> dict:
    proc = subprocess.run(
        [
            "gh",
            "run",
            "view",
            "-R",
            repo,
            run_id,
            "--json",
            "status,conclusion,url",
        ],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return {"error": ((proc.stdout or "") + (proc.stderr or "")).strip()}
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        return {"error": f"json parse failed: {exc}: {(proc.stdout or '')[:400]}"}


def db_rows(db_path: Path) -> list[tuple]:
    if not db_path.is_file():
        return []
    conn = sqlite3.connect(str(db_path))
    try:
        return conn.execute(
            """
            SELECT core_name, core_path, is_default, sort_order
            FROM browser_cores
            ORDER BY sort_order, created_at
            """
        ).fetchall()
    finally:
        conn.close()


def has_installed_core(rows: list[tuple], core_path: str) -> bool:
    return any(row[1] == core_path for row in rows)


def run_smoke(runner_python: str, smoke_script: str, app_path: Path) -> tuple[int, str]:
    proc = subprocess.run(
        [runner_python, smoke_script, "--app", str(app_path)],
        capture_output=True,
        text=True,
    )
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def run_probe(app_path: Path) -> tuple[int, str]:
    executable = app_path / "Contents" / "MacOS" / "Chromium"
    html = textwrap.dedent(
        """\
        <!doctype html>
        <meta charset="utf-8">
        <pre id="out">pending</pre>
        <script>
        (async () => {
          const data = {
            ua: navigator.userAgent,
            platform: navigator.platform,
            webdriver: navigator.webdriver,
            hardwareConcurrency: navigator.hardwareConcurrency,
            deviceMemory: navigator.deviceMemory,
            language: navigator.language,
            languages: navigator.languages,
            timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
            uaData: navigator.userAgentData ? {
              brands: navigator.userAgentData.brands,
              mobile: navigator.userAgentData.mobile,
              platform: navigator.userAgentData.platform,
            } : null,
          };
          document.getElementById('out').textContent = JSON.stringify(data, null, 2);
        })();
        </script>
        """
    )
    with tempfile.TemporaryDirectory() as td:
        page = Path(td) / "probe.html"
        page.write_text(html, encoding="utf-8")
        cmd = [
            str(executable),
            "--headless=new",
            "--disable-gpu",
            "--no-first-run",
            "--allow-file-access-from-files",
            "--virtual-time-budget=3000",
            "--fingerprint",
            "--fingerprint-brand=Chrome",
            "--fingerprint-platform=mac",
            "--timezone=Asia/Shanghai",
            "--accept-lang=zh-CN,zh",
            "--dump-dom",
            f"file://{page}",
        ]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            return proc.returncode, (proc.stdout or "") + (proc.stderr or "")
        except subprocess.TimeoutExpired as exc:
            output = ((exc.stdout or "") + (exc.stderr or "")).strip()
            return 124, output


def main() -> int:
    args = parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    log_path = (
        Path(args.log_path).expanduser().resolve()
        if args.log_path
        else (repo_root / "logs" / f"post-build-verify-{args.run_id}.log").resolve()
    )
    state_root = Path(args.state_root).expanduser().resolve()
    db_path = state_root / "data" / "app.db"
    app_path = state_root / args.core_path / "Chromium.app"

    append_log(log_path, "background verifier armed")
    append_log(log_path, f"watching run={args.run_id} repo={args.repo}")
    append_log(log_path, f"expected app={app_path}")

    start = time.time()
    last_status = None
    last_rows_json = None
    while time.time() - start < args.timeout_seconds:
        status = gh_status(args.repo, args.run_id)
        status_json = json.dumps(status, ensure_ascii=False, sort_keys=True)
        if status_json != last_status:
            append_log(log_path, f"run_status={status_json}")
            last_status = status_json

        rows = db_rows(db_path)
        rows_json = json.dumps(rows, ensure_ascii=False)
        if rows and rows_json != last_rows_json:
            append_log(log_path, f"db_rows={rows_json}")
            last_rows_json = rows_json

        if app_path.is_dir() and has_installed_core(rows, args.core_path):
            append_log(log_path, f"installed core detected at {app_path}")
            rc, output = run_smoke(args.runner_python, args.smoke_script, app_path)
            append_log(log_path, f"smoke_rc={rc}")
            append_log(log_path, output[:12000].rstrip())
            rc, output = run_probe(app_path)
            append_log(log_path, f"probe_rc={rc}")
            append_log(log_path, output[:20000].rstrip())
            append_log(log_path, "background verifier complete")
            return 0

        if status.get("status") == "completed" and status.get("conclusion") not in ("", None, "success"):
            append_log(log_path, "run completed without success; stopping verifier")
            return 1

        time.sleep(args.poll_seconds)

    append_log(log_path, "timeout waiting for installed core")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
