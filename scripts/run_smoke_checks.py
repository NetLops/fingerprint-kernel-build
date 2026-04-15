#!/usr/bin/env python3
import argparse
from pathlib import Path
import subprocess


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run basic smoke checks against a built Chromium.app bundle.")
    parser.add_argument("--app", required=True, help="Path to Chromium.app")
    parser.add_argument("--require-codesign", action="store_true", help="Fail if codesign verification fails.")
    return parser.parse_args()


def run_command(cmd: list[str], allow_failure: bool = False) -> tuple[int, str]:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    output = (proc.stdout or "") + (proc.stderr or "")
    if proc.returncode != 0 and not allow_failure:
        raise RuntimeError(output.strip() or f"command failed: {' '.join(cmd)}")
    return proc.returncode, output.strip()


def main() -> int:
    args = parse_args()
    app_path = Path(args.app).expanduser().resolve()
    macos_dir = app_path / "Contents" / "MacOS"
    if not app_path.is_dir() or app_path.suffix != ".app":
        raise RuntimeError(f"not a .app bundle: {app_path}")
    if not macos_dir.is_dir():
        raise RuntimeError(f"missing Contents/MacOS: {app_path}")

    executables = [item for item in macos_dir.iterdir() if item.is_file()]
    if not executables:
        raise RuntimeError(f"no executable found in: {macos_dir}")
    executable = executables[0]

    _, archs = run_command(["lipo", "-archs", str(executable)])
    print(f"[OK] executable: {executable}")
    print(f"[OK] archs: {archs}")

    code, output = run_command(
        ["codesign", "--verify", "--deep", "--strict", str(app_path)],
        allow_failure=True,
    )
    if code == 0:
        print("[OK] codesign verification passed")
    elif args.require_codesign:
        raise RuntimeError(output or "codesign verification failed")
    else:
        print("[WARN] codesign verification skipped/failed:")
        print(output or "(no output)")

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as exc:
        print(f"[ERROR] {exc}")
        raise SystemExit(1)
