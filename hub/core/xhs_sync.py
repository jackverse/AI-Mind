# -*- coding: utf-8 -*-
"""小红书数据自动维护：多账号各自登录 → 后台导出接口 → 自动并入对应账号库。

一台机器上可能同时维护多个小红书号（比如不同手机号注册的号）。原则：
  · 每个号单独扫码登录，token 单独存，**按小红书号归档**，绝不互相覆盖
  · 每天定时把每个号自己的 5 张表拉到 `data/hub/xhs/exports/<日期>/<小红书号>/`
  · 入库时按小红书号写进 `data/hub/xhs/<号>.json`（hub 小红书页按号切换/融合）

后台 5 个导出接口只认登录 Cookie（浏览器里能打开，说明不需要签名）：
  · 笔记数据  /api/galaxy/creator/datacenter/note/analyze/download?post_begin_time=&post_end_time=&type=0&page_size=10&page_num=1
  · 观看/互动/涨粉/发布  /api/galaxy/v2/download/creator/datacenter/account/analyze?data_type=0..3&days=N

定时：Windows 计划任务「小红书数据导出」每天调 `hub.exe --xhs-sync`，逐个账号跑。
"""
import json
import os
import re
import subprocess
import sys
import time as _time
import urllib.error
import urllib.request
from datetime import date, datetime, time, timedelta
from pathlib import Path

from . import paths, xhs, xhs_auth

BASE = "https://creator.xiaohongshu.com"
REFERER = BASE + "/creator/data"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36")
TASK_NAME = "小红书数据导出"
LABELS = ("笔记数据", "观看数据", "互动数据", "涨粉数据", "发布数据")

PORT = 9333
CHROME_CANDIDATES = (
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.join(os.environ.get("LOCALAPPDATA") or "", "Google", "Chrome",
                 "Application", "chrome.exe"),
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
)

DEFAULTS = {
    "enabled": False,
    "time": "09:00",
    "data_days": 30,        # 观看/互动/涨粉/发布 的 days 参数
    "note_days": 365,       # 笔记表按发布时间回看多少天（账号老笔记也要覆盖）
    "accounts": [],         # [{id, name, phone, at, last}]（Cookie 在 xhs_auth 加密分片里）
}

RE_RED_ID = re.compile(r"小红书(?:号|账号)\s*[:：]?\s*([0-9A-Za-z_]{4,})")


class SyncError(RuntimeError):
    """导出失败（登录态、接口、文件格式问题）。"""


class LoginError(SyncError):
    """没登录，或登录已失效。"""


# ------------------------------------------------------------------ 配置
def _dir():
    return paths.data_dir("hub", "xhs")


def config_file():
    return _dir() / "sync.json"


def log_file():
    return _dir() / "sync.log"


def exports_dir(day=None):
    return paths.data_dir("hub", "xhs", "exports",
                          day or date.today().isoformat())


def load_cfg():
    cfg = dict(DEFAULTS)
    data = {}
    try:
        with open(config_file(), "r", encoding="utf-8-sig") as f:
            data = json.load(f) or {}
    except (OSError, ValueError):
        data = {}
    if isinstance(data, dict):
        for k in DEFAULTS:
            if k in data:
                cfg[k] = data[k]
        if "last" in data:
            cfg["last"] = data["last"]
        # 旧版单账号配置：handle + cookie → accounts[0]
        if not cfg["accounts"] and data.get("handle"):
            cfg["accounts"] = [{
                "id": str(data["handle"]),
                "name": "",
                "phone": "",
                "cookie": data.get("cookie") or "",
                "at": "",
            }]
    if _adopt_plaintext(cfg):
        save_cfg(cfg)
    return cfg


def _adopt_plaintext(cfg):
    """旧版把 Cookie 明文存在 sync.json 里：搬进加密分片，再把明文抹掉。

    迁移失败（比如本机分片在但没密钥）就保留明文，别把唯一的登录态弄丢。
    """
    changed = False
    for acc in cfg.get("accounts") or []:
        raw = str(acc.get("cookie") or "")
        xid = str(acc.get("id") or "")
        if raw and xid and not xhs_auth.has_session(xid):
            try:
                xhs_auth.save_session(xid, parse_cookie(raw), acc.get("name") or "")
            except Exception:                                # noqa: BLE001
                continue
        if "cookie" in acc:
            acc.pop("cookie", None)
            changed = True
    return changed


