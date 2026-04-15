# Assets Repo

`fingerprint-kernel-assets` 负责保存“发布索引”，不负责承载 Chromium 大文件源码或构建缓存。

推荐职责：

- 保存每个内核版本的 `manifest.json`
- 保存 release metadata
- 保存 `.dmg` / `.zip` / `.pkg` 的校验和
- 保存 notarization 说明和 ticket 记录
- 记录 GitHub Actions run、commit、来源仓库

不建议直接提交：

- `Chromium.app`
- 大体积 `.dmg` / `.zip`
- build cache
- 原始超大 `build.log`

推荐做法：

1. 大文件放 GitHub Releases 或制品仓
2. 这个仓库只跟踪小体积 metadata 和 checksums

## 当前本地路径

- `/Users/netlops/Documents/ai/github/fingerprint-kernel-assets`

## 标准归档命令

```bash
cd /Users/netlops/Documents/ai/github/fingerprint-kernel-build
python3 scripts/archive_to_assets_repo.py \
  --manifest manifests/current.json \
  --run-id 24451150534 \
  --assets-repo /Users/netlops/Documents/ai/github/fingerprint-kernel-assets \
  --commit
```

## 一把梭

```bash
cd /Users/netlops/Documents/ai/github/fingerprint-kernel-build
python3 scripts/run_build.py \
  --manifest manifests/current.json \
  --install \
  --set-default \
  --replace-existing \
  --archive-assets \
  --assets-repo /Users/netlops/Documents/ai/github/fingerprint-kernel-assets \
  --archive-commit
```
