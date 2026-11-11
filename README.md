# AI-Mind

个人第二大脑的工具端：Windows 桌面端（hub）+ Android 手机 App（APK）。
抖音 / 小红书的数据工作台、笔记、刷题、健身、时间线等页面都在桌面端里；手机端是同一套页面的离线壳。

**两个仓库同步发版，内容一样：**

- GitHub：<https://github.com/jackverse/AI-Mind>
- Gitee：<https://gitee.com/jacktianxz/ai-mind>

Release 目前只发两个产物：**Windows 桌面端（hub.exe 压缩包）** 和 **Android 手机 APK**。
手表版暂时不发。

## 功能

**桌面端（15 页）**

| 模块 | 能做什么 |
|---|---|
| 抖音 | 多账号登录、作品明细、每日趋势、粉丝数据、自动同步 |
| 小红书 | 多账号、笔记明细、近 30 天观看 / 互动 / 涨粉、自动导出 |
| 笔记 | 目录树浏览全部 Markdown、搜索 |
| 刷题 / 错题本 / 统计 | 题库测验、错题重练、正确率与掌握度 |
| 健身 | 从日报派生打卡率、体重变化、训练统计 |
| 时间线 | 按日期倒序回看在干嘛 |
| 买房 | 多房源跟踪、首付 / 月供 / 利息方案对比 |
| 账单 | 支付宝 / 微信账单导入、月度统计 |
| 欧路 | 多账号生词与学习记录 |
| 邮件 | 从 TODO / 日报生成提醒并发送 |
| 收集箱 | 文件丢进来自动识别、分类入库 |
| 设置 | 隐私脱敏、模块管理、数据路径 |

**手机端（Android）**：首页、笔记、健身、时间线、对话、抖音、小红书、账单、刷题、统计、「我的」（同步记录 / 设置）。
只读展示 + 刷题进度写回 + 分享文件进收集箱 + 应用内检查更新。

## 平台支持

| 平台 | 支持情况 |
|---|---|
| Windows | ✅ Windows 10 / 11 64 位（x64），提供 exe；32 位系统不支持 |
| Android | ✅ Android 8.0（API 26）及以上，提供手机 APK |
| macOS | ❌ 不支持，没有安装包 |
| iOS | ❌ 不支持 |
| 手表（OPPO Watch 等） | ❌ 暂未发布，当前 Release 不带手表包 |

> 现成安装包只有 Windows 和 Android 两个。

## 下载

| 产物 | GitHub | Gitee |
|---|---|---|
| Windows 桌面端 | [最新 Release](https://github.com/jackverse/AI-Mind/releases/latest) | [最新 Release](https://gitee.com/jacktianxz/ai-mind/releases/latest) |
| Android 手机 APK | [hub-android.apk](https://github.com/jackverse/AI-Mind/releases/latest/download/hub-android.apk) | [Gitee Release 页](https://gitee.com/jacktianxz/ai-mind/releases) |

版本号从 `0.0.1` 开始，之后按 `0.0.2`、`0.0.3` 慢慢加。

## 这个仓库不放数据

- 仓库里只有源码、构建脚本和版本清单；`notes/`、`data/`、登录态、导出的表格、网页快照一律不进 git。
- 安装包也不带内置数据：APK 首次打开是空的，桌面端要自己指定数据目录。
- 数据放你自己的私有仓库（或本地目录），工具只负责读写。

## 桌面端

解压 `hub-v*-win64.zip`，双击 `hub.exe`。第一次用需要把数据目录指过去：

```powershell
hub.exe --root D:\path\to\your-vault
```

或者设环境变量：

```powershell
$env:HUB_ROOT = "D:\path\to\your-vault"
hub.exe
```

数据目录约定（没有就自动建）：

```
<数据目录>/
├─ notes/        笔记、对话、题库
└─ data/hub/     抖音、小红书、账单、房源等业务数据
```

源码方式运行：

```powershell
python tools\hub\hub.py --root D:\path\to\your-vault
```

## 手机端

装 `hub-android.apk`，打开后点底部「我的」：

1. **数据仓库**：填你自己的 `owner/repo`（私有仓库就再填一个有 `repo` 权限的 Token）；
2. 点顶部 ☁ 同步，把笔记和数据拉到手机上；
3. 更新检查固定读公开仓库 `jackverse/AI-Mind` 的 `version.json`，和你的数据仓库无关。

手机端只读展示，不同步回写笔记。包名 `com.jackverse.secondbrain`，调试签名，只能自装，不能上架。

## 构建

要求：Windows、Python 3.10+（自带 tkinter）、PyInstaller；打 APK 还要 JDK 17+ 和 Android SDK（`ANDROID_HOME`）。

```powershell
# 两个产物一起：hub.exe + hub-android.apk（APK 不带 seed）
powershell -ExecutionPolicy Bypass -File tools\build-all.ps1

# 只构建一个
... -Only exe
... -Only android
```

产物在仓库根：`hub.exe` + `.hub\`、`hub-android.apk`，以及自更新清单 `version.json`。

## 发版

```powershell
powershell -ExecutionPolicy Bypass -File tools\release.ps1 -Version 0.0.2 -Notes "这次改了什么"
```

脚本会：递增版本 → 重建 exe + 无 seed APK → 提交打 tag → 同时推 GitHub 和 Gitee →
在两个仓库各建一个 Release 并上传 `hub-vX.Y.Z-win64.zip`、`hub-android.apk`、`version.json`。

## 目录

```
tools/
├─ hub/          桌面端（Python + tkinter，页面自动发现）
├─ hub-web/      浏览器版 / 手机 WebView 前端
├─ android-app/  Android 壳（WebView + 本地仓库副本）
├─ build-all.ps1 构建两个产物
└─ release.ps1   发版到 GitHub + Gitee
```

## 许可

[MIT License](LICENSE)。**完全开源、不收费**：可商用、可私用、可修改、可分发，保留版权与许可声明即可。

## 赞助

项目完全免费、完全开放，没有付费版。如果它帮你省了时间，欢迎自愿打赏（不影响任何功能）：

| 微信支付 | 支付宝 |
|---|---|
| [![微信支付](docs/sponsor/wechat-280.jpg)](docs/sponsor/wechat.jpg) | [![支付宝](docs/sponsor/alipay-280.jpg)](docs/sponsor/alipay.jpg) |

> 点图片看原图。二维码只用于自愿打赏。

## 联系

微信：**jack9527xz**（欢迎咨询，产品长期迭代）

