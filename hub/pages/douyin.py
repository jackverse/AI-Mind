# -*- coding: utf-8 -*-
"""抖音页：一次扫码长期同步 + 多账号数据看板。

数据来自创作者中心的只读接口（也兼容后台导出的 xlsx），解析结果存
`data/hub/douyin/<抖音号>.json`。

版式（2026-11-04 重做）：顶部只放标题 / 视图切换 / 账号 / 数据量 + 三个操作，
同步状态单独一条细卡；「概览」看指标卡、趋势、Top 6、分账号，
「明细」是一整张可排序可搜索的作品表——不再把所有东西挤进一屏。
"""
import os
import queue
import threading
import tkinter as tk
import webbrowser
from tkinter import filedialog, messagebox, simpledialog, ttk

import dash
import ui
from core import douyin as dy
from core import douyin_auth as da
from core import douyin_sync as ds
from core import privacy as pv

URL_CONTENT = "https://creator.douyin.com/creator-micro/content/manage"
URL_DATA = "https://creator.douyin.com/creator-micro/data-center/operation"

ALL = "__all__"

# 明细表列：(key, 表头, 宽度, 对齐, 是否吃掉剩余宽度)
# 作品标题放最前（内容页最想看的是「哪条」），账号放最后（融合视图才加）
COLS = [
    ("title", "作品", 380, "w", True),
    ("date", "日期", 96, "w", False),
    ("media", "体裁", 84, "w", False),
    ("plays", "播放", 74, "e", False),
    ("finish", "完播率", 68, "e", False),
    ("likes", "点赞", 56, "e", False),
    ("fans", "涨粉", 56, "e", False),
]


