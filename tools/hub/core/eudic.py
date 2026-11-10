# -*- coding: utf-8 -*-
"""欧路词典（Eudic）OpenAPI：多账号、同步生词本/语料、按天汇总「学习情况」。

官方 API 只有生词本/笔记/例句/语音打分，**没有学习记录/复习/打卡接口**；
本模块只读，按每条记录的 add_time 反推每日新增生词、查词语料、已掌握。

文档：https://my.eudic.net/OpenAPI/Doc_Index
接口：https://api.frdic.com/api/open/v1/...
授权：Header `Authorization: NIS <授权码>`，授权码在
      https://my.eudic.net/OpenAPI/Authorization 登录后生成，一个账号一份。

数据：`data/hub/eudic/accounts.json`（授权码 DPAPI 密文）+ 每账号一个 json
（words / mastered / vocab / daily / sync），不进 git。
"""
import hashlib
import json
import os
import re
import threading
import time
from datetime import date, datetime, timedelta, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from . import daily, paths, secret

API_BASE = "https://api.frdic.com/api/open/v1"
AUTH_URL = "https://my.eudic.net/OpenAPI/Authorization"
DOC_URL = "https://my.eudic.net/OpenAPI/Doc_Index"
LANGS = {"en": "英语", "fr": "法语", "de": "德语", "es": "西语"}

PAGE_SIZE = 100
MAX_PAGES = 51                 # page 0–50；单分类最多约 5,100 条
RECENT_DAYS = 90               # 语料接口只取近 90 天，历史靠本地累积
MIN_INTERVAL = 2.1             # 30 次/分钟；实际按 ~28 次/分钟留余量
KEEP_VOCAB_DAYS = 400          # 语料明细本地保留约 13 个月

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) hub/1.3",
    "Accept": "application/json",
}

_sync_lock = threading.Lock()
_last_call = 0.0
_call_lock = threading.Lock()


class EudicError(Exception):
    """API / 授权 / 网络错误，message 直接给用户看。"""

    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


# ------------------------------------------------------------------ 基础
def normalize_token(value):
    """去掉首尾空白/引号，兼容用户把「NIS xxx」整段粘进来。"""
    s = (value or "").strip().strip('"').strip("'").strip()
    if s.lower().startswith("nis "):
        s = s[4:].strip()
    return s


def token_id(token):
    return hashlib.sha1(("eudic|" + normalize_token(token)).encode("utf-8")).hexdigest()[:12]


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def today_str():
    return date.today().isoformat()


def _throttle():
    """全局限速：30 次/分钟，按 2.1s 一次串行。"""
    global _last_call
    with _call_lock:
        wait = MIN_INTERVAL - (time.monotonic() - _last_call)
        if wait > 0:
            time.sleep(wait)
        _last_call = time.monotonic()


def _friendly(code, raw):
    msg = ""
    try:
        obj = json.loads((raw or b"").decode("utf-8", "ignore") or "{}")
        if isinstance(obj, dict):
            msg = str(obj.get("message") or "").strip()
    except ValueError:
        pass
    base = {
        400: "参数不对，欧路拒绝了这次请求",
        401: "授权失败：授权码无效或已过期，请重新生成再绑定",
        403: "请求过于频繁，欧路已临时封禁（1 小时 / 24 小时），过一会再试",
        404: "欧路接口不存在（可能改版了）",
        429: "请求过于频繁，稍后再试",
        500: "欧路服务端出错了，稍后再试",
    }.get(code)
    if base:
        return base + (f"（{msg}）" if msg else "")
    return f"欧路接口返回 {code}" + (f"：{msg}" if msg else "")


def _request(path, token, params=None, timeout=25):
    token = normalize_token(token)
    if not token:
        raise EudicError("授权码为空")
    url = API_BASE + path
    clean = {k: v for k, v in (params or {}).items() if v is not None}
    if clean:
        url += "?" + urlencode(clean)
    _throttle()
    req = Request(url, headers=dict(HEADERS, Authorization="NIS " + token))
    try:
        with urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
    except HTTPError as e:
        try:
            raw = e.read()
        except Exception:                       # noqa: BLE001
            raw = b""
        raise EudicError(_friendly(e.code, raw), e.code) from None
    except (URLError, TimeoutError, OSError) as e:
        raise EudicError("连不上欧路服务器（网络/代理问题）：" + str(getattr(e, "reason", e))) from None
    try:
        obj = json.loads(raw.decode("utf-8", "ignore") or "{}")
    except ValueError:
        raise EudicError("欧路返回的不是 JSON，稍后再试") from None
    if not isinstance(obj, dict):
        raise EudicError("欧路返回格式异常")
    return obj


