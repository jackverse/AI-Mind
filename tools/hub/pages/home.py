# -*- coding: utf-8 -*-
"""首页：抖音 / 小红书数据概览 + 三个入口。"""

# 侧栏入口（hub 启动时自动扫这个 META，不用改 hub.py）
META = {"icon": '◎', "title": '首页', "sub": '总览', "weight": 100}
import tkinter as tk
from datetime import datetime

import ui
from core import douyin, xhs


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
        tk.Label(top, text="0.x 内测版", font=ui.F["small"], bg="#eef3ff",
                 fg=ui.C["accent"], padx=8, pady=2).pack(side="left", padx=(10, 0))
        self.when = tk.Label(top, text=datetime.now().strftime("%Y-%m-%d  %H:%M"),
                             font=ui.F["small"], bg=ui.C["bg"], fg=ui.C["muted"])
        self.when.pack(side="right", pady=(10, 0))

        tk.Label(wrap, text="抖音 / 小红书数据工作台", font=ui.F["h2"],
                 bg=ui.C["bg"], fg=ui.C["text"], anchor="w").pack(fill="x", pady=(16, 0))

        self.stats = tk.Frame(wrap, bg=ui.C["bg"])
        self.stats.pack(fill="x", pady=(18, 6))

        self.cards = tk.Frame(wrap, bg=ui.C["bg"])
        self.cards.pack(fill="x", pady=(14, 0))

        foot = tk.Frame(wrap, bg=ui.C["bg"])
        foot.pack(fill="x", side="bottom", pady=(18, 0))
        self.path = tk.Label(foot, text="", font=ui.F["small"], bg=ui.C["bg"],
                             fg=ui.C["muted"], anchor="w")
        self.path.pack(fill="x")

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
        try:
            dy = len(douyin.load_accounts())
        except Exception:
            dy = 0
        try:
            xh = len(xhs.load_accounts())
        except Exception:
            xh = 0
        self._tile(self.stats, dy, "抖音账号")
        self._tile(self.stats, xh, "小红书账号")

        for w in self.cards.winfo_children():
            w.destroy()
        grid = tk.Frame(self.cards, bg=ui.C["bg"])
        grid.pack(fill="x", anchor="n")
        for i in range(3):
            grid.columnconfigure(i, weight=1)

        items = [
            ("抖音", "多账号、作品明细、每日趋势、自动同步", "douyin", dy),
            ("小红书", "多账号、笔记明细、近 30 天指标、自动导出", "xhs", xh),
            ("我的", "数据目录、隐私模式、版本与反馈", "me", None),
        ]
        for i, (title, desc, key, badge) in enumerate(items):
            card = ui.Card(grid, title, desc, lambda k=key: self.app.goto(k), badge)
            card.grid(row=0, column=i, sticky="nsew", padx=(0, 14))

        self.path.configure(text="数据目录：" + str(self.ctx.root))

    def on_show(self, **kw):
        self.when.configure(text=datetime.now().strftime("%Y-%m-%d  %H:%M"))
        self._reload()


def make(master, ctx, app):
    return HomePage(master, ctx, app)
