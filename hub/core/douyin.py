# -*- coding: utf-8 -*-
"""抖音账号数据：账号库、导出表解析入库、派生指标。

数据放仓库内 data\\hub\\douyin\\（一个账号一个 json，含 works / daily 两段；
不进 git，重新导入即可复现）。

文件识别靠表头，不靠文件名——用户在后台导出的文件名各地不同：
  · 作品明细：含「作品名称 + 播放量 + 发布时间」
  · 每日指标：含「日期 + 总播放量」或「投稿量」
"""
import json
import os
import re
import statistics
from datetime import date, datetime, timedelta

from . import paths, xlsx

KIND_WORKS = "works"
KIND_DAILY = "daily"
KIND_LABEL = {KIND_WORKS: "作品明细", KIND_DAILY: "每日指标"}

_migrated = False


# ------------------------------------------------------------------ 存储
def data_root():
    global _migrated
    path = paths.data_dir("hub", "douyin")
    if not _migrated:                       # 旧版在 %APPDATA%：首次运行搬过来
        paths.adopt_legacy(paths.legacy_data_dir("douyin"), path)
        _migrated = True
    return str(path)


def _accounts_file():
    return os.path.join(data_root(), "accounts.json")


def _account_file(handle):
    safe = re.sub(r"[^0-9A-Za-z_\-]", "_", str(handle)) or "unknown"
    return os.path.join(data_root(), f"{safe}.json")