def save_cfg(cfg):
    p = config_file()
    tmp = str(p) + ".tmp"
    out = {k: cfg.get(k) for k in DEFAULTS}
    if "last" in cfg:
        out["last"] = cfg["last"]
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    os.replace(tmp, p)


def write_log(text):
    try:
        with open(log_file(), "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {text}\n")
    except OSError:
        pass


def read_log(limit=80):
    try:
        lines = log_file().read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    return lines[-limit:]


def _chrome_log(limit=4000):
    try:
        return (_dir() / "chrome-last.log").read_text(
            encoding="utf-8", errors="replace")[-limit:]
    except OSError:
        return ""


# ------------------------------------------------------------------ 账号表
def get_accounts(cfg=None):
    cfg = cfg or load_cfg()
    return list(cfg.get("accounts") or [])


def find_account(xhs_id, cfg=None):
    for a in get_accounts(cfg):
        if str(a.get("id")) == str(xhs_id):
            return a
    return None


def upsert_account(xhs_id, name="", cookie="", phone="", cfg=None):
    """按小红书号新增/更新账号；同一个号只保留一份，避免数据串号。

    Cookie 不再写进 sync.json（那文件进 git）：有 Cookie 就加密存进本机分片。
    """
    cfg = cfg or load_cfg()
    xhs_id = str(xhs_id or "").strip()
    if not xhs_id:
        raise SyncError("小红书号不能为空")
    acc = find_account(xhs_id, cfg)
    if acc is None:
        acc = {"id": xhs_id, "name": "", "phone": "", "at": ""}
        cfg["accounts"].append(acc)
    if name:
        acc["name"] = name
    if phone is not None and phone != "":
        acc["phone"] = phone
    if cookie:
        try:
            xhs_auth.save_session(xhs_id, parse_cookie(cookie),
                                  name or acc.get("name") or "")
        except xhs_auth.AuthError as e:
            raise SyncError(f"登录态保存失败：{e}")
        acc["at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    acc.pop("cookie", None)
    save_cfg(cfg)
    return acc


def session_cookie(acc):
    """账号当前能用的 Cookie：优先本机加密分片，其次旧版明文（迁移期兜底）。"""
    if isinstance(acc, str):
        acc = {"id": acc}
    elif not isinstance(acc, dict):
        return ""
    xid = str(acc.get("id") or "")
    if not xid:
        return ""
    return xhs_auth.cookie_of(xid) or parse_cookie(acc.get("cookie"))


def remove_account_cfg(xhs_id, cfg=None):
    cfg = cfg or load_cfg()
    cfg["accounts"] = [a for a in cfg.get("accounts") or []
                       if str(a.get("id")) != str(xhs_id)]
    save_cfg(cfg)


def logged_accounts(cfg=None):
    return [a for a in get_accounts(cfg) if has_login(session_cookie(a))]


# ------------------------------------------------------------------ Cookie
def parse_cookie(text):
    """把粘贴的内容规整成 Cookie 头。

    认三种：`Cookie: a=b; c=d` 整行、curl 里的 `-H 'Cookie: ...'`、裸 `a=b; c=d`。
    """
    t = str(text or "").strip()
    if not t:
        return ""
    m = re.search(r"-H\s+[\"']?Cookie:\s*([^\"']+)", t, re.I)
    if m:
        t = m.group(1)
    elif re.match(r"^cookie\s*:", t, re.I):
        t = t.split(":", 1)[1]
    t = " ".join(t.split())
    pairs = []
    for part in t.split(";"):
        part = part.strip().strip("'\"")
        if "=" not in part:
            continue
        name, value = part.split("=", 1)
        name = name.strip()
        if name and " " not in name:
            pairs.append(f"{name}={value.strip()}")
    return "; ".join(pairs)


# 创作者中心的登录态 Cookie：新版用 access-token / galaxy_creator_session_id，
# 老版是 web_session；任何一个在就算已登录（导出接口只认这组 Cookie）。
AUTH_COOKIES = ("access-token-creator.xiaohongshu.com",
                "galaxy_creator_session_id",
                "customer-sso-sid",
                "web_session")


def has_login(cookie):
    c = str(cookie or "")
    return any(f"{name}=" in c for name in AUTH_COOKIES)


def merge_cookies(cookie, set_cookies):
    """接口偶尔会刷新 Cookie（Set-Cookie），合并回去，让登录态越跑越新。"""
    jar = {}
    for part in str(cookie or "").split(";"):
        part = part.strip()
        if "=" in part:
            k, v = part.split("=", 1)
            jar[k.strip()] = v.strip()
    before = dict(jar)
    for line in set_cookies or []:
        first = line.split(";", 1)[0]
        if "=" in first:
            k, v = first.split("=", 1)
            jar[k.strip()] = v.strip()
    if jar == before:
        return cookie
    return "; ".join(f"{k}={v}" for k, v in jar.items())


# ------------------------------------------------------------------ 扫码登录
def browser_exe():
    for p in CHROME_CANDIDATES:
        if p and os.path.isfile(p):
            return p
    raise SyncError("找不到 Chrome 或 Edge，先装一个")


def _cdp_http(path, timeout=1):
    """读 CDP 的 HTTP 端点。用 http.client 直连：系统代理会把 127.0.0.1 也代理掉。"""
    import http.client
    try:
        conn = http.client.HTTPConnection("127.0.0.1", PORT, timeout=timeout)
        try:
            conn.request("GET", path)
            resp = conn.getresponse()
            if resp.status != 200:
                return None
            return json.loads(resp.read().decode("utf-8", "replace"))
        finally:
            conn.close()
    except Exception:
        return None


def browser_running():
    return _cdp_http("/json/version") is not None


def _connect(ws_url):
    from websockets.sync.client import connect
    return connect(ws_url, max_size=None, open_timeout=10)


def _call(ws, method, params=None, _seq=[0]):
    _seq[0] += 1
    ws.send(json.dumps({"id": _seq[0], "method": method, "params": params or {}}))
    while True:
        msg = json.loads(ws.recv(timeout=20))
        if msg.get("id") == _seq[0]:
            if "error" in msg:
                raise SyncError(f"{method} 失败：{msg['error'].get('message')}")
            return msg.get("result") or {}


def _page_ws():
    tabs = _cdp_http("/json/list") or []
    pages = [t for t in tabs if t.get("type") == "page"]
    if not pages:
        raise SyncError("浏览器里没有标签页")
    return _connect(pages[0]["webSocketDebuggerUrl"])


def _eval(ws, expr):
    r = _call(ws, "Runtime.evaluate",
              {"expression": expr, "returnByValue": True})
    return (r.get("result") or {}).get("value")


def read_cookies():
    """读出浏览器里 xiaohongshu.com 的 Cookie（dict）。"""
    ws = _page_ws()
    try:
        _call(ws, "Network.enable")
        res = _call(ws, "Network.getAllCookies")
    finally:
        try:
            ws.close()
        except Exception:
            pass
    jar = {}
    for c in res.get("cookies") or []:
        if "xiaohongshu.com" in (c.get("domain") or ""):
            jar[c["name"]] = c["value"]
    return jar


def detect_identity(wait=4.0):
    """在已登录的浏览器里认出当前账号：返回 {'id': 小红书号, 'name': 昵称}。

    页面侧栏会显示「昵称 / 小红书号：xxx」；认不出来再从 __INITIAL_STATE__ 里找。
    """
    ws = _page_ws()
    try:
        _call(ws, "Page.enable")
        _call(ws, "Runtime.enable")
        try:
            _call(ws, "Page.navigate", {"url": BASE + "/new/home"})
        except SyncError:
            pass
        _time.sleep(wait)
        text = _eval(ws, "document.body.innerText") or ""
        state = _eval(ws,
                      "(() => { try { return JSON.stringify(window.__INITIAL_STATE__ || null); }"
                      " catch (e) { return ''; } })()") or ""
    finally:
        try:
            ws.close()
        except Exception:
            pass

    ident = {"id": "", "name": ""}
    lines = [ln.strip() for ln in str(text).splitlines() if ln.strip()]
    # 页面顶部固定是「创作服务平台 / 昵称 / 发布笔记…」，昵称取第二行
    if len(lines) >= 2 and lines[0] in ("创作服务平台", "创作服务平台") \
            and 0 < len(lines[1]) <= 24:
        ident["name"] = lines[1]
    for line in lines:
        m = RE_RED_ID.search(line)
        if m:
            ident["id"] = m.group(1)
            break
    if not ident["id"] and state:
        m = re.search(r'"(?:red_id|redId|red_id_str)"\s*:\s*"([0-9A-Za-z_]+)"', state)
        if m:
            ident["id"] = m.group(1)
    if not ident["name"] and state:
        m = re.search(r'"nickname"\s*:\s*"([^"]{1,24})"', state)
        if m:
            ident["name"] = m.group(1)
    if not ident["id"]:
        write_log("识别账号失败；页面文本前 300 字：" + str(text)[:300].replace("\n", " / "))
    return ident


def close_browser():
    """让浏览器自己退出（CDP Browser.close）。"""
    ver = _cdp_http("/json/version")
    if not ver:
        return
    try:
        ws = _connect(ver.get("webSocketDebuggerUrl") or "")
        try:
            _call(ws, "Browser.close")
        finally:
            ws.close()
    except Exception:
        pass


def logout_browser():
    """登出专用浏览器（清 Cookie + localStorage），用来换另一个号扫码。

    只清浏览器里的登录态，不动 sync.json 里已经存好的各账号 token。
    """
    if not browser_running():
        open_browser(headless=False)
    ws = _page_ws()
    try:
        _call(ws, "Network.enable")
        try:
            _call(ws, "Network.clearBrowserCookies")
        except SyncError:
            pass
        try:
            _eval(ws, "localStorage.clear(); sessionStorage.clear(); 1")
        except SyncError:
            pass
        try:
            _call(ws, "Page.navigate", {"url": BASE + "/login"})
        except SyncError:
            pass
        _time.sleep(2)
    finally:
        try:
            ws.close()
        except Exception:
            pass
    return True


def _clear_singleton(profile):
    """清掉上次强杀留下的 Singleton 锁，否则新 Chrome 可能开不了。"""
    for name in ("SingletonLock", "SingletonCookie", "SingletonSocket"):
        try:
            os.remove(os.path.join(profile, name))
        except OSError:
            pass


def _kill_profile_chrome(profile):
    """杀掉还占着采集配置、但没有调试端口的 Chrome（否则新进程只会转发然后退出）。"""
    if os.name != "nt":
        return
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command",
             "Get-CimInstance Win32_Process -Filter \"Name='chrome.exe'\" | "
             "Where-Object { $_.CommandLine -like '*chrome-profile*' } | "
             "ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"],
            capture_output=True, timeout=20,
            creationflags=subprocess.CREATE_NO_WINDOW)
    except Exception:
        pass


