#!/usr/bin/env python3
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Optional


NETLOPS_BLOCK_BEGIN = "# >>> netlops custom patches >>>"
NETLOPS_BLOCK_END = "# <<< netlops custom patches <<<"
IGNORE_NAMES = {"__pycache__", ".DS_Store"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Prepare the local build workspace from a kernel manifest by syncing patch queues, "
            "checking out the packaging repo, and injecting custom Chromium patch series."
        )
    )
    parser.add_argument("--manifest", required=True, help="Path to kernel manifest JSON.")
    parser.add_argument(
        "--repo-root",
        default=str(Path(__file__).resolve().parents[1]),
        help="Build repo root. Default: current repository root.",
    )
    parser.add_argument(
        "--packaging-ref",
        help="Optional override for the packaging repo checkout ref. Default: versions.ungoogledTag",
    )
    return parser.parse_args()


def run(cmd: list[str], cwd: Optional[Path] = None) -> None:
    subprocess.run(cmd, cwd=str(cwd) if cwd else None, check=True)


def load_manifest(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def resolve_manifest_path(value: str, repo_root: Path) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = repo_root / path
    return path.resolve()


def copy_dir_contents(src: Path, dst: Path) -> None:
    if not src.is_dir():
        raise RuntimeError(f"missing source directory: {src}")
    if dst.exists():
        shutil.rmtree(dst)
    dst.mkdir(parents=True, exist_ok=True)
    for item in src.rglob("*"):
        if any(part in IGNORE_NAMES for part in item.parts):
            continue
        relative = item.relative_to(src)
        target = dst / relative
        if item.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(item, target)


def resolve_patch_queue_source(
    repo_root: Path,
    manifest: dict,
    queue_name: str,
    default_relative_path: str,
) -> Path | None:
    patch_queues = manifest.get("patchQueues", {})
    configured = patch_queues.get(queue_name, default_relative_path)
    if configured is None or configured is False:
        return None
    if isinstance(configured, str) and not configured.strip():
        return None
    source = Path(str(configured)).expanduser()
    if not source.is_absolute():
        source = repo_root / source
    return source.resolve()


def prepare_patch_queue(
    repo_root: Path,
    manifest: dict,
    queue_name: str,
    default_relative_path: str,
    destination: Path,
) -> bool:
    source = resolve_patch_queue_source(
        repo_root,
        manifest,
        queue_name,
        default_relative_path,
    )
    if source is None:
        if destination.exists():
            shutil.rmtree(destination)
        destination.mkdir(parents=True, exist_ok=True)
        (destination / "SERIES.txt").write_text("", encoding="utf-8")
        return False

    copy_dir_contents(source, destination)
    return bool(apply_queue_excludes(manifest, queue_name, destination / "SERIES.txt"))


def load_series(series_path: Path) -> list[Path]:
    items: list[Path] = []
    if not series_path.is_file():
        raise RuntimeError(f"series file not found: {series_path}")
    for raw in series_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        items.append(Path(line))
    return items


def write_series(series_path: Path, entries: list[Path]) -> None:
    text = "\n".join(entry.as_posix() for entry in entries)
    if text:
        text += "\n"
    series_path.write_text(text, encoding="utf-8")


def apply_queue_excludes(manifest: dict, queue_name: str, series_path: Path) -> list[Path]:
    excludes = manifest.get("patchQueueExcludes", {}).get(queue_name, [])
    if not excludes:
        return load_series(series_path)
    if not isinstance(excludes, list):
        raise RuntimeError(f"patchQueueExcludes.{queue_name} must be a list")

    excluded = {Path(str(item)).as_posix() for item in excludes}
    entries = load_series(series_path)
    matched = {entry.as_posix() for entry in entries if entry.as_posix() in excluded}
    missing = sorted(excluded - matched)
    if missing:
        raise RuntimeError(
            f"patchQueueExcludes.{queue_name} entries not found in {series_path}: {', '.join(missing)}"
        )

    filtered = [entry for entry in entries if entry.as_posix() not in excluded]
    write_series(series_path, filtered)
    return filtered


def prepare_packaging_repo(repo_url: str, repo_dir: Path, checkout_ref: str) -> None:
    if not (repo_dir / ".git").is_dir():
        if repo_dir.exists():
            shutil.rmtree(repo_dir)
        repo_dir.parent.mkdir(parents=True, exist_ok=True)
        run(["git", "clone", "--recurse-submodules", repo_url, str(repo_dir)])
    else:
        run(["git", "-C", str(repo_dir), "remote", "set-url", "origin", repo_url])

    run(["git", "-C", str(repo_dir), "fetch", "--tags", "origin"])
    run(["git", "-C", str(repo_dir), "checkout", "--force", checkout_ref])
    run(["git", "-C", str(repo_dir), "reset", "--hard", checkout_ref])
    run(["git", "-C", str(repo_dir), "clean", "-fdx"])
    run(["git", "-C", str(repo_dir), "submodule", "sync", "--recursive"])
    run(["git", "-C", str(repo_dir), "submodule", "update", "--init", "--recursive"])


def apply_packaging_patches(repo_root: Path, packaging_repo_dir: Path, series_path: Path) -> None:
    run(
        [
            sys.executable,
            str(repo_root / "scripts" / "apply_patch_series.py"),
            "--repo-root",
            str(packaging_repo_dir),
            "--series",
            str(series_path),
        ]
    )


def strip_managed_block(lines: list[str]) -> list[str]:
    output: list[str] = []
    in_block = False
    for line in lines:
        if line == NETLOPS_BLOCK_BEGIN:
            in_block = True
            continue
        if line == NETLOPS_BLOCK_END:
            in_block = False
            continue
        if not in_block:
            output.append(line)
    while output and output[-1] == "":
        output.pop()
    return output


def inject_overlay_patches(
    packaging_repo_dir: Path,
    chromium_patches_dir: Path,
    product_patches_dir: Path,
) -> list[str]:
    packaging_patch_root = packaging_repo_dir / "patches"
    packaging_series_path = packaging_patch_root / "series"
    if not packaging_series_path.is_file():
        raise RuntimeError(f"packaging patch series not found: {packaging_series_path}")

    dest_root = packaging_patch_root / "netlops"
    if dest_root.exists():
        shutil.rmtree(dest_root)

    overlay_entries: list[tuple[str, Path, list[Path]]] = [
        ("chromium", chromium_patches_dir, load_series(chromium_patches_dir / "SERIES.txt")),
        ("product", product_patches_dir, load_series(product_patches_dir / "SERIES.txt")),
    ]
    appended_paths: list[str] = []

    for group_name, group_root, entries in overlay_entries:
        for entry in entries:
            source_patch = group_root / entry
            if not source_patch.is_file():
                raise RuntimeError(f"patch file not found: {source_patch}")
            dest_patch = dest_root / group_name / entry
            dest_patch.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_patch, dest_patch)
            appended_paths.append((Path("netlops") / group_name / entry).as_posix())

    series_lines = packaging_series_path.read_text(encoding="utf-8").splitlines()
    new_lines = strip_managed_block(series_lines)
    if appended_paths:
        new_lines.append("")
        new_lines.append(NETLOPS_BLOCK_BEGIN)

        chromium_entries = overlay_entries[0][2]
        if chromium_entries:
            new_lines.append("# chromium")
            new_lines.extend((Path("netlops") / "chromium" / entry).as_posix() for entry in chromium_entries)

        product_entries = overlay_entries[1][2]
        if product_entries:
            if chromium_entries:
                new_lines.append("")
            new_lines.append("# product")
            new_lines.extend((Path("netlops") / "product" / entry).as_posix() for entry in product_entries)

        new_lines.append(NETLOPS_BLOCK_END)

    packaging_series_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    return appended_paths


