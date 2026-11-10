# -*- coding: utf-8 -*-
"""欧路词典页：多账号 + 学习情况（生词 / 语料 / 已掌握 / 连续天数）。

数据来自欧路官方 OpenAPI（只读），授权码按账号分开存（DPAPI 加密）；
官方**没有学习记录/复习接口**，所以「今日复习」用页面手动补，能从
daily-log.md 的英语列读到就预填。

布局按 940px 最小宽度设计；同步跑后台线程，进度显示在标题右侧。
"""

# 侧栏入口（hub 启动时自动扫这个 META，不用改 hub.py）
META = {"icon": '英', "title": '欧路', "sub": '生词/学习', "weight": 63}
import threading
import tkinter as tk
import webbrowser
from tkinter import messagebox, ttk

import ui
from core import eudic
from core import privacy as pv

AUTH_URL = eudic.AUTH_URL


def _acct_label(acct):
    """账号显示名：有备注名就按隐私规则打码，没有就给「账号 + 打码后的 ID」。"""
    name = (acct.get("name") or "").strip()
    if name:
        return pv.show_name(name)
    return "账号 " + pv.show_handle(acct.get("id") or "")


def _fmt(n):
    try:
        return f"{int(n):,}"
    except (TypeError, ValueError):
        return "-"


def _nice_max(v):
    """纵轴上限取整成好看的数（1/2/2.5/5 × 10^n）。"""
    if v <= 10:
        return max(4, int(v))
    mag = 10 ** (len(str(int(v))) - 1)
    for k in (1, 2, 2.5, 5, 10):
        if v <= mag * k:
            return int(mag * k)
    return int(v)