def _wait_port(seconds):
    deadline = _time.time() + seconds
    while _time.time() < deadline:
        if browser_running():
            return True
        _time.sleep(0.3)
    return False


def _start_chrome(exe, args, env):
    errlog = open(_dir() / "chrome-last.log", "wb")
    try:
        proc = subprocess.Popen([exe] + args, stdin=subprocess.DEVNULL,
                                stdout=errlog, stderr=errlog, env=env,
                                creationflags=subprocess.CREATE_NO_WINDOW)
    finally:
        errlog.close()
    _time.sleep(2.0)
    return proc if proc.poll() is None else None


def open_browser(headless=False):
    """起一个带调试端口的采集浏览器；返回 True 表示本次新起。

    部分机器上，Chrome 的沙箱从打包后的 hub.exe 里起不来（exit 0x80000003），
    普通参数失败后自动加 --no-sandbox 再试一次（只用于扫码登录这一下）。
    """
    if browser_running():
        return False
    exe = browser_exe()
    profile = str(paths.data_dir("social", "browser", "chrome-profile"))
    _kill_profile_chrome(profile)
    _time.sleep(1.5)
    _clear_singleton(profile)
    args = [f"--remote-debugging-port={PORT}", f"--user-data-dir={profile}",
            "--no-first-run", "--no-default-browser-check",
            "--disable-blink-features=AutomationControlled",
            "--lang=zh-CN", "--window-size=1280,900"]
    if headless:
        args.insert(0, "--headless=new")
    args.append(BASE + "/new/home")
    write_log("启动采集浏览器：" + " ".join(args))
    env = {k: v for k, v in os.environ.items()
           if not k.upper().startswith(("PYTHON", "_PYI", "TCL", "TK"))}

    if _start_chrome(exe, args, env) and _wait_port(15):
        return True
    write_log("普通启动失败（%s），改用 --no-sandbox 重试"
              % (_chrome_log()[:200].strip() or "无输出"))
    if _start_chrome(exe, ["--no-sandbox"] + args, env) and _wait_port(15):
        return True
    raise SyncError("浏览器没起来（调试端口 %d 没开），"
                    "详情见 data/hub/xhs/chrome-last.log" % PORT)


