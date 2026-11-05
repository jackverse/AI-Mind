# -*- coding: utf-8 -*-
"""买房页：组合贷月供测算 + 多套房源清单（看 N 套、比价、跟进度）。

数据只有一份：`data/hub/house/house.json`（进 git，两台机器 pull 后共享）。
本页读写它，不做第二套录入；房源链接点开就是系统浏览器。
"""
import tkinter as tk
import webbrowser
from datetime import date
from tkinter import messagebox, ttk

import ui
from core import house as hs
from core import privacy

COLS = [
    ("name", "小区 / 室号", 200, "w"),
    ("area", "地段", 92, "w"),
    ("layout", "户型", 64, "w"),
    ("size", "面积㎡", 60, "e"),
    ("floor", "楼层", 52, "w"),
    ("price", "总价", 78, "e"),
    ("unit", "单价/㎡", 74, "e"),
    ("down", "首付", 72, "e"),
    ("monthly", "月供", 66, "e"),
    ("status", "状态", 46, "w"),
    ("updated", "更新", 58, "w"),
]

STATUS_COLOR = {
    "关注": "#1c2333",
    "约看": "#b26a00",
    "已看": "#3d6ee0",
    "出价": "#1f9d55",
    "放弃": "#9aa4b2",
    "成交": "#1f9d55",
}

CLOSED = ("放弃", "成交")


def _brief_plan(st):
    """指标卡上的短方案名：取「商贷30年」或「100 万 / 20 年」。"""
    name = (st or {}).get("name") or ""
    if "+" in name:
        return name.split("+")[-1].strip()
    return name.split("·")[-1].strip()


def _wan(v):
    return hs.fmt_wan(v) if v else "—"


