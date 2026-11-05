# -*- coding: utf-8 -*-
"""题库数据层：读写 questions.jsonl / review.json，沿用 1 → 3 → 7 天的间隔复习规则。"""
import json
from datetime import date, timedelta
from pathlib import Path

INTERVALS = [1, 3, 7]


def list_subjects(kb):
    try:
        return sorted(p.name for p in kb.iterdir() if p.is_dir())
    except OSError:
        return []


def questions_file(kb, subject):
    return kb / subject / "questions.jsonl"


def review_file(kb, subject):
    return kb / subject / "review.json"


def load_questions(kb, subject):
    f = questions_file(kb, subject)
    if not f.exists():
        return []
    out = []
    for line in f.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def load_review(kb, subject):
    f = review_file(kb, subject)
    if not f.exists():
        return {}
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def save_review(kb, subject, review):
    f = review_file(kb, subject)
    f.write_text(json.dumps(review, ensure_ascii=False, indent=1), encoding="utf-8")


def overview(kb):
    """[{subject, total, seen, wrong}]，用于首页/统计页。"""
    rows = []
    for s in list_subjects(kb):
        qs = load_questions(kb, s)
        rv = load_review(kb, s)
        seen = sum(1 for q in qs if q.get("id") in rv)
        wrong = sum(1 for q in qs if rv.get(q.get("id"), {}).get("wrong", 0) > 0
                    and not rv.get(q.get("id"), {}).get("mastered"))
        rows.append({"subject": s, "total": len(qs), "seen": seen, "wrong": wrong})
    return rows


def wrong_items(kb, subject):
    """未掌握错题明细：[{id, chapter, wrong, due, q}]"""
    qs = load_questions(kb, subject)
    rv = load_review(kb, subject)
    out = []
    for q in qs:
        st = rv.get(q.get("id"))
        if st and st.get("wrong", 0) > 0 and not st.get("mastered"):
            out.append({"id": q.get("id"), "chapter": q.get("chapter", ""),
                        "wrong": st.get("wrong", 0), "due": st.get("due", "—"),
                        "q": q.get("q", "")})
    out.sort(key=lambda r: r["due"])
    return out


def pick_pool(kb, subject, mode="all", chapter=None, due_only=False):
    qs = load_questions(kb, subject)
    if chapter:
        qs = [q for q in qs if chapter in q.get("chapter", "")]
    if mode in ("wrong", "due"):
        rv = load_review(kb, subject)
        today = date.today().isoformat()
        ids = set()
        for qid, st in rv.items():
            if st.get("wrong", 0) <= 0 or st.get("mastered"):
                continue
            if mode == "due" and st.get("due", "9999") > today:
                continue
            ids.add(qid)
        qs = [q for q in qs if q.get("id") in ids]
    return qs


def apply_answer(review, qid, ok, intervals=None):
    """与 study.py update() 完全一致的间隔规则。"""
    intervals = intervals or INTERVALS
    st = review.setdefault(qid, {"wrong": 0, "streak": 0, "seen": 0})
    st["seen"] += 1
    st["last"] = date.today().isoformat()
    if ok:
        st["streak"] = st.get("streak", 0) + 1
        if st["wrong"] > 0 and not st.get("mastered"):
            if st["streak"] >= 2:
                st["mastered"] = True
            else:
                st["due"] = (date.today() + timedelta(days=intervals[1])).isoformat()
    else:
        st["wrong"] += 1
        st["streak"] = 0
        st["mastered"] = False
        st["due"] = (date.today() + timedelta(days=intervals[0])).isoformat()
    return st
