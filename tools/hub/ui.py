# -*- coding: utf-8 -*-
"""主题、字体与通用控件。"""
import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk

C = {
    "bg": "#f4f6fa",
    "card": "#ffffff",
    "card_hover": "#eef3ff",
    "sidebar": "#1a202b",
    "sidebar_hover": "#2b3444",
    "sidebar_active": "#3d6ee0",
    "sidebar_card": "#242c3b",
    "sidebar_card_hover": "#2f3948",
    "sidebar_border": "#333e52",
    "text": "#1c2333",
    "muted": "#6b7688",
    "accent": "#3d6ee0",
    "ok": "#1f9d55",
    "bad": "#d64545",
    "line": "#e2e7f0",
    "code_bg": "#f2f4f8",
}

UI = "Microsoft YaHei UI"
MONO = "Consolas"

F = {
    "title": (UI, 20, "bold"),
    "h1": (UI, 19, "bold"),
    "h2": (UI, 16, "bold"),
    "h3": (UI, 13, "bold"),
    "h4": (UI, 11, "bold"),
    "body": (UI, 10),
    "small": (UI, 9),
    "mono": (MONO, 9),
}


def apply_theme(root):
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass
    style.configure("TFrame", background=C["bg"])
    style.configure("TLabel", background=C["bg"], foreground=C["text"], font=F["body"])
    style.configure("Card.TFrame", background=C["card"])
    style.configure("TButton", font=F["body"], padding=(10, 6))
    style.configure("Accent.TButton", font=F["body"], padding=(12, 7))
    style.map("Accent.TButton",
              background=[("!disabled", C["accent"])],
              foreground=[("!disabled", "white")])
    style.configure("TCombobox", padding=4)
    style.configure("Treeview", font=F["body"], rowheight=26, background=C["card"],
                    fieldbackground=C["card"])
    style.configure("Treeview.Heading", font=(UI, 9, "bold"), background="#eef2f8",
                    foreground=C["text"], relief="flat", padding=(4, 6))
    style.map("Treeview.Heading", background=[("active", "#e2e9f6")])
    style.configure("TSpinbox", padding=3)
    _style_dashboard(style)
    root.configure(bg=C["bg"])


def _style_dashboard(style):
    """数据页（抖音/小红书）专用的表格与滚动条：大行高、无边框、淡表头。"""
    style.configure("Dash.Treeview", font=(UI, 10), rowheight=31,
                    background=C["card"], fieldbackground=C["card"],
                    borderwidth=0, relief="flat")
    style.map("Dash.Treeview", background=[("selected", "#e6eefd")],
              foreground=[("selected", C["text"])])
    style.configure("Dash.Treeview.Heading", font=(UI, 9, "bold"),
                    background="#f7f9fc", foreground="#5f6b80", relief="flat",
                    padding=(8, 9), borderwidth=0)
    style.map("Dash.Treeview.Heading",
              background=[("active", "#eef3fb"), ("pressed", "#eef3fb")])
    style.layout("Dash.Vertical.TScrollbar", [
        ("Vertical.Scrollbar.trough", {
            "children": [("Vertical.Scrollbar.thumb",
                          {"expand": "1", "sticky": "nswe"})],
            "sticky": "ns"})])
    style.configure("Dash.Vertical.TScrollbar", width=10, background="#c7d2e4",
                    troughcolor=C["bg"], bordercolor=C["bg"], arrowcolor=C["bg"],
                    relief="flat", borderwidth=0)
    style.map("Dash.Vertical.TScrollbar",
              background=[("active", "#adbcd6"), ("pressed", "#9aabc9")])


