把当前要构建的 `kernel-manifest.json` 放到这里，推荐命名：

- `current.json`
- `current-linux-arm64.json`
- `current-linux-amd64.json`
- `current-windows-amd64.json`
- `147.0.7727.56-fk.1.json`

mac arm64 CI / 本地脚本默认优先读取 `manifests/current.json`。
Linux workflow 默认读取 `manifests/current-linux-arm64.json`，也可用
`current-linux-amd64.json` 配合 `arch=x64`。Windows AMD64 使用
`current-windows-amd64.json`。这些平台当前都固定在 `146.0.7680.177-fk.3`
这条常用 146 线。
