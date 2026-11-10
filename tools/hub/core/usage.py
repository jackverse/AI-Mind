# -*- coding: utf-8 -*-
"""模块浏览统计：**按机器分片 + 读时合并**（存 `data/hub/usage.<机器>.json`）。

每台机器只写自己那一片，读的时候把所有分片合起来算：

| 字段 | 合并规则 | 为什么不会多算 / 少算 |
|---|---|---|
| `total` | 各分片相加 | 每个事件只属于一台机器，相加就是全局次数 |
| `last`  | 取最大 | 最近一次访问时间 |
| `days`  | `{日期: 次数}` 按日相加 | 天然去重，重读/重拉/重复提交都不会翻倍 |

**设置项（`_meta.sort` / `_meta.pins`）不参与合并**，只认本机分片——否则 A 机置顶、B 机取消，会来回打架。

**为什么不存 hits 时间戳**：旧实现只留最近 50 条，7 天内点超过 50 次就少算；
按天计数只有 7~400 个数字，结构上不会截断。

数据不进 git 的旧规则已改：`usage.<机器>.json` 允许入库（`usage.json` 老文件仍忽略）。
"""
import json
import os
import re
import socket
from datetime import date, datetime, timedelta

from . import paths

RECENT_DAYS = 7
KEEP_DAYS = 400          # 按天计数最多留这么久，防止文件无限长

# 排序模式标签（hub 侧栏与设置页共用）
SORT_LABEL = {"recent": "最近 7 天", "total": "总次数", "default": "默认权重"}
SORT_MODES = ["recent", "total", "default"]

_migrated = False


# ---------------------------------------------------------------- 分片定位
def host_id():
    """本机标识：COMPUTERNAME（Windows）/ hostname，清洗成文件名安全的形式。"""
    raw = os.environ.get("COMPUTERNAME") or socket.gethostname() or "local"
    clean = re.sub(r"[^A-Za-z0-9_.-]", "_", raw).strip("._")
    return (clean or "local")[:40]


def store_dir():
    global _migrated
    d = paths.data_dir("hub")
    if not _migrated:                       # 旧版在 %APPDATA%：首次运行搬过来
        paths.adopt_legacy(paths.legacy_data_dir("usage.json"), d / "usage.json")
        _migrated = True
    return d


def store_path(host=None):
    """本机分片路径（写只用这个）。"""
    return store_dir() / f"usage.{host or host_id()}.json"


def legacy_path():
    return store_dir() / "usage.json"


def shard_paths():
    try:
        return sorted(p for p in store_dir().glob("usage.*.json") if p.is_file())
    except OSError:
        return []


def _host_of(path):
    stem = path.stem                     # usage.LAPTOP-XYZ
    return stem.split(".", 1)[-1] if "." in stem else "local"


# ---------------------------------------------------------------- 读写
def _read(path):
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))   # 容忍 BOM
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _write(path, data):
    try:
        path.write_text(json.dumps(data, ensure_ascii=False, indent=1),
                        encoding="utf-8")
    except OSError:
        pass


def _norm_rec(rec):
    """统一成 {total, last, days}；兼容旧结构（顶层 hits 时间戳列表）。"""
    if not isinstance(rec, dict):
        return {"total": 0, "last": None, "days": {}}
    days = {}
    for d, n in (rec.get("days") or {}).items():
        if isinstance(d, str):
            try:
                days[d] = days.get(d, 0) + int(n or 0)
            except (TypeError, ValueError):
                pass
    for t in (rec.get("hits") or []):        # 旧结构迁移：时间戳 → 按天计数
        if isinstance(t, str) and len(t) >= 10:
            days[t[:10]] = days.get(t[:10], 0) + 1
    return {"total": int(rec.get("total") or 0),
            "last": rec.get("last"),
            "days": days}


def _trim(days):
    """只留最近 KEEP_DAYS 天，防止文件越写越长。"""
    if len(days) <= KEEP_DAYS:
        return days
    cutoff = (date.today() - timedelta(days=KEEP_DAYS)).isoformat()
    for d in [k for k in days if k < cutoff]:
        days.pop(d, None)
    return days


def _local_shard():
    """本机分片（结构：{_meta, pages}）；首次运行会把旧的 usage.json 迁过来。"""
    p = store_path()
    shard = _read(p)
    if shard.get("pages") is None:
        shard = {"_meta": shard.get("_meta") or {}, "pages": {}}
    shard.setdefault("_meta", {})
    shard.setdefault("pages", {})
    if not shard["pages"]:                   # 迁移旧单文件
        old = _read(legacy_path())
        pages = {k: _norm_rec(v) for k, v in old.items() if not k.startswith("_")}
        if pages:
            shard["pages"] = pages
            if not shard["_meta"]:
                shard["_meta"] = old.get("_meta") or {}
            _write(p, shard)
    return shard


def load_local():
    """本机分片（要改计数器时用它）。"""
    return _local_shard()


