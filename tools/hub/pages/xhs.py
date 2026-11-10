# -*- coding: utf-8 -*-
"""小红书页：账号绑定 + 自动导出 + 数据看板。

数据来自创作者中心后台（自动导出 5 张表，也兼容手动导入 xlsx），
解析结果存 `data/hub/xhs/<小红书号>.json`。

版式（2026-11-04 重做）：顶部只放标题 / 视图切换 / 账号 / 数据量 + 操作，
同步状态单独一条细卡；「概览」看指标卡、趋势、Top 6、近 30 天指标、分账号，
「明细」是一整张可排序可搜索的笔记表——不再把所有东西挤进一屏。
"""

# 侧栏入口（hub 启动时自动扫这个 META，不用改 hub.py）
META = {"icon": '✿', "title": '小红书', "sub": '笔记数据', "weight": 60}
import os
import queue
import threading
import tkinter as tk
import webbrowser
from tkinter import filedialog, messagebox, simpledialog, ttk

import dash
import ui
from core import privacy as pv
from core import xhs as xh
from core import xhs_auth as xa
from core import xhs_sync as xs

URL_NOTES = "https://creator.xiaohongshu.com/new/home"
URL_STATS = "https://creator.xiaohongshu.com/statistics/account/v2"

# 指标条里不展示的细项（数据仍保留在 summary 里，翻详情看得到）
_THIN = {"posts_video", "posts_figure", "fans_lost"}
# 指标条里的短名：格子窄，「平均观看时长 + 环比」会顶到格宽
_SHORT = {"avg_watch": "平均时长", "watch_total": "总时长", "follow_rate": "转粉率"}

# 明细表列：(key, 表头, 宽度, 对齐, 是否吃掉剩余宽度)
COLS = [
    ("title", "笔记", 360, "w", True),
    ("date", "日期", 96, "w", False),
    ("media", "体裁", 76, "w", False),
    ("exposure", "曝光", 72, "e", False),
    ("views", "观看", 72, "e", False),
    ("ctr", "点击率", 66, "e", False),
    ("likes", "点赞", 56, "e", False),
    ("collects", "收藏", 56, "e", False),
    ("fans", "涨粉", 56, "e", False),
]


