# Repo Setup

这个仓库建议只负责一件事：

- 读取 `manifests/current.json`
- 应用 patch queue
- 构建、签名、公证 mac arm64 指纹内核

## 当前仓库地址

- Build repo:
  - `https://github.com/NetLops/fingerprint-kernel-build.git`
- Ant Browser fork:
  - `https://github.com/NetLops/Ant-Browser`
- Ant Browser upstream:
  - `https://github.com/black-ant/Ant-Browser`

## 推荐关联仓库

最小只需要两个仓库：

1. `Ant-Browser`
2. `fingerprint-kernel-build`

可选第三个：

3. `fingerprint-kernel-assets`
   - 只存归档产物、校验和、notarization 记录

## 当前本地目录

```text
/Users/netlops/Documents/ai/github/
  Ant-Browser/
  fingerprint-kernel-build/
```

## 初始化顺序

1. 在 `Ant-Browser` 里生成新版本工作区
2. 把 `kernel-manifest.json` 复制到本仓 `manifests/current.json`
3. 把 patch queue 放进本仓 `patches/`
4. 本地跑一遍脚本校验
5. 再接 GitHub Actions / 自建 runner / 签名

## 适合你现在直接执行的命令

### 1. 给本地 Ant-Browser 加一个 fork remote

你当前本地 `Ant-Browser` 的 `origin` 还是官方仓库。

为了不打断现有工作流，建议只新增一个 `fork` remote：

```bash
git -C /Users/netlops/Documents/ai/github/Ant-Browser remote add fork https://github.com/NetLops/Ant-Browser.git
git -C /Users/netlops/Documents/ai/github/Ant-Browser remote -v
```

这样后面可以：

- 从 `origin` 拉官方
- 往 `fork` 推你们自己的分支

### 2. 在 Ant-Browser 里生成第一版工作区

```bash
cd /Users/netlops/Documents/ai/github/Ant-Browser
python3 tools/fingerprint-kernel/create-workspace.py \
  --version 147.0.7727.56 \
  --ungoogled-tag 147.0.7727.56-1 \
  --workspace-root /Users/netlops/Documents/ai/github/fingerprint-kernel-build/work/147.0.7727.56-fk.1-mac-arm64
```

### 3. 把 manifest 放进当前 build 仓

```bash
cp /Users/netlops/Documents/ai/github/fingerprint-kernel-build/work/147.0.7727.56-fk.1-mac-arm64/kernel-manifest.json \
  /Users/netlops/Documents/ai/github/fingerprint-kernel-build/manifests/current.json
```

### 4. 本地先跑一次体检

```bash
cd /Users/netlops/Documents/ai/github/fingerprint-kernel-build
python3 -m py_compile scripts/*.py
python3 scripts/render_upgrade_plan.py --manifest manifests/current.json
```

## 建议本地目录

```text
~/github/
  Ant-Browser/
  fingerprint-kernel-build/
```

## 建议 Git 远程关系

如果 `Ant-Browser` 是 fork 工作流，建议：

- `origin` 保持当前官方仓库也可以
- 新增 `fork` 指向你们自己的 fork

这样后面同步主仓更省事。