def load():
    """合并视图：{页面: {total,last,days,by_host}} + `_meta`（本机）+ `_sources`。"""
    local = _local_shard()          # 先确保本机分片存在（含首次从 usage.json 迁移）
    merged, sources = {}, []
    for p in shard_paths():
        host = _host_of(p)
        shard = _read(p)
        if not isinstance(shard, dict):
            continue
        pages = shard.get("pages")
        if not isinstance(pages, dict):       # 兼容没迁过的老单文件
            pages = {k: v for k, v in shard.items() if not k.startswith("_")}
        sources.append(host)
        for key, raw in pages.items():
            rec = _norm_rec(raw)
            acc = merged.setdefault(key, {"total": 0, "last": None,
                                          "days": {}, "by_host": {}})
            acc["total"] += rec["total"]
            acc["by_host"][host] = acc["by_host"].get(host, 0) + rec["total"]
            if rec["last"] and (not acc["last"] or rec["last"] > acc["last"]):
                acc["last"] = rec["last"]
            for d, n in rec["days"].items():
                acc["days"][d] = acc["days"].get(d, 0) + n
    merged["_meta"] = local.get("_meta") or {"sort": "recent", "pins": []}
    merged["_sources"] = sources or [host_id()]
    return merged


def save(data):
    """只落**设置项**（`_meta`）；计数只由 `record()` 写。

    ⚠️ 不能把合并视图整份写回：那会把别台机器的计数复制进本机分片，下次合并翻倍。
    """
    shard = _local_shard()
    meta = (data or {}).get("_meta")
    if isinstance(meta, dict):
        shard["_meta"] = meta
        _write(store_path(), shard)
    return data


def clear():
    """清空**本机**计数（保留置顶/排序）；别的机器的数据不受影响。"""
    shard = _local_shard()
    shard["pages"] = {}
    _write(store_path(), shard)
    return load()


# ---------------------------------------------------------------- 记账
def record(key, data=None):
    """记一次访问（只写本机分片），返回最新合并视图。"""
    shard = _local_shard()
    pages = shard.setdefault("pages", {})
    rec = pages.get(key)
    if not isinstance(rec, dict):
        rec = {"total": 0, "last": None, "days": {}}
    now = datetime.now()
    rec["total"] = int(rec.get("total") or 0) + 1
    rec["last"] = now.isoformat(timespec="seconds")
    days = rec.get("days")
    if not isinstance(days, dict):
        days = rec["days"] = {}
    day = now.date().isoformat()
    days[day] = int(days.get(day) or 0) + 1
    _trim(days)
    pages[key] = rec
    _write(store_path(), shard)
    return load()


def recent(rec, days=RECENT_DAYS):
    """最近 N 天访问次数（按日计数相加，不截断）。"""
    today = date.today()
    window = {(today - timedelta(days=i)).isoformat() for i in range(days)}
    return sum(int(n or 0) for d, n in ((rec or {}).get("days") or {}).items()
               if d in window)


def summary(data):
    """[(key, recent7, total, last)]，按最近 7 天降序。"""
    rows = [(k, recent(v), int(v.get("total", 0)), v.get("last"))
            for k, v in data.items() if not k.startswith("_")]
    rows.sort(key=lambda r: (-r[1], -r[2]))
    return rows


def sources(data):
    """这次合并用到了哪几台机器的分片。"""
    return list((data or {}).get("_sources") or [host_id()])


def breakdown(rec):
    """某页在各机器上的次数，用于核对有没有多算/少算。"""
    return dict((rec or {}).get("by_host") or {})


# ---------------------------------------------------------------- 机器别名
ALIAS_FILE = "machines.json"


def aliases_path():
    return store_dir() / ALIAS_FILE


def load_aliases():
    """{机器名: 别名}；两台机器共用同一份（进 git），改的人少、冲突概率低。"""
    data = _read(aliases_path())
    raw = data.get("aliases") if isinstance(data, dict) else None
    return {k: v for k, v in (raw or {}).items()
            if isinstance(k, str) and isinstance(v, str) and v.strip()}


def set_alias(host, alias):
    """设/清某台机器的别名（空字符串 = 删掉，回到原始机器名）。"""
    al = load_aliases()
    alias = (alias or "").strip()
    if alias:
        al[host] = alias
    else:
        al.pop(host, None)
    _write(aliases_path(), {"aliases": al})
    return al


def display_name(host, aliases=None):
    al = aliases if isinstance(aliases, dict) else load_aliases()
    return al.get(host) or host


# ---------------------------------------------------------------- 设置项
def get_sort_mode(data, default="recent"):
    return (data.get("_meta") or {}).get("sort", default)


def set_sort_mode(mode, data=None):
    data = data if data is not None else load()
    data.setdefault("_meta", {})["sort"] = mode
    save(data)
    return data


# ---------------------------------------------------------------- 置顶
def get_pins(data):
    """置顶页面键列表（按置顶顺序）。"""
    meta = data.get("_meta") or {}
    return [k for k in (meta.get("pins") or []) if isinstance(k, str)]


def is_pinned(key, data=None):
    data = data if data is not None else load()
    return key in get_pins(data)


def toggle_pin(key, data=None):
    """切换某页置顶，返回 (data, 现在是否置顶)。"""
    data = data if data is not None else load()
    meta = data.setdefault("_meta", {})
    pins = get_pins(data)
    if key in pins:
        pins.remove(key)
        pinned = False
    else:
        pins.append(key)
        pinned = True
    meta["pins"] = pins
    save(data)
    return data, pinned
