# -*- coding: utf-8 -*-
"""自定义快捷模块页：笔记在页内渲染，文件夹/网址/程序给打开入口。"""
import os
import subprocess
import tkinter as tk
import webbrowser

import ui
from core import modules


class ShortcutPage(tk.Frame):
    def __init__(self, master, ctx, app, key):
        super().__init__(master, bg=ui.C["bg"])
        self.ctx, self.app, self.key = ctx, app, key
        self.item = modules.get_item(app.modules_data, key) or {}
        self._build()

    # ------------------------------------------------------------------
    def _build(self):
        bar = tk.Frame(self, bg=ui.C["bg"])
        bar.pack(fill="x", padx=24, pady=(20, 8))

        self.icon_lbl = tk.Label(bar, text="▣", font=(ui.UI, 26, "bold"),
                                 bg=ui.C["bg"], fg=ui.C["accent"])
        self.icon_lbl.pack(side="left", padx=(0, 10))
        head = tk.Frame(bar, bg=ui.C["bg"])
        head.pack(side="left")
        self.title_lbl = tk.Label(head, text="", font=ui.F["h1"], bg=ui.C["bg"],
                                  fg=ui.C["text"], anchor="w")
        self.title_lbl.pack(anchor="w")
        self.sub_lbl = tk.Label(head, text="", font=ui.F["small"], bg=ui.C["bg"],
                                fg=ui.C["muted"], anchor="w")
        self.sub_lbl.pack(anchor="w")

        self.badge = tk.Label(bar, text="", font=ui.F["small"], bg="#eef3ff",
                              fg=ui.C["accent"], padx=10, pady=3)
        self.badge.pack(side="right", pady=(8, 0))

        tools = tk.Frame(self, bg=ui.C["bg"])
        tools.pack(fill="x", padx=24, pady=(0, 10))
        self.open_btn = tk.Button(tools, text="打开目标", font=ui.F["small"],
                                  bg=ui.C["accent"], fg="white", bd=0,
                                  padx=14, pady=6, cursor="hand2",
                                  command=self.open_target)
        self.open_btn.pack(side="left")
        self.reveal_btn = tk.Button(tools, text="在文件夹中显示", font=ui.F["small"],
                                    bg=ui.C["card"], fg=ui.C["text"], bd=0,
                                    padx=12, pady=6, cursor="hand2",
                                    command=self.reveal_target)
        self.reveal_btn.pack(side="left", padx=8)
        tk.Button(tools, text="复制路径", font=ui.F["small"], bg=ui.C["card"],
                  fg=ui.C["text"], bd=0, padx=12, pady=6, cursor="hand2",
                  command=self.copy_target).pack(side="left")
        tk.Button(tools, text="编辑模块", font=ui.F["small"], bg=ui.C["card"],
                  fg=ui.C["text"], bd=0, padx=12, pady=6, cursor="hand2",
                  command=lambda: self.app.edit_module(self.key)).pack(
                      side="left", padx=8)

        self.state_lbl = tk.Label(tools, text="", font=ui.F["small"],
                                  bg=ui.C["bg"], fg=ui.C["bad"])
        self.state_lbl.pack(side="left", padx=8)

        self.body = tk.Frame(self, bg=ui.C["bg"])
        self.body.pack(fill="both", expand=True, padx=24, pady=(0, 20))
        self.view = None
        self.info = None

    # ------------------------------------------------------------------
    def _target(self):
        return (self.item.get("target_type") or ""), (self.item.get("target") or "")

    def _exists(self):
        t, target = self._target()
        if not target:
            return False
        if t == "note":
            return (self.ctx.root / target).is_file()
        if t == "folder":
            return os.path.isdir(target)
        if t == "app":
            return os.path.isfile(target)
        return t == "url"

    def _render(self):
        item = modules.get_item(self.app.modules_data, self.key)
        if item is None:                 # 模块被删（理论上会先跳回首页）
            return
        self.item = item
        t = item.get("target_type", "folder")
        self.icon_lbl.configure(text=item.get("icon") or modules.TYPE_ICON.get(t, "◆"))
        self.title_lbl.configure(text=item.get("title") or "未命名模块")
        self.sub_lbl.configure(text=item.get("target") or "")
        self.badge.configure(text="快捷模块 · " + modules.TYPE_LABEL.get(t, t))

        for w in self.body.winfo_children():
            w.destroy()
        self.view = None
        self.info = None

        ok = self._exists()
        self.state_lbl.configure(text="" if ok else "目标不存在，请编辑模块重新选")
        self.open_btn.configure(state="normal" if ok else "disabled")
        self.reveal_btn.configure(
            state="normal" if ok and t in ("note", "folder", "app") else "disabled")

        if t == "note":
            self.view = ui.MarkdownView(self.body)
            self.view.pack(fill="both", expand=True)
            self._load_note()
            return

        card = tk.Frame(self.body, bg=ui.C["card"], highlightthickness=1,
                        highlightbackground=ui.C["line"])
        card.pack(fill="both", expand=True)
        inner = tk.Frame(card, bg=ui.C["card"])
        inner.pack(fill="x", padx=24, pady=24)
        tk.Label(inner, text=modules.TYPE_LABEL.get(t, t), font=ui.F["small"],
                 bg=ui.C["card"], fg=ui.C["muted"]).pack(anchor="w")
        tk.Label(inner, text=item.get("target") or "", font=ui.F["body"],
                 bg=ui.C["card"], fg=ui.C["text"], wraplength=760,
                 justify="left", anchor="w").pack(anchor="w", pady=(4, 14))
        hint = {"folder": "点「打开目标」在资源管理器里打开这个目录",
                "url": "点「打开目标」用系统默认浏览器打开",
                "app": "点「打开目标」用系统默认程序打开"}.get(t, "")
        tk.Label(inner, text=hint, font=ui.F["small"], bg=ui.C["card"],
                 fg=ui.C["muted"]).pack(anchor="w")
        self.info = inner

    def _load_note(self):
        if self.view is None:
            return
        rel = self.item.get("target") or ""
        try:
            text = self.ctx.read_text(rel)
        except OSError as e:
            self.view.show_text(f"读取失败：{e}")
            return
        self.view.show(text)

    # ------------------------------------------------------------------
    def open_target(self):
        t, target = self._target()
        if not self._exists():
            return
        if t == "note":
            self.app.goto("notes", path=target)
        elif t == "url":
            webbrowser.open(target)
        else:
            os.startfile(target)          # noqa: S606 —— 本地工具，目标由用户自己选

    def reveal_target(self):
        t, target = self._target()
        if not self._exists():
            return
        if t == "url":
            return
        try:
            if t == "folder":
                os.startfile(target)
            else:
                subprocess.Popen(["explorer", "/select,", os.path.normpath(target)])
        except OSError as e:
            self.state_lbl.configure(text=f"打开失败：{e}")

    def copy_target(self):
        _t, target = self._target()
        self.clipboard_clear()
        self.clipboard_append(target)
        self.state_lbl.configure(text="已复制路径")

    def on_show(self, **kw):
        self._render()


def make(master, ctx, app, key):
    return ShortcutPage(master, ctx, app, key)
