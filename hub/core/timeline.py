# -*- coding: utf-8 -*-
"""时间线：把「在干嘛」按日期倒序摊平，**全部只读派生自现有笔记**。

数据源（不新增文件、不复制数据、不用二次维护）：
  · notes/daily-log.md —— 日报表格，复用 core.daily 的表头式解析
  · notes/index.md     —— 交流记录表：日期 | 主题分类 | 摘要 | 详情

改这两个文件，时间线自动跟着变；本模块不写任何文件。
"""
import re
from datetime import date, datetime

from core import daily

WEEK_CN = "一二三四五六日"
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
LINK_RE = re.compile(r"\[([^\]]*)\]\(([^)\s]*)\)")

# 交流记录的「主题分类」→ 时间线上的短标签
TALK_TAGS = (("宠物", "项目"), ("职业", "职业"), ("生活", "生活"),
             ("技术", "技术"), ("系统", "系统"),
             ("自媒体", "自媒体"), ("考研", "考研"))

# 日报各列 → (标签, 字段名)，顺序即时间线里的展示顺序
DAILY_COLS = (("健身", "fitness"), ("体重", "weight"), ("睡眠", "sleep"),
              ("抖音", "douyin"), ("英语", "english"), ("饮食", "diet"),
              ("项目", "project"), ("备注", "note"))


def _clean(s):
    s = (s or "").replace("**", "").replace("`", "")
    return re.sub(r"\s+", " ", s).strip()


def _blank(v):
    return not v or v in ("—", "-", "–")


def weekday(iso):
    try:
        return "周" + WEEK_CN[datetime.strptime(iso, "%Y-%m-%d").weekday()]
    except ValueError:
        return ""


def talk_tag(category):
    """「技术/自媒体」→ 技术；「宠物定位器项目」→ 项目。"""
    head = re.split(r"[/+＋]", _clean(category))[0].strip()
    for key, tag in TALK_TAGS:
        if key in head:
            return tag
    return head[:4] or "交流"


def resolve_href(href):
    """详情链接 → 仓库内笔记相对路径（指向 notes/ 之外的返回 None）。"""
    href = (href or "").strip()
    if not href or "://" in href or href.startswith("mailto:"):
        return None
    if href.startswith("notes/"):
        return href
    if href.startswith("../") or href.startswith("/"):
        return None                      # 如 ../AGENTS.md，笔记页里打不开
    return "notes/" + href.lstrip("./")


def parse_index(text):
    """解析 index.md 的交流记录表 → [{date, category, summary, path}]。"""
    out = []
    cols = None
    for line in (text or "").splitlines():
        s = line.strip()
        if not s.startswith("|"):
            if s.startswith("## "):
                cols = None
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        if len(cells) < 3:
            continue
        if cells[0] == "日期":
            cols = {name: i for i, name in enumerate(cells)}
            continue
        if cols is None or not DATE_RE.match(cells[0]):
            continue

        def cell(key):
            i = cols.get(key)
            return cells[i] if i is not None and i < len(cells) else ""

        detail = cell("详情")
        links = LINK_RE.findall(detail)
        path = None
        for _label, href in links:
            path = resolve_href(href)
            if path:
                break
        out.append({
            "date": cells[0],
            "category": _clean(cell("主题分类")),
            "summary": _clean(cell("一句话摘要")) or _clean(detail),
            "path": path,
        })
    return out


def build(daily_text="", index_text="", today=None):
    """返回按日期倒序的 [{date, week, today, items:[{kind,tag,text,path}]}]。"""
    today = (today or date.today()).isoformat()
    days = {}

    def bucket(d):
        b = days.get(d)
        if b is None:
            b = days[d] = {"date": d, "week": weekday(d),
                           "today": d == today, "items": []}
        return b

    rows = daily.parse_text(daily_text or "")
    ws = daily.weight_series(rows)
    first_w = ws[0][1] if ws else None
    low = None
    for r in rows:
        b = bucket(r["date"])
        path = "notes/daily-log.md"
        for tag, key in DAILY_COLS:
            val = r.get(key)
            if tag == "体重":
                if val is None:
                    continue
                extra = []
                if first_w is not None and abs(val - first_w) > 1e-9:
                    extra.append(f"累计 {val - first_w:+.1f}")
                if low is not None and val < low:
                    extra.append("新低")
                low = val if low is None else min(low, val)
                text = f"{val:g} 斤" + (f"（{'，'.join(extra)}）" if extra else "")
            else:
                text = _clean(val)
                if _blank(text):
                    continue
            b["items"].append({"kind": "daily", "tag": tag, "text": text,
                               "path": path})

    for t in parse_index(index_text or ""):
        bucket(t["date"])["items"].append({
            "kind": "talk", "tag": talk_tag(t["category"]),
            "text": t["summary"], "path": t["path"],
        })

    return [days[d] for d in sorted(days, reverse=True)]


def summary(days, flt="all"):
    """统计当前筛选下可见的天数与条目数、日期范围。"""
    shown = [d for d in days
             if flt == "all" or any(i["kind"] == flt for i in d["items"])]
    n = sum(1 for d in shown for i in d["items"] if flt == "all" or i["kind"] == flt)
    if not shown:
        return {"days": 0, "count": 0, "first": None, "last": None}
    return {"days": len(shown), "count": n,
            "first": shown[-1]["date"], "last": shown[0]["date"]}
