#!/usr/bin/env python3
"""Patch ungoogled-chromium-windows build.py for CI supervision.

The upstream Windows packaging script hard-codes:

- a 3.5 hour ninja timeout, which is too short for CI diagnostics; and
- the release target set (chrome, chromedriver, mini_installer), which makes it
  impossible to run a cheaper chrome-only smoke compile.

This helper keeps the workflow patching logic in Python instead of fragile
PowerShell string literals. It is intentionally idempotent.
"""

from __future__ import annotations

import argparse
from pathlib import Path


def replace_once(text: str, old: str, new: str, description: str) -> tuple[str, bool]:
    if old in text:
        return text.replace(old, new, 1), True
    if new in text:
        return text, False
    raise RuntimeError(f"could not find marker for {description}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build-py", required=True, help="Path to ungoogled-chromium-windows build.py")
    parser.add_argument("--timeout-hours", required=True, help="Ninja timeout in hours")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    build_py = Path(args.build_py)
    text = build_py.read_text(encoding="utf-8")

    timeout_old = "timeout=3.5*60*60"
    timeout_new = f"timeout={args.timeout_hours}*60*60"
    text, changed_timeout = replace_once(text, timeout_old, timeout_new, "ninja timeout")

    parser_old = """    parser.add_argument(
        '--tarball',
        action='store_true'
    )
"""
    parser_new = """    parser.add_argument(
        '--tarball',
        action='store_true'
    )
    parser.add_argument(
        '--targets',
        nargs='+',
        default=('chrome', 'chromedriver', 'mini_installer'),
        choices=('chrome', 'chromedriver', 'mini_installer'),
        help='GN/Ninja targets to build. Default: release artifact targets.'
    )
"""
    text, changed_parser = replace_once(text, parser_old, parser_new, "--targets parser argument")

    targets_old = """    ninja_commandline.append('chrome')
    ninja_commandline.append('chromedriver')
    ninja_commandline.append('mini_installer')
"""
    targets_new = """    ninja_commandline.extend(args.targets)
"""
    text, changed_targets = replace_once(text, targets_old, targets_new, "ninja target selection")

    package_old = """        # package
        os.chdir(_ROOT_DIR)
        subprocess.run([sys.executable, 'package.py'])
"""
    package_new = """        # package only when release artifacts were requested
        if 'mini_installer' in args.targets:
            os.chdir(_ROOT_DIR)
            subprocess.run([sys.executable, 'package.py'], check=True)
"""
    text, changed_package = replace_once(text, package_old, package_new, "conditional package step")

    build_py.write_text(text, encoding="utf-8", newline="")
    changed = changed_timeout or changed_parser or changed_targets or changed_package
    print(f"[OK] patched {build_py} changed={changed}")


if __name__ == "__main__":
    main()
