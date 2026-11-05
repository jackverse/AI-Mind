# -*- coding: utf-8 -*-
"""设置页：侧栏排序、模块管理（添加/隐藏/回收站/插件）、数据位置、浏览统计。

模块管理是「不写代码也能改侧栏」的入口；内容比一屏高，整页可滚。
"""
import tkinter as tk
from datetime import datetime
from tkinter import messagebox, simpledialog, ttk

import ui
from core import mailer, modules, paths, privacy, usage
from core.usage import SORT_LABEL, SORT_MODES


def _fmt_time(stamp):
    if not stamp:
        return "—"
    try:
        return datetime.fromisoformat(stamp).strftime("%m-%d %H:%M")
    except ValueError:
        return stamp


def _kind_label(entry):
    return {"builtin": "内置", "shortcut": "快捷", "plugin": "插件"}.get(
        entry["kind"], entry["kind"])


class SettingsPage(tk.Frame):
    def __init__(self, master, ctx, app):
        super().__init__(master, bg=ui.C["bg"])
        self.ctx, self.app = ctx, app
        self._build_scroller()
        self._build()
        self.canvas.bind_all("<MouseWheel>", self._on_wheel)

    # ---------------------------------------------------------------- 滚动容器
    def _build_scroller(self):
        self.canvas = tk.Canvas(self, bg=ui.C["bg"], bd=0, highlightthickness=0)
        self.vbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.vbar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.vbar.pack(side="right", fill="y")

        self.body = tk.Frame(self.canvas, bg=ui.C["bg"])
        self._win = self.canvas.create_window((0, 0), window=self.body, anchor="nw")
        self._bar = True          # 滚动条已 pack，内容放得下时自动收起
        self.body.bind("<Configure>", self._on_body)
        self.canvas.bind("<Configure>", self._on_canvas)

    def _on_canvas(self, event):
        self.canvas.itemconfigure(self._win, width=event.width)
        self._sync_scrollbar()

    def _on_body(self, _event=None):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        self._sync_scrollbar()

    def _sync_scrollbar(self):
        """一屏放得下就不显示滚动条。"""
        need = self.body.winfo_reqheight() > self.canvas.winfo_height()
        if need == self._bar:
            return
        self._bar = need
        if need:
            self.vbar.pack(side="right", fill="y")
        else:
            self.vbar.pack_forget()

    def _on_wheel(self, event):
        if not self.winfo_exists() or not self.winfo_ismapped():
            return
        self.canvas.yview_scroll(-int(event.delta / 120), "units")

    # ------------------------------------------------------------------
    def _card(self, parent, title):
        card = tk.Frame(parent, bg=ui.C["card"], highlightthickness=1,
                        highlightbackground=ui.C["line"])
        card.pack(fill="x", padx=24, pady=(0, 10))
        tk.Label(card, text=title, font=(ui.UI, 10, "bold"), bg=ui.C["card"],
                 fg=ui.C["text"]).pack(anchor="w", padx=18, pady=(12, 4))
        return card

    def _table(self, parent, columns, height, scroll=False):
        box = tk.Frame(parent, bg=ui.C["card"])
        box.pack(fill="x", padx=18)
        tree = ttk.Treeview(box, columns=[c[0] for c in columns],
                            show="headings", height=height, selectmode="browse")
        for cid, text, width, anchor, stretch in columns:
            tree.heading(cid, text=text, anchor=anchor)
            tree.column(cid, width=width, minwidth=width, anchor=anchor,
                        stretch=stretch)
        tree.tag_configure("muted", foreground=ui.C["muted"])
        tree.tag_configure("accent", foreground=ui.C["accent"])
        tree.tag_configure("bad", foreground=ui.C["bad"])
        if scroll:
            sb = ttk.Scrollbar(box, orient="vertical", command=tree.yview)
            tree.configure(yscrollcommand=sb.set)
            tree.pack(side="left", fill="x", expand=True)
            sb.pack(side="right", fill="y")
        else:
            tree.pack(fill="x")
        return tree

    def _build(self):
        bar = tk.Frame(self.body, bg=ui.C["bg"])
        bar.pack(fill="x", padx=24, pady=(14, 8))
        tk.Label(bar, text="设置", font=(ui.UI, 18, "bold"), bg=ui.C["bg"],
                 fg=ui.C["text"]).pack(side="left")

        # 界面
        icard = self._card(self.body, "界面")
        row = tk.Frame(icard, bg=ui.C["card"])
        row.pack(fill="x", padx=18, pady=(0, 4))
        tk.Label(row, text="侧栏排序", font=ui.F["body"], bg=ui.C["card"],
                 fg=ui.C["text"]).pack(side="left", padx=(0, 10))
        self.sort_var = tk.StringVar(value=self.app.sort_mode)
        for key in SORT_MODES:
            tk.Radiobutton(row, text=SORT_LABEL[key], variable=self.sort_var,
                           value=key, command=self.apply_sort, bg=ui.C["card"],
                           activebackground=ui.C["card"]).pack(side="left", padx=4)
        tk.Label(icard, text="按真实浏览统计排序；首页固定第一位；右键侧栏卡片可置顶/隐藏/删除",
                 font=ui.F["small"], bg=ui.C["card"], fg=ui.C["muted"]).pack(
                     anchor="w", padx=18, pady=(0, 10))

        # 隐私
        pcard = self._card(self.body, "隐私")
        self.privacy_var = tk.BooleanVar(value=self.app.privacy_on)
        prow = tk.Frame(pcard, bg=ui.C["card"])
        prow.pack(fill="x", padx=18, pady=(0, 2))
        tk.Checkbutton(
            prow, text="隐私模式：账号昵称 / 抖音号 / 小红书号 / 手机号 / 邮箱打码；买房页公积金余额打码",
            variable=self.privacy_var, command=self.apply_privacy,
            font=ui.F["body"], bg=ui.C["card"], activebackground=ui.C["card"],
            anchor="w").pack(side="left")
        tk.Label(pcard, text="只影响界面显示，data/hub 里的数据仍是明文；侧栏底部也能一键切换。"
                             "笔记正文里的手机号、邮箱与 8 位以上数字（账号 ID）同样打码；"
                             "买房页的公积金/补充余额显示为 ¥••••，在「贷款参数」里勾「显示余额」可临时看。",
                 font=ui.F["small"], bg=ui.C["card"], fg=ui.C["muted"],
                 justify="left", wraplength=880).pack(anchor="w", padx=18,
                                                      pady=(0, 10))

        # 侧栏模块
        mcard = self._card(self.body, "侧栏模块")
        tk.Label(mcard, text="内置模块随 exe 发行；快捷模块指向笔记/文件夹/网址/程序；"
                             "插件是 data/hub/modules/ 下的 .py。隐藏只是不显示，删除先进回收站。",
                 font=ui.F["small"], bg=ui.C["card"], fg=ui.C["muted"],
                 justify="left", wraplength=880).pack(anchor="w", padx=18,
                                                      pady=(0, 6))
        self.m_tree = self._table(mcard, (
            ("page", "模块", 220, "w", True),
            ("icon", "图标", 55, "center", False),
            ("kind", "类型", 70, "center", False),
            ("state", "状态", 80, "center", False),
            ("where", "目标", 280, "w", True),
        ), 10, scroll=True)
        self.m_tree.bind("<<TreeviewSelect>>", lambda _e: self._sync_mod_btns())
        self.m_tree.bind("<Double-1>", lambda _e: self._open_selected())

        btns = tk.Frame(mcard, bg=ui.C["card"])
        btns.pack(fill="x", padx=18, pady=(8, 4))
        ttk.Button(btns, text="添加模块", command=self.add_module).pack(side="left")
        self.edit_btn = ttk.Button(btns, text="编辑", command=self.edit_selected)
        self.edit_btn.pack(side="left", padx=6)
        self.hide_btn = ttk.Button(btns, text="隐藏", command=self.toggle_hide_selected)
        self.hide_btn.pack(side="left")
        self.del_btn = ttk.Button(btns, text="移到回收站",
                                  command=self.recycle_selected)
        self.del_btn.pack(side="left", padx=6)
        ttk.Button(btns, text="新建插件", command=self.new_plugin).pack(side="right")
        ttk.Button(btns, text="重置侧栏", command=self.app.reset_modules).pack(
            side="right", padx=6)
        self.plugin_note = tk.Label(mcard, text="", font=ui.F["small"],
                                    bg=ui.C["card"], fg=ui.C["bad"], anchor="w",
                                    justify="left", wraplength=880)
        self.plugin_note.pack(fill="x", padx=18)
        tk.Frame(mcard, bg=ui.C["card"], height=10).pack()

        # 回收站
        rcard = self._card(self.body, "回收站")
        tk.Label(rcard, text="这里的模块只是被标记删除，配置都还在；「还原」即回到侧栏。"
                             "「彻底删除」需二次确认：快捷模块删配置、插件移到 .trash、"
                             "内置模块留标记（可重置侧栏找回）。",
                 font=ui.F["small"], bg=ui.C["card"], fg=ui.C["muted"],
                 justify="left", wraplength=880).pack(anchor="w", padx=18,
                                                      pady=(0, 6))
        self.r_tree = self._table(rcard, (
            ("page", "模块", 220, "w", True),
            ("kind", "类型", 70, "center", False),
            ("when", "删除时间", 130, "center", False),
        ), 5, scroll=True)
        self.r_tree.bind("<<TreeviewSelect>>", lambda _e: self._sync_recycle_btns())
        rbtns = tk.Frame(rcard, bg=ui.C["card"])
        rbtns.pack(fill="x", padx=18, pady=(8, 12))
        self.restore_btn = ttk.Button(rbtns, text="还原", command=self.restore_selected)
        self.restore_btn.pack(side="left")
        self.purge_btn = ttk.Button(rbtns, text="彻底删除", command=self.purge_selected)
        self.purge_btn.pack(side="left", padx=6)
        tk.Label(rbtns, text="双击行 = 还原", font=ui.F["small"], bg=ui.C["card"],
                 fg=ui.C["muted"]).pack(side="left", padx=10)

        # 数据位置
        ccard = self._card(self.body, "数据位置")
        for name, val in (("仓库", str(self.ctx.root)),
                          ("笔记", str(self.ctx.notes)),
                          ("题库", str(self.ctx.kb)),
                          ("数据", str(paths.data_dir())),
                          ("模块", str(modules.store_path())),
                          ("插件", str(modules.plugin_dir())),
                          ("统计", str(usage.store_path())),
                          ("隐私", str(privacy.store_path())),
                          ("邮件", str(mailer.store_path())),
                          ("邮件日志", str(mailer.log_path()))):
            r = tk.Frame(ccard, bg=ui.C["card"])
            r.pack(fill="x", padx=18, pady=0)
            tk.Label(r, text=name, font=ui.F["small"], bg=ui.C["card"],
                     fg=ui.C["muted"], width=8, anchor="w").pack(side="left")
            tk.Label(r, text=val, font=ui.F["small"], bg=ui.C["card"],
                     fg=ui.C["text"], anchor="w").pack(side="left")
        tk.Frame(ccard, bg=ui.C["card"], height=10).pack()

        # 模块浏览（浏览次数集中在这里）
        ucard = self._card(self.body, "模块浏览")
        head = tk.Frame(ucard, bg=ui.C["card"])
        head.pack(fill="x", padx=18, pady=(0, 6))
        self.total_lbl = tk.Label(head, text="", font=ui.F["small"],
                                  bg=ui.C["card"], fg=ui.C["muted"], anchor="w")
        self.total_lbl.pack(side="left")

        self.tree = self._table(ucard, (
            ("page", "页面", 150, "w", False),
            ("pin", "置顶", 55, "center", False),
            ("recent", "近 7 天", 75, "center", False),
            ("total", "累计", 70, "center", False),
            ("hosts", "来源机器", 160, "w", False),
            ("last", "最近一次", 110, "center", False),
        ), 8, scroll=True)
        self.tree.bind("<<TreeviewSelect>>", lambda _e: self._sync_pin_btn())
        self.tree.bind("<Double-1>", lambda _e: self.toggle_pin_selected())

        btns = tk.Frame(ucard, bg=ui.C["card"])
        btns.pack(fill="x", padx=18, pady=(8, 12))
        self.pin_btn = ttk.Button(btns, text="置顶所选", command=self.toggle_pin_selected)
        self.pin_btn.pack(side="left")
        ttk.Button(btns, text="清空统计", command=self.clear_usage).pack(
            side="left", padx=8)
        ttk.Button(btns, text="机器别名…", command=self.edit_aliases).pack(
            side="left")
        tk.Label(btns, text="双击行 = 置顶/取消置顶；首页固定，不可置顶",
                 font=ui.F["small"], bg=ui.C["card"], fg=ui.C["muted"]).pack(
                     side="left", padx=10)

        tk.Frame(self.body, bg=ui.C["bg"], height=6).pack()

    # ---------------------------------------------------------------- 排序
    def apply_sort(self):
        self.app.sort_mode = self.sort_var.get()
        usage.set_sort_mode(self.app.sort_mode, self.app.usage)
        self.app.sort_btn.configure(text=f"排序：{SORT_LABEL[self.app.sort_mode]} ⇄")
        self.app.build_nav()
        self.refresh()
        self.refresh_modules()

    # ---------------------------------------------------------------- 隐私
    def apply_privacy(self):
        self.app.set_privacy(self.privacy_var.get())

    def sync_privacy(self):
        """侧栏切了开关后回填勾选（set 不会触发 command）。"""
        try:
            self.privacy_var.set(self.app.privacy_on)
        except (AttributeError, tk.TclError):
            pass

    # ---------------------------------------------------------------- 模块表
    def refresh_modules(self):
        keep_m = self.m_tree.selection()
        self.m_tree.delete(*self.m_tree.get_children())
        for key in self.app._order(include_hidden=True):
            e = self.app.registry[key]
            if e["deleted_at"]:
                continue
            if e["protected"]:
                state, tag = "固定", "muted"
            elif e["hidden"]:
                state, tag = "已隐藏", "muted"
            else:
                state, tag = "显示", ""
            if e["kind"] == "shortcut":
                where = e["item"].get("target", "")
            elif e["kind"] == "plugin":
                where = str(e["item"].get("path", ""))
            else:
                where = "—"
            self.m_tree.insert("", "end", iid=key, tags=(tag,),
                               values=(e["title"], e["icon"], _kind_label(e),
                                       state, where))

        for iid in keep_m:
            if self.m_tree.exists(iid):
                self.m_tree.selection_set(iid)
                break

        keep_r = self.r_tree.selection()
        self.r_tree.delete(*self.r_tree.get_children())
        deleted = [k for k, e in self.app.registry.items() if e["deleted_at"]]
        deleted.sort(key=lambda k: self.app.registry[k]["deleted_at"], reverse=True)
        for key in deleted:
            e = self.app.registry[key]
            self.r_tree.insert("", "end", iid=key,
                               values=(e["title"], _kind_label(e),
                                       _fmt_time(e["deleted_at"])))
        for iid in keep_r:
            if self.r_tree.exists(iid):
                self.r_tree.selection_set(iid)
                break

        err = modules.plugin_errors_note(self.app.plugin_errors)
        self.plugin_note.configure(
            text=("插件未加载：" + err) if err else "")
        self._sync_mod_btns()
        self._sync_recycle_btns()
        self._on_body()

    def _selected_module(self):
        sel = self.m_tree.selection()
        return sel[0] if sel else None

    def _sync_mod_btns(self):
        key = self._selected_module()
        entry = self.app.registry.get(key) if key else None
        if entry is None:
            for btn in (self.edit_btn, self.hide_btn, self.del_btn):
                btn.state(["disabled"])
            return
        editable = entry["kind"] == "shortcut"
        protected = entry["protected"]
        self.edit_btn.state(["!disabled"] if editable else ["disabled"])
        self.hide_btn.state(["disabled"] if protected else ["!disabled"])
        self.hide_btn.configure(text="显示" if entry["hidden"] else "隐藏")
        self.del_btn.state(["disabled"] if protected else ["!disabled"])

    def _open_selected(self):
        key = self._selected_module()
        entry = self.app.registry.get(key) if key else None
        if entry is None:
            return
        if entry["kind"] == "shortcut":
            self.edit_selected()
        elif not entry["protected"]:
            self.toggle_hide_selected()

    def add_module(self):
        self.app.add_module_dialog()
        self.refresh_modules()

    def edit_selected(self):
        key = self._selected_module()
        if key:
            self.app.edit_module(key)
            self.refresh_modules()

    def toggle_hide_selected(self):
        key = self._selected_module()
        if key:
            self.app.hide_module(key)
            self.refresh_modules()

    def recycle_selected(self):
        key = self._selected_module()
        if key:
            self.app.recycle_module(key)
            self.refresh_modules()

    def new_plugin(self):
        name = simpledialog.askstring(
            "新建插件", "文件名（不带 .py，可中文）：", parent=self)
        if not name:
            return
        path = self.app.create_plugin(name)
        self.refresh_modules()
        messagebox.showinfo(
            "插件模板已创建",
            f"{path}\n\n模板已加入侧栏；改完 make() 保存后重启 hub 生效。",
            parent=self)

    # ---------------------------------------------------------------- 回收站
    def _selected_deleted(self):
        sel = self.r_tree.selection()
        return sel[0] if sel else None

    def _sync_recycle_btns(self):
        on = "!disabled" if self._selected_deleted() else "disabled"
        self.restore_btn.state([on])
        self.purge_btn.state([on])

    def restore_selected(self):
        key = self._selected_deleted()
        if key:
            self.app.restore_module(key)
            self.refresh_modules()

    def purge_selected(self):
        key = self._selected_deleted()
        if key:
            self.app.purge_module(key)
            self.refresh_modules()

    # ---------------------------------------------------------------- 统计
    def toggle_pin_selected(self):
        sel = self.tree.selection()
        if not sel:
            return
        key = sel[0]
        if key == "home":
            return
        self.app.toggle_pin(key)
        self.refresh()
        if self.tree.exists(key):
            self.tree.selection_set(key)
        self._sync_pin_btn()

    def _sync_pin_btn(self):
        sel = self.tree.selection()
        key = sel[0] if sel else None
        if not key or key == "home":
            self.pin_btn.state(["disabled"])
            self.pin_btn.configure(text="置顶所选")
            return
        self.pin_btn.state(["!disabled"])
        self.pin_btn.configure(
            text="取消置顶" if usage.is_pinned(key, self.app.usage) else "置顶所选")

    def clear_usage(self):
        """清空浏览次数（**只清本机分片**），保留置顶与排序设置。"""
        self.app.usage = usage.clear()
        self.app.build_nav()
        self.refresh()
        self.app.notify("已清空本机浏览统计（其它机器的不受影响）")

    def edit_aliases(self):
        """给来源机器起别名（存 data/hub/machines.json，两台机器共用一份）。"""
        hosts = usage.sources(self.app.usage)
        aliases = usage.load_aliases()
        win = tk.Toplevel(self)
        win.title("机器别名")
        win.configure(bg=ui.C["bg"])
        win.resizable(False, False)
        win.transient(self.winfo_toplevel())
        tk.Label(win, text="给每台机器起个名字；留空 = 用原始机器名",
                 font=ui.F["small"], bg=ui.C["bg"], fg=ui.C["muted"]).pack(
                     anchor="w", padx=18, pady=(14, 8))
        vars_ = {}
        for host in hosts:
            row = tk.Frame(win, bg=ui.C["bg"])
            row.pack(fill="x", padx=18, pady=3)
            tk.Label(row, text=host, font=ui.F["small"], bg=ui.C["bg"],
                     fg=ui.C["text"], width=22, anchor="w").pack(side="left")
            var = tk.StringVar(value=aliases.get(host, ""))
            ttk.Entry(row, textvariable=var, width=18).pack(side="left")
            vars_[host] = var
        btns = tk.Frame(win, bg=ui.C["bg"])
        btns.pack(fill="x", padx=18, pady=(12, 14))

        def save():
            for host, var in vars_.items():
                usage.set_alias(host, var.get())
            win.destroy()
            self.refresh()

        ttk.Button(btns, text="保存", style="Accent.TButton",
                   command=save).pack(side="right")
        ttk.Button(btns, text="取消", command=win.destroy).pack(side="right", padx=8)
        win.grab_set()
        win.focus_force()

    def refresh(self):
        rows = {k: (r, t, l) for k, r, t, l in usage.summary(self.app.usage)}
        aliases = usage.load_aliases()
        keep = self.tree.selection()
        self.tree.delete(*self.tree.get_children())
        total_all = 0
        for key in self.app._order(include_hidden=True):
            entry = self.app.registry.get(key)
            if entry is None or entry["deleted_at"]:
                continue
            name = entry["title"] + ("（隐藏）" if entry["hidden"] else "")
            recent, total, last = rows.get(key, (0, 0, None))
            total_all += total
            by_host = usage.breakdown(self.app.usage.get(key, {}))
            parts = []
            for h, n in sorted(by_host.items()):
                label = usage.display_name(h, aliases)
                if len(label) > 8:
                    label = label[:7] + "…"
                parts.append(f"{label}:{n}")
            host_txt = " / ".join(parts) or "—"
            if key == "home":
                pin_txt, tag = "固定", "muted"
            elif usage.is_pinned(key, self.app.usage):
                pin_txt, tag = "置顶", "accent"
            else:
                pin_txt, tag = "—", ""
            when = "—"
            if last:
                try:
                    when = datetime.fromisoformat(last).strftime("%m-%d %H:%M")
                except ValueError:
                    when = last
            self.tree.insert("", "end", iid=key, tags=(tag,),
                             values=(name, pin_txt, recent, total, host_txt, when))
        for iid in keep:
            if self.tree.exists(iid):
                self.tree.selection_set(iid)
                break
        srcs = usage.sources(self.app.usage)
        names = "、".join(usage.display_name(h, aliases) for h in srcs)
        self.total_lbl.configure(
            text=f"累计浏览 {total_all} 次 · 合并 {len(srcs)} 台机器（{names}）"
                 f"；本机只写 {usage.store_path().name}")
        self._sync_pin_btn()
        self._on_body()

    def on_show(self, **kw):
        self.sort_var.set(self.app.sort_mode)
        self.sync_privacy()
        self.refresh()
        self.refresh_modules()


def make(master, ctx, app):
    return SettingsPage(master, ctx, app)