def configure_tags(text):
    """给 Text 配置 Markdown 渲染用的 tag。"""
    text.tag_configure("p", font=F["body"], spacing1=2, spacing3=4, lmargin1=0, lmargin2=0)
    text.tag_configure("li", font=F["body"], lmargin1=14, lmargin2=28, spacing1=1, spacing3=3)
    text.tag_configure("h1", font=F["h1"], spacing1=14, spacing3=8, foreground=C["text"])
    text.tag_configure("h2", font=F["h2"], spacing1=12, spacing3=6)
    text.tag_configure("h3", font=F["h3"], spacing1=10, spacing3=4)
    text.tag_configure("h4", font=F["h4"], spacing1=8, spacing3=3)
    text.tag_configure("quote", font=F["body"], foreground=C["muted"], lmargin1=10,
                       lmargin2=24, spacing1=3, spacing3=3)
    text.tag_configure("code", font=F["mono"], background=C["code_bg"],
                       lmargin1=10, lmargin2=10, spacing1=6, spacing3=6)
    text.tag_configure("code_inline", font=F["mono"], background=C["code_bg"])
    text.tag_configure("bold", font=(UI, 10, "bold"))
    text.tag_configure("th", font=(UI, 9, "bold"), spacing1=2, spacing3=2)
    text.tag_configure("td", font=F["body"], spacing1=1, spacing3=1)
    text.tag_configure("hr", font=F["small"], foreground=C["line"], spacing1=8, spacing3=8)
    text.tag_configure("link", foreground=C["accent"], underline=True)


class MarkdownView(ttk.Frame):
    """带滚动条的 Markdown 阅读区。"""

    def __init__(self, master, **kw):
        super().__init__(master, **kw)
        self.text = tk.Text(self, wrap="word", relief="flat", bd=0, padx=22, pady=16,
                            bg=C["card"], fg=C["text"], insertwidth=0,
                            selectbackground="#cfe0ff")
        self.text.configure(font=F["body"], spacing1=2)
        sb = ttk.Scrollbar(self, orient="vertical", command=self.text.yview)
        self.text.configure(yscrollcommand=sb.set)
        self.text.grid(row=0, column=0, sticky="nsew")
        sb.grid(row=0, column=1, sticky="ns")
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)
        configure_tags(self.text)
        self.text.configure(state="disabled")

    def show(self, markdown, on_link=None):
        from core import md, privacy
        md.render(self.text, markdown, None, on_link=on_link,
                  mask=privacy.mask_text if privacy.enabled() else None)
        self.text.yview_moveto(0)

    def show_text(self, s):
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.insert("end", s, "p")
        self.text.configure(state="disabled")
        self.text.yview_moveto(0)


class Card(tk.Frame):
    """可点击入口卡片（首页/空状态用）。"""

    def __init__(self, master, title, desc, command, badge=None):
        super().__init__(master, bg=C["card"], highlightthickness=1,
                         highlightbackground=C["line"], cursor="hand2")
        self.command = command
        self._build(title, desc, badge)
        for w in (self, *self.winfo_children()):
            w.bind("<Button-1>", self._click)
            w.bind("<Enter>", self._enter)
            w.bind("<Leave>", self._leave)

    def _build(self, title, desc, badge):
        pad = tk.Frame(self, bg=C["card"])
        pad.pack(fill="both", expand=True, padx=18, pady=16)
        head = tk.Frame(pad, bg=C["card"])
        head.pack(fill="x")
        tk.Label(head, text=title, font=(UI, 14, "bold"), bg=C["card"],
                 fg=C["text"]).pack(side="left")
        if badge is not None:
            tk.Label(head, text=str(badge), font=F["small"], bg="#eef3ff",
                     fg=C["accent"], padx=8, pady=2).pack(side="right")
        tk.Label(pad, text=desc, font=F["small"], bg=C["card"], fg=C["muted"],
                 justify="left", wraplength=250, anchor="w").pack(fill="x", pady=(8, 0))

    def _click(self, _e=None):
        self.command()

    def _enter(self, _e=None):
        self._paint(C["card_hover"])

    def _leave(self, _e=None):
        self._paint(C["card"])

    def _paint(self, color):
        def walk(w):
            if isinstance(w, tk.Frame) or isinstance(w, tk.Label):
                try:
                    w.configure(bg=color)
                except tk.TclError:
                    pass
            for c in w.winfo_children():
                walk(c)
        walk(self)