class EudicPage(tk.Frame):
    def __init__(self, master, ctx, app):
        super().__init__(master, bg=ui.C["bg"])
        self.ctx, self.app = ctx, app
        self.aid = None                 # None = 融合
        self.summary = None
        self.busy = False
        self._combo_map = []
        self._msg = ""
        self._result = None
        self._auto_tried = False
        self._build_header()
        self.body = tk.Frame(self, bg=ui.C["bg"])
        self.body.pack(fill="both", expand=True)

    # ------------------------------------------------------------ 顶部
    def _build_header(self):
        bar = tk.Frame(self, bg=ui.C["bg"])
        bar.pack(fill="x", padx=20, pady=(16, 4))
        tk.Label(bar, text="欧路", font=(ui.UI, 17, "bold"), bg=ui.C["bg"],
                 fg=ui.C["text"]).pack(side="left")
        self.sub_lbl = tk.Label(bar, text="", font=ui.F["small"], bg=ui.C["bg"],
                                fg=ui.C["muted"])
        self.sub_lbl.pack(side="left", padx=8, pady=(6, 0))

        right = tk.Frame(bar, bg=ui.C["bg"])
        right.pack(side="right", pady=(2, 0))

        self.combo = ttk.Combobox(right, state="readonly", width=18,
                                  font=ui.F["small"])
        self.combo.pack(side="left", padx=(0, 6))
        self.combo.bind("<<ComboboxSelected>>", self._on_pick)
        self.combo.bind("<Button-3>", self._combo_menu)

        ttk.Button(right, text="＋ 账号", width=7,
                   command=self.add_account).pack(side="left", padx=3)
        self.sync_btn = ttk.Button(right, text="同步", width=6,
                                   style="Accent.TButton", command=self.start_sync)
        self.sync_btn.pack(side="left", padx=3)
        ttk.Button(right, text="来源", width=6,
                   command=self.show_guide).pack(side="left", padx=3)

    # ------------------------------------------------------------ 账号
    def _sync_combo(self, accounts):
        labels, mapping = [], []
        if len(accounts) > 1:
            labels.append(f"全部账号（融合 {len(accounts)}）")
            mapping.append(None)
        for a in accounts:
            label = _acct_label(a)
            lang = eudic.LANGS.get(a.get("language") or "en", "")
            labels.append(label + (f" · {lang}" if lang and lang != "英语" else ""))
            mapping.append(a["id"])
        self._combo_map = mapping
        self.combo["values"] = labels
        if mapping:
            self.combo.current(max(0, self._current_index()))
        else:
            self.combo.set("")

    def _current_index(self):
        for i, aid in enumerate(self._combo_map):
            if aid == self.aid:
                return i
        return 0

    def _on_pick(self, _e=None):
        idx = self.combo.current()
        if 0 <= idx < len(self._combo_map):
            self.aid = self._combo_map[idx]
        self.refresh()

    def _combo_menu(self, event):
        if self.aid is None:
            return
        menu = tk.Menu(self, tearoff=0)
        menu.add_command(label="删除这个账号…",
                         command=lambda: self._remove_account(self.aid))
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _remove_account(self, aid):
        acct = next((a for a in eudic.load_accounts() if a["id"] == aid), None)
        if acct is None:
            return
        name = _acct_label(acct)
        if not messagebox.askyesno(
                "删除账号",
                f"删掉「{name}」的本地绑定和已同步数据？\n\n"
                "只影响 hub 本地；欧路云端生词本、学习记录不受影响。",
                parent=self):
            return
        eudic.remove_account(aid)
        self.aid = None
        self.refresh()

    def add_account(self):
        dlg = AccountDialog(self, self)
        self.wait_window(dlg)
        if dlg.result:
            self.aid = dlg.result["id"]
            self.refresh()
            self.start_sync()

    # ------------------------------------------------------------ 刷新
    def on_show(self, **kw):
        self.refresh()

    def refresh(self):
        accounts = eudic.load_accounts()
        ids = [a["id"] for a in accounts]
        if self.aid not in ids:
            self.aid = ids[0] if len(ids) == 1 else None
        self._sync_combo(accounts)

        targets = ids if self.aid is None else [self.aid]
        self.summary = eudic.summarize(targets) if ids else None
        s = self.summary

        for w in self.body.winfo_children():
            w.destroy()

        if not accounts:
            self._build_empty(False)
            self.sub_lbl.configure(text="未绑定账号")
        elif s is None or not s["has_data"]:
            self._build_empty(True)
            self.sub_lbl.configure(text="已绑定，等待首次同步")
        else:
            self._build_data(s)
            prefix = "融合 · " if (self.aid is None and len(accounts) > 1) else ""
            err = " · 有同步错误" if any(a.get("last_error") for a in s["accounts"]) else ""
            self.sub_lbl.configure(
                text=f"{prefix}{len(targets)} 个账号 · 最后同步 "
                     f"{s['last_sync'] or '从未'}{err}")

        if (accounts and s is not None and not s["has_data"]
                and not self.busy and not self._auto_tried
                and not any(a.get("last_error") for a in accounts)):
            self._auto_tried = True
            self.after(400, self.start_sync)

    # ------------------------------------------------------------ 空状态
    def _build_empty(self, has_accounts):
        card = self._card(self.body)
        card.pack(fill="both", expand=True, padx=20, pady=(6, 16))
        inner = tk.Frame(card, bg=ui.C["card"])
        inner.pack(fill="both", expand=True, padx=26, pady=22)

        tk.Label(inner,
                 text="账号已绑定，还没有同步" if has_accounts else "还没有绑定欧路账号",
                 font=(ui.UI, 15, "bold"), bg=ui.C["card"],
                 fg=ui.C["text"]).pack(anchor="w")
        tk.Label(
            inner,
            text="三步：生成授权码 → 绑定 → 同步。可绑多个账号，之后在下拉里切换或融合。",
            font=ui.F["body"], bg=ui.C["card"], fg=ui.C["muted"], anchor="w",
        ).pack(anchor="w", pady=(6, 16))

        steps = [
            ("① 生成授权码",
             "点下面的「打开授权页」→ 登录欧路账号 → 生成/复制授权码。\n"
             "一个欧路账号一份授权码；换账号时先退出或开无痕窗口。"),
            ("② 绑定",
             "点右上「＋ 账号」，粘贴授权码（也可点「从剪贴板粘贴」自动读），起个备注名。"),
            ("③ 同步",
             "点「同步」；首次全量约 1–3 分钟（接口限 30 次/分），之后按新增增量。"),
        ]
        for title, desc in steps:
            row = tk.Frame(inner, bg=ui.C["card"])
            row.pack(fill="x", pady=(0, 12))
            tk.Label(row, text=title, font=ui.F["h4"], bg=ui.C["card"],
                     fg=ui.C["text"], anchor="w").pack(anchor="w")
            tk.Label(row, text=desc, font=ui.F["small"], bg=ui.C["card"],
                     fg=ui.C["muted"], justify="left", anchor="w").pack(
                         anchor="w", pady=(2, 0))

        link = tk.Label(inner, text="打开欧路授权页 ↗", font=ui.F["small"],
                        bg=ui.C["card"], fg=ui.C["accent"], anchor="w",
                        cursor="hand2")
        link.pack(anchor="w", pady=(0, 2))
        link.bind("<Button-1>", lambda _e: webbrowser.open(AUTH_URL))
        tk.Label(inner,
                 text="授权码能读写你的生词本（可删词），按密码保管；"
                      "hub 用 Windows DPAPI 加密，只存本机。",
                 font=ui.F["small"], bg=ui.C["card"], fg=ui.C["muted"],
                 anchor="w").pack(anchor="w", pady=(6, 0))

        btns = tk.Frame(inner, bg=ui.C["card"])
        btns.pack(anchor="w", pady=(12, 0))
        if has_accounts:
            ttk.Button(btns, text="立即同步", style="Accent.TButton",
                       command=self.start_sync).pack(side="left", padx=(0, 8))
        ttk.Button(btns, text="＋ 绑定账号",
                   command=self.add_account).pack(side="left", padx=(0, 8))
        ttk.Button(btns, text="打开授权页",
                   command=lambda: webbrowser.open(AUTH_URL)).pack(side="left")

    # ------------------------------------------------------------ 有数据
    def _build_data(self, s):
        tiles = tk.Frame(self.body, bg=ui.C["bg"])
        tiles.pack(fill="x", padx=20, pady=(2, 0))
        cards = [
            ("生词（个）", _fmt(s["words_total"])),
            ("已掌握", _fmt(s["mastered_total"])),
            ("今日新增", _fmt(s["added_today"])),
            ("近 30 天新增", _fmt(s["added_30"])),
            ("连续学习（天）", _fmt(s["streak"])),
        ]
        for i, (label, value) in enumerate(cards):
            tiles.columnconfigure(i, weight=1, uniform="t")
            box = tk.Frame(tiles, bg=ui.C["card"], highlightthickness=1,
                           highlightbackground=ui.C["line"])
            box.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else 8, 0))
            wrap = tk.Frame(box, bg=ui.C["card"])
            wrap.pack(padx=10, pady=9, anchor="w")
            tk.Label(wrap, text=value, font=(ui.UI, 15, "bold"), bg=ui.C["card"],
                     fg=ui.C["text"], anchor="w").pack(anchor="w")
            tk.Label(wrap, text=label, font=(ui.UI, 8), bg=ui.C["card"],
                     fg=ui.C["muted"], anchor="w").pack(anchor="w")

        self._build_review_bar(s)

        mid = tk.Frame(self.body, bg=ui.C["bg"])
        mid.pack(fill="x", padx=20, pady=(8, 0))
        mid.columnconfigure(0, weight=5)
        mid.columnconfigure(1, weight=3)

        c1 = self._card(mid)
        c1.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        head = tk.Frame(c1, bg=ui.C["card"])
        head.pack(fill="x", padx=14, pady=(8, 0))
        tk.Label(head, text="近 30 天学习", font=ui.F["h4"], bg=ui.C["card"],
                 fg=ui.C["text"]).pack(side="left")
        tk.Label(head, text=f"今日语料 {s['vocab_today']}  ·  生词 {s['words_total']}",
                 font=ui.F["small"], bg=ui.C["card"],
                 fg=ui.C["muted"]).pack(side="right")
        cv = tk.Canvas(c1, height=150, bg=ui.C["card"], highlightthickness=0)
        cv.pack(fill="x", padx=6, pady=(2, 8))
        cv.bind("<Configure>", lambda _e, c=cv: self._draw_chart(c, s))

        c2 = self._card(mid)
        c2.grid(row=0, column=1, sticky="nsew")
        tk.Label(c2, text="生词本分类", font=ui.F["h4"], bg=ui.C["card"],
                 fg=ui.C["text"]).pack(anchor="w", padx=14, pady=(8, 0))
        wrap2 = tk.Frame(c2, bg=ui.C["card"])
        wrap2.pack(fill="both", expand=True, padx=10, pady=(2, 8))
        cols = ("name", "count", "today")
        tree = ttk.Treeview(wrap2, columns=cols, show="headings", height=5)
        for key, label, width in (("name", "分类", 120), ("count", "词数", 50),
                                  ("today", "今日", 44)):
            tree.heading(key, text=label)
            tree.column(key, width=width, minwidth=40,
                        anchor="w" if key == "name" else "e",
                        stretch=(key == "name"))
        sb = ttk.Scrollbar(wrap2, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=sb.set)
        tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        for c in s["cats"]:
            tree.insert("", "end", values=(c["name"], _fmt(c["count"]),
                                           _fmt(c["today"])))
        if not s["cats"]:
            tree.insert("", "end", values=("（空）", "-", "-"))

        bottom = self._card(self.body)
        bottom.pack(fill="both", expand=True, padx=20, pady=(8, 14))
        bhead = tk.Frame(bottom, bg=ui.C["card"])
        bhead.pack(fill="x", padx=14, pady=(8, 2))
        tk.Label(bhead, text="最近生词", font=ui.F["h4"], bg=ui.C["card"],
                 fg=ui.C["text"]).pack(side="left")
        tk.Label(bhead, text="双击看释义 / 语境", font=ui.F["small"],
                 bg=ui.C["card"], fg=ui.C["muted"]).pack(side="right")

        cols = [("date", "日期", 84), ("word", "单词", 120),
                ("exp", "释义", 300), ("star", "星级", 50),
                ("cat", "分类", 100)]
        if len(s["accounts"]) > 1:
            cols.insert(0, ("acct", "账号", 90))
        wrap3 = tk.Frame(bottom, bg=ui.C["card"])
        wrap3.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        tree2 = ttk.Treeview(wrap3, columns=[c[0] for c in cols],
                             show="headings", height=7)
        for key, label, width in cols:
            tree2.heading(key, text=label)
            tree2.column(key, width=width, minwidth=40,
                         anchor="w" if key in ("word", "exp", "cat", "acct", "date") else "e",
                         stretch=(key == "exp"))
        sb2 = ttk.Scrollbar(wrap3, orient="vertical", command=tree2.yview)
        tree2.configure(yscrollcommand=sb2.set)
        tree2.pack(side="left", fill="both", expand=True)
        sb2.pack(side="right", fill="y")
        tree2.bind("<Double-1>", self._show_detail)
        self.tree = tree2
        self.recent = s["recent"]

        for r in s["recent"][:200]:
            cat = "、".join((r.get("cats") or [r.get("cat") or ""])[:2])
            vals = [
                (r.get("d") or "")[5:],
                r.get("w") or "",
                (r.get("exp") or "")[:60],
                str(r.get("star") or "-"),
                cat[:18],
            ]
            if len(s["accounts"]) > 1:
                vals.insert(0, pv.show_name(r.get("_acct") or ""))
            tree2.insert("", "end", values=vals)

    def _build_review_bar(self, s):
        today = s["today"]
        manual = eudic.load_manual()
        saved = manual.get(today)
        log_val = eudic.review_from_log(self.ctx.root, today)

        wrap = tk.Frame(self.body, bg=ui.C["bg"])
        wrap.pack(fill="x", padx=20, pady=(8, 0))
        box = tk.Frame(wrap, bg=ui.C["card"], highlightthickness=1,
                       highlightbackground=ui.C["line"])
        box.pack(fill="x")
        inner = tk.Frame(box, bg=ui.C["card"])
        inner.pack(fill="x", padx=12, pady=7)

        tk.Label(inner, text="今日复习", font=ui.F["small"], bg=ui.C["card"],
                 fg=ui.C["text"]).pack(side="left")
        entry = tk.Entry(inner, width=6, font=ui.F["body"], relief="solid",
                         bd=1, justify="center")
        entry.pack(side="left", padx=(8, 4))
        if saved is not None:
            entry.insert(0, str(saved))
        elif log_val is not None:
            entry.insert(0, str(log_val))
        tk.Label(inner, text="个", font=ui.F["small"], bg=ui.C["card"],
                 fg=ui.C["muted"]).pack(side="left")

        def save():
            raw = entry.get().strip()
            try:
                n = int(raw or 0)
            except ValueError:
                messagebox.showwarning("格式不对", "复习数填整数，例如 30", parent=self)
                return
            eudic.set_manual(today, n)
            self.refresh()

        ttk.Button(inner, text="保存", width=5, command=save).pack(
            side="left", padx=(10, 8))

        if saved is not None:
            hint = "已保存到本地（官方 API 没有复习数据）"
        elif log_val is not None:
            hint = f"daily-log 里记了 {log_val}，保存后以这里为准"
        else:
            hint = "官方 API 不提供复习数，手动记一笔；也会从 daily-log 英语列预填"
        tk.Label(inner, text=hint, font=ui.F["small"], bg=ui.C["card"],
                 fg=ui.C["muted"]).pack(side="left")

    # ------------------------------------------------------------ 同步
    def start_sync(self):
        if self.busy:
            return
        accounts = eudic.load_accounts()
        if not accounts:
            self.add_account()
            return
        targets = [a["id"] for a in accounts] if self.aid is None else [self.aid]
        names = {a["id"]: _acct_label(a) for a in accounts}
        self.busy = True
        self._auto_tried = True
        self._result = None
        self._msg = "准备同步…"
        self.sync_btn.configure(state="disabled")
        self.sub_lbl.configure(text="准备同步…")
        self.after(150, self._tick)

        def work():
            out = []
            total = len(targets)
            for i, aid in enumerate(targets):
                try:
                    eudic.sync_account(
                        aid,
                        progress=lambda m, i=i: setattr(
                            self, "_msg", f"[{i + 1}/{total}] {m}"))
                    out.append((names.get(aid, aid), ""))
                except Exception as e:              # noqa: BLE001
                    out.append((names.get(aid, aid), str(e)))
            self._result = out

        threading.Thread(target=work, daemon=True).start()

    def _tick(self):
        if not self.busy:
            return
        if self._msg:
            names = [a.get("name") for a in eudic.load_accounts()]
            self.sub_lbl.configure(text=pv.show_text(self._msg, names))
        if self._result is not None:
            out, self._result = self._result, None
            self._finish(out)
            return
        self.after(200, self._tick)

    def _finish(self, out):
        self.busy = False
        try:
            self.sync_btn.configure(state="normal")
        except tk.TclError:
            pass
        errs = [f"{name}：{err}" for name, err in out if err]
        self.refresh()
        if errs:
            messagebox.showerror("同步失败", "\n\n".join(errs), parent=self)
        elif hasattr(self.app, "notify"):
            self.app.notify("欧路同步完成")

    # ------------------------------------------------------------ 绘图
    @staticmethod
    def _card(parent):
        return tk.Frame(parent, bg=ui.C["card"], highlightthickness=1,
                        highlightbackground=ui.C["line"])

    def _draw_chart(self, cv, s):
        cv.delete("all")
        days = s["days"]
        w, h = cv.winfo_width(), cv.winfo_height()
        if w < 80 or h < 60:
            return
        pad_l, pad_r, pad_t, pad_b = 36, 10, 22, 20
        plot_w = max(1, w - pad_l - pad_r)
        plot_h = max(1, h - pad_t - pad_b)
        peak = max([max(d["words"], d["vocab"]) for d in days] or [0])
        ymax = _nice_max(peak)

        for i in range(4):
            y = pad_t + plot_h * i / 3
            cv.create_line(pad_l, y, w - pad_r, y, fill=ui.C["line"])
            cv.create_text(pad_l - 4, y, text=str(int(ymax * (3 - i) / 3)),
                           anchor="e", font=(ui.UI, 7), fill=ui.C["muted"])

        n = len(days)
        slot = plot_w / max(1, n)
        bar_w = max(2, slot * 0.55)
        pts = []
        for i, d in enumerate(days):
            x = pad_l + slot * (i + 0.5)
            y = pad_t + plot_h * (1 - min(1.0, d["words"] / ymax))
            cv.create_rectangle(x - bar_w / 2, y, x + bar_w / 2,
                                pad_t + plot_h, fill=ui.C["accent"], outline="")
            vy = pad_t + plot_h * (1 - min(1.0, d["vocab"] / ymax))
            pts.append((x, vy))

        if n >= 2:
            cv.create_line(*[c for p in pts for c in p], fill="#e08a1e", width=2)
        for x, y in pts:
            cv.create_oval(x - 2, y - 2, x + 2, y + 2, fill="#e08a1e", outline="")

        step = max(1, (n - 1) // 5)
        for i in range(0, n, step):
            anchor = "w" if i == 0 else ("e" if i == n - 1 else "center")
            cv.create_text(pad_l + slot * (i + 0.5), h - 8,
                           text=days[i]["date"][5:], font=(ui.UI, 7),
                           fill=ui.C["muted"], anchor=anchor)

        cv.create_rectangle(6, 5, 13, 11, fill=ui.C["accent"], outline="")
        cv.create_text(16, 8, text="新增生词", anchor="w", font=(ui.UI, 7),
                       fill=ui.C["text"])
        cv.create_line(w - 92, 8, w - 80, 8, fill="#e08a1e", width=2)
        cv.create_text(w - 76, 8, text="查词语料", anchor="w", font=(ui.UI, 7),
                       fill=ui.C["text"])

    def _show_detail(self, _e=None):
        sel = self.tree.selection()
        if not sel:
            return
        idx = self.tree.index(sel[0])
        if idx >= len(self.recent):
            return
        r = self.recent[idx]
        rows = [
            ("单词", r.get("w") or "-"),
            ("释义", r.get("exp") or "-"),
            ("星级", str(r.get("star") or "-")),
            ("分类", "、".join(r.get("cats") or [r.get("cat") or "-"])),
            ("添加时间", (r.get("t") or "-").replace("T", " ").replace("Z", " UTC")),
            ("语境", r.get("ctx") or "-"),
            ("账号", pv.show_name(r.get("_acct") or "-")),
        ]
        top = tk.Toplevel(self)
        top.title("生词详情")
        top.configure(bg=ui.C["card"])
        top.transient(self.winfo_toplevel())
        top.resizable(False, False)
        box = tk.Frame(top, bg=ui.C["card"])
        box.pack(padx=20, pady=16)
        for i, (k, v) in enumerate(rows):
            tk.Label(box, text=k, font=ui.F["small"], bg=ui.C["card"],
                     fg=ui.C["muted"], anchor="w").grid(row=i, column=0,
                                                        sticky="w", pady=2)
            tk.Label(box, text=str(v), font=ui.F["body"], bg=ui.C["card"],
                     fg=ui.C["text"], anchor="w", wraplength=380,
                     justify="left").grid(row=i, column=1, sticky="w",
                                          padx=(14, 0), pady=2)
        ttk.Button(top, text="关闭", command=top.destroy).pack(pady=(0, 14))

    # ------------------------------------------------------------ 说明
    def show_guide(self):
        messagebox.showinfo(
            "欧路数据从哪来",
            "官方 OpenAPI（只读）：\n"
            "  /studylist/category  生词本分类\n"
            "  /studylist/words     生词本单词（add_time / star）\n"
            "  /studylist/mastered_words  已掌握\n"
            "  /studylist/vocab_entries   语料（查词/划词记录）\n\n"
            "授权：https://my.eudic.net/OpenAPI/Authorization\n"
            "一个欧路账号一份授权码；请求头 Authorization: NIS <码>。\n"
            "授权码能读写生词本，按密码保管；hub 用 DPAPI 加密存本机。\n\n"
            "能自动记：每日新增生词、查词语料、已掌握、连续天数。\n"
            "不能自动记：复习次数/正确率/学习时长——官方没有这个接口，\n"
            "所以在页面「今日复习」手动补，能读到 daily-log 英语列就预填。\n\n"
            "限流 30 次/分；单个生词本最多约 5,100 条；\n"
            "首次同步 1–3 分钟，之后只拉新增。\n\n"
            "定时：hub.exe --eudic-sync（无窗口）\n"
            "全量重建：hub.exe --eudic-sync --full\n"
            "删除账号：在顶部账号下拉上右键。",
            parent=self)


class AccountDialog(tk.Toplevel):
    def __init__(self, master, page):
        super().__init__(master)
        self.page = page
        self.result = None
        self.title("绑定欧路账号")
        self.configure(bg=ui.C["card"])
        self.transient(master.winfo_toplevel())
        self.resizable(False, False)
        self.grab_set()

        box = tk.Frame(self, bg=ui.C["card"])
        box.pack(padx=22, pady=18)

        tk.Label(box, text="绑定欧路账号", font=(ui.UI, 14, "bold"),
                 bg=ui.C["card"], fg=ui.C["text"]).pack(anchor="w")
        tk.Label(
            box,
            text="① 打开授权页并登录要绑定的欧路账号\n"
                 "② 生成/复制授权码\n"
                 "③ 粘贴到下面，保存后会先验证一次",
            font=ui.F["small"], bg=ui.C["card"], fg=ui.C["muted"],
            justify="left", anchor="w").pack(anchor="w", pady=(8, 12))

        row = tk.Frame(box, bg=ui.C["card"])
        row.pack(fill="x")
        tk.Label(row, text="授权码", font=ui.F["small"], bg=ui.C["card"],
                 fg=ui.C["muted"], width=6, anchor="w").pack(side="left")
        self.token_var = tk.StringVar()
        entry = tk.Entry(row, textvariable=self.token_var, width=48,
                         font=ui.F["small"], relief="solid", bd=1)
        entry.pack(side="left", padx=(4, 6))
        entry.focus_set()

        paste = tk.Frame(box, bg=ui.C["card"])
        paste.pack(fill="x", pady=(6, 0))
        ttk.Button(paste, text="从剪贴板粘贴",
                   command=self._paste).pack(side="left", padx=(52, 6))
        ttk.Button(paste, text="打开授权页",
                   command=lambda: webbrowser.open(AUTH_URL)).pack(side="left")

        row2 = tk.Frame(box, bg=ui.C["card"])
        row2.pack(fill="x", pady=(10, 0))
        tk.Label(row2, text="备注名", font=ui.F["small"], bg=ui.C["card"],
                 fg=ui.C["muted"], width=6, anchor="w").pack(side="left")
        self.name_var = tk.StringVar()
        tk.Entry(row2, textvariable=self.name_var, width=28,
                 font=ui.F["small"], relief="solid", bd=1).pack(
                     side="left", padx=(4, 6))
        tk.Label(row2, text="可留空（用账号 ID 区分）", font=ui.F["small"],
                 bg=ui.C["card"], fg=ui.C["muted"]).pack(side="left")

        self.status = tk.Label(box, text="", font=ui.F["small"],
                               bg=ui.C["card"], fg=ui.C["muted"], anchor="w")
        self.status.pack(fill="x", pady=(10, 0))

        btns = tk.Frame(box, bg=ui.C["card"])
        btns.pack(fill="x", pady=(12, 0))
        ttk.Button(btns, text="取消", command=self.destroy).pack(
            side="right", padx=(6, 0))
        self.ok = ttk.Button(btns, text="验证并绑定", style="Accent.TButton",
                             command=self._save)
        self.ok.pack(side="right")

        self.update_idletasks()
        x = page.winfo_rootx() + max(0, (page.winfo_width() - self.winfo_width()) // 2)
        y = page.winfo_rooty() + 80
        self.geometry(f"+{x}+{y}")

    def _paste(self):
        try:
            text = self.clipboard_get()
        except tk.TclError:
            self.status.configure(text="剪贴板是空的")
            return
        token = eudic.normalize_token(text)
        if not token:
            self.status.configure(text="剪贴板里没有可用文本")
            return
        self.token_var.set(token)
        self.status.configure(text=f"已读入 {len(token)} 个字符")

    def _save(self):
        token = eudic.normalize_token(self.token_var.get())
        if len(token) < 8:
            messagebox.showwarning("授权码太短", "粘贴完整的授权码（不是登录密码）。",
                                   parent=self)
            return
        self.ok.configure(state="disabled")
        self.status.configure(text="正在验证授权码…")
        self.configure(cursor="watch")
        self.update_idletasks()
        try:
            eudic.categories(token, "en")
        except eudic.EudicError as e:
            self.configure(cursor="")
            self.ok.configure(state="normal")
            self.status.configure(text="")
            messagebox.showerror("验证失败", str(e), parent=self)
            return
        except Exception as e:                       # noqa: BLE001
            self.configure(cursor="")
            self.ok.configure(state="normal")
            messagebox.showerror("验证失败", str(e), parent=self)
            return
        self.configure(cursor="")
        self.result = eudic.add_account(token, self.name_var.get(), "en")
        self.destroy()


def make(master, ctx, app):
    return EudicPage(master, ctx, app)
