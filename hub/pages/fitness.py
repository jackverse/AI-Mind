# -*- coding: utf-8 -*-
"""健身页：全部指标从 notes/daily-log.md 派生，不新增任何数据文件。"""
import tkinter as tk
from datetime import datetime

import ui
from core import daily


class FitnessPage(tk.Frame):
    def __init__(self, master, ctx, app):
        super().__init__(master, bg=ui.C["bg"])
        self.ctx, self.app = ctx, app
        self.rows = []
        self._build()

    # ------------------------------------------------------------------ UI
    def _build(self):
        bar = tk.Frame(self, bg=ui.C["bg"])
        bar.pack(fill="x", padx=24, pady=(18, 8))
        tk.Label(bar, text="健身", font=(ui.UI, 18, "bold"), bg=ui.C["bg"],
                 fg=ui.C["text"]).pack(side="left")
        self.range_lbl = tk.Label(bar, text="", font=ui.F["small"], bg=ui.C["bg"],
                                  fg=ui.C["muted"])
        self.range_lbl.pack(side="left", padx=10, pady=(6, 0))
        tk.Label(bar, text="数据源：notes/daily-log.md（只读派生）", font=ui.F["small"],
                 bg=ui.C["bg"], fg=ui.C["muted"]).pack(side="right", pady=(6, 0))

        self.tiles = tk.Frame(self, bg=ui.C["bg"])
        self.tiles.pack(fill="x", padx=24)

        chart_card = self._card(self, pady=(12, 0))
        chart_card.pack(fill="x", padx=24)
        head = tk.Frame(chart_card, bg=ui.C["card"])
        head.pack(fill="x", padx=16, pady=(10, 0))
        tk.Label(head, text="体重曲线（斤）", font=(ui.UI, 10, "bold"), bg=ui.C["card"],
                 fg=ui.C["text"]).pack(side="left")
        self.chart_hint = tk.Label(head, text="", font=ui.F["small"], bg=ui.C["card"],
                                   fg=ui.C["muted"])
        self.chart_hint.pack(side="right")
        self.chart = tk.Canvas(chart_card, height=210, bg=ui.C["card"],
                               highlightthickness=0)
        self.chart.pack(fill="x", padx=8, pady=(2, 10))
        self.chart.bind("<Configure>", lambda _e: self._draw_chart())

        bottom = tk.Frame(self, bg=ui.C["bg"])
        bottom.pack(fill="both", expand=True, padx=24, pady=(12, 16))
        bottom.columnconfigure(0, weight=3)
        bottom.columnconfigure(1, weight=2)

        cal_card = self._card(bottom)
        cal_card.grid(row=0, column=0, sticky="nsew", padx=(0, 14))
        tk.Label(cal_card, text="最近 30 天", font=(ui.UI, 10, "bold"), bg=ui.C["card"],
                 fg=ui.C["text"]).pack(anchor="w", padx=16, pady=(10, 2))
        self.cal = tk.Canvas(cal_card, height=140, bg=ui.C["card"], highlightthickness=0)
        self.cal.pack(fill="both", expand=True, padx=12, pady=(0, 10))
        self.cal.bind("<Configure>", lambda _e: self._draw_calendar())

        part_card = self._card(bottom)
        part_card.grid(row=0, column=1, sticky="nsew")
        phead = tk.Frame(part_card, bg=ui.C["card"])
        phead.pack(fill="x", padx=16, pady=(10, 2))
        tk.Label(phead, text="部位分布", font=(ui.UI, 10, "bold"), bg=ui.C["card"],
                 fg=ui.C["text"]).pack(side="left")
        self.best_lbl = tk.Label(phead, text="", font=ui.F["small"], bg=ui.C["card"],
                                 fg=ui.C["muted"])
        self.best_lbl.pack(side="right")
        self.parts = tk.Canvas(part_card, height=140, bg=ui.C["card"],
                               highlightthickness=0)
        self.parts.pack(fill="both", expand=True, padx=12, pady=(0, 10))
        self.parts.bind("<Configure>", lambda _e: self._draw_parts())

    @staticmethod
    def _card(parent, pady=0):
        f = tk.Frame(parent, bg=ui.C["card"], highlightthickness=1,
                     highlightbackground=ui.C["line"])
        return f

    def _tile(self, parent, value, label, color=None):
        box = tk.Frame(parent, bg=ui.C["card"], highlightthickness=1,
                       highlightbackground=ui.C["line"])
        box.pack(side="left", padx=(0, 12))
        inner = tk.Frame(box, bg=ui.C["card"])
        inner.pack(padx=16, pady=8)
        tk.Label(inner, text=str(value), font=(ui.UI, 16, "bold"), bg=ui.C["card"],
                 fg=color or ui.C["accent"]).pack(anchor="w")
        tk.Label(inner, text=label, font=ui.F["small"], bg=ui.C["card"],
                 fg=ui.C["muted"]).pack(anchor="w")

    # ------------------------------------------------------------------ 绘制
    def _draw_chart(self):
        c = self.chart
        c.delete("all")
        ws = daily.weight_series(self.rows)
        if len(ws) < 2:
            c.create_text(20, 20, anchor="nw", text="体重数据不足两天",
                          fill=ui.C["muted"], font=ui.F["small"])
            return
        w = max(c.winfo_width(), 300)
        h = max(c.winfo_height(), 160)
        L, R, T, B = 46, 24, 14, 26
        px0, py0, px1, py1 = L, T, w - R, h - B

        avg = daily.moving_avg(ws, 7)
        dates = [d for d, _ in ws]
        d0 = datetime.strptime(dates[0], "%Y-%m-%d").date().toordinal()
        d1 = datetime.strptime(dates[-1], "%Y-%m-%d").date().toordinal()
        span = max(d1 - d0, 1)
        vals = [v for _, v in ws] + [v for _, v in avg]
        lo, hi = min(vals), max(vals)
        pad = max(0.6, (hi - lo) * 0.12)
        lo, hi = lo - pad, hi + pad

        def X(d):
            o = datetime.strptime(d, "%Y-%m-%d").date().toordinal()
            return px0 + (o - d0) / span * (px1 - px0)

        def Y(v):
            return py1 - (v - lo) / (hi - lo) * (py1 - py0)

        # 横向网格 + 刻度
        for i in range(4):
            v = lo + (hi - lo) * i / 3
            y = Y(v)
            c.create_line(px0, y, px1, y, fill="#eef1f6")
            c.create_text(px0 - 8, y, text=f"{v:.1f}", anchor="e",
                          fill=ui.C["muted"], font=(ui.UI, 8))
        # 7 日均线
        c.create_line(*[coord for d, v in avg for coord in (X(d), Y(v))],
                      fill="#9db4e8", width=1.6, smooth=True, dash=(4, 3))
        # 体重折线
        coords = [coord for d, v in ws for coord in (X(d), Y(v))]
        c.create_line(*coords, fill=ui.C["accent"], width=2.2, smooth=True)
        for d, v in ws:
            c.create_oval(X(d) - 2.4, Y(v) - 2.4, X(d) + 2.4, Y(v) + 2.4,
                          fill=ui.C["accent"], outline="")
        # 最低点
        dm, vm = min(ws, key=lambda t: t[1])
        c.create_oval(X(dm) - 4, Y(vm) - 4, X(dm) + 4, Y(vm) + 4,
                      fill=ui.C["ok"], outline="")
        c.create_text(X(dm) + (-8 if X(dm) > px1 - 60 else 8), Y(vm) - 10,
                      text=f"最低 {vm:g}", fill=ui.C["ok"], font=(ui.UI, 8, "bold"),
                      anchor="e" if X(dm) > px1 - 60 else "w")
        # 首末标注
        for d, v in (ws[0], ws[-1]):
            c.create_text(X(d), Y(v) + 13, text=f"{v:g}", fill=ui.C["muted"],
                          font=(ui.UI, 8))
        c.create_text(px0, py1 + 14, text=dates[0][5:], anchor="w",
                      fill=ui.C["muted"], font=(ui.UI, 8))
        c.create_text(px1, py1 + 14, text=dates[-1][5:], anchor="e",
                      fill=ui.C["muted"], font=(ui.UI, 8))

        s = daily.summary(self.rows)
        self.chart_hint.configure(
            text=f"实线=体重　虚线=7 日均　共 {len(ws)} 个数据点　"
                 f"{s['w_first'][1]:g} → {s['w_last'][1]:g}（{'-' if s['w_delta']>0 else '+'}"
                 f"{abs(s['w_delta']):g} 斤）")

    def _draw_calendar(self):
        c = self.cal
        c.delete("all")
        days = daily.calendar(self.rows, n=30)
        w = max(c.winfo_width(), 300)
        cell, gap = 26, 6
        cols = max(8, min(10, int((w - 10) // (cell + gap))))
        rows_n = (len(days) + cols - 1) // cols
        x0, y0 = 6, 6
        colors = {"train": ui.C["accent"], "rest": "#f0b46a",
                  "plan": "#b9ccf2", None: "#eceff4"}
        for i, (d, st) in enumerate(days):
            r, cidx = divmod(i, cols)
            x = x0 + cidx * (cell + gap)
            y = y0 + r * (cell + gap)
            c.create_rectangle(x, y, x + cell, y + cell,
                               fill=colors.get(st, "#eceff4"), outline="")
        # 图例
        ly = y0 + rows_n * (cell + gap) + 6
        lx = x0
        for label, color in (("训练", colors["train"]), ("休息", colors["rest"]),
                             ("计划", colors["plan"]), ("未记录", colors[None])):
            c.create_rectangle(lx, ly, lx + 10, ly + 10, fill=color, outline="")
            c.create_text(lx + 14, ly + 5, text=label, anchor="w",
                          fill=ui.C["muted"], font=(ui.UI, 8))
            lx += 20 + len(label) * 13

    def _draw_parts(self):
        c = self.parts
        c.delete("all")
        parts = daily.part_counts(self.rows)
        if not parts:
            c.create_text(10, 10, anchor="nw", text="还没有训练记录",
                          fill=ui.C["muted"], font=ui.F["small"])
            return
        w = max(c.winfo_width(), 200)
        top = 4
        rowh = 24
        mx = max(n for _, n in parts)
        label_w = 56
        for i, (name, n) in enumerate(parts[:6]):
            y = top + i * rowh
            c.create_text(0, y + 8, text=name, anchor="w", fill=ui.C["text"],
                          font=(ui.UI, 9))
            bar_w = (w - label_w - 40) * n / mx
            c.create_rectangle(label_w, y + 1, label_w + bar_w, y + 16,
                               fill="#cfe0ff", outline="")
            c.create_text(label_w + bar_w + 8, y + 8, text=str(n), anchor="w",
                          fill=ui.C["muted"], font=(ui.UI, 8))

    # ------------------------------------------------------------------
    def on_show(self, **kw):
        try:
            text = self.ctx.read_text("notes/daily-log.md")
        except OSError:
            text = ""
        self.rows = daily.parse_text(text) if text else []
        for w in self.tiles.winfo_children():
            w.destroy()
        if not self.rows:
            self.range_lbl.configure(text="未找到 daily-log.md")
            return
        s = daily.summary(self.rows)
        txt = f"{self.rows[0]['md']} ~ {self.rows[-1]['md']}　共 {s['days']} 天记录"
        plan = daily.planned_today(self.rows)
        if plan:
            txt += f"　｜　今日计划：{plan}"
        self.range_lbl.configure(text=txt)
        self._tile(self.tiles, s["rec_streak"], "连续记录（天）")
        self._tile(self.tiles, f"{s['train']} / {s['rest']}", "训练 / 休息（天）")
        self._tile(self.tiles, f"{s['rate']}%", "打卡率")
        delta = s["w_delta"]
        self._tile(self.tiles, f"-{delta:g}" if delta > 0 else f"+{abs(delta):g}",
                   f"体重变化（斤，{s['w_first'][1]:g}→{s['w_last'][1]:g}）",
                   ui.C["ok"] if delta > 0 else ui.C["bad"])
        self.best_lbl.configure(text=f"最长连续训练 {s['best_streak']} 天")
        self._draw_chart()
        self._draw_calendar()
        self._draw_parts()


def make(master, ctx, app):
    return FitnessPage(master, ctx, app)
