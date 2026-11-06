# -*- coding: utf-8 -*-
"""抖音数据自动维护：一次扫码，长期复用；多账号；只拉数据，不改抖音侧任何内容。

授权模型
  · 专用浏览器扫码一次 → 读出 douyin.com 的 Cookie → 用同步密钥加密后
    写进 data/hub/douyin/auth.<机器>.json（进 git，另一台机器 pull 得到）；
  · 密钥只在本机 data/hub/douyin/sync.key（不进 git），换机粘一次即可；
  · 之后每天定时用这份 Cookie 调创作者中心的**只读**接口。

只读边界（硬编码白名单，别处一律拒绝）
  · GET  /aweme/v1/creator/pc/user/info/          认账号
  · GET  /web/api/creator/item/list/download      作品列表导出（xlsx）
  · GET  /web/api/creator/item/list               作品列表 JSON（兜底）
  · GET  /janus/douyin/creator/pc/work_list       最近作品 JSON（兜底）
  · POST /janus/douyin/creator/data/overview/dashboard       账号概览（含每日趋势）
  · GET  /janus/douyin/creator/data/overview/dashboard/fans  粉丝概览
  · POST /janus/douyin/creator/download/data/pc/item/list    数据中心的列表导出（兜底）
  不发布、不点赞、不评论、不删作品、不改资料。

定时：Windows 计划任务「抖音数据同步」调 hub.exe --douyin-sync。
"""
import gzip
import json
import os
import re
import subprocess
import sys
import threading
import time as _time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from datetime import date, datetime, time, timedelta
from pathlib import Path

from . import browser, douyin, douyin_auth, paths

BASE = "https://creator.douyin.com"
HOME = BASE + "/creator-micro/home"
LOGIN = BASE + "/creator-micro/home"
REFERER = BASE + "/creator-micro/home"
UA = browser.UA
TASK_NAME = "抖音数据同步"

DEFAULTS = {
    "enabled": True,       # 默认每天自动同步一次（09:10），不用手动开
    "time": "09:10",
    "days": 30,            # 概览趋势回看天数
    "last": {},
    "accounts": {},        # handle -> {name, at, ok, works, daily, error}
}

# 只读白名单：method + path 前缀。新接口必须同时改这里和 README。
ALLOWED = (
    ("GET", "/aweme/v1/creator/pc/user/info/"),
    ("GET", "/aweme/v1/creator/user/info/"),
    ("GET", "/web/api/creator/item/list/download"),
    ("GET", "/web/api/creator/item/list"),
    ("GET", "/janus/douyin/creator/pc/work_list"),
    ("POST", "/janus/douyin/creator/data/overview/dashboard"),
    ("GET", "/janus/douyin/creator/data/overview/dashboard/fans"),
    ("POST", "/janus/douyin/creator/download/data/pc/item/list"),
)

AUTH_COOKIES = ("sessionid", "sessionid_ss", "sid_guard")


class SyncError(RuntimeError):
    """接口/文件/配置问题。"""


class LoginError(SyncError):
    """没登录，或登录已失效。"""


# ------------------------------------------------------------------ 配置
def _dir():
    return paths.data_dir("hub", "douyin")


def config_file():
    return _dir() / "sync.json"


def log_file():
    return _dir() / "sync.log"


def exports_dir(day=None, handle=None):
    parts = ["hub", "douyin", "exports", day or date.today().isoformat()]
    if handle:
        parts.append(handle)
    return paths.data_dir(*parts)


def probe_dir():
    return paths.data_dir("hub", "douyin", "probe")


def load_cfg():
    cfg = dict(DEFAULTS)
    try:
        with open(config_file(), "r", encoding="utf-8-sig") as f:
            data = json.load(f) or {}
    except (OSError, ValueError):
        data = {}
    if isinstance(data, dict):
        for k in DEFAULTS:
            if k in data:
                cfg[k] = data[k]
    if not isinstance(cfg.get("accounts"), dict):
        cfg["accounts"] = {}
    return cfg