def login(timeout=300, on_status=None, phone=""):
    """扫码登录一个账号：认号 → 按小红书号存 token。

    返回 {'ok', 'cookie', 'count', 'id', 'name'}；认不出号时 id 为空，由调用方补。
    """
    on_status = on_status or (lambda _s: None)
    started = open_browser(headless=False)
    on_status("浏览器已打开：用小红书 App 扫码登录创作平台…")
    deadline = _time.time() + timeout
    while _time.time() < deadline:
        try:
            jar = read_cookies()
        except SyncError:
            jar = {}
        if any(name in jar for name in AUTH_COOKIES):
            cookie = "; ".join(f"{k}={v}" for k, v in jar.items())
            on_status("登录成功，正在识别小红书号…")
            ident = {"id": "", "name": ""}
            try:
                ident = detect_identity()
            except Exception as e:                          # noqa: BLE001
                write_log(f"识别账号异常：{e}")
            if ident.get("id"):
                upsert_account(ident["id"], ident.get("name", ""), cookie, phone)
                try:
                    xhs.add_account(ident["id"], ident.get("name", ""))
                except Exception:                            # noqa: BLE001
                    pass
                on_status(f"已登录 {ident['id']}"
                          + (f"（{ident['name']}）" if ident.get("name") else "")
                          + "，token 已保存")
            else:
                on_status("登录成功，但没认出小红书号（稍后手动填）")
            if started:
                close_browser()
            write_log(f"扫码登录：{ident.get('id') or '未识别'} · Cookie {len(jar)} 项")
            return {"ok": True, "cookie": cookie, "count": len(jar),
                    "id": ident.get("id", ""), "name": ident.get("name", "")}
        _time.sleep(1.5)
    if started:
        close_browser()
    raise LoginError("等了 %d 分钟没检测到登录，重试一次" % (timeout // 60))


def login_cli():
    """调试/兜底：命令行里弹浏览器扫码。"""
    try:
        result = login(on_status=write_log)
    except Exception as e:                                # noqa: BLE001
        write_log(f"登录 CLI 失败：{e}")
        return 1
    write_log("登录 CLI 结束：%s" % (result.get("id") or "未识别"))
    return 0 if result.get("ok") else 1


# ------------------------------------------------------------------ 目标地址
def build_targets(cfg, today=None):
    """5 个导出接口，带当天范围（本地时区转毫秒时间戳）。"""
    today = today or date.today()
    days = max(1, int(cfg.get("data_days") or DEFAULTS["data_days"]))
    note_days = max(1, int(cfg.get("note_days") or DEFAULTS["note_days"]))
    begin = datetime.combine(today - timedelta(days=note_days - 1), time.min)
    end = datetime.combine(today, time.max)
    ms = lambda dt: int(dt.timestamp() * 1000)      # noqa: E731
    note = (f"{BASE}/api/galaxy/creator/datacenter/note/analyze/download"
            f"?post_begin_time={ms(begin)}&post_end_time={ms(end)}"
            f"&type=0&page_size=10&page_num=1")

    def acc(t):
        return (f"{BASE}/api/galaxy/v2/download/creator/datacenter/account/analyze"
                f"?data_type={t}&days={days}")

    return [("笔记数据", note), ("观看数据", acc(0)), ("互动数据", acc(1)),
            ("涨粉数据", acc(2)), ("发布数据", acc(3))]


# ------------------------------------------------------------------ HTTP
def _decode(raw):
    for enc in ("utf-8", "gb18030"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace")


def _api_message(raw):
    try:
        obj = json.loads(_decode(raw))
    except ValueError:
        text = _decode(raw).strip()
        return text[:200] if text and not text.startswith("<") else ""
    msg = str(obj.get("msg") or obj.get("message") or "").strip()
    if "登录" in msg:
        return "登录已失效：" + msg
    return msg or ("" if obj.get("success") else "接口报错")


def http_get(url, cookie, timeout=90):
    """下载一个导出接口，返回 (xlsx 字节, 响应里的 Set-Cookie)。JSON 错误体转成异常。"""
    headers = {
        "User-Agent": UA,
        "Accept": "application/json, text/plain, */*",
        "Accept-Encoding": "identity",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Referer": REFERER,
        "Cookie": cookie,
    }
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            ctype = r.headers.get("Content-Type", "")
            body = r.read()
            cookies = r.headers.get_all("Set-Cookie") or []
    except urllib.error.HTTPError as e:
        ctype = e.headers.get("Content-Type", "") if e.headers else ""
        body = e.read()
        if e.code != 200:
            raise SyncError(_api_message(body) or f"HTTP {e.code}")
    except urllib.error.URLError as e:
        raise SyncError(f"网络错误：{e.reason}")

    if body[:1] in (b"{", b"[") or "json" in ctype.lower():
        raise SyncError(_api_message(body) or "接口返回了 JSON 而不是表格")
    if not body.startswith(b"PK"):
        raise SyncError(f"返回的不是 xlsx（{ctype or '未知类型'}，{len(body)} 字节）")
    return body, cookies


# ------------------------------------------------------------------ 主流程
def _sync_one(acc, cfg, outdir, log):
    """同步一个账号，返回 (files, errors)。数据只进这个号自己的目录/文件。"""
    xhs_id = str(acc.get("id") or "")
    name = acc.get("name") or ""
    cookie = session_cookie(acc)
    if not has_login(cookie):
        return 0, [f"{xhs_id or '未命名'}：没有登录态，先扫码登录"]

    xhs.add_account(xhs_id, name)
    outdir.mkdir(parents=True, exist_ok=True)      # 每个号一个目录
    files, errors = 0, []
    for label, url in build_targets(cfg):
        try:
            body, set_cookies = http_get(url, cookie)
            cookie = merge_cookies(cookie, set_cookies)
            path = outdir / f"{label}_{date.today().isoformat()}.xlsx"
            path.write_bytes(body)
            info = xhs.import_file(str(path), xhs_id)
            parts = []
            added, updated = info.get("notes", [0, 0])
            if added or updated:
                parts.append(f"笔记 +{added}/改{updated}")
            if info.get("metrics"):
                parts.append(f"指标 {info['metrics']} 项")
            if info.get("trends"):
                parts.append(f"趋势 {info['trends']} 张")
            log(f"  ✓ {label}：{len(body) // 1024} KB" +
                (f"（{'；'.join(parts)}）" if parts else ""))
            files += 1
        except SyncError as e:
            errors.append(f"{label}：{e}")
            log(f"  ✗ {label}：{e}")
        except Exception as e:                           # noqa: BLE001
            errors.append(f"{label}：{e}")
            log(f"  ✗ {label}：{e}")
    if cookie != (xhs_auth.cookie_of(xhs_id) or acc.get("cookie") or ""):
        try:                       # 接口刷新过 Cookie：更新本机加密分片
            xhs_auth.save_session(xhs_id, cookie, name)
        except xhs_auth.AuthError as e:
            errors.append(f"登录态刷新失败：{e}")
            log(f"  ✗ 登录态刷新失败：{e}")
    acc["last"] = {"at": datetime.now().strftime("%Y-%m-%d %H:%M"),
                   "files": files, "errors": errors}
    return files, errors


def sync(log=None, cfg=None):
    """逐个账号同步（按小红书号各自落库，互不干扰）。返回汇总 dict。"""
    cfg = cfg or load_cfg()
    log = log or write_log

    day = date.today().isoformat()
    result = {"ok": False, "at": datetime.now().strftime("%Y-%m-%d %H:%M"),
              "files": 0, "errors": [], "dir": str(exports_dir(day)),
              "accounts": []}
    accounts = get_accounts(cfg)
    if not accounts:
        result["errors"].append("还没有登录账号：在「小红书」页点「登录」扫码")
        result["message"] = result["errors"][0]
        write_log("✗ " + result["errors"][0])
        return result

    log(f"开始同步 · {len(accounts)} 个账号 · 笔记 {cfg.get('note_days')} 天 / "
        f"账户 {cfg.get('data_days')} 天")
    for acc in accounts:
        xhs_id = str(acc.get("id") or "")
        if not xhs_id:
            result["errors"].append("有账号没填小红书号，已跳过")
            continue
        label = xhs_id + (f"（{acc['name']}）" if acc.get("name") else "")
        log(f"→ {label}")
        outdir = exports_dir(day) / xhs_id
        files, errors = _sync_one(acc, cfg, outdir, log)
        result["accounts"].append({"id": xhs_id, "name": acc.get("name", ""),
                                   "files": files, "errors": errors})
        result["files"] += files
        if errors:
            result["errors"].extend(f"{label}：{e}" for e in errors)
        if not files:
            log(f"  ✗ {label}：{'；'.join(errors)[:200]}")
        else:
            log(f"  ✓ {label}：{files} 张表已入库")

    result["ok"] = result["files"] > 0
    result["message"] = ("；".join(result["errors"]) if result["errors"]
                         else f"{len(accounts)} 个账号 · {result['files']} 张表已入库")
    if result["ok"]:
        log(f"完成：{result['files']} 张表，存到 {exports_dir(day)}")
    else:
        log("失败：一张表都没拿到")

    latest = load_cfg()
    latest["accounts"] = accounts          # 带回去刷新过的 last（Cookie 走加密分片）
    latest["last"] = result
    try:
        save_cfg(latest)
    except OSError:
        pass
    return result


# ------------------------------------------------------------------ 计划任务
def _task_binary():
    """计划任务要跑的命令：打包版直接跑 exe，源码版跑 hub/hub.py。"""
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}" --daily-sync'
    script = Path(__file__).resolve().parents[1] / "hub.py"
    return f'"{sys.executable}" "{script}" --daily-sync'


def _run(cmd):
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=30,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return r.returncode, _decode(r.stdout or b"") + _decode(r.stderr or b"")
    except Exception as e:                               # noqa: BLE001
        return 1, str(e)


_TASK_KEYS = {
    "next": ("下次运行时间", "Next Run Time"),
    "command": ("要运行的任务", "Task To Run"),
    "status": ("状态", "Status"),
    "time": ("开始时间", "Start Time"),
}


def _pick(line_key):
    for name, keys in _TASK_KEYS.items():
        if any(k == line_key or k in line_key for k in keys):
            return name
    return None


def task_info():
    """计划任务状态：{'exists':bool,'time':'09:00','next':'...','command':'...'}"""
    code, out = _run(["schtasks", "/Query", "/TN", TASK_NAME, "/FO", "LIST", "/V"])
    if code != 0:
        return {"exists": False}
    info = {"exists": True, "time": "", "next": "", "command": "", "status": ""}
    for line in out.splitlines():
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        field = _pick(k.strip())
        if field:
            info[field] = v.strip()
    m = re.match(r"^\s*(\d{1,2}):(\d{2})", info["time"] or "")
    info["time"] = f"{int(m.group(1)):02d}:{m.group(2)}" if m else "09:00"
    m = re.match(r"^(\d{4})[/-](\d{1,2})[/-](\d{1,2})\s+(\d{1,2}):(\d{2})", info["next"] or "")
    if m:
        info["next"] = (f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d} "
                        f"{int(m.group(4)):02d}:{m.group(5)}")
    return info


def register_task(at="09:00"):
    """注册/更新每天定时任务（任务计划程序里可见、可再改）。"""
    at = norm_time(at)
    cmd = _task_binary()
    code, out = _run(["schtasks", "/Create", "/F", "/SC", "DAILY", "/ST", at,
                      "/TN", TASK_NAME, "/TR", cmd])
    if code != 0:
        raise SyncError(f"注册计划任务失败：{out.strip()[:300]}")
    return task_info()


def unregister_task():
    code, out = _run(["schtasks", "/Delete", "/TN", TASK_NAME, "/F"])
    if code != 0 and "找不到" not in out and "cannot find" not in out.lower():
        raise SyncError(f"删除计划任务失败：{out.strip()[:300]}")


def norm_time(text):
    m = re.match(r"^\s*(\d{1,2})\s*[:：]\s*(\d{1,2})\s*$", str(text or ""))
    if not m:
        raise SyncError("时间格式要像 09:30")
    h, mi = int(m.group(1)), int(m.group(2))
    if not (0 <= h < 24 and 0 <= mi < 60):
        raise SyncError("时间超出范围（00:00 ~ 23:59）")
    return f"{h:02d}:{mi:02d}"


# ------------------------------------------------------------------ CLI
def main_cli():
    """hub.exe --xhs-sync：给计划任务用，无窗口、只写日志。"""
    write_log(f"CLI 启动 frozen={getattr(sys, 'frozen', False)}")
    try:
        result = sync()
    except Exception as e:                               # noqa: BLE001
        write_log(f"CLI 异常：{type(e).__name__}: {e}")
        return 1
    write_log("CLI 结束：ok=%s files=%s" % (result["ok"], result["files"]))
    return 0 if result["ok"] else 1
