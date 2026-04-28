#!/usr/bin/env python3
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys


ARCHIVE_SUFFIXES = (
    ".AppImage",
    ".AppImage.zsync",
    ".dmg",
    ".zip",
    ".pkg",
    ".tar.xz",
    ".tar",
    ".tar.gz",
    ".tgz",
    ".txz",
    ".exe",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Stage release metadata, checksums, and summary logs into the "
            "fingerprint-kernel-assets repository."
        )
    )
    parser.add_argument(
        "--repo-root",
        default=str(Path(__file__).resolve().parents[1]),
        help="Build repo root. Default: current repository root.",
    )
    parser.add_argument(
        "--manifest",
        default="manifests/current.json",
        help="Path to the kernel manifest JSON. Default: manifests/current.json",
    )
    parser.add_argument(
        "--assets-repo",
        default="",
        help="Path to fingerprint-kernel-assets repo. Default: sibling ../fingerprint-kernel-assets",
    )
    parser.add_argument("--run-id", type=int, help="Optional GitHub Actions run id.")
    parser.add_argument(
        "--notes",
        help="Optional free-form note to write into release metadata.",
    )
    parser.add_argument(
        "--scan-dir",
        action="append",
        default=[],
        help="Extra directory to scan for archive files. Can be passed multiple times.",
    )
    parser.add_argument(
        "--commit",
        action="store_true",
        help="Create a git commit in the assets repo after staging metadata.",
    )
    return parser.parse_args()


def run(cmd: list[str], cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        check=check,
        text=True,
        capture_output=True,
    )


