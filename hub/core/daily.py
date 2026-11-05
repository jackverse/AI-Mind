# -*- coding: utf-8 -*-
"""daily-log.md 解析与健身指标派生。

原则：**不新增数据文件**——日报表格是唯一真身，这里只做只读解析。
容错：认表头不认列位置；`—` 视为未报；`**153**` 这类加粗会先剥掉。
"""
import re
from datetime import date, datetime
from pathlib import Path

MONTH_RE = re.compile(r"^##\s+(\d{4})-(\d{2})\s*$")
DATE_RE = re.compile(r"^(\d{2})-(\d{2})$")
SEP_RE = re.compile(r":?-{2,}:?")

TRAIN_WORDS = ("练", "打卡", "跑", "有氧", "训练")
PARTS = [
    ("练腿", "腿"), ("深蹲", "腿"), ("硬拉", "腿"),
    ("练背", "背"), ("引体", "背"), ("划船", "背"),
    ("练胸", "胸"), ("卧推", "胸"),
    ("练肩", "肩"), ("推举", "肩"),
    ("练胳膊", "胳膊"), ("手臂", "胳膊"), ("二头", "胳膊"), ("三头", "胳膊"),
    ("有氧", "有氧"), ("跑", "有氧"),
]


def _clean(s):
    return (s or "").replace("**", "").replace("`", "").strip()


def _num(s):
    m = re.search(r"\d+(?:\.\d+)?", _clean(s))
    return float(m.group()) if m else None


def _find_col(cols, key):
    """按表头名找列：精确匹配优先，其次前缀匹配。"""
    if key in cols:
        return cols[key]
    for name, idx in cols.items():
        if name.startswith(key):
            return idx
    return None


def parse(path):
    """从文件解析（明文区）。"""
    return parse_text(Path(path).read_text(encoding="utf-8"))


def parse_text(text):
    """返回按日期排序的 [{date, md, week, fitness, status, part, weight, raw}]。"""
    month = None
    year = None
    cols = None
    rows = []
    for line in text.splitlines():
        s = line.strip()
        m = MONTH_RE.match(s)
        if m:
            month = f"{m.group(1)}-{m.group(2)}"
            year = m.group(1)
            cols = None
            continue
        if s.startswith("## "):          # 进入「小结」等其他二级标题，停止表格解析
            month = None
            cols = None
            continue
        if not s.startswith("|") or month is None:
            continue

        cells = [_clean(c) for c in s.strip("|").split("|")]
        if cols is None:
            if cells and cells[0] == "日期":
                cols = {name: i for i, name in enumerate(cells)}
            continue
        if all(SEP_RE.fullmatch(c) for c in cells if c):
            continue
        if not cells or not DATE_RE.match(cells[0]):
            continue

        def get(key):
            i = _find_col(cols, key)
            return cells[i] if i is not None and i < len(cells) else ""

        fitness = get("健身")
        weight = _num(get("体重"))
        rest = "休息" in fitness
        planned = any(w in fitness for w in ("计划", "准备", "打算"))
        trained = bool(fitness) and fitness not in ("—", "-") and not rest \
            and any(w in fitness for w in TRAIN_WORDS)
        part = None
        if trained:
            part = next((v for k, v in PARTS if k in fitness), None)
            if part is None:
                part = "未记部位" if ("打卡" in fitness or "部位未辨" in fitness) else "其他"
        if rest:
            status = "rest"
        elif planned:
            status = "plan"          # 计划但未确认完成，不计入训练次数
        else:
            status = "train" if trained else "none"

        rows.append({
            "date": f"{year}-{cells[0]}",
            "md": cells[0],
            "week": get("星期"),
            "fitness": fitness,
            "status": status,
            "part": part,
            "weight": weight,
            "sleep": get("睡眠"),
            "douyin": get("抖音"),
            "english": get("英语"),
            "diet": get("饮食"),
            "project": get("项目"),      # 表头是「项目进展」，前缀匹配即可
            "note": get("备注"),
        })
    rows.sort(key=lambda r: r["date"])
    return rows


# ------------------------------------------------------------------ 指标

def streaks(rows, today=None):
    """返回 (连续训练天数·截至最后一条, 最长连续训练, 连续记录天数)。"""
    best = cur = 0
    for r in rows:
        if r["status"] == "train":
            cur += 1
            best = max(best, cur)
        elif r["status"] == "rest":
            cur = 0
    tail = 0
    for r in reversed(rows):
        if r["status"] == "train":
            tail += 1
        elif r["status"] == "rest":
            break
    return tail, best, len(rows)


def weight_series(rows):
    """[(date, weight)]，跳过未报。"""
    return [(r["date"], r["weight"]) for r in rows if r["weight"] is not None]


def moving_avg(series, window=7):
    """按日期 7 天窗口的加权均值（点稀疏时按窗口内所有点平均）。"""
    out = []
    for d, _w in series:
        d0 = datetime.strptime(d, "%Y-%m-%d").date()
        vals = [w for dd, w in series
                if 0 <= (d0 - datetime.strptime(dd, "%Y-%m-%d").date()).days < window]
        out.append((d, round(sum(vals) / len(vals), 2)))
    return out


def part_counts(rows):
    c = {}
    for r in rows:
        if r["status"] == "train":
            c[r["part"] or "其他"] = c.get(r["part"] or "其他", 0) + 1
    return sorted(c.items(), key=lambda kv: -kv[1])


def planned_today(rows, today=None):
    """今天标记为「计划」的健身内容（如「练肩（计划）」）。"""
    today = (today or date.today()).isoformat()
    for r in rows:
        if r["date"] == today and r["status"] == "plan":
            return r["fitness"]
    return None


def record_streak(rows):
    """从最后一条往前，日期连续（无断档）的记录天数。"""
    if not rows:
        return 0
    n = 1
    for prev, cur in zip(reversed(rows[:-1]), reversed(rows[1:])):
        d_prev = datetime.strptime(prev["date"], "%Y-%m-%d").date()
        d_cur = datetime.strptime(cur["date"], "%Y-%m-%d").date()
        if (d_cur - d_prev).days == 1:
            n += 1
        else:
            break
    return n


def summary(rows, today=None):
    today = today or date.today()
    trains = [r for r in rows if r["status"] == "train"]
    rests = [r for r in rows if r["status"] == "rest"]
    plans = [r for r in rows if r["status"] == "plan"]
    ws = weight_series(rows)
    tail, best, days = streaks(rows, today)
    recent7 = [r for r in trains
               if (today - datetime.strptime(r["date"], "%Y-%m-%d").date()).days <= 7]
    return {
        "days": days,
        "rec_streak": record_streak(rows),
        "train": len(trains),
        "rest": len(rests),
        "plan": len(plans),
        "rate": round(len(trains) * 100 / days) if days else 0,
        "streak": tail,
        "best_streak": best,
        "recent7": len(recent7),
        "w_first": ws[0] if ws else None,
        "w_last": ws[-1] if ws else None,
        "w_min": min(ws, key=lambda t: t[1]) if ws else None,
        "w_delta": round(ws[0][1] - ws[-1][1], 1) if len(ws) > 1 else 0.0,
    }


def calendar(rows, today=None, n=30):
    """最近 n 天：[(date, status|None)]，按日期升序。"""
    today = today or date.today()
    idx = {r["date"]: r["status"] for r in rows}
    out = []
    for i in range(n - 1, -1, -1):
        d = today.fromordinal(today.toordinal() - i)
        key = d.isoformat()
        out.append((key, idx.get(key)))
    return out
