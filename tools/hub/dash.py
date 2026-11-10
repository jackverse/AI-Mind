# -*- coding: utf-8 -*-
"""仪表盘控件库（抖音 / 小红书等数据页共用）。

tkinter 自带控件偏「工程感」：灰底、方角、小字、表格挤。这里补一层视觉组件，
全部用 Canvas 手绘，**零第三方依赖**（打包后体积不变）：

  · Card      圆角卡片（白色底 + 1px 描边），内容自动撑高
  · StatTile  指标卡：标签 / 大数字 / 环比
  · Pill      胶囊标签（账号名、体裁、状态）
  · Btn       扁平按钮：primary / soft / ghost / plain，带悬停
  · ScrollArea 竖向滚动区（滚轮只在指针进入时生效，表格自己滚）
  · LineChart 面积折线图：网格 + 峰值标注 + 悬停十字线
  · BarList   横向条形榜：榜首高亮 + 悬停看标题
  · AccountTable 分账号对照表（带占比条）
  · DataTable 可排序明细表：斑马纹 + 行悬停 + 表头排序 + 搜索

字体、颜色统一从 ui.C / ui.F 取，页面里不再写死字号。
"""
import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk

import ui

# ------------------------------------------------------------------ 设计变量
MUTED = "#5f6b80"          # 比 ui.C["muted"] 深一点：9pt 小字也能看清
FAINT = "#8a94a6"
LINE = "#e6eaf2"
SOFT = "#f7f9fc"           # 表头、轨道底色
ACCENT = ui.C["accent"]
ACCENT_SOFT = "#e9f0fd"
ACCENT_2 = "#a9c2f4"       # 次级条形（非榜首）
OK, BAD = ui.C["ok"], ui.C["bad"]
TRACK = "#eef2f8"

RADIUS = 14
PAD = 16                   # 卡片内边距
GAP = 12                   # 卡片间距
# 多账号对比配色（折线 / 分组柱 / 图例共用：同一账号在各图里颜色一致）
SERIES_COLORS = ("#3d6ee0", "#e0795c", "#3f9d69", "#c07c26",
                 "#8a6bd0", "#3f9fb8", "#c2453e", "#7a8aa8")

_FONT_CACHE = {}


def f(size, bold=False):
    """字体元组。bold=True 时加粗。"""
    return (ui.UI, size, "bold") if bold else (ui.UI, size)


def measure(text, font):
    """文本像素宽（建一次缓存，别每个控件都 new 一个 Font）。"""
    key = (font, text)
    got = _FONT_CACHE.get(key)
    if got is None:
        key = ("font", font)
        tf = _FONT_CACHE.get(key)
        if tf is None:
            tf = _FONT_CACHE[key] = tkfont.Font(font=font)
        got = _FONT_CACHE[(font, text)] = tf.measure(text)
    return got


def _round_pts(x0, y0, x1, y1, r):
    """圆角矩形的平滑多边形顶点。"""
    r = max(0, min(r, (x1 - x0) / 2, (y1 - y0) / 2))
    return [x0 + r, y0, x1 - r, y0, x1, y0, x1, y0 + r, x1, y1 - r, x1, y1,
            x1 - r, y1, x0 + r, y1, x0, y1, x0, y1 - r, x0, y0 + r, x0, y0]


def round_rect(cv, x0, y0, x1, y1, r, **kw):
    return cv.create_polygon(_round_pts(x0, y0, x1, y1, r), smooth=True, **kw)


# ------------------------------------------------------------------ 卡片
class Card(tk.Canvas):
    """圆角卡片。内容放 `card.content`，卡片高度跟着内容走。

    用法：
        card = Card(parent)
        card.pack(fill="x")
        tk.Label(card.content, ...).pack(...)
    """

    def __init__(self, master, padx=PAD, pady=14, radius=RADIUS, fill=None,
                 outline=LINE, outer_bg=None):
        super().__init__(master, bd=0, highlightthickness=0, takefocus=0,
                         bg=outer_bg or _bg_of(master))
        self._px, self._py, self._r = padx, pady, radius
        self._fill = fill or ui.C["card"]
        self._outline = outline
        self._h = 1
        self.content = tk.Frame(self, bg=self._fill)
        self._win = self.create_window(padx, pady, window=self.content, anchor="nw")
        self._shape = None
        self.bind("<Configure>", self._on_resize)
        self.content.bind("<Configure>", self._on_content)

    def _on_resize(self, event):
        self.itemconfigure(self._win, width=max(1, event.width - 2 * self._px))
        self._paint(event.width, event.height)

    def _on_content(self, _event=None):
        need = self.content.winfo_reqheight() + 2 * self._py
        if abs(need - self._h) > 1:
            self._h = need
            self.configure(height=need)
            self._paint(self.winfo_width(), need)

    def _paint(self, w, h):
        if w < 4 or h < 4:
            return
        if self._shape is None:
            self._shape = round_rect(self, 1, 1, w - 1, h - 1, self._r,
                                     fill=self._fill,
                                     outline=self._outline or "", width=1)
            self.tag_lower(self._shape)
        else:
            self.coords(self._shape, *_round_pts(1, 1, w - 1, h - 1, self._r))
            self.itemconfigure(self._shape, fill=self._fill,
                               outline=self._outline or "")
            self.tag_lower(self._shape)


