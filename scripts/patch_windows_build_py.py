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
import re
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
    parser.add_argument(
        "--gn-profile",
        default="release",
        choices=("release", "hosted-fast"),
        help="Optional GN flag profile to apply to flags.windows.gn.",
    )
    return parser.parse_args()


def set_gn_arg(text: str, name: str, value: str) -> tuple[str, bool]:
    line = f"{name}={value}"
    pattern = re.compile(rf"^{re.escape(name)}\s*=.*$", re.MULTILINE)
    if pattern.search(text):
        new_text = pattern.sub(line, text)
        return new_text, new_text != text
    suffix = "\n" if text.endswith("\n") else "\n\n"
    return f"{text}{suffix}{line}\n", True


def apply_gn_profile(packaging_repo: Path, profile: str) -> bool:
    if profile == "release":
        return False
    flags_path = packaging_repo / "flags.windows.gn"
    text = flags_path.read_text(encoding="utf-8")
    changed = False
    # Hosted Windows runners cannot finish Chromium 146 with official PGO/LTO
    # flags before the 6h hard cap. This profile produces a usable functional
    # package for validation while preserving non-debug, non-component outputs.
    for name, value in {
        "chrome_pgo_phase": "0",
        "is_official_build": "false",
        "use_thin_lto": "false",
        "symbol_level": "0",
        "blink_symbol_level": "0",
        "v8_symbol_level": "0",
    }.items():
        text, item_changed = set_gn_arg(text, name, value)
        changed = changed or item_changed
    flags_path.write_text(text, encoding="utf-8", newline="")
    print(f"[OK] applied Windows GN profile {profile}: {flags_path} changed={changed}")
    return changed


def main() -> None:
    args = parse_args()
    build_py = Path(args.build_py)
    packaging_repo = build_py.parent
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
    changed_gn = apply_gn_profile(packaging_repo, args.gn_profile)
    changed = changed_timeout or changed_parser or changed_targets or changed_package or changed_gn
    print(f"[OK] patched {build_py} changed={changed}")


if __name__ == "__main__":
    main()
