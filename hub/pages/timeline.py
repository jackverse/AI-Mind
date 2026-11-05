# -*- coding: utf-8 -*-
"""时间线页：按日期倒序摊开「在干嘛」。

数据全部只读派生自 notes/daily-log.md（日报）与 notes/index.md（交流记录），
不写文件、不另存数据；改那两个文件，这里刷新即变。
"""
import tkinter as tk
from tkinter import ttk

import ui
from core import privacy as pv
from core import timeline

FILTERS = (("all", "全部"), ("daily", "日常"), ("talk", "交流"))
MAX_ITEMS = 6          # 单天超过这么多条就先折叠，保持时间线可扫

# 标签配色（未列到的走默认灰）
TONE = {
    "健身": "#e0795c", "体重": "#4f7ee0", "睡眠": "#6f7fa6",
    "抖音": "#2f3340", "英语": "#3f7fc4", "饮食": "#4f9d69",
    "项目": "#8a6bd0", "备注": "#8a93a5",
    "技术": "#3d6ee0", "系统": "#5d6f8f", "职业": "#c07c26",
    "生活": "#3fa07a", "自媒体": "#c2453e", "考研": "#7a5cd0",
}
DEFAULT_TONE = "#6b7688"
CHIP_W = 5


class TimelinePage(tk.Frame):
    def __init__(self, master, ctx, app):
        super().__init__(master, bg=ui.C["bg"])
        self.ctx, self.app = ctx, app
        self.flt = "all"
        self.days = []
        self._wrap = []
        self._chips = {}
        self._cards = {}
        self.expanded = set()      # 展开全部条目的日期
        self._wl = None
        self._build_head()
        self._build_scroller()
        self.canvas.bind_all("<MouseWheel>", self._on_wheel)
        self._render()

    # ---------------------------------------------------------------- 顶栏
    def _build_head(self):
        head = tk.Frame(self, bg=ui.C["bg"])
        head.pack(fill="x", padx=24, pady=(18, 8))
        tk.Label(head, text="时间线", font=(ui.UI, 18, "bold"), bg=ui.C["bg"],
                 fg=ui.C["text"]).pack(side="left")
        self.meta = tk.Label(head, text="", font=ui.F["small"], bg=ui.C["bg"],
                             fg=ui.C["muted"])
        self.meta.pack(side="left", padx=10, pady=(6, 0))

        chips = tk.Frame(head, bg=ui.C["bg"])
        chips.pack(side="right", pady=(4, 0))
        for key, label in FILTERS:
            chip = tk.Label(chips, text=label, font=ui.F["small"], cursor="hand2",
                            padx=12, pady=3)
            chip.pack(side="left", padx=(6, 0))
            chip.bind("<Button-1>", lambda _e, k=key: self.set_filter(k))
            self._chips[key] = chip
        tk.Label(head, text="数据源：daily-log.md · index.md（只读派生）",
                 font=ui.F["small"], bg=ui.C["bg"], fg=ui.C["muted"]).pack(
                     side="right", padx=(0, 14), pady=(6, 0))
        self._paint_chips()

    def _paint_chips(self):
        for key, chip in self._chips.items():
            on = key == self.flt
            chip.configure(bg=ui.C["accent"] if on else "#e7ecf6",
                           fg="white" if on else ui.C["muted"])

    def set_filter(self, key):
        if key == self.flt:
            return
        self.flt = key
        self._paint_chips()
        self._render()

    # ---------------------------------------------------------------- 滚动容器
    def _build_scroller(self):
        self.canvas = tk.Canvas(self, bg=ui.C["bg"], bd=0, highlightthickness=0)
        self.vbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.vbar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.vbar.pack(side="right", fill="y")

        self.list = tk.Frame(self.canvas, bg=ui.C["bg"])
        self._win = self.canvas.create_window((0, 0), window=self.list, anchor="nw")
        self._bar = True
        self.list.bind("<Configure>", self._on_list)
        self.canvas.bind("<Configure>", self._on_canvas)

    def _on_canvas(self, event):
        self.canvas.itemconfigure(self._win, width=event.width)
        self._sync_scrollbar()

    def _on_list(self, _event=None):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        self._sync_scrollbar()

    def _sync_scrollbar(self):
        need = self.list.winfo_reqheight() > self.canvas.winfo_height()
        if need == self._bar:
            return
        self._bar = need
        if need:
            self.vbar.pack(side="right", fill="y")
        else:
            self.vbar.pack_forget()

    def _on_wheel(self, event):
        if not self.winfo_exists() or not self.winfo_ismapped():
            return
        self.canvas.yview_scroll(-int(event.delta / 120), "units")

    # ---------------------------------------------------------------- 渲染
    def _render(self):
        for w in self.list.winfo_children():
            w.destroy()
        self._wrap.clear()
        self._cards.clear()

        def read(rel):
            try:
                return self.ctx.read_text(rel)
            except OSError:
                return ""

        self.days = timeline.build(read("notes/daily-log.md"),
                                   read("notes/index.md"))
        shown = [d for d in self.days if self._keep(d)]
        s = timeline.summary(self.days, self.flt)
        if s["days"]:
            self.meta.configure(text=f"{s['days']} 天 · {s['count']} 条　｜　"
                                     f"{s['first']} ~ {s['last']}")
        else:
            self.meta.configure(text="没有记录")

        if not shown:
            tk.Label(self.list, text="daily-log.md 与 index.md 里还没有可显示的记录",
                     font=ui.F["body"], bg=ui.C["bg"], fg=ui.C["muted"]).pack(pady=40)
            self._on_list()
            return

        for day in shown:
            self._day(day)

        self._wl = None
        self.list.update_idletasks()
        self._resize_width(self.canvas.winfo_width())
        self._on_list()
        self.canvas.yview_moveto(0)

    def _keep(self, day):
        return self.flt == "all" or any(i["kind"] == self.flt for i in day["items"])

    def _day(self, day):
        items = [i for i in day["items"]
                 if self.flt == "all" or i["kind"] == self.flt]
        row = tk.Frame(self.list, bg=ui.C["bg"])
        row.pack(fill="x", padx=(24, 16))
        row.columnconfigure(0, minsize=64)
        row.columnconfigure(2, weight=1)

        # 日期列
        dcell = tk.Frame(row, bg=ui.C["bg"])
        dcell.grid(row=0, column=0, sticky="nw", padx=(0, 6), pady=(5, 0))
        tk.Label(dcell, text=day["date"][5:], font=(ui.UI, 11, "bold"),
                 bg=ui.C["bg"], fg=ui.C["accent"] if day["today"] else ui.C["text"]
                 ).pack(anchor="w")
        tk.Label(dcell, text="今天" if day["today"] else day["week"],
                 font=ui.F["small"], bg=ui.C["bg"],
                 fg=ui.C["accent"] if day["today"] else ui.C["muted"]).pack(anchor="w")

        # 竖向时间轴
        rail = tk.Frame(row, bg=ui.C["bg"], width=16)
        rail.grid(row=0, column=1, sticky="ns")
        rail.pack_propagate(False)
        tk.Label(rail, text="●", font=(ui.UI, 7), bg=ui.C["bg"],
                 fg=ui.C["accent"] if day["today"] else "#93a9cc").pack(
                     side="top", pady=(5, 0))
        tk.Frame(rail, bg="#c9d4e6", width=2).pack(side="top", fill="both",
                                                   expand=True, pady=(3, 0))

        # 当天内容卡（今天用强调色描边）
        card = tk.Frame(row, bg=ui.C["card"], highlightthickness=1,
                        highlightbackground=ui.C["accent"] if day["today"]
                        else ui.C["line"])
        card.grid(row=0, column=2, sticky="nsew", pady=(0, 10))
        self._cards[day["date"]] = card
        self._fill_card(card, day, items)

    def _fill_card(self, card, day, items):
        """按当前折叠状态铺一天的内容（超过 MAX_ITEMS 条先折叠）。"""
        for w in card.winfo_children():
            w.destroy()
        expanded = day["date"] in self.expanded
        shown = items if expanded or len(items) <= MAX_ITEMS else items[:MAX_ITEMS]
        for item in shown:
            self._item(card, item)
        rest = len(items) - len(shown)
        if rest > 0:
            self._toggle_lbl(card, f"展开其余 {rest} 条 ▾", day, items)
        elif expanded and len(items) > MAX_ITEMS:
            self._toggle_lbl(card, "收起 ▴", day, items)
        tk.Frame(card, bg=ui.C["card"], height=5).pack(fill="x")

    def _toggle_lbl(self, card, text, day, items):
        lbl = tk.Label(card, text=text, font=ui.F["small"], bg=ui.C["card"],
                       fg=ui.C["accent"], cursor="hand2", anchor="w")
        lbl.pack(fill="x", padx=14, pady=(5, 0))
        lbl.bind("<Button-1>", lambda _e: self._toggle(day, items))

    def _toggle(self, day, items):
        d = day["date"]
        if d in self.expanded:
            self.expanded.discard(d)
        else:
            self.expanded.add(d)
        card = self._cards.get(d)
        if card is None:
            return
        self._fill_card(card, day, items)
        self.list.update_idletasks()
        self._on_list()

    def _item(self, parent, item):
        erow = tk.Frame(parent, bg=ui.C["card"])
        erow.pack(fill="x", padx=12, pady=(6, 0))
        chip = tk.Label(erow, text=item["tag"], bg=TONE.get(item["tag"], DEFAULT_TONE),
                        fg="white", font=(ui.UI, 8), padx=6, pady=1, width=CHIP_W)
        chip.pack(side="left", anchor="n")
        txt = tk.Label(erow, text=pv.show_text(item["text"]), bg=ui.C["card"],
                       fg=ui.C["text"], font=ui.F["body"], anchor="w",
                       justify="left", wraplength=self._wl or 560)
        txt.pack(side="left", fill="x", expand=True, padx=(8, 0))
        self._wrap.append(txt)

        def hover(on):
            bg = ui.C["card_hover"] if on else ui.C["card"]
            erow.configure(bg=bg)
            txt.configure(bg=bg)

        for w in (erow, chip, txt):
            w.bind("<Enter>", lambda _e: hover(True))
            w.bind("<Leave>", lambda _e: hover(False))
        path = item.get("path")
        if path:
            for w in (erow, chip, txt):
                w.configure(cursor="hand2")
                w.bind("<Button-1>",
                       lambda _e, p=path: self.app.goto("notes", path=p))

    def _resize_width(self, width):
        """按窗口宽度换算换行宽度（只在变化时更新，避免 Configure 抖动）。"""
        if width <= 1:
            return
        wl = max(220, width - 200)
        if wl == self._wl:
            return
        self._wl = wl
        for lbl in self._wrap:
            try:
                lbl.configure(wraplength=wl)
            except tk.TclError:
                pass

    # ------------------------------------------------------------------
    def on_show(self, **kw):
        self._render()


def make(master, ctx, app):
    return TimelinePage(master, ctx, app)
