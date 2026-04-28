#!/usr/bin/env python3
import argparse
import json
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render a concise upgrade plan from kernel-manifest.json.")
    parser.add_argument("--manifest", required=True, help="Path to kernel-manifest.json")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    manifest_path = Path(args.manifest).expanduser().resolve()
    data = json.loads(manifest_path.read_text(encoding="utf-8"))

    versions = data.get("versions", {})
    paths = data.get("paths", {})
    build = data.get("build", {})
    target_os = build.get("targetOs", "darwin")
    target_arch = build.get("targetArch", "arm64")
    bundle_name = build.get("bundleName", "Chromium.app")
    print("# Upgrade Plan")
    print()
    print(f"- Kernel version: `{data.get('kernelVersion', 'unknown')}`")
    print(f"- Platform: `{data.get('platform', 'unknown')}`")
    print(f"- Chromium tag: `{versions.get('chromiumTag', 'unknown')}`")
    print(f"- Ungoogled tag: `{versions.get('ungoogledTag', 'unknown')}`")
    print(f"- Workspace: `{paths.get('workspaceRoot', 'unknown')}`")
    print()
    print("## Tasks")
    print("1. Checkout packaging repo to the target ungoogled tag.")
    print("2. Apply `patches/packaging/SERIES.txt` when enabled by the manifest.")
    print("3. Sync Chromium sources and apply `patches/chromium/SERIES.txt`.")
    print("4. Apply `patches/product/SERIES.txt`.")
    print(f"5. Build `{bundle_name}` for {target_os} {target_arch}.")
    print("6. Run the platform smoke checks on the built output.")
    print("7. Package and archive artifacts.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
