# -*- coding: utf-8 -*-
"""专用采集浏览器：起一个带调试端口的 Chrome/Edge，只做登录与页面操作。

不碰用户平时用的 Chrome。默认 profile 是 `data/social/browser/chrome-profile`
（和小红书自动导出共用）；抖音多账号登录时用 `new_login_profile()` 开**独立的
一次性 profile**，每个号一个干净环境，登录完即删——从根上隔离 Cookie / localStorage。
"""
import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

from . import paths

DEFAULT_PORT = int(os.environ.get("SOCIAL_CDP_PORT") or 9333)
DEFAULT_PROFILE = paths.data_dir("social", "browser", "chrome-profile")
PORT = DEFAULT_PORT
PROFILE = DEFAULT_PROFILE
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36")

CHROME_CANDIDATES = (
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.join(os.environ.get("LOCALAPPDATA") or "", "Google", "Chrome",
                 "Application", "chrome.exe"),
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
)


class BrowserError(RuntimeError):
    pass


def browser_exe():
    for p in CHROME_CANDIDATES:
        if p and os.path.isfile(p):
            return p
    raise BrowserError("找不到 Chrome 或 Edge，先装一个")


def configure(profile=None, port=None):
    """切换当前浏览器实例的 profile / 调试端口（登录多账号时用）。"""
    global PROFILE, PORT
    if profile is not None:
        PROFILE = Path(profile)
    if port is not None:
        PORT = int(port)
    return PROFILE, PORT


def new_login_profile():
    """一次性的独立登录 profile：每个抖音号一个，登录完删掉，绝不和别的号共用。"""
    root = paths.data_dir("social", "browser")
    return root / ("douyin-login-" + time.strftime("%Y%m%d-%H%M%S"))


def free_port():
    import socket
    s = socket.socket()
    try:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])
    finally:
        s.close()


def cleanup_profile(profile):
    """删掉一次性 profile（Chrome 刚退出时文件可能还被占，重试两次）。"""
    p = Path(profile)
    if p.resolve() == DEFAULT_PROFILE.resolve():
        return False                       # 默认 profile 不删
    for _ in range(3):
        shutil.rmtree(str(p), ignore_errors=True)
        if not p.exists():
            return True
        time.sleep(0.6)
    return not p.exists()


def _marker(profile=None):
    """用 profile 目录名做 PowerShell 匹配标记（只留安全字符）。"""
    name = Path(profile or PROFILE).name
    return re.sub(r"[^0-9A-Za-z_\-]", "", name) or "chrome-profile"


def _http(path, timeout=1.5, method="GET"):
    """读 CDP 的 HTTP 端点。用 http.client 直连，避免系统代理把 127.0.0.1 也代理掉。"""
    import http.client
    try:
        conn = http.client.HTTPConnection("127.0.0.1", PORT, timeout=timeout)
        try:
            conn.request(method, path)
            resp = conn.getresponse()
            if resp.status not in (200, 201):
                return None
            return json.loads(resp.read().decode("utf-8", "replace"))
        finally:
            conn.close()
    except Exception:                                    # noqa: BLE001
        return None


def running():
    return _http("/json/version") is not None


def pages():
    tabs = _http("/json/list") or []
    return [t for t in tabs if t.get("type") == "page"]


def _connect(ws_url):
    from websockets.sync.client import connect
    return connect(ws_url, max_size=None, open_timeout=10)


def _call(ws, method, params=None, seq=[0]):
    seq[0] += 1
    ws.send(json.dumps({"id": seq[0], "method": method, "params": params or {}}))
    while True:
        msg = json.loads(ws.recv(timeout=20))
        if msg.get("id") == seq[0]:
            if "error" in msg:
                raise BrowserError(f"{method} 失败：{msg['error'].get('message')}")
            return msg.get("result") or {}


def _page_ws():
    ps = pages()
    if not ps:
        raise BrowserError("浏览器里没有标签页")
    # 优先创作者中心页面
    pick = next((p for p in ps if "douyin.com" in (p.get("url") or "")), ps[0])
    return _connect(pick["webSocketDebuggerUrl"])


