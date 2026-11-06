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

