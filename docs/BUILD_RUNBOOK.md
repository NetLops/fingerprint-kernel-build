# Build Runbook

## 输入

- `manifests/current.json`
- `patches/packaging`
- `patches/chromium`
- `patches/product`

## 输出

- `artifacts/Chromium.app`
- `logs/build-*.log`

## 标准步骤

1. checkout packaging repo 到目标 tag
2. 应用 `packaging` patch queue
3. 把 `chromium` / `product` patch queue 注入 packaging repo 的 `patches/series`
4. 拉 Chromium 源码
5. 执行上游 `./build.sh arm64`
6. 构建 `Chromium.app`
7. 运行冒烟检查
8. 签名 / 公证

## 注意

- 所有失败日志都落到 `logs/`
- 不要把证书提交进 git
- patch 冲突修复后及时回写 patch queue
- CI 构建时要隔离 runner 的全局 Cargo 配置，避免继承 `~/.cargo/config.toml` 里的私有镜像或 `replace-with`

## 自动化入口

- 本地 / CI 统一先跑：
  - `python3 scripts/prepare_build_context.py --manifest manifests/current.json`
- GitHub Actions 手动触发：
  - `.github/workflows/build-mac-arm64.yml`
  - `.github/workflows/build-linux-arm64.yml`
- 懒人一键入口：
  - `python3 scripts/run_build.py --manifest manifests/current.json --install --set-default --replace-existing`
  - 如果成功后本地工作区没有现成 `Chromium.app`，脚本会自动下载当前 GitHub run 的 artifact，并尝试从 `.zip` / `.dmg` 里提取可安装的 `Chromium.app`
  - 如果还要同步 release metadata 到 `fingerprint-kernel-assets`，追加：
    - `--archive-assets --assets-repo /Users/netlops/Documents/ai/github/fingerprint-kernel-assets --archive-commit`
- runner 出现多条 `FAILED: [code=137]` 时，按内存压力处理，重新触发 workflow 并把 `ninja_jobs` 降低，例如 `ninja_jobs=6`
- 后台安装后验收：
  - `python3 scripts/post_build_verify.py --run-id <gh-run-id> --core-path chrome/chromium-<version>`
- 归档 release metadata：
  - `python3 scripts/archive_to_assets_repo.py --manifest manifests/current.json --run-id <gh-run-id> --assets-repo /Users/netlops/Documents/ai/github/fingerprint-kernel-assets --commit`

## Linux And Windows 146

当前跨平台内核固定跟随本机常用 146 线：

- Chromium: `146.0.7680.177`
- Ungoogled portablelinux tag: `146.0.7680.177-1`
- Ungoogled windows tag: `146.0.7680.177-1.1`
- Kernel revision: `fk.3`
- Linux ARM64 manifest: `manifests/current-linux-arm64.json`
- Linux AMD64 manifest: `manifests/current-linux-amd64.json`
- Windows AMD64 manifest: `manifests/current-windows-amd64.json`

触发 Linux ARM64 构建：

```bash
export CNB_TOKEN=$(awk '$1=="machine" && $2=="cnb.cool"{found=1; next} found && $1=="machine"{found=0} found && $1=="password"{print $2; exit}' ~/.netrc)
curl --http1.1 -sS -X POST \
  -H "Authorization: Bearer $CNB_TOKEN" \
  -H 'accept: application/json' \
  -H 'content-type: application/json' \
  'https://api.cnb.cool/shunleite/fingerprint-kernel-build/-/build/start' \
  -d '{"branch":"main","event":"api_trigger_linux_arm64","sync":false}'
```

触发 Linux AMD64 构建：

```bash
export CNB_TOKEN=$(awk '$1=="machine" && $2=="cnb.cool"{found=1; next} found && $1=="machine"{found=0} found && $1=="password"{print $2; exit}' ~/.netrc)
curl --http1.1 -sS -X POST \
  -H "Authorization: Bearer $CNB_TOKEN" \
  -H 'accept: application/json' \
  -H 'content-type: application/json' \
  'https://api.cnb.cool/shunleite/fingerprint-kernel-build/-/build/start' \
  -d '{"branch":"main","event":"api_trigger_linux_amd64","sync":false}'
```

触发 Windows AMD64 构建：

```bash
gh workflow run build-windows-amd64.yml \
  -R NetLops/fingerprint-kernel-build \
  --ref <branch> \
  -f manifest_path=manifests/current-windows-amd64.json \
  -f dry_run=false \
  -f ninja_jobs=16 \
  -f windows_build_mode=release \
  -f runs_on_json='["self-hosted","Windows","X64","fingerprint-kernel-build"]' \
  -f build_timeout_hours=11
```

Linux workflow 会先 checkout `ungoogled-chromium-portablelinux`，跳过 mac 专用
packaging patch queue，再把 `patches/chromium` 和 `patches/product` 注入
portablelinux 的 `patches/series`。Windows workflow 会 checkout
`ungoogled-chromium-windows`，同样注入 fingerprint patch queue。产物是：

- `ungoogled-chromium-*-arm64.AppImage`
- `ungoogled-chromium-*-arm64.AppImage.zsync`
- `ungoogled-chromium-*-arm64_linux.tar.xz`
- `ungoogled-chromium-*-x64.AppImage`
- `ungoogled-chromium-*-x64.AppImage.zsync`
- `ungoogled-chromium-*-x64_linux.tar.xz`
- `ungoogled-chromium_*_windows_x64.zip`
- `ungoogled-chromium_*_installer_x64.exe`

Linux 146/fk.3 已在 CNB.cool 通过；产物见：

- `https://cnb.cool/shunleite/fingerprint-kernel-build/-/commit/a352ec3e859ae055cad87e06ecb7dd451ca34b8e?tab=attachments`

Windows 146/fk.3 在普通 GitHub-hosted `windows-2022` 上不可行：

- `25129319044`: release `-j8`，约 330 分钟到 `[22384/56754]` 后 watchdog 停止。
- `25142149448`: chrome-only smoke `-j8`，约 330 分钟到 `[22366/56604]` 后停止。
- `25159317309`: hosted-fast-release `-j8`，约 330 分钟到 `[22302/56646]` 后停止。

这不是源码错误，而是 runner 算力/时限问题。下一步必须接入更大规格或自建
Windows x64 runner；CNB 官方 Linux runner 不能替代 Windows/MSVC 原生构建。

## 最低验收

- `scripts/render_upgrade_plan.py --manifest manifests/current.json` 能正常输出
- `scripts/apply_patch_series.py --check` 能检查 patch queue
- 产物 `Chromium.app` 存在
- `scripts/run_smoke_checks.py --app /path/to/Chromium.app` 能识别 `arm64`
- 正式分发时额外通过 `codesign` / notarization
