#!/usr/bin/env python3
import argparse
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Static smoke checks for Windows build artifacts.")
    parser.add_argument("--build-dir", required=True, help="Path to ungoogled-chromium-windows build directory.")
    parser.add_argument("--target-arch", default="x64", help="Expected Windows target arch token.")
    return parser.parse_args()


def require_one(pattern: str, build_dir: Path) -> Path:
    matches = sorted(build_dir.glob(pattern))
    if not matches:
        raise RuntimeError(f"missing artifact matching {pattern} in {build_dir}")
    return matches[0]


def main() -> int:
    args = parse_args()
    build_dir = Path(args.build_dir).expanduser().resolve()
    if not build_dir.is_dir():
        raise RuntimeError(f"build directory not found: {build_dir}")

    arch = args.target_arch
    zip_path = require_one(f"ungoogled-chromium_*_windows_{arch}.zip", build_dir)
    installer_path = require_one(f"ungoogled-chromium_*_installer_{arch}.exe", build_dir)

    for artifact in (zip_path, installer_path):
        if artifact.stat().st_size <= 0:
            raise RuntimeError(f"empty artifact: {artifact}")
        print(f"[OK] {artifact.name} size={artifact.stat().st_size}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as exc:
        print(f"[ERROR] {exc}")
        raise SystemExit(1)