def _bg_of(widget):
    try:
        return widget.cget("bg")
    except tk.TclError:
        return ui.C["bg"]


# ------------------------------------------------------------------ 指标卡
class StatTile(Card):
    """指标卡：小标签 / 大数字 / 环比 + 备注。窄窗口里数字自动缩小一号。"""

    def __init__(self, master, label, value, note="", delta=None, good_when_up=True,
                 value_color=None, padx=18, pady=14):
        super().__init__(master, padx=padx, pady=pady)
        self._value_color = value_color or ui.C["text"]
        self._fsize = 20
        self._note_text = note
        tk.Label(self.content, text=label, font=f(9), bg=self._fill, fg=MUTED,
                 anchor="w").pack(fill="x")
        self.val = tk.Label(self.content, text=value, font=f(20, True), bg=self._fill,
                            fg=self._value_color, anchor="w")
        self.val.pack(fill="x", pady=(5, 2))
        self.bind("<Configure>", self._fit_value, add="+")
        row = tk.Frame(self.content, bg=self._fill)
        row.pack(fill="x")
        self.delta = None
        if delta is not None:
            up = delta >= 0
            good = up if good_when_up else not up
            color = OK if good else BAD
            self.delta = tk.Label(
                row, text=f"{'↑' if up else '↓'} {abs(delta) * 100:.0f}%", font=f(9, True),
                bg=self._fill, fg=color)
            self.delta.pack(side="left")
        self.note = tk.Label(row, text=note, font=f(9), bg=self._fill, fg=FAINT,
                             anchor="w")
        self.note.pack(side="left", padx=(6 if delta is not None else 0, 0))
        if not note:
            self.note.pack_forget()

    def set_value(self, value, color=None):
        self.val.configure(text=value, fg=color or self._value_color)
        self._fit_value()

    def _fit_value(self, event=None):
        """数字太长就缩一号（130px 的格子里「18,323」不要被切掉）。

        格子再窄就别硬塞备注了（「↑36% 近 7 天 4,885」会把边框顶穿）。
        """
        width = (event.width if event is not None else self.winfo_width()) - 2 * self._px
        text = self.val.cget("text")
        size = 20
        while size > 13 and measure(text, (ui.UI, size, "bold")) > max(40, width):
            size -= 1
        if size != self._fsize:
            self._fsize = size
            self.val.configure(font=(ui.UI, size, "bold"))
        want_note = width >= 150 and bool(self._note_text)
        has_note = bool(self.note.winfo_manager())
        if want_note and not has_note:
            self.note.pack(side="left", padx=(6 if self.delta is not None else 0, 0))
        elif not want_note and has_note:
            self.note.pack_forget()

    def set_note(self, text):
        self.note.configure(text=text)
        if text:
            self.note.pack(side="left", padx=(6 if self.delta is not None else 0, 0))
        else:
            self.note.pack_forget()


# ------------------------------------------------------------------ 胶囊 / 按钮
class Pill(tk.Canvas):
    """胶囊标签：账号、体裁、状态。"""

    def __init__(self, master, text, fg=ACCENT, fill=ACCENT_SOFT, height=22,
                 pad=9, font=None):
        self._font = font or f(9, True)
        w = measure(text, self._font) + 2 * pad
        super().__init__(master, width=w, height=height, bd=0, highlightthickness=0,
                         takefocus=0, bg=_bg_of(master))
        self._pad, self._h = pad, height
        self._shape = round_rect(self, 0, 0, w, height, height / 2, fill=fill,
                                 outline="")
        self._text = self.create_text(w / 2, height / 2, text=text, fill=fg,
                                      font=self._font)

    def set_text(self, text, fg=None, fill=None):
        self.itemconfigure(self._text, text=text)
        if fg:
            self.itemconfigure(self._text, fill=fg)
        if fill:
            self.itemconfigure(self._shape, fill=fill)
        w = measure(text, self._font) + 2 * self._pad
        self.configure(width=w)
        self.coords(self._shape, *_round_pts(0, 0, w, self._h, self._h / 2))
        self.coords(self._text, w / 2, self._h / 2)


class Segment(tk.Canvas):
    """分段控件（概览 / 明细）：一眼看出当前在看哪一屏。"""

    def __init__(self, master, items, command=None, value=0, height=30, pad=14):
        self._font = f(9, True)
        self._pad = pad
        self._items = list(items)
        self._widths = [measure(t, self._font) + 2 * pad for t in self._items]
        self._value = value
        self._command = command
        self._h = height
        w = sum(self._widths) + 4
        super().__init__(master, width=w, height=height, bd=0, highlightthickness=0,
                         takefocus=0, cursor="hand2", bg=_bg_of(master))
        self.bind("<Button-1>", self._click)
        self._paint()

    def _paint(self):
        self.delete("all")
        w = sum(self._widths) + 4
        round_rect(self, 0, 0, w, self._h, self._h / 2, fill="#eaeef6", outline="")
        x = 2
        for i, (text, wd) in enumerate(zip(self._items, self._widths)):
            on = i == self._value
            if on:
                round_rect(self, x, 2, x + wd, self._h - 2, (self._h - 4) / 2,
                           fill=ui.C["card"], outline="#e3e9f3")
            self.create_text(x + wd / 2, self._h / 2, text=text,
                             fill=ui.C["text"] if on else MUTED,
                             font=self._font)
            x += wd

    def set_value(self, i):
        if i != self._value:
            self._value = i
            self._paint()

    def set_items(self, items, value=0):
        """换一组标签（账号 tab 会随账号列表变），宽度重算。"""
        self._items = list(items)
        self._widths = [measure(t, self._font) + 2 * self._pad for t in self._items]
        self._value = max(0, min(int(value or 0), max(0, len(self._items) - 1)))
        w = sum(self._widths) + 4
        self.configure(width=w)
        self._paint()

    def _click(self, event):
        x = 2
        for i, wd in enumerate(self._widths):
            if x <= event.x <= x + wd:
                if i != self._value:
                    self._value = i
                    self._paint()
                    if self._command:
                        self._command(i)
                return
            x += wd


