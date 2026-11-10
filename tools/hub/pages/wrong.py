# -*- coding: utf-8 -*-
"""错题本：未掌握错题明细 + 一键复习。"""

# 侧栏入口（hub 启动时自动扫这个 META，不用改 hub.py）
META = {"icon": '✗', "title": '错题本', "sub": '待攻克', "weight": 40}
import tkinter as tk
from tkinter import ttk

import ui
from core import store


class WrongPage(tk.Frame):
    def __init__(self, master, ctx, app):
        super().__init__(master, bg=ui.C["bg"])
        self.ctx, self.app = ctx, app
        self._build()

    def _build(self):
        bar = tk.Frame(self, bg=ui.C["bg"])
        bar.pack(fill="x", padx=24, pady=(20, 10))
        tk.Label(bar, text="错题本", font=(ui.UI, 18, "bold"), bg=ui.C["bg"],
                 fg=ui.C["text"]).pack(side="left")
        self.summary = tk.Label(bar, text="", font=ui.F["small"], bg=ui.C["bg"],
                                fg=ui.C["muted"])
        self.summary.pack(side="left", padx=10, pady=(6, 0))

        btns = tk.Frame(bar, bg=ui.C["bg"])
        btns.pack(side="right")
        ttk.Button(btns, text="复习今天的", style="Accent.TButton",
                   command=lambda: self.app.goto("quiz", mode="due", auto=True)).pack(side="left", padx=(0, 8))
        ttk.Button(btns, text="刷全部错题",
                   command=lambda: self.app.goto("quiz", mode="wrong", auto=True)).pack(side="left", padx=(0, 8))
        ttk.Button(btns, text="刷新", command=self.refresh).pack(side="left")

        box = tk.Frame(self, bg=ui.C["card"], highlightthickness=1,
                       highlightbackground=ui.C["line"])
        box.pack(fill="both", expand=True, padx=24, pady=(0, 20))

        cols = ("subject", "id", "chapter", "wrong", "due", "q")
        self.tree = ttk.Treeview(box, columns=cols, show="headings", selectmode="browse")
        heads = {"subject": ("科目", 90), "id": ("题号", 90), "chapter": ("章节", 150),
                 "wrong": ("错次", 50), "due": ("到期", 96), "q": ("题干", 520)}
        for c in cols:
            title, w = heads[c]
            self.tree.heading(c, text=title)
            self.tree.column(c, width=w, anchor="w" if c in ("chapter", "q") else "center")
        sb = ttk.Scrollbar(box, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        self.hint = tk.Label(self, text="", font=ui.F["small"], bg=ui.C["bg"],
                             fg=ui.C["muted"], anchor="w")
        self.hint.pack(fill="x", padx=26, pady=(0, 10))

    def refresh(self):
        self.tree.delete(*self.tree.get_children())
        total = 0
        for s in self.ctx.subjects():
            for r in store.wrong_items(self.ctx.kb, s):
                total += 1
                self.tree.insert("", "end", values=(
                    s, r["id"], r["chapter"], r["wrong"], r["due"],
                    (r["q"][:60] + "…") if len(r["q"]) > 60 else r["q"]))
        self.summary.configure(text=f"{total} 道未掌握")
        self.hint.configure(text="复习规则：答错后 1 天到期 → 到期答对一次 3 天后再考 → 连对两次移出错题本。"
                                 if total else "错题本为空 —— 去「刷题」页练几组就会有了。")

    def on_show(self, **kw):
        self.refresh()


def make(master, ctx, app):
    return WrongPage(master, ctx, app)