def _list_data(obj):
    data = obj.get("data")
    if data is None:
        return []
    if isinstance(data, dict):
        return [data]
    return data if isinstance(data, list) else []


def categories(token, language="en"):
    return [c for c in _list_data(_request(
        "/studylist/category", token, {"language": language})) if isinstance(c, dict)]


def words(token, language, category_id, page=0, page_size=PAGE_SIZE, sort="desc"):
    return [w for w in _list_data(_request("/studylist/words", token, {
        "language": language, "category_id": category_id,
        "page": page, "page_size": page_size, "sort": sort,
    })) if isinstance(w, dict)]


def mastered_words(token, language, page=0, page_size=PAGE_SIZE):
    return [w for w in _list_data(_request("/studylist/mastered_words", token, {
        "language": language, "page": page, "page_size": page_size,
    })) if isinstance(w, dict)]


def vocab_entries(token, language, recent_days=RECENT_DAYS, page=0,
                  page_size=PAGE_SIZE):
    return [w for w in _list_data(_request("/studylist/vocab_entries", token, {
        "language": language, "recent_days": recent_days,
        "page": page, "page_size": page_size,
    })) if isinstance(w, dict)]


def _parse_dt(value):
    s = str(value or "").strip()
    if not s:
        return None
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _utc_iso(value):
    dt = _parse_dt(value)
    if dt is None:
        return ""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _local_day(value):
    dt = _parse_dt(value)
    if dt is not None:
        return dt.astimezone().strftime("%Y-%m-%d")
    m = re.match(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", str(value or ""))
    return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}" if m else ""


# ------------------------------------------------------------------ 存储
def data_root():
    return str(paths.data_dir("hub", "eudic"))


def _accounts_path():
    return os.path.join(data_root(), "accounts.json")


def _account_path(aid):
    safe = re.sub(r"[^0-9A-Za-z_\-]", "_", str(aid)) or "unknown"
    return os.path.join(data_root(), f"{safe}.json")


def _manual_path():
    return os.path.join(data_root(), "manual.json")


def _read_json(path, default):
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            obj = json.load(f)
        return obj if isinstance(obj, type(default)) else default
    except (OSError, ValueError):
        return default


def _write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def load_accounts():
    raw = _read_json(_accounts_path(), {})
    accounts = raw.get("accounts") if isinstance(raw, dict) else None
    return [a for a in (accounts or []) if isinstance(a, dict) and a.get("id")]


def save_accounts(accounts):
    _write_json(_accounts_path(), {"accounts": accounts})


def public_account(acct):
    return {
        "id": acct.get("id"),
        "name": acct.get("name") or "",
        "language": acct.get("language") or "en",
        "created": acct.get("created") or "",
        "last_sync": acct.get("last_sync") or "",
        "last_error": acct.get("last_error") or "",
        "encrypted": secret.is_sealed(acct.get("token") or ""),
    }


def token_of(acct):
    return secret.open_sealed(acct.get("token") or "")


def add_account(token, name="", language="en"):
    token = normalize_token(token)
    if not token:
        raise EudicError("授权码为空")
    language = language if language in LANGS else "en"
    aid = token_id(token)
    accounts = load_accounts()
    for a in accounts:
        if a.get("id") == aid:
            if name:
                a["name"] = name.strip()
            a["language"] = language
            a["token"] = secret.seal(token)
            save_accounts(accounts)
            return public_account(a)
    rec = {
        "id": aid,
        "name": (name or "").strip(),
        "language": language,
        "token": secret.seal(token),
        "created": _now(),
        "last_sync": "",
        "last_error": "",
    }
    accounts.append(rec)
    save_accounts(accounts)
    return public_account(rec)


