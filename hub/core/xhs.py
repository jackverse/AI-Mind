# -*- coding: utf-8 -*-
"""小红书账号数据：账号库、导出表解析入库、派生指标。

数据放仓库内 data\\hub\\xhs\\（一个账号一个 json，含 notes / daily / summary 三段；
不进 git，重新导入即可复现）。

**识别靠表头与工作表名，不靠文件名**——创作者中心能导出三类表：
  · 笔记明细：表头含「笔记标题 + 观看量 + 曝光」；首行常带「最多导出排序后前1000条笔记」横幅
  · 账户汇总：表头为「指标 / 数值」；指标名带单位与「环比」后缀
  · 指标趋势：表头为「日期 / 数值」；**工作表名**就是指标名（「曝光趋势」「点赞趋势」……）

四张 30 天表（观看/互动/涨粉/发布）各含 1 张汇总 + N 张趋势，导入时自动合并进
同一份 daily（按日期并集）与 summary（按指标并集），重复导入按日期/笔记覆盖。
"""
import json
import os
import re
import statistics
from datetime import date, datetime, timedelta

from . import paths, xlsx

KIND_NOTES = "notes"
KIND_SUMMARY = "summary"
KIND_TREND = "trend"
KIND_LABEL = {KIND_NOTES: "笔记明细", KIND_SUMMARY: "账户指标", KIND_TREND: "指标趋势"}

# ------------------------------------------------------------------ 指标字典
# key -> 中文名；顺序即展示顺序（近 30 天指标条按这个排）
METRICS = {
    "exposure": "曝光",
    "views": "观看",
    "cover_ctr": "封面点击率",
    "avg_watch": "平均观看时长",
    "watch_total": "总观看时长",
    "finish_rate": "完播率",
    "likes": "点赞",
    "comments": "评论",
    "collects": "收藏",
    "shares": "分享",
    "fans_net": "净涨粉",
    "fans_new": "新增关注",
    "fans_lost": "取消关注",
    "profile_visits": "主页访客",
    "follow_rate": "主页转粉率",
    "posts": "总发布",
    "posts_video": "发布视频",
    "posts_figure": "发布图文",
}
ORDER = list(METRICS)

# 比率型（存 0~1 小数）；时长型（存秒）；其余是计数
PCT_KEYS = {"cover_ctr", "finish_rate", "follow_rate"}
SEC_KEYS = {"avg_watch", "watch_total"}

ALIASES = {
    "曝光": "exposure",
    "观看": "views",
    "封面点击率": "cover_ctr",
    "平均观看时长": "avg_watch",
    "总观看时长": "watch_total",
    "观看总时长": "watch_total",
    "总完播率": "finish_rate",
    "视频完播率": "finish_rate",
    "完播率": "finish_rate",
    "点赞": "likes",
    "评论": "comments",
    "收藏": "collects",
    "分享": "shares",
    "净涨粉": "fans_net",
    "新增关注": "fans_new",
    "取消关注": "fans_lost",
    "主页访客": "profile_visits",
    "主页转粉率": "follow_rate",
    "总发布": "posts",
    "发布视频": "posts_video",
    "发布图文": "posts_figure",
}

# 融合多账号时，比率型指标按谁加权
WEIGHT_OF = {
    "cover_ctr": "exposure",
    "avg_watch": "views",
    "finish_rate": "views",
    "follow_rate": "profile_visits",
}

RE_CN_DT = re.compile(
    r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日"
    r"(?:\s*(\d{1,2})\s*时\s*(\d{1,2})\s*分(?:\s*(\d{1,2})\s*秒)?)?")
RE_ISO = re.compile(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})")

_migrated = False


# ------------------------------------------------------------------ 存储
def data_root():
    global _migrated
    path = paths.data_dir("hub", "xhs")
    if not _migrated:
        paths.adopt_legacy(paths.legacy_data_dir("xhs"), path)
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
    return _read_json(_accounts_file(), {}).get("accounts", [])


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
    data.setdefault("notes", [])
    data.setdefault("daily", {})
    data.setdefault("summary", {})
    data.setdefault("summary_delta", {})
    data.setdefault("imports", [])
    return data