def _read_json(path, default):
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _write_json(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def load_accounts():
    data = _read_json(_accounts_file(), {})
    return data.get("accounts", [])


def save_accounts(accounts):
    _write_json(_accounts_file(), {"accounts": accounts})


def add_account(handle, name=""):
    handle = str(handle).strip()
    accounts = load_accounts()
    for a in accounts:
        if a.get("handle") == handle:
            if name:
                a["name"] = name
            save_accounts(accounts)
            return a
    rec = {
        "handle": handle,
        "name": (name or "").strip(),
        "created": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }
    accounts.append(rec)
    save_accounts(accounts)
    return rec


def remove_account(handle):
    accounts = [a for a in load_accounts() if a.get("handle") != handle]
    save_accounts(accounts)
    try:
        os.remove(_account_file(handle))
    except OSError:
        pass


def load(handle):
    data = _read_json(_account_file(handle), {})
    data.setdefault("works", [])
    data.setdefault("daily", [])
    data.setdefault("imports", [])
    return data


def save(handle, data):
    _write_json(_account_file(handle), data)


# ------------------------------------------------------------------ 识别与解析
def detect_kind(rows):
    """看表头判断是作品明细还是每日指标。"""
    if not rows:
        return None
    headers = rows[0]
    has = lambda *names: any(xlsx.col_index(headers, n) is not None for n in names)
    if has("作品名称", "发布日期", "发布时间") and has("播放量"):
        return KIND_WORKS
    if has("日期") and (has("总播放量") or has("投稿量")):
        return KIND_DAILY
    return None


def _s(v):
    return "" if v is None else str(v).strip()


def _date_of(v):
    """'2026-10-29 19:09:10' / '2026-10-29' / datetime -> 'YYYY-MM-DD'"""
    if isinstance(v, (datetime, date)):
        return v.strftime("%Y-%m-%d")
    s = _s(v)
    m = re.match(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", s)
    if m:
        return f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    return ""


def parse_works(rows):
    h = rows[0]
    idx = {
        "title": xlsx.col_index(h, "作品名称", "标题"),
        "published_at": xlsx.col_index(h, "发布时间", "发布时间"),
        "media_type": xlsx.col_index(h, "体裁", "类型"),
        "status": xlsx.col_index(h, "审核状态", "状态"),
        "plays": xlsx.col_index(h, "播放量"),
        "finish_rate": xlsx.col_index(h, "完播率"),
        "finish5_rate": xlsx.col_index(h, "5s完播率", "5秒完播率"),
        "cover_ctr": xlsx.col_index(h, "封面点击率"),
        "bounce2_rate": xlsx.col_index(h, "2s跳出率", "2秒跳出率"),
        "avg_duration": xlsx.col_index(h, "平均播放时长"),
        "likes": xlsx.col_index(h, "点赞量", "点赞"),
        "shares": xlsx.col_index(h, "分享量", "分享"),
        "comments": xlsx.col_index(h, "评论量", "评论"),
        "collects": xlsx.col_index(h, "收藏量", "收藏"),
        "profile_visits": xlsx.col_index(h, "主页访问量", "主页访问"),
        "fans_delta": xlsx.col_index(h, "粉丝增量", "涨粉"),
    }
    if idx["finish_rate"] is not None and idx["finish5_rate"] is not None:
        # 「5s完播率」也含「完播率」四个字，精确列优先，避免串列
        pass
    out = []
    for row in rows[1:]:
        if not row or not any(v not in (None, "") for v in row):
            continue

        def get(key, num=True):
            i = idx.get(key)
            if i is None or i >= len(row):
                return None if num else ""
            return xlsx.to_num(row[i]) if num else _s(row[i])

        title = get("title", num=False)
        published = get("published_at", num=False)
        if not title and not published:
            continue
        plays = get("plays") or 0.0
        out.append({
            "title": title,
            "published_at": published,
            "date": _date_of(published),
            "media_type": get("media_type", num=False),
            "status": get("status", num=False),
            "plays": plays,
            "finish_rate": xlsx.to_ratio(row[idx["finish_rate"]]) if idx["finish_rate"] is not None and idx["finish_rate"] < len(row) else None,
            "finish5_rate": xlsx.to_ratio(row[idx["finish5_rate"]]) if idx["finish5_rate"] is not None and idx["finish5_rate"] < len(row) else None,
            "cover_ctr": xlsx.to_ratio(row[idx["cover_ctr"]]) if idx["cover_ctr"] is not None and idx["cover_ctr"] < len(row) else None,
            "bounce2_rate": xlsx.to_ratio(row[idx["bounce2_rate"]]) if idx["bounce2_rate"] is not None and idx["bounce2_rate"] < len(row) else None,
            "avg_duration": xlsx.to_seconds(row[idx["avg_duration"]]) if idx["avg_duration"] is not None and idx["avg_duration"] < len(row) else None,
            "likes": get("likes") or 0.0,
            "shares": get("shares") or 0.0,
            "comments": get("comments") or 0.0,
            "collects": get("collects") or 0.0,
            "profile_visits": get("profile_visits") or 0.0,
            "fans_delta": get("fans_delta") or 0.0,
        })
    return out


def parse_daily(rows):
    h = rows[0]
    idx = {
        "date": xlsx.col_index(h, "日期"),
        "posts": xlsx.col_index(h, "投稿量", "发布量"),
        "plays": xlsx.col_index(h, "总播放量", "播放量"),
        "likes": xlsx.col_index(h, "总点赞量", "点赞量"),
        "shares": xlsx.col_index(h, "总分享量", "分享量"),
        "comments": xlsx.col_index(h, "总评论量", "评论量"),
        "finish5_rate": xlsx.col_index(h, "5秒完播率", "5s完播率"),
        "bounce2_rate": xlsx.col_index(h, "2秒跳出率", "2s跳出率"),
        "cover_ctr": xlsx.col_index(h, "封面点击率"),
        "avg_duration": xlsx.col_index(h, "平均播放时长"),
    }
    out = []
    for row in rows[1:]:
        if not row:
            continue
        d = _date_of(row[idx["date"]]) if idx["date"] is not None and idx["date"] < len(row) else ""
        if not d:
            continue

        def num(key):
            i = idx.get(key)
            if i is None or i >= len(row):
                return None
            return xlsx.to_num(row[i])

        def ratio(key):
            i = idx.get(key)
            if i is None or i >= len(row):
                return None
            return xlsx.to_ratio(row[i])

        def secs(key):
            i = idx.get(key)
            if i is None or i >= len(row):
                return None
            return xlsx.to_seconds(row[i])

        out.append({
            "date": d,
            "posts": num("posts") or 0.0,
            "plays": num("plays") or 0.0,
            "likes": num("likes") or 0.0,
            "shares": num("shares") or 0.0,
            "comments": num("comments") or 0.0,
            "finish5_rate": ratio("finish5_rate"),
            "bounce2_rate": ratio("bounce2_rate"),
            "cover_ctr": ratio("cover_ctr"),
            "avg_duration": secs("avg_duration"),
        })
    return out


def find_header(rows, limit=8):
    """导出表第一行经常是标题/说明；往下找真正含表头的那一行。"""
    for i, row in enumerate(rows[:limit]):
        if detect_kind([row]):
            return i
    return 0


def import_file(path, handle):
    """把一个导出表并进账号库，返回 (kind, 新增, 更新) 。"""
    rows = xlsx.read_sheet(path)
    start = find_header(rows)
    if start:
        rows = rows[start:]
    kind = detect_kind(rows)
    if kind is None:
        raise ValueError("认不出这个表：需要「作品名称+播放量」或「日期+总播放量」的表头")

    data = load(handle)
    added = updated = 0
    if kind == KIND_WORKS:
        incoming = parse_works(rows)
        index = {(w.get("published_at"), w.get("title")): i
                 for i, w in enumerate(data["works"])}
        for w in incoming:
            key = (w.get("published_at"), w.get("title"))
            if key in index:
                data["works"][index[key]] = w
                updated += 1
            else:
                index[key] = len(data["works"])
                data["works"].append(w)
                added += 1
        data["works"].sort(key=lambda w: w.get("published_at") or "", reverse=True)
    else:
        incoming = parse_daily(rows)
        index = {d["date"]: i for i, d in enumerate(data["daily"])}
        for d in incoming:
            if d["date"] in index:
                data["daily"][index[d["date"]]] = d
                updated += 1
            else:
                index[d["date"]] = len(data["daily"])
                data["daily"].append(d)
                added += 1
        data["daily"].sort(key=lambda d: d["date"])

    data["imports"].append({
        "file": os.path.basename(path),
        "kind": kind,
        "at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "rows": len(incoming),
    })
    data["imports"] = data["imports"][-40:]
    save(handle, data)
    return kind, added, updated


# ------------------------------------------------------------------ 自动同步写入
# 创作者中心「账号概览」的指标名 -> 本模块 daily 字段
DASH_FIELDS = {
    "publish_cnt": "posts", "publish_count": "posts", "item_cnt": "posts",
    "aweme_cnt": "posts", "publish_activation": "posts",
    "vv": "plays", "play_count": "plays", "play_cnt": "plays",
    "total_play": "plays", "total_play_count": "plays",
    "like": "likes", "like_count": "likes", "digg_count": "likes", "digg_cnt": "likes",
    "share": "shares", "share_count": "shares", "share_cnt": "shares",
    "comment": "comments", "comment_count": "comments", "comment_cnt": "comments",
    "completion_rate_5s": "finish5_rate", "finish5s": "finish5_rate",
    "completion_rate": "finish5_rate",
    "bounce_rate_2s": "bounce2_rate", "skip2s": "bounce2_rate",
    "cover_click_ratio": "cover_ctr", "cover_click_rate": "cover_ctr",
    "average_play_duration": "avg_duration", "play_avg_time": "avg_duration",
    "avg_play_time": "avg_duration", "avg_view_second": "avg_duration",
}
RATIO_FIELDS = {"finish5_rate", "bounce2_rate", "cover_ctr"}
DAILY_ZERO = {"date": "", "posts": 0.0, "plays": 0.0, "likes": 0.0,
              "shares": 0.0, "comments": 0.0, "finish5_rate": None,
              "bounce2_rate": None, "cover_ctr": None, "avg_duration": None}


def _dash_key(name):
    s = re.sub(r"[^a-z0-9]+", "_", str(name or "").strip().lower()).strip("_")
    return DASH_FIELDS.get(s)


def _dash_date(v):
    if isinstance(v, (int, float)) and v > 1_000_000_000:
        try:
            return datetime.fromtimestamp(v).strftime("%Y-%m-%d")
        except (OverflowError, OSError, ValueError):
            return ""
    s = str(v or "").strip()
    m = re.match(r"^(\d{4})(\d{2})(\d{2})$", s)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    return _date_of(s)


def _dash_value(field, v):
    if v is None:
        return None
    if isinstance(v, str):
        s = v.strip()
        if not s or s in ("-", "—", "--", "/"):
            return None
        if s.endswith("%"):
            try:
                v = float(s[:-1]) / 100.0
            except ValueError:
                return None
        else:
            try:
                v = float(s.replace(",", ""))
            except ValueError:
                return None
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    if field in RATIO_FIELDS and v > 1.5:      # 接口偶尔给 28.64 而不是 0.2864
        v /= 100.0
    return v


def merge_dashboard(handle, metrics, at=None):
    """把 /overview/dashboard 的 metrics[].trends[] 并进 daily，返回写入天数。"""
    if isinstance(metrics, dict):
        metrics = [metrics]
    data = load(handle)
    rows = {d["date"]: d for d in data["daily"] if d.get("date")}
    touched = set()
    for m in metrics or []:
        if not isinstance(m, dict):
            continue
        field = _dash_key(m.get("english_metric_name") or m.get("metric_name")
                          or m.get("key"))
        if not field:
            continue
        for t in m.get("trends") or []:
            if not isinstance(t, dict):
                continue
            day = _dash_date(t.get("date_time") or t.get("date"))
            if not day:
                continue
            val = _dash_value(field, t.get("value"))
            if val is None:
                continue
            row = rows.get(day)
            if row is None:
                row = dict(DAILY_ZERO, date=day)
                rows[day] = row
                data["daily"].append(row)
            row[field] = val
            touched.add(day)
    if touched:
        data["daily"].sort(key=lambda d: d.get("date") or "")
        data["imports"].append({
            "file": "创作者中心 · 账号概览",
            "kind": KIND_DAILY,
            "at": at or datetime.now().strftime("%Y-%m-%d %H:%M"),
            "rows": len(touched),
        })
        data["imports"] = data["imports"][-40:]
        save(handle, data)
    return len(touched)


def _metric_latest(m):
    """取一个指标的当前值：优先 metric_value，其次 trends 最后一天。"""
    if not isinstance(m, dict):
        return None
    v = m.get("metric_value")
    if v is None:
        trends = [t for t in (m.get("trends") or []) if isinstance(t, dict)]
        if trends:
            v = trends[-1].get("value")
    return v


def merge_profile(handle, metrics, at=None):
    """粉丝概览：存总粉丝等账号级数字，供页面展示。"""
    if isinstance(metrics, dict):
        metrics = [metrics]
    got = {}
    for m in metrics or []:
        if not isinstance(m, dict):
            continue
        raw = str(m.get("english_metric_name") or m.get("metric_name") or "")
        key = re.sub(r"[^a-z0-9]+", "_", raw.strip().lower()).strip("_")
        v = _metric_latest(m)
        val = _dash_value("", v)
        if val is None:
            continue
        if key in ("total_fans_cnt", "fans_all", "total_fans"):
            got["fans"] = int(round(val))
        elif key in ("net_fans_cnt", "net_follow_fans"):
            got["fans_delta"] = int(round(val))
        elif key in ("increase_fans_cnt", "new_fans_cnt", "follow_fans_cnt"):
            got["fans_new"] = int(round(val))
    if not got:
        return 0
    data = load(handle)
    prof = data.get("profile") or {}
    prof.update(got)
    prof["updated"] = at or datetime.now().strftime("%Y-%m-%d %H:%M")
    data["profile"] = prof
    save(handle, data)
    return len(got)


# 创作者中心 item/list 的 type -> 体裁（实测：8 长图文 / 1 图文 / 2~5 视频时长档）
TYPE_MEDIA = {1: "图文", 2: "1min-视频", 3: "1-3min视频", 4: "3-5min视频",
              5: "5min+视频", 8: "长图文"}


def _f(v, default=0.0):
    try:
        if v is None or (isinstance(v, str) and not v.strip()):
            return default
        return float(str(v).replace(",", "").strip())
    except (TypeError, ValueError):
        return default


def _item_to_work(item):
    """item/list 或 work_list 的一条 -> 本模块 works 的一条（两种字段名都认）。"""
    if not isinstance(item, dict):
        return None
    metrics = item.get("metrics") or {}
    stats = item.get("statistics") or item.get("stats") or {}

    def m(*names):
        for n in names:
            if isinstance(metrics, dict) and metrics.get(n) not in (None, ""):
                return _f(metrics.get(n))
            if isinstance(stats, dict) and stats.get(n) not in (None, ""):
                return _f(stats.get(n))
        return None

    created = item.get("create_time") or item.get("publish_time")
    if isinstance(created, str) and created.isdigit():
        created = int(created)
    try:
        dt = datetime.fromtimestamp(int(created)) if created else None
    except (TypeError, ValueError, OverflowError, OSError):
        dt = None
    title = item.get("description") or item.get("desc") or item.get("title") or ""
    if not title and not dt:
        return None

    media = TYPE_MEDIA.get(item.get("type"))
    if not media:
        media = ("图文" if item.get("images") else "视频")
    status = "公开" if (item.get("review") or {}).get("status") in (None, 2) else "未公开"

    plays = m("view_count", "play_count", "play_cnt")
    likes = m("like_count", "digg_count") or 0.0
    shares = m("share_count") or 0.0
    comments = m("comment_count") or 0.0
    collects = m("favorite_count", "collect_count") or 0.0
    profile = m("homepage_visit_count", "profile_visit_count") or 0.0
    fans = m("fans_delta")
    if fans is None:
        fans = (m("subscribe_count") or 0.0) - (m("unsubscribe_count") or 0.0)

    return {
        "aweme_id": str(item.get("id") or item.get("aweme_id") or ""),
        "title": str(title).strip(),
        "published_at": dt.strftime("%Y-%m-%d %H:%M:%S") if dt else "",
        "date": dt.strftime("%Y-%m-%d") if dt else "",
        "media_type": media,
        "status": status,
        "plays": plays or 0.0,
        "finish_rate": m("completion_rate"),
        "finish5_rate": m("completion_rate_5s"),
        "cover_ctr": m("cover_click_rate", "cover_click_ratio"),
        "bounce2_rate": m("bounce_rate_2s"),
        "avg_duration": m("avg_view_second", "average_play_duration"),
        "likes": likes,
        "shares": shares,
        "comments": comments,
        "collects": collects,
        "profile_visits": profile,
        "fans_delta": fans,
    }


def replace_works(handle, items, at=None):
    """用接口返回的完整作品列表替换本地 works（接口一次拉全时用，能清掉已删/改名的旧条目）。"""
    works = [_item_to_work(i) for i in items or []]
    works = [w for w in works if w]
    if not works:
        return 0, 0
    data = load(handle)
    before = {(w.get("published_at"), w.get("title")) for w in data["works"]}
    after = {(w.get("published_at"), w.get("title")) for w in works}
    added = len(after - before)
    updated = len(after & before)
    data["works"] = sorted(works, key=lambda w: w.get("published_at") or "",
                           reverse=True)
    data["imports"].append({
        "file": "创作者中心 · 作品列表（接口全量）",
        "kind": KIND_WORKS,
        "at": at or datetime.now().strftime("%Y-%m-%d %H:%M"),
        "rows": len(works),
    })
    data["imports"] = data["imports"][-40:]
    save(handle, data)
    return added, updated


def merge_aweme_works(handle, items):
    """JSON 兜底：把 item/list 或 work_list 里的作品并进 works，返回 (新增, 更新)。"""
    data = load(handle)
    index = {(w.get("published_at"), w.get("title")): i
             for i, w in enumerate(data["works"])}
    added = updated = 0
    for item in items or []:
        w = _item_to_work(item)
        if not w:
            continue
        key = (w["published_at"], w["title"])
        if key in index:
            data["works"][index[key]] = w
            updated += 1
        else:
            index[key] = len(data["works"])
            data["works"].append(w)
            added += 1
    if added or updated:
        data["works"].sort(key=lambda w: w.get("published_at") or "", reverse=True)
        data["imports"].append({
            "file": "创作者中心 · 作品列表（接口）",
            "kind": KIND_WORKS,
            "at": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "rows": added + updated,
        })
        data["imports"] = data["imports"][-40:]
        save(handle, data)
    return added, updated


# ------------------------------------------------------------------ 派生指标
def _nums(works, key):
    vals = [w.get(key) for w in works]
    return [v for v in vals if isinstance(v, (int, float))]


def _fmt_int(n):
    try:
        return f"{int(round(n)):,}"
    except (TypeError, ValueError):
        return "-"


def _pct(v, digits=1):
    if v is None:
        return "-"
    return f"{v * 100:.{digits}f}%"


def summarize(handles):
    """把一个或多个账号的作品/每日数据合成一份统计（融合视图就是多账号求和）。"""
    works, daily, imports = [], [], []
    for h in handles:
        d = load(h)
        for w in d["works"]:
            w = dict(w)
            w["_handle"] = h
            works.append(w)
        for row in d["daily"]:
            row = dict(row)
            row["_handle"] = h
            daily.append(row)
        imports.extend(d.get("imports", []))

    works.sort(key=lambda w: w.get("published_at") or "", reverse=True)
    total_plays = sum(w.get("plays") or 0 for w in works)
    plays_list = _nums(works, "plays")

    # 每日序列：优先用「每日指标」表，没有就按作品发布日期汇总
    series = {}
    for row in daily:
        d = row["date"]
        cur = series.setdefault(d, {"date": d, "plays": 0.0, "posts": 0.0,
                                    "likes": 0.0, "comments": 0.0, "shares": 0.0})
        for k in ("plays", "posts", "likes", "comments", "shares"):
            cur[k] += row.get(k) or 0
    if not series:
        for w in works:
            d = w.get("date") or ""
            if not d:
                continue
            cur = series.setdefault(d, {"date": d, "plays": 0.0, "posts": 0.0,
                                        "likes": 0.0, "comments": 0.0, "shares": 0.0})
            cur["plays"] += w.get("plays") or 0
            cur["posts"] += 1
    days = [series[k] for k in sorted(series)]

    finish = _nums(works, "finish_rate")
    finish5 = _nums(works, "finish5_rate")
    weighted = None
    pairs = [(w.get("finish_rate"), w.get("plays") or 0) for w in works
             if isinstance(w.get("finish_rate"), (int, float)) and (w.get("plays") or 0) > 0]
    if pairs:
        denom = sum(p for _, p in pairs)
        if denom:
            weighted = sum(r * p for r, p in pairs) / denom

    likes = sum(w.get("likes") or 0 for w in works)
    comments = sum(w.get("comments") or 0 for w in works)
    shares = sum(w.get("shares") or 0 for w in works)
    collects = sum(w.get("collects") or 0 for w in works)
    fans = sum(w.get("fans_delta") or 0 for w in works)
    profile = sum(w.get("profile_visits") or 0 for w in works)
    engage = (likes + comments + shares + collects) / total_plays if total_plays else 0.0

    media = {}
    for w in works:
        key = w.get("media_type") or "未标"
        media[key] = media.get(key, 0) + 1

    top = sorted(works, key=lambda w: w.get("plays") or 0, reverse=True)[:10]

    today = date.today()
    last7 = [d for d in days if _as_date(d["date"]) and
             (today - _as_date(d["date"])).days < 7]
    prev7 = [d for d in days if _as_date(d["date"]) and
             7 <= (today - _as_date(d["date"])).days < 14]
    plays7 = sum(d["plays"] for d in last7)
    plays_prev7 = sum(d["plays"] for d in prev7)
    trend = ((plays7 - plays_prev7) / plays_prev7) if plays_prev7 else None

    last_publish = works[0].get("published_at") if works else ""
    gap_days = None
    if last_publish:
        d = _as_date(_date_of(last_publish))
        if d:
            gap_days = (today - d).days

    # 按自然日补齐（趋势图别断档）
    filled = []
    if days:
        start = _as_date(days[0]["date"])
        end = _as_date(days[-1]["date"])
        if start and end:
            cur = start
            by_day = {d["date"]: d for d in days}
            while cur <= end:
                key = cur.strftime("%Y-%m-%d")
                filled.append(by_day.get(key, {"date": key, "plays": 0.0, "posts": 0.0,
                                               "likes": 0.0, "comments": 0.0,
                                               "shares": 0.0}))
                cur += timedelta(days=1)

    return {
        "handles": list(handles),
        "works": works,
        "days": filled,
        "imports": sorted(imports, key=lambda x: x.get("at") or "")[-1:] if imports else [],
        "count": len(works),
        "total_plays": total_plays,
        "avg_plays": (total_plays / len(plays_list)) if plays_list else 0.0,
        "median_plays": statistics.median(plays_list) if plays_list else 0.0,
        "max_plays": max(plays_list) if plays_list else 0.0,
        "likes": likes, "comments": comments, "shares": shares,
        "collects": collects, "fans": fans, "profile_visits": profile,
        "engage_rate": engage,
        "finish_avg": (sum(finish) / len(finish)) if finish else None,
        "finish_weighted": weighted,
        "finish5_avg": (sum(finish5) / len(finish5)) if finish5 else None,
        "media": media,
        "top": top,
        "plays_last7": plays7,
        "plays_prev7": plays_prev7,
        "trend": trend,
        "last_publish": last_publish,
        "gap_days": gap_days,
        "top1_share": ((max(plays_list) / total_plays) if plays_list and total_plays else None),
        "fmt_int": _fmt_int,
        "fmt_pct": _pct,
    }


def _as_date(s):
    try:
        return datetime.strptime(s[:10], "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None