def remove_account(aid):
    accounts = [a for a in load_accounts() if a.get("id") != aid]
    save_accounts(accounts)
    for p in (_account_path(aid), _account_path(aid) + ".tmp"):
        try:
            os.remove(p)
        except OSError:
            pass


def _lang_data(d, language):
    languages = d.setdefault("languages", {})
    ld = languages.setdefault(language, {})
    ld.setdefault("words", {})
    ld.setdefault("mastered", {})
    ld.setdefault("vocab", {})
    ld.setdefault("cats", {})
    ld.setdefault("sync", {})
    return ld


def load_data(aid):
    d = _read_json(_account_path(aid), {})
    d.setdefault("languages", {})
    d.setdefault("daily", {})
    d.setdefault("meta", {})
    for ld in d["languages"].values():
        if isinstance(ld, dict):
            ld.setdefault("words", {})
            ld.setdefault("mastered", {})
            ld.setdefault("vocab", {})
            ld.setdefault("cats", {})
            ld.setdefault("sync", {})
    return d


def save_data(aid, d):
    _write_json(_account_path(aid), d)


def has_data(aid):
    d = load_data(aid)
    return any(ld.get("words") or ld.get("mastered") or ld.get("vocab")
               for ld in d.get("languages", {}).values())


# ------------------------------------------------------------------ 手动复习
def load_manual():
    raw = _read_json(_manual_path(), {})
    out = {}
    for k, v in raw.items():
        try:
            n = int(v)
        except (TypeError, ValueError):
            continue
        if n >= 0:
            out[str(k)[:10]] = n
    return out


def set_manual(day, n):
    try:
        n = max(0, int(n))
    except (TypeError, ValueError):
        raise EudicError("复习数要填整数")
    data = load_manual()
    data[str(day)[:10]] = n
    cutoff = (date.today() - timedelta(days=1100)).isoformat()
    data = {k: v for k, v in data.items() if k >= cutoff}
    _write_json(_manual_path(), data)
    return data


def review_from_log(root, day=None):
    """从 daily-log.md 的「英语」列读「复习 N」；读不到返回 None。"""
    day = day or today_str()
    try:
        text = (paths.find_repo_root(str(root)) / "notes" / "daily-log.md").read_text(
            encoding="utf-8")
    except OSError:
        return None
    rows = daily.parse_text(text)
    for row in reversed(rows):
        if row.get("date") == day:
            m = re.search(r"复习\s*(\d+)", row.get("english") or "")
            return int(m.group(1)) if m else None
    return None


# ------------------------------------------------------------------ 同步
def _p(progress, msg):
    if progress:
        try:
            progress(msg)
        except Exception:                       # noqa: BLE001
            pass


def _merge_word(target, rec):
    key = (rec.get("w") or "").lower()
    if not key:
        return
    old = target.get(key)
    if old is None:
        target[key] = rec
        return
    if rec.get("t") and (not old.get("t") or rec["t"] < old["t"]):
        old["t"], old["d"] = rec["t"], rec["d"]
    if rec.get("star", 0) > old.get("star", 0):
        old["star"] = rec["star"]
    if rec.get("exp") and rec["exp"] != old.get("exp"):
        old["exp"] = rec["exp"]
    if rec.get("ctx") and not old.get("ctx"):
        old["ctx"] = rec["ctx"]
    cats = sorted(set(old.get("cats") or []) | set(rec.get("cats") or []))
    if cats != (old.get("cats") or []):
        old["cats"] = cats
    if rec.get("cat") and not old.get("cat"):
        old["cat"] = rec["cat"]


def _word_rec(item, cat_name):
    w = str(item.get("word") or "").strip()
    if not w:
        return None
    t = _utc_iso(item.get("add_time"))
    star = item.get("star")
    try:
        star = max(0, min(5, int(star)))
    except (TypeError, ValueError):
        star = 0
    return {
        "w": w,
        "t": t,
        "d": _local_day(item.get("add_time")) or (t[:10] if t else ""),
        "star": star,
        "exp": str(item.get("exp") or "").strip(),
        "ctx": str(item.get("context_line") or "").strip(),
        "cat": cat_name,
        "cats": [cat_name] if cat_name else [],
    }