def save(handle, data):
    _write_json(_account_file(handle), data)


# ------------------------------------------------------------------ 解析工具
def _s(v):
    return "" if v is None else str(v).strip()


def _norm_label(s):
    """指标名归一：去单位括号、去「环比」、去空格与全角括号。"""
    s = _s(s).replace("（", "(").replace("）", ")")
    s = re.sub(r"\(.*?\)", "", s)
    s = s.replace("环比", "")
    return s.replace(" ", "").strip()


def metric_of(label):
    """表头/工作表名 -> 指标 key。"""
    name = _norm_label(label)
    if name in ALIASES:
        return name and ALIASES[name]
    for alias, key in ALIASES.items():          # 容忍「视频完播率趋势」这类长尾
        if name.endswith(alias):
            return key
    return None


def _is_delta(label):
    return "环比" in _s(label)


def _date_of(v):
    """'2026年10月29日' / '2026-10-29 19:09:10' / date -> 'YYYY-MM-DD'"""
    if isinstance(v, (datetime, date)):
        return v.strftime("%Y-%m-%d")
    s = _s(v)
    m = RE_CN_DT.match(s)
    if m:
        return f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    m = RE_ISO.match(s)
    if m:
        return f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    return ""


def _datetime_of(v):
    """中文时间 -> 'YYYY-MM-DD HH:MM:SS'（排序与展示都用它）。"""
    s = _s(v)
    m = RE_CN_DT.match(s)
    if not m:
        return s
    g = [int(x) if x else 0 for x in m.groups()]
    return f"{g[0]:04d}-{g[1]:02d}-{g[2]:02d} {g[3]:02d}:{g[4]:02d}:{g[5]:02d}"


def _value(key, raw):
    """单元格 -> canonical 值。比率折 0~1，时长折秒，其余数字。"""
    if raw is None:
        return None
    text = _s(raw)
    if not text or text in ("-", "—", "--", "/", "N/A"):
        return None
    if key in PCT_KEYS:
        if text.endswith("%"):
            return xlsx.to_num(text)               # to_num 已把 % 折成小数
        n = xlsx.to_num(text)                      # 汇总表里 11.3 = 11.3%
        return None if n is None else n / 100.0
    if key in SEC_KEYS:
        return xlsx.to_seconds(text)
    return xlsx.to_num(text)


def _delta_value(raw):
    """环比一律是百分比：28 -> 0.28，'-25' -> -0.25，'12%' -> 0.12。"""
    text = _s(raw)
    if not text or text in ("-", "—", "--", "/"):
        return None
    if text.endswith("%"):
        return xlsx.to_num(text)
    n = xlsx.to_num(text)
    return None if n is None else n / 100.0


def _ratio(v):
    """笔记明细里的比率：0.116 与 '11.6%' 都认，裸数字 >1.5 视作百分数。"""
    n = xlsx.to_num(v)
    if n is None:
        return None
    return n / 100.0 if n > 1.5 else n


# ------------------------------------------------------------------ 表识别
def sheet_kind(rows):
    """看前几行表头判断工作表类型，返回 (kind, 表头行号)；认不出返回 (None, None)。

    笔记明细的上面常有一行「最多导出排序后前1000条笔记」横幅，所以要往下找几行。
    """
    for i, row in enumerate(rows[:8]):
        cells = [_s(c).replace(" ", "") for c in row]
        if not any(cells):
            continue

        def has(name):
            return any(name in c for c in cells)

        if has("笔记标题") and (has("观看量") or has("曝光")):
            return KIND_NOTES, i
        if has("指标") and has("数值"):
            return KIND_SUMMARY, i
        if has("日期") and has("数值"):
            return KIND_TREND, i
    return None, None


