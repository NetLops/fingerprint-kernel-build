# fingerprint-kernel-build

这是 NetLops 自建 mac arm64 指纹内核的私有构建仓。

设计目标：

- 不把大体积 Chromium 源码塞进 Ant Browser 仓库
- 让私有构建仓库有一致的目录和脚本入口
- 能直接读取 `kernel-manifest.json`
- 能统一应用 patch queue、做冒烟检查、沉淀构建日志

## 当前关联仓库

- Build repo:
  - [NetLops/fingerprint-kernel-build](https://github.com/NetLops/fingerprint-kernel-build.git)
- Source fork:
  - [NetLops/Ant-Browser](https://github.com/NetLops/Ant-Browser)

本地对应目录：

- `/Users/netlops/Documents/ai/github/fingerprint-kernel-build`
- `/Users/netlops/Documents/ai/github/Ant-Browser`

## 建议目录

```text
fingerprint-kernel-build/
  .github/workflows/
  docs/
  manifests/
  patches/
    packaging/
    chromium/
    product/
  scripts/
  signing/
  logs/
  artifacts/
```

## 推荐使用方式

先在 Ant Browser 仓库里生成工作区：

```bash
python3 tools/fingerprint-kernel/create-workspace.py \
  --version 147.0.7727.56 \
  --ungoogled-tag 147.0.7727.56-1
```

这个仓库已经完成 skeleton 初始化。

如果后面要重建，可以从 `Ant-Browser` 里执行：

```bash
python3 tools/fingerprint-kernel/bootstrap-build-repo.py \
  --target /Users/netlops/Documents/ai/github/fingerprint-kernel-build
```

然后把 `kernel-manifest.json` 放进：

- `manifests/current.json`

接下来在这个仓库里做：

1. clone packaging repo
2. checkout 目标 tag
3. 用 `scripts/apply_patch_series.py` 依次应用 patch
4. 构建 `Chromium.app`
5. 用 `scripts/run_smoke_checks.py` 做产物冒烟
6. 完成签名、公证、发布

## 当前工作流用法

正式构建 workflow：

- `.github/workflows/build-mac-arm64.yml`

默认是 `dry_run=true`，只做这些动作：

1. 校验脚本
2. 渲染升级计划
3. 同步 `patches/`
4. checkout `ungoogled-chromium-macos`
5. 应用 `packaging` patch
6. 把 `chromium/product` patch 注入 packaging repo 的 `patches/series`

确认自建 runner、patch queue、签名环境都准备好后，再把 `dry_run` 切成 `false` 触发真实编译。

如果你想一把梭，直接用：

```bash
cd /Users/netlops/Documents/ai/github/fingerprint-kernel-build
python3 scripts/run_build.py \
  --manifest manifests/current.json \
  --install \
  --set-default \
  --replace-existing
```

它会自动：

1. dispatch GitHub Actions 构建
2. watch 当前 run 到结束
3. 成功后把 `Chromium.app` 装进本机 Ant Browser

如果 workflow 已经在跑，也可以直接接管现有 run：

```bash
python3 scripts/run_build.py \
  --manifest manifests/current.json \
  --existing-run-id 24448462058 \
  --install \
  --set-default \
  --replace-existing
```

## 这个 skeleton 已经带了什么

- `scripts/apply_patch_series.py`
- `scripts/prepare_build_context.py`
- `scripts/render_upgrade_plan.py`
- `scripts/run_smoke_checks.py`
- `scripts/run_build.py`
- `docs/BUILD_RUNBOOK.md`
- `docs/REPO_SETUP.md`
- `docs/GITHUB_SECRETS.md`
- `.github/workflows/repo-smoke.yml`
- `.github/workflows/build-mac-arm64.yml`
- `.github/workflows/build-mac-arm64.yml.example`

其中：

- `repo-smoke.yml` 可以直接作为仓库基础体检工作流
- `build-mac-arm64.yml` 会在自建 `macOS ARM64` runner 上执行真实构建
- `build-mac-arm64.yml.example` 保留作额外实验模板

## 和 Ant Browser 仓库的关系

Ant Browser 仓库负责：

- 文档
- 工作区 manifest 生成
- patch queue 模板
- 把构建产物安装进 Ant Browser

私有构建仓库负责：

- 真正的源码拉取
- patch 应用
- 构建
- 签名 / 公证
- 发布制品

## 推荐下一步

1. 看 [docs/REPO_SETUP.md](docs/REPO_SETUP.md) 跑一遍 NetLops 本地初始化
2. 在 `Ant-Browser` 里生成第一版 `kernel-manifest.json`
3. 把 `manifests/current.json` 和 patch queue 补进来
4. 按 [docs/GITHUB_SECRETS.md](docs/GITHUB_SECRETS.md) 配 GitHub Secrets
5. 先跑 `repo-smoke`，再接入正式构建 workflow
