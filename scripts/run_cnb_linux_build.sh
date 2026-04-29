#!/usr/bin/env bash
set -Eeuo pipefail

usage() {
    cat <<'USAGE'
Usage:
  run_cnb_linux_build.sh --manifest <path> --arch <arm64|x64> --output-name <name> [--phase <phase>]

Environment:
  FK_CNB_USE_MIRRORS=true|false              Patch generated Linux Dockerfiles for China mirrors.
  FK_CNB_DOCKER_CPUS=<number>                CPU limit for the inner portablelinux build container.
  FK_CNB_NINJA_TASK_TIMEOUT_SECONDS=<secs>   Timeout for portablelinux ninja step.
  FK_CNB_PREPARE_ONLY=true|false             Stop after preparing the build tree.

Phases:
  all           Prepare, build, package, and smoke check.
  prepare       Prepare the portablelinux build tree.
  build-slice   Run one resumable ninja slice.
  build-final   Run the final ninja slice and fail if still incomplete.
  package       Package and smoke check completed outputs.
USAGE
}

MANIFEST=""
TARGET_ARCH=""
OUTPUT_NAME=""
PHASE="all"

while [ "$#" -gt 0 ]; do
    case "$1" in
        --manifest)
            MANIFEST="${2:-}"
            shift 2
            ;;
        --arch)
            TARGET_ARCH="${2:-}"
            shift 2
            ;;
        --output-name)
            OUTPUT_NAME="${2:-}"
            shift 2
            ;;
        --phase)
            PHASE="${2:-}"
            shift 2
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "[ERROR] unknown argument: $1" >&2
            usage >&2
            exit 2
            ;;
    esac
done

if [ -z "$MANIFEST" ] || [ -z "$TARGET_ARCH" ] || [ -z "$OUTPUT_NAME" ]; then
    usage >&2
    exit 2
fi

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

PUBLIC_ARTIFACT_DIR="$REPO_ROOT/artifacts/cnb/$OUTPUT_NAME"
PUBLIC_LOG_DIR="$REPO_ROOT/logs/cnb/$OUTPUT_NAME"
mkdir -p "$PUBLIC_ARTIFACT_DIR" "$PUBLIC_LOG_DIR"

install_missing_tools() {
    local missing=()
    local bin
    for bin in git python3 docker file tar xz sed grep tee; do
        if ! command -v "$bin" >/dev/null 2>&1; then
            missing+=("$bin")
        fi
    done
    if [ "${#missing[@]}" -eq 0 ]; then
        return 0
    fi
    echo "[WARN] missing tools: ${missing[*]}"
    if ! command -v apt-get >/dev/null 2>&1; then
        echo "[ERROR] apt-get is not available; cannot install missing tools" >&2
        return 1
    fi
    if [ "$(id -u)" -ne 0 ] && ! command -v sudo >/dev/null 2>&1; then
        echo "[ERROR] need root or sudo to install missing tools" >&2
        return 1
    fi

    local apt_prefix=()
    if [ "$(id -u)" -ne 0 ]; then
        apt_prefix=(sudo)
    fi

    if [ "${FK_CNB_USE_MIRRORS:-true}" != "false" ]; then
        if [ -f /etc/apt/sources.list.d/debian.sources ]; then
            "${apt_prefix[@]}" sed -i \
                's|https\?://deb.debian.org/debian|http://mirrors.tuna.tsinghua.edu.cn/debian|g; s|https\?://security.debian.org/debian-security|http://mirrors.tuna.tsinghua.edu.cn/debian-security|g' \
                /etc/apt/sources.list.d/debian.sources || true
        fi
        if [ -f /etc/apt/sources.list ]; then
            "${apt_prefix[@]}" sed -i \
                's|https\?://deb.debian.org/debian|http://mirrors.tuna.tsinghua.edu.cn/debian|g; s|https\?://security.debian.org/debian-security|http://mirrors.tuna.tsinghua.edu.cn/debian-security|g; s|https\?://archive.ubuntu.com/ubuntu|http://mirrors.tuna.tsinghua.edu.cn/ubuntu|g; s|https\?://security.ubuntu.com/ubuntu|http://mirrors.tuna.tsinghua.edu.cn/ubuntu|g' \
                /etc/apt/sources.list || true
        fi
    fi

    "${apt_prefix[@]}" apt-get update
    "${apt_prefix[@]}" apt-get install -y \
        ca-certificates git python3 docker.io file tar xz-utils sed grep coreutils
}

