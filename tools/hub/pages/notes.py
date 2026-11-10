# -*- coding: utf-8 -*-
"""笔记页：左侧**目录树** + 右侧 Markdown 渲染。

树按目录分组（notes 根文件 → topics/ → kb/<科目>/ → 其它），知识库多一个
科目目录，侧栏里就自动多一组，不用改代码；搜索时命中项所在的分组会自动展开。
"""

# 侧栏入口（hub 启动时自动扫这个 META，不用改 hub.py）
META = {"icon": '☰', "title": '笔记', "sub": '全部 md', "weight": 90}
import posixpath
import tkinter as tk
from tkinter import ttk

import ui

DIR_PREFIX = "dir::"


def _name(rel):
    """文件名展示：去掉 .md，太长才截断。"""
    base = posixpath.basename(rel)
    if base.lower().endswith(".md"):
        base = base[:-3]
    return base if len(base) <= 30 else base[:14] + "…" + base[-13:]


class NotesPage(tk.Frame):
    def __init__(self, master, ctx, app):
        super().__init__(master, bg=ui.C["bg"])
        self.ctx, self.app = ctx, app
        self.files = []
        self._build()

    def _build(self):
        bar = tk.Frame(self, bg=ui.C["bg"])
        bar.pack(fill="x", padx=24, pady=(20, 10))
        tk.Label(bar, text="笔记", font=(ui.UI, 18, "bold"), bg=ui.C["bg"],
                 fg=ui.C["text"]).pack(side="left")
        self.count = tk.Label(bar, text="", font=ui.F["small"], bg=ui.C["bg"],
                              fg=ui.C["muted"])
        self.count.pack(side="left", padx=10, pady=(6, 0))

        self.q = tk.StringVar()
        entry = ttk.Entry(bar, textvariable=self.q, width=26)
        entry.pack(side="right")
        entry.bind("<KeyRelease>", lambda _e: self._reload())
        tk.Label(bar, text="搜索", font=ui.F["small"], bg=ui.C["bg"],
                 fg=ui.C["muted"]).pack(side="right", padx=(0, 6))

        pane = tk.Frame(self, bg=ui.C["bg"])
        pane.pack(fill="both", expand=True, padx=24, pady=(0, 20))

        left = tk.Frame(pane, bg=ui.C["card"], highlightthickness=1,
                        highlightbackground=ui.C["line"], width=320)
        left.pack(side="left", fill="y")
        left.pack_propagate(False)
        self.tree = ttk.Treeview(left, show="tree", selectmode="browse")
        sb = ttk.Scrollbar(left, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.tree.bind("<<TreeviewSelect>>", self._on_select)

        right = tk.Frame(pane, bg=ui.C["bg"])
        right.pack(side="left", fill="both", expand=True, padx=(16, 0))
        self.path_lbl = tk.Label(right, text="", font=ui.F["small"], bg=ui.C["bg"],
                                 fg=ui.C["muted"], anchor="w")
        self.path_lbl.pack(fill="x", pady=(0, 6))
        self.view = ui.MarkdownView(right)
        self.view.pack(fill="both", expand=True)

    # ------------------------------------------------------------------
    @staticmethod
    def _group_key(d):
        """分组排序：notes 根文件最前 → topics → kb/* → 其它。"""
        if d == "notes":
            return (0, d)
        if d == "notes/topics":
            return (1, d)
        if d.startswith("notes/kb/"):
            return (2, d)
        return (3, d)

    @staticmethod
    def _label(d):
        if d == "notes":
            return "根目录"
        return d[6:] if d.startswith("notes/") else d

    def _reload(self):
        keep = self.tree.selection()
        all_files = self.ctx.note_rels()
        kw = self.q.get().strip().lower()
        files = [r for r in all_files if not kw or kw in r.lower()]
        self.files = files

        # 依目录分桶
        buckets = {}
        for rel in files:
            buckets.setdefault(posixpath.dirname(rel), []).append(rel)

        self.tree.delete(*self.tree.get_children())
        for d in sorted(buckets, key=self._group_key):
            key = DIR_PREFIX + d
            # 有搜索词时全部展开，否则根目录展开、其它收起
            opened = bool(kw) or d == "notes" or len(buckets) == 1
            self.tree.insert("", "end", iid=key,
                             text="  " + self._label(d),
                             open=opened)
            for rel in sorted(buckets[d]):
                self.tree.insert(key, "end", iid=rel, text="    " + _name(rel))

        self.count.configure(
            text=f"{len(files)} 个文件 · {len(buckets)} 个目录")
        if keep and keep[0] in self.tree.get_children():
            self.tree.selection_set(keep[0])

    def _on_select(self, _e=None):
        sel = self.tree.selection()
        if not sel:
            return
        rel = sel[0]
        if rel.startswith(DIR_PREFIX):      # 点到目录：只展开/收起，不换内容
            return
        try:
            text = self.ctx.read_text(rel)
        except OSError as e:
            self.view.show_text(f"读取失败：{e}")
            return
        self.path_lbl.configure(text=rel)
        self.view.show(text)

    def on_show(self, path=None, **kw):
        if not self.files:
            self._reload()
        target = None
        if path:
            rel = path.replace("\\", "/")
            if self.tree.exists(rel):
                target = rel
        if target is None and not self.tree.selection() and self.files:
            target = self.files[0]
        if target:
            parent = self.tree.parent(target)
            if parent:
                self.tree.item(parent, open=True)
            self.tree.selection_set(target)
            self.tree.see(target)
            self._on_select()


def make(master, ctx, app):
    return NotesPage(master, ctx, app)
