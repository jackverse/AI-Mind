# -*- coding: utf-8 -*-
"""邮件提醒页：SMTP 配置 + 测试发信 + 立即发提醒 + 每日定时（Windows 计划任务）。

发信走 core/mailer（标准库 smtplib），正文由 core/reminder 从 TODO.md /
daily-log.md 现场生成；授权码用 DPAPI 加密存在 data/hub/mail.json。
"""
import re
import threading
import time
import tkinter as tk
import webbrowser
from datetime import datetime
from tkinter import messagebox, ttk

import ui
from core import autotask, mailer, reminder
from core import privacy as pv

CODE_FULL = re.compile(r"[A-Za-z0-9]{12,24}")
CODE_TOKEN = re.compile(r"(?<![A-Za-z0-9])([A-Za-z0-9]{16})(?![A-Za-z0-9])")


def _join(addrs):
    return ", ".join(addrs or [])


class MailPage(tk.Frame):
    def __init__(self, master, ctx, app):
        super().__init__(master, bg=ui.C["bg"])
        self.ctx, self.app = ctx, app
        self.cfg = mailer.load()
        self._busy = False
        self._gen_body = ""
        self._watch_id = None
        self._last_code = ""
        self._build_scroller()
        self._build()
        self._fill(self.cfg)
        self._regen(silent=True)
        self.canvas.bind_all("<MouseWheel>", self._on_wheel)
        self.bind("<Destroy>", self._on_destroy)

    # ---------------------------------------------------------------- 滚动容器
    def _build_scroller(self):
        self.canvas = tk.Canvas(self, bg=ui.C["bg"], bd=0, highlightthickness=0)
        self.vbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.vbar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.vbar.pack(side="right", fill="y")

        self.body = tk.Frame(self.canvas, bg=ui.C["bg"])
        self._win = self.canvas.create_window((0, 0), window=self.body, anchor="nw")
        self._bar = True
        self.body.bind("<Configure>", self._on_body)
        self.canvas.bind("<Configure>", self._on_canvas)

    def _on_canvas(self, event):
        self.canvas.itemconfigure(self._win, width=event.width)
        self._sync_scrollbar()

    def _on_body(self, _event=None):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        self._sync_scrollbar()

    def _sync_scrollbar(self):
        need = self.body.winfo_reqheight() > self.canvas.winfo_height()
        if need == self._bar:
            return
        self._bar = need
        if need:
            self.vbar.pack(side="right", fill="y")
        else:
            self.vbar.pack_forget()

    def _on_wheel(self, event):
        try:
            if not self.winfo_exists() or not self.winfo_ismapped():
                return
            self.canvas.yview_scroll(-int(event.delta / 120), "units")
        except tk.TclError:
            return

    # ---------------------------------------------------------------- 小部件
    def _card(self, title, desc=""):
        card = tk.Frame(self.body, bg=ui.C["card"], highlightthickness=1,
                        highlightbackground=ui.C["line"])
        card.pack(fill="x", padx=24, pady=(0, 10))
        tk.Label(card, text=title, font=(ui.UI, 10, "bold"), bg=ui.C["card"],
                 fg=ui.C["text"]).pack(anchor="w", padx=18, pady=(12, 2))
        if desc:
            tk.Label(card, text=desc, font=ui.F["small"], bg=ui.C["card"],
                     fg=ui.C["muted"], justify="left", wraplength=860).pack(
                         anchor="w", padx=18, pady=(0, 6))
        return card

    def _label(self, parent, text, width=9):
        lbl = tk.Label(parent, text=text, font=ui.F["small"], bg=ui.C["card"],
                       fg=ui.C["muted"], width=width, anchor="w")
        return lbl

    def _status(self, parent):
        lbl = tk.Label(parent, text="", font=ui.F["small"], bg=ui.C["card"],
                       fg=ui.C["muted"], anchor="w", justify="left",
                       wraplength=820)
        return lbl

    def _set_status(self, lbl, text, color=None):
        try:
            lbl.configure(text=text, fg=color or ui.C["muted"])
        except tk.TclError:
            pass

    # ---------------------------------------------------------------- 页面
    def _build(self):
        bar = tk.Frame(self.body, bg=ui.C["bg"])
        bar.pack(fill="x", padx=24, pady=(14, 8))
        tk.Label(bar, text="邮件提醒", font=(ui.UI, 18, "bold"), bg=ui.C["bg"],
                 fg=ui.C["text"]).pack(side="left")
        self.head_note = tk.Label(bar, text="", font=ui.F["small"],
                                  bg=ui.C["bg"], fg=ui.C["muted"], anchor="w")
        self.head_note.pack(side="left", padx=10, pady=(8, 0))

        self._build_server()
        self._build_send()
        self._build_daily()
        self._build_help()
        tk.Frame(self.body, bg=ui.C["bg"], height=6).pack()

    # ---- 发件服务器
    def _build_server(self):
        card = self._card("发件服务器",
                          "QQ/163 等个人邮箱：先去网页版开启 SMTP 服务，拿一串"
                          "「授权码」填在这里（不是登录密码）。")
        form = tk.Frame(card, bg=ui.C["card"])
        form.pack(fill="x", padx=18)
        form.columnconfigure(1, weight=1)

        # 预设
        self._label(form, "快速填写").grid(row=0, column=0, sticky="w", pady=3)
        line = tk.Frame(form, bg=ui.C["card"])
        line.grid(row=0, column=1, sticky="ew", pady=3)
        self.preset_var = tk.StringVar(value=mailer.PRESETS[0]["label"])
        preset = ttk.Combobox(line, textvariable=self.preset_var, state="readonly",
                              width=16,
                              values=[p["label"] for p in mailer.PRESETS])
        preset.pack(side="left")
        preset.bind("<<ComboboxSelected>>", lambda _e: self._apply_preset())
        tk.Label(line, text="选一个常见邮箱，自动填服务器/端口/加密",
                 font=ui.F["small"], bg=ui.C["card"], fg=ui.C["muted"]).pack(
                     side="left", padx=8)

        # 服务器 + 端口 + 加密
        self._label(form, "服务器").grid(row=1, column=0, sticky="w", pady=3)
        line = tk.Frame(form, bg=ui.C["card"])
        line.grid(row=1, column=1, sticky="ew", pady=3)
        self.host_var = tk.StringVar()
        ttk.Entry(line, textvariable=self.host_var, width=26).pack(side="left")
        tk.Label(line, text="端口", font=ui.F["small"], bg=ui.C["card"],
                 fg=ui.C["muted"]).pack(side="left", padx=(12, 4))
        self.port_var = tk.StringVar(value="465")
        tk.Spinbox(line, from_=1, to=65535, width=6, textvariable=self.port_var,
                   relief="solid", bd=1).pack(side="left")
        tk.Label(line, text="加密", font=ui.F["small"], bg=ui.C["card"],
                 fg=ui.C["muted"]).pack(side="left", padx=(12, 4))
        self.sec_var = tk.StringVar(value=mailer.SECURITY_LABEL["ssl"])
        sec = ttk.Combobox(line, textvariable=self.sec_var, state="readonly",
                           width=20,
                           values=[mailer.SECURITY_LABEL[k] for k in mailer.SECURITY])
        sec.pack(side="left")

        # 发件邮箱（离开输入框时按域名自动选服务器）
        self._label(form, "发件邮箱").grid(row=2, column=0, sticky="w", pady=3)
        self.user_var = tk.StringVar()
        self.user_entry = ttk.Entry(form, textvariable=self.user_var)
        self.user_entry.grid(row=2, column=1, sticky="ew", pady=3)
        self.user_entry.bind("<FocusOut>", self._on_user_leave)

        # 授权码
        self._label(form, "授权码").grid(row=3, column=0, sticky="w", pady=3)
        line = tk.Frame(form, bg=ui.C["card"])
        line.grid(row=3, column=1, sticky="ew", pady=3)
        self.pw_var = tk.StringVar()
        self.pw_entry = ttk.Entry(line, textvariable=self.pw_var, show="•")
        self.pw_entry.pack(side="left", fill="x", expand=True)
        self.show_pw = tk.BooleanVar(value=False)
        tk.Checkbutton(line, text="显示", variable=self.show_pw,
                       command=self._toggle_pw, bg=ui.C["card"],
                       activebackground=ui.C["card"]).pack(side="left", padx=6)
        self.code_btn = ttk.Button(line, text="获取授权码…",
                                   command=self._get_code)
        self.code_btn.pack(side="left")

        # 收件邮箱
        self._label(form, "收件邮箱").grid(row=4, column=0, sticky="w", pady=3)
        line = tk.Frame(form, bg=ui.C["card"])
        line.grid(row=4, column=1, sticky="ew", pady=3)
        self.to_var = tk.StringVar()
        ttk.Entry(line, textvariable=self.to_var).pack(side="left", fill="x",
                                                       expand=True)
        tk.Label(line, text="留空=发给自己；多个用逗号隔开", font=ui.F["small"],
                 bg=ui.C["card"], fg=ui.C["muted"]).pack(side="left", padx=8)

        # 发件人名称
        self._label(form, "发件人").grid(row=5, column=0, sticky="w", pady=3)
        self.name_var = tk.StringVar()
        ttk.Entry(form, textvariable=self.name_var, width=26).grid(
            row=5, column=1, sticky="w", pady=3)

        # 取授权码的引导面板（点「获取授权码」才展开）
        self.guide = tk.Frame(card, bg="#f3f7ff", highlightthickness=1,
                              highlightbackground="#d6e2f7")
        ghead = tk.Frame(self.guide, bg="#f3f7ff")
        ghead.pack(fill="x", padx=12, pady=(10, 2))
        self.guide_title = tk.Label(ghead, text="", font=(ui.UI, 9, "bold"),
                                    bg="#f3f7ff", fg=ui.C["text"], anchor="w")
        self.guide_title.pack(side="left")
        ttk.Button(ghead, text="再次打开页面",
                   command=self._open_code_page).pack(side="right")
        ttk.Button(ghead, text="取消等待",
                   command=self._stop_watch_ui).pack(side="right", padx=6)
        self.guide_steps = tk.Label(self.guide, text="", font=ui.F["small"],
                                    bg="#f3f7ff", fg=ui.C["text"],
                                    justify="left", anchor="w", wraplength=840)
        self.guide_steps.pack(fill="x", padx=12, pady=(2, 4))
        self.guide_status = tk.Label(self.guide, text="", font=ui.F["small"],
                                     bg="#f3f7ff", fg=ui.C["muted"],
                                     justify="left", anchor="w", wraplength=840)
        self.guide_status.pack(fill="x", padx=12, pady=(0, 10))

        self.server_btns = btns = tk.Frame(card, bg=ui.C["card"])
        btns.pack(fill="x", padx=18, pady=(8, 4))
        self.save_btn = ttk.Button(btns, text="保存配置", command=self._save_clicked)
        self.save_btn.pack(side="left")
        self.test_btn = ttk.Button(btns, text="发送测试邮件", style="Accent.TButton",
                                   command=self._test)
        self.test_btn.pack(side="left", padx=8)
        tk.Label(btns, text="授权码用 Windows DPAPI 加密保存在 data/hub/mail.json",
                 font=ui.F["small"], bg=ui.C["card"], fg=ui.C["muted"]).pack(
                     side="left", padx=8)
        self.cfg_status = self._status(card)
        self.cfg_status.pack(fill="x", padx=18, pady=(0, 12))

    # ---- 立即发送
    def _build_send(self):
        card = self._card("立即发送提醒",
                          "正文由 TODO.md 的未完成项 + daily-log.md 的打卡情况"
                          "现场生成，可以改完再发。")
        row = tk.Frame(card, bg=ui.C["card"])
        row.pack(fill="x", padx=18, pady=(0, 6))
        self._label(row, "主题", width=5).pack(side="left")
        self.subject_var = tk.StringVar()
        ttk.Entry(row, textvariable=self.subject_var).pack(
            side="left", fill="x", expand=True)

        box = tk.Frame(card, bg=ui.C["card"])
        box.pack(fill="x", padx=18)
        self.body_text = tk.Text(box, height=13, wrap="word", relief="solid",
                                 bd=1, font=ui.F["body"], bg="#f8fafd",
                                 fg=ui.C["text"], padx=10, pady=8)
        sb = ttk.Scrollbar(box, orient="vertical", command=self.body_text.yview)
        self.body_text.configure(yscrollcommand=sb.set)
        self.body_text.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        btns = tk.Frame(card, bg=ui.C["card"])
        btns.pack(fill="x", padx=18, pady=(8, 4))
        self.regen_btn = ttk.Button(btns, text="重新生成摘要",
                                    command=self._regen)
        self.regen_btn.pack(side="left")
        self.send_btn = ttk.Button(btns, text="发送到邮箱", style="Accent.TButton",
                                   command=self._send_now)
        self.send_btn.pack(side="left", padx=8)
        self.send_status = self._status(card)
        self.send_status.pack(fill="x", padx=18, pady=(0, 12))

    # ---- 每日提醒
    def _build_daily(self):
        card = self._card("每日提醒",
                          "用 Windows 自带的任务计划：每天到点运行 hub.exe --remind，"
                          "不需要 hub 开着，也不弹窗口。")
        row = tk.Frame(card, bg=ui.C["card"])
        row.pack(fill="x", padx=18, pady=(2, 4))
        self.daily_var = tk.BooleanVar(value=False)
        tk.Checkbutton(row, text="启用", variable=self.daily_var,
                       bg=ui.C["card"], activebackground=ui.C["card"]).pack(
                           side="left")
        tk.Label(row, text="每天", font=ui.F["small"], bg=ui.C["card"],
                 fg=ui.C["muted"]).pack(side="left", padx=(8, 4))
        self.time_var = tk.StringVar(value="08:30")
        ttk.Entry(row, textvariable=self.time_var, width=8).pack(side="left")
        tk.Label(row, text="发送（24 小时制，例如 08:30）", font=ui.F["small"],
                 bg=ui.C["card"], fg=ui.C["muted"]).pack(side="left", padx=6)
        tk.Label(card, text="只勾「启用」不会自己发：要生效必须点下面的"
                            "「保存并安装计划任务」。", font=ui.F["small"],
                 bg=ui.C["card"], fg=ui.C["bad"], anchor="w").pack(
                     fill="x", padx=18)

        btns = tk.Frame(card, bg=ui.C["card"])
        btns.pack(fill="x", padx=18, pady=(6, 4))
        self.install_btn = ttk.Button(btns, text="保存并安装计划任务",
                                      command=self._install_task)
        self.install_btn.pack(side="left")
        self.remove_btn = ttk.Button(btns, text="移除计划任务",
                                     command=self._remove_task)
        self.remove_btn.pack(side="left", padx=8)
        self.task_status = self._status(card)
        self.task_status.pack(fill="x", padx=18, pady=(0, 12))

    # ---- 帮助
    def _build_help(self):
        card = self._card("授权码怎么拿 / 常见报错")
        text = (
            "最省事的路径：点「授权码」右边的「获取授权码…」→ 自动打开对应邮箱的"
            "设置页 → 按弹出的步骤生成 → 点页面上的「复制」→ 回到 hub，"
            "授权码会自动填进输入框（不用手动粘贴）。\n\n"
            "QQ 邮箱：设置 → 账户 → 开启「POP3/IMAP/SMTP 服务」→ 发短信验证 → 得到 16 位授权码。\n"
            "163 / 126：设置 → POP3/SMTP/IMAP → 开启服务 → 新增授权密码。\n"
            "Gmail：要开两步验证再生成「应用专用密码」；国内网络直连 smtp.gmail.com 不通（实测），不建议用。\n\n"
            "535 登录被拒 = 授权码错 / SMTP 服务没开 / 填的是登录密码。\n"
            "连接超时 = 端口被网络拦了，换 465 + SSL（587 在国内部分网络会断）。\n"
            "TLS 握手失败 = 加密方式和端口不匹配（465→SSL，587→STARTTLS）。\n\n"
            "配置：data/hub/mail.json（授权码 DPAPI 加密）　日志：data/hub/mail.log")
        tk.Label(card, text=text, font=ui.F["small"], bg=ui.C["card"],
                 fg=ui.C["muted"], justify="left", wraplength=880).pack(
                     anchor="w", padx=18, pady=(0, 14))

    # ---------------------------------------------------------------- 数据
    def _fill(self, cfg):
        self.cfg = cfg
        self.host_var.set(cfg["host"])
        self.port_var.set(str(cfg["port"]))
        self.sec_var.set(mailer.SECURITY_LABEL.get(cfg["security"],
                                                   mailer.SECURITY_LABEL["ssl"]))
        self.preset_var.set(next((p["label"] for p in mailer.PRESETS
                                  if p["host"] and p["host"] == cfg["host"]),
                                 "自定义"))
        self.user_var.set(cfg["user"])
        self.to_var.set(_join(cfg["to"]))
        self.name_var.set(cfg["from_name"])
        self.daily_var.set(cfg["daily"]["enabled"])
        self.time_var.set(cfg["daily"]["time"])
        self.pw_var.set("")
        self._refresh_head()

    def _collect(self):
        cfg = dict(self.cfg)
        cfg["host"] = self.host_var.get().strip()
        try:
            cfg["port"] = int(self.port_var.get() or 0)
        except ValueError:
            cfg["port"] = 0
        cfg["security"] = next((k for k, v in mailer.SECURITY_LABEL.items()
                                if v == self.sec_var.get()), "ssl")
        cfg["user"] = self.user_var.get().strip()
        cfg["from_name"] = self.name_var.get().strip() or "第二大脑"
        tos = [t.strip() for t in self.to_var.get().replace("；", ",")
               .replace(";", ",").split(",") if t.strip()]
        cfg["to"] = tos or ([cfg["user"]] if cfg["user"] else [])
        cfg["daily"] = {"enabled": bool(self.daily_var.get()),
                        "time": self.time_var.get().strip() or "08:30",
                        "last_sent": self.cfg["daily"].get("last_sent", "")}
        return cfg

    def _save(self, quiet=False):
        cfg = self._collect()
        if not cfg["host"]:
            self._set_status(self.cfg_status, "服务器地址不能为空", ui.C["bad"])
            return None
        if cfg["port"] <= 0:
            self._set_status(self.cfg_status, "端口不对", ui.C["bad"])
            return None
        if cfg["user"] and "@" not in cfg["user"]:
            self._set_status(self.cfg_status, "发件邮箱格式不对", ui.C["bad"])
            return None
        plain = self.pw_var.get().strip()
        if plain:                                   # 留空 = 不改已有授权码
            protected = mailer.set_password(cfg, plain)
            if not protected:
                self._set_status(self.cfg_status,
                                 "DPAPI 不可用，授权码只能明文保存", ui.C["bad"])
        try:
            self.cfg = mailer.save(cfg)
        except mailer.MailError as e:
            self._set_status(self.cfg_status, str(e), ui.C["bad"])
            return None
        if not quiet:
            self._set_status(self.cfg_status, "已保存", ui.C["ok"])
        self._refresh_head()
        return self.cfg

    def _save_clicked(self):
        if self._save():
            self.pw_var.set("")

    def _refresh_head(self):
        reason = mailer.readiness(self.cfg)
        if reason:
            self.head_note.configure(text="未就绪：" + reason, fg=ui.C["bad"])
        else:
            self.head_note.configure(
                text="已就绪，收件人：" + pv.show_text(_join(self.cfg["to"])),
                fg=ui.C["ok"])

    # ---------------------------------------------------------------- 交互
    def _apply_preset(self):
        preset = self._current_preset()
        if preset["host"]:
            self.host_var.set(preset["host"])
            self.port_var.set(str(preset["port"]))
            self.sec_var.set(mailer.SECURITY_LABEL[preset["security"]])
        self._stop_watch()
        if self.guide.winfo_manager():
            self._show_guide(preset)

    def _toggle_pw(self):
        self.pw_entry.configure(show="" if self.show_pw.get() else "•")

    # ---------------------------------------------------------------- 授权码向导
    def _current_preset(self):
        return mailer.preset_for(self.preset_var.get())

    def _get_code(self):
        preset = self._current_preset()
        self._show_guide(preset)
        if not preset["url"]:
            self._guide_status(
                "自定义邮箱没有固定页面：先问服务商要 SMTP 地址和端口，"
                "再在邮箱后台开启 SMTP / 生成授权码。", ui.C["bad"])
            return
        self._open_code_page()

    def _open_code_page(self):
        preset = self._current_preset()
        if not preset["url"]:
            return
        webbrowser.open(preset["url"])
        self._guide_status(
            f"已打开 {preset['url']} —— 按上面步骤生成授权码，点「复制」后"
            "这里会自动填上（等待中…）", ui.C["accent"])
        self._start_watch()

    def _show_guide(self, preset):
        self.guide_title.configure(text=f"怎么拿「{preset['label']}」授权码")
        self.guide_steps.configure(text="\n".join(
            f"{i}. {s}" for i, s in enumerate(preset["steps"], 1)))
        if not self.guide.winfo_manager():
            self.guide.pack(fill="x", padx=18, pady=(4, 0),
                            before=self.server_btns)
        self._on_body()

    def _guide_status(self, text, color=None):
        try:
            self.guide_status.configure(text=text, fg=color or ui.C["muted"])
        except tk.TclError:
            pass

    def _start_watch(self):
        """盯着剪贴板：用户从邮箱页面点「复制」后，自动把授权码填进来。"""
        self._last_code = ""
        self._stop_watch()
        deadline = time.monotonic() + 15 * 60      # 最多等 15 分钟

        def tick():
            self._watch_id = None
            code = self._clip_code()
            if code:
                self.pw_var.set(code)
                self.show_pw.set(False)
                self._guide_status(
                    f"已抓到授权码（{len(code)} 位），已填进上面输入框。"
                    "点「发送测试邮件」确认能发出去。", ui.C["ok"])
                return
            if time.monotonic() > deadline:
                self._guide_status("等了 15 分钟没看到复制动作，先停在这里。"
                                   "手动粘贴授权码也行。", ui.C["muted"])
                return
            self._watch_id = self.after(700, tick)

        self._watch_id = self.after(700, tick)

    def _clip_code(self):
        try:
            raw = self.clipboard_get()
        except tk.TclError:
            return ""
        text = (raw or "").strip()
        if CODE_FULL.fullmatch(text):
            return text
        if len(text) <= 60:                 # 只认「基本就是这串码」的剪贴板
            m = CODE_TOKEN.search(text)
            if m:
                return m.group(1)
        return ""

    def _stop_watch(self):
        if self._watch_id is not None:
            try:
                self.after_cancel(self._watch_id)
            except tk.TclError:
                pass
            self._watch_id = None

    def _stop_watch_ui(self):
        self._stop_watch()
        self._guide_status("已停止等待。手动粘贴到上面的输入框也行。", ui.C["muted"])

    def _on_user_leave(self, _event=None):
        """按发件邮箱域名自动选服务器（只在自己没改过服务器时动手）。"""
        addr = self.user_var.get().strip().lower()
        preset = mailer.preset_for_address(addr)
        if preset is None:
            return
        known = {p["host"] for p in mailer.PRESETS if p["host"]}
        current = self.host_var.get().strip()
        if current not in ("", *known) or current == preset["host"]:
            return
        self.preset_var.set(preset["label"])
        self.host_var.set(preset["host"])
        self.port_var.set(str(preset["port"]))
        self.sec_var.set(mailer.SECURITY_LABEL[preset["security"]])
        self._set_status(
            self.cfg_status,
            f"已按 {addr.split('@')[-1]} 自动选好服务器："
            f"{preset['host']}:{preset['port']}", ui.C["accent"])

    def _regen(self, silent=False):
        subject, body = reminder.digest(self.ctx)
        self.subject_var.set(subject)
        self.body_text.delete("1.0", "end")
        self.body_text.insert("1.0", body)
        self._gen_body = body
        if not silent:
            self._set_status(self.send_status, "已按当前笔记重新生成", ui.C["accent"])

    def _async(self, work, done):
        """后台发信，别把界面卡住（SMTP 超时可能 20 秒）。"""
        if self._busy:
            return
        self._busy = True
        for btn in (self.test_btn, self.send_btn, self.save_btn):
            btn.state(["disabled"])
        self._set_status(self.send_status, "正在发送…", ui.C["accent"])

        def runner():
            try:
                result = (True, work())
            except mailer.MailError as e:
                result = (False, str(e))
            except Exception as e:                   # noqa: BLE001
                result = (False, f"{type(e).__name__}: {e}")

            def finish():
                self._busy = False
                for btn in (self.test_btn, self.send_btn, self.save_btn):
                    try:
                        btn.state(["!disabled"])
                    except tk.TclError:
                        pass
                done(*result)
            try:
                self.after(0, finish)
            except (tk.TclError, RuntimeError):
                pass

        threading.Thread(target=runner, daemon=True).start()

    def _test(self):
        cfg = self._save(quiet=True)
        if cfg is None:
            return
        reason = mailer.readiness(cfg)
        if reason:
            self._set_status(self.send_status, reason, ui.C["bad"])
            return

        def done(ok, payload):
            if ok:
                self._set_status(
                    self.send_status,
                    f"测试邮件已发出 → {pv.show_text(_join(payload['recipients']))}"
                    f"（{payload['seconds']:.1f}s）；没收到就看垃圾箱", ui.C["ok"])
            else:
                self._set_status(self.send_status, payload, ui.C["bad"])

        self._async(lambda: mailer.send_test(cfg), done)

    def _send_now(self):
        cfg = self._save(quiet=True)
        if cfg is None:
            return
        reason = mailer.readiness(cfg)
        if reason:
            self._set_status(self.send_status, reason, ui.C["bad"])
            return
        subject = self.subject_var.get().strip() or "第二大脑提醒"
        body = self.body_text.get("1.0", "end").strip()
        if not body:
            messagebox.showwarning("正文为空", "先写点内容再发。", parent=self)
            return

        def done(ok, payload):
            if ok:
                self.cfg = dict(self.cfg)
                self.cfg["daily"] = dict(self.cfg["daily"])
                self.cfg["daily"]["last_sent"] = datetime.now().strftime(
                    "%Y-%m-%d %H:%M")
                try:
                    mailer.save(self.cfg)
                except mailer.MailError:
                    pass
                self._set_status(
                    self.send_status,
                    f"已发送 → {pv.show_text(_join(payload['recipients']))}"
                    f"（{payload['seconds']:.1f}s）", ui.C["ok"])
            else:
                self._set_status(self.send_status, payload, ui.C["bad"])

        self._async(lambda: mailer.send(cfg, subject, body), done)

    # ---------------------------------------------------------------- 计划任务
    def _refresh_task(self):
        installed, detail = autotask.status()
        self._set_status(self.task_status,
                         ("计划任务：" + detail) if installed else detail,
                         ui.C["ok"] if installed else ui.C["muted"])

    def _install_task(self):
        cfg = self._save(quiet=True)
        if cfg is None:
            return
        reason = mailer.readiness(cfg)
        if reason:
            self._set_status(self.task_status, "先配好邮箱：" + reason, ui.C["bad"])
            return
        cfg["daily"]["enabled"] = True
        cfg["daily"]["time"] = self.time_var.get().strip() or "08:30"
        try:
            self.cfg = mailer.save(cfg)
        except mailer.MailError as e:
            self._set_status(self.task_status, str(e), ui.C["bad"])
            return
        ok, msg = autotask.install(self.cfg["daily"]["time"])
        self._set_status(self.task_status, msg, ui.C["ok"] if ok else ui.C["bad"])
        self._refresh_head()

    def _remove_task(self):
        ok, msg = autotask.remove()
        self._set_status(self.task_status, msg, ui.C["ok"] if ok else ui.C["bad"])

    # ---------------------------------------------------------------- 生命周期
    def _on_destroy(self, event=None):
        if event is None or event.widget is self:
            self._stop_watch()

    def on_show(self, **kw):
        self.cfg = mailer.load()
        self._refresh_head()
        self._refresh_task()
        if self.body_text.get("1.0", "end").strip() == self._gen_body.strip():
            self._regen(silent=True)          # 用户没改过正文才刷新摘要


def make(master, ctx, app):
    return MailPage(master, ctx, app)
