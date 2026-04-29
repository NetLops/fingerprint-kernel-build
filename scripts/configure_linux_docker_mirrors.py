#!/usr/bin/env python3
import argparse
from pathlib import Path


DEBIAN_MIRROR = "http://mirrors.tuna.tsinghua.edu.cn/debian"
DEBIAN_SECURITY_MIRROR = "http://mirrors.tuna.tsinghua.edu.cn/debian-security"
DOCKER_DEBIAN_IMAGE = "docker.m.daocloud.io/library/debian:trixie-slim"
NPM_MIRROR = "https://registry.npmmirror.com"
CARGO_MIRROR = "sparse+https://rsproxy.cn/index/"
LLVM_GIT_URL = "https://github.com/llvm/llvm-project"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Patch a prepared portablelinux workspace to use China-friendly mirrors."
    )
    parser.add_argument(
        "--packaging-repo",
        required=True,
        help="Path to the prepared ungoogled-chromium-portablelinux repo.",
    )
    return parser.parse_args()


def patch_dockerfile(path: Path, include_npm: bool) -> None:
    text = path.read_text(encoding="utf-8")
    text = text.replace("FROM debian:trixie-slim\n", f"FROM {DOCKER_DEBIAN_IMAGE}\n", 1)
    if "mirrors.tuna.tsinghua.edu.cn/debian" not in text:
        text = text.replace(
            f"FROM {DOCKER_DEBIAN_IMAGE}\n",
            f"FROM {DOCKER_DEBIAN_IMAGE}\n\n"
            "RUN sed -i "
            "'s|https\\?://deb.debian.org/debian|"
            f"{DEBIAN_MIRROR}"
            "|g; "
            "s|https\\?://security.debian.org/debian-security|"
            f"{DEBIAN_SECURITY_MIRROR}"
            "|g' /etc/apt/sources.list.d/debian.sources\n",
            1,
        )
    if include_npm and "registry.npmmirror.com" not in text:
        text = text.replace(
            "RUN apt-get -y update && apt-get -y install nodejs && npm update -g npm\n",
            "RUN apt-get -y update && apt-get -y install nodejs && "
            f"npm config set registry {NPM_MIRROR} && npm update -g npm\n",
            1,
        )
    path.write_text(text, encoding="utf-8")


def patch_bindgen_cargo_mirror(packaging_repo: Path) -> None:
    patch_path = (
        packaging_repo
        / "patches"
        / "netlops"
        / "chromium"
        / "025-bindgen-force-sparse-crates-io.patch"
    )
    if not patch_path.is_file():
        return
    text = patch_path.read_text(encoding="utf-8")
    text = text.replace(
        '+registry = "sparse+https://index.crates.io/"',
        f'+registry = "{CARGO_MIRROR}"',
    )
    text = text.replace('+git-fetch-with-cli = true', '+git-fetch-with-cli = false')
    patch_path.write_text(text, encoding="utf-8")


def patch_toolchain_git_mirrors(packaging_repo: Path) -> None:
    shared_path = packaging_repo / "scripts" / "shared.sh"
    if not shared_path.is_file():
        return
    text = shared_path.read_text(encoding="utf-8")
    if "FK_LLVM_GIT_URL" in text:
        return
    needle = (
        "    sed -i 's/chromium.9oo91esource.qjz9zk/chromium.googlesource.com/g' \\\n"
        '        "${_src_dir}/tools/clang/scripts/build.py" \\\n'
        '        "${_src_dir}/tools/rust/build_rust.py" \\\n'
        '        "${_src_dir}/tools/rust/build_bindgen.py"\n'
    )
    replacement = (
        needle
        + "\n"
        + '    local llvm_git_url="${FK_LLVM_GIT_URL:-'
        + LLVM_GIT_URL
        + '}"\n'
        + '    if [ -n "${llvm_git_url}" ]; then\n'
        + '        sed -i "s|https://chromium.googlesource.com/external/github.com/llvm/llvm-project|${llvm_git_url}|g" \\\n'
        + '            "${_src_dir}/tools/clang/scripts/build.py"\n'
        + "    fi\n"
    )
    if needle not in text:
        raise RuntimeError(f"could not find toolchain mirror insertion point in {shared_path}")
    shared_path.write_text(text.replace(needle, replacement, 1), encoding="utf-8")


def main() -> int:
    args = parse_args()
    packaging_repo = Path(args.packaging_repo).expanduser().resolve()
    if not packaging_repo.is_dir():
        raise SystemExit(f"missing packaging repo: {packaging_repo}")

    patch_dockerfile(packaging_repo / "docker" / "build.Dockerfile", include_npm=True)
    patch_dockerfile(packaging_repo / "docker" / "package.Dockerfile", include_npm=False)
    patch_bindgen_cargo_mirror(packaging_repo)
    patch_toolchain_git_mirrors(packaging_repo)
    print(f"[OK] configured Linux Docker mirrors for: {packaging_repo}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
