# -*- coding: utf-8 -*-
"""我的：数据目录、隐私模式、版本与反馈。"""

# 侧栏入口（hub 启动时自动扫这个 META，不用改 hub.py）
META = {"icon": '◉', "title": '我的', "sub": '设置/反馈', "weight": 20}
import os
import tkinter as tk
import webbrowser

import ui
from core import privacy

WECHAT = "jack9527xz"
EMAIL = "1060061749@qq.com"
GITHUB = "https://github.com/jackverse/AI-Mind"
GITEE = "https://gitee.com/jacktianxz/ai-mind"


class MePage(tk.Frame):
    def __init__(self, master, ctx, app):
        super().__init__(master, bg=ui.C["bg"])
        self.ctx, self.app = ctx, app
        self._build()

    def _section(self, parent, title):
        tk.Label(parent, text=title, font=ui.F["h3"], bg=ui.C["bg"],
                 fg=ui.C["text"], anchor="w").pack(fill="x", pady=(18, 6))

    def _card(self, parent):
        box = tk.Frame(parent, bg=ui.C["card"], highlightthickness=1,
                       highlightbackground=ui.C["line"])
        box.pack(fill="x")
        inner = tk.Frame(box, bg=ui.C["card"])
        inner.pack(fill="x", padx=18, pady=14)
        return inner

    def _build(self):
        wrap = tk.Frame(self, bg=ui.C["bg"])
        wrap.pack(fill="both", expand=True, padx=34, pady=26)

        top = tk.Frame(wrap, bg=ui.C["bg"])
        top.pack(fill="x")
        tk.Label(top, text="我的", font=(ui.UI, 22, "bold"), bg=ui.C["bg"],
                 fg=ui.C["text"], anchor="w").pack(side="left")
        ver = getattr(self.app, "version", "")
        tk.Label(top, text=f"v{ver} · 0.x 内测版" if ver else "0.x 内测版",
                 font=ui.F["small"], bg="#eef3ff", fg=ui.C["accent"],
                 padx=8, pady=2).pack(side="left", padx=(10, 0))

        # 数据目录
        self._section(wrap, "数据目录")
        box = self._card(wrap)
        tk.Label(box, text=str(self.ctx.root), font=ui.F["body"], bg=ui.C["card"],
                 fg=ui.C["text"], anchor="w").pack(side="left")
        tk.Button(box, text="打开目录", command=self._open_root).pack(side="right")

        # 隐私
        self._section(wrap, "隐私模式")
        box = self._card(wrap)
        self.privacy_label = tk.Label(box, text=privacy.status_text(), font=ui.F["body"],
                                      bg=ui.C["card"], fg=ui.C["text"], anchor="w")
        self.privacy_label.pack(side="left")
        tk.Button(box, text="切换", command=self._toggle_privacy).pack(side="right")

        # 关于
        self._section(wrap, "关于")
        box = self._card(wrap)
        tk.Label(box, text="完全开源、免费，可商用可私用（MIT）。0.x 开头都是内测版，功能和接口可能变。",
                 font=ui.F["body"], bg=ui.C["card"], fg=ui.C["muted"],
                 anchor="w", justify="left", wraplength=760).pack(fill="x")

        # 反馈（放在页面最下面）
        self._section(wrap, "反馈")
        box = self._card(wrap)
        tk.Label(box, text="用着有问题、想要新功能，都可以找我们。", font=ui.F["body"],
                 bg=ui.C["card"], fg=ui.C["text"], anchor="w").pack(side="left")
        tk.Button(box, text="联系我们", command=self._contact).pack(side="right")

    def _open_root(self):
        try:
            os.startfile(str(self.ctx.root))
        except OSError:
            pass

    def _toggle_privacy(self):
        self.app.toggle_privacy()
        self.sync_privacy()

    def _copy(self, text):
        try:
            self.clipboard_clear()
            self.clipboard_append(text)
            self.app.notify("已复制：" + text)
        except tk.TclError:
            pass

    def _contact(self):
        win = tk.Toplevel(self)
        win.title("联系我们")
        win.configure(bg=ui.C["bg"])
        win.transient(self.winfo_toplevel())
        win.resizable(False, False)

        wrap = tk.Frame(win, bg=ui.C["bg"])
        wrap.pack(padx=26, pady=20)
        tk.Label(wrap, text="联系我们", font=ui.F["h1"], bg=ui.C["bg"],
                 fg=ui.C["text"], anchor="w").pack(fill="x")
        tk.Label(wrap, text="用着有问题、想要新功能，都可以找我。", font=ui.F["small"],
                 bg=ui.C["bg"], fg=ui.C["muted"], anchor="w").pack(fill="x", pady=(4, 14))

        tk.Label(wrap, text=f"微信：{WECHAT}", font=ui.F["body"], bg=ui.C["bg"],
                 fg=ui.C["text"], anchor="w").pack(fill="x")
        tk.Button(wrap, text="复制微信", command=lambda: self._copy(WECHAT)).pack(anchor="w", pady=(4, 10))

        tk.Label(wrap, text=f"邮箱：{EMAIL}", font=ui.F["body"], bg=ui.C["bg"],
                 fg=ui.C["text"], anchor="w").pack(fill="x")
        tk.Button(wrap, text="复制邮箱", command=lambda: self._copy(EMAIL)).pack(anchor="w", pady=(4, 10))

        links = tk.Frame(wrap, bg=ui.C["bg"])
        links.pack(fill="x", pady=(2, 12))
        tk.Button(links, text="GitHub", command=lambda: webbrowser.open(GITHUB)).pack(side="left")
        tk.Button(links, text="Gitee", command=lambda: webbrowser.open(GITEE)).pack(side="left", padx=(8, 0))

        tk.Button(wrap, text="关闭", command=win.destroy).pack(anchor="e")

        win.update_idletasks()
        x = self.winfo_rootx() + (self.winfo_width() - win.winfo_width()) // 2
        y = self.winfo_rooty() + (self.winfo_height() - win.winfo_height()) // 2
        win.geometry(f"+{max(x, 0)}+{max(y, 0)}")

    def sync_privacy(self):
        try:
            self.privacy_label.configure(text=privacy.status_text())
        except tk.TclError:
            pass

    def on_show(self, **kw):
        self.sync_privacy()


def make(master, ctx, app):
    return MePage(master, ctx, app)