class XhsPage(tk.Frame):
    def __init__(self, master, ctx, app):
        super().__init__(master, bg=ui.C["bg"])
        self.ctx, self.app = ctx, app
        self.handle = None          # None = 融合
        self.stats = None
        self._combo_map = []        # 下拉索引 -> handle
        self._query = ""            # 明细表搜索词
        self._table = None
        self._view = 0              # 0=概览 1=明细
        self._pills_on = True
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
        self.combo = ttk.Combobox(right, state="readonly", width=17, font=dash.f(9))
        self.combo.pack(side="left", padx=(0, 8), ipady=2)
        self.combo.bind("<<ComboboxSelected>>", self._on_pick)
        self._btn_add = dash.Btn(right, "＋ 账号", self.add_account)
        self._btn_add.pack(side="left", padx=(6, 0))
        dash.Btn(right, "导入", self.import_files, kind="soft").pack(
            side="left", padx=(6, 0))
        dash.Btn(right, "来源", self.show_guide).pack(side="left", padx=(6, 0))

        left = tk.Frame(bar, bg=ui.C["bg"])
        left.pack(side="left", fill="x", expand=True)
        tk.Label(left, text="小红书", font=dash.f(21, True), bg=ui.C["bg"],
                 fg=ui.C["text"]).pack(side="left")
        self.segment = dash.Segment(left, ["概览", "明细"], command=self._on_view,
                                    value=self._view)
        self.segment.pack(side="left", padx=(16, 0), pady=(4, 0))
        self.pill_acc = dash.Pill(left, "未绑定账号", fg=dash.MUTED, fill="#eef1f6")
        self.pill_acc.pack(side="left", padx=(12, 0), pady=(4, 0))
        self.pill_cnt = dash.Pill(left, "0 条笔记", fg=dash.ACCENT, fill=dash.ACCENT_SOFT)
        self.pill_cnt.pack(side="left", padx=(6, 0), pady=(4, 0))
        bar.bind("<Configure>", self._on_header_resize)

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

    def _on_view(self, i):
        self._view = i
        self._render_view()

    # ------------------------------------------------------------ 自动同步条
    def _build_sync_bar(self):
        card = dash.Card(self, padx=14, pady=9)
        card.pack(fill="x", padx=20, pady=(0, 10))
        row = tk.Frame(card.content, bg=ui.C["card"])
        row.pack(fill="x")

        right = tk.Frame(row, bg=ui.C["card"])
        right.pack(side="right")
        dash.Btn(right, "登录", self.login_dialog, height=28).pack(
            side="left", padx=(0, 6))
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

    def _acct_names(self):
        try:
            return [a.get("name") for a in xs.get_accounts(xs.load_cfg())]
        except Exception:                       # noqa: BLE001 — 只用来给日志打码
            return []

    def _refresh_sync_bar(self):
        text, color = self._sync_status(xs.load_cfg())
        self._set_sync_text(pv.show_text(text, self._acct_names()), color)

    def _set_sync_text(self, text, color=None):
        color = color or dash.MUTED
        try:
            self.sync_lbl.configure(text=text, fg=color)
            self._dot.itemconfigure(self._dot_id, fill=color)
        except tk.TclError:
            pass

    @staticmethod
    def _sync_status(cfg):
        logged = xs.logged_accounts(cfg)
        if not logged:
            return "未登录（点「登录」扫码一次）", ui.C["bad"]
        ids = "、".join(pv.show_handle(a.get("id")) for a in logged[:3])
        if len(logged) > 3:
            ids += f" 等 {len(logged)} 个"
        last = cfg.get("last") or {}
        if last.get("at"):
            when = str(last["at"])[5:] if len(str(last["at"])) > 5 else str(last["at"])
            if last.get("ok"):
                tail = f"上次 ✓ {when}（{last.get('files', 0)} 张表）"
            else:
                tail = f"上次 ✗ {when}：{(last.get('message') or '失败')[:28]}"
        else:
            tail = "还没跑过"
        if cfg.get("enabled"):
            return (f"{ids} · 每天 {cfg.get('time', '09:00')} · {tail}",
                    ui.C["ok"] if last.get("ok") else ui.C["muted"])
        return f"{ids} · 未开定时（点「定时」） · {tail}", ui.C["muted"]

    def _bg(self, work, done):
        """后台跑 work()，主线程回调 done(result)。"""
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

    def run_sync_now(self):
        cfg = xs.load_cfg()
        if not xs.logged_accounts(cfg):
            messagebox.showinfo("还没有登录",
                                "先点「登录」扫码一次，再自动导出。", parent=self)
            return
        self.sync_btn.set_enabled(False)
        self._set_sync_text("同步中：逐个账号拉 5 张表 → 各自入库（约 10~30 秒）…")

        def done(result):
            self.sync_btn.set_enabled(True)
            self.refresh()
            if result.get("ok"):
                per = "\n".join(
                    f"· {pv.show_handle(a['id'])}"
                    + (f"（{pv.show_name(a['name'])}）" if a.get("name") else "")
                    + f"：{a['files']} 张表"
                    for a in result.get("accounts") or [])
                extra = ("\n\n失败项：\n"
                         + pv.show_text("\n".join(result["errors"]), self._acct_names())
                         ) if result.get("errors") else ""
                messagebox.showinfo("同步完成", per + extra, parent=self)
            else:
                messagebox.showerror("同步失败", result.get("message") or "未知错误",
                                     parent=self)

        self._bg(xs.sync, done)

    # ------------------------------------------------------------ 账号
    def _accounts(self):
        return xh.load_accounts()

    def _sync_combo(self):
        accounts = self._accounts()
        labels, mapping = [], []
        if len(accounts) > 1:
            labels.append(f"全部账号 · 融合 {len(accounts)}")
            mapping.append(None)
        for a in accounts:
            name = a.get("name") or ""
            labels.append(pv.show_handle(a['handle'])
                          + (f" · {pv.show_name(name)}" if name else ""))
            mapping.append(a["handle"])
        self._combo_map = mapping
        self.combo["values"] = labels
        if mapping:
            self.combo.current(self._current_index())
            if not self.combo.winfo_manager():
                self.combo.pack(side="left", padx=(0, 8), ipady=2,
                                before=self._btn_add)
        else:
            self.combo.set("")
            self.combo.pack_forget()

    def _current_index(self):
        for i, h in enumerate(self._combo_map):
            if h == self.handle:
                return i
        return 0

    def _on_pick(self, _e=None):
        idx = self.combo.current()
        if 0 <= idx < len(self._combo_map):
            self.handle = self._combo_map[idx]
        self._query = ""
        self.refresh()

    def _handles(self):
        accounts = self._accounts()
        all_handles = [a["handle"] for a in accounts]
        if self.handle is None:
            return all_handles
        return [self.handle] if self.handle in all_handles else all_handles

    def add_account(self):
        handle = simpledialog.askstring(
            "添加小红书号", "小红书号（后台主页可见，纯数字或字母数字）：", parent=self)
        if not handle:
            return
        handle = handle.strip()
        if not handle:
            return
        name = simpledialog.askstring("备注名（可留空）", "给这个账号起个名字：",
                                      parent=self) or ""
        xh.add_account(handle, name or "")
        self.handle = handle
        self.refresh()
        messagebox.showinfo(
            "已添加",
            f"小红书号 {handle} 已绑定。\n\n"
            "下一步：点「登录」扫码，之后每天自动导出；或点「导入」把已有表导进来。",
            parent=self)

    def import_files(self):
        accounts = self._accounts()
        if not accounts:
            messagebox.showinfo("还没有账号",
                                "先点「＋ 账号」绑定一个小红书号，再导入数据。", parent=self)
            return
        if self.handle is None:
            messagebox.showinfo(
                "先选一个账号",
                "当前是「全部账号（融合）」视图，导入需要指定归属账号。\n"
                "请在右上角下拉里选中具体账号再导入。", parent=self)
            return

        paths = filedialog.askopenfilenames(
            parent=self, title="选择创作者中心导出的 Excel（可多选）",
            filetypes=[("Excel 表格", "*.xlsx *.xlsm"), ("全部文件", "*.*")])
        if not paths:
            return

        lines, ok = [], 0
        for p in paths:
            try:
                info = xh.import_file(p, self.handle)
                ok += 1
                parts = []
                added, updated = info["notes"]
                if added or updated:
                    parts.append(f"笔记明细：新增 {added} 条，更新 {updated} 条")
                if info["metrics"]:
                    parts.append(f"账户指标：{info['metrics']} 项")
                if info["trends"]:
                    parts.append(f"趋势：{info['trends']} 张"
                                 f"（新日期 {info['new_dates']} 天）")
                lines.append(f"✓ {os.path.basename(p)}\n    " +
                             ("；".join(parts) if parts else "认出了表，但没有数据行"))
            except Exception as e:                  # noqa: BLE001 — 单文件失败不影响其它
                lines.append(f"✗ {os.path.basename(p)}\n    {e}")
        self.refresh()
        messagebox.showinfo("导入结果" if ok else "导入失败", "\n\n".join(lines), parent=self)

    def show_guide(self):
        messagebox.showinfo(
            "数据从哪来",
            "小红书创作服务平台 → 两处导出：\n\n"
            "① 笔记列表明细（每条笔记的曝光/观看/互动）\n"
            f"   {URL_NOTES}\n"
            "   内容管理 → 笔记列表 → 导出\n\n"
            "② 近 30 天数据看板（观看/互动/涨粉/发布 四张表）\n"
            f"   {URL_STATS}\n"
            "   数据看板 → 每个模块右上角「导出」\n\n"
            "导出的 .xlsx 直接选「导入」，可一次多选：\n"
            "   · 表头有「笔记标题+观看量」→ 笔记明细\n"
            "   · 表头是「指标/数值」→ 账户指标\n"
            "   · 表头是「日期/数值」→ 按工作表名归到对应指标趋势\n\n"
            "更省事的是点「登录」扫码一次，之后每天自动导出。\n"
            "注意：导出表里没有小红书号，所以导入前要先选中归属账号。",
            parent=self)

    # ------------------------------------------------------------ 登录 / 定时
    def login_dialog(self):
        cfg = xs.load_cfg()
        win = tk.Toplevel(self)
        win.title("登录小红书")
        win.configure(bg=ui.C["bg"])
        win.transient(self.winfo_toplevel())
        win.geometry("760x520")

        pad = tk.Frame(win, bg=ui.C["bg"])
        pad.pack(fill="both", expand=True, padx=18, pady=14)

        tk.Label(pad, text="扫码登录（每个号各扫一次）", font=ui.F["h3"],
                 bg=ui.C["bg"], fg=ui.C["text"]).pack(anchor="w")
        tk.Label(
            pad,
            text=("点下面按钮会弹一个专用浏览器窗口（独立配置，不碰你平时的 Chrome）。\n"
                  "用小红书 App 扫码；工具会自己认出小红书号，把登录态加密后按号存，"
                  "不会串号。"),
            font=ui.F["small"], bg=ui.C["bg"], fg=ui.C["muted"],
            justify="left", anchor="w").pack(anchor="w", pady=(2, 8))

        top = tk.Frame(pad, bg=ui.C["bg"])
        top.pack(fill="x")
        login_btn = ttk.Button(top, text="打开浏览器扫码", style="Accent.TButton")
        login_btn.pack(side="left")
        ttk.Button(top, text="换个号", command=self.switch_account).pack(side="left", padx=6)
        tk.Label(top, text="手机号备注（可选）", font=ui.F["small"],
                 bg=ui.C["bg"], fg=ui.C["muted"]).pack(side="left", padx=(10, 4))
        var_phone = tk.StringVar()
        ttk.Entry(top, textvariable=var_phone, width=14).pack(side="left")
        status = tk.Label(pad, text=self._login_hint(cfg), font=ui.F["small"],
                          bg=ui.C["bg"], fg=ui.C["muted"], anchor="w")
        status.pack(anchor="w", pady=(6, 0))
        tk.Label(pad, text=self._key_line(), font=ui.F["small"], bg=ui.C["bg"],
                 fg=ui.C["muted"], anchor="w", justify="left").pack(anchor="w",
                                                                   pady=(2, 0))

        tk.Label(pad, text="已登录账号", font=ui.F["h4"], bg=ui.C["bg"],
                 fg=ui.C["text"]).pack(anchor="w", pady=(10, 2))
        acc_box = tk.Text(pad, height=4, font=ui.F["small"], wrap="word",
                          relief="solid", bd=1, bg="#f7f9fc", fg=ui.C["text"])
        acc_box.pack(fill="x")
        acc_box.configure(state="disabled")

        def fill_accounts():
            acc_box.configure(state="normal")
            acc_box.delete("1.0", "end")
            rows = xs.get_accounts(xs.load_cfg())
            if not rows:
                acc_box.insert("end", "（还没有）扫一次码就会出现在这里")
            for a in rows:
                bits = [pv.show_handle(a.get("id") or "未填号")]
                if a.get("name"):
                    bits.append(pv.show_name(a["name"]))
                if a.get("phone"):
                    bits.append("手机 " + pv.show_phone(a["phone"]))
                if a.get("at"):
                    bits.append("登录于 " + str(a["at"]))
                acc_box.insert("end", "· " + " · ".join(bits) + "\n")
            acc_box.configure(state="disabled")

        fill_accounts()

        def on_login():
            login_btn.state(["disabled"])
            status.configure(text="正在打开浏览器…", fg=ui.C["muted"])
            q = queue.Queue()
            phone = var_phone.get().strip()

            def work():
                try:
                    q.put(("done", xs.login(on_status=lambda s: q.put(("s", s)),
                                            phone=phone)))
                except Exception as e:                 # noqa: BLE001
                    q.put(("err", str(e)))

            threading.Thread(target=work, daemon=True).start()

            def poll():
                try:
                    kind, val = q.get_nowait()
                except queue.Empty:
                    win.after(300, poll)
                    return
                if kind == "s":
                    status.configure(text=pv.show_text(val, self._acct_names()))
                    win.after(250, poll)
                elif kind == "done":
                    login_btn.state(["!disabled"])
                    self._finish_login(win, status, val, phone, fill_accounts)
                else:
                    status.configure(text=pv.show_text(val, self._acct_names()),
                                     fg=ui.C["bad"])
                    login_btn.state(["!disabled"])

            win.after(300, poll)

        login_btn.configure(command=on_login)

        tk.Label(pad, text="──────────  或手动粘贴 Cookie（备选）  ──────────",
                 font=ui.F["small"], bg=ui.C["bg"], fg=ui.C["line"]).pack(pady=(12, 6))

        box = tk.Text(pad, height=5, font=ui.F["mono"], wrap="char",
                      relief="solid", bd=1, bg="white", fg=ui.C["text"])
        box.pack(fill="both", expand=True)

        def paste():
            try:
                data = win.clipboard_get()
            except tk.TclError:
                data = ""
            box.delete("1.0", "end")
            box.insert("end", data)

        def save_manual():
            cookie = xs.parse_cookie(box.get("1.0", "end"))
            if not cookie:
                messagebox.showinfo("没有内容", "先把 Cookie 粘进来。", parent=win)
                return
            xhs_id = simpledialog.askstring(
                "这是哪个号？", "小红书号（纯数字，后台可见）：", parent=win)
            if not xhs_id:
                return
            xhs_id = xhs_id.strip()
            name = simpledialog.askstring("昵称（可空）", "备注名：", parent=win) or ""
            xs.upsert_account(xhs_id, name, cookie, var_phone.get().strip())
            try:
                xhs.add_account(xhs_id, name)
            except Exception:                          # noqa: BLE001
                pass
            fill_accounts()
            self.refresh()
            messagebox.showinfo("已保存", f"已记到 {pv.show_handle(xhs_id)}。", parent=win)

        bar = tk.Frame(pad, bg=ui.C["bg"])
        bar.pack(fill="x", pady=(10, 0))
        ttk.Button(bar, text="从剪贴板粘贴", command=paste).pack(side="left")
        ttk.Button(bar, text="存到账号…", command=save_manual).pack(side="left", padx=6)
        ttk.Button(bar, text="关闭", command=win.destroy).pack(side="right")

    def switch_account(self):
        if not messagebox.askyesno(
                "换个号登录",
                "会清除专用浏览器里的当前登录（已保存的 token 不受影响），"
                "然后请扫另一个号的码。继续？", parent=self):
            return
        try:
            xs.logout_browser()
        except Exception as e:                          # noqa: BLE001
            messagebox.showerror("换号失败", str(e), parent=self)
            return
        messagebox.showinfo("已退出当前号",
                            "浏览器已回到登录页，点「打开浏览器扫码」扫另一个号。",
                            parent=self)

    def _finish_login(self, win, status, val, phone, fill_accounts):
        cookie = val.get("cookie") or ""
        xhs_id = str(val.get("id") or "").strip()
        if not xhs_id:
            xhs_id = simpledialog.askstring(
                "没认出小红书号", "请填这个号的小红书号（纯数字）：", parent=win) or ""
            xhs_id = xhs_id.strip()
            if not xhs_id:
                status.configure(text="已登录但没归到账号，再扫一次或手动粘贴",
                                 fg=ui.C["bad"])
                return
            xs.upsert_account(xhs_id, val.get("name") or "", cookie, phone)
            try:
                xhs.add_account(xhs_id, val.get("name") or "")
            except Exception:                          # noqa: BLE001
                pass
        name = val.get("name") or ""
        status.configure(
            text=f"已登录 {pv.show_handle(xhs_id)}"
                 + (f"（{pv.show_name(name)}）" if name else "")
                 + "，登录态已加密保存",
            fg=ui.C["ok"])
        fill_accounts()
        self.refresh()

    @staticmethod
    def _login_hint(cfg):
        logged = xs.logged_accounts(cfg)
        if not logged:
            if xa.local_key_missing():
                return "本机分片在，但缺登录态密钥（只能重新扫码）"
            return "当前未登录"
        return (f"已登录 {len(logged)} 个号："
                + "、".join(pv.show_handle(a.get("id")) for a in logged))

    @staticmethod
    def _key_line():
        """登录对话框里那行「登录态」说明：本机密钥状态。"""
        try:
            if xa.local_key_missing():
                return ("⚠ data/hub/xhs/auth.%s.json 在，但本机 sync.key 丢了："
                        "删掉这份分片后重新扫码（笔记数据不受影响）" % xa.machine_name())
            if xa.load_key():
                return ("登录态：本机密钥 ✓，Cookie 加密存在 data/hub/xhs/auth.%s.json"
                        "（同步进 git，但各机各管自己的，不要求共用）" % xa.machine_name())
            return ("登录态：首次扫码会自动生成本机密钥（data/hub/xhs/sync.key，不进 git；"
                    "各机各管自己的，丢了重新扫码）")
        except xa.AuthError as e:
            return f"登录态：{e}"

    def open_schedule(self):
        cfg = xs.load_cfg()
        logged = xs.logged_accounts(cfg)
        win = tk.Toplevel(self)
        win.title("自动导出 · 定时设置")
        win.configure(bg=ui.C["bg"])
        win.transient(self.winfo_toplevel())
        win.resizable(False, False)

        pad = tk.Frame(win, bg=ui.C["bg"])
        pad.pack(padx=22, pady=18)
        tk.Label(pad, text="每天自动同步所有已登录账号", font=ui.F["h3"],
                 bg=ui.C["bg"], fg=ui.C["text"]).grid(
                     row=0, column=0, columnspan=2, sticky="w")
        tk.Label(pad,
                 text="任务名「小红书数据导出」，注册后也能在 Windows 任务计划程序里改；"
                      "每个号各自落库，不会串号",
                 font=ui.F["small"], bg=ui.C["bg"], fg=ui.C["muted"]).grid(
                     row=1, column=0, columnspan=2, sticky="w", pady=(2, 12))

        var_time = tk.StringVar(value=cfg.get("time", "09:00"))
        var_days = tk.StringVar(value=str(cfg.get("data_days", 30)))
        var_note = tk.StringVar(value=str(cfg.get("note_days", 30)))
        var_on = tk.BooleanVar(value=bool(cfg.get("enabled")))

        rows = [
            ("每天时间", tk.Entry(pad, textvariable=var_time, width=10,
                                  font=ui.F["body"], relief="solid", bd=1)),
            ("数据天数", ttk.Spinbox(pad, from_=1, to=180, width=8,
                                 textvariable=var_days)),
            ("笔记回看天数", ttk.Spinbox(pad, from_=1, to=365, width=8,
                                 textvariable=var_note)),
        ]
        for i, (label, widget) in enumerate(rows, start=2):
            tk.Label(pad, text=label, font=ui.F["small"], bg=ui.C["bg"],
                     fg=ui.C["muted"]).grid(row=i, column=0, sticky="w",
                                            pady=4, padx=(0, 12))
            widget.grid(row=i, column=1, sticky="w", pady=4)
        tk.Checkbutton(pad, text="每天自动同步（写入 Windows 计划任务）",
                       variable=var_on, font=ui.F["small"], bg=ui.C["bg"],
                       activebackground=ui.C["bg"], anchor="w").grid(
                           row=5, column=0, columnspan=2, sticky="w", pady=(8, 2))

        if logged:
            acc_txt = "已登录：" + "、".join(
                pv.show_handle(a.get("id"))
                + (f"（{pv.show_name(a['name'])}）" if a.get("name") else "")
                for a in logged)
        else:
            acc_txt = "还没有登录账号：先去「登录」扫一次码"
        tk.Label(pad, text=acc_txt, font=ui.F["small"], bg=ui.C["bg"],
                 fg=ui.C["muted"], wraplength=360, justify="left").grid(
                     row=6, column=0, columnspan=2, sticky="w", pady=(2, 4))

        info = xs.task_info()
        if info.get("exists"):
            state = (f"当前任务：每天 {info.get('time')} · "
                     f"下次 {info.get('next') or '（未排期）'}")
        else:
            state = "当前没有注册定时任务"
        tk.Label(pad, text=state, font=ui.F["small"], bg=ui.C["bg"],
                 fg=ui.C["muted"]).grid(row=7, column=0, columnspan=2,
                                        sticky="w", pady=(2, 10))

        bar = tk.Frame(pad, bg=ui.C["bg"])
        bar.grid(row=8, column=0, columnspan=2, sticky="w")

        def save():
            try:
                at = xs.norm_time(var_time.get())
                if var_on.get() and not xs.logged_accounts():
                    raise xs.SyncError("还没有登录账号，先去「登录」扫码")
                new = xs.load_cfg()
                new.update(time=at, enabled=bool(var_on.get()),
                           data_days=max(1, int(var_days.get() or 30)),
                           note_days=max(1, int(var_note.get() or 30)))
                xs.save_cfg(new)
                if var_on.get():
                    got = xs.register_task(at)
                    messagebox.showinfo(
                        "已启用",
                        f"每天 {at} 自动同步。\n下次运行：{got.get('next') or '明天 ' + at}",
                        parent=win)
                else:
                    xs.unregister_task()
                    messagebox.showinfo("已停用", "定时任务已删除；「立即同步」照常可用。",
                                        parent=win)
                win.destroy()
                self.refresh()
            except xs.SyncError as e:
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
        win.title("自动导出日志")
        win.configure(bg=ui.C["card"])
        win.transient(self.winfo_toplevel())
        win.geometry("780x440")
        body = tk.Frame(win, bg=ui.C["card"])
        body.pack(fill="both", expand=True, padx=12, pady=(12, 0))
        box = tk.Text(body, wrap="none", font=ui.F["mono"], bg=ui.C["card"],
                      fg=ui.C["text"], relief="flat")
        sb = ttk.Scrollbar(body, orient="vertical", command=box.yview)
        box.configure(yscrollcommand=sb.set)
        box.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        lines = xs.read_log(200) or ["（还没有日志：点「立即同步」跑一次）"]
        names = [a.get("name") for a in xs.get_accounts(xs.load_cfg())]
        box.insert("end", pv.show_text("\n".join(lines), names))
        box.see("end")
        box.configure(state="disabled")

        bar = tk.Frame(win, bg=ui.C["card"])
        bar.pack(fill="x", padx=12, pady=10)
        ttk.Button(bar, text="打开数据目录",
                   command=lambda: os.startfile(str(xs.exports_dir()))
                   if xs.exports_dir().is_dir() else None).pack(side="left")
        ttk.Button(bar, text="关闭", command=win.destroy).pack(side="right")

    # ------------------------------------------------------------ 刷新
    def on_show(self, **kw):
        self.refresh()

    def refresh(self):
        accounts = self._accounts()
        if accounts and self.handle is None and len(accounts) == 1:
            self.handle = accounts[0]["handle"]
        if self.handle is not None and self.handle not in [a["handle"] for a in accounts]:
            self.handle = accounts[0]["handle"] if len(accounts) == 1 else None
        self._sync_combo()
        self._refresh_sync_bar()

        stats = xh.summarize(self._handles()) if accounts else None
        self.stats = stats
        has_data = bool(stats and (stats["count"] or stats["summary"]))
        if not accounts or not has_data:
            self.pill_acc.set_text("未绑定账号" if not accounts else
                                   f"{len(accounts)} 个账号", fg=dash.MUTED,
                                   fill="#eef1f6")
            self.pill_cnt.set_text("0 条笔记", fg=dash.MUTED, fill="#eef1f6")
        else:
            self.pill_acc.set_text("全部账号 · 融合" if self.handle is None else "单账号",
                                   fg=dash.ACCENT, fill=dash.ACCENT_SOFT)
            self.pill_cnt.set_text(f"{stats['count']} 条笔记",
                                   fg=dash.ACCENT, fill=dash.ACCENT_SOFT)
        self._render_view()

    def _render_view(self):
        for w in self.area.body.winfo_children():
            w.destroy()
        self.area.scroll_top()
        s = self.stats
        if not s or not (s["count"] or s["summary"]):
            self._build_empty(self._accounts())
        elif self._view == 0:
            self._build_overview(s)
        else:
            self._build_detail(s)
        self.area.bind_wheel()

    # ------------------------------------------------------------ 空状态引导
    def _build_empty(self, accounts):
        card = dash.Card(self.area.body, padx=28, pady=24)
        card.pack(fill="x")
        inner = card.content

        tk.Label(inner, text="还没有数据" if not accounts else "账号已绑定，还缺数据",
                 font=dash.f(17, True), bg=ui.C["card"], fg=ui.C["text"],
                 anchor="w").pack(fill="x")
        tk.Label(inner, text="扫码一次就每天自动导出：指标卡 / 趋势 / 近 30 天指标 / 笔记明细。",
                 font=dash.f(10), bg=ui.C["card"], fg=dash.MUTED,
                 anchor="w").pack(fill="x", pady=(6, 20))

        steps = [
            ("绑定小红书号",
             "右上角「＋ 账号」，填小红书号 + 备注名。"
             "可以绑多个，之后在下拉里切换或融合。"),
            ("登录一次（每个号扫一次）",
             "点「登录」弹专用浏览器，用小红书 App 扫码；登录态加密保存。"),
            ("自动导出 / 手动导入",
             "点「立即同步」自动拉 5 张表；也可以在「定时」里设成每天自动跑。"
             "手里已有的 xlsx 直接点「导入」，一次多选也行。"),
        ]
        for i, (title, desc) in enumerate(steps, start=1):
            self._step(inner, i, title, desc)

        links = tk.Frame(inner, bg=ui.C["card"])
        links.pack(anchor="w", pady=(2, 16))
        for label, url in (("打开笔记列表页 ↗", URL_NOTES),
                           ("打开数据看板 ↗", URL_STATS)):
            link = tk.Label(links, text=label, font=dash.f(9), bg=ui.C["card"],
                            fg=dash.ACCENT, anchor="w", cursor="hand2")
            link.pack(side="left", padx=(0, 18))
            link.bind("<Button-1>", lambda _e, u=url: webbrowser.open(u))

        btns = tk.Frame(inner, bg=ui.C["card"])
        btns.pack(anchor="w")
        dash.Btn(btns, "登录小红书", self.login_dialog, kind="primary").pack(side="left")
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

    # ------------------------------------------------------------ 概览
    def _build_overview(self, s):
        body = self.area.body
        notes = s["notes"]
        f_int, f_pct = s["fmt_int"], s["fmt_pct"]

        # ---- 指标卡（有笔记看笔记累计，只有 30 天表就看账户口径）
        if notes:
            views_total = s["views"]
            engage = s["engage_rate"]
            cards = [
                ("笔记", f_int(s["count"]),
                 "全部账号" if self.handle is None else "当前账号", None),
                ("总曝光", f_int(s["exposure"]), "笔记累计", None),
                ("总观看", f_int(views_total), f"近 7 天 {f_int(s['views_last7'])}",
                 s["trend"]),
                ("平均点击率", f_pct(s["ctr"]), "按曝光加权", None),
                ("互动率", f_pct(engage, 2), "赞评藏转 / 观看", None),
            ]
        else:
            sm = s["summary"]
            views_total = sm.get("views") or 0
            engage = (((sm.get("likes") or 0) + (sm.get("comments") or 0)
                       + (sm.get("collects") or 0) + (sm.get("shares") or 0))
                      / views_total) if views_total else 0.0
            cards = [
                ("近 30 天发布", f_int(sm.get("posts") or 0), "账户口径", None),
                ("曝光", f_int(sm.get("exposure") or 0), "近 30 天", None),
                ("观看", f_int(views_total), "近 30 天", None),
                ("封面点击率", f_pct(sm.get("cover_ctr")), "近 30 天", None),
                ("互动率", f_pct(engage, 2), "赞评藏转 / 观看", None),
            ]
        tiles = tk.Frame(body, bg=ui.C["bg"])
        tiles.pack(fill="x")
        for i, (label, value, note, delta) in enumerate(cards):
            tiles.columnconfigure(i, weight=1, uniform="t")
            tile = dash.StatTile(tiles, label, value, note=note, delta=delta)
            tile.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else 10, 0))

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
        extra.append(f"近 7 天 {f_int(s['views_last7'])}")
        dash.section(c1.content, "每日观看", " · ".join(extra))
        chart = dash.LineChart(c1.content, height=186)
        chart.pack(fill="x", pady=(2, 0))
        chart.set_series([(d["date"], d.get("views") or 0) for d in s["days"]])

        c2 = dash.Card(mid)
        c2.grid(row=0, column=1, sticky="nsew")
        bar_hint = "双击榜单看完整指标" if notes else ""
        head = dash.section(c2.content, "观看 Top 6", bar_hint)
        bars = dash.BarList(c2.content, height=186, rows=6)
        bars.pack(fill="x", pady=(2, 0))
        top = s["top"][:6]

        def hover(title):
            if head.hint is None:
                return
            text = bar_hint if not title else (
                title if len(title) <= 30 else title[:29] + "…")
            head.hint.configure(text=text, fg=dash.FAINT if not title else dash.MUTED)

        bars.set_rows([(n.get("date") or n.get("published_at") or "",
                        n.get("views") or 0, n.get("title") or "") for n in top],
                      on_click=lambda i: self._show_detail(top[i]) if i < len(top) else None,
                      on_hover=hover)

        # ---- 近 30 天指标
        if s["summary"]:
            self._build_summary(body, s)

        # ---- 分账号（融合视图才显示）
        accounts = self._accounts()
        if self.handle is None and len(accounts) > 1:
            self._build_accounts(body, s)

    # ------------------------------------------------------------ 近 30 天指标
    def _build_summary(self, body, s):
        card = dash.Card(body, pady=14)
        card.pack(fill="x", pady=(dash.GAP, 0))
        win = s["window"]
        right = f"{win[0]} ~ {win[1]}" if win and win[0] else ""
        dash.section(card.content, "近 30 天账户指标",
                     (right + " · " if right else "") + "环比 = 与前 30 天相比",
                     pady=(0, 12))

        keys = [k for k in s["metric_order"] if k not in _THIN]
        cols = 5
        grid = tk.Frame(card.content, bg=ui.C["card"])
        grid.pack(fill="x")
        for c in range(cols):
            grid.columnconfigure(c, weight=1, uniform="m")
        for i, key in enumerate(keys):
            r, c = divmod(i, cols)
            box = tk.Frame(grid, bg="#f8fafd")
            box.grid(row=r, column=c, sticky="nsew",
                     padx=(0 if c == 0 else 8, 0), pady=(0 if r == 0 else 8, 0))
            inner = tk.Frame(box, bg="#f8fafd")
            inner.pack(fill="x", padx=12, pady=9)
            tk.Label(inner, text=s["fmt_metric"](key, s["summary"].get(key)),
                     font=dash.f(15, True), bg="#f8fafd", fg=ui.C["text"],
                     anchor="w").pack(fill="x")
            line = tk.Frame(inner, bg="#f8fafd")
            line.pack(fill="x", pady=(2, 0))
            tk.Label(line, text=_SHORT.get(key, xh.METRICS[key]), font=dash.f(9),
                     bg="#f8fafd", fg=dash.MUTED).pack(side="left")
            d = s["delta"].get(key)
            if d is not None:
                good = (d >= 0) if key != "fans_lost" else (d <= 0)
                tk.Label(line, text=f"{'↑' if d >= 0 else '↓'}{abs(d) * 100:.0f}%",
                         font=dash.f(9, True), bg="#f8fafd",
                         fg=dash.OK if good else dash.BAD).pack(side="left", padx=(6, 0))
        # 最后一行不满时补空，保证格子宽度一致
        for i in range(len(keys), ((len(keys) + cols - 1) // cols) * cols):
            r, c = divmod(i, cols)
            tk.Frame(grid, bg=ui.C["card"]).grid(row=r, column=c, sticky="nsew",
                                                 padx=(0 if c == 0 else 8, 0),
                                                 pady=(0 if r == 0 else 8, 0))

    # ------------------------------------------------------------ 分账号卡
    def _build_accounts(self, body, s):
        card = dash.Card(body, pady=12)
        card.pack(fill="x", pady=(dash.GAP, 0))
        dash.section(card.content, "分账号表现", "占比 = 该号观看 / 合计", pady=(0, 8))
        total = (s["views"] or 0) or 1
        rows = []
        for a in self._accounts():
            handle = a["handle"]
            d = xh.load(handle)
            notes = d.get("notes") or []
            views = sum(n.get("views") or 0 for n in notes)
            fans = sum(n.get("fans") or 0 for n in notes)
            pairs = [(n.get("cover_ctr"), n.get("exposure") or 0) for n in notes
                     if isinstance(n.get("cover_ctr"), (int, float))
                     and (n.get("exposure") or 0) > 0]
            denom = sum(p for _, p in pairs)
            ctr = (sum(r * p for r, p in pairs) / denom) if denom else None
            rows.append({"name": pv.show_handle(handle),
                         "sub": pv.show_name(a.get("name") or ""),
                         "cells": [str(len(notes)), s["fmt_int"](views),
                                   f"{views / total * 100:.0f}%",
                                   s["fmt_pct"](ctr) if ctr is not None else "-",
                                   s["fmt_int"](fans)]})
        rows.sort(key=lambda r: -int(r["cells"][1].replace(",", "") or 0))
        table = dash.AccountTable(card.content, cols=("笔记", "观看", "占比", "点击率", "涨粉"))
        table.pack(fill="x", pady=(0, 4))
        table.set_rows(rows)

    # ------------------------------------------------------------ 明细
    def _build_detail(self, s):
        card = dash.Card(self.area.body, pady=12)
        card.pack(fill="x")
        hint = " · ".join(f"{k} {v}" for k, v in sorted(s["media"].items(),
                                                        key=lambda kv: -kv[1]))
        head = dash.section(card.content, "笔记明细", hint, pady=(0, 10))

        def right(parent):
            dash.Search(parent, placeholder="搜笔记标题…",
                        on_change=self._on_search).pack(side="right")

        right(head)

        if not s["notes"]:
            tk.Label(card.content, text="只导入了账户指标；再导入「笔记列表明细」就能看单条数据。",
                     font=dash.f(10), bg=ui.C["card"], fg=dash.MUTED,
                     anchor="w").pack(fill="x", pady=(6, 10))
            return

        cols = list(COLS)
        if self.handle is None:
            cols.append(("handle", "账号", 112, "w", False))
        self._table = dash.DataTable(card.content, cols,
                                     height=min(14, max(8, s["count"])),
                                     on_double=lambda row: self._show_detail(row["_obj"]),
                                     ellipsis=("title",))
        self._table.pack(fill="x", pady=(2, 0))
        self._fill_table()

    def _rows(self):
        s, f_int, f_pct = self.stats, self.stats["fmt_int"], self.stats["fmt_pct"]
        rows = []
        for n in s["notes"]:
            date = n.get("date") or ""
            title = n.get("title") or "(无标题)"
            rows.append({
                "_obj": n,
                "handle": (pv.show_handle(n.get("_handle") or ""),
                           n.get("_handle") or ""),
                "date": (date, date),
                "media": (n.get("media_type") or "-", n.get("media_type") or ""),
                "exposure": (f_int(n.get("exposure") or 0), n.get("exposure") or 0),
                "views": (f_int(n.get("views") or 0), n.get("views") or 0),
                "ctr": (f_pct(n.get("cover_ctr")) if n.get("cover_ctr") is not None else "-",
                        n.get("cover_ctr") if n.get("cover_ctr") is not None else -1),
                "likes": (f_int(n.get("likes") or 0), n.get("likes") or 0),
                "collects": (f_int(n.get("collects") or 0), n.get("collects") or 0),
                "fans": (f_int(n.get("fans") or 0), n.get("fans") or 0),
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

    # ------------------------------------------------------------ 笔记详情
    def _show_detail(self, n):
        if not n:
            return
        f = self.stats["fmt_int"]
        p = self.stats["fmt_pct"]
        rows = [
            ("笔记", n.get("title") or "(无标题)"),
            ("发布时间", n.get("published_at") or "-"),
            ("体裁", n.get("media_type") or "-"),
            ("曝光", f(n.get("exposure") or 0)),
            ("观看量", f(n.get("views") or 0)),
            ("封面点击率", p(n.get("cover_ctr")) if n.get("cover_ctr") is not None else "-"),
            ("点赞 / 评论", f"{f(n.get('likes') or 0)} / {f(n.get('comments') or 0)}"),
            ("收藏 / 分享", f"{f(n.get('collects') or 0)} / {f(n.get('shares') or 0)}"),
            ("涨粉", f(n.get("fans") or 0)),
            ("人均观看时长", self.stats["fmt_sec"](n.get("avg_watch")) if n.get("avg_watch") else "-"),
            ("弹幕", f(n.get("danmaku") or 0)),
        ]
        top = tk.Toplevel(self)
        top.title("笔记详情")
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
    """打开 Windows 任务计划程序（看/改「小红书数据导出」任务）。"""
    try:
        os.startfile("taskschd.msc")
    except OSError as e:
        messagebox.showerror("打不开任务计划程序", str(e), parent=parent)


def make(master, ctx, app):
    return XhsPage(master, ctx, app)
