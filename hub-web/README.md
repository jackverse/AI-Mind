# hub-web — 浏览器 / 手机版

把抖音 / 小红书账号数据搬到浏览器：同一份数据仓库，手机连同一 Wi-Fi 就能看。

- 数据仓库 = 任意包含 `data/hub/douyin` 或 `data/hub/xhs` 的目录；**本仓库不含任何数据**
- 只读：不写账号数据，不做登录/同步/导入（那些在桌面 hub 做）
- 不是独立应用：启动时从 `../hub/` 复用 `core` 模块，代码必须和 `hub/` 放在同一仓库

## 运行

```powershell
python hub-web\server.py --root D:\path\to\vault --open
# 默认 127.0.0.1:8765

python hub-web\server.py --root D:\path\to\vault --host 0.0.0.0   # 手机同局域网
powershell -ExecutionPolicy Bypass -File hub-web\start.ps1 -Root D:\path\to\vault -Lan
```

也可以设环境变量：

```powershell
$env:HUB_ROOT = "D:\path\to\vault"
python hub-web\server.py
```

## 页面

| 页面 | 内容 |
|---|---|
| **抖音** | 账号切换（全部/单号）、总播放/作品数/完播率/互动率、每日播放柱状图、Top 作品、账号概况、作品明细 |
| **小红书** | 账号切换（全部/单号）、观看/笔记数/点击率/互动率、每日观看折线、近 30 天指标（带环比）、笔记明细 |

## 静态快照

```powershell
python hub-web\server.py --root D:\path\to\vault --export
# 默认写 hub-web\web\data\bundle.json
```

导出文件是完整账号数据，只适合自己看或挂私有 Pages；**不要提交到公开仓库**，
`.gitignore` 已忽略 `hub-web/web/data/`。

## 接口

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/bundle` | 抖音 + 小红书数据（2 秒缓存） |
| GET | `/api/health` | 健康检查 |
| GET | `/` | 前端单页（hash 路由） |

## 前端

`web/` 是纯静态资源，无构建步骤：

- `app.js` / `app.css` / `index.html`：两个页面的渲染；
- `android-bundle.js`：Android 客户端里把本地文件拼成与 `/api/bundle` 相同结构，复用同一套渲染代码；
- `manifest.webmanifest` + `icon.svg`：可加到手机桌面；
- `web/data/` 只放运行时导出的快照，不进 git。

## 安全边界

- 默认只监听 `127.0.0.1`；用 `--host 0.0.0.0` 时同一局域网的人都能访问，别在公共 Wi-Fi 开；
- 没有登录/鉴权，定位是家庭局域网自用。
