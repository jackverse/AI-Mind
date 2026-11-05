# -*- coding: utf-8 -*-
"""统计页：科目正确率 + 章节掌握度。"""
import tkinter as tk
from tkinter import ttk

import ui
from core import store


class StatsPage(tk.Frame):
    def __init__(self, master, ctx, app):
        super().__init__(master, bg=ui.C["bg"])
        self.ctx, self.app = ctx, app
        self._build()

    def _build(self):
        bar = tk.Frame(self, bg=ui.C["bg"])
        bar.pack(fill="x", padx=24, pady=(20, 10))
        tk.Label(bar, text="统计", font=(ui.UI, 18, "bold"), bg=ui.C["bg"],
                 fg=ui.C["text"]).pack(side="left")

        self.subject = tk.StringVar()
        self.cb = ttk.Combobox(bar, textvariable=self.subject, width=16, state="readonly")
        self.cb.pack(side="right")
        self.cb.bind("<<ComboboxSelected>>", lambda _e: self._render_chapters())

        self.tiles = tk.Frame(self, bg=ui.C["bg"])
        self.tiles.pack(fill="x", padx=24)

        box = tk.Frame(self, bg=ui.C["card"], highlightthickness=1,
                       highlightbackground=ui.C["line"])
        box.pack(fill="both", expand=True, padx=24, pady=(14, 20))
        tk.Label(box, text="章节掌握度", font=ui.F["body"], bg=ui.C["card"],
                 fg=ui.C["text"]).pack(anchor="w", padx=16, pady=(12, 4))

        cols = ("chapter", "seen", "ok", "rate")
        self.tree = ttk.Treeview(box, columns=cols, show="headings")
        for c, (t, w) in {"chapter": ("章节", 320), "seen": ("练过", 80),
                          "ok": ("当前掌握", 100), "rate": ("正确率", 100)}.items():
            self.tree.heading(c, text=t)
            self.tree.column(c, width=w, anchor="w" if c == "chapter" else "center")
        self.tree.pack(fill="both", expand=True, padx=16, pady=(0, 14))

    def _tile(self, parent, value, label, color=None):
        box = tk.Frame(parent, bg=ui.C["card"], highlightthickness=1,
                       highlightbackground=ui.C["line"])
        box.pack(side="left", padx=(0, 12), pady=(6, 0))
        inner = tk.Frame(box, bg=ui.C["card"])
        inner.pack(padx=18, pady=10)
        tk.Label(inner, text=str(value), font=(ui.UI, 17, "bold"), bg=ui.C["card"],
                 fg=color or ui.C["accent"]).pack(anchor="w")
        tk.Label(inner, text=label, font=ui.F["small"], bg=ui.C["card"],
                 fg=ui.C["muted"]).pack(anchor="w")

    def _render_chapters(self):
        self.tree.delete(*self.tree.get_children())
        s = self.subject.get()
        if not s:
            return
        qs = store.load_questions(self.ctx.kb, s)
        rv = store.load_review(self.ctx.kb, s)
        ch = {}
        for q in qs:
            st = rv.get(q.get("id"))
            if not st:
                continue
            c = ch.setdefault(q.get("chapter", "未分类"), [0, 0])
            c[0] += 1
            c[1] += 1 if st.get("streak", 0) > 0 else 0
        for name, (seen, ok) in sorted(ch.items()):
            rate = f"{int(ok * 100 / seen)}%" if seen else "—"
            self.tree.insert("", "end", values=(name, seen, ok, rate))
        if not ch:
            self.tree.insert("", "end", values=("（还没练过这个科目）", "", "", ""))

    def on_show(self, **kw):
        subs = self.ctx.subjects()
        self.cb.configure(values=subs)
        if subs and self.subject.get() not in subs:
            self.subject.set(subs[0])

        for w in self.tiles.winfo_children():
            w.destroy()
        rows = store.overview(self.ctx.kb)
        total = sum(r["total"] for r in rows)
        seen = sum(r["seen"] for r in rows)
        wrong = sum(r["wrong"] for r in rows)
        self._tile(self.tiles, len(rows), "科目")
        self._tile(self.tiles, total, "题目总数")
        self._tile(self.tiles, seen, "已练题数")
        self._tile(self.tiles, wrong, "待攻克错题", ui.C["bad"] if wrong else ui.C["ok"])
        self._render_chapters()


def make(master, ctx, app):
    return StatsPage(master, ctx, app)
