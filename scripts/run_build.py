#!/usr/bin/env python3
import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Dispatch or watch the mac arm64 GitHub Actions build, then optionally install the "
            "built Chromium.app into a local Ant Browser state directory."
        )
    )
    parser.add_argument(
        "--repo-root",
        default=str(Path(__file__).resolve().parents[1]),
        help="Build repo root. Default: current repository root.",
    )
    parser.add_argument(
        "--repo",
        default="NetLops/fingerprint-kernel-build",
        help="GitHub repository slug for the build workflow.",
    )
    parser.add_argument(
        "--workflow",
        default="build-mac-arm64.yml",
        help="GitHub Actions workflow file name. Default: build-mac-arm64.yml",
    )
    parser.add_argument(
        "--manifest",
        default="manifests/current.json",
        help="Path to the kernel manifest JSON. Default: manifests/current.json",
    )
    parser.add_argument(
        "--ref",
        help="Git ref used when dispatching a new workflow run. Default: current git branch.",
    )
    parser.add_argument(
        "--packaging-ref",
        help="Optional override for the packaging repo git ref.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Dispatch the workflow in dry-run mode.",
    )
    parser.add_argument(
        "--existing-run-id",
        type=int,
        help="Skip dispatch and watch an already-running workflow run.",
    )
    parser.add_argument(
        "--poll-seconds",
        type=float,
        default=3.0,
        help="Polling interval while waiting for a newly dispatched run to appear. Default: 3",
    )
    parser.add_argument(
        "--resolve-timeout-seconds",
        type=int,
        default=90,
        help="How long to wait for a newly dispatched run id to appear. Default: 90",
    )
    parser.add_argument(
        "--install",
        action="store_true",
        help="Install the built app into Ant Browser after a successful non-dry-run build.",
    )
    parser.add_argument(
        "--ant-browser-repo",
        help="Path to the local Ant-Browser repository. Default: sibling ../Ant-Browser",
    )
    parser.add_argument(
        "--installer-script",
        help="Optional explicit path to install-into-ant-browser.py",
    )
    parser.add_argument(
        "--state-root",
        help="Optional explicit Ant Browser state root. Default: manifest install.antBrowserStateRoot",
    )
    parser.add_argument(
        "--core-name",
        help="Optional explicit core display name. Default: manifest install.suggestedCoreName",
    )
    parser.add_argument(
        "--relative-core-path",
        help="Optional explicit relative core path. Default: manifest install.relativeCorePath",
    )
    parser.add_argument(
        "--set-default",
        action="store_true",
        help="Set the installed kernel as the default core.",
    )
    parser.add_argument(
        "--replace-existing",
        action="store_true",
        help="Replace an existing installed core with the same path.",
    )
    return parser.parse_args()


def run(cmd: list[str], cwd: Path | None = None, capture_output: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        check=True,
        text=True,
        capture_output=capture_output,
    )


