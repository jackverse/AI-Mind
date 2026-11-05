# AI-Mind

一个本地优先的个人知识库工具集：桌面 GUI（hub）、浏览器/手机版（hub-web）、Android 客户端。

**这个仓库只放代码与构建脚本，不放任何数据。** 笔记、日报、账号、账单、房源、登录态、Token、构建产物一律不进来；
数据都在你自己的数据仓库（任意包含 `notes/kb/` 的目录）里，用 `--root` / `HUB_ROOT` 指过去。

```
AI-Mind/
├─ hub/           桌面端（Python + tkinter，零第三方依赖）
├─ hub-web/       浏览器版（标准库 HTTP 服务，可导出静态快照）
├─ android-app/   Android 客户端（WebView 壳 + GitHub 同步，不依赖 Gradle）
├─ .gitignore     数据/产物黑名单
└─ README.md
```

## 快速开始

要求：Windows、Python 3.10+（自带 tkinter）。

```powershell
# 1. 指向你的数据仓库（含 notes/kb/）
python hub\hub.py --root D:\path\to\vault

# 或者设环境变量，之后直接运行
$env:HUB_ROOT = "D:\path\to\vault"
python hub\hub.py
```

不指定数据仓库也能启动：所有页面显示空状态，`data/` 会建在当前目录。

浏览器版：

```powershell
python hub-web\server.py --root D:\path\to\vault --open
# 手机同 Wi-Fi：--host 0.0.0.0
```

## 三个部分

| 目录 | 入口 | 说明 |
|---|---|---|
| `hub/` | `hub.py` | 14 个页面的桌面工具：笔记、刷题、错题本、统计、健身、时间线、买房、抖音、小红书、欧路、账单、邮件、设置；页面懒加载，隐私模式默认开 |
| `hub-web/` | `server.py` | 同一份数据的只读镜像 + 刷题写回；手机浏览器可用，支持导出静态 `bundle.json` |
| `android-app/` | `build.ps1` | 半离线 Android 客户端：首次可用内置快照，之后点 ☁ 跟 GitHub 仓库双向同步（只写 `review.json`） |

每个目录下的 README 有各自的细节。

## 数据与隐私

数据分两层，互不混：

```
<你的数据仓库>/
├─ notes/                 Markdown 笔记 + kb/<科目>/questions.jsonl
└─ data/
   ├─ hub/                业务数据（账号库、账单、房源、设置）
   └─ social/             采集浏览器 profile 等大文件（可选）
```

- 本仓库的 `.gitignore` 直接忽略 `notes/`、`data/`、`dist/`、日志与构建产物，误提交的概率降到最低。
- 桌面端的「隐私模式」只改**显示**，不改数据：账号昵称、抖音/小红书号、手机号、邮箱、公积金余额会打码；默认开启，侧栏底部可切换。
- 抖音/小红书的登录态用本机密钥加密后落在数据仓库；**是否提交由你自己决定**，公开仓库不要提交 `auth.*`、`sync.key`、`mail.json`。
- Android 的 Token 只存在 App 私有目录；APK 默认不内置任何数据，`-VaultRoot` 只在本机打包时读数据仓库。

## 构建

```powershell
# 桌面端：产物 dist\hub\（把整个目录放进数据仓库根目录即可运行）
powershell -ExecutionPolicy Bypass -File hub\build.ps1

# Android：产物 dist\hub-android.apk
powershell -ExecutionPolicy Bypass -File android-app\build.ps1
# 可选：把数据仓库打进 APK 内置快照（产物不要提交）
powershell -ExecutionPolicy Bypass -File android-app\build.ps1 -VaultRoot D:\path\to\vault
```

桌面端打包需要 `pip install pyinstaller`；Android 需要 JDK 17+、Android SDK（build-tools + platform）。
抖音自动同步还需要可选的 `pip install websockets`，其余功能只用标准库。

## 约定

- 数据仓库的 `notes/kb/<科目>/questions.jsonl` 一行一题，`review.json` 由刷题自动生成。
- `notes/daily-log.md` 与 `notes/index.md` 是健身/时间线页的数据源，格式见 `hub/README.md`。
- hub-web 只有刷题写回 `review.json`，其余页面只读。