def parse_notes(rows, header_row=0):
    h = rows[header_row]
    idx = {
        "title": xlsx.col_index(h, "笔记标题", "标题"),
        "published": xlsx.col_index(h, "首次发布时间", "发布时间"),
        "media_type": xlsx.col_index(h, "体裁", "类型"),
        "exposure": xlsx.col_index(h, "曝光"),
        "views": xlsx.col_index(h, "观看量", "观看"),
        "cover_ctr": xlsx.col_index(h, "封面点击率"),
        "likes": xlsx.col_index(h, "点赞"),
        "comments": xlsx.col_index(h, "评论"),
        "collects": xlsx.col_index(h, "收藏"),
        "fans": xlsx.col_index(h, "涨粉"),
        "shares": xlsx.col_index(h, "分享"),
        "avg_watch": xlsx.col_index(h, "人均观看时长"),
        "danmaku": xlsx.col_index(h, "弹幕"),
    }

    out = []
    for row in rows[header_row + 1:]:
        if not row or not any(v not in (None, "") for v in row):
            continue

        def raw(key):
            i = idx.get(key)
            if i is None or i >= len(row):
                return None
            return row[i]

        published = _datetime_of(raw("published"))
        title = _s(raw("title"))
        if not published and not title:
            continue
        out.append({
            "title": title,
            "published_at": published,
            "date": _date_of(published),
            "media_type": _s(raw("media_type")) or "未标",
            "exposure": xlsx.to_num(raw("exposure")) or 0.0,
            "views": xlsx.to_num(raw("views")) or 0.0,
            "cover_ctr": _ratio(raw("cover_ctr")),
            "likes": xlsx.to_num(raw("likes")) or 0.0,
            "comments": xlsx.to_num(raw("comments")) or 0.0,
            "collects": xlsx.to_num(raw("collects")) or 0.0,
            "fans": xlsx.to_num(raw("fans")) or 0.0,
            "shares": xlsx.to_num(raw("shares")) or 0.0,
            "avg_watch": xlsx.to_seconds(raw("avg_watch")),
            "danmaku": xlsx.to_num(raw("danmaku")) or 0.0,
        })
    return out


def parse_summary(rows, header_row=0):
    """「指标 / 数值」两列 -> ({key: value}, {key: 环比小数})"""
    summary, delta = {}, {}
    for row in rows[header_row + 1:]:
        if not row:
            continue
        label = _s(row[0]) if len(row) > 0 else ""
        if not label or label == "指标":
            continue
        key = metric_of(label)
        if key is None:
            continue
        raw = row[1] if len(row) > 1 else None
        if _is_delta(label):
            v = _delta_value(raw)
            if v is not None:
                delta[key] = v
        else:
            v = _value(key, raw)
            if v is not None:
                summary[key] = v
    return summary, delta


def parse_trend(rows, header_row=0):
    """「日期 / 数值」两列 -> [(date, value)]"""
    out = []
    for row in rows[header_row + 1:]:
        if not row:
            continue
        d = _date_of(row[0]) if len(row) > 0 else ""
        if not d:
            continue
        v = row[1] if len(row) > 1 else None
        out.append((d, v))
    return out


# ------------------------------------------------------------------ 导入
def import_file(path, handle):
    """把一个导出表并进账号库，返回说明用的 dict。认不出来抛 ValueError。"""
    names = xlsx.sheet_names(path)
    data = load(handle)
    before = set(data["daily"])
    info = {"file": os.path.basename(path), "sheets": [], "notes": [0, 0],
            "metrics": 0, "trends": 0, "new_dates": 0, "skipped": []}
    seen = False

    for name in names:
        rows = xlsx.read_sheet(path, name)
        kind, hdr = sheet_kind(rows)
        if kind is None:
            info["skipped"].append(name)
            continue
        seen = True
        info["sheets"].append(f"{name}（{KIND_LABEL[kind]}）")

        if kind == KIND_NOTES:
            incoming = parse_notes(rows, hdr)
            index = {(n.get("published_at"), n.get("title")): i
                     for i, n in enumerate(data["notes"])}
            added = updated = 0
            for n in incoming:
                key = (n.get("published_at"), n.get("title"))
                if key in index:
                    data["notes"][index[key]] = n
                    updated += 1
                else:
                    index[key] = len(data["notes"])
                    data["notes"].append(n)
                    added += 1
            data["notes"].sort(key=lambda n: n.get("published_at") or "",
                               reverse=True)
            info["notes"] = [added, updated]

        elif kind == KIND_SUMMARY:
            summary, delta = parse_summary(rows, hdr)
            data["summary"].update(summary)
            data["summary_delta"].update(delta)
            info["metrics"] += len(summary)

        else:                                    # trend
            key = metric_of(re.sub(r"趋势$", "", name))
            if key is None:
                info["skipped"].append(name)
                continue
            served = 0
            for d, raw in parse_trend(rows, hdr):
                v = _value(key, raw)
                if v is None:
                    continue
                data["daily"].setdefault(d, {})[key] = v
                served += 1
            if served:
                info["trends"] += 1

    if not seen:
        raise ValueError("认不出这个表：需要「笔记标题+观看量」、"
                         "「指标+数值」或「日期+数值」的表头")

    info["new_dates"] = len(set(data["daily"]) - before)
    if data["daily"]:
        dates = sorted(data["daily"])
        data["window"] = [dates[0], dates[-1]]

    data["imports"].append({
        "file": os.path.basename(path),
        "at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "sheets": len(info["sheets"]),
        "notes": info["notes"][0] + info["notes"][1],
    })
    data["imports"] = data["imports"][-40:]
    save(handle, data)
    return info