def _sync_words(token, language, ld, progress, full):
    cats = categories(token, language)
    if not cats:
        cats = [{"id": "0", "name": "我的生词本"}]
    ld["cats"] = {}
    for c in cats:
        cid = str(c.get("id") if c.get("id") is not None else "0")
        ld["cats"][cid] = {"id": cid, "name": str(c.get("name") or "未命名")}

    water = dict((ld.get("sync") or {}).get("water") or {})
    do_full = bool(full or not ld["words"])
    target = {} if do_full else ld["words"]
    pages = 0
    cap_hit = False
    for c in cats:
        cid = str(c.get("id") if c.get("id") is not None else "0")
        cname = str(c.get("name") or "未命名")
        cat_water = water.get(cid) or ""
        prev_water = cat_water
        for page in range(MAX_PAGES):
            _p(progress, f"生词本「{cname}」第 {page + 1} 页…")
            items = words(token, language, cid, page, PAGE_SIZE, "desc")
            if not items:
                break
            pages += 1
            for it in items:
                rec = _word_rec(it, cname)
                if rec:
                    _merge_word(target, rec)
            newest = max((_utc_iso(it.get("add_time")) for it in items), default="")
            if newest > cat_water:
                cat_water = newest
                water[cid] = newest
            if len(items) < PAGE_SIZE:
                break
            if prev_water and not do_full:
                oldest = min((_utc_iso(it.get("add_time")) or "9999") for it in items)
                if oldest and oldest <= prev_water:
                    break
        else:
            cap_hit = True

    if cap_hit and do_full:               # 超过 5,100 条：保留旧数据，别把已知的丢了
        for key, rec in (ld.get("words") or {}).items():
            target.setdefault(key, rec)
    ld["words"] = target
    return pages, cap_hit, water


def _sync_mastered(token, language, ld, progress):
    _p(progress, "读取已掌握单词…")
    target = {}
    pages = 0
    for page in range(MAX_PAGES):
        items = mastered_words(token, language, page, PAGE_SIZE)
        if not items:
            break
        pages += 1
        for it in items:
            w = str(it.get("word") or "").strip()
            if not w:
                continue
            t = _utc_iso(it.get("add_time"))
            target[w.lower()] = {
                "w": w, "t": t,
                "d": _local_day(it.get("add_time")) or (t[:10] if t else ""),
            }
        if len(items) < PAGE_SIZE:
            break
        if page % 5 == 4:
            _p(progress, f"已掌握第 {page + 2} 页…")
    ld["mastered"] = target
    return pages


def _sync_vocab(token, language, ld, progress):
    _p(progress, f"读取近 {RECENT_DAYS} 天语料…")
    target = dict(ld["vocab"])
    pages = 0
    for page in range(MAX_PAGES):
        items = vocab_entries(token, language, RECENT_DAYS, page, PAGE_SIZE)
        if not items:
            break
        pages += 1
        for it in items:
            w = str(it.get("word") or "").strip()
            d = _local_day(it.get("add_time"))
            if not w or not d:
                continue
            target[f"{d}|{w.lower()}"] = {
                "w": w,
                "t": _utc_iso(it.get("add_time")),
                "d": d,
            }
        if len(items) < PAGE_SIZE:
            break
        if page % 5 == 4:
            _p(progress, f"语料第 {page + 2} 页…")
    cutoff = (date.today() - timedelta(days=KEEP_VOCAB_DAYS)).isoformat()
    ld["vocab"] = {k: v for k, v in target.items() if (v.get("d") or "") >= cutoff}
    return pages


def _recompute_daily(d):
    daily_map = {}

    def bump(day, key):
        if not day:
            return
        bucket = daily_map.setdefault(day, {"words": 0, "mastered": 0, "vocab": 0})
        bucket[key] += 1

    for ld in d.get("languages", {}).values():
        for rec in (ld.get("words") or {}).values():
            bump(rec.get("d"), "words")
        for rec in (ld.get("mastered") or {}).values():
            bump(rec.get("d"), "mastered")
        for rec in (ld.get("vocab") or {}).values():
            bump(rec.get("d"), "vocab")
    d["daily"] = daily_map


