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

## 自动化入口

- 本地 / CI 统一先跑：
  - `python3 scripts/prepare_build_context.py --manifest manifests/current.json`
- GitHub Actions 手动触发：
  - `.github/workflows/build-mac-arm64.yml`

## 最低验收

- `scripts/render_upgrade_plan.py --manifest manifests/current.json` 能正常输出
- `scripts/apply_patch_series.py --check` 能检查 patch queue
- 产物 `Chromium.app` 存在
- `scripts/run_smoke_checks.py --app /path/to/Chromium.app` 能识别 `arm64`
- 正式分发时额外通过 `codesign` / notarization
