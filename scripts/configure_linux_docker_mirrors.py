#!/usr/bin/env python3
import argparse
from pathlib import Path


DEBIAN_MIRROR = "http://mirrors.tuna.tsinghua.edu.cn/debian"
DEBIAN_SECURITY_MIRROR = "http://mirrors.tuna.tsinghua.edu.cn/debian-security"
DOCKER_DEBIAN_IMAGE = "docker.m.daocloud.io/library/debian:trixie-slim"
NPM_MIRROR = "https://registry.npmmirror.com"
CARGO_MIRROR = "sparse+https://rsproxy.cn/index/"


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


def main() -> int:
    args = parse_args()
    packaging_repo = Path(args.packaging_repo).expanduser().resolve()
    if not packaging_repo.is_dir():
        raise SystemExit(f"missing packaging repo: {packaging_repo}")

    patch_dockerfile(packaging_repo / "docker" / "build.Dockerfile", include_npm=True)
    patch_dockerfile(packaging_repo / "docker" / "package.Dockerfile", include_npm=False)
    patch_bindgen_cargo_mirror(packaging_repo)
    print(f"[OK] configured Linux Docker mirrors for: {packaging_repo}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
