# hub — 桌面端

抖音 / 小红书两个页面的桌面工作台。tkinter 单窗口，页面按需加载，
**零第三方依赖**（只有抖音自动同步需要可选的 `websockets`）。

## 运行

```powershell
python hub\hub.py                       # 默认抖音
python hub\hub.py --page xhs            # 直接进小红书
python hub\hub.py --root D:\path\to\vault
python hub\hub.py --selftest            # 构建两个页面后退出
```

数据仓库定位顺序：`--root` > 环境变量 `HUB_ROOT` > 从程序目录向上找 `notes/kb/` > 当前目录。
本版本只读 `data/hub/douyin` 与 `data/hub/xhs`，不需要 `notes/`。

打包后的 `hub.exe` 同理：把 `dist\hub` 整个目录放进数据仓库根目录（或设 `HUB_ROOT`）即可。

## 抖音页

- 多账号：融合视图 + 每号一个 tab；单个号时平铺；
- 登录：专用浏览器扫码，登录态加密后按机器分片保存；
- 自动同步：默认每天 09:10，Windows 计划任务可改；
- 手动导入后台导出的作品/趋势 Excel 兜底；
- 指标卡、每日播放、Top 作品、账号概况、作品明细（排序/搜索/双击详情）。

## 小红书页

- 多账号：切换或融合，概览 / 明细两屏；
- 登录：扫码一次，登录态加密后按机器分片保存；
- 自动导出：后台 5 张表（笔记 / 观看 / 互动 / 涨粉 / 发布），默认每天 09:00；
- 手动导入导出的 Excel；
- 指标卡、每日观看趋势、近 30 天指标、笔记明细。

## 数据

```
<vault>/data/hub/
├─ douyin/
│  ├─ accounts.json        绑定账号
│  ├─ <handle>.json        作品 / 每日趋势 / 概览 / 导入记录
│  ├─ auth.<主机名>.json   加密登录态（按号合并）
│  ├─ sync.key             本机同步密钥（不要公开）
│  └─ sync.json            自动同步配置
└─ xhs/
   ├─ accounts.json
   ├─ <handle>.json        笔记 / 每日趋势 / 近 30 天指标
   ├─ auth.<主机名>.json
   ├─ sync.key
   └─ sync.json
```

隐私模式默认开：账号昵称、抖音号、小红书号、手机号、邮箱打码；只改显示，不动数据。
开关按机器分片存 `data/hub/privacy.<主机名>.json`。

## 命令行

```powershell
python hub\hub.py --douyin-sync     # 抖音同步，无窗口
python hub\hub.py --xhs-sync        # 小红书导出，无窗口
python hub\hub.py --daily-sync      # 两个一起跑（计划任务用）
python hub\hub.py --douyin-login    # 命令行扫码登录
python hub\hub.py --xhs-login
```

## 构建

```powershell
pip install pyinstaller
powershell -ExecutionPolicy Bypass -File hub\build.ps1
```

产物在 `dist\hub\`：`hub.exe` + `.hub\` 运行时目录。
不要只拷贝 exe；`.hub\` 必须一起带着。

## 平台与边界

- 面向 Windows：计划任务走 Windows「任务计划程序」；
- 抖音/小红书自动同步依赖本机 Chrome/Edge 与 CDP；
- 不登录、不同步时，hub 完全离线可用。