def load_manifest(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def resolve_manifest_path(value: str, repo_root: Path) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = repo_root / path
    return path.resolve()


def resolve_assets_repo(args: argparse.Namespace, repo_root: Path) -> Path:
    if args.assets_repo:
        repo = Path(args.assets_repo).expanduser().resolve()
    else:
        repo = (repo_root.parent / "fingerprint-kernel-assets").resolve()
    if not repo.is_dir():
        raise RuntimeError(f"assets repo not found: {repo}")
    if not (repo / ".git").exists():
        raise RuntimeError(f"assets repo is not a git repository: {repo}")
    return repo


def gh_run_metadata(repo_root: Path, run_id: int) -> dict:
    proc = run(
        [
            "gh",
            "run",
            "view",
            "-R",
            "NetLops/fingerprint-kernel-build",
            str(run_id),
            "--json",
            "status,conclusion,url,createdAt,updatedAt,headSha",
        ],
        cwd=repo_root,
        check=False,
    )
    if proc.returncode != 0 or not proc.stdout.strip():
        return {"runId": run_id, "error": (proc.stdout or "") + (proc.stderr or "")}
    data = json.loads(proc.stdout)
    data["runId"] = run_id
    return data


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        while True:
            chunk = fh.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def is_archive(path: Path) -> bool:
    name = path.name.lower()
    return any(name.endswith(suffix) for suffix in ARCHIVE_SUFFIXES)


def discover_archive_files(manifest: dict, args: argparse.Namespace, repo_root: Path) -> list[Path]:
    artifact_dir = resolve_manifest_path(manifest["paths"]["artifactDir"], repo_root)
    packaging_repo_dir = resolve_manifest_path(manifest["paths"]["packagingRepoDir"], repo_root)
    recursive_candidates = [artifact_dir]
    recursive_candidates.extend(Path(item).expanduser().resolve() for item in args.scan_dir)
    shallow_candidates = [packaging_repo_dir / "build"]

    seen: set[Path] = set()
    results: list[Path] = []
    for root in recursive_candidates:
        if not root.exists():
            continue
        for path in sorted(root.rglob("*")):
            if not path.is_file() or not is_archive(path):
                continue
            resolved = path.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            results.append(resolved)

    for root in shallow_candidates:
        if not root.exists():
            continue
        for path in sorted(root.glob("*")):
            if not path.is_file() or not is_archive(path):
                continue
            resolved = path.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            results.append(resolved)
    return results


def summarize_build_logs(manifest: dict, run_meta: dict | None, repo_root: Path) -> str:
    logs_dir = resolve_manifest_path(manifest["paths"]["logsDir"], repo_root)
    lines = [
        f"kernelVersion: {manifest['kernelVersion']}",
        f"generatedAtUtc: {datetime.now(timezone.utc).isoformat()}",
    ]
    if run_meta:
        lines.append(f"runId: {run_meta.get('runId', '')}")
        lines.append(f"runStatus: {run_meta.get('status', '')}")
        lines.append(f"runConclusion: {run_meta.get('conclusion', '')}")
        lines.append(f"runUrl: {run_meta.get('url', '')}")

    build_log = logs_dir / "build.log"
    if build_log.is_file():
        build_lines = build_log.read_text(encoding="utf-8", errors="ignore").splitlines()
        lines.append(f"buildLog: {build_log}")
        lines.append(f"buildLogLastLine: {build_lines[-1] if build_lines else ''}")

    detached_install_log = logs_dir / f"install-supervisor-detached-{run_meta.get('runId')}.log" if run_meta else None
    if detached_install_log and detached_install_log.is_file():
        tail = detached_install_log.read_text(encoding="utf-8", errors="ignore").splitlines()[-20:]
        lines.append("")
        lines.append("installSupervisorTail:")
        lines.extend(tail)

    verify_log = logs_dir / f"post-build-verify-{run_meta.get('runId')}.log" if run_meta else None
    if verify_log and verify_log.is_file():
        tail = verify_log.read_text(encoding="utf-8", errors="ignore").splitlines()[-20:]
        lines.append("")
        lines.append("postBuildVerifyTail:")
        lines.extend(tail)

    return "\n".join(lines).rstrip() + "\n"


def ensure_release_dirs(assets_repo: Path, kernel_version: str) -> dict[str, Path]:
    release_dir = assets_repo / "releases" / kernel_version
    checksums_dir = release_dir / "checksums"
    logs_dir = release_dir / "logs"
    notarization_dir = release_dir / "notarization"
    for path in (release_dir, checksums_dir, logs_dir, notarization_dir):
        path.mkdir(parents=True, exist_ok=True)
    return {
        "release": release_dir,
        "checksums": checksums_dir,
        "logs": logs_dir,
        "notarization": notarization_dir,
    }


def write_notarization_readme(notarization_dir: Path) -> None:
    readme = notarization_dir / "README.md"
    if readme.exists():
        return
    readme.write_text(
        "# Notarization Notes\n\n"
        "把当前版本的签名、公证结果、ticket、Apple 返回信息记录在这里。\n",
        encoding="utf-8",
    )


def git_commit_if_needed(assets_repo: Path, kernel_version: str) -> None:
    status = run(["git", "status", "--short"], cwd=assets_repo).stdout.strip()
    if not status:
        print("[OK] assets repo has no new changes to commit")
        return
    run(["git", "add", "."], cwd=assets_repo)
    run(["git", "commit", "-m", f"Archive {kernel_version} metadata"], cwd=assets_repo)
    print(f"[OK] committed assets repo metadata for {kernel_version}")


def main() -> int:
    args = parse_args()
    repo_root = Path(args.repo_root).expanduser().resolve()
    manifest_path = Path(args.manifest).expanduser()
    if not manifest_path.is_absolute():
        manifest_path = (repo_root / manifest_path).resolve()
    manifest = load_manifest(manifest_path)
    assets_repo = resolve_assets_repo(args, repo_root)
    kernel_version = str(manifest["kernelVersion"])
    run_meta = gh_run_metadata(repo_root, args.run_id) if args.run_id else {}
    release_dirs = ensure_release_dirs(assets_repo, kernel_version)

    shutil.copy2(manifest_path, release_dirs["release"] / "manifest.json")

    archives = discover_archive_files(manifest, args, repo_root)
    checksum_lines = []
    archive_entries = []
    for archive in archives:
        sha = file_sha256(archive)
        checksum_lines.append(f"{sha}  {archive.name}")
        archive_entries.append(
            {
                "filename": archive.name,
                "sourcePath": str(archive),
                "sizeBytes": archive.stat().st_size,
                "sha256": sha,
            }
        )
    (release_dirs["checksums"] / "sha256sums.txt").write_text(
        ("\n".join(checksum_lines) + "\n") if checksum_lines else "",
        encoding="utf-8",
    )

    metadata = {
        "schemaVersion": 1,
        "generatedAtUtc": datetime.now(timezone.utc).isoformat(),
        "kernelVersion": kernel_version,
        "kernelName": manifest.get("kernelName", ""),
        "platform": manifest.get("platform", ""),
        "versions": manifest.get("versions", {}),
        "repos": manifest.get("repos", {}),
        "run": run_meta,
        "assetsRepo": str(assets_repo),
        "archives": archive_entries,
        "notes": args.notes or "",
    }
    (release_dirs["release"] / "release-metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    (release_dirs["logs"] / "summary.txt").write_text(
        summarize_build_logs(manifest, run_meta, repo_root),
        encoding="utf-8",
    )
    write_notarization_readme(release_dirs["notarization"])

    print(f"[OK] staged assets repo release dir: {release_dirs['release']}")
    print(f"[OK] discovered archive files: {len(archive_entries)}")
    if args.commit:
        git_commit_if_needed(assets_repo, kernel_version)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as exc:
        print(f"[ERROR] {exc}")
        raise SystemExit(1)
