这里放当前私有构建仓库实际使用的 patch queue。

建议直接从 Ant Browser 工作区同步：

- `patches/packaging`
- `patches/chromium`
- `patches/product`

参考：

- `tools/fingerprint-kernel/PATCH_QUEUE_TEMPLATE.md`
- `tools/fingerprint-kernel/UPGRADE_CHECKLIST.md`

当前首批已落地的 `chromium` patch：

- `010-core-fingerprint-overrides.patch`
  - 启动开关透传
  - `navigator.platform`
  - `hardwareConcurrency`
  - `deviceMemory`
  - `screen.colorDepth`
  - `timezone`
  - `webdriver`
  - UA 平台 / 品牌后缀
- `020-user-agent-metadata-overrides.patch`
  - `navigator.userAgentData`
  - `Sec-CH-UA*` / Client Hints 元数据
