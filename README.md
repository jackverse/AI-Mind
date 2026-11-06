# AI-Mind

抖音 / 小红书数据工作台：桌面端（hub）、浏览器/手机版（hub-web）、Android 客户端。

**这个仓库是代码与发版仓库，不放数据。** 抖音 / 小红书的账号、作品、笔记数据都在你自己的数据仓库
（`data/hub/douyin`、`data/hub/xhs`）里，用 `--root` / `HUB_ROOT` 指过去；本仓库只提交源码、脚本和说明。

```
AI-Mind/
├─ hub/           桌面端（Python + tkinter）
├─ hub-web/       浏览器版（标准库 HTTP 服务，可导出静态快照）
├─ android-app/   Android 客户端（WebView 壳，只读拉取）
├─ .gitignore     数据 / 构建产物黑名单
└─ README.md
```

## 下载 v1.0.0

- **Windows 桌面端**：[hub-v1.0.0-win64.zip](releases/v1.0.0/hub-v1.0.0-win64.zip)（解压后运行 `hub\hub.exe`）
- **Android**：[hub-android-v1.0.0.apk](releases/v1.0.0/hub-android-v1.0.0.apk)（无内置数据，首次打开后在 ⚙ 填仓库和 Token）

## 快速开始

要求：Windows、Python 3.10+（自带 tkinter）。

```powershell
# 指向数据仓库
python hub\hub.py --root D:\path\to\vault

# 或设环境变量，之后直接运行
$env:HUB_ROOT = "D:\path\to\vault"
python hub\hub.py
```

浏览器版：

```powershell
python hub-web\server.py --root D:\path\to\vault --open
# 手机同 Wi-Fi：--host 0.0.0.0
```

## 只做两个模块

| 模块 | 桌面 | 网页 | Android |
|---|---|---|---|
| 抖音 | 登录 / 账号 / 自动同步 / 导入 / 图表 / 明细 | 账号概览与作品明细 | 只读查看 |
| 小红书 | 登录 / 账号 / 自动导出 / 导入 / 指标 / 明细 | 账号概览与笔记明细 | 只读查看 |

不包含笔记、刷题、健身、时间线、买房、账单、欧路、邮件等其他模块。

## 数据与隐私

```
<数据仓库>/
└─ data/
   └─ hub/
      ├─ douyin/    accounts.json + <handle>.json + auth.<机器>.json
      └─ xhs/       accounts.json + <handle>.json + auth.<机器>.json
```

- `.gitignore` 忽略 `notes/`、`data/`、`dist/`、日志、`auth.*`、`sync.key`、`mail.json`、APK/exe；
  数据仓库可以自己决定哪些数据进 git，但**不要提交到本仓库**。
- 桌面端「隐私模式」默认开启：账号昵称、抖音号、小红书号、手机号、邮箱打码展示；只改显示，不改数据。
- 登录态用本机密钥加密；`sync.key` 只留在数据仓库本机，丢了重新扫码。
- Android 只读：不回写远程，Token 只存在 App 私有目录。

## 构建

```powershell
# 桌面端：产物 dist\hub\（放进数据仓库根目录即可运行）
powershell -ExecutionPolicy Bypass -File hub\build.ps1

# Android：产物 dist\hub-android.apk
powershell -ExecutionPolicy Bypass -File android-app\build.ps1
# 可选：把数据仓库的抖音/小红书数据打进 APK 内置快照（产物不要提交）
powershell -ExecutionPolicy Bypass -File android-app\build.ps1 -VaultRoot D:\path\to\vault
```

桌面端打包需要 `pip install pyinstaller`；Android 需要 JDK 17+、Android SDK（build-tools + platform）。
抖音自动同步需要可选的 `pip install websockets`，其余功能只用标准库。