def eval_js(expr, ws=None):
    own = ws is None
    ws = ws or _page_ws()
    try:
        r = _call(ws, "Runtime.evaluate",
                  {"expression": expr, "returnByValue": True, "awaitPromise": True})
        return (r.get("result") or {}).get("value")
    finally:
        if own:
            try:
                ws.close()
            except Exception:                            # noqa: BLE001
                pass


def navigate(url, wait=2.0):
    ws = _page_ws()
    try:
        _call(ws, "Page.enable")
        _call(ws, "Page.navigate", {"url": url})
    finally:
        try:
            ws.close()
        except Exception:                                # noqa: BLE001
            pass
    if wait:
        time.sleep(wait)


def read_cookies(domain_suffix="douyin.com"):
    """读出浏览器里某个域的 Cookie（dict）。"""
    ws = _page_ws()
    try:
        _call(ws, "Network.enable")
        res = _call(ws, "Network.getAllCookies")
    finally:
        try:
            ws.close()
        except Exception:                                # noqa: BLE001
            pass
    jar = {}
    for c in res.get("cookies") or []:
        if domain_suffix in (c.get("domain") or ""):
            jar[c["name"]] = c["value"]
    return jar


def clear_origin(origin):
    """只清这个站点（cookies / localStorage / sessionStorage / indexedDB）。

    不清整个 profile，避免把小红书等其它登录一起搞掉。
    """
    ws = _page_ws()
    try:
        _call(ws, "Storage.clearDataForOrigin",
              {"origin": origin,
               "storageTypes": "cookies,local_storage,session_storage,indexeddb,cache_storage"})
    finally:
        try:
            ws.close()
        except Exception:                                # noqa: BLE001
            pass


def _clear_singleton(profile):
    for name in ("SingletonLock", "SingletonCookie", "SingletonSocket"):
        try:
            os.remove(os.path.join(profile, name))
        except OSError:
            pass


def _kill_profile_chrome(profile):
    """杀掉占着这个 profile、但没有调试端口的 Chrome（否则新进程只会转发然后退出）。"""
    if os.name != "nt":
        return
    marker = _marker(profile)
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command",
             "Get-CimInstance Win32_Process -Filter \"Name='chrome.exe'\" | "
             f"Where-Object {{ $_.CommandLine -like '*{marker}*' }} | "
             "ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"],
            capture_output=True, timeout=20,
            creationflags=subprocess.CREATE_NO_WINDOW)
    except Exception:                                    # noqa: BLE001
        pass


def kill_login_browsers():
    """清掉所有遗留的一次性登录窗口（异常退出时可能没关干净）。"""
    _kill_profile_chrome("douyin-login-")


def _start_chrome(exe, args, env):
    log = open(paths.data_dir("hub", "douyin") / "chrome-last.log", "wb")
    try:
        proc = subprocess.Popen([exe] + args, stdin=subprocess.DEVNULL,
                                stdout=log, stderr=log, env=env,
                                creationflags=subprocess.CREATE_NO_WINDOW)
    finally:
        log.close()
    time.sleep(2.0)
    return proc if proc.poll() is None else None


def _focus_pid(pid, tries=20):
    """把指定进程的窗口提到前台（全屏窗口开着时新窗口容易被压在后面）。"""
    if os.name != "nt":
        return False
    try:
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        handles = []

        @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        def enum_cb(hwnd, _lparam):
            owner = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
            if owner.value == pid and user32.IsWindowVisible(hwnd):
                handles.append(hwnd)
            return True

        user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int,
                                        ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                        ctypes.c_uint]
        user32.SetWindowPos.restype = wintypes.BOOL
        swp = 0x0001 | 0x0002 | 0x0040          # NOSIZE | NOMOVE | SHOWWINDOW
        for _ in range(tries):
            handles.clear()
            user32.EnumWindows(enum_cb, 0)
            if handles:
                hwnd = handles[0]
                # 全屏窗口通常是置顶的，先临时 TOPMOST 把登录窗露出来，再恢复
                user32.SetWindowPos(hwnd, ctypes.c_void_p(-1), 0, 0, 0, 0, swp)
                user32.ShowWindow(hwnd, 9)          # SW_RESTORE
                user32.SetForegroundWindow(hwnd)
                time.sleep(0.8)
                user32.SetWindowPos(hwnd, ctypes.c_void_p(-2), 0, 0, 0, 0,
                                    0x0001 | 0x0002)
                return True
            time.sleep(0.25)
    except Exception:                                    # noqa: BLE001
        pass
    return False