def _sync_language(token, language, d, progress, full=False):
    ld = _lang_data(d, language)
    pages, cap_hit, water = _sync_words(token, language, ld, progress, full)
    m_pages = _sync_mastered(token, language, ld, progress)
    v_pages = _sync_vocab(token, language, ld, progress)
    _p(progress, "汇总每日数据…")
    ld["sync"] = {
        "at": _now(),
        "words": len(ld["words"]),
        "mastered": len(ld["mastered"]),
        "vocab": len(ld["vocab"]),
        "pages": pages + m_pages + v_pages,
        "full": bool(full),
        "cap_hit": bool(cap_hit),
        "water": water,
    }
    return ld["sync"]


def sync_account(aid, progress=None, full=False):
    """同步一个账号；progress(msg) 在调用线程里回调。返回该语言的 sync 摘要。"""
    if not _sync_lock.acquire(blocking=False):
        raise EudicError("已有同步任务在跑，等它结束再试")
    accounts = load_accounts()
    acct = next((a for a in accounts if a.get("id") == aid), None)
    try:
        if acct is None:
            raise EudicError("账号不存在（可能已删除）")
        token = token_of(acct)
        if not token:
            raise EudicError("授权码解不开（换机器/换用户了？），请重新绑定")
        d = load_data(aid)
        language = acct.get("language") or "en"
        _p(progress, f"开始同步「{acct.get('name') or aid}」…")
        info = _sync_language(token, language, d, progress, full)
        _recompute_daily(d)
        d.setdefault("meta", {})["last_sync"] = _now()
        save_data(aid, d)
        acct["last_sync"] = _now()
        acct["last_error"] = ""
        save_accounts(accounts)
        write_log(f"同步成功 · {acct.get('name') or aid} · 生词 {info['words']} / "
                  f"掌握 {info['mastered']} / 语料 {info['vocab']} · {info['pages']} 页")
        return info
    except Exception as e:                          # noqa: BLE001 — 统一记错误
        msg = str(e) or e.__class__.__name__
        if acct is not None:
            acct["last_error"] = msg
            try:
                save_accounts(accounts)
            except OSError:
                pass
        write_log(f"同步失败 · {aid} · {msg}")
        raise
    finally:
        _sync_lock.release()


def sync_all(progress=None, full=False):
    """同步全部账号，返回 [(账号名, ok, 错误信息)]。"""
    result = []
    for acct in load_accounts():
        name = acct.get("name") or acct.get("id")
        try:
            sync_account(acct["id"], progress=progress, full=full)
            result.append((name, True, ""))
        except Exception as e:                      # noqa: BLE001
            result.append((name, False, str(e)))
    return result


def write_log(line):
    p = os.path.join(data_root(), "sync.log")
    try:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "a", encoding="utf-8") as f:
            f.write(f"{_now()} {line}\n")
        if os.path.getsize(p) > 200 * 1024:
            with open(p, "r", encoding="utf-8") as f:
                lines = f.readlines()[-400:]
            with open(p, "w", encoding="utf-8") as f:
                f.writelines(lines)
    except OSError:
        pass


# ------------------------------------------------------------------ 汇总
def _sum_daily(target, source):
    for day, b in (source or {}).items():
        cur = target.setdefault(day, {"words": 0, "mastered": 0, "vocab": 0})
        for k in ("words", "mastered", "vocab"):
            cur[k] += int(b.get(k) or 0)


def _merge_display(target, rec, aid, name):
    key = (rec.get("_lang") or "", (rec.get("w") or "").lower())
    old = target.get(key)
    if old is None:
        item = dict(rec)
        item["_aid"] = aid
        item["_acct"] = name
        target[key] = item
        return
    if rec.get("t") and (not old.get("t") or rec["t"] < old["t"]):
        old["t"], old["d"] = rec["t"], rec["d"]
    if rec.get("star", 0) > old.get("star", 0):
        old["star"] = rec["star"]
    cats = sorted(set(old.get("cats") or []) | set(rec.get("cats") or []))
    if cats:
        old["cats"] = cats
    if not old.get("exp") and rec.get("exp"):
        old["exp"] = rec["exp"]