class DouyinPage(tk.Frame):
    def __init__(self, master, ctx, app):
        super().__init__(master, bg=ui.C["bg"])
        self.ctx, self.app = ctx, app
        self.handle = None          # None = 全部融合；否则为单个抖音号
        self.stats = None
        self._query = ""            # 明细表搜索词
        self._table = None
        self._tab_seg = None
        self._tab_labels = []
        self._tab_values = []
        self._pills_on = True
        self._task_checked = False
        self._build_header()
        self._build_sync_bar()
        self.area = dash.ScrollArea(self)
        self.area.pack(fill="both", expand=True, padx=20, pady=(0, 8))

    # ------------------------------------------------------------ 顶部
    def _build_header(self):
        bar = tk.Frame(self, bg=ui.C["bg"])
        bar.pack(fill="x", padx=20, pady=(18, 10))

        # 右侧操作区先 pack，保证窄窗口下按钮不被标题挤出去
        right = tk.Frame(bar, bg=ui.C["bg"])
        right.pack(side="right")
        self._btn_add = dash.Btn(right, "＋ 账号", self.add_account)
        self._btn_add.pack(side="left", padx=(6, 0))
        dash.Btn(right, "导入", self.import_files, kind="soft").pack(
            side="left", padx=(6, 0))
        dash.Btn(right, "来源", self.show_guide).pack(side="left", padx=(6, 0))

        left = tk.Frame(bar, bg=ui.C["bg"])
        left.pack(side="left", fill="x", expand=True)
        tk.Label(left, text="抖音", font=dash.f(21, True), bg=ui.C["bg"],
                 fg=ui.C["text"]).pack(side="left")
        self.pill_acc = dash.Pill(left, "未绑定账号", fg=dash.MUTED, fill="#eef1f6")
        self.pill_acc.pack(side="left", padx=(12, 0), pady=(4, 0))
        self.pill_cnt = dash.Pill(left, "0 条作品", fg=dash.ACCENT, fill=dash.ACCENT_SOFT)
        self.pill_cnt.pack(side="left", padx=(6, 0), pady=(4, 0))
        bar.bind("<Configure>", self._on_header_resize)

        # 账号 tab：2 个号以上才显示（全部融合 + 每个号一个）
        self.tab_bar = tk.Frame(self, bg=ui.C["bg"])
        self.tab_bar.pack(fill="x", padx=20, pady=(0, 8))

    def _on_header_resize(self, event):
        """窄窗口把两个胶囊收掉，优先保证右侧按钮完整。"""
        want = event.width >= 800
        if want == self._pills_on:
            return
        self._pills_on = want
        for i, pill in enumerate((self.pill_acc, self.pill_cnt)):
            if want:
                pill.pack(side="left", padx=(12 if i == 0 else 6, 0), pady=(4, 0))
            else:
                pill.pack_forget()

    def _on_tab(self, i):
        """切换账号 tab：0 = 全部融合，其余为单个抖音号。"""
        if 0 <= i < len(self._tab_values):
            self.handle = self._tab_values[i]
        self._query = ""
        self.refresh()

    # ------------------------------------------------------------ 同步状态条
    def _build_sync_bar(self):
        card = dash.Card(self, padx=14, pady=9)
        card.pack(fill="x", padx=20, pady=(0, 10))
        self.sync_card = card
        row = tk.Frame(card.content, bg=ui.C["card"])
        row.pack(fill="x")

        right = tk.Frame(row, bg=ui.C["card"])
        right.pack(side="right")
        self.login_btn = dash.Btn(right, "登录", self.login_dialog, height=28)
        self.login_btn.pack(side="left", padx=(0, 6))
        dash.Btn(right, "定时", self.open_schedule, height=28).pack(
            side="left", padx=(0, 6))
        dash.Btn(right, "日志", self.show_log, height=28).pack(
            side="left", padx=(0, 10))
        self.sync_btn = dash.Btn(right, "立即同步", self.run_sync_now, kind="primary",
                                 height=28)
        self.sync_btn.pack(side="left")

        dot = tk.Canvas(row, width=10, height=10, bg=ui.C["card"],
                        highlightthickness=0)
        dot.pack(side="left", pady=(4, 0))
        self._dot_id = dot.create_oval(1, 1, 9, 9, fill=ui.C["muted"], outline="")
        self._dot = dot
        tk.Label(row, text="自动同步", font=dash.f(10, True), bg=ui.C["card"],
                 fg=ui.C["text"]).pack(side="left", padx=(6, 0))
        self.sync_lbl = tk.Label(row, text="", font=dash.f(9), bg=ui.C["card"],
                                 fg=dash.MUTED, anchor="w")
        self.sync_lbl.pack(side="left", padx=(8, 0), pady=(2, 0))
        self._refresh_sync_bar()

    def _refresh_sync_bar(self):
        text, color = ds.status()
        self._set_sync_text(pv.show_text(text, self._acct_names()),
                            ui.C.get(color, dash.MUTED))

    def _acct_names(self):
        try:
            return [a.get("name") for a in self._accounts()]
        except Exception:                       # noqa: BLE001 — 只用来给日志打码
            return []

    def _set_sync_text(self, text, color=None):
        color = color or dash.MUTED
        try:
            self.sync_lbl.configure(text=text, fg=color)
            self._dot.itemconfigure(self._dot_id, fill=color)
        except tk.TclError:
            pass

    def _bg(self, work, done):
        """后台跑 work()，主线程回调 done(result)；异常也变成 result，别让 UI 卡死。"""
        q = queue.Queue()

        def runner():
            try:
                q.put(work())
            except Exception as e:                       # noqa: BLE001
                q.put({"ok": False, "errors": [str(e)],
                       "message": f"{type(e).__name__}: {e}", "accounts": []})

        threading.Thread(target=runner, daemon=True).start()

        def poll():
            try:
                result = q.get_nowait()
            except queue.Empty:
                self.after(150, poll)
                return
            done(result)

        self.after(150, poll)

    def run_sync_now(self):
        if da.local_key_missing():
            messagebox.showwarning(
                "缺同步密钥",
                "本机的登录态分片还在，但本机没有同步密钥。\n"
                "先点「登录 → 同步密钥…」导入本机那把。", parent=self)
            return
        if not ds.logged_handles():
            messagebox.showinfo(
                "还没有登录",
                "先点「登录」用抖音 App 扫码一次（每个号各扫一次），之后就能长期自动同步。",
                parent=self)
            return
        self.sync_btn.set_enabled(False)
        self._set_sync_text("同步中：逐个账号拉作品列表 + 每日趋势（约 10~40 秒）…")

        def done(result):
            self.sync_btn.set_enabled(True)
            self.refresh()
            if result.get("ok"):
                per = "\n".join(
                    f"· {pv.show_handle(a['handle'])}"
                    + (f"（{pv.show_name(a['name'])}）" if a.get("name") else "")
                    + f"：作品 {a['works']} · 趋势 {a['daily']} 天"
                    for a in result.get("accounts") or [])
                extra = ("\n\n注意：\n"
                         + pv.show_text("\n".join(result["errors"]), self._acct_names())
                         ) if result.get("errors") else ""
                messagebox.showinfo("同步完成", per + extra, parent=self)
            else:
                messagebox.showerror("同步失败", result.get("message") or "未知错误",
                                     parent=self)

        self._bg(ds.sync, done)

    # ------------------------------------------------------------ 账号
    def _accounts(self):
        return dy.load_accounts()

    def _tab_label(self, acct, used):
        """tab 上只写昵称（脱敏）；没备注名就写脱敏后的抖音号，重名补号尾。"""
        name = pv.show_name(acct.get("name") or "")
        base = name or pv.show_handle(acct.get("handle"))
        label = base
        if label in used:
            label = f"{base}·{pv.show_handle(acct.get('handle'))[-3:]}"
        used.add(label)
        return label

    def _sync_tabs(self, accounts):
        if len(accounts) <= 1:
            self.tab_bar.pack_forget()
            self._tab_seg = None
            self._tab_labels = []
            self._tab_values = []
            return
        if not self.tab_bar.winfo_manager():
            self.tab_bar.pack(fill="x", padx=20, pady=(0, 8),
                              before=getattr(self, "sync_card", None))
        used, labels, values = set(), ["全部融合"], [None]
        for a in accounts:
            labels.append(self._tab_label(a, used))
            values.append(a["handle"])
        idx = values.index(self.handle) if self.handle in values else 0
        self._tab_values = values
        if self._tab_seg is None:
            self._tab_seg = dash.Segment(self.tab_bar, labels,
                                         command=self._on_tab, value=idx)
            self._tab_seg.pack(side="left")
        elif labels != self._tab_labels:
            self._tab_seg.set_items(labels, idx)
        else:
            self._tab_seg.set_value(idx)
        self._tab_labels = labels

    def _refresh_actions(self):
        """登录后不再显示「登录」：同一个按钮改成「账号…」，扫码入口还在。"""
        logged = bool(ds.logged_handles())
        try:
            self.login_btn.set_text("账号…" if logged else "登录")
        except (AttributeError, tk.TclError):
            pass

    def _handles(self):
        accounts = self._accounts()
        all_handles = [a["handle"] for a in accounts]
        if self.handle is None:
            return all_handles
        return [self.handle] if self.handle in all_handles else all_handles

    def add_account(self):
        handle = simpledialog.askstring("添加抖音号", "抖音号（纯数字）：", parent=self)
        if not handle:
            return
        handle = handle.strip()
        if not handle.isdigit():
            messagebox.showwarning("格式不对", "抖音号应该是纯数字，例如 12345678901",
                                   parent=self)
            return
        name = simpledialog.askstring("备注名（可留空）", "给这个账号起个名字：",
                                      parent=self) or ""
        dy.add_account(handle, name or "")
        self.handle = handle
        self.refresh()
        messagebox.showinfo(
            "已添加",
            f"抖音号 {pv.show_handle(handle)} 已绑定。\n\n下一步：点「登录」扫码一次，"
            "或点「导入」把手里的导出表导进来。", parent=self)

    def import_files(self):
        accounts = self._accounts()
        if not accounts:
            messagebox.showinfo("还没有账号",
                                "先点「＋ 账号」绑定一个抖音号，再导入数据。", parent=self)
            return
        if self.handle is None:
            messagebox.showinfo(
                "先选一个账号",
                "当前是「全部融合」视图，导入需要指定归属账号。\n"
                "请在上方账号 tab 里选中具体账号再导入。", parent=self)
            return

        paths = filedialog.askopenfilenames(
            parent=self, title="选择创作者中心导出的 Excel（可多选）",
            filetypes=[("Excel 表格", "*.xlsx *.xlsm"), ("全部文件", "*.*")])
        if not paths:
            return

        lines, ok = [], 0
        for p in paths:
            try:
                kind, added, updated = dy.import_file(p, self.handle)
                ok += 1
                lines.append(f"✓ {os.path.basename(p)}\n    {dy.KIND_LABEL[kind]}："
                             f"新增 {added} 条，更新 {updated} 条")
            except Exception as e:                  # noqa: BLE001 — 单文件失败不影响其它
                lines.append(f"✗ {os.path.basename(p)}\n    {e}")
        self.refresh()
        messagebox.showinfo("导入结果" if ok else "导入失败", "\n\n".join(lines), parent=self)

    def show_guide(self):
        messagebox.showinfo(
            "数据从哪来",
            "抖音创作者中心 → 两个导出入口：\n\n"
            "① 作品明细（每条作品的播放/完播/互动）\n"
            f"   {URL_CONTENT}\n"
            "   内容管理 → 作品列表 → 导出\n\n"
            "② 每日全量指标（账号每天的整体表现）\n"
            f"   {URL_DATA}\n"
            "   数据中心 → 数据表现 → 导出\n\n"
            "导出的 .xlsx 直接选「导入」，表头认得出就自动归类。\n"
            "更省事的是点「登录」扫码一次，之后每天自动同步。\n\n"
            "注意：导出表里没有抖音号，所以导入前要先选中归属账号。",
            parent=self)

    # ------------------------------------------------------------ 登录 / 密钥 / 定时
    def _account_rows(self):
        """[(handle, name, has_token, last)]，覆盖已绑定账号 + 只有登录态的号。"""
        cfg = ds.load_cfg()
        stats = cfg.get("accounts") or {}
        rows, seen = [], set()
        for a in self._accounts():
            handle = str(a.get("handle") or "")
            if not handle:
                continue
            seen.add(handle)
            rows.append((handle, a.get("name") or "", handle in ds.logged_handles(),
                         stats.get(handle) or {}))
        try:
            sessions = da.load_sessions()
        except da.AuthError:
            sessions = {}
        for handle, sess in sessions.items():
            if handle in seen:
                continue
            rows.append((handle, sess.get("name") or "", True, stats.get(handle) or {}))
        return rows

    def login_dialog(self):
        win = tk.Toplevel(self)
        win.title("登录抖音（每个号各扫一次）")
        win.configure(bg=ui.C["bg"])
        win.transient(self.winfo_toplevel())
        win.geometry("780x560")

        pad = tk.Frame(win, bg=ui.C["bg"])
        pad.pack(fill="both", expand=True, padx=18, pady=14)

        tk.Label(pad, text="扫码登录（每个号各扫一次，之后长期有效）",
                 font=ui.F["h3"], bg=ui.C["bg"], fg=ui.C["text"]).pack(anchor="w")
        tk.Label(
            pad,
            text=("点「打开浏览器扫码」会弹一个专用浏览器（独立配置，不碰你平时的 Chrome）。\n"
                  "每个号都会新开一个独立配置，扫完即关、用完即删，绝不会把上一个号的 Cookie 带过来。\n"
                  "扫码前先在抖音 App 里切到要登录的那个号，再扫；否则扫进来的还是手机当前登录的号。\n"
                  "只调用创作者中心的只读数据接口：不发布、不点赞、不评论、不改资料。"),
            font=ui.F["small"], bg=ui.C["bg"], fg=ui.C["muted"],
            justify="left", anchor="w").pack(anchor="w", pady=(2, 8))

        top = tk.Frame(pad, bg=ui.C["bg"])
        top.pack(fill="x")
        login_btn = ttk.Button(top, text="打开浏览器扫码", style="Accent.TButton")
        login_btn.pack(side="left")
        ttk.Button(top, text="换个号", command=self.switch_account).pack(side="left", padx=6)
        ttk.Button(top, text="同步密钥…", command=lambda: self.key_dialog(parent=win)).pack(
            side="left", padx=6)
        tk.Label(top, text="手机号备注（可选）", font=ui.F["small"],
                 bg=ui.C["bg"], fg=ui.C["muted"]).pack(side="left", padx=(8, 4))
        var_phone = tk.StringVar()
        ttk.Entry(top, textvariable=var_phone, width=13).pack(side="left")

        status = tk.Label(pad, text=self._login_hint(), font=ui.F["small"],
                          bg=ui.C["bg"], fg=ui.C["muted"], anchor="w")
        status.pack(anchor="w", pady=(6, 0))

        tk.Label(pad, text="账号与登录状态", font=ui.F["h4"], bg=ui.C["bg"],
                 fg=ui.C["text"]).pack(anchor="w", pady=(10, 2))
        acc_box = tk.Text(pad, height=7, font=ui.F["small"], wrap="word",
                          relief="solid", bd=1, bg="#f7f9fc", fg=ui.C["text"])
        acc_box.pack(fill="both", expand=True)
        acc_box.configure(state="disabled")

        def fill_accounts():
            acc_box.configure(state="normal")
            acc_box.delete("1.0", "end")
            rows = self._account_rows()
            if not rows:
                acc_box.insert("end", "（还没有）扫一次码就会出现在这里\n")
            for handle, name, has, last in rows:
                bits = [pv.show_handle(handle)]
                if name:
                    bits.append(pv.show_name(name))
                bits.append("登录态 ✓" if has else "登录态 ✗ 需重扫")
                if last.get("at"):
                    bits.append(f"上次 {'✓' if last.get('ok') else '✗'} {last['at'][5:]}")
                    if last.get("error"):
                        bits.append("错误：" + str(last["error"])[:40])
                acc_box.insert("end", "· " + " · ".join(bits) + "\n")
            if da.local_key_missing():
                acc_box.insert("end", "\n⚠ 本机分片在但缺同步密钥：先点「同步密钥…」导入本机那把。\n")
            acc_box.configure(state="disabled")

        fill_accounts()

        def on_login():
            login_btn.state(["disabled"])
            status.configure(text="正在打开浏览器…", fg=ui.C["muted"])
            q = queue.Queue()
            phone = var_phone.get().strip()

            def work():
                try:
                    q.put(("done", ds.login(on_status=lambda s: q.put(("s", s)),
                                            phone=phone)))
                except Exception as e:                   # noqa: BLE001
                    q.put(("err", str(e)))

            threading.Thread(target=work, daemon=True).start()

            def poll():
                try:
                    kind, val = q.get_nowait()
                except queue.Empty:
                    win.after(300, poll)
                    return
                if kind == "s":
                    status.configure(text=pv.show_text(val, self._acct_names()),
                                     fg=ui.C["muted"])
                    win.after(250, poll)
                elif kind == "done":
                    login_btn.state(["!disabled"])
                    self.handle = val.get("handle") or self.handle
                    status.configure(
                        text=f"已登录 {pv.show_handle(val.get('handle'))}"
                             + (f"（{pv.show_name(val['name'])}）" if val.get("name") else "")
                             + "，登录态已加密保存",
                        fg=ui.C["ok"])
                    fill_accounts()
                    self.refresh()
                    self._refresh_actions()
                    try:
                        ds.ensure_task()          # 登录后默认把每天同步任务补上
                    except Exception:             # noqa: BLE001
                        pass
                    self._refresh_sync_bar()
                    if val.get("key_created"):
                        messagebox.showinfo(
                            "同步密钥已生成",
                            "这是第一次登录，工具生成了一把「同步密钥」，用来加密登录态。\n\n"
                            "换机器时要把这把密钥粘到另一台机器一次；丢了就只能重新扫码。\n"
                            "下一步会显示密钥，请自己存好（别发到公开地方）。",
                            parent=win)
                        self.key_dialog(prefill=val.get("key_text"), parent=win)
                else:
                    status.configure(text=pv.show_text(val, self._acct_names()),
                                     fg=ui.C["bad"])
                    login_btn.state(["!disabled"])

            win.after(300, poll)

        login_btn.configure(command=on_login)

        bar = tk.Frame(pad, bg=ui.C["bg"])
        bar.pack(fill="x", pady=(8, 0))
        ttk.Button(bar, text="查看日志", command=self.show_log).pack(side="left")
        ttk.Button(bar, text="关闭", command=win.destroy).pack(side="right")

    def switch_account(self):
        closed = False
        try:
            closed = ds.cancel_login()
        except Exception as e:                          # noqa: BLE001
            messagebox.showerror("关闭扫码窗口失败", str(e), parent=self)
            return
        if closed:
            messagebox.showinfo(
                "已关闭当前扫码窗口",
                "已保存的登录态不受影响。\n"
                "点「打开浏览器扫码」扫下一个号：每次都会用全新的独立配置，不会带上一个号的登录。",
                parent=self)
        else:
            messagebox.showinfo(
                "可以扫下一个号",
                "当前没有挂着的扫码窗口。\n"
                "直接点「打开浏览器扫码」即可：每次都会新开一个独立配置，和上一个号完全隔离。",
                parent=self)

    def key_dialog(self, prefill=None, parent=None):
        win = tk.Toplevel(parent or self)
        win.title("抖音 · 同步密钥")
        win.configure(bg=ui.C["bg"])
        win.transient(self.winfo_toplevel())
        win.geometry("700x440")

        pad = tk.Frame(win, bg=ui.C["bg"])
        pad.pack(fill="both", expand=True, padx=20, pady=16)

        tk.Label(pad, text="一把密钥，多台机器共用登录态", font=ui.F["h3"],
                 bg=ui.C["bg"], fg=ui.C["text"]).pack(anchor="w")
        tk.Label(
            pad,
            text=("仓库里只放加密后的 auth.<机器>.json；密钥只在本机 "
                  "data/hub/douyin/sync.key，不进 git。\n"
                  "换机器：把下面这串粘到另一台机器的「从另一台机器导入」，之后长期不用再管。"),
            font=ui.F["small"], bg=ui.C["bg"], fg=ui.C["muted"],
            justify="left", anchor="w").pack(anchor="w", pady=(2, 10))

        key = da.load_key()
        if key is None and not prefill:
            try:
                key, _created = da.ensure_key()
            except da.AuthError as e:
                key = None
                tk.Label(pad, text=str(e), font=ui.F["small"], bg=ui.C["bg"],
                         fg=ui.C["bad"], wraplength=620, justify="left").pack(anchor="w")

        var = tk.StringVar(value=prefill or (da.key_text(key) if key else ""))
        ent = ttk.Entry(pad, textvariable=var, font=(ui.MONO, 10), width=64)
        ent.pack(fill="x", pady=(2, 8))
        ent.configure(state="readonly")

        def copy_key():
            text = var.get().strip()
            if not text:
                return
            win.clipboard_clear()
            win.clipboard_append(text)
            messagebox.showinfo("已复制", "同步密钥已复制到剪贴板。", parent=win)

        def import_key():
            text = simpledialog.askstring(
                "导入同步密钥", "把另一台机器的同步密钥粘进来：", parent=win)
            if not text:
                return
            try:
                da.import_key(text)
            except da.AuthError as e:
                messagebox.showerror("导入失败", str(e), parent=win)
                return
            var.set(da.key_text())
            messagebox.showinfo("导入成功", "密钥已保存，现在可以同步另一台机器的登录态了。",
                                parent=win)
            self.refresh()

        def rotate_key():
            if not messagebox.askyesno(
                    "换新密钥",
                    "会用新密钥重新加密本仓库里所有 auth.*.json。\n"
                    "另一台机器要重新导入新密钥，否则解不开。继续？", parent=win):
                return
            try:
                new = da.new_key()
                n = da.rotate_all(new)
                var.set(da.key_text(new))
                messagebox.showinfo(
                    "已换密钥",
                    f"已重新加密 {n} 个分片。\n新密钥已显示，复制到另一台机器即可。",
                    parent=win)
            except da.AuthError as e:
                messagebox.showerror("换密钥失败", str(e), parent=win)

        info = (f"本机：{da.machine_name()} · 密钥状态："
                + ("已保存" if da.load_key() else "没有")
                + f" · 加密登录态文件：{len(da.auth_files())} 个")
        tk.Label(pad, text=info, font=ui.F["small"], bg=ui.C["bg"],
                 fg=ui.C["muted"]).pack(anchor="w", pady=(2, 8))

        bar = tk.Frame(pad, bg=ui.C["bg"])
        bar.pack(fill="x", pady=(8, 0))
        ttk.Button(bar, text="复制密钥", command=copy_key).pack(side="left")
        ttk.Button(bar, text="从另一台机器导入…",
                   command=import_key).pack(side="left", padx=6)
        ttk.Button(bar, text="换新密钥…", command=rotate_key).pack(side="left", padx=6)
        ttk.Button(bar, text="关闭", command=win.destroy).pack(side="right")

        if prefill:
            messagebox.showinfo(
                "这把密钥只显示这一次",
                "请现在复制保存（密码管理器/另一台机器）。\n"
                "丢了不会泄露数据，但两台机器都得重新扫码。",
                parent=win)

    @staticmethod
    def _login_hint():
        handles = ds.logged_handles()
        if not handles:
            if da.local_key_missing():
                return "本机分片在，但缺同步密钥（导入后才能同步）"
            return "当前未登录"
        return (f"已登录 {len(handles)} 个号："
                + "、".join(pv.show_handle(h) for h in handles[:6]))

    def open_schedule(self):
        cfg = ds.load_cfg()
        handles = ds.logged_handles()
        win = tk.Toplevel(self)
        win.title("自动同步 · 定时设置")
        win.configure(bg=ui.C["bg"])
        win.transient(self.winfo_toplevel())
        win.resizable(False, False)

        pad = tk.Frame(win, bg=ui.C["bg"])
        pad.pack(padx=22, pady=18)
        tk.Label(pad, text="每天自动同步所有已登录账号", font=ui.F["h3"],
                 bg=ui.C["bg"], fg=ui.C["text"]).grid(
                     row=0, column=0, columnspan=2, sticky="w")
        tk.Label(pad,
                 text="任务名「抖音数据同步」，注册后也能在 Windows 任务计划程序里改；"
                      "每个号各自落库，不会串号",
                 font=ui.F["small"], bg=ui.C["bg"], fg=ui.C["muted"]).grid(
                     row=1, column=0, columnspan=2, sticky="w", pady=(2, 12))

        var_time = tk.StringVar(value=cfg.get("time", "09:10"))
        var_days = tk.StringVar(value=str(cfg.get("days", 30)))
        var_on = tk.BooleanVar(value=bool(cfg.get("enabled")))

        rows = [
            ("每天时间", tk.Entry(pad, textvariable=var_time, width=10,
                                  font=ui.F["body"], relief="solid", bd=1)),
            ("趋势回看天数", ttk.Spinbox(pad, from_=1, to=180, width=8,
                                     textvariable=var_days)),
        ]
        for i, (label, widget) in enumerate(rows, start=2):
            tk.Label(pad, text=label, font=ui.F["small"], bg=ui.C["bg"],
                     fg=ui.C["muted"]).grid(row=i, column=0, sticky="w",
                                            pady=4, padx=(0, 12))
            widget.grid(row=i, column=1, sticky="w", pady=4)
        tk.Checkbutton(pad, text="每天自动同步（写入 Windows 计划任务）",
                       variable=var_on, font=ui.F["small"], bg=ui.C["bg"],
                       activebackground=ui.C["bg"], anchor="w").grid(
                           row=4, column=0, columnspan=2, sticky="w", pady=(8, 2))

        if handles:
            acc_txt = "已登录：" + "、".join(pv.show_handle(h) for h in handles)
        else:
            acc_txt = "还没有登录账号：先去「登录」扫一次码"
        if da.local_key_missing():
            acc_txt += "\n⚠ 本机分片在但缺同步密钥，先到「登录 → 同步密钥」导入"
        tk.Label(pad, text=acc_txt, font=ui.F["small"], bg=ui.C["bg"],
                 fg=ui.C["muted"], wraplength=380, justify="left").grid(
                     row=5, column=0, columnspan=2, sticky="w", pady=(2, 4))

        info = ds.task_info()
        if info.get("exists"):
            state = (f"当前任务：每天 {info.get('time')} · "
                     f"下次 {info.get('next') or '（未排期）'}")
        else:
            state = "当前没有注册定时任务"
        tk.Label(pad, text=state, font=ui.F["small"], bg=ui.C["bg"],
                 fg=ui.C["muted"]).grid(row=6, column=0, columnspan=2,
                                        sticky="w", pady=(2, 10))

        bar = tk.Frame(pad, bg=ui.C["bg"])
        bar.grid(row=7, column=0, columnspan=2, sticky="w")

        def save():
            try:
                at = ds.norm_time(var_time.get())
                if var_on.get() and not ds.logged_handles():
                    raise ds.SyncError("还没有登录账号，先去「登录」扫码")
                new = ds.load_cfg()
                new.update(time=at, enabled=bool(var_on.get()),
                           days=max(1, int(var_days.get() or 30)))
                ds.save_cfg(new)
                if var_on.get():
                    got = ds.register_task(at)
                    messagebox.showinfo(
                        "已启用",
                        f"每天 {at} 自动同步。\n下次运行：{got.get('next') or '明天 ' + at}",
                        parent=win)
                else:
                    ds.unregister_task()
                    messagebox.showinfo("已停用", "定时任务已删除；「立即同步」照常可用。",
                                        parent=win)
                win.destroy()
                self.refresh()
            except ds.SyncError as e:
                messagebox.showerror("设置失败", str(e), parent=win)
            except ValueError:
                messagebox.showerror("设置失败", "天数要填数字", parent=win)

        ttk.Button(bar, text="保存", style="Accent.TButton",
                   command=save).pack(side="left", padx=(0, 6))
        ttk.Button(bar, text="打开任务计划程序",
                   command=lambda: _open_scheduler(win)).pack(side="left", padx=6)
        ttk.Button(bar, text="关闭", command=win.destroy).pack(side="left", padx=6)

    def show_log(self):
        win = tk.Toplevel(self)
        win.title("抖音自动同步日志")
        win.configure(bg=ui.C["card"])
        win.transient(self.winfo_toplevel())
        win.geometry("800x460")
        body = tk.Frame(win, bg=ui.C["card"])
        body.pack(fill="both", expand=True, padx=12, pady=(12, 0))
        box = tk.Text(body, wrap="none", font=ui.F["mono"], bg=ui.C["card"],
                      fg=ui.C["text"], relief="flat")
        sb = ttk.Scrollbar(body, orient="vertical", command=box.yview)
        box.configure(yscrollcommand=sb.set)
        box.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        lines = ds.read_log(300) or ["（还没有日志：点「立即同步」跑一次）"]
        names = [a.get("name") for a in self._accounts()]
        box.insert("end", pv.show_text("\n".join(lines), names))
        box.see("end")
        box.configure(state="disabled")

        bar = tk.Frame(win, bg=ui.C["card"])
        bar.pack(fill="x", padx=12, pady=10)
        ttk.Button(bar, text="打开数据目录",
                   command=lambda: os.startfile(str(ds._dir()))
                   if ds._dir().is_dir() else None).pack(side="left")
        ttk.Button(bar, text="关闭", command=win.destroy).pack(side="right")

    # ------------------------------------------------------------ 刷新
    def on_show(self, **kw):
        self.refresh()
        if not self._task_checked:          # 默认每天同步：任务没注册就补一次
            self._task_checked = True
            try:
                ds.ensure_task()
            except Exception:               # noqa: BLE001
                pass
            self._refresh_sync_bar()

    def refresh(self):
        accounts = self._accounts()
        if len(accounts) == 1:
            self.handle = accounts[0]["handle"]
        elif self.handle not in [a["handle"] for a in accounts]:
            self.handle = None
        self._sync_tabs(accounts)
        self._refresh_sync_bar()
        self._refresh_actions()

        stats = dy.summarize(self._handles()) if accounts else None
        self.stats = stats
        if not accounts or not stats or not stats["count"]:
            self.pill_acc.set_text("未绑定账号" if not accounts else
                                   f"{len(accounts)} 个账号", fg=dash.MUTED,
                                   fill="#eef1f6")
            self.pill_cnt.set_text("0 条作品", fg=dash.MUTED, fill="#eef1f6")
        elif self.handle is None:
            self.pill_acc.set_text(f"全部融合 · {len(accounts)} 个号",
                                   fg=dash.ACCENT, fill=dash.ACCENT_SOFT)
            self.pill_cnt.set_text(f"{stats['count']} 条作品",
                                   fg=dash.ACCENT, fill=dash.ACCENT_SOFT)
        else:
            acct = self._account_of(self.handle) or {}
            label = pv.show_name(acct.get("name") or "") or pv.show_handle(self.handle)
            self.pill_acc.set_text(label, fg=dash.ACCENT, fill=dash.ACCENT_SOFT)
            self.pill_cnt.set_text(f"{stats['count']} 条作品",
                                   fg=dash.ACCENT, fill=dash.ACCENT_SOFT)
        self._render_view()

    def _account_of(self, handle):
        for a in self._accounts():
            if a.get("handle") == handle:
                return a
        return None

    def _render_view(self):
        for w in self.area.body.winfo_children():
            w.destroy()
        self.area.scroll_top()
        s = self.stats
        if not s or not s["count"]:
            self._build_empty(self._accounts())
        elif self.handle is None and len(self._accounts()) > 1:
            self._build_compare(s)
        else:
            self._build_single(s)
        self.area.bind_wheel()

    # ------------------------------------------------------------ 空状态引导
    def _build_empty(self, accounts):
        card = dash.Card(self.area.body, padx=28, pady=24)
        card.pack(fill="x")
        inner = card.content

        tk.Label(inner, text="还没有数据" if not accounts else "账号已绑定，还缺数据",
                 font=dash.f(17, True), bg=ui.C["card"], fg=ui.C["text"],
                 anchor="w").pack(fill="x")
        tk.Label(inner, text="扫码一次就长期同步：登录 → 自动拉作品和每日趋势 → 多个号分开看。",
                 font=dash.f(10), bg=ui.C["card"], fg=dash.MUTED,
                 anchor="w").pack(fill="x", pady=(6, 20))

        steps = [
            ("登录一次（每个号扫一次）",
             "点「登录」会弹专用浏览器，用抖音 App 扫码；工具自动认号，"
             "登录态加密保存，之后长期有效。四个号各扫一次。"),
            ("等它自己同步",
             "点「立即同步」拉作品列表 + 每日趋势，按抖音号分开入库；"
             "也可以在「定时」里设成每天自动跑。"),
            ("（可选）手动导入兜底",
             "后台导出的 xlsx 也能直接拖进来，表头认得出就自动归类。"),
        ]
        for i, (title, desc) in enumerate(steps, start=1):
            self._step(inner, i, title, desc)

        links = tk.Frame(inner, bg=ui.C["card"])
        links.pack(anchor="w", pady=(2, 16))
        for label, url in (("打开作品列表页 ↗", URL_CONTENT),
                           ("打开数据表现页 ↗", URL_DATA)):
            link = tk.Label(links, text=label, font=dash.f(9), bg=ui.C["card"],
                            fg=dash.ACCENT, anchor="w", cursor="hand2")
            link.pack(side="left", padx=(0, 18))
            link.bind("<Button-1>", lambda _e, u=url: webbrowser.open(u))

        btns = tk.Frame(inner, bg=ui.C["card"])
        btns.pack(anchor="w")
        logged = bool(ds.logged_handles())
        dash.Btn(btns, "账号…" if logged else "登录抖音", self.login_dialog,
                 kind="primary").pack(side="left")
        dash.Btn(btns, "立即同步", self.run_sync_now).pack(side="left", padx=(8, 0))
        dash.Btn(btns, "手动导入 Excel", self.import_files).pack(side="left", padx=(8, 0))

    def _step(self, parent, n, title, desc):
        """空状态里的编号步骤：圆号 + 标题 + 说明。"""
        row = tk.Frame(parent, bg=ui.C["card"])
        row.pack(fill="x", pady=(0, 14))
        cv = tk.Canvas(row, width=26, height=26, bg=ui.C["card"],
                       highlightthickness=0)
        cv.pack(side="left", anchor="n")
        cv.create_oval(1, 1, 25, 25, fill=dash.ACCENT_SOFT, outline="")
        cv.create_text(13, 13, text=str(n), fill=dash.ACCENT, font=dash.f(10, True))
        txt = tk.Frame(row, bg=ui.C["card"])
        txt.pack(side="left", fill="x", expand=True, padx=(10, 0))
        tk.Label(txt, text=title, font=dash.f(10, True), bg=ui.C["card"],
                 fg=ui.C["text"], anchor="w").pack(fill="x")
        tk.Label(txt, text=desc, font=dash.f(9), bg=ui.C["card"], fg=dash.MUTED,
                 anchor="w", justify="left").pack(fill="x", pady=(2, 0))

    # ------------------------------------------------------------ 单账号
    def _build_single(self, s):
        """一个号：指标卡 / 趋势 / Top6 / 明细全铺在一屏里滚，不再分「概览·明细」。"""
        self._build_overview(s)
        self._build_detail(s, compare=False)

    # ------------------------------------------------------------ 全部融合（多号对比）
    def _build_compare(self, s):
        """全部融合：合计指标 + 分账号折线 / 分组柱 + 分账号表 + 合并明细。

        折线按账号各一条、柱状图按天每组多根柱子——不把几个号加总成一条线。
        """
        body = self.area.body
        accounts = self._accounts()
        layers = self._layers(accounts)

        cards = [
            ("账号", str(len(accounts)), "全部融合", None),
            ("作品", s["fmt_int"](s["count"]), "所有号合计", None),
            ("总播放", s["fmt_int"](s["total_plays"]),
             f"近 7 天 {s['fmt_int'](s['plays_last7'])}", s["trend"]),
            ("净涨粉", s["fmt_int"](s["fans"]), "作品累计", None),
            ("平均完播率", s["fmt_pct"](s["finish_avg"]) if s["finish_avg"] is not None else "-",
             "按作品平均", None),
        ]
        self._tiles(body, cards)

        mid = tk.Frame(body, bg=ui.C["bg"])
        mid.pack(fill="x", pady=(dash.GAP, 0))
        mid.columnconfigure(0, weight=5)
        mid.columnconfigure(1, weight=3)

        c1 = dash.Card(mid)
        c1.grid(row=0, column=0, sticky="nsew", padx=(0, dash.GAP))
        dash.section(c1.content, "每日播放 · 分账号", "一条线 = 一个号，互不叠加")
        chart = dash.LineChart(c1.content, height=184)
        chart.pack(fill="x", pady=(2, 0))
        chart.set_multi([{"label": l["label"], "color": l["color"],
                          "points": [(d["date"], d.get("plays") or 0)
                                     for d in l["stats"]["days"]]}
                         for l in layers])

        c2 = dash.Card(mid)
        c2.grid(row=0, column=1, sticky="nsew")
        dash.section(c2.content, "近 7 天 · 分账号对比",
                     "每组柱子 = 同一天的各号，右侧是合计")
        self._legend(c2.content, layers)
        bars = dash.BarList(c2.content, height=168, rows=7, label_w=48, value_w=56)
        bars.pack(fill="x", pady=(2, 0))
        days = self._compare_days(layers)[-7:]
        groups = []
        for day in days:
            vals = [l["plays"].get(day, 0) for l in layers]
            title = day[5:] + "：" + " · ".join(
                f"{l['label']} {int(v):,}" for l, v in zip(layers, vals))
            groups.append((day, vals, title))
        bars.set_groups(groups)

        self._build_accounts(body, s)
        self._build_detail(s, compare=True)

    def _layers(self, accounts):
        """每个号单独 summarize 一份，图表按号分开画，不把数据混在一起。"""
        out = []
        for i, a in enumerate(accounts):
            st = dy.summarize([a["handle"]])
            out.append({
                "acct": a,
                "handle": a["handle"],
                "stats": st,
                "label": pv.show_name(a.get("name") or "") or pv.show_handle(a["handle"]),
                "color": dash.SERIES_COLORS[i % len(dash.SERIES_COLORS)],
                "plays": {d["date"]: d.get("plays") or 0 for d in st["days"]},
            })
        return out

    @staticmethod
    def _compare_days(layers):
        days = sorted({d for l in layers for d in l["plays"]})
        return days

    @staticmethod
    def _legend(parent, layers):
        row = tk.Frame(parent, bg=ui.C["card"])
        row.pack(fill="x", pady=(0, 4))
        for l in layers:
            dot = tk.Canvas(row, width=9, height=9, bg=ui.C["card"],
                            highlightthickness=0)
            dot.create_oval(1, 1, 8, 8, fill=l["color"], outline="")
            dot.pack(side="left", padx=(0, 4))
            tk.Label(row, text=l["label"], font=dash.f(9), bg=ui.C["card"],
                     fg=dash.MUTED).pack(side="left", padx=(0, 12))

    def _tiles(self, body, cards):
        tiles = tk.Frame(body, bg=ui.C["bg"])
        tiles.pack(fill="x")
        for i, (label, value, note, delta) in enumerate(cards):
            tiles.columnconfigure(i, weight=1, uniform="t")
            tile = dash.StatTile(tiles, label, value, note=note, delta=delta)
            tile.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else 10, 0))

    # ------------------------------------------------------------ 概览
    def _build_overview(self, s):
        body = self.area.body
        f_int, f_pct = s["fmt_int"], s["fmt_pct"]

        # ---- 指标卡
        cards = [
            ("作品", f_int(s["count"]), "当前账号", None),
            ("总播放", f_int(s["total_plays"]),
             f"近 7 天 {f_int(s['plays_last7'])}", s["trend"]),
            ("净涨粉", f_int(s["fans"]), "作品累计", None),
            ("平均完播率", f_pct(s["finish_avg"]) if s["finish_avg"] is not None else "-",
             "按作品平均", None),
            ("互动率", f_pct(s["engage_rate"], 2), "赞评藏转 / 播放", None),
        ]
        self._tiles(body, cards)

        # ---- 趋势 + Top6
        mid = tk.Frame(body, bg=ui.C["bg"])
        mid.pack(fill="x", pady=(dash.GAP, 0))
        mid.columnconfigure(0, weight=5)
        mid.columnconfigure(1, weight=3)

        c1 = dash.Card(mid)
        c1.grid(row=0, column=0, sticky="nsew", padx=(0, dash.GAP))
        extra = []
        if s["gap_days"] is not None:
            extra.append(f"距上次发布 {s['gap_days']} 天")
        extra.append(f"近 7 天 {f_int(s['plays_last7'])}")
        dash.section(c1.content, "每日播放", " · ".join(extra))
        chart = dash.LineChart(c1.content, height=186)
        chart.pack(fill="x", pady=(2, 0))
        chart.set_series([(d["date"], d.get("plays") or 0) for d in s["days"]])

        c2 = dash.Card(mid)
        c2.grid(row=0, column=1, sticky="nsew")
        bar_hint = "先看跑出来的那几条"
        head = dash.section(c2.content, "播放 Top 6", bar_hint)
        bars = dash.BarList(c2.content, height=186, rows=6)
        bars.pack(fill="x", pady=(2, 0))
        top = s["top"][:6]

        def hover(title):
            if head.hint is None:
                return
            text = bar_hint if not title else (
                title if len(title) <= 30 else title[:29] + "…")
            head.hint.configure(text=text, fg=dash.FAINT if not title else dash.MUTED)

        bars.set_rows([(w.get("date") or "", w.get("plays") or 0,
                        w.get("title") or "") for w in top],
                      on_click=lambda i: self._show_detail(top[i]) if i < len(top) else None,
                      on_hover=hover)

    # ------------------------------------------------------------ 明细
    def _build_detail(self, s, compare=None):
        if compare is None:
            compare = self.handle is None
        card = dash.Card(self.area.body, pady=12)
        card.pack(fill="x", pady=(dash.GAP, 0))
        head = dash.section(card.content, "作品明细", self._media_hint(s),
                            pady=(0, 10))

        def right(parent):
            dash.Search(parent, placeholder="搜作品标题…",
                        on_change=self._on_search).pack(side="right")

        right(head)

        cols = list(COLS)
        if compare:
            cols.append(("handle", "账号", 112, "w", False))
        self._table = dash.DataTable(card.content, cols,
                                     height=min(14, max(8, s["count"])),
                                     on_double=lambda row: self._show_detail(row["_obj"]),
                                     ellipsis=("title",))
        self._table.pack(fill="x", pady=(2, 0))
        self._fill_table()

    @staticmethod
    def _media_hint(s):
        bits = [f"{k} {v}" for k, v in sorted(s["media"].items(), key=lambda kv: -kv[1])]
        return " · ".join(bits)

    def _rows(self):
        s, f_int, f_pct = self.stats, self.stats["fmt_int"], self.stats["fmt_pct"]
        rows = []
        for w in s["works"]:
            date = w.get("date") or ""
            title = w.get("title") or "(无标题)"
            raw_handle = w.get("_handle") or ""
            rows.append({
                "_obj": w,
                "handle": (pv.show_handle(raw_handle), raw_handle),
                "date": (date, date),
                "media": (w.get("media_type") or "-", w.get("media_type") or ""),
                "plays": (f_int(w.get("plays") or 0), w.get("plays") or 0),
                "finish": (f_pct(w.get("finish_rate")) if w.get("finish_rate") is not None
                           else "-", w.get("finish_rate") if w.get("finish_rate") is not None else -1),
                "likes": (f_int(w.get("likes") or 0), w.get("likes") or 0),
                "comments": (f_int(w.get("comments") or 0), w.get("comments") or 0),
                "fans": (f_int(w.get("fans_delta") or 0), w.get("fans_delta") or 0),
                "title": (title, title),
            })
        return rows

    def _on_search(self, text):
        self._query = text
        self._fill_table()

    def _fill_table(self):
        if self._table is None:
            return
        rows = self._rows()
        q = (self._query or "").lower()
        if q:
            rows = [r for r in rows
                    if q in str(r["title"][0]).lower()
                    or q in str(r["handle"][0]).lower()
                    or q in str(r["media"][0]).lower()
                    or q in str(r["date"][0])]
        self._table.set_rows(rows)

    # ------------------------------------------------------------ 分账号卡
    def _build_accounts(self, body, s):
        card = dash.Card(body, pady=12)
        card.pack(fill="x", pady=(dash.GAP, 0))
        dash.section(card.content, "分账号表现", "占比 = 该号播放 / 合计",
                     pady=(0, 8))
        total = s["total_plays"] or 1
        rows = []
        for a in self._accounts():
            handle = a["handle"]
            d = dy.load(handle)
            works = d.get("works") or []
            plays = sum(w.get("plays") or 0 for w in works)
            fans = sum(w.get("fans_delta") or 0 for w in works)
            pairs = [(w.get("finish_rate"), w.get("plays") or 0) for w in works
                     if isinstance(w.get("finish_rate"), (int, float))
                     and (w.get("plays") or 0) > 0]
            denom = sum(p for _, p in pairs)
            finish = (sum(r * p for r, p in pairs) / denom) if denom else None
            rows.append({"name": pv.show_handle(handle),
                         "sub": pv.show_name(a.get("name") or ""),
                         "cells": [str(len(works)), s["fmt_int"](plays),
                                   f"{plays / total * 100:.0f}%",
                                   s["fmt_pct"](finish) if finish is not None else "-",
                                   s["fmt_int"](fans)]})
        rows.sort(key=lambda r: -int(r["cells"][1].replace(",", "") or 0))
        table = dash.AccountTable(card.content)
        table.pack(fill="x", pady=(0, 4))
        table.set_rows(rows)

    # ------------------------------------------------------------ 作品详情
    def _show_detail(self, w):
        if not w:
            return
        f, p = self.stats["fmt_int"], self.stats["fmt_pct"]
        rows = [
            ("作品", w.get("title") or "-"),
            ("发布时间", w.get("published_at") or "-"),
            ("体裁 / 状态", f"{w.get('media_type') or '-'} / {w.get('status') or '-'}"),
            ("播放量", f(w.get("plays") or 0)),
            ("完播率", p(w.get("finish_rate")) if w.get("finish_rate") is not None else "-"),
            ("5s 完播率", p(w.get("finish5_rate")) if w.get("finish5_rate") is not None else "-"),
            ("封面点击率", p(w.get("cover_ctr")) if w.get("cover_ctr") is not None else "-"),
            ("2s 跳出率", p(w.get("bounce2_rate")) if w.get("bounce2_rate") is not None else "-"),
            ("平均播放时长", f"{w['avg_duration']:.1f}s" if w.get("avg_duration") else "-"),
            ("点赞 / 评论", f"{f(w.get('likes') or 0)} / {f(w.get('comments') or 0)}"),
            ("收藏 / 分享", f"{f(w.get('collects') or 0)} / {f(w.get('shares') or 0)}"),
            ("主页访问", f(w.get("profile_visits") or 0)),
            ("粉丝增量", f(w.get("fans_delta") or 0)),
        ]
        top = tk.Toplevel(self)
        top.title("作品详情")
        top.configure(bg=ui.C["card"])
        top.transient(self.winfo_toplevel())
        top.resizable(False, False)
        box = tk.Frame(top, bg=ui.C["card"])
        box.pack(padx=20, pady=16)
        for i, (k, v) in enumerate(rows):
            tk.Label(box, text=k, font=ui.F["small"], bg=ui.C["card"],
                     fg=ui.C["muted"], anchor="w").grid(row=i, column=0, sticky="w", pady=2)
            tk.Label(box, text=str(v), font=ui.F["body"], bg=ui.C["card"],
                     fg=ui.C["text"], anchor="w", wraplength=330,
                     justify="left").grid(row=i, column=1, sticky="w", padx=(14, 0), pady=2)
        dash.Btn(top, "关闭", top.destroy, height=28).pack(pady=(0, 14))


def _open_scheduler(parent=None):
    try:
        os.startfile("taskschd.msc")
    except OSError:
        messagebox.showinfo("打开任务计划程序",
                            "开始菜单搜索「任务计划程序」即可，任务名「抖音数据同步」。",
                            parent=parent)


def make(master, ctx, app):
    return DouyinPage(master, ctx, app)