def focus_profile():
    """浏览器已经在跑时，按调试端口那条命令行找到主进程再提前台。"""
    if os.name != "nt":
        return False
    marker = _marker()
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command",
             "(Get-CimInstance Win32_Process -Filter \"Name='chrome.exe'\" | "
             f"Where-Object {{ $_.CommandLine -like '*{marker}*' -and "
             "$_.CommandLine -like '*remote-debugging-port*' } | "
             "Select-Object -First 1 -ExpandProperty ProcessId)"],
            capture_output=True, text=True, timeout=15,
            creationflags=subprocess.CREATE_NO_WINDOW)
        pid = int((out.stdout or "").strip() or 0)
        return _focus_pid(pid) if pid else False
    except Exception:                                    # noqa: BLE001
        return False


def _wait_port(seconds):
    deadline = time.time() + seconds
    while time.time() < deadline:
        if running():
            return True
        time.sleep(0.3)
    return False


def chrome_log(limit=4000):
    try:
        p = paths.data_dir("hub", "douyin") / "chrome-last.log"
        return p.read_text(encoding="utf-8", errors="replace")[-limit:]
    except OSError:
        return ""


def open_browser(url, headless=False, profile=None, port=None):
    """确保当前 profile 的采集浏览器在跑并导航到 url；返回 True 表示本次新起。

    profile/port 传入时会切换到该实例（抖音多账号登录用一次性 profile）。
    """
    if profile is not None or port is not None:
        configure(profile=profile, port=port)
    started = False
    proc = None
    if not running():
        exe = browser_exe()
        profile = str(PROFILE)
        _kill_profile_chrome(profile)
        time.sleep(1.5)
        _clear_singleton(profile)
        args = [f"--remote-debugging-port={PORT}", f"--user-data-dir={profile}",
                "--no-first-run", "--no-default-browser-check",
                "--disable-blink-features=AutomationControlled",
                "--lang=zh-CN", "--window-size=1280,900",
                "--window-position=120,60", "--new-window"]
        if headless:
            args.insert(0, "--headless=new")
            args = [a for a in args if a not in ("--new-window", "--window-position=120,60")]
        args.append(url)
        env = {k: v for k, v in os.environ.items()
               if not k.upper().startswith(("PYTHON", "_PYI", "TCL", "TK"))}
        proc = _start_chrome(exe, args, env)
        if proc and _wait_port(15):
            started = True
        else:
            proc = _start_chrome(exe, ["--no-sandbox"] + args, env)
            if proc and _wait_port(15):
                # 这台机器上 Chrome 的沙箱从打包后的 hub.exe 里起不来
                started = True
            else:
                raise BrowserError("浏览器没起来（调试端口 %d 没开），详情见 "
                                   "data/hub/douyin/chrome-last.log" % PORT)
        if not headless and proc:
            _focus_pid(proc.pid)
    # 已经有页面就直接导航；没有就开一个
    if not pages():
        _http(f"/json/new?{url}", timeout=3, method="PUT")
        time.sleep(1.5)
    else:
        navigate(url, wait=1.5)
    if not headless:
        # 页面加载完再提一次：窗口刚创建时可能还没标题/还没画出来
        if started and proc:
            _focus_pid(proc.pid)
        elif not started:
            focus_profile()
    return started


def close_browser(force=False):
    """让浏览器自己退出（CDP Browser.close）；force=True 时兜底杀掉专用进程。"""
    ver = _http("/json/version")
    if ver:
        try:
            ws = _connect(ver.get("webSocketDebuggerUrl") or "")
            try:
                _call(ws, "Browser.close")
            finally:
                ws.close()
        except Exception:                                # noqa: BLE001
            pass
        time.sleep(1.5)
    if force or running():
        _kill_profile_chrome(str(PROFILE))
        time.sleep(0.8)
