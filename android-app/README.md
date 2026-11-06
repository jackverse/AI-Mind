# AI-Mind · Android（半离线）

装进手机就能看的抖音 / 小红书账号数据：**数据不在电脑上也能看**。
首次打开可用 APK 内置快照，之后点顶部 **☁** 从 GitHub 仓库拉取最新数据。

- 包名：`com.jackverse.secondbrain`（沿用既有安装，便于覆盖升级）
- 安装包：构建产物 `dist\hub-android.apk`（**不进仓库**）
- Android 8.0+；不用装 git、不用内网穿透，能连 GitHub 就行
- 只读：不改远程数据；登录/同步/导入仍在桌面 hub 做

## 首次使用

1. 安装 APK，打开是抖音页（没有内置快照时为空）；
2. 点右上 **⚙** 填：

   | 字段 | 说明 |
   |---|---|
   | 仓库 | `owner/repo`，一个有 `data/hub/douyin` 或 `data/hub/xhs` 的 GitHub 仓库 |
   | 分支 | 默认 `main` |
   | Token | GitHub 个人访问令牌，需要 contents 读权限（fine-grained 勾 `Contents: Read`，或 classic 勾 `repo`） |

3. 保存并拉取；之后随时点 **☁** 手动刷新。

Token 只存在 App 私有目录（`/data/data/com.jackverse.secondbrain/shared_prefs/`），换手机要重填。

## 拉取什么

| 方向 | 内容 | 实现 |
|---|---|---|
| **pull** | `data/hub/**/*.json`（排除 `auth.*`、`sync.json`、`mail.json`） | `GET git/trees/<分支>?recursive=1` 取目录，逐个 `GET git/blobs/<sha>` 写本地；远程删掉的文件本地也删 |
| **push** | 无 | 手机端只读 |

不碰的东西：构建产物、`notes/`、`auth.*`、`sync.key`、`mail.json`。
手机上只留账号与作品/笔记的文本数据，内置快照通常只有几百 KB。

## 构建

```powershell
# 不内置数据：APK 首启为空，拉取后才有内容
powershell -ExecutionPolicy Bypass -File android-app\build.ps1

# 可选：把本机数据仓库的抖音/小红书数据打进 seed.zip（只用于自己安装，产物别提交）
powershell -ExecutionPolicy Bypass -File android-app\build.ps1 -VaultRoot D:\path\to\vault

# 自定义输出路径
powershell -ExecutionPolicy Bypass -File android-app\build.ps1 -Out D:\temp\hub.apk
```

需要：JDK 17+（`JAVA_HOME`）、Android SDK（`ANDROID_HOME` 或默认 `%LOCALAPPDATA%\Android\Sdk`），
build-tools + platform 已装即可。

流程：复制 `hub-web/web` → 可选打包 `seed.zip` → `aapt2 compile/link` → `javac` → `d8` →
写回 `classes.dex` → `zipalign` → `apksigner`（`debug.keystore`，密码 `android`，**调试证书，不能上架**）。
产物：`dist\hub-android.apk`，`.gitignore` 已排除。

> `build.ps1` 带中文注释，必须存成 **UTF-8 with BOM**，否则 Windows PowerShell 5.1 会按 GBK 读、报 `Missing closing '}'`。

## 目录

```
android-app/
├─ app/
│  ├─ AndroidManifest.xml
│  ├─ res/                          # 主题、图标（自适应矢量）
│  └─ src/com/jackverse/secondbrain/
│     ├─ MainActivity.java          # WebView 壳、⚙ 设置、☁ 拉取、返回键
│     ├─ RepoStore.java             # 本地副本（首启解压 seed.zip）
│     ├─ GitHubClient.java          # trees/blobs 只读拉取
│     └─ SyncStore.java             # 同步用的读写接口
├─ build.ps1
├─ debug.keystore                   # 调试签名（同一把，保证覆盖安装）
└─ README.md
```

界面就是 `hub-web/web` 那一套页面；`android-bundle.js` 在手机里把本地文件算成与 `server.py` 相同结构的 bundle。

## 已知限制

- 首次拉取要手动建 Token；Token 明文存在 App 私有目录；
- 只读展示，桌面 hub 的登录/同步/导入没有搬过来；
- GitHub API 有频率限制（带 Token 每小时 5000 次，一次拉取约几十个请求）；
- 内置快照是打包那一刻的数据，刚装上还没拉取时看到的是旧数据，点一次 ☁ 即可。