def _say(text):
    try:
        print(text)
    except Exception:                           # noqa: BLE001 — windowed exe 没有 stdout
        pass


def sync_all_cli(full=False):
    """命令行/计划任务入口：同步全部账号，只写日志 + 控制台。"""
    accounts = load_accounts()
    if not accounts:
        _say("未绑定欧路账号")
        return 0
    ok = 0
    for acct in accounts:
        name = acct.get("name") or acct.get("id")
        _say(f"[{name}] 同步中…")
        try:
            sync_account(acct["id"],
                         progress=lambda m: _say("  " + m), full=full)
            ok += 1
            _say("  完成")
        except Exception as e:                  # noqa: BLE001
            _say(f"  失败：{e}")
    return 0 if ok else 1


def summarize(aids=None):
    """把一个或多个账号合成页面所需的统计。"""
    accounts = load_accounts()
    by_id = {a["id"]: a for a in accounts}
    if aids is None:
        aids = [a["id"] for a in accounts]
    aids = [a for a in aids if a in by_id]

    words = {}
    mastered = set()
    daily_map = {}
    last_sync = ""
    for aid in aids:
        acct = by_id[aid]
        name = acct.get("name") or aid
        d = load_data(aid)
        last_sync = max(last_sync, acct.get("last_sync") or "")
        _sum_daily(daily_map, d.get("daily") or {})
        for language, ld in (d.get("languages") or {}).items():
            for key in (ld.get("mastered") or {}):
                mastered.add((language, key))
            for rec in (ld.get("words") or {}).values():
                item = dict(rec)
                item["_lang"] = language
                _merge_display(words, item, aid, name)

    manual = load_manual()
    today = today_str()
    month_days = []
    start = date.today() - timedelta(days=29)
    for i in range(30):
        day = (start + timedelta(days=i)).isoformat()
        b = daily_map.get(day) or {}
        month_days.append({
            "date": day,
            "words": int(b.get("words") or 0),
            "mastered": int(b.get("mastered") or 0),
            "vocab": int(b.get("vocab") or 0),
        })
    added_30 = sum(d["words"] for d in month_days)
    added_today = int((daily_map.get(today) or {}).get("words") or 0)
    vocab_today = int((daily_map.get(today) or {}).get("vocab") or 0)

    stars = {i: 0 for i in range(1, 6)}
    cats = {}
    for rec in words.values():
        star = rec.get("star") or 0
        if 1 <= star <= 5:
            stars[star] += 1
        names = rec.get("cats") or [rec.get("cat") or "未分类"]
        for name in names:
            cur = cats.setdefault(name or "未分类", {"name": name or "未分类",
                                                     "count": 0, "today": 0})
            cur["count"] += 1
            if rec.get("d") == today:
                cur["today"] += 1

    def active(day):
        b = daily_map.get(day) or {}
        return bool(b.get("words") or b.get("mastered") or b.get("vocab")
                    or manual.get(day, 0))

    cur = date.today()
    if not active(cur.isoformat()):
        cur -= timedelta(days=1)
    streak = 0
    while streak < 3650 and active(cur.isoformat()):
        streak += 1
        cur -= timedelta(days=1)

    recent = sorted(words.values(), key=lambda r: r.get("t") or "", reverse=True)

    return {
        "accounts": [public_account(a) for a in accounts if a["id"] in aids],
        "all_accounts": [public_account(a) for a in accounts],
        "aids": aids,
        "words_total": len(words),
        "mastered_total": len(mastered),
        "added_today": added_today,
        "added_30": added_30,
        "vocab_today": vocab_today,
        "review_today": manual.get(today),
        "streak": streak,
        "days": month_days,
        "stars": stars,
        "cats": sorted(cats.values(), key=lambda c: -c["count"]),
        "recent": recent[:300],
        "last_sync": last_sync,
        "today": today,
        "has_data": bool(words or daily_map),
    }

# 每日任务注册：hub --daily-sync 启动时静态扫这个 DAILY，加数据源不用改 hub.py
def daily_cli():
    """--daily-sync 调用：保持零参，返回 0 表示成功。"""
    return sync_all_cli()

DAILY = {"label": '欧路词典', "func": 'daily_cli', "weight": 60}
