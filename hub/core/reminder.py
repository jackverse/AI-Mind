# -*- coding: utf-8 -*-
"""每日提醒正文：只读 notes/TODO.md + notes/daily-log.md 派生，不新增数据。

提醒内容 = 今天该干什么（待办）+ 今天还没记的打卡，全部来自笔记本身；
用户改了笔记，邮件内容跟着变。
"""
import re
from datetime import date, datetime
from pathlib import Path

from . import daily

TODO_ITEM_RE = re.compile(r"^\s*[-*]\s*\[( |x|X)\]\s*(.+?)\s*$")
H2_RE = re.compile(r"^##\s+(.+?)\s*$")
H3_RE = re.compile(r"^#{3,4}\s+(.+?)\s*$")
LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]*\)")
MAX_ITEMS = 15
MAX_LEN = 64


def _clean(text):
    text = LINK_RE.sub(r"\1", text or "")
    text = text.replace("**", "").replace("`", "").strip()
    text = re.sub(r"\s+", " ", text)
    return text


def _short(text, limit=MAX_LEN):
    text = _clean(text)
    return text if len(text) <= limit else text[:limit - 1] + "…"


def pending_todos(todo_file, limit=MAX_ITEMS):
    """未完成待办：[(分组, 文本)]，只取「进行中」一节。"""
    try:
        text = (todo_file if hasattr(todo_file, "read_text") else Path(todo_file)) \
            .read_text(encoding="utf-8")
    except OSError:
        return []
    items, section, top, in_progress = [], "其他", None, False
    for line in text.splitlines():
        s = line.strip()
        h2 = H2_RE.match(s)
        if h2:
            top = _clean(h2.group(1))
            in_progress = top.startswith("进行中")
            section = top
            continue
        h3 = H3_RE.match(s)
        if h3:
            if in_progress:
                section = _clean(h3.group(1))
            continue
        if not in_progress:
            continue
        m = TODO_ITEM_RE.match(line)
        if m and m.group(1).lower() != "x":
            items.append((section, _short(m.group(2))))
            if len(items) >= limit:
                break
    return items


def _weekday(d):
    return "一二三四五六日"[d.weekday()]


def _md(d):
    return f"{d.month:02d}-{d.day:02d}"


def digest(ctx, when=None):
    """返回 (subject, body)，正文是纯文本。数据全来自笔记，缺文件就少一段。"""
    today = when or date.today()
    rows = []
    try:
        rows = daily.parse(ctx.notes / "daily-log.md")
    except OSError:
        rows = []

    by_date = {r["date"]: r for r in rows}
    today_row = by_date.get(today.isoformat())
    last_row = max(rows, key=lambda r: r["date"]) if rows else None
    last_date = None
    if last_row:
        try:
            last_date = datetime.strptime(last_row["date"], "%Y-%m-%d").date()
        except ValueError:
            last_date = None

    todos = pending_todos(ctx.notes / "TODO.md")

    # ---- 今天
    if today_row is not None:
        today_txt = f"日报已记（{today_row['fitness'] or '健身未记'}）"
    elif last_date is None:
        today_txt = "日报今天还没记"
    else:
        gap = (today - last_date).days
        today_txt = (f"日报今天还没记（上次记录 {_md(last_date)}，"
                     f"隔了 {gap} 天）" if gap > 1
                     else f"日报今天还没记（上次记录 {_md(last_date)}）")

    weight = None
    for r in reversed(rows):
        if r.get("weight") is not None:
            weight = (r["date"], r["weight"])
            break
    if weight:
        wd = datetime.strptime(weight[0], "%Y-%m-%d").date()
        today_txt += f"；体重 {weight[1]:g} 斤（{_md(wd)}）"

    plan = daily.planned_today(rows, today)

    # ---- 拼正文
    lines = ["第二大脑 · 每日提醒",
             f"{today:%Y-%m-%d} 周{_weekday(today)}",
             ""]
    lines.append("【今天】" + today_txt)
    if plan:
        lines.append("【训练】今天计划：" + _clean(plan))
    if today_row is None and last_date is not None:
        lines.append("【日报】记一行：健身 / 体重 / 抖音 / 英语 / 饮食，"
                     "打开 hub → 时间线 或直接改 notes/daily-log.md")

    lines.append("")
    if todos:
        lines.append(f"【待办 {len(todos)} 项】")
        last_section = None
        for section, text in todos:
            if section != last_section:
                lines.append(f"· {section}")
                last_section = section
            lines.append(f"    - {text}")
    else:
        lines.append("【待办】TODO.md 里没有未完成项")

    lines.append("")
    lines.append("——")
    lines.append("由 hub 自动发送。改 notes/TODO.md 或 daily-log.md，"
                 "这封信的内容会自动跟着变。")

    body = "\n".join(lines)
    subject = f"第二大脑提醒 · {_md(today)} 周{_weekday(today)} · 待办 {len(todos)} 项"
    if today_row is None:
        subject += " · 日报未记"
    return subject, body