def save_cfg(cfg):
    p = config_file()
    tmp = str(p) + ".tmp"
    out = {k: cfg.get(k) for k in DEFAULTS}
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
        f.write("\n")
    os.replace(tmp, p)


def write_log(text):
    try:
        with open(log_file(), "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {text}\n")
    except OSError:
        pass


def read_log(limit=200):
    try:
        lines = log_file().read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    return lines[-limit:]


# ------------------------------------------------------------------ Cookie
def parse_cookie(text):
    """把粘贴的内容规整成 Cookie 头：认 `Cookie: …`、curl `-H 'Cookie: …'`、裸 a=b; c=d。"""
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


def has_login(cookie):
    c = str(cookie or "")
    return any(f"{name}=" in c for name in AUTH_COOKIES)


def merge_cookies(cookie, set_cookies):
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


def cookie_from_jar(jar):
    return "; ".join(f"{k}={v}" for k, v in (jar or {}).items())


def _settle_cookies(jar, seconds=4):
    """登录后再等一会儿，把安全 SDK 陆续写进来的 Cookie（bd_ticket_guard_* 等）补齐。

    实测：刚扫码成功就保存，会缺 bd_ticket_guard_ticket / pubKey / tssign，
    关掉浏览器后接口就报「用户未登录」。
    """
    deadline = _time.time() + max(0, seconds)
    while _time.time() < deadline:
        _time.sleep(1)
        try:
            jar.update(browser.read_cookies("douyin.com"))
        except Exception:                                # noqa: BLE001
            pass
    return jar


# ------------------------------------------------------------------ HTTP
def _guard(url, method):
    path = urllib.parse.urlsplit(url).path
    for m, prefix in ALLOWED:
        if method == m and path.startswith(prefix):
            return
    raise SyncError(f"拒绝访问（只读白名单之外）：{method} {path}")