def load_manifest(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def parse_iso8601(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def current_git_ref(repo_root: Path) -> str:
    proc = run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=repo_root, capture_output=True)
    ref = proc.stdout.strip()
    if not ref or ref == "HEAD":
        raise RuntimeError("could not determine current git branch; pass --ref explicitly")
    return ref


def current_head_sha(repo_root: Path) -> str:
    proc = run(["git", "rev-parse", "HEAD"], cwd=repo_root, capture_output=True)
    sha = proc.stdout.strip()
    if not sha:
        raise RuntimeError("could not determine current git HEAD sha")
    return sha


def gh_json(repo_root: Path, args: list[str]) -> object:
    proc = run(["gh", *args], cwd=repo_root, capture_output=True)
    output = proc.stdout.strip()
    return json.loads(output) if output else None


def dispatch_run(args: argparse.Namespace, repo_root: Path, manifest_path: str) -> tuple[int, str]:
    ref = args.ref or current_git_ref(repo_root)
    head_sha = current_head_sha(repo_root)
    started_at = datetime.now(timezone.utc) - timedelta(seconds=5)

    cmd = [
        "gh",
        "workflow",
        "run",
        args.workflow,
        "-R",
        args.repo,
        "--ref",
        ref,
        "-f",
        f"manifest_path={manifest_path}",
        "-f",
        f"dry_run={'true' if args.dry_run else 'false'}",
    ]
    if args.packaging_ref:
        cmd.extend(["-f", f"packaging_ref={args.packaging_ref}"])
    run(cmd, cwd=repo_root)

    deadline = time.monotonic() + args.resolve_timeout_seconds
    while time.monotonic() < deadline:
        runs = gh_json(
            repo_root,
            [
                "run",
                "list",
                "-R",
                args.repo,
                "--workflow",
                args.workflow,
                "--limit",
                "20",
                "--json",
                "databaseId,headSha,createdAt,url,status",
            ],
        )
        if isinstance(runs, list):
            matching = []
            for item in runs:
                created_at = parse_iso8601(item["createdAt"])
                if item.get("headSha") != head_sha:
                    continue
                if created_at < started_at:
                    continue
                matching.append(item)
            if matching:
                matching.sort(key=lambda item: item["createdAt"], reverse=True)
                latest = matching[0]
                return int(latest["databaseId"]), str(latest["url"])
        time.sleep(args.poll_seconds)

    raise RuntimeError(
        "workflow dispatch succeeded but no matching run id was found before timeout; "
        "check `gh run list` manually"
    )


def resolve_run_url(repo_root: Path, repo: str, run_id: int) -> str:
    info = gh_json(repo_root, ["run", "view", "-R", repo, str(run_id), "--json", "url"])
    if isinstance(info, dict) and info.get("url"):
        return str(info["url"])
    return f"https://github.com/{repo}/actions/runs/{run_id}"


def watch_run(repo_root: Path, repo: str, run_id: int, logs_dir: Path) -> None:
    try:
        run(["gh", "run", "watch", "-R", repo, str(run_id), "--exit-status"], cwd=repo_root)
    except subprocess.CalledProcessError as exc:
        failed_log_path = logs_dir / f"gh-run-{run_id}-failed.log"
        proc = subprocess.run(
            ["gh", "run", "view", "-R", repo, str(run_id), "--log-failed"],
            cwd=str(repo_root),
            check=False,
            text=True,
            capture_output=True,
        )
        output = ((proc.stdout or "") + (proc.stderr or "")).strip()
        if output:
            failed_log_path.parent.mkdir(parents=True, exist_ok=True)
            failed_log_path.write_text(output + "\n", encoding="utf-8")
            print(f"[WARN] failed step log written: {failed_log_path}")
        raise RuntimeError(f"workflow run failed: {run_id}") from exc


def find_built_app(manifest: dict) -> Path:
    packaging_repo_dir = Path(manifest["paths"]["packagingRepoDir"]).expanduser().resolve()
    bundle_name = manifest["build"]["bundleName"]
    candidates = [
        packaging_repo_dir / "build" / "src" / "out" / "Default" / bundle_name,
        packaging_repo_dir / "build" / bundle_name,
    ]
    for candidate in candidates:
        if candidate.is_dir():
            return candidate

    out_root = packaging_repo_dir / "build" / "src" / "out"
    if out_root.is_dir():
        matches = sorted(out_root.glob(f"*/{bundle_name}"))
        if matches:
            return matches[0]
    raise RuntimeError(f"built app bundle not found under: {packaging_repo_dir}")


def resolve_installer_script(args: argparse.Namespace, repo_root: Path) -> Path:
    if args.installer_script:
        script = Path(args.installer_script).expanduser().resolve()
    else:
        ant_browser_repo = (
            Path(args.ant_browser_repo).expanduser().resolve()
            if args.ant_browser_repo
            else (repo_root.parent / "Ant-Browser").resolve()
        )
        script = ant_browser_repo / "tools" / "fingerprint-kernel" / "install-into-ant-browser.py"
    if not script.is_file():
        raise RuntimeError(f"installer script not found: {script}")
    return script


def install_built_app(args: argparse.Namespace, repo_root: Path, manifest: dict) -> None:
    if args.dry_run:
        raise RuntimeError("--install cannot be used with --dry-run")

    app_path = find_built_app(manifest)
    installer_script = resolve_installer_script(args, repo_root)
    install_info = manifest.get("install", {})
    core_name = args.core_name or install_info.get("suggestedCoreName") or f"Chromium {manifest['kernelVersion']}"
    state_root = args.state_root or install_info.get("antBrowserStateRoot")
    relative_core_path = args.relative_core_path or install_info.get("relativeCorePath")

    cmd = [
        sys.executable,
        str(installer_script),
        "--app",
        str(app_path),
        "--version",
        str(manifest["kernelVersion"]),
        "--core-name",
        str(core_name),
    ]
    if state_root:
        cmd.extend(["--state-root", str(state_root)])
    if relative_core_path:
        cmd.extend(["--relative-core-path", str(relative_core_path)])
    if args.set_default:
        cmd.append("--set-default")
    if args.replace_existing:
        cmd.append("--replace-existing")

    run(cmd, cwd=repo_root)
    print(f"[OK] installed built app from: {app_path}")


def ensure_prereqs() -> None:
    for binary in ("gh", "git"):
        if shutil.which(binary) is None:
            raise RuntimeError(f"required binary not found in PATH: {binary}")


def main() -> int:
    args = parse_args()
    ensure_prereqs()

    repo_root = Path(args.repo_root).expanduser().resolve()
    manifest_path = Path(args.manifest).expanduser()
    if not manifest_path.is_absolute():
        manifest_path = (repo_root / manifest_path).resolve()
    manifest = load_manifest(manifest_path)
    logs_dir = Path(manifest["paths"]["logsDir"]).expanduser().resolve()
    logs_dir.mkdir(parents=True, exist_ok=True)

    if args.existing_run_id:
        run_id = args.existing_run_id
        run_url = resolve_run_url(repo_root, args.repo, run_id)
        print(f"[OK] reusing existing workflow run: {run_id}")
    else:
        run_id, run_url = dispatch_run(args, repo_root, manifest_path.as_posix())
        print(f"[OK] dispatched workflow run: {run_id}")

    print(f"[OK] run url: {run_url}")
    watch_run(repo_root, args.repo, run_id, logs_dir)
    print(f"[OK] workflow run succeeded: {run_id}")

    if args.install:
        install_built_app(args, repo_root, manifest)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as exc:
        print(f"[ERROR] {exc}")
        raise SystemExit(1)
