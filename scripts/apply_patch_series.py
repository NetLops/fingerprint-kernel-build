#!/usr/bin/env python3
import argparse
from pathlib import Path
import subprocess


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Apply a git patch series listed in SERIES.txt.")
    parser.add_argument("--repo-root", required=True, help="Target git repo root.")
    parser.add_argument("--series", required=True, help="Path to SERIES.txt.")
    parser.add_argument("--check", action="store_true", help="Only run git apply --check.")
    return parser.parse_args()


def load_series(path: Path) -> list[Path]:
    items: list[Path] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        items.append((path.parent / line).resolve())
    return items


def main() -> int:
    args = parse_args()
    repo_root = Path(args.repo_root).expanduser().resolve()
    series_path = Path(args.series).expanduser().resolve()
    patches = load_series(series_path)

    if not repo_root.is_dir():
        raise RuntimeError(f"repo root not found: {repo_root}")
    if not series_path.is_file():
        raise RuntimeError(f"series file not found: {series_path}")

    for patch in patches:
        if not patch.is_file():
            raise RuntimeError(f"patch file not found: {patch}")
        cmd = ["git", "-C", str(repo_root), "apply", "--whitespace=nowarn"]
        if args.check:
            cmd.append("--check")
        else:
            cmd.append("--3way")
        cmd.append(str(patch))
        subprocess.run(cmd, check=True)
        action = "checked" if args.check else "applied"
        print(f"[OK] {action}: {patch.name}")

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as exc:
        print(f"[ERROR] {exc}")
        raise SystemExit(1)