class HousePage(tk.Frame):
    def __init__(self, master, ctx, app):
        super().__init__(master, bg=ui.C["bg"])
        self.ctx, self.app = ctx, app
        self.data = hs.load()
        self.status_filter = "全部"
        self.sort_key = "updated"
        self.sort_rev = True
        self.view_rows = []
        self._build()
        self.refresh()

    # ------------------------------------------------------------------ 外壳
    def _build(self):
        bar = tk.Frame(self, bg=ui.C["bg"])
        bar.pack(fill="x", padx=22, pady=(16, 2))

        right = tk.Frame(bar, bg=ui.C["bg"])
        right.pack(side="right", pady=(2, 0))
        ttk.Button(right, text="贷款参数", width=10,
                   command=self.edit_loan).pack(side="left", padx=3)
        ttk.Button(right, text="＋ 新增房源", width=11, style="Accent.TButton",
                   command=lambda: self.edit_property(None)).pack(side="left", padx=3)

        left = tk.Frame(bar, bg=ui.C["bg"])
        left.pack(side="left", fill="x", expand=True)
        tk.Label(left, text="买房", font=(ui.UI, 17, "bold"), bg=ui.C["bg"],
                 fg=ui.C["text"]).pack(side="left")
        self.sub_lbl = tk.Label(left, text="", font=ui.F["small"], bg=ui.C["bg"],
                                fg=ui.C["muted"], anchor="w")
        self.sub_lbl.pack(side="left", padx=10, pady=(5, 0))

        self.status = tk.Label(self, text="", font=ui.F["small"], bg=ui.C["bg"],
                               fg=ui.C["muted"], anchor="w")
        self.status.pack(fill="x", padx=22)

        self.body = tk.Frame(self, bg=ui.C["bg"])
        self.body.pack(fill="both", expand=True, padx=22, pady=(6, 14))

    def _set_status(self, text, color=None):
        try:
            self.status.configure(text=text, fg=color or ui.C["muted"])
        except tk.TclError:
            pass

    # ------------------------------------------------------------------ 刷新
    def on_show(self, **kw):
        self.refresh()

    def refresh(self):
        self.data = hs.load()
        for w in self.body.winfo_children():
            w.destroy()
        prof = self.data.get("profile") or {}
        props = self.data.get("properties") or []
        plans = hs.all_plans(prof)

        plan = hs.find_plan(prof)
        st = hs.plan_stats(prof, plan) if plan else None
        fund = prof.get("fund") or {}
        if st:
            self.sub_lbl.configure(
                text="%s · %s · %s　｜　%s"
                     % (prof.get("city", ""), prof.get("district", ""),
                        prof.get("property_type", ""), hs.plan_desc(st)))
        else:
            self.sub_lbl.configure(text="还没设贷款方案，点右上角「贷款参数」")
        self._set_status("数据：data/hub/house/house.json　｜　最后保存 %s"
                         % self.data.get("updated", "—"))

        self._build_tiles(prof, props, plans)
        self._build_plans(plans, prof.get("loan_note", ""))
        self._build_table(prof, props)

    # ------------------------------------------------------------------ 指标卡
    def _build_tiles(self, prof, props, plans):
        row = tk.Frame(self.body, bg=ui.C["bg"])
        row.pack(fill="x", pady=(8, 0))
        counts = hs.status_counts(props)
        live = sum(1 for p in props if p.get("status") not in CLOSED)
        hint = " · ".join("%s %d" % (k, counts[k]) for k in hs.STATUSES if counts.get(k))
        fund = prof.get("fund") or {}
        st = plans[0] if plans else None
        cheap = min(plans, key=lambda p: p["monthly"]) if plans else None
        lowest = min(plans, key=lambda p: p["interest"]) if plans else None
        live_desc = " + ".join(hs.fmt_wan(l["amount"])
                               for l in (st["active"] if st else []))
        hide = privacy.enabled()
        bal = "¥••••" if hide else "¥" + hs.fmt_money(fund.get("provident_balance"))
        supp = ("¥••••" if hide
                else "¥" + hs.fmt_money(fund.get("supplementary_balance")))
        tiles = [
            (str(live), "在跟房源（套）", hint or "点右上角新增第一套", ui.C["accent"]),
            (bal, "公积金余额", "补充 " + supp, ui.C["text"]),
            (hs.fmt_wan(st["amount"]) if st else "—", "可贷总额",
             live_desc or "点「贷款参数」设置", ui.C["text"]),
            (("%.2f" % cheap["monthly"]) if cheap else "—", "最低月供",
             _brief_plan(cheap) if cheap else "—", ui.C["accent"]),
            (hs.fmt_wan(lowest["interest"], 2) if lowest else "—", "利息最省",
             _brief_plan(lowest) if lowest else "—", ui.C["text"]),
        ]
        for i, (value, label, sub, color) in enumerate(tiles):
            row.columnconfigure(i, weight=1, uniform="t")
            box = tk.Frame(row, bg=ui.C["card"], highlightthickness=1,
                           highlightbackground=ui.C["line"])
            box.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else 9, 0))
            inner = tk.Frame(box, bg=ui.C["card"])
            inner.pack(fill="x", padx=13, pady=9)
            tk.Label(inner, text=value, font=(ui.UI, 15, "bold"), bg=ui.C["card"],
                     fg=color, anchor="w").pack(anchor="w")
            tk.Label(inner, text=label, font=(ui.UI, 9), bg=ui.C["card"],
                     fg=ui.C["text"], anchor="w").pack(anchor="w")
            tk.Label(inner, text=sub, font=(ui.UI, 8), bg=ui.C["card"],
                     fg=ui.C["muted"], anchor="w", wraplength=150,
                     justify="left").pack(anchor="w", pady=(2, 0))

    # ------------------------------------------------------------------ 方案表
    def _build_plans(self, plans, loan_note=""):
        if not plans:
            return
        card = tk.Frame(self.body, bg=ui.C["card"], highlightthickness=1,
                        highlightbackground=ui.C["line"])
        card.pack(fill="x", pady=(10, 0))

        head = tk.Frame(card, bg=ui.C["card"])
        head.pack(fill="x", padx=14, pady=(8, 2))
        tk.Label(head, text="贷款方案", font=(ui.UI, 11, "bold"), bg=ui.C["card"],
                 fg=ui.C["text"]).pack(side="left")
        tk.Label(head, text="%d 个方案　｜　等额本息，公积金/商贷分开算" % len(plans),
                 font=ui.F["small"], bg=ui.C["card"],
                 fg=ui.C["muted"]).pack(side="left", padx=8)
        tk.Label(head, text="改额度/利率点右上「贷款参数」", font=(ui.UI, 8),
                 bg=ui.C["card"], fg=ui.C["muted"]).pack(side="right")

        cols = [
            ("name", "方案", 160, "w"),
            ("gjj", "公积金", 124, "w"),
            ("sy", "商贷", 124, "w"),
            ("monthly", "月供", 76, "e"),
            ("interest", "利息总额", 76, "e"),
            ("payoff", "公积金还完后", 100, "w"),
            ("condition", "前提", 152, "w"),
            ("quote", "截图", 46, "e"),
        ]
        tree = ttk.Treeview(card, columns=[c[0] for c in cols], show="headings",
                            height=min(len(plans), 6), style="Dash.Treeview")
        for key, label, width, anchor in cols:
            tree.heading(key, text=label, anchor=anchor)
            tree.column(key, width=width, minwidth=40, anchor=anchor,
                        stretch=(key == "name"))
        tree.tag_configure("default", foreground=ui.C["accent"])
        for st in plans:
            gjj, sy = st["loans"][0], st["loans"][1]

            def part(l):
                return ("—" if l["amount"] <= 0
                        else "%s / %d 年" % (hs.fmt_wan(l["amount"]), l["years"]))

            payoff = ("%s/月" % hs.fmt_money(st["after_monthly"])
                      if st["after_monthly"] else "—")
            quote = "一致" if st.get("quote_ok") else ("—" if not st["quote"] else "差异")
            tree.insert("", "end", values=[
                st.get("short") or st["name"], part(gjj), part(sy),
                "%.2f" % st["monthly"], hs.fmt_wan(st["interest"], 2), payoff,
                st.get("condition") or "—", quote,
            ], tags=("default",) if st["key"] == plans[0]["key"] else ())
        tree.pack(fill="x", padx=10, pady=(0, 6))
        if loan_note:
            tk.Label(card, text=loan_note, font=(ui.UI, 8), bg=ui.C["card"],
                     fg=ui.C["muted"], anchor="w", wraplength=880,
                     justify="left").pack(fill="x", padx=12, pady=(0, 8))

    # ------------------------------------------------------------------ 房源表
    def _build_table(self, prof, props):
        self.tree = None
        card = tk.Frame(self.body, bg=ui.C["card"], highlightthickness=1,
                        highlightbackground=ui.C["line"])
        card.pack(fill="both", expand=True, pady=(10, 0))

        head = tk.Frame(card, bg=ui.C["card"])
        head.pack(fill="x", padx=14, pady=(9, 4))
        tk.Label(head, text="房源", font=(ui.UI, 11, "bold"), bg=ui.C["card"],
                 fg=ui.C["text"]).pack(side="left")
        self.count_lbl = tk.Label(head, text="", font=ui.F["small"],
                                  bg=ui.C["card"], fg=ui.C["muted"])
        self.count_lbl.pack(side="left", padx=8)

        right = tk.Frame(head, bg=ui.C["card"])
        right.pack(side="right")
        self.filter_var = tk.StringVar(value=self.status_filter)
        combo = ttk.Combobox(right, textvariable=self.filter_var, state="readonly",
                             width=8, font=ui.F["small"],
                             values=["全部"] + hs.STATUSES)
        combo.pack(side="left", padx=(0, 8))
        combo.bind("<<ComboboxSelected>>", self._on_filter)
        ttk.Button(right, text="详情", width=6,
                   command=self._open_selected).pack(side="left", padx=2)
        ttk.Button(right, text="编辑", width=6,
                   command=self._edit_selected).pack(side="left", padx=2)
        ttk.Button(right, text="删除", width=6,
                   command=self._delete_selected).pack(side="left", padx=2)

        if not props:
            self._build_empty(card)
            return

        wrap = tk.Frame(card, bg=ui.C["card"])
        wrap.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        tree = ttk.Treeview(wrap, columns=[c[0] for c in COLS], show="headings",
                            height=10, style="Dash.Treeview")
        for key, label, width, anchor in COLS:
            tree.heading(key, text=label, anchor=anchor,
                         command=lambda k=key: self._on_head(k))
            tree.column(key, width=width, minwidth=40, anchor=anchor,
                        stretch=(key == "name"))
        for status, color in STATUS_COLOR.items():
            tree.tag_configure(status, foreground=color)
        sb = ttk.Scrollbar(wrap, orient="vertical", command=tree.yview,
                           style="Dash.Vertical.TScrollbar")
        tree.configure(yscrollcommand=sb.set)
        tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        tree.bind("<Double-1>", lambda _e: self._open_selected())
        self.tree = tree

        self.view_rows = []
        for p in props:
            a = hs.afford(prof, p)
            self.view_rows.append({
                "id": p["id"],
                "updated": p.get("updated") or "",
                "name": hs.display_name(p),
                "area": hs.location(p) or "—",
                "layout": p.get("layout") or "—",
                "size": hs._num(p.get("area_sqm")),
                "floor": p.get("floor") or "—",
                "price": hs._num(p.get("price")),
                "unit": a["unit_price"],
                "down": a["down"],
                "monthly": a["monthly"],
                "status": p.get("status") or "关注",
            })
        self._fill_table()

    def _build_empty(self, card):
        inner = tk.Frame(card, bg=ui.C["card"])
        inner.pack(fill="both", expand=True, padx=20, pady=14)
        tk.Label(inner, text="还没有房源，先加第一套", font=(ui.UI, 14, "bold"),
                 bg=ui.C["card"], fg=ui.C["text"]).pack(anchor="w")
        tk.Label(inner,
                 text="把「小区 + 室号 + 挂牌价 + 链接」发我，或点下面自己录：",
                 font=ui.F["body"], bg=ui.C["card"], fg=ui.C["muted"],
                 justify="left", anchor="w").pack(anchor="w", pady=(4, 10))
        ttk.Button(inner, text="＋ 新增房源", style="Accent.TButton",
                   command=lambda: self.edit_property(None)).pack(anchor="w")
        tk.Label(inner,
                 text="字段：地段 / 小区 / 室号 / 户型 / 面积 / 楼层 / 总价 / 首付 / 链接 / 状态；"
                      "改价自动记价格记录",
                 font=ui.F["small"], bg=ui.C["card"], fg=ui.C["muted"],
                 justify="left", anchor="w").pack(anchor="w", pady=(10, 0))

    def _on_filter(self, _e=None):
        self.status_filter = self.filter_var.get()
        self._fill_table()

    def _on_head(self, key):
        if self.sort_key == key:
            self.sort_rev = not self.sort_rev
        else:
            self.sort_key, self.sort_rev = key, True
        self._fill_table()

    def _fill_table(self):
        tree = getattr(self, "tree", None)
        if tree is None:
            return
        rows = [r for r in self.view_rows
                if self.status_filter == "全部" or r["status"] == self.status_filter]
        numeric = {"size", "price", "unit", "down", "monthly"}
        if self.sort_key in numeric:
            rows.sort(key=lambda r: r.get(self.sort_key) or 0, reverse=self.sort_rev)
        else:
            rows.sort(key=lambda r: str(r.get(self.sort_key) or ""),
                      reverse=self.sort_rev)

        tree.delete(*tree.get_children())
        for r in rows:
            values = [
                r["name"], r["area"], r["layout"],
                ("%g" % r["size"]) if r["size"] else "—",
                r["floor"], _wan(r["price"]),
                hs.fmt_unit(r["unit"]) if r["unit"] else "—",
                _wan(r["down"]),
                ("%.0f" % r["monthly"]) if r["monthly"] else "—",
                r["status"], (r["updated"] or "")[5:],
            ]
            tree.insert("", "end", iid=r["id"], values=values,
                        tags=(r["status"],))
        for key, label, _w, anchor in COLS:
            mark = ""
            if key == self.sort_key:
                mark = " ▼" if self.sort_rev else " ▲"
            tree.heading(key, text=label + mark, anchor=anchor)
        total = len(self.view_rows)
        self.count_lbl.configure(
            text="%d 套%s" % (len(rows), "" if self.status_filter == "全部"
                              else " / 共 %d 套" % total))

    def _selected_id(self):
        tree = getattr(self, "tree", None)
        if tree is None:
            return None
        sel = tree.selection()
        return sel[0] if sel else None

    # ------------------------------------------------------------------ 操作
    def _edit_selected(self):
        pid = self._selected_id()
        if pid:
            self.edit_property(pid)

    def _open_selected(self):
        pid = self._selected_id()
        if pid:
            self.detail(pid)

    def _delete_selected(self):
        pid = self._selected_id()
        if not pid:
            return
        p = hs.get(self.data, pid)
        if p is None:
            return
        if not messagebox.askyesno(
                "删除房源", "确定删除「%s」？\n价格记录和跟进也会一起删掉，不能恢复。"
                % hs.display_name(p), parent=self):
            return
        hs.remove(self.data, pid)
        self.refresh()
        self._set_status("已删除 1 套房源")

    # ------------------------------------------------------------------ 房源详情
    def detail(self, pid):
        p = hs.get(self.data, pid)
        if p is None:
            return
        a = hs.afford(self.data.get("profile"), p)
        win = tk.Toplevel(self)
        win.title(hs.display_name(p))
        win.configure(bg=ui.C["bg"])
        win.transient(self.winfo_toplevel())
        win.geometry("720x720")

        pad = tk.Frame(win, bg=ui.C["bg"])
        pad.pack(fill="both", expand=True, padx=20, pady=14)

        tk.Label(pad, text=hs.display_name(p), font=(ui.UI, 16, "bold"),
                 bg=ui.C["bg"], fg=ui.C["text"], anchor="w").pack(fill="x")
        sub = " · ".join(x for x in (hs.location(p), p.get("layout"),
                                     ("%g ㎡" % hs._num(p.get("area_sqm"))
                                      if p.get("area_sqm") else ""),
                                     p.get("floor"), p.get("status")) if x)
        tk.Label(pad, text=sub, font=ui.F["small"], bg=ui.C["bg"],
                 fg=ui.C["muted"], anchor="w").pack(fill="x", pady=(0, 8))

        info = tk.Frame(pad, bg=ui.C["card"], highlightthickness=1,
                        highlightbackground=ui.C["line"])
        info.pack(fill="x")
        grid = tk.Frame(info, bg=ui.C["card"])
        grid.pack(fill="x", padx=14, pady=10)
        pairs = [
            ("总价", hs.fmt_wan(a["price"]) if a["price"] else "—"),
            ("单价", "%s 元/㎡" % hs.fmt_unit(a["unit_price"]) if a["unit_price"] else "—"),
            ("首付", "%s（%d%%）" % (_wan(a["down"]), round(a["down_ratio"] * 100))),
            ("贷款", hs.fmt_wan(a["loan"]) + ("（超上限，已按可贷额算）" if a["over_cap"] else "")),
            ("月供", "%.2f 元" % a["monthly"] if a["monthly"] else "—"),
            ("交易费用", "%s（契税 %s · 中介 %s · 其他 %s）"
             % (_wan(a["fee_total"]), _wan((p.get("fees") or {}).get("tax")),
                _wan((p.get("fees") or {}).get("agency")),
                _wan((p.get("fees") or {}).get("other")))),
            ("到手现金", _wan(a["cash"])),
            ("房龄", ("%g 年" % hs._num(p.get("age_years"))) if p.get("age_years") else "—"),
            ("朝向 / 装修", " / ".join(x for x in (p.get("orientation"),
                                                  p.get("decoration")) if x) or "—"),
            ("电梯", "有" if p.get("elevator") else "无"),
            ("评分", ("★" * p.get("rating", 0)) or "—"),
            ("标签", " · ".join(p.get("tags") or []) or "—"),
        ]
        for i, (k, v) in enumerate(pairs):
            r, c = divmod(i, 3)
            cell = tk.Frame(grid, bg=ui.C["card"])
            cell.grid(row=r, column=c, sticky="w", padx=(0, 18), pady=2)
            tk.Label(cell, text=k, font=(ui.UI, 8), bg=ui.C["card"],
                     fg=ui.C["muted"]).pack(anchor="w")
            tk.Label(cell, text=v, font=ui.F["body"], bg=ui.C["card"],
                     fg=ui.C["text"]).pack(anchor="w")

        # 链接
        link_box = tk.Frame(pad, bg=ui.C["bg"])
        link_box.pack(fill="x", pady=(10, 0))
        tk.Label(link_box, text="链接", font=(ui.UI, 10, "bold"), bg=ui.C["bg"],
                 fg=ui.C["text"]).pack(side="left", padx=(0, 8))
        links = p.get("links") or []
        if not links:
            tk.Label(link_box, text="还没有链接（点下方「编辑」加）",
                     font=ui.F["small"], bg=ui.C["bg"],
                     fg=ui.C["muted"]).pack(side="left")
        for link in links:
            ttk.Button(link_box, text="打开 " + (link.get("title") or "链接"),
                       command=lambda u=link["url"]: webbrowser.open(u)).pack(
                           side="left", padx=(0, 6))

        # 价格记录 + 跟进
        mid = tk.Frame(pad, bg=ui.C["bg"])
        mid.pack(fill="x", pady=(10, 0))
        mid.columnconfigure(0, weight=1, uniform="m")
        mid.columnconfigure(1, weight=1, uniform="m")

        hist = tk.Frame(mid, bg=ui.C["card"], highlightthickness=1,
                        highlightbackground=ui.C["line"])
        hist.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        tk.Label(hist, text="价格记录", font=(ui.UI, 9, "bold"), bg=ui.C["card"],
                 fg=ui.C["text"]).pack(anchor="w", padx=12, pady=(8, 2))
        hlist = tk.Text(hist, width=28, height=5, font=ui.F["small"], relief="flat",
                        bg=ui.C["card"], fg=ui.C["text"], wrap="word")
        hlist.pack(fill="both", expand=True, padx=10, pady=(0, 8))
        rows = p.get("price_history") or []
        hlist.insert("end", "\n".join(
            "%s  %s  %s" % (h.get("date", "")[5:], hs.fmt_wan(h.get("price")),
                            h.get("note", "")) for h in reversed(rows)) or "（暂无）")
        hlist.configure(state="disabled")

        note_box = tk.Frame(mid, bg=ui.C["card"], highlightthickness=1,
                            highlightbackground=ui.C["line"])
        note_box.grid(row=0, column=1, sticky="nsew")
        tk.Label(note_box, text="跟进记录", font=(ui.UI, 9, "bold"), bg=ui.C["card"],
                 fg=ui.C["text"]).pack(anchor="w", padx=12, pady=(8, 2))
        lst = tk.Listbox(note_box, width=18, height=4, font=ui.F["small"],
                         relief="flat", bg=ui.C["card"], fg=ui.C["text"],
                         activestyle="none")
        lst.pack(fill="both", expand=True, padx=10)
        for v in reversed(p.get("visits") or []):
            lst.insert("end", "%s  %s" % (v.get("date", "")[5:], v.get("note", "")))
        add = tk.Frame(note_box, bg=ui.C["card"])
        add.pack(fill="x", padx=10, pady=(4, 8))
        entry = tk.Entry(add, font=ui.F["small"], relief="solid", bd=1)
        entry.pack(side="left", fill="x", expand=True)
        tk.Label(pad, text="备注：" + (p.get("note") or "—"), font=ui.F["small"],
                 bg=ui.C["bg"], fg=ui.C["muted"], anchor="w",
                 wraplength=660, justify="left").pack(fill="x", pady=(8, 0))

        def add_visit():
            text = entry.get().strip()
            if not text:
                return
            hs.add_visit(self.data, pid, text)
            win.destroy()
            self.refresh()
            self._set_status("已加一条跟进：" + text[:24])

        ttk.Button(add, text="加一条", width=7, command=add_visit).pack(
            side="left", padx=(6, 0))
        entry.bind("<Return>", lambda _e: add_visit())

        bottom = tk.Frame(pad, bg=ui.C["bg"])
        bottom.pack(fill="x", pady=(10, 0))
        ttk.Button(bottom, text="编辑", style="Accent.TButton",
                   command=lambda: (win.destroy(), self.edit_property(pid))).pack(
                       side="left")
        if p.get("url"):
            ttk.Button(bottom, text="打开主链接",
                       command=lambda: webbrowser.open(p["url"])).pack(
                           side="left", padx=8)
        ttk.Button(bottom, text="关闭", command=win.destroy).pack(side="right")

    # ------------------------------------------------------------------ 新增 / 编辑
    def edit_property(self, pid=None):
        p = hs.get(self.data, pid) if pid else None
        prof = self.data.get("profile") or {}
        win = tk.Toplevel(self)
        win.title("编辑房源" if p else "新增房源")
        win.configure(bg=ui.C["bg"])
        win.transient(self.winfo_toplevel())
        win.resizable(False, False)

        pad = tk.Frame(win, bg=ui.C["bg"])
        pad.pack(padx=18, pady=14)
        grid = tk.Frame(pad, bg=ui.C["bg"])
        grid.pack(fill="x")

        def var(v):
            return tk.StringVar(value="" if v is None else str(v))

        def wan(v):
            return "" if not v else ("%g" % (hs._num(v) / 10000.0))

        fees = (p or {}).get("fees") or {}
        fields = {
            "community": var((p or {}).get("community")),
            "area_name": var((p or {}).get("area_name")),
            "district": var((p or {}).get("district") or prof.get("district")),
            "building": var((p or {}).get("building")),
            "unit": var((p or {}).get("unit")),
            "floor": var((p or {}).get("floor")),
            "layout": var((p or {}).get("layout")),
            "area_sqm": var((p or {}).get("area_sqm") or ""),
            "age_years": var((p or {}).get("age_years") or ""),
            "price": var(wan((p or {}).get("price"))),
            "down": var(wan((p or {}).get("down_payment"))),
            "tax": var(wan(fees.get("tax"))),
            "agency": var(wan(fees.get("agency"))),
            "other": var(wan(fees.get("other"))),
            "orientation": var((p or {}).get("orientation")),
            "decoration": var((p or {}).get("decoration")),
            "tags": var("、".join((p or {}).get("tags") or [])),
        }
        layout = [
            ("小区", "community", 18), ("板块 / 地段", "area_name", 18),
            ("区", "district", 18),
            ("楼栋", "building", 18), ("室号", "unit", 18), ("楼层（如 5/6）", "floor", 18),
            ("户型", "layout", 18), ("面积（㎡）", "area_sqm", 18),
            ("房龄（年）", "age_years", 18),
            ("总价（万）", "price", 18), ("首付（万，可空）", "down", 16),
            ("单价", None, 18),
            ("契税（万）", "tax", 18), ("中介费（万）", "agency", 18),
            ("其他费用（万）", "other", 18),
            ("朝向", "orientation", 18), ("装修", "decoration", 18),
            ("标签（、分隔）", "tags", 18),
        ]
        for i, (label, key, width) in enumerate(layout):
            r, c = divmod(i, 3)
            tk.Label(grid, text=label, font=ui.F["small"], bg=ui.C["bg"],
                     fg=ui.C["muted"], anchor="w").grid(
                         row=r * 2, column=c, sticky="w", padx=(0, 10), pady=(6, 0))
            if key is None:
                lbl = tk.Label(grid, text="", font=ui.F["small"], bg=ui.C["bg"],
                               fg=ui.C["muted"], anchor="w")
                lbl.grid(row=r * 2 + 1, column=c, sticky="w", padx=(0, 10))
                self._unit_lbl = lbl
                continue
            tk.Entry(grid, textvariable=fields[key], width=width,
                     font=ui.F["body"], relief="solid", bd=1).grid(
                         row=r * 2 + 1, column=c, sticky="w", padx=(0, 10))

        extra = tk.Frame(pad, bg=ui.C["bg"])
        extra.pack(fill="x", pady=(8, 0))
        status_var = tk.StringVar(value=(p or {}).get("status") or "关注")
        rating_var = tk.StringVar(value=str((p or {}).get("rating") or 0))
        elevator_var = tk.BooleanVar(value=bool((p or {}).get("elevator")))

        def _box(label):
            box = tk.Frame(extra, bg=ui.C["bg"])
            box.pack(side="left", padx=(0, 16))
            tk.Label(box, text=label, font=ui.F["small"], bg=ui.C["bg"],
                     fg=ui.C["muted"]).pack(anchor="w")
            return box

        ttk.Combobox(_box("状态"), textvariable=status_var, width=8,
                     state="readonly", values=hs.STATUSES).pack(anchor="w")
        tk.Spinbox(_box("评分（0-5）"), from_=0, to=5, width=5,
                   textvariable=rating_var).pack(anchor="w")
        tk.Checkbutton(_box("电梯"), variable=elevator_var, text="有",
                       bg=ui.C["bg"], activebackground=ui.C["bg"]).pack(anchor="w")

        tk.Label(pad, text="链接（每行一条，可写「名称|网址」，也可以只写网址）",
                 font=ui.F["small"], bg=ui.C["bg"], fg=ui.C["muted"],
                 anchor="w").pack(fill="x", pady=(10, 2))
        links_box = tk.Text(pad, height=3, font=ui.F["small"], relief="solid",
                            bd=1, wrap="word")
        links_box.pack(fill="x")
        links_box.insert("end", "\n".join(
            "%s|%s" % (l.get("title", ""), l.get("url", ""))
            if l.get("title") and l.get("title") != hs._url_title(l.get("url", ""))
            else l.get("url", "") for l in (p or {}).get("links") or []))

        tk.Label(pad, text="备注", font=ui.F["small"], bg=ui.C["bg"],
                 fg=ui.C["muted"], anchor="w").pack(fill="x", pady=(8, 2))
        note_box = tk.Text(pad, height=3, font=ui.F["small"], relief="solid",
                           bd=1, wrap="word")
        note_box.pack(fill="x")
        note_box.insert("end", (p or {}).get("note") or "")

        def num(var_, name, scale=1.0, allow_empty=True):
            text = var_.get().strip().replace(",", "")
            if not text:
                if allow_empty:
                    return 0.0
                raise ValueError("%s 不能空" % name)
            try:
                return float(text) * scale
            except ValueError:
                raise ValueError("%s 要填数字（单位：%s）"
                                 % (name, "万" if scale == 10000 else ""))

        def save():
            try:
                community = fields["community"].get().strip()
                if not community:
                    raise ValueError("小区不能空")
                price = num(fields["price"], "总价", 10000)
                if price <= 0:
                    raise ValueError("总价要大于 0")
                down_text = fields["down"].get().strip()
                down = num(fields["down"], "首付", 10000) if down_text else None
                if down is not None and down > price:
                    raise ValueError("首付不能大于总价")
                data = {
                    "community": community,
                    "area_name": fields["area_name"].get().strip(),
                    "district": fields["district"].get().strip(),
                    "building": fields["building"].get().strip(),
                    "unit": fields["unit"].get().strip(),
                    "floor": fields["floor"].get().strip(),
                    "layout": fields["layout"].get().strip(),
                    "area_sqm": num(fields["area_sqm"], "面积"),
                    "age_years": num(fields["age_years"], "房龄"),
                    "price": price,
                    "down_payment": down,
                    "fees": {
                        "tax": num(fields["tax"], "契税", 10000),
                        "agency": num(fields["agency"], "中介费", 10000),
                        "other": num(fields["other"], "其他费用", 10000),
                    },
                    "status": status_var.get() or "关注",
                    "rating": int(hs._num(rating_var.get())),
                    "elevator": bool(elevator_var.get()),
                    "orientation": fields["orientation"].get().strip(),
                    "decoration": fields["decoration"].get().strip(),
                    "tags": [t.strip() for t in fields["tags"].get()
                             .replace(",", "、").split("、") if t.strip()],
                    "links": self._parse_links(links_box.get("1.0", "end")),
                    "note": note_box.get("1.0", "end").strip(),
                }
            except ValueError as e:
                messagebox.showerror("填写有误", str(e), parent=win)
                return
            data["url"] = data["links"][0]["url"] if data["links"] else ""
            if p is None:
                hs.add(self.data, data)
                msg = "已新增：" + hs.display_name(data)
            else:
                hs.update(self.data, pid, data)
                msg = "已保存：" + hs.display_name(data)
            win.destroy()
            self.refresh()
            self._set_status(msg)

        bar = tk.Frame(pad, bg=ui.C["bg"])
        bar.pack(fill="x", pady=(12, 0))
        ttk.Button(bar, text="保存", style="Accent.TButton",
                   command=save).pack(side="left")
        ttk.Button(bar, text="取消", command=win.destroy).pack(side="left", padx=8)

        def update_unit(*_e):
            try:
                price = num(fields["price"], "总价", 10000)
                area = num(fields["area_sqm"], "面积")
                text = ("≈ %s 元/㎡" % hs.fmt_unit(price / area)) if price and area else ""
            except ValueError:
                text = ""
            try:
                self._unit_lbl.configure(text=text)
            except tk.TclError:
                pass

        for key in ("price", "area_sqm"):
            fields[key].trace_add("write", update_unit)
        update_unit()
        win.grab_set()

    @staticmethod
    def _parse_links(text):
        out = []
        for line in (text or "").splitlines():
            line = line.strip()
            if not line:
                continue
            if "|" in line:
                title, url = line.split("|", 1)
                title, url = title.strip(), url.strip()
            else:
                title, url = "", line
            if not url.lower().startswith(("http://", "https://")):
                continue
            out.append({"url": url, "title": title or hs._url_title(url),
                        "added": date.today().isoformat()})
        return out

    # ------------------------------------------------------------------ 贷款参数
    def edit_loan(self):
        prof = self.data.get("profile") or {}
        fund = prof.get("fund") or {}
        plans = prof.get("plans") or []
        win = tk.Toplevel(self)
        win.title("贷款参数")
        win.configure(bg=ui.C["bg"])
        win.transient(self.winfo_toplevel())
        win.resizable(False, False)
        pad = tk.Frame(win, bg=ui.C["bg"])
        pad.pack(padx=18, pady=14)
        grid = tk.Frame(pad, bg=ui.C["bg"])
        grid.pack(fill="x")

        def w(v):
            return "%g" % (hs._num(v) / 10000.0)

        p1 = hs.plan_stats(prof, plans[0]) if plans else None
        p2 = hs.plan_stats(prof, plans[1]) if len(plans) > 1 else None
        p3 = hs.plan_stats(prof, plans[2]) if len(plans) > 2 else None

        def var(v):
            return tk.StringVar(value="" if v is None else str(v))

        fields = [
            ("区", var(prof.get("district")), 14),
            ("类型", var(prof.get("property_type")), 14),
            ("公积金余额（元）", var(fund.get("provident_balance")), 12),
            ("补充公积金余额（元）", var(fund.get("supplementary_balance")), 12),
            ("公积金利率（%）", var((fund.get("rates") or {}).get("provident")), 8),
            ("商贷利率（%）", var((fund.get("rates") or {}).get("commercial")), 8),
            ("公积金贷款（万）", var(w(p1["loans"][0]["amount"]) if p1 else ""), 10),
            ("公积金年限（年）", var(p1["loans"][0]["years"] if p1 else ""), 8),
            ("商贷贷款（万）", var(w(p1["loans"][1]["amount"]) if p1 else ""), 10),
            ("方案一 商贷年限", var(p1["loans"][1]["years"] if p1 else ""), 8),
            ("方案二 商贷年限", var(p2["loans"][1]["years"] if p2 else ""), 8),
            ("纯公积金贷款（万，0=不要）", var(w(p3["loans"][0]["amount"]) if p3 else "0"), 10),
            ("纯公积金年限（年）", var(p3["loans"][0]["years"] if p3 else "0"), 8),
        ]
        entries = []
        for i, (label, v, width) in enumerate(fields):
            r, c = divmod(i, 2)
            tk.Label(grid, text=label, font=ui.F["small"], bg=ui.C["bg"],
                     fg=ui.C["muted"], anchor="w").grid(
                         row=r * 2, column=c, sticky="w", padx=(0, 14), pady=(6, 0))
            entry = tk.Entry(grid, textvariable=v, width=width, font=ui.F["body"],
                             relief="solid", bd=1,
                             show="•" if privacy.enabled() and i in (2, 3) else "")
            entry.grid(row=r * 2 + 1, column=c, sticky="w", padx=(0, 14))
            entries.append(entry)

        if privacy.enabled():
            show_bal = tk.BooleanVar(value=False)

            def toggle_bal():
                for entry in entries[2:4]:
                    entry.configure(show="" if show_bal.get() else "•")

            tk.Checkbutton(pad, text="显示余额（隐私模式默认隐藏）",
                           variable=show_bal, command=toggle_bal,
                           font=ui.F["small"], bg=ui.C["bg"],
                           activebackground=ui.C["bg"], anchor="w").pack(
                               anchor="w", pady=(6, 0))

        def num(v, name):
            text = v.get().strip()
            if not text:
                raise ValueError("%s 不能空" % name)
            try:
                return float(text)
            except ValueError:
                raise ValueError("%s 要填数字" % name)

        def save():
            try:
                district = fields[0][1].get().strip()
                ptype = fields[1][1].get().strip()
                prov = num(fields[2][1], "公积金余额")
                supp = num(fields[3][1], "补充余额")
                r1 = num(fields[4][1], "公积金利率")
                r2 = num(fields[5][1], "商贷利率")
                g_amount = num(fields[6][1], "公积金贷款") * 10000
                g_years = int(num(fields[7][1], "公积金年限"))
                c_amount = num(fields[8][1], "商贷贷款") * 10000
                y1 = int(num(fields[9][1], "方案一商贷年限"))
                y2 = int(num(fields[10][1], "方案二商贷年限")) if len(plans) > 1 else 0
                p_amount = num(fields[11][1], "纯公积金贷款") * 10000
                p_years = int(num(fields[12][1], "纯公积金年限"))
            except ValueError as e:
                messagebox.showerror("填写有误", str(e), parent=win)
                return
            prof["district"] = district
            prof["property_type"] = ptype
            prof["fund"] = {
                "provident_balance": prov,
                "supplementary_balance": supp,
                "rates": {"provident": r1, "commercial": r2},
            }
            new_plans = [{
                "key": "combo%d" % y1,
                "name": "组合贷 · 公积金%d年 + 商贷%d年" % (g_years, y1),
                "provident": {"amount": g_amount, "years": g_years},
                "commercial": {"amount": c_amount, "years": y1},
            }]
            if len(plans) > 1:
                new_plans.append({
                    "key": "combo%d" % y2,
                    "name": "组合贷 · 公积金%d年 + 商贷%d年" % (g_years, y2),
                    "provident": {"amount": g_amount, "years": g_years},
                    "commercial": {"amount": c_amount, "years": y2},
                })
            if p_amount > 0 and p_years > 0:
                pure = {
                    "key": "gjj%d" % p_years,
                    "name": "纯公积金 · %g万%d年" % (p_amount / 10000.0, p_years),
                    "provident": {"amount": p_amount, "years": p_years},
                    "commercial": {"amount": 0, "years": 0},
                }
                old_cond = plans[2].get("condition") if len(plans) > 2 else ""
                if old_cond:
                    pure["condition"] = old_cond
                new_plans.append(pure)
            prof["plans"] = new_plans
            prof["default_plan"] = new_plans[0]["key"]
            hs.save(self.data)
            win.destroy()
            self.refresh()
            self._set_status("贷款参数已保存")

        bar = tk.Frame(pad, bg=ui.C["bg"])
        bar.pack(fill="x", pady=(12, 0))
        ttk.Button(bar, text="保存", style="Accent.TButton",
                   command=save).pack(side="left")
        ttk.Button(bar, text="取消", command=win.destroy).pack(side="left", padx=8)
        tk.Label(pad, text="改这里不会动房源；月供/首付会按新参数重算。",
                 font=ui.F["small"], bg=ui.C["bg"],
                 fg=ui.C["muted"]).pack(anchor="w", pady=(8, 0))
        win.grab_set()


def make(master, ctx, app):
    return HousePage(master, ctx, app)