# ------------------------------------------------------------------ 派生指标
def _fmt_int(n):
    try:
        return f"{int(round(n)):,}"
    except (TypeError, ValueError):
        return "-"


def _fmt_pct(v, digits=1):
    if v is None:
        return "-"
    return f"{v * 100:.{digits}f}%"


def _fmt_sec(v):
    if v is None:
        return "-"
    if v >= 3600:
        return f"{v / 3600:.1f} 小时"
    if v >= 60:
        return f"{v / 60:.1f} 分"
    return f"{v:.1f} 秒"


def fmt_metric(key, v):
    """近 30 天指标条用的格式化。"""
    if v is None:
        return "-"
    if key in PCT_KEYS:
        return _fmt_pct(v)
    if key == "watch_total":
        return _fmt_sec(v)
    if key == "avg_watch":
        return _fmt_sec(v)
    return _fmt_int(v)


def _as_date(s):
    try:
        return datetime.strptime(str(s)[:10], "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def _weighted(values, weights):
    pairs = [(v, w) for v, w in zip(values, weights)
             if isinstance(v, (int, float)) and isinstance(w, (int, float)) and w > 0]
    if not pairs:
        return None
    denom = sum(w for _, w in pairs)
    return sum(v * w for v, w in pairs) / denom if denom else None


def summarize(handles):
    """把一个或多个账号的笔记/每日/汇总合成一份（融合视图 = 多账号求和）。"""
    notes, daily, summary, delta, imports = [], {}, {}, {}, []
    per_summary = []
    window = ["", ""]

    for h in handles:
        d = load(h)
        for n in d.get("notes", []):
            n = dict(n)
            n["_handle"] = h
            notes.append(n)
        for day, rec in (d.get("daily") or {}).items():
            cur = daily.setdefault(day, {"date": day})
            for k, v in rec.items():
                if isinstance(v, (int, float)):
                    cur[k] = (cur.get(k) or 0) + v
                else:
                    cur.setdefault(k, v)
        per_summary.append((h, d.get("summary") or {}, d.get("summary_delta") or {}))
        imports.extend(d.get("imports", []))
        for key in ("summary_delta",):
            delta.update(d.get(key) or {})
        win = d.get("window") or ["", ""]
        if win[0]:
            window[0] = min(window[0] or win[0], win[0])
            window[1] = max(window[1] or win[1], win[1])

    notes.sort(key=lambda n: n.get("published_at") or "", reverse=True)

    # 汇总合并：计数求和，比率按权重
    all_keys = set()
    for _, s, _ in per_summary:
        all_keys.update(s)
    for key in all_keys:
        vals = [(s.get(key), s) for _, s, _ in per_summary]
        if key in PCT_KEYS:
            weight_key = WEIGHT_OF.get(key)
            merged = _weighted([v for v, _ in vals],
                               [(s.get(weight_key) or 0) for _, s in vals])
            if merged is None:
                got = [v for v, _ in vals if isinstance(v, (int, float))]
                merged = (sum(got) / len(got)) if got else None
        else:
            got = [v for v, _ in vals if isinstance(v, (int, float))]
            merged = sum(got) if got else None
        if merged is not None:
            summary[key] = merged
    if len(handles) > 1:
        delta = {}
        for key in summary:
            got = [d[key] for _, _, d in per_summary if isinstance(d.get(key), (int, float))]
            delta[key] = (sum(got) / len(got)) if got else None

    tot = {}
    for key in ("exposure", "views", "likes", "comments", "collects",
                "shares", "fans", "danmaku"):
        tot[key] = sum(n.get(key) or 0 for n in notes)

    # 封面点击率：按曝光的加权平均（笔记级）
    ctr = _weighted([n.get("cover_ctr") for n in notes],
                    [n.get("exposure") or 0 for n in notes])
    if ctr is None:
        ctr = _weighted([n.get("cover_ctr") for n in notes], [1] * len(notes))

    engage = ((tot["likes"] + tot["comments"] + tot["collects"] + tot["shares"])
              / tot["views"]) if tot["views"] else 0.0

    # 每日序列：优先用 30 天趋势；没有就按笔记发布日期汇总
    series = sorted(daily.values(), key=lambda d: d["date"])
    if not series:
        buckets = {}
        for n in notes:
            if not n.get("date"):
                continue
            cur = buckets.setdefault(n["date"], {"date": n["date"]})
            for k in ("exposure", "views", "likes", "comments", "collects",
                      "shares", "fans"):
                cur[k] = (cur.get(k) or 0) + (n.get(k) or 0)
            cur["posts"] = (cur.get("posts") or 0) + 1
        series = [buckets[k] for k in sorted(buckets)]

    # 按自然日补齐（趋势图别断档）
    days = []
    if series:
        start, end = _as_date(series[0]["date"]), _as_date(series[-1]["date"])
        if start and end:
            by_day = {d["date"]: d for d in series}
            cur = start
            while cur <= end:
                key = cur.strftime("%Y-%m-%d")
                days.append(by_day.get(key, {"date": key}))
                cur += timedelta(days=1)

    today = date.today()
    last7 = [d for d in days if _as_date(d["date"]) and
             0 <= (today - _as_date(d["date"])).days < 7]
    prev7 = [d for d in days if _as_date(d["date"]) and
             7 <= (today - _as_date(d["date"])).days < 14]
    views7 = sum(d.get("views") or 0 for d in last7)
    views_prev7 = sum(d.get("views") or 0 for d in prev7)
    trend = ((views7 - views_prev7) / views_prev7) if views_prev7 else None

    media = {}
    for n in notes:
        key = n.get("media_type") or "未标"
        media[key] = media.get(key, 0) + 1

    top = sorted(notes, key=lambda n: n.get("views") or 0, reverse=True)[:10]

    last_publish = notes[0].get("published_at") if notes else ""
    gap_days = None
    if last_publish:
        d = _as_date(_date_of(last_publish))
        if d:
            gap_days = (today - d).days

    return {
        "handles": list(handles),
        "notes": notes,
        "days": days,
        "summary": summary,
        "delta": {k: v for k, v in delta.items() if v is not None},
        "summary_metrics": len(summary),
        "window": window,
        "imports": imports,
        "count": len(notes),
        "exposure": tot["exposure"],
        "views": tot["views"],
        "likes": tot["likes"],
        "comments": tot["comments"],
        "collects": tot["collects"],
        "shares": tot["shares"],
        "fans": tot["fans"],
        "danmaku": tot["danmaku"],
        "ctr": ctr,
        "engage_rate": engage,
        "avg_views": (tot["views"] / len(notes)) if notes else 0.0,
        "top": top,
        "media": media,
        "views_last7": views7,
        "views_prev7": views_prev7,
        "trend": trend,
        "last_publish": last_publish,
        "gap_days": gap_days,
        "fmt_int": _fmt_int,
        "fmt_pct": _fmt_pct,
        "fmt_sec": _fmt_sec,
        "fmt_metric": fmt_metric,
        "metric_order": [k for k in ORDER if k in summary],
    }