patch_portablelinux_helpers() {
    local packaging_repo="$1"
    local timeout_seconds="${FK_CNB_NINJA_TASK_TIMEOUT_SECONDS:-41400}"
    local docker_cpus="${FK_CNB_DOCKER_CPUS:-}"

    python3 - "$packaging_repo" "$timeout_seconds" "$docker_cpus" <<'PY'
from pathlib import Path
import sys

packaging_repo = Path(sys.argv[1])
timeout_seconds = sys.argv[2]
docker_cpus = sys.argv[3]

build_script = packaging_repo / ".github" / "scripts" / "build.sh"
text = build_script.read_text(encoding="utf-8")
old = "_task_timeout=18000"
new = f"_task_timeout={timeout_seconds}"
if old in text:
    text = text.replace(old, new, 1)
elif new not in text:
    raise SystemExit(f"could not find {old!r} in {build_script}")
build_script.write_text(text, encoding="utf-8")

if docker_cpus:
    docker_build = packaging_repo / "scripts" / "docker-build.sh"
    text = docker_build.read_text(encoding="utf-8")
    if "_docker_run_limits=()" not in text:
        text = text.replace(
            '_gha_mount=""\n',
            '_gha_mount=""\n'
            '_docker_run_limits=()\n'
            'if [ -n "${FK_DOCKER_CPUS:-}" ]; then\n'
            '    _docker_run_limits+=(--cpus "${FK_DOCKER_CPUS}")\n'
            'fi\n',
            1,
        )
        text = text.replace(
            'cd "${_base_dir}" && docker run --rm -i \\\n',
            'cd "${_base_dir}" && docker run --rm -i \\\n'
            '    "${_docker_run_limits[@]}" \\\n',
            1,
        )
        docker_build.write_text(text, encoding="utf-8")
PY
}

sync_outputs() {
    mkdir -p "$PUBLIC_ARTIFACT_DIR" "$PUBLIC_LOG_DIR"
    if [ -n "${FK_ARTIFACT_DIR:-}" ] && [ -d "$FK_ARTIFACT_DIR" ]; then
        cp -a "$FK_ARTIFACT_DIR"/. "$PUBLIC_ARTIFACT_DIR"/ 2>/dev/null || true
    fi
    if [ -n "${FK_LOGS_DIR:-}" ] && [ -d "$FK_LOGS_DIR" ]; then
        cp -a "$FK_LOGS_DIR"/. "$PUBLIC_LOG_DIR"/ 2>/dev/null || true
    fi
    if [ -n "${FK_PACKAGING_REPO_DIR:-}" ] && [ -d "$FK_PACKAGING_REPO_DIR/build/release" ]; then
        find "$FK_PACKAGING_REPO_DIR/build/release" -maxdepth 1 -type f -exec cp {} "$PUBLIC_ARTIFACT_DIR"/ \; || true
    fi
}

trap sync_outputs EXIT

release_arch_name() {
    case "$TARGET_ARCH" in
        x64|amd64|x86_64)
            echo "x86_64"
            ;;
        arm64|aarch64)
            echo "arm64"
            ;;
        *)
            echo "$TARGET_ARCH"
            ;;
    esac
}

GITHUB_ENV_FILE="$PUBLIC_LOG_DIR/github-env"
GITHUB_OUTPUT="$PUBLIC_LOG_DIR/github-output"

source_prepared_env() {
    if [ ! -f "$GITHUB_ENV_FILE" ]; then
        echo "[ERROR] missing prepared env file: $GITHUB_ENV_FILE" >&2
        echo "[ERROR] run --phase prepare first" >&2
        exit 1
    fi
    set -a
    # shellcheck disable=SC1090
    . "$GITHUB_ENV_FILE"
    set +a
}