def export_env(items: dict[str, str]) -> None:
    env_file = os.environ.get("GITHUB_ENV")
    if env_file:
        with open(env_file, "a", encoding="utf-8") as handle:
            for key, value in items.items():
                handle.write(f"{key}={value}\n")


def main() -> int:
    args = parse_args()
    manifest_path = Path(args.manifest).expanduser().resolve()
    repo_root = Path(args.repo_root).expanduser().resolve()
    manifest = load_manifest(manifest_path)

    workspace_root = resolve_manifest_path(manifest["paths"]["workspaceRoot"], repo_root)
    packaging_repo_dir = resolve_manifest_path(manifest["paths"]["packagingRepoDir"], repo_root)
    chromium_source_dir = resolve_manifest_path(manifest["paths"]["chromiumSourceDir"], repo_root)
    artifact_dir = resolve_manifest_path(manifest["paths"]["artifactDir"], repo_root)
    logs_dir = resolve_manifest_path(manifest["paths"]["logsDir"], repo_root)
    packaging_patches_dir = resolve_manifest_path(manifest["paths"]["packagingPatchesDir"], repo_root)
    chromium_patches_dir = resolve_manifest_path(manifest["paths"]["chromiumPatchesDir"], repo_root)
    product_patches_dir = resolve_manifest_path(manifest["paths"]["productPatchesDir"], repo_root)
    checkout_ref = args.packaging_ref or manifest["versions"]["ungoogledTag"]

    workspace_root.mkdir(parents=True, exist_ok=True)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)

    packaging_queue_has_entries = prepare_patch_queue(
        repo_root,
        manifest,
        "packaging",
        "patches/packaging",
        packaging_patches_dir,
    )
    prepare_patch_queue(
        repo_root,
        manifest,
        "chromium",
        "patches/chromium",
        chromium_patches_dir,
    )
    prepare_patch_queue(
        repo_root,
        manifest,
        "product",
        "patches/product",
        product_patches_dir,
    )
    shutil.copy2(manifest_path, workspace_root / "kernel-manifest.json")

    prepare_packaging_repo(manifest["repos"]["packagingRepo"], packaging_repo_dir, checkout_ref)
    if packaging_queue_has_entries:
        apply_packaging_patches(repo_root, packaging_repo_dir, packaging_patches_dir / "SERIES.txt")
    injected_paths = inject_overlay_patches(packaging_repo_dir, chromium_patches_dir, product_patches_dir)

    summary = {
        "manifestPath": str(manifest_path),
        "workspaceRoot": str(workspace_root),
        "packagingRepoDir": str(packaging_repo_dir),
        "chromiumSourceDir": str(chromium_source_dir),
        "artifactDir": str(artifact_dir),
        "logsDir": str(logs_dir),
        "checkoutRef": checkout_ref,
        "packagingPatchQueueApplied": packaging_queue_has_entries,
        "injectedSeriesEntries": injected_paths,
    }
    summary_path = logs_dir / "prepare-build-context.json"
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    env_items = {
        "FK_MANIFEST_PATH": str(manifest_path),
        "FK_WORKSPACE_ROOT": str(workspace_root),
        "FK_PACKAGING_REPO_DIR": str(packaging_repo_dir),
        "FK_CHROMIUM_SOURCE_DIR": str(chromium_source_dir),
        "FK_ARTIFACT_DIR": str(artifact_dir),
        "FK_LOGS_DIR": str(logs_dir),
        "FK_PACKAGING_REF": checkout_ref,
        "FK_BUNDLE_NAME": str(manifest["build"]["bundleName"]),
        "FK_PLATFORM": str(manifest.get("platform", "")),
        "FK_TARGET_OS": str(manifest["build"].get("targetOs", "")),
        "FK_TARGET_ARCH": str(manifest["build"].get("targetArch", "")),
    }
    export_env(env_items)

    print(f"[OK] workspace synced: {workspace_root}")
    print(f"[OK] packaging repo ready: {packaging_repo_dir}")
    print(f"[OK] checkout ref: {checkout_ref}")
    if packaging_queue_has_entries:
        print(f"[OK] packaging patches applied from: {packaging_patches_dir / 'SERIES.txt'}")
    else:
        print(f"[OK] packaging patch queue disabled for this manifest")
    print(f"[OK] overlay patch entries injected: {len(injected_paths)}")
    print(f"[OK] summary written: {summary_path}")
    for key, value in env_items.items():
        print(f"{key}={value}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as exc:
        print(f"[ERROR] {exc}")
        raise SystemExit(1)
