# -*- coding: utf-8 -*-
"""自定义模块的添加/编辑对话框（标题、图标、类型、目标）。"""
import os
import re
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import ui
from core import modules

TYPE_ORDER = ["note", "folder", "url", "app"]
TYPE_HINT = {
    "note": "选 notes/ 下的 Markdown，模块页内直接渲染",
    "folder": "点开在资源管理器里打开目录",
    "url": "点开用系统浏览器打开网址",
    "app": "点开用系统默认程序打开文件/程序",
}


def _center(win, parent):
    win.update_idletasks()
    w, h = win.winfo_width(), win.winfo_height()
    px, py = parent.winfo_rootx(), parent.winfo_rooty()
    pw, ph = parent.winfo_width(), parent.winfo_height()
    win.geometry(f"+{px + max(0, (pw - w) // 2)}+{py + max(0, (ph - h) // 2)}")


class ModuleDialog(tk.Toplevel):
    """返回 dict(title, icon, sub, target_type, target)；取消返回 None。"""

    def __init__(self, parent, ctx, item=None):
        super().__init__(parent)
        self.ctx = ctx
        self.item = dict(item or {})
        self.result = None
        self.title("编辑模块" if self.item else "添加模块")
        self.configure(bg=ui.C["card"])
        self.resizable(False, False)
        self.transient(parent)
        self._build()
        _center(self, parent)
        self.grab_set()
        self.title_entry.focus_set()

    # ------------------------------------------------------------------
    def _row(self, text, hint=None):
        row = tk.Frame(self.body, bg=ui.C["card"])
        row.pack(fill="x", pady=(0, 10))
        tk.Label(row, text=text, font=ui.F["small"], bg=ui.C["card"],
                 fg=ui.C["muted"], width=8, anchor="w").pack(side="left")
        box = tk.Frame(row, bg=ui.C["card"])
        box.pack(side="left", fill="x", expand=True)
        if hint:
            tk.Label(box, text=hint, font=ui.F["small"], bg=ui.C["card"],
                     fg=ui.C["muted"], anchor="w").pack(fill="x", pady=(2, 0))
        return box

    def _build(self):
        self.body = tk.Frame(self, bg=ui.C["card"], padx=20, pady=18)
        self.body.pack(fill="both", expand=True)

        box = self._row("标题")
        self.title_var = tk.StringVar(value=self.item.get("title", ""))
        self.title_entry = ttk.Entry(box, textvariable=self.title_var, width=40)
        self.title_entry.pack(fill="x")

        box = self._row("图标", "1 个字符或 emoji，留空按类型自动选")
        self.icon_var = tk.StringVar(value=self.item.get("icon", ""))
        ttk.Entry(box, textvariable=self.icon_var, width=8).pack(anchor="w")

        box = self._row("副标题", "侧栏卡片第二行，留空按类型自动填")
        self.sub_var = tk.StringVar(value=self.item.get("sub", ""))
        ttk.Entry(box, textvariable=self.sub_var, width=40).pack(fill="x")

        box = self._row("类型")
        cur = self.item.get("target_type", "note")
        self.type_var = tk.StringVar(
            value=modules.TYPE_LABEL.get(cur, modules.TYPE_LABEL["note"]))
        self.type_box = ttk.Combobox(
            box, textvariable=self.type_var, state="readonly", width=12,
            values=[modules.TYPE_LABEL[t] for t in TYPE_ORDER])
        self.type_box.pack(anchor="w")
        self.type_box.bind("<<ComboboxSelected>>", lambda _e: self._sync_type())
        self.type_hint = tk.Label(box, text="", font=ui.F["small"],
                                  bg=ui.C["card"], fg=ui.C["muted"], anchor="w")
        self.type_hint.pack(fill="x", pady=(3, 0))

        box = self._row("目标")
        self.target_var = tk.StringVar(value=self.item.get("target", ""))
        line = tk.Frame(box, bg=ui.C["card"])
        line.pack(fill="x")
        ttk.Entry(line, textvariable=self.target_var, width=34).pack(
            side="left", fill="x", expand=True)
        self.browse_btn = ttk.Button(line, text="浏览…", width=7,
                                     command=self._browse)
        self.browse_btn.pack(side="left", padx=(6, 0))

        tip = tk.Label(self.body,
                       text="模块只登记入口，不改动目标文件；删除会先进回收站。",
                       font=ui.F["small"], bg=ui.C["card"], fg=ui.C["muted"],
                       anchor="w")
        tip.pack(fill="x", pady=(2, 0))

        btns = tk.Frame(self, bg=ui.C["card"], padx=20, pady=0)
        btns.pack(fill="x", pady=(0, 16))
        ttk.Button(btns, text="取消", command=self.destroy).pack(side="right")
        ttk.Button(btns, text="保存", command=self._ok).pack(
            side="right", padx=(0, 8))
        self._sync_type()

    def _sync_type(self):
        t = self.target_type()
        self.type_hint.configure(text=TYPE_HINT[t])
        self.browse_btn.configure(state="disabled" if t == "url" else "!disabled")

    def target_type(self):
        label = self.type_var.get()
        for k, v in modules.TYPE_LABEL.items():
            if v == label:
                return k
        return "note"

    # ------------------------------------------------------------------
    def _browse(self):
        t = self.target_type()
        path = ""
        if t == "note":
            path = filedialog.askopenfilename(
                parent=self, title="选择 Markdown", initialdir=str(self.ctx.notes),
                filetypes=[("Markdown", "*.md"), ("全部文件", "*.*")])
        elif t == "folder":
            path = filedialog.askdirectory(parent=self, title="选择文件夹")
        elif t == "app":
            path = filedialog.askopenfilename(
                parent=self, title="选择文件或程序",
                filetypes=[("程序/文件", "*.*")])
        if path:
            if t == "note":
                path = self._to_rel(path)
            self.target_var.set(path.replace("\\", "/") if t != "note" else path)

    def _to_rel(self, path):
        """笔记目标统一存仓库相对路径（notes/xxx.md），换机器也能用。"""
        try:
            p = Path(path)
            if not p.is_absolute():
                p = self.ctx.root / p
            p = p.resolve()
            rel = p.relative_to(self.ctx.root.resolve()).as_posix()
        except (OSError, ValueError):
            return str(Path(path).as_posix())
        return rel

    # ------------------------------------------------------------------
    def _ok(self):
        t = self.target_type()
        title = self.title_var.get().strip()
        target = self.target_var.get().strip().replace("\\", "/")
        if not title:
            messagebox.showwarning("缺少标题", "给模块起个名字吧。", parent=self)
            return
        if not target:
            messagebox.showwarning("缺少目标", "选一个目标：笔记 / 文件夹 / 网址 / 程序。",
                                   parent=self)
            return
        if t == "url":
            if not re.match(r"^[a-zA-Z][a-zA-Z0-9+.\-]*://", target):
                target = "https://" + target
            self.target_var.set(target)
        elif t == "note":
            target = self._to_rel(target)
            full = self.ctx.root / target
            if not full.is_file():
                messagebox.showerror("找不到笔记", f"文件不存在：\n{target}",
                                     parent=self)
                return
        elif t == "folder":
            if not os.path.isdir(target):
                messagebox.showerror("找不到文件夹", f"目录不存在：\n{target}",
                                     parent=self)
                return
        elif t == "app":
            if not os.path.isfile(target):
                messagebox.showerror("找不到文件", f"文件不存在：\n{target}",
                                     parent=self)
                return
        self.result = {
            "title": title,
            "icon": self.icon_var.get().strip(),
            "sub": self.sub_var.get().strip(),
            "target_type": t,
            "target": target,
        }
        self.destroy()
