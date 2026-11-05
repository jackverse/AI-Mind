# -*- coding: utf-8 -*-
"""账单页：绑定的账户（支付宝/微信/银行卡）+ 每日收支 + 分类 + 明细。

支付宝：后台「账务组合查询」导出 .xls.zip，直接选文件导入；
账户按文件头里的支付宝账号自动归属，多账户互不干扰。
"""
import os
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

import ui
from core import bill as bl
from core import bill_sync as bs

WINDOW_DAYS = 30

COLS = [
    ("date", "日期", 92),
    ("account", "账户", 132),
    ("direction", "收支", 44),
    ("amount", "金额", 80),
    ("merchant", "商户 / 商品", 208),
    ("category", "分类", 52),
    ("biz", "账务类型", 72),
]


class BillsPage(tk.Frame):
    def __init__(self, master, ctx, app):
        super().__init__(master, bg=ui.C["bg"])
        self.ctx, self.app = ctx, app
        self.account_id = None          # None = 全部账户
        self.stats = None
        self._build_header()
        self.body = tk.Frame(self, bg=ui.C["bg"])
        self.body.pack(fill="both", expand=True)

    # ------------------------------------------------------------ 顶部
    def _build_header(self):
        bar = tk.Frame(self, bg=ui.C["bg"])
        bar.pack(fill="x", padx=20, pady=(16, 4))

        right = tk.Frame(bar, bg=ui.C["bg"])
        right.pack(side="right", pady=(2, 0))
        self.combo = ttk.Combobox(right, state="readonly", width=22, font=ui.F["small"])
        self.combo.pack(side="left", padx=(0, 6))
        self.combo.bind("<<ComboboxSelected>>", self._on_pick)
        ttk.Button(right, text="账户", width=6,
                   command=self.manage_accounts).pack(side="left", padx=3)
        ttk.Button(right, text="导入账单", width=9,
                   command=self.import_files).pack(side="left", padx=3)
        self.sync_btn = ttk.Button(right, text="同步个人账单", width=11,
                                   style="Accent.TButton",
                                   command=self.sync_personal_now)
        self.sync_btn.pack(side="left", padx=3)

        left = tk.Frame(bar, bg=ui.C["bg"])
        left.pack(side="left", fill="x", expand=True)
        tk.Label(left, text="账单", font=(ui.UI, 17, "bold"), bg=ui.C["bg"],
                 fg=ui.C["text"]).pack(side="left")
        self.sub_lbl = tk.Label(left, text="", font=ui.F["small"], bg=ui.C["bg"],
                                fg=ui.C["muted"], anchor="w")
        self.sub_lbl.pack(side="left", padx=8, pady=(6, 0))

        self.status = tk.Label(self, text="", font=ui.F["small"], bg=ui.C["bg"],
                               fg=ui.C["accent"], anchor="w")
        self.status.pack(fill="x", padx=20)

    def _set_status(self, text, color=None):
        try:
            self.status.configure(text=text, fg=color or ui.C["accent"])
        except tk.TclError:
            pass

    # ------------------------------------------------------------ 账户
    def _sync_combo(self):
        accounts = bl.load_accounts()
        labels, mapping = ["全部账户"], [None]
        for a in accounts:
            labels.append(a.get("name") or a["id"])
            mapping.append(a["id"])
        self._map = mapping
        self.combo["values"] = labels
        idx = mapping.index(self.account_id) if self.account_id in mapping else 0
        self.combo.current(idx)

    def _on_pick(self, _e=None):
        idx = self.combo.current()
        if 0 <= idx < len(self._map):
            self.account_id = self._map[idx]
        self.refresh()

    def manage_accounts(self):
        win = tk.Toplevel(self)
        win.title("账单账户")
        win.configure(bg=ui.C["bg"])
        win.transient(self.winfo_toplevel())
        win.geometry("560x380")
        pad = tk.Frame(win, bg=ui.C["bg"])
        pad.pack(fill="both", expand=True, padx=18, pady=14)
        tk.Label(pad, text="已绑定账户", font=ui.F["h3"], bg=ui.C["bg"],
                 fg=ui.C["text"]).pack(anchor="w")
        tk.Label(pad, text="支付宝：导入「账务组合查询」导出包时自动按账号绑定；"
                           "微信/银行卡随后接。",
                 font=ui.F["small"], bg=ui.C["bg"], fg=ui.C["muted"]).pack(
                     anchor="w", pady=(2, 8))

        box = tk.Text(pad, height=10, font=ui.F["small"], wrap="word",
                      relief="solid", bd=1, bg="#f7f9fc", fg=ui.C["text"])
        box.pack(fill="both", expand=True)
        box.configure(state="disabled")

        def fill():
            box.configure(state="normal")
            box.delete("1.0", "end")
            accs = bl.load_accounts()
            if not accs:
                box.insert("end", "（还没有账户，点「导入账单」选一个支付宝导出包）")
            for a in accs:
                box.insert("end", f"· {a.get('name') or '未命名'}  "
                                  f"[{bl.PLATFORM_LABEL.get(a.get('platform'), a.get('platform'))}]  "
                                  f"{a.get('id')}\n")
            box.configure(state="disabled")

        fill()

        def remove():
            accs = bl.load_accounts()
            if not accs:
                return
            names = [f"{a.get('name')}（{a['id']}）" for a in accs]
            idx = _ask_index(win, names)
            if idx is None:
                return
            bl.remove_account(accs[idx]["id"])
            fill()
            self.refresh()

        bar = tk.Frame(pad, bg=ui.C["bg"])
        bar.pack(fill="x", pady=(10, 0))
        ttk.Button(bar, text="删除账户…", command=remove).pack(side="left")
        ttk.Button(bar, text="关闭", command=win.destroy).pack(side="right")

    # ------------------------------------------------------------ 同步支付宝
    def sync_personal_now(self):
        self._set_status("正在同步个人账单；如果弹出登录/安全校验页，请扫码授权…")

        def work():
            try:
                from core import bill_personal as bp
                return {"data": bp.sync_personal(days=31)}
            except Exception as e:                     # noqa: BLE001
                return {"error": str(e)}

        def done(r):
            self._set_status("")
            self.refresh()
            if r.get("error"):
                messagebox.showerror("同步失败", r["error"], parent=self)
            else:
                d = r.get("data") or {}
                messagebox.showinfo(
                    "同步完成",
                    f"抓到 {d.get('rows', 0)} 条，新增 {d.get('added', 0)}，"
                    f"更新 {d.get('updated', 0)}（共 {d.get('total', 0)} 条）",
                    parent=self)

        self._bg(work, done)

    def scan_downloads_now(self):
        self._set_status("正在扫描 Downloads 里的新账单…")

        def work():
            try:
                return {"items": bs.scan_downloads()}
            except Exception as e:                     # noqa: BLE001
                return {"error": str(e)}

        def done(r):
            self._set_status("")
            self.refresh()
            if r.get("error"):
                messagebox.showerror("扫描失败", r["error"], parent=self)
                return
            items = r.get("items") or []
            if not items:
                messagebox.showinfo(
                    "没有新账单",
                    "Downloads 里没找到新的账单文件。\n\n"
                    "在支付宝「我的账单」页点一次「电子对账单/导出」，"
                    "文件落到 Downloads 后 5 分钟内会自动入库。", parent=self)
            else:
                messagebox.showinfo(
                    "已导入",
                    "\n".join(f"· {i['account'].get('name')}："
                              f"新增 {i['added']} 笔，更新 {i['updated']} 笔"
                              for i in items), parent=self)

        self._bg(work, done)

    def _bg(self, work, done):
        q = queue.Queue()
        threading.Thread(target=lambda: q.put(work()), daemon=True).start()

        def poll():
            try:
                result = q.get_nowait()
            except queue.Empty:
                self.after(150, poll)
                return
            done(result)

        self.after(150, poll)

    def sync_alipay_now(self):
        try:
            self.sync_btn.state(["disabled"])
        except tk.TclError:
            pass
        self._set_status("正在同步支付宝：检查登录态…（如果弹出支付宝页面，请扫码登录）")

        def work():
            try:
                if not bs.is_logged_in_safe():
                    return {"login": True,
                            "data": bs.login_and_sync(days=180)}
                return {"login": False, "data": bs.sync_alipay(days=180)}
            except Exception as e:                     # noqa: BLE001
                return {"error": str(e)}

        def done(r):
            try:
                self.sync_btn.state(["!disabled"])
            except tk.TclError:
                pass
            self._set_status("")
            self.refresh()
            if r.get("error"):
                messagebox.showerror("同步失败", r["error"], parent=self)
                return
            accs = (r.get("data") or {}).get("accounts") or []
            msg = "\n".join(
                f"· {a['account'].get('name')}：新增 {a['added']} 笔，更新 {a['updated']} 笔"
                for a in accs)
            messagebox.showinfo("同步完成", msg or "没有新增", parent=self)

        self._bg(work, done)

    # ------------------------------------------------------------ 导入
    def import_files(self):
        paths = filedialog.askopenfilenames(
            parent=self, title="选择账单导出文件（支付宝 .xls.zip / .xls）",
            filetypes=[("账单文件", "*.zip *.xls *.xml"), ("全部文件", "*.*")])
        if not paths:
            return
        lines, ok = [], 0
        for p in paths:
            try:
                info = bl.import_file(p)
            except bl.PasswordRequired:
                pwd = simpledialog.askstring(
                    "压缩包密码",
                    f"{os.path.basename(p)} 有密码（微信账单），\n"
                    "输入微信里给的解压密码：", parent=self)
                if not pwd:
                    lines.append(f"✗ {os.path.basename(p)}\n    跳过（需要密码）")
                    continue
                try:
                    info = bl.import_file(p, password=pwd)
                except Exception as e:                 # noqa: BLE001
                    lines.append(f"✗ {os.path.basename(p)}\n    {e}")
                    continue
            except Exception as e:                     # noqa: BLE001
                lines.append(f"✗ {os.path.basename(p)}\n    {e}")
                continue
            ok += 1
            lines.append(f"✓ {os.path.basename(p)}\n"
                         f"    {info['account'].get('name')}："
                         f"新增 {info['added']} 笔，更新 {info['updated']} 笔")
        self.refresh()
        messagebox.showinfo("导入结果" if ok else "导入失败",
                            "\n\n".join(lines), parent=self)

    # ------------------------------------------------------------ 刷新
    def on_show(self, **kw):
        self.refresh()

    def refresh(self):
        self._sync_combo()
        for w in self.body.winfo_children():
            w.destroy()

        stats = bl.summarize([self.account_id] if self.account_id else None,
                             days=WINDOW_DAYS)
        self.stats = stats
        if not stats["accounts"] or not stats["all_count"]:
            self._build_empty()
            self.sub_lbl.configure(text="还没有账单数据")
            return

        self.sub_lbl.configure(
            text=f"{len(stats['accounts'])} 个账户 · 近 {WINDOW_DAYS} 天支出 "
                 f"¥{bl.fmt_money(stats['expense'])}"
                 + (f" · 已排除 {stats['excluded_count']} 笔"
                    if stats.get("excluded_count") else ""))
        self._build_tiles(stats)
        self._build_mid(stats)
        self._build_table(stats)

    def _build_empty(self):
        card = self._card(self.body)
        card.pack(fill="both", expand=True, padx=20, pady=(6, 16))
        inner = tk.Frame(card, bg=ui.C["card"])
        inner.pack(fill="both", expand=True, padx=26, pady=22)
        tk.Label(inner, text="还没有账单", font=(ui.UI, 15, "bold"),
                 bg=ui.C["card"], fg=ui.C["text"]).pack(anchor="w")
        tk.Label(inner, text="支付宝后台 → 资金 → 账务明细 → 账务组合查询 → 导出",
                 font=ui.F["body"], bg=ui.C["card"], fg=ui.C["muted"],
                 anchor="w").pack(anchor="w", pady=(6, 4))
        tk.Label(inner,
                 text="点「同步个人账单」：需要授权时会在浏览器里弹登录/安全校验，扫码即可；\n"
                      "工具自己提交查询、读表格、按账号去重入库，不点界面按钮。\n"
                      "也可以把后台导出的账单文件用「导入账单」导入（自动按账号归属）。",
                 font=ui.F["small"], bg=ui.C["card"], fg=ui.C["muted"],
                 justify="left", anchor="w").pack(anchor="w", pady=(0, 14))
        btns = tk.Frame(inner, bg=ui.C["card"])
        btns.pack(anchor="w")
        ttk.Button(btns, text="同步个人账单", style="Accent.TButton",
                   command=self.sync_personal_now).pack(side="left", padx=(0, 8))
        ttk.Button(btns, text="导入账单", command=self.import_files).pack(side="left")

    def _build_tiles(self, s):
        row = tk.Frame(self.body, bg=ui.C["bg"])
        row.pack(fill="x", padx=20, pady=(2, 0))
        tiles = [
            ("本月支出", f"¥{bl.fmt_money(s['month_expense'])}"),
            (f"近 {WINDOW_DAYS} 天支出", f"¥{bl.fmt_money(s['expense'])}"),
            (f"近 {WINDOW_DAYS} 天收入", f"¥{bl.fmt_money(s['income'])}"),
            (f"笔数（{s['window'][0][5:]}~{s['window'][1][5:]}）", f"{s['count']} 笔"),
        ]
        for i, (label, value) in enumerate(tiles):
            row.columnconfigure(i, weight=1, uniform="t")
            box = tk.Frame(row, bg=ui.C["card"], highlightthickness=1,
                           highlightbackground=ui.C["line"])
            box.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else 8, 0))
            wrap = tk.Frame(box, bg=ui.C["card"])
            wrap.pack(padx=12, pady=9, anchor="w")
            tk.Label(wrap, text=value, font=(ui.UI, 15, "bold"), bg=ui.C["card"],
                     fg=ui.C["text"], anchor="w").pack(anchor="w")
            tk.Label(wrap, text=label, font=(ui.UI, 8), bg=ui.C["card"],
                     fg=ui.C["muted"], anchor="w").pack(anchor="w")

    def _build_mid(self, s):
        mid = tk.Frame(self.body, bg=ui.C["bg"])
        mid.pack(fill="x", padx=20, pady=(10, 0))
        mid.columnconfigure(0, weight=5)
        mid.columnconfigure(1, weight=3)

        c1 = self._card(mid)
        c1.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        head = tk.Frame(c1, bg=ui.C["card"])
        head.pack(fill="x", padx=14, pady=(8, 0))
        tk.Label(head, text="每日支出", font=ui.F["h4"], bg=ui.C["card"],
                 fg=ui.C["text"]).pack(side="left")
        tk.Label(head, text=f"日均 ¥{bl.fmt_money(s['avg_day'])}",
                 font=ui.F["small"], bg=ui.C["card"], fg=ui.C["muted"]).pack(side="right")
        cv = tk.Canvas(c1, height=130, bg=ui.C["card"], highlightthickness=0)
        cv.pack(fill="x", padx=6, pady=(2, 6))
        cv.bind("<Configure>", lambda _e, c=cv: self._draw_daily(c, s))

        c2 = self._card(mid)
        c2.grid(row=0, column=1, sticky="nsew")
        tk.Label(c2, text="分类", font=ui.F["h4"], bg=ui.C["card"],
                 fg=ui.C["text"]).pack(anchor="w", padx=14, pady=(8, 2))
        cv2 = tk.Canvas(c2, height=130, bg=ui.C["card"], highlightthickness=0)
        cv2.pack(fill="both", expand=True, padx=6, pady=(0, 6))
        cv2.bind("<Configure>", lambda _e, c=cv2: self._draw_cats(c, s))

    def _build_table(self, s):
        card = self._card(self.body)
        card.pack(fill="both", expand=True, padx=20, pady=(10, 14))
        head = tk.Frame(card, bg=ui.C["card"])
        head.pack(fill="x", padx=14, pady=(8, 2))
        tk.Label(head, text="明细", font=ui.F["h4"], bg=ui.C["card"],
                 fg=ui.C["text"]).pack(side="left")
        tk.Label(head, text="双击改分类 / 备注 / 不计入统计（可恢复）· 只统计近 %d 天" % WINDOW_DAYS,
                 font=ui.F["small"], bg=ui.C["card"], fg=ui.C["muted"]).pack(side="right")

        wrap = tk.Frame(card, bg=ui.C["card"])
        wrap.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        tree = ttk.Treeview(wrap, columns=[c[0] for c in COLS], show="headings",
                            height=8)
        for key, label, width in COLS:
            tree.heading(key, text=label)
            tree.column(key, width=width, minwidth=40,
                        anchor="w" if key in ("date", "account", "merchant", "category", "biz")
                        else "e",
                        stretch=(key == "merchant"))
        tree.tag_configure("excluded", foreground="#9aa4b2")
        sb = ttk.Scrollbar(wrap, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=sb.set)
        tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        tree.bind("<Double-1>", self.edit_txn)
        self.tree = tree

        for t in s["txns"]:
            merchant = t.get("counterparty_name") or t.get("item") or t.get("counterparty") or "-"
            excluded = bool(t.get("excluded"))
            values = [
                t.get("date", "")[5:],
                t.get("account_name", ""),
                "支出" if t["direction"] == "expense" else "收入",
                ("-" if t["direction"] == "expense" else "+") + bl.fmt_money(t["amount"]),
                merchant[:46],
                t.get("category", ""),
                "不计入" if excluded else t.get("biz_type", ""),
            ]
            tree.insert("", "end", values=values,
                        tags=("excluded",) if excluded else ())

    # ------------------------------------------------------------ 备注 / 排除
    def edit_txn(self, _e=None):
        sel = self.tree.selection()
        if not sel:
            return
        idx = self.tree.index(sel[0])
        if idx >= len(self.stats["txns"]):
            return
        t = self.stats["txns"][idx]

        win = tk.Toplevel(self)
        win.title("账单备注")
        win.configure(bg=ui.C["bg"])
        win.transient(self.winfo_toplevel())
        win.resizable(False, False)

        pad = tk.Frame(win, bg=ui.C["bg"])
        pad.pack(padx=18, pady=14)
        rows = [
            ("时间", t.get("time") or t.get("date") or ""),
            ("账户", t.get("account_name") or ""),
            ("收支", ("支出 " if t["direction"] == "expense" else "收入 ")
                     + "¥" + bl.fmt_money(t["amount"])),
            ("对方", t.get("counterparty_name") or ""),
            ("商品", t.get("item") or ""),
            ("原始备注", t.get("note") or ""),
        ]
        for i, (k, v) in enumerate(rows):
            tk.Label(pad, text=k, font=ui.F["small"], bg=ui.C["bg"],
                     fg=ui.C["muted"], anchor="w").grid(row=i, column=0, sticky="w", pady=2)
            tk.Label(pad, text=str(v), font=ui.F["body"], bg=ui.C["bg"],
                     fg=ui.C["text"], anchor="w", wraplength=360,
                     justify="left").grid(row=i, column=1, sticky="w", padx=(12, 0), pady=2)

        tk.Label(pad, text="分类", font=ui.F["small"], bg=ui.C["bg"],
                 fg=ui.C["muted"], anchor="w").grid(row=len(rows), column=0,
                                                    sticky="w", pady=(10, 2))
        var_cat = tk.StringVar(value=t.get("user_category") or "自动（按规则）")
        ttk.Combobox(pad, textvariable=var_cat,
                     values=["自动（按规则）"] + bl.CATEGORIES,
                     state="readonly", width=14).grid(
                         row=len(rows), column=1, sticky="w", padx=(12, 0), pady=(10, 2))

        tk.Label(pad, text="我的备注", font=ui.F["small"], bg=ui.C["bg"],
                 fg=ui.C["muted"], anchor="w").grid(row=len(rows) + 1, column=0,
                                                    sticky="nw", pady=(6, 2))
        box = tk.Text(pad, width=42, height=4, font=ui.F["body"], wrap="word",
                      relief="solid", bd=1)
        box.grid(row=len(rows) + 1, column=1, sticky="w", padx=(12, 0), pady=(6, 2))
        box.insert("1.0", t.get("user_note") or "")

        var_ex = tk.BooleanVar(value=bool(t.get("excluded")))
        tk.Checkbutton(pad, text="不计入统计（不删数据，随时可取消）",
                       variable=var_ex, font=ui.F["small"], bg=ui.C["bg"],
                       activebackground=ui.C["bg"], anchor="w").grid(
                           row=len(rows) + 2, column=0, columnspan=2,
                           sticky="w", pady=(8, 2))

        def save():
            note = box.get("1.0", "end").strip()
            cat = var_cat.get()
            if cat == "自动（按规则）":
                cat = ""
            bl.update_txn(t["account_id"], t["trade_no"],
                          user_note=note, excluded=bool(var_ex.get()),
                          user_category=cat)
            win.destroy()
            self.refresh()

        bar = tk.Frame(pad, bg=ui.C["bg"])
        bar.grid(row=len(rows) + 3, column=0, columnspan=2, sticky="e", pady=(10, 0))
        ttk.Button(bar, text="保存", style="Accent.TButton",
                   command=save).pack(side="left", padx=(0, 6))
        ttk.Button(bar, text="取消", command=win.destroy).pack(side="left")

    # ------------------------------------------------------------ 绘图
    @staticmethod
    def _card(parent):
        return tk.Frame(parent, bg=ui.C["card"], highlightthickness=1,
                        highlightbackground=ui.C["line"])

    def _draw_daily(self, cv, s):
        cv.delete("all")
        days = s["days"]
        w, h = cv.winfo_width(), cv.winfo_height()
        if w < 80 or h < 60:
            return
        pad_l, pad_r, pad_t, pad_b = 40, 8, 10, 20
        plot_w = max(1, w - pad_l - pad_r)
        plot_h = max(1, h - pad_t - pad_b)
        vmax = max([d["expense"] for d in days] + [1])
        n = len(days)
        bw = max(2, plot_w / n * 0.62)
        for i, d in enumerate(days):
            x = pad_l + plot_w * i / max(1, n)
            bh = plot_h * d["expense"] / vmax
            cv.create_rectangle(x, pad_t + plot_h - bh, x + bw,
                                pad_t + plot_h, fill=ui.C["accent"], outline="")
        cv.create_line(pad_l, pad_t + plot_h, w - pad_r, pad_t + plot_h,
                       fill=ui.C["line"])
        for i in range(3):
            y = pad_t + plot_h * i / 2
            cv.create_line(pad_l, y, w - pad_r, y, fill=ui.C["line"])
            cv.create_text(pad_l - 4, y, text=f"{vmax * (2 - i) / 2:.0f}",
                           anchor="e", font=(ui.UI, 7), fill=ui.C["muted"])
        for i in (0, n // 2, n - 1):
            if 0 <= i < n:
                x = pad_l + plot_w * i / max(1, n) + bw / 2
                cv.create_text(x, h - 8, text=days[i]["date"][5:],
                               font=(ui.UI, 7), fill=ui.C["muted"])

    def _draw_cats(self, cv, s):
        cv.delete("all")
        w, h = cv.winfo_width(), cv.winfo_height()
        if w < 80 or h < 40:
            return
        cats = s["categories"][:6]
        if not cats:
            cv.create_text(w // 2, h // 2, text="还没有支出", fill=ui.C["muted"],
                           font=ui.F["small"])
            return
        total = sum(v for _, v in cats) or 1
        row_h = min(22, (h - 8) / len(cats))
        label_w, value_w = 44, 62
        bar_w = max(20, w - label_w - value_w - 8)
        for i, (name, v) in enumerate(cats):
            y = 4 + i * row_h
            cy = y + row_h / 2 - 2
            cv.create_text(2, cy, text=name, anchor="w", font=(ui.UI, 8),
                           fill=ui.C["text"])
            cv.create_rectangle(label_w, y + 3, label_w + bar_w, y + row_h - 5,
                                fill="#eef2f8", outline="")
            cv.create_rectangle(label_w, y + 3,
                                label_w + max(2, bar_w * v / total),
                                y + row_h - 5, fill=ui.C["accent"], outline="")
            cv.create_text(w - 4, cy, text=bl.fmt_money(v), anchor="e",
                           font=(ui.UI, 8), fill=ui.C["text"])


def _ask_index(parent, names):
    """让用户输入序号（1-based），返回 0-based 索引或 None。"""
    from tkinter import simpledialog
    text = "\n".join(f"{i + 1}. {n}" for i, n in enumerate(names))
    pick = simpledialog.askstring("选择账户", "输入序号：\n" + text, parent=parent)
    try:
        idx = int(pick) - 1
    except (TypeError, ValueError):
        return None
    return idx if 0 <= idx < len(names) else None


def make(master, ctx, app):
    return BillsPage(master, ctx, app)