class Btn(tk.Canvas):
    """扁平按钮。kind: primary / soft / ghost / plain。"""

    STYLES = {
        "primary": (ACCENT, "white", ""),
        "soft": (ACCENT_SOFT, ACCENT, ""),
        "ghost": (ui.C["card"], ui.C["text"], LINE),
        "plain": ("", MUTED, ""),
    }
    HOVER = {
        "primary": "#3562cc",
        "soft": "#dde8fc",
        "ghost": "#f2f5fb",
        "plain": "#f2f5fb",
    }

    def __init__(self, master, text, command=None, kind="ghost", height=30,
                 pad=14, font=None, radius=9):
        self._font = font or f(10, True)
        fill, fg, outline = self.STYLES[kind]
        w = measure(text, self._font) + 2 * pad
        super().__init__(master, width=w, height=height, bd=0, highlightthickness=0,
                         takefocus=0, cursor="hand2",
                         bg=outline or _bg_of(master))
        self._kind, self._r, self._h = kind, radius, height
        self._enabled = True
        self._pad = pad
        self.command = command
        self._bg = round_rect(self, 0, 0, w, height, radius, fill=fill,
                              outline=outline or "", width=1)
        self._tx = self.create_text(w / 2, height / 2, text=text, fill=fg,
                                    font=self._font)
        self.bind("<Button-1>", self._click)
        self.bind("<Enter>", lambda _e: self._paint(hover=True))
        self.bind("<Leave>", lambda _e: self._paint(hover=False))

    def _paint(self, hover=False):
        fill, fg, outline = self.STYLES[self._kind]
        if not self._enabled:
            self.itemconfigure(self._bg, fill="#eef1f6", outline="")
            self.itemconfigure(self._tx, fill=FAINT)
            return
        self.itemconfigure(self._bg, fill=self.HOVER[self._kind] if hover else fill,
                           outline=outline or "")
        self.itemconfigure(self._tx, fill=fg)

    def _click(self, _e=None):
        if self._enabled and self.command:
            self.command()

    def set_enabled(self, on):
        self._enabled = bool(on)
        self.configure(cursor="hand2" if on else "arrow")
        self._paint(False)

    set_state = set_enabled

    def set_text(self, text):
        """换文案并重算宽度（「登录」登录后变成「账号…」）。"""
        w = measure(text, self._font) + 2 * self._pad
        self.configure(width=w)
        self.itemconfigure(self._tx, text=text)
        self.coords(self._bg, *_round_pts(0, 0, w, self._h, self._r))
        self.coords(self._tx, w / 2, self._h / 2)


# ------------------------------------------------------------------ 滚动区
class ScrollArea(tk.Frame):
    """竖向滚动区：`area.body` 里放内容，`area.scroll_top()` 回到顶部。

    滚轮只绑到内容里的控件（bind_wheel），避开 ttk.Treeview / Text 自己的滚动。
    """

    SKIP = (ttk.Treeview, tk.Text, tk.Listbox, ttk.Scrollbar, ttk.Combobox)

    def __init__(self, master, bg=None):
        bg = bg or ui.C["bg"]
        super().__init__(master, bg=bg)
        self.canvas = tk.Canvas(self, bg=bg, bd=0, highlightthickness=0,
                                yscrollincrement=22)
        self.bar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview,
                                 style="Dash.Vertical.TScrollbar")
        self.canvas.configure(yscrollcommand=self._on_view)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.bar.grid(row=0, column=1, sticky="ns")
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)
        self.body = tk.Frame(self.canvas, bg=bg)
        self._win = self.canvas.create_window((0, 0), window=self.body, anchor="nw")
        self.body.bind("<Configure>", self._sync)
        self.canvas.bind("<Configure>", self._on_canvas)
        self._bar_on = True

    def _on_canvas(self, event):
        self.canvas.itemconfigure(self._win, width=event.width)
        self._sync()

    def _sync(self, _event=None):
        h = max(self.body.winfo_reqheight(), 1)
        self.canvas.configure(scrollregion=(0, 0, self.canvas.winfo_width(), h))
        need = h > self.canvas.winfo_height() + 1
        if need != self._bar_on:
            self._bar_on = need
            (self.bar.grid if need else self.bar.grid_remove)()

    def _on_view(self, first, last):
        self.bar.set(first, last)

    def bind_wheel(self, root=None):
        """把滚轮绑到内容里的每个控件（重建内容后调一次）。"""
        for w in _walk(root or self.body):
            if isinstance(w, self.SKIP):
                continue
            w.bind("<MouseWheel>", self._wheel, add="+")

    def _wheel(self, event):
        if self._bar_on:
            self.canvas.yview_scroll(-1 if event.delta > 0 else 1, "units")
        return "break"

    def scroll_top(self):
        self.canvas.yview_moveto(0)


