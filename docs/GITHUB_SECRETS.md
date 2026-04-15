# GitHub Secrets Checklist

如果你们要把签名、公证接进 GitHub Actions，建议至少准备这些 secrets：

## 签名证书

- `MAC_CERT_P12_BASE64`
  - 导出的 `.p12` 证书，转成 base64 后保存
- `MAC_CERT_PASSWORD`
  - `.p12` 的密码
- `MAC_KEYCHAIN_PASSWORD`
  - Actions 临时 keychain 密码

## Apple Notarization

两种方式选一种即可。

### 方式 A：Apple ID

- `APPLE_ID`
- `APPLE_APP_PASSWORD`
- `APPLE_TEAM_ID`

### 方式 B：App Store Connect API Key

- `APPLE_API_KEY_ID`
- `APPLE_API_ISSUER_ID`
- `APPLE_API_PRIVATE_KEY`
- `APPLE_TEAM_ID`

## 可选

- `BUILD_BOT_PAT`
  - 如果你们后面要拉私有依赖、私有 patch 仓、私有 release 资产
  - 如果你们后面要自动往 `fingerprint-kernel-assets` 的 GitHub Releases 上传 `.zip` / `.dmg`，也可以复用这类 PAT

## Runner 要求

正式 `build-mac-arm64` workflow 默认跑在自建 runner：

- `self-hosted`
- `macOS`
- `ARM64`

建议 runner 预装：

- Xcode
- Homebrew
- `greadlink`
- `ninja`
- `node`
- Python 3

## 注意

- 不要把 `.p12`、私钥、密码提交到仓库
- 正式接入前先本地手跑一次 `codesign` / `notarytool`
- 构建 Chromium 更适合自建 mac runner，GitHub Hosted Runner 更适合跑校验和轻量任务
