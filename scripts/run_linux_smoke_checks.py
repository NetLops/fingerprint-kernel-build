#!/usr/bin/env python3
import argparse
from pathlib import Path
import subprocess


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run static smoke checks against a Linux Chromium build output."
    )
    parser.add_argument(
        "--out-dir",
        required=True,
        help="Path to Chromium out/Default directory.",
    )
    parser.add_argument(
        "--release-dir",
        required=True,
        help="Path to portablelinux build/release directory.",
    )
    parser.add_argument(
        "--target-arch",
        default="arm64",
        help="Expected target arch. Default: arm64.",
    )
    return parser.parse_args()


def run_command(cmd: list[str]) -> str:
    proc = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return ((proc.stdout or "") + (proc.stderr or "")).strip()


def require_file(path: Path) -> None:
    if not path.is_file():
        raise RuntimeError(f"missing file: {path}")


def assert_arch(file_output: str, target_arch: str) -> None:
    normalized = target_arch.lower()
    if normalized in ("arm64", "aarch64"):
        tokens = ("aarch64", "arm aarch64", "arm64")
    elif normalized in ("x64", "x86_64", "amd64"):
        tokens = ("x86-64", "x86_64", "amd64")
    else:
        tokens = (normalized,)
    if not any(token in file_output.lower() for token in tokens):
        raise RuntimeError(
            f"target arch {target_arch!r} not found in file output: {file_output}"
        )


def main() -> int:
    args = parse_args()
    out_dir = Path(args.out_dir).expanduser().resolve()
    release_dir = Path(args.release_dir).expanduser().resolve()

    chrome = out_dir / "chrome"
    chromedriver = out_dir / "chromedriver"
    chrome_wrapper = out_dir / "chrome-wrapper"
    for path in (chrome, chromedriver, chrome_wrapper):
        require_file(path)

    chrome_file = run_command(["file", str(chrome)])
    chromedriver_file = run_command(["file", str(chromedriver)])
    assert_arch(chrome_file, args.target_arch)
    assert_arch(chromedriver_file, args.target_arch)

    appimages = sorted(release_dir.glob(f"*{args.target_arch}*.AppImage"))
    tarballs = sorted(release_dir.glob(f"*{args.target_arch}*_linux.tar.xz"))
    if not appimages:
        raise RuntimeError(f"missing {args.target_arch} AppImage under: {release_dir}")
    if not tarballs:
        raise RuntimeError(f"missing {args.target_arch} tar.xz under: {release_dir}")

    print(f"[OK] chrome: {chrome}")
    print(f"[OK] chrome file: {chrome_file}")
    print(f"[OK] chromedriver file: {chromedriver_file}")
    for appimage in appimages:
        print(f"[OK] AppImage: {appimage}")
    for tarball in tarballs:
        print(f"[OK] tarball: {tarball}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as exc:
        print(f"[ERROR] {exc}")
        raise SystemExit(1)