def _decode(raw):
    for enc in ("utf-8", "gb18030"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace")


def _message(raw):
    try:
        obj = json.loads(_decode(raw))
    except ValueError:
        text = _decode(raw).strip()
        return text[:300] if text and not text.startswith("<") else ""
    if isinstance(obj, dict):
        msg = str(obj.get("status_msg") or obj.get("msg") or obj.get("message") or "").strip()
        base = obj.get("BaseResp") or {}
        if not msg and isinstance(base, dict):
            msg = str(base.get("StatusMessage") or "").strip()
        return msg
    return ""


def _is_login_error(text):
    return bool(re.search(r"未登录|登录已|登录失效|not\s*login|login\s*required", str(text), re.I))


def request(url, cookie, method="GET", data=None, timeout=90, referer=None):
    """发一个受白名单约束的请求，返回 (body bytes, content-type, set-cookies)。"""
    _guard(url, method)
    body = None
    headers = {
        "User-Agent": UA,
        "Accept": "application/json, text/plain, */*",
        "Accept-Encoding": "identity",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Referer": referer or REFERER,
        "Cookie": cookie,
    }
    if data is not None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
        headers["Origin"] = BASE
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            ctype = r.headers.get("Content-Type", "")
            raw = r.read()
            cookies = r.headers.get_all("Set-Cookie") or []
            enc = (r.headers.get("Content-Encoding") or "").lower()
    except urllib.error.HTTPError as e:
        ctype = e.headers.get("Content-Type", "") if e.headers else ""
        raw = e.read()
        cookies = e.headers.get_all("Set-Cookie") if e.headers else []
        enc = ""
        if e.code != 200:
            msg = _message(raw)
            if _is_login_error(msg) or e.code in (401, 403):
                raise LoginError(msg or f"HTTP {e.code}（可能登录已失效）")
            raise SyncError(msg or f"HTTP {e.code}")
    except urllib.error.URLError as e:
        raise SyncError(f"网络错误：{e.reason}")
    if enc == "gzip":
        try:
            raw = gzip.decompress(raw)
        except OSError:
            pass
    return raw, ctype, cookies


def get_json(url, cookie, method="GET", data=None, timeout=60):
    raw, ctype, cookies = request(url, cookie, method, data, timeout)
    text = _decode(raw).strip()
    if not text.startswith(("{", "[")):
        raise SyncError(f"接口返回的不是 JSON（{ctype or '未知类型'}）")
    try:
        obj = json.loads(text)
    except ValueError:
        raise SyncError("接口返回了坏 JSON")
    if isinstance(obj, dict):
        code = obj.get("status_code")
        if code is None:
            code = (obj.get("BaseResp") or {}).get("StatusCode")
        if code not in (None, 0):
            msg = str(obj.get("status_msg") or (obj.get("BaseResp") or {}).get("StatusMessage")
                      or "").strip()
            if code == 8 or _is_login_error(msg):
                raise LoginError(msg or "登录已失效")
            raise SyncError(msg or f"接口报错 status_code={code}")
    return obj, cookies


# ------------------------------------------------------------------ 身份
def _clean_handle(v):
    s = str(v or "").strip()
    if not s or s in ("0", "None", "null"):
        return ""
    return s


def parse_identity(obj):
    """从 user/info 里认出 {handle, name, user_id, follower_count}。字段位置各版本不同，递归找。"""
    found = []

    def walk(o):
        if isinstance(o, dict):
            nick = (o.get("nickname") or o.get("nick_name")
                    or o.get("nickName") or o.get("name"))
            uid = o.get("user_id") or o.get("uid") or o.get("userId")
            unique = (o.get("unique_id") or o.get("uniqueId")
                      or o.get("douyin_unique_id") or o.get("douyinUniqueId"))
            short = o.get("short_id") or o.get("shortId")
            if nick and (uid or unique or short):
                found.append({
                    "name": str(nick),
                    "user_id": _clean_handle(uid),
                    "handle": _clean_handle(unique) or _clean_handle(short)
                              or _clean_handle(uid),
                    "follower_count": o.get("follower_count"),
                })
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(obj)
    if not found:
        return {"handle": "", "name": "", "user_id": "", "follower_count": None}
    # 优先有 unique_id/short_id 的，其次 user_id
    found.sort(key=lambda x: (not x.get("handle"), not x.get("name")))
    return found[0]


def verify(cookie, retries=3, wait=2.0):
    """验登录并认号。新版用户资料在 /aweme/v1/creator/user/info/，
    /pc/user/info/ 只回 uid，作为兜底。"""
    last = None
    for i in range(max(1, retries)):
        for path in ("/aweme/v1/creator/user/info/",
                     "/aweme/v1/creator/pc/user/info/"):
            try:
                obj, _ = get_json(BASE + path, cookie)
                ident = parse_identity(obj)
                if ident.get("handle"):
                    return ident
                last = SyncError("登录成功但没认出抖音号")
            except LoginError as e:
                last = e
            except SyncError as e:
                last = e
        if i + 1 < retries:
            _time.sleep(wait)
    raise last or LoginError("登录态无效")


# ------------------------------------------------------------------ 登录
# 当前挂着的扫码窗口（一次性 profile）；换号/异常时靠它收尾
_ACTIVE_PROFILE = None
_CANCEL = threading.Event()


def _reset_browser():
    global _ACTIVE_PROFILE
    _ACTIVE_PROFILE = None
    browser.configure(profile=browser.DEFAULT_PROFILE, port=browser.DEFAULT_PORT)


def _cleanup_stale_logins():
    """清掉上次异常退出留下的一次性登录窗口/配置目录。"""
    browser.kill_login_browsers()
    try:
        root = paths.data_dir("social", "browser")
        for p in root.glob("douyin-login-*"):
            browser.cleanup_profile(p)
    except OSError:
        pass


def cancel_login():
    """关掉当前挂着的扫码窗口（已保存的加密登录态不动）。"""
    global _ACTIVE_PROFILE
    _CANCEL.set()
    if not _ACTIVE_PROFILE:
        return False
    try:
        browser.close_browser(force=True)
    finally:
        browser.cleanup_profile(_ACTIVE_PROFILE)
        _reset_browser()
    return True


# 兼容旧名字
logout_browser = cancel_login


def login(timeout=600, on_status=None, phone=""):
    """扫码登录一个号：每次都用**全新的一次性 profile**，和别的号彻底隔离。

    登录完把 Cookie 加密存进本机分片，然后关窗口、删 profile——下一个号从零开始，
    不会出现「还登着上一个号 / 扫码跳到旧账号」的问题。
    """
    global _ACTIVE_PROFILE
    on_status = on_status or (lambda _s: None)
    cfg = load_cfg()
    master, key_created = douyin_auth.ensure_key()
    # 先收拾上一次没关干净的窗口
    cancel_login()
    _CANCEL.clear()
    _cleanup_stale_logins()

    profile = browser.new_login_profile()
    port = browser.free_port()
    _ACTIVE_PROFILE = profile
    try:
        browser.open_browser(HOME, headless=False, profile=profile, port=port)
        on_status("独立扫码窗口已打开：用抖音 App 扫这个号（扫完窗口会自动关）…")
        deadline = _time.time() + timeout
        while _time.time() < deadline:
            if _CANCEL.is_set():
                raise LoginError("已取消本次扫码")
            try:
                jar = browser.read_cookies("douyin.com")
            except Exception:                            # noqa: BLE001
                jar = {}
            cookie = cookie_from_jar(jar)
            if has_login(cookie):
                on_status("扫码成功，正在等安全票据生成（约 10 秒）…")
                # 让页面自己跑一遍：数据中心会触发安全 SDK，把 bd_ticket_guard_* 写全
                try:
                    browser.navigate(HOME, wait=2)
                    browser.navigate(BASE + "/creator-micro/data-center/operation", wait=4)
                except Exception:                    # noqa: BLE001
                    pass
                jar = _settle_cookies(jar, 5)
                cookie = cookie_from_jar(jar)
                if not has_login(cookie):
                    _time.sleep(1.5)
                    continue
                try:
                    ident = verify(cookie, retries=5, wait=2)
                except LoginError as e:
                    on_status(f"登录了但校验失败（{e}），再等一下…")
                    _time.sleep(2)
                    continue
                # 保存前再补一次（有些票据是最后一个请求才下发的）
                jar = _settle_cookies(jar, 2)
                cookie = cookie_from_jar(jar)
                handle = ident["handle"]
                name = ident.get("name") or ""
                at = douyin_auth.save_session(handle, cookie, name)
                try:
                    douyin.add_account(handle, name)
                except Exception:                        # noqa: BLE001
                    pass
                cfg = load_cfg()
                cfg.setdefault("accounts", {})[handle] = {
                    "name": name, "at": at, "ok": True,
                    "works": 0, "daily": 0, "error": "",
                }
                save_cfg(cfg)
                write_log(f"扫码登录：{handle}（{name}）· Cookie {len(jar)} 项"
                          + (" · 已生成同步密钥" if key_created else ""))
                on_status(f"已登录 {handle}" + (f"（{name}）" if name else "")
                          + "，登录态已加密保存")
                return {"ok": True, "handle": handle, "name": name,
                        "cookie": cookie, "count": len(jar),
                        "key_created": key_created,
                        "key_text": douyin_auth.key_text(master) if key_created else ""}
            _time.sleep(1.5)
        raise LoginError("等了 %d 分钟没检测到登录，重试一次" % (timeout // 60))
    except LoginError:
        raise
    except Exception as e:                                # noqa: BLE001
        if _CANCEL.is_set():
            raise LoginError("已取消本次扫码")
        raise
    finally:
        # 无论成功、超时还是报错，都关掉并删掉这个一次性 profile。
        # cancel_login 已经收尾过时（PROFILE 已复位）就不要再碰默认 profile。
        try:
            if browser.PROFILE == profile:
                browser.close_browser(force=True)
        finally:
            browser.cleanup_profile(profile)
            _reset_browser()
            _CANCEL.clear()


def login_cli():
    try:
        result = login(on_status=write_log)
    except Exception as e:                                # noqa: BLE001
        write_log(f"登录 CLI 失败：{e}")
        print("登录失败：" + str(e))
        return 1
    print(f"已登录 {result['handle']}" + (f"（{result['name']}）" if result.get("name") else ""))
    if result.get("key_created"):
        print("同步密钥（换机器时要用，别公开）：" + result["key_text"])
    return 0


# ------------------------------------------------------------------ 拉数据
def _save_export(handle, label, raw):
    day = date.today().isoformat()
    out = exports_dir(day, handle)
    out.mkdir(parents=True, exist_ok=True)
    p = out / f"{label}.xlsx"
    p.write_bytes(raw)
    return p


def _xlsx_from_raw(raw, path):
    """导出的可能是 xlsx，也可能是装着 xlsx 的 zip。返回可读的 xlsx 路径。"""
    if raw.startswith(b"PK"):
        try:
            douyin.xlsx.sheet_names(str(path))
            return str(path)
        except Exception:                                # noqa: BLE001
            pass
        try:
            with zipfile.ZipFile(path) as z:
                names = [n for n in z.namelist()
                         if n.lower().endswith((".xlsx", ".xlsm"))]
                if names:
                    target = path.with_suffix(".inner.xlsx")
                    with open(target, "wb") as f:
                        f.write(z.read(names[0]))
                    return str(target)
        except Exception:                                # noqa: BLE001
            pass
    raise SyncError("导出的不是 xlsx")


def export_works(cookie, handle):
    """作品列表导出（内容管理 → 导出），返回 (xlsx 路径, 刷新后的 Set-Cookie)。"""
    qs = urllib.parse.urlencode({
        "min_cursor": 0,
        "max_cursor": 0,
        "count": 1000,
        "need_long_article": 1,
    })
    url = f"{BASE}/web/api/creator/item/list/download?{qs}"
    raw, ctype, cookies = request(url, cookie,
                                  referer=BASE + "/creator-micro/content/manage",
                                  timeout=120)
    if raw[:1] in (b"{", b"["):
        msg = _message(raw)
        if _is_login_error(msg):
            raise LoginError(msg)
        raise SyncError(msg or "导出接口返回了 JSON")
    p = _save_export(handle, "作品列表", raw)
    path = _xlsx_from_raw(raw, p)
    return path, cookies


def fetch_item_list(cookie):
    """作品列表 JSON（含播放/完播/互动/涨粉全部指标），分页拉全。"""
    out, cursor = [], 0
    for _page in range(30):
        qs = urllib.parse.urlencode({
            "count": 100,
            "max_cursor": cursor,
            "fields": "metrics,review,visibility",
            "need_long_article": 1,
        })
        obj, _ = get_json(f"{BASE}/web/api/creator/item/list?{qs}", cookie)
        items = obj.get("items") or []
        if not isinstance(items, list):
            break
        out.extend(items)
        if not obj.get("has_more"):
            break
        nxt = obj.get("max_cursor")
        if not nxt or nxt == cursor:
            break
        cursor = nxt
    return out


def fetch_work_list(cookie):
    """JSON 兜底：拉最近作品（含播放/点赞/评论/分享）。"""
    out, cursor = [], 0
    for _page in range(60):
        qs = urllib.parse.urlencode({
            "scene": "star_atlas", "aid": 1128, "count": 12,
            "device_platform": "android", "status": 1, "max_cursor": cursor,
        })
        obj, _ = get_json(f"{BASE}/janus/douyin/creator/pc/work_list?{qs}", cookie)
        items = obj.get("aweme_list") or obj.get("items") or []
        if not isinstance(items, list):
            break
        out.extend(items)
        if not obj.get("has_more"):
            break
        nxt = obj.get("max_cursor")
        if not nxt or nxt == cursor:
            break
        cursor = nxt
    return out


def fetch_dashboard(cookie, days):
    obj, _ = get_json(BASE + "/janus/douyin/creator/data/overview/dashboard",
                      cookie, method="POST", data={"recent_days": int(days)},
                      timeout=60)
    return obj


def fetch_fans(cookie, days):
    qs = urllib.parse.urlencode({"recent_days": int(days)})
    obj, _ = get_json(
        f"{BASE}/janus/douyin/creator/data/overview/dashboard/fans?{qs}", cookie)
    return obj


# ------------------------------------------------------------------ 单账号
def _sync_one(handle, session, cfg, log):
    """同步一个号，只写这个号自己的数据文件。返回 (works_n, daily_n, errors)。"""
    name = session.get("name") or ""
    cookie = parse_cookie(session.get("cookie"))
    if not has_login(cookie):
        return 0, 0, ["没有登录态，先扫码登录"]
    # 先验一下，避免拿过期 Cookie 到处撞
    ident = verify(cookie)
    real = ident.get("handle") or handle
    if real != handle:
        return 0, 0, [f"登录态属于 {real}，和账号 {handle} 对不上，已跳过（避免串号）"]
    if ident.get("name") and ident["name"] != name:
        name = ident["name"]
        try:
            douyin.add_account(handle, name)
        except Exception:                                # noqa: BLE001
            pass

    works_n = daily_n = 0
    errors = []

    # 1) 作品列表：优先 JSON（字段最全、不分导出大小限制），失败退官方导出 xlsx
    try:
        items = fetch_item_list(cookie)
        if not items:
            raise SyncError("接口没返回作品")
        added, updated = douyin.replace_works(handle, items)
        works_n = added + updated
        log(f"  ✓ 作品列表（接口全量）：新增 {added} / 更新 {updated}（共 {len(items)} 条）")
    except LoginError:
        raise
    except Exception as e:                               # noqa: BLE001
        errors.append(f"作品接口失败：{e}")
        log(f"  ! 作品接口失败，改用导出 xlsx：{e}")
        try:
            path, _ = export_works(cookie, handle)
            kind, added, updated = douyin.import_file(path, handle)
            works_n = added + updated
            log(f"  ✓ 作品列表（xlsx）：新增 {added} / 更新 {updated}（{kind}）")
        except LoginError:
            raise
        except Exception as e2:                          # noqa: BLE001
            errors.append(f"作品导出也失败：{e2}")
            log(f"  ✗ 作品导出失败：{e2}")

    # 2) 账号概览：每日播放/投稿/互动/完播等
    try:
        obj = fetch_dashboard(cookie, cfg.get("days") or 30)
        metrics = obj.get("metrics") or []
        n = douyin.merge_dashboard(handle, metrics)
        daily_n = n
        log(f"  ✓ 每日趋势：{n} 天")
    except LoginError:
        raise
    except Exception as e:                               # noqa: BLE001
        errors.append(f"概览失败：{e}")
        log(f"  ✗ 概览：{e}")

    # 3) 粉丝概览（总粉丝等）
    try:
        obj = fetch_fans(cookie, cfg.get("days") or 30)
        douyin.merge_profile(handle, obj.get("metrics") or [])
    except Exception as e:                               # noqa: BLE001
        # 粉丝接口失败不算致命
        log(f"  · 粉丝概览跳过：{e}")

    # Cookie 可能被接口刷新，写回本机分片让登录态越跑越新
    if cookie != parse_cookie(session.get("cookie")):
        try:
            douyin_auth.save_session(handle, cookie, name)
        except Exception:                                # noqa: BLE001
            pass
    return works_n, daily_n, errors


def sync(log=None, only=None):
    """逐个账号同步。返回汇总 dict；任何单号失败不影响其它号。"""
    log = log or write_log
    cfg = load_cfg()
    result = {"ok": False, "at": datetime.now().strftime("%Y-%m-%d %H:%M"),
              "works": 0, "daily": 0, "errors": [], "accounts": []}
    try:
        sessions = douyin_auth.load_sessions(strict=True)
    except douyin_auth.KeyMissing as e:
        result["errors"].append(str(e))
        result["message"] = "本机缺同步密钥：抖音页 → 登录 → 同步密钥（从另一台机器粘过来）"
        write_log("✗ " + result["message"])
        return result
    except douyin_auth.AuthError as e:
        result["errors"].append(str(e))
        result["message"] = f"登录态解不开：{e}"
        write_log("✗ " + result["message"])
        return result

    handles = [h["handle"] for h in douyin.load_accounts()]
    for h in sessions:
        if h not in handles:
            handles.append(h)
    if only:
        handles = [h for h in handles if h == only]
    if not handles:
        result["message"] = "还没有抖音账号：先点「登录」扫码一次"
        write_log("✗ " + result["message"])
        return result

    log(f"开始同步 · {len(handles)} 个账号 · 趋势 {cfg.get('days') or 30} 天")
    for handle in handles:
        sess = sessions.get(handle)
        if not sess:
            err = "没有登录态（这台机器上没扫过，仓库里也没有可用的加密登录态）"
            result["accounts"].append({"handle": handle, "name": "", "works": 0,
                                       "daily": 0, "errors": [err]})
            result["errors"].append(f"{handle}：{err}")
            log(f"→ {handle}\n  ✗ {err}")
            continue
        label = handle + (f"（{sess['name']}）" if sess.get("name") else "")
        log(f"→ {label}")
        try:
            works_n, daily_n, errors = _sync_one(handle, sess, cfg, log)
        except LoginError as e:
            works_n, daily_n, errors = 0, 0, [f"登录已失效：{e}"]
        except Exception as e:                           # noqa: BLE001
            works_n, daily_n, errors = 0, 0, [f"{type(e).__name__}: {e}"]
        result["accounts"].append({"handle": handle, "name": sess.get("name") or "",
                                   "works": works_n, "daily": daily_n,
                                   "errors": errors})
        result["works"] += works_n
        result["daily"] += daily_n
        cfg.setdefault("accounts", {})[handle] = {
            "name": sess.get("name") or "",
            "at": result["at"],
            "ok": not errors and (works_n > 0 or daily_n > 0),
            "works": works_n,
            "daily": daily_n,
            "error": "；".join(errors)[:300],
        }
        if errors:
            result["errors"].extend(f"{label}：{e}" for e in errors)
            log(f"  ✗ {errors[0]}")
        else:
            log(f"  ✓ {label}：作品 {works_n} · 趋势 {daily_n} 天")

    result["ok"] = any((a["works"] or a["daily"]) for a in result["accounts"]) \
        and not any("登录已失效" in e for e in result["errors"])
    summary = f"{len(handles)} 个账号 · 作品 {result['works']} · 趋势 {result['daily']} 天"
    result["message"] = (summary + "；注意：" + "；".join(result["errors"])
                         if result["errors"] else summary)
    cfg["last"] = result
    try:
        save_cfg(cfg)
    except OSError:
        pass
    log(("完成：" if result["ok"] else "失败：") + result["message"][:300])
    return result


# ------------------------------------------------------------------ 计划任务
def _task_binary():
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}" --douyin-sync'
    script = Path(__file__).resolve().parents[1] / "hub.py"
    return f'"{sys.executable}" "{script}" --douyin-sync'


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
    return info


def register_task(at="09:00"):
    at = norm_time(at)
    code, out = _run(["schtasks", "/Create", "/F", "/SC", "DAILY", "/ST", at,
                      "/TN", TASK_NAME, "/TR", _task_binary()])
    if code != 0:
        raise SyncError(f"注册计划任务失败：{out.strip()[:300]}")
    return task_info()


def unregister_task():
    code, out = _run(["schtasks", "/Delete", "/TN", TASK_NAME, "/F"])
    if code != 0 and "找不到" not in out and "cannot find" not in out.lower():
        raise SyncError(f"删除计划任务失败：{out.strip()[:300]}")


def ensure_task(cfg=None):
    """默认每天同步：配置开着但 Windows 任务没注册时，自动补注册一次。

    没有登录态时不建任务（建了也是空跑）；注册失败不抛错，页面照常显示状态。
    """
    cfg = cfg or load_cfg()
    info = task_info()
    if not cfg.get("enabled") or info.get("exists") or not logged_handles():
        return info
    try:
        return register_task(cfg.get("time") or "09:10")
    except SyncError:
        return info


def norm_time(text):
    m = re.match(r"^\s*(\d{1,2})\s*[:：]\s*(\d{1,2})\s*$", str(text or ""))
    if not m:
        raise SyncError("时间格式要像 09:30")
    h, mi = int(m.group(1)), int(m.group(2))
    if not (0 <= h < 24 and 0 <= mi < 60):
        raise SyncError("时间超出范围（00:00 ~ 23:59）")
    return f"{h:02d}:{mi:02d}"


# ------------------------------------------------------------------ 状态 / CLI
def logged_handles():
    try:
        return list(douyin_auth.load_sessions().keys())
    except douyin_auth.AuthError:
        return []


def status(cfg=None):
    """给 UI 用的一行状态。"""
    cfg = cfg or load_cfg()
    sessions = logged_handles()
    last = cfg.get("last") or {}
    tail = ""
    if last.get("at"):
        when = str(last["at"])[5:] if len(str(last["at"])) > 5 else str(last["at"])
        tail = (f" · 上次 ✓ {when}" if last.get("ok") else
                f" · 上次 ✗ {when}：{(last.get('message') or '失败')[:24]}")
    if not sessions:
        if douyin_auth.has_encrypted_auth():
            return "有加密登录态，但本机缺同步密钥", "bad"
        return "未登录（点「登录」扫码一次）", "bad"
    if not douyin_auth.load_key() and douyin_auth.has_encrypted_auth():
        return "有加密登录态，但本机缺同步密钥", "bad"
    ids = f"{len(sessions)} 个号"
    sched = f"每天 {cfg.get('time', '09:00')}" if cfg.get("enabled") else "未开定时"
    return f"{ids} · {sched}{tail}", ("ok" if last.get("ok") else "muted")


def probe_cli():
    """开发用：把各接口原样存下来，方便对字段。"""
    sessions = douyin_auth.load_sessions(strict=True)
    if not sessions:
        print("没有登录态")
        return 1
    handle, sess = next(iter(sessions.items()))
    cookie = parse_cookie(sess.get("cookie"))
    out = probe_dir() / datetime.now().strftime("%Y%m%d-%H%M%S")
    out.mkdir(parents=True, exist_ok=True)
    targets = [
        ("user_info", "GET", BASE + "/aweme/v1/creator/user/info/", None),
        ("item_list", "GET",
         BASE + "/web/api/creator/item/list?count=100&max_cursor=0"
                     "&fields=metrics,review,visibility&need_long_article=1", None),
        ("dashboard", "POST", BASE + "/janus/douyin/creator/data/overview/dashboard",
         {"recent_days": 30}),
        ("fans", "GET", BASE + "/janus/douyin/creator/data/overview/dashboard/fans?recent_days=30", None),
        ("work_list", "GET",
         BASE + "/janus/douyin/creator/pc/work_list?scene=star_atlas&aid=1128&count=12"
                     "&device_platform=android&status=1&max_cursor=0", None),
        ("works_export", "GET",
         BASE + "/web/api/creator/item/list/download?min_cursor=0&max_cursor=0"
                     "&count=1000&need_long_article=1", None),
    ]
    for name, method, url, data in targets:
        try:
            raw, ctype, _ = request(url, cookie, method=method, data=data, timeout=90)
            ext = ".bin"
            if raw.startswith(b"PK"):
                ext = ".zip"
            elif raw.strip().startswith((b"{", b"[")):
                ext = ".json"
            elif b"<html" in raw[:200].lower():
                ext = ".html"
            p = out / f"{name}{ext}"
            p.write_bytes(raw)
            print(f"{name}: {len(raw)} bytes -> {p.name} ({ctype})")
        except Exception as e:                           # noqa: BLE001
            print(f"{name}: 失败 {e}")
    print("探测结果：" + str(out))
    return 0


def main_cli():
    write_log(f"CLI 启动 frozen={getattr(sys, 'frozen', False)}")
    try:
        result = sync()
    except Exception as e:                               # noqa: BLE001
        write_log(f"CLI 异常：{type(e).__name__}: {e}")
        print("同步异常：" + str(e))
        return 1
    write_log("CLI 结束：ok=%s works=%s daily=%s" %
              (result["ok"], result["works"], result["daily"]))
    print(result.get("message") or "")
    return 0 if result["ok"] else 1
