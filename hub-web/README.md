# hub-web — 浏览器 / 手机版

把桌面 hub 的视图搬到浏览器：同一份数据仓库，手机连同一 Wi-Fi 就能看，换电脑也不用装桌面环境。

- 数据仓库 = 任意包含 `notes/kb/` 的目录；**本仓库不含任何数据**
- 只读镜像 + 刷题写回：除 `notes/kb/<科目>/review.json` 外全部只读
- 不是独立应用：启动时从 `../hub/` 复用 `core` 模块，代码必须和 `hub/` 放在同一仓库

## 运行

```powershell
python hub-web\server.py --root D:\path\to\vault --open
# 默认 127.0.0.1:8765

python hub-web\server.py --root D:\path\to\vault --host 0.0.0.0   # 手机同局域网
powershell -ExecutionPolicy Bypass -File hub-web\start.ps1 -Root D:\path\to\vault -Lan
```

也可以用环境变量：

```powershell
$env:HUB_ROOT = "D:\path\to\vault"
python hub-web\server.py
```

不传 `--root` 时，默认用代码仓库自身作为数据仓库；没有 `notes/` 就显示空状态。

## 静态快照

```powershell
python hub-web\server.py --root D:\path\to\vault --export
# 默认写 hub-web\web\data\bundle.json
```

导出文件是**完整数据快照**（笔记正文、账号、账单等），只适合自己挂 Pages 或离线打开；
**不要提交到任何公开仓库**，`.gitignore` 已忽略 `hub-web/web/data/`。

## 接口

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/bundle` | 全部页面的数据（2 秒缓存） |
| GET | `/api/health` | 健康检查 |
| POST | `/api/answer` | 刷题写回：`{subject, id, ok}` |
| GET | `/` | 前端单页（hash 路由） |

## 前端

`web/` 是纯静态资源，无构建步骤：

- `app.js` / `app.css` / `index.html`：页面与样式；
- `android-bundle.js`：Android 客户端里把本地文件拼成与 `/api/bundle` 相同结构，复用同一套渲染代码；
- `manifest.webmanifest` + `icon.svg`：可加到手机桌面；
- `web/data/` 只放运行时导出的快照，不进 git。

## 安全边界

- 默认只监听 `127.0.0.1`；用 `--host 0.0.0.0` 时同一局域网的人都能访问，注意别在公共 Wi-Fi 开；
- 没有登录/鉴权，定位是家庭局域网自用；
- 刷题写回不做并发锁文件的跨进程协调，桌面端和网页端同时写同一科时以最后一次为准。