def _walk(widget):
    yield widget
    for child in widget.winfo_children():
        yield from _walk(child)


# ------------------------------------------------------------------ 折线图
class LineChart(tk.Canvas):
    """折线图：单序列带面积；多序列按账号分色，图例 + 悬停显示各条数值。"""

    def __init__(self, master, height=200, color=ACCENT, fill="#eaf0fc"):
        super().__init__(master, height=height, bd=0, highlightthickness=0,
                         bg=ui.C["card"])
        self._color, self._fillc = color, fill
        self._lines = []           # [{label, color, fill, points:[(date, value)]}]
        self._multi = False
        self._plot = None
        self._tip = []
        self.bind("<Configure>", lambda _e: self.redraw())
        self.bind("<Motion>", self._hover)
        self.bind("<Leave>", lambda _e: self._clear_tip())

    # ---------------------------------------------------------- 数据
    def set_series(self, series, color=None, fill=None):
        """单条线（兼容旧用法）。"""
        pts = [(str(d)[:10], float(v or 0)) for d, v in series]
        if color:
            self._color = color
        if fill:
            self._fillc = fill
        self._lines = [{"label": "", "color": self._color,
                        "fill": self._fillc, "points": pts}]
        self._multi = False
        self.redraw()

    def set_multi(self, lines):
        """多条线：lines=[{label, color, points:[(date, value)]}]，同一账号颜色固定。"""
        self._lines = []
        for i, ln in enumerate(lines):
            pts = [(str(d)[:10], float(v or 0))
                   for d, v in (ln.get("points") or [])]
            self._lines.append({
                "label": str(ln.get("label") or ""),
                "color": ln.get("color") or SERIES_COLORS[i % len(SERIES_COLORS)],
                "fill": None,
                "points": pts,
            })
        self._multi = len(self._lines) > 1
        self.redraw()

    def _axis(self):
        return sorted({d for ln in self._lines for d, _ in ln["points"]})

    def redraw(self):
        self.delete("all")
        w, h = self.winfo_width(), self.winfo_height()
        if w < 120 or h < 80:
            return
        axis = self._axis()
        if len(axis) < 2:
            self.create_text(w // 2, h // 2, text="数据点不足（同步后自动出现趋势）",
                             fill=FAINT, font=f(10))
            self._plot = None
            return
        L, R, B = 52, 14, 26
        T = 38 if self._multi else 16
        px0, px1 = L, w - R
        py0, py1 = T, h - B
        vals = [v for ln in self._lines for _, v in ln["points"]]
        ymax = _nice_max(max(vals) or 1)
        self._plot = (L, R, T, B, px0, px1, py0, py1, ymax, axis)

        for i in range(5):
            y = py0 + (py1 - py0) * i / 4
            self.create_line(px0, y, px1, y, fill=LINE if i else "#dfe5ef")
            self.create_text(px0 - 10, y, text=_fmt_short(ymax * (4 - i) / 4),
                             anchor="e", fill=FAINT, font=f(9))

        n = len(axis)
        index = {d: i for i, d in enumerate(axis)}

        def xy(i, v):
            x = px0 + (px1 - px0) * i / (n - 1)
            y = py1 - (py1 - py0) * min(1.0, v / ymax)
            return x, y

        for ln in self._lines:
            pts = [(index[d], v) for d, v in ln["points"] if d in index]
            if len(pts) < 2:
                continue
            screen = [xy(i, v) for i, v in pts]
            if not self._multi:
                self.create_polygon(
                    [px0, py1] + [c for p in screen for c in p] + [px1, py1],
                    fill=ln["fill"] or self._fillc, outline="")
            self.create_line(*[c for p in screen for c in p], fill=ln["color"],
                             width=2, joinstyle="round", capstyle="round")
            if not self._multi:
                pi = max(range(len(pts)), key=lambda k: pts[k][1])
                x, y = screen[pi]
                self.create_oval(x - 3.4, y - 3.4, x + 3.4, y + 3.4,
                                 fill=ln["color"], outline=ui.C["card"], width=1.5)
                self._tag_text(x, y - 8, f"{int(pts[pi][1]):,}", anchor="s",
                               color=ui.C["text"], bold=True)

        # 图例（多账号时才画）
        if self._multi:
            lx = px0
            for ln in self._lines:
                label = ln["label"]
                if not label:
                    continue
                self.create_oval(lx, 8, lx + 7, 15, fill=ln["color"], outline="")
                self.create_text(lx + 11, 11, text=label[:10], anchor="w",
                                 fill=MUTED, font=f(9))
                lx += 11 + measure(label[:10], f(9)) + 14
                if lx > px1 - 30:
                    break

        # X 轴：按可用宽度决定刻几个（窄窗口少画几个，别叠在一起）
        max_ticks = max(2, int((px1 - px0) / 92) + 1)
        step = max(1, (n - 1) // max(1, max_ticks - 1))
        idxs = []
        for i in range(0, n, step):
            if i != n - 1 and px0 + (px1 - px0) * i / (n - 1) > px1 - 64:
                continue
            idxs.append(i)
        if (n - 1) not in idxs:
            idxs.append(n - 1)
        for i in idxs:
            x = px0 + (px1 - px0) * i / (n - 1)
            anchor = "w" if i == 0 else ("e" if i == n - 1 else "center")
            self.create_text(x, h - 8, text=axis[i][5:], fill=FAINT,
                             font=f(9), anchor=anchor)

    def _tag_text(self, x, y, text, anchor="s", color=None, bold=False, bg=None):
        """带底衬的字（避免压在线上看不清）。"""
        font = f(9, bold)
        tw = measure(text, font)
        padx, pady = 5, 2
        if anchor == "s":
            box = (x - tw / 2 - padx, y - 13 - pady, x + tw / 2 + padx, y + pady)
            tx, ty, ta = x, y - 6, "s"
        elif anchor == "w":
            box = (x, y - 7 - pady, x + tw + 2 * padx, y + 7 + pady)
            tx, ty, ta = x + padx, y, "w"
        else:
            box = (x - tw - 2 * padx, y - 7 - pady, x, y + 7 + pady)
            tx, ty, ta = x - padx, y, "e"
        round_rect(self, *box, 5, fill=bg or ui.C["card"], outline="")
        self.create_text(tx, ty, text=text, fill=color or MUTED, font=font, anchor=ta)

    # ---------------------------------------------------------- 悬停
    def _clear_tip(self):
        for i in self._tip:
            self.delete(i)
        self._tip = []

    def _hover(self, event):
        plot = self._plot
        if not plot:
            return
        L, R, T, B, px0, px1, py0, py1, ymax, axis = plot
        if not (px0 - 4 <= event.x <= px1 + 4 and py0 - 4 <= event.y <= py1 + 4):
            self._clear_tip()
            return
        n = len(axis)
        ratio = (event.x - px0) / max(1, px1 - px0)
        i = max(0, min(n - 1, round(ratio * (n - 1))))
        x = px0 + (px1 - px0) * i / (n - 1)
        day = axis[i]
        self._clear_tip()
        self._tip.append(self.create_line(x, py0, x, py1, fill="#c9d3e6", dash=(3, 3)))

        items = []
        for ln in self._lines:
            v = dict(ln["points"]).get(day)
            if v is None:
                continue
            y = py1 - (py1 - py0) * min(1.0, v / ymax)
            self._tip.append(self.create_oval(x - 3.6, y - 3.6, x + 3.6, y + 3.6,
                                              fill="white", outline=ln["color"],
                                              width=2))
            items.append((ln["label"], v, ln["color"]))

        if not items:
            return
        head = day[5:]
        rows = [head] + [((f"{lab}  " if lab else "") + f"{int(v):,}") for lab, v, _c in items]
        font = f(9, True)
        bw = max(measure(t, font) for t in rows) + 16
        bh = 10 + 15 * len(rows)
        bx = min(max(x - bw / 2, px0), max(px0, px1 - bw))
        by = py0 + 2
        self._tip.append(round_rect(self, bx, by, bx + bw, by + bh, 7,
                                    fill=ui.C["text"], outline=""))
        ty = by + 7
        for k, text in enumerate(rows):
            self.create_text(bx + 8, ty, text=text, anchor="nw", fill="white",
                             font=font)
            if k > 0:
                color = items[k - 1][2]
                self.create_oval(bx + bw - 12, ty + 4, bx + bw - 6, ty + 10,
                                 fill=color, outline="")
            ty += 15
        for i2 in self._tip:
            self.tag_raise(i2)


# ------------------------------------------------------------------ 条形榜
class BarList(tk.Canvas):
    """横向条形榜：单条（Top N）或分组多条（多账号按天对比，多个柱子并排）。"""

    def __init__(self, master, height=200, label_w=54, value_w=74, rows=6,
                 on_hover=None):
        super().__init__(master, height=height, bd=0, highlightthickness=0,
                         bg=ui.C["card"])
        self._rows, self._groups = [], []
        self._label_w, self._value_w = label_w, value_w
        self._max_rows = rows
        self._hover_i = None
        self._on_click = None
        self._on_hover = on_hover
        self._multi = False
        self.bind("<Configure>", lambda _e: self.redraw())
        self.bind("<Motion>", self._motion)
        self.bind("<Leave>", lambda _e: self._set_hover(None))
        self.bind("<Button-1>", self._click)

    def set_rows(self, rows, on_click=None, on_hover=None):
        """rows: [(左边标签, 数值, 悬停用的标题)]，自动只显示前 N 条。"""
        self._rows = list(rows)[: self._max_rows]
        self._groups = []
        self._multi = False
        self._on_click = on_click
        if on_hover is not None:
            self._on_hover = on_hover
        self.redraw()

    def set_groups(self, groups, on_hover=None):
        """groups: [(左边标签, [各账号数值], 悬停标题)] —— 每行画多个柱子。"""
        self._groups = list(groups)[: self._max_rows]
        self._rows = []
        self._multi = True
        if on_hover is not None:
            self._on_hover = on_hover
        self.redraw()

    def _count(self):
        return len(self._groups) if self._multi else len(self._rows)

    @staticmethod
    def _short(label):
        s = str(label)
        return s[5:] if len(s) >= 10 and s[4:5] == "-" else s

    def redraw(self):
        self.delete("all")
        w, h = self.winfo_width(), self.winfo_height()
        if w < 120 or h < 40:
            return
        n = self._count()
        if not n:
            self.create_text(w / 2, h / 2, text="还没有数据", fill=FAINT, font=f(10))
            return
        self._draw_chrome(w, h)
        if self._multi:
            self._draw_groups(w, h, n)
        else:
            self._draw_rows(w, h, n)

    def _draw_chrome(self, w, h):
        return None

    def _draw_rows(self, w, h, n):
        rows = self._rows
        vmax = max(v for _, v, _ in rows) or 1
        row_h = (h - 8) / n
        bar_h = max(8, min(16, row_h * 0.5))
        bx0 = self._label_w
        bx1 = w - self._value_w
        for i, (label, value, _title) in enumerate(rows):
            cy = 4 + row_h * i + row_h / 2
            if i == self._hover_i:
                round_rect(self, 0, cy - row_h / 2 + 1, w, cy + row_h / 2 - 1, 8,
                           fill="#f4f7fe", outline="")
            self.create_text(2, cy, text=self._short(label), anchor="w", fill=MUTED,
                             font=f(9))
            round_rect(self, bx0, cy - bar_h / 2, bx1, cy + bar_h / 2, bar_h / 2,
                       fill=TRACK, outline="")
            wpx = max(4, (bx1 - bx0) * (value / vmax))
            if wpx <= bar_h:
                self.create_oval(bx0, cy - bar_h / 2, bx0 + bar_h, cy + bar_h / 2,
                                 fill=ACCENT if i == 0 else ACCENT_2, outline="")
            else:
                round_rect(self, bx0, cy - bar_h / 2, bx0 + wpx, cy + bar_h / 2,
                           bar_h / 2, fill=ACCENT if i == 0 else ACCENT_2, outline="")
            self.create_text(w - 2, cy, text=_fmt_short(value), anchor="e",
                             fill=ui.C["text"] if i == 0 else MUTED,
                             font=f(9, i == 0))

    def _draw_groups(self, w, h, n):
        groups = self._groups
        k = max(len(vals) for _lab, vals, _t in groups) or 1
        vmax = max((max(vals) if vals else 0) for _lab, vals, _t in groups) or 1
        row_h = (h - 8) / n
        gap = 2
        bar_h = max(3, min(11, (row_h * 0.62 - gap * (k - 1)) / k))
        bx0 = self._label_w
        bx1 = w - self._value_w
        for i, (label, vals, _title) in enumerate(groups):
            cy = 4 + row_h * i + row_h / 2
            if i == self._hover_i:
                round_rect(self, 0, cy - row_h / 2 + 1, w, cy + row_h / 2 - 1, 8,
                           fill="#f4f7fe", outline="")
            self.create_text(2, cy, text=self._short(label), anchor="w",
                             fill=MUTED, font=f(9))
            total = sum(vals or [])
            y0 = cy - (bar_h * k + gap * (k - 1)) / 2
            for j, v in enumerate(vals):
                y = y0 + j * (bar_h + gap)
                color = SERIES_COLORS[j % len(SERIES_COLORS)]
                pw = max(2, (bx1 - bx0) * (v / vmax))
                round_rect(self, bx0, y, bx0 + pw, y + bar_h, bar_h / 2,
                           fill=color, outline="")
            self.create_text(w - 2, cy, text=_fmt_short(total), anchor="e",
                             fill=MUTED, font=f(9))

    def _row_at(self, y):
        n = self._count()
        if not n:
            return None
        row_h = (self.winfo_height() - 8) / n
        i = int((y - 4) / row_h)
        return i if 0 <= i < n else None

    def _motion(self, event):
        i = self._row_at(event.y)
        if i != self._hover_i:
            self._set_hover(i)

    def _set_hover(self, i):
        self._hover_i = i
        self.redraw()
        if self._on_hover:
            if i is None:
                title = None
            elif self._multi:
                title = self._groups[i][2] if i < len(self._groups) else None
            else:
                title = self._rows[i][2] if i < len(self._rows) else None
            self._on_hover(title)

    def _click(self, event):
        i = self._row_at(event.y)
        if i is not None and self._on_click:
            self._on_click(i)


# ------------------------------------------------------------------ 分账号表
class AccountTable(tk.Canvas):
    """分账号对照：账号 / 作品 / 播放 / 占比条 / 完播 / 涨粉。"""

    def __init__(self, master, cols=("作品", "播放", "占比", "完播", "涨粉")):
        self._cols = cols
        super().__init__(master, height=26 + 30, bd=0, highlightthickness=0,
                         bg=ui.C["card"])
        self._rows = []
        self.bind("<Configure>", lambda _e: self.redraw())

    def set_rows(self, rows):
        self._rows = list(rows)
        self.configure(height=30 + 32 * max(1, len(self._rows)))
        self.redraw()

    def redraw(self):
        self.delete("all")
        w = self.winfo_width()
        if w < 160:
            return
        ncol = len(self._cols)
        name_w = max(120, min(210, w * 0.28))
        rest = (w - name_w) / ncol
        xs = [name_w + rest * i for i in range(ncol)]

        self.create_text(2, 15, text="账号", anchor="w", fill=FAINT, font=f(9))
        for i, label in enumerate(self._cols):
            self.create_text(xs[i] + rest - 8, 15, text=label, anchor="e", fill=FAINT,
                             font=f(9))
        self.create_line(0, 29, w, 29, fill=LINE)
        for r, row in enumerate(self._rows):
            y = 30 + 32 * r + 16
            if r % 2:
                self.create_rectangle(0, y - 16, w, y + 16, fill="#fbfcfe", outline="")
            name = row.get("name") or ""
            self.create_text(2, y, text=name, anchor="w", fill=ui.C["text"],
                             font=f(10, True))
            sub = row.get("sub") or ""
            if sub:
                self.create_text(2 + measure(name, f(10, True)) + 8, y, text=sub,
                                 anchor="w", fill=FAINT, font=f(9))
            for i, val in enumerate(row.get("cells") or []):
                cx = xs[i] + rest - 8
                if i == 2:
                    # 占比：一条细条 + 百分比
                    share = float(str(val).rstrip("%") or 0) / 100
                    bar_w = rest - 54
                    round_rect(self, xs[i] + 6, y - 4, xs[i] + 6 + bar_w, y + 4, 4,
                               fill=TRACK, outline="")
                    round_rect(self, xs[i] + 6, y - 4,
                               xs[i] + 6 + max(3, bar_w * share), y + 4, 4,
                               fill=ACCENT_2 if r else ACCENT, outline="")
                    self.create_text(cx, y, text=str(val), anchor="e",
                                     fill=MUTED, font=f(9))
                else:
                    self.create_text(cx, y, text=str(val), anchor="e",
                                     fill=ui.C["text"] if i == 0 else MUTED,
                                     font=f(10, i == 0))


# ------------------------------------------------------------------ 明细表
class DataTable(tk.Frame):
    """可排序明细表：斑马纹、行悬停、表头点一下换排序、双击回调。"""

    def __init__(self, master, cols, height=10, on_double=None, style="Dash.Treeview",
                 ellipsis=()):
        super().__init__(master, bg=ui.C["card"])
        self.cols = cols          # [(key, label, width, anchor, stretch)]
        self._rows = []           # [{key: (display, sort_key), "_obj": obj}]
        self._sort = (None, False)
        self._on_double = on_double
        self._ellipsis = tuple(ellipsis)   # 这些列按列宽截断并补「…」
        self._last_w = 0
        self._hover = None

        self.tree = ttk.Treeview(self, columns=[c[0] for c in cols], show="headings",
                                 height=height, style=style)
        for key, label, width, anchor, stretch in cols:
            self.tree.heading(key, text=label, anchor=anchor,
                              command=lambda k=key: self.sort_by(k))
            self.tree.column(key, width=width, minwidth=44, anchor=anchor,
                             stretch=stretch)
        sb = ttk.Scrollbar(self, orient="vertical", command=self.tree.yview,
                           style="Dash.Vertical.TScrollbar")
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.tree.tag_configure("odd", background="#f7f9fd")
        self.tree.tag_configure("even", background="#ffffff")
        self.tree.tag_configure("hover", background="#eff4ff")
        self.tree.bind("<Double-1>", self._dbl)
        self.tree.bind("<Motion>", self._motion)
        self.tree.bind("<Leave>", lambda _e: self._paint_zebra())
        self.tree.bind("<Configure>", self._maybe_reflow)

    # ---------------------------------------------------------- 数据
    def set_rows(self, rows, keep_sort=True):
        self._rows = list(rows)
        self._render(keep_sort=keep_sort)

    def sort_by(self, key):
        """表头点一下：升序 ▲；再点一下：降序 ▼。"""
        cur, rev = self._sort
        self._sort = (key, not rev) if cur == key else (key, False)
        for k, label, *_ in self.cols:
            arrow = ""
            if k == self._sort[0]:
                arrow = " ▼" if self._sort[1] else " ▲"
            self.tree.heading(k, text=label + arrow)
        self._render(keep_sort=True)

    def _sorted(self):
        key, rev = self._sort
        if not key:
            return self._rows
        def sk(row):
            cell = row.get(key)
            v = cell[1] if isinstance(cell, tuple) else cell
            if v is None:
                return (1, 0)
            if isinstance(v, (int, float)):
                return (0, v)
            return (0, str(v))
        try:
            return sorted(self._rows, key=sk, reverse=rev)
        except TypeError:
            return self._rows

    def _render(self, keep_sort=True):
        rows = self._sorted() if keep_sort else self._rows
        self.tree.delete(*self.tree.get_children())
        widths = {}
        if self._ellipsis:
            # 标题列吃掉剩余宽度：先按控件实际宽度算，再截断（否则会被硬切）
            fixed = sum(w for _k, _l, w, _a, stretch in self.cols if not stretch)
            tree_w = self.tree.winfo_width()
            for key in self._ellipsis:
                if tree_w > 200:
                    avail = max(90, tree_w - fixed - 10)
                    self.tree.column(key, width=avail)
                else:
                    avail = int(self.tree.column(key, "width"))
                widths[key] = max(60, avail - 16)
        for i, row in enumerate(rows):
            vals = []
            for key, *_ in self.cols:
                cell = row.get(key, "")
                text = cell[0] if isinstance(cell, tuple) else cell
                text = _clean(text)
                if key in widths:
                    text = ellipsize(text, (ui.UI, 10), widths[key])
                vals.append(text)
            self.tree.insert("", "end", values=vals, tags=("odd" if i % 2 else "even",))
        self._hover = None

    def _maybe_reflow(self, event):
        """列宽随窗口变了就重排一次（标题那列要重新截断）。"""
        if abs(event.width - self._last_w) < 12:
            return
        self._last_w = event.width
        if self._ellipsis and self._rows:
            self._render(keep_sort=True)

    def _paint_zebra(self):
        for i, iid in enumerate(self.tree.get_children()):
            self.tree.item(iid, tags=("odd" if i % 2 else "even",))
        self._hover = None

    def _motion(self, event):
        iid = self.tree.identify_row(event.y)
        if iid == self._hover:
            return
        self._paint_zebra()
        if iid:
            self.tree.item(iid, tags=("hover",))
            self._hover = iid

    def _dbl(self, event):
        iid = self.tree.identify_row(event.y)
        if not iid or not self._on_double:
            return
        idx = self.tree.index(iid)
        rows = self._sorted()
        if idx < len(rows):
            self._on_double(rows[idx])

    def selected_obj(self):
        sel = self.tree.selection()
        if not sel:
            return None
        idx = self.tree.index(sel[0])
        rows = self._sorted()
        return rows[idx].get("_obj") if idx < len(rows) else None


# ------------------------------------------------------------------ 搜索框
class Search(tk.Frame):
    """带图标和占位提示的搜索框（过滤明细表用）。"""

    def __init__(self, master, placeholder="搜索…", on_change=None, width=190):
        super().__init__(master, bg=SOFT, highlightthickness=1,
                         highlightbackground=LINE)
        self.var = tk.StringVar()
        self._ph = placeholder
        self._on_change = on_change
        self._ph_on = True
        tk.Label(self, text="⌕", font=f(11), bg=SOFT, fg=FAINT).pack(
            side="left", padx=(8, 0))
        self.entry = tk.Entry(self, textvariable=self.var, width=1, relief="flat",
                              bd=0, highlightthickness=0, bg=SOFT,
                              fg=FAINT, insertbackground=ui.C["text"],
                              font=f(9), justify="left")
        self.entry.configure(width=max(6, width // 7))
        self.entry.pack(side="left", fill="x", expand=True, padx=(4, 8), pady=5)
        self.var.set(placeholder)
        self.entry.bind("<FocusIn>", self._focus_in)
        self.entry.bind("<FocusOut>", self._focus_out)
        self.var.trace_add("write", self._changed)

    def _focus_in(self, _e=None):
        if self._ph_on:
            self._ph_on = False
            self.var.set("")
            self.entry.configure(fg=ui.C["text"])

    def _focus_out(self, _e=None):
        if not self.var.get().strip():
            self._ph_on = True
            self.var.set(self._ph)
            self.entry.configure(fg=FAINT)

    def _changed(self, *_a):
        if self._on_change and not self._ph_on:
            self._on_change(self.var.get().strip())

    def get(self):
        return "" if self._ph_on else self.var.get().strip()


# ------------------------------------------------------------------ 通用小件
def section(parent, title, hint="", right=None, pady=(0, 10)):
    """卡片小标题行：标题 + 灰字说明（右侧可放控件）。返回标题行 Frame。"""
    head = tk.Frame(parent, bg=ui.C["card"])
    head.pack(fill="x", pady=pady)
    tk.Label(head, text=title, font=f(11, True), bg=ui.C["card"],
             fg=ui.C["text"]).pack(side="left")
    lbl = None
    if hint:
        lbl = tk.Label(head, text=hint, font=f(9), bg=ui.C["card"], fg=FAINT,
                       anchor="w")
        lbl.pack(side="left", padx=(8, 0))
    if right is not None:
        right(head)
    head.hint = lbl
    return head


def row_of(parent, gap=GAP, uniform=True):
    """一行等宽卡片容器。"""
    row = tk.Frame(parent, bg=ui.C["bg"])
    row.pack(fill="x")
    return row


def _clean(text):
    """表格单元格里不能有换行（Treeview 会把行撑开），一律压成空格。"""
    return " ".join(str(text if text is not None else "").split())


def ellipsize(text, font, width):
    """按像素宽截断并补「…」（Treeview 自己不会省略号，只会硬切）。"""
    text = str(text or "")
    if width <= 0 or not text:
        return text
    if measure(text, font) <= width:
        return text
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if measure(text[:mid] + "…", font) <= width:
            lo = mid
        else:
            hi = mid - 1
    return text[:lo] + "…"


def _nice_max(v):
    """纵轴上限取整成好看的数（1/2/2.5/5 × 10^n）。"""
    try:
        v = float(v)
    except (TypeError, ValueError):
        return 1
    if v <= 4:
        return 4
    mag = 10 ** (len(str(int(v))) - 1)
    for k in (1, 2, 2.5, 5, 10):
        if v <= mag * k:
            return mag * k
    return v


def _fmt_short(v):
    """轴上数字：1,234 / 1.2 万。"""
    try:
        v = float(v)
    except (TypeError, ValueError):
        return "-"
    if abs(v) >= 10000:
        return f"{v / 10000:.1f}万".replace(".0万", "万")
    if abs(v) >= 1000:
        return f"{int(round(v)):,}"
    return f"{v:.0f}"
