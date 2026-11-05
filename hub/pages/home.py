# -*- coding: utf-8 -*-
"""首页：数据概览 + 四个入口卡片。"""
import tkinter as tk
from datetime import datetime
from tkinter import ttk

import ui
from core import store


class HomePage(tk.Frame):
    def __init__(self, master, ctx, app):
        super().__init__(master, bg=ui.C["bg"])
        self.ctx, self.app = ctx, app
        self._build()

    def _build(self):
        wrap = tk.Frame(self, bg=ui.C["bg"])
        wrap.pack(fill="both", expand=True, padx=34, pady=26)

        top = tk.Frame(wrap, bg=ui.C["bg"])
        top.pack(fill="x")
        tk.Label(top, text="首页", font=(ui.UI, 22, "bold"), bg=ui.C["bg"],
                 fg=ui.C["text"], anchor="w").pack(side="left")
        self.when = tk.Label(top, text=datetime.now().strftime("%Y-%m-%d  %H:%M"),
                             font=ui.F["small"], bg=ui.C["bg"], fg=ui.C["muted"])
        self.when.pack(side="right", pady=(10, 0))

        self.stats = tk.Frame(wrap, bg=ui.C["bg"])
        self.stats.pack(fill="x", pady=(18, 6))

        self.cards = tk.Frame(wrap, bg=ui.C["bg"])
        self.cards.pack(fill="x", pady=(14, 0))

        self.recent = tk.Frame(wrap, bg=ui.C["bg"])
        self.recent.pack(fill="both", expand=True, pady=(6, 0))

    # ------------------------------------------------------------------
    def _tile(self, parent, value, label):
        box = tk.Frame(parent, bg=ui.C["card"], highlightthickness=1,
                       highlightbackground=ui.C["line"])
        box.pack(side="left", padx=(0, 12))
        inner = tk.Frame(box, bg=ui.C["card"])
        inner.pack(padx=18, pady=12)
        tk.Label(inner, text=str(value), font=(ui.UI, 20, "bold"), bg=ui.C["card"],
                 fg=ui.C["accent"]).pack(anchor="w")
        tk.Label(inner, text=label, font=ui.F["small"], bg=ui.C["card"],
                 fg=ui.C["muted"]).pack(anchor="w")

    def _reload(self):
        for w in self.stats.winfo_children():
            w.destroy()
        rows = store.overview(self.ctx.kb)
        total_q = sum(r["total"] for r in rows)
        total_wrong = sum(r["wrong"] for r in rows)
        notes = len(self.ctx.note_rels())
        self._tile(self.stats, len(rows), "科目")
        self._tile(self.stats, total_q, "题目总数")
        self._tile(self.stats, total_wrong, "待攻克错题")
        self._tile(self.stats, notes, "笔记文件")

        for w in self.cards.winfo_children():
            w.destroy()
        grid = tk.Frame(self.cards, bg=ui.C["bg"])
        grid.pack(fill="x", anchor="n")
        grid.columnconfigure(0, weight=1)
        grid.columnconfigure(1, weight=1)

        items = [
            ("笔记", "浏览 notes/ 下全部 Markdown：档案、日报、主题、知识库", "notes", notes),
            ("刷题", "按科目/章节抽题，选择题即时判分并写入错题本", "quiz", total_q),
            ("错题本", "未掌握的错题明细，按到期时间排序，一键复习", "wrong", total_wrong),
            ("统计", "各科目正确率与章节掌握度", "stats", len(rows)),
        ]
        items = [it for it in items
                 if self.app.registry.get(it[2]) is not None
                 and not self.app.registry[it[2]]["deleted_at"]]
        for i, (title, desc, key, badge) in enumerate(items):
            card = ui.Card(grid, title, desc, lambda k=key: self.app.goto(k), badge)
            card.grid(row=i // 2, column=i % 2, sticky="nsew", padx=(0, 14), pady=(0, 14))

        # 最近修改的笔记
        for w in self.recent.winfo_children():
            w.destroy()
        box = tk.Frame(self.recent, bg=ui.C["card"], highlightthickness=1,
                       highlightbackground=ui.C["line"])
        box.pack(fill="both", expand=True)
        tk.Label(box, text="最近更新", font=(ui.UI, 10, "bold"), bg=ui.C["card"],
                 fg=ui.C["text"]).pack(anchor="w", padx=16, pady=(12, 6))
        files = sorted(self.ctx.note_rels(),
                       key=lambda r: self.ctx.mtime(r) or 0, reverse=True)[:4]
        for rel in files:
            mt = self.ctx.mtime(rel)
            when = (datetime.fromtimestamp(mt).strftime("%m-%d %H:%M")
                    if mt else "—")
            row = tk.Frame(box, bg=ui.C["card"], cursor="hand2")
            row.pack(fill="x", padx=16, pady=1)
            tk.Label(row, text=rel, font=ui.F["body"], bg=ui.C["card"],
                     fg=ui.C["accent"], anchor="w").pack(side="left")
            tk.Label(row, text=when, font=ui.F["small"], bg=ui.C["card"],
                     fg=ui.C["muted"]).pack(side="right")
            for w in (row, *row.winfo_children()):
                w.bind("<Button-1>", lambda _e, r=rel: self.app.goto("notes", path=r))

    def on_show(self, **kw):
        self.when.configure(text=datetime.now().strftime("%Y-%m-%d  %H:%M"))
        self._reload()


def make(master, ctx, app):
    return HomePage(master, ctx, app)