prepare_tree() {
    install_missing_tools
    python3 -m py_compile scripts/*.py
    python3 scripts/render_upgrade_plan.py --manifest "$MANIFEST" | tee "$PUBLIC_LOG_DIR/upgrade-plan.log"

    rm -f "$GITHUB_ENV_FILE" "$GITHUB_OUTPUT"
    touch "$GITHUB_ENV_FILE" "$GITHUB_OUTPUT"
    export GITHUB_ENV="$GITHUB_ENV_FILE"

    python3 scripts/prepare_build_context.py --manifest "$MANIFEST" --repo-root "$REPO_ROOT" \
        2>&1 | tee "$PUBLIC_LOG_DIR/prepare-build-context.log"

    source_prepared_env

    if [ "${FK_CNB_USE_MIRRORS:-true}" != "false" ]; then
        python3 scripts/configure_linux_docker_mirrors.py --packaging-repo "$FK_PACKAGING_REPO_DIR" \
            2>&1 | tee "$PUBLIC_LOG_DIR/configure-linux-docker-mirrors.log"
    fi

    patch_portablelinux_helpers "$FK_PACKAGING_REPO_DIR"

    cd "$FK_PACKAGING_REPO_DIR"
    export ARCH="$TARGET_ARCH"
    export FK_DOCKER_CPUS="${FK_CNB_DOCKER_CPUS:-}"
    export CI=true
    export GITHUB_OUTPUT

    echo "[OK] CNB output: $OUTPUT_NAME"
    echo "[OK] target arch: $ARCH"
    echo "[OK] packaging repo: $FK_PACKAGING_REPO_DIR"
    echo "[OK] inner docker cpus: ${FK_DOCKER_CPUS:-unlimited}"
    echo "[OK] ninja timeout seconds: ${FK_CNB_NINJA_TASK_TIMEOUT_SECONDS:-41400}"

    export _prepare_only=true
    bash ./scripts/docker-build.sh 2>&1 | tee "$FK_LOGS_DIR/prepare-linux.log"
}

build_slice() {
    local final="$1"
    install_missing_tools
    rm -f "$GITHUB_OUTPUT"
    touch "$GITHUB_OUTPUT"
    source_prepared_env
    patch_portablelinux_helpers "$FK_PACKAGING_REPO_DIR"

    cd "$FK_PACKAGING_REPO_DIR"
    export ARCH="$TARGET_ARCH"
    export FK_DOCKER_CPUS="${FK_CNB_DOCKER_CPUS:-}"
    export CI=true
    export GITHUB_OUTPUT
    export _prepare_only=false
    export _use_existing_image=true
    export _gha_final="$final"

    echo "[OK] CNB build phase: final=$final"
    echo "[OK] target arch: $ARCH"
    echo "[OK] inner docker cpus: ${FK_DOCKER_CPUS:-unlimited}"
    echo "[OK] ninja timeout seconds: ${FK_CNB_NINJA_TASK_TIMEOUT_SECONDS:-41400}"
    bash ./scripts/docker-build.sh 2>&1 | tee -a "$FK_LOGS_DIR/build.log"
}

package_and_smoke() {
    install_missing_tools
    source_prepared_env
    cd "$FK_PACKAGING_REPO_DIR"

    bash ./package/docker-package.sh 2>&1 | tee "$FK_LOGS_DIR/package.log"
    mkdir -p "$FK_ARTIFACT_DIR"
    release_arch="$(release_arch_name)"
    cp -v build/release/ungoogled-chromium-*-"${release_arch}".AppImage* "$FK_ARTIFACT_DIR"/
    cp -v build/release/ungoogled-chromium-*-"${release_arch}"_linux.tar.xz "$FK_ARTIFACT_DIR"/

    cd "$REPO_ROOT"
    python3 scripts/run_linux_smoke_checks.py \
        --out-dir "$FK_PACKAGING_REPO_DIR/build/src/out/Default" \
        --release-dir "$FK_PACKAGING_REPO_DIR/build/release" \
        --target-arch "$TARGET_ARCH" \
        2>&1 | tee "$FK_LOGS_DIR/smoke-check.log"
}

case "$PHASE" in
    all)
        prepare_tree
        if [ "${FK_CNB_PREPARE_ONLY:-false}" = "true" ]; then
            echo "[OK] FK_CNB_PREPARE_ONLY=true; stopping before Chromium build"
            exit 0
        fi
        build_slice true
        package_and_smoke
        ;;
    prepare)
        prepare_tree
        ;;
    build-slice)
        build_slice false
        ;;
    build-final)
        build_slice true
        ;;
    package)
        package_and_smoke
        ;;
    *)
        echo "[ERROR] unknown phase: $PHASE" >&2
        usage >&2
        exit 2
        ;;
esac

sync_outputs
echo "[OK] CNB Linux phase complete: $OUTPUT_NAME / $PHASE"
