# -*- coding: utf-8 -*-
"""收集箱页：把丢进 notes/inbox/ 的东西认出来、处理掉。

扫描会把聊天 md 收进 conversations/、账单丢给 bill 解析、小红书表并进账号库，
认不出的放 unsorted/ 等 agent。
"""
import os
import subprocess
import tkinter as tk
from tkinter import messagebox, ttk

import ui
from core import collect

# 侧栏入口（hub 启动时自动扫这个 META，不用改 hub.py）
META = {"icon": "⤓", "title": "收集箱", "sub": "丢文件进来", "weight": 57}


class InboxPage(tk.Frame):
    def __init__(self, master, ctx, app):
        super().__init__(master, bg=ui.C["bg"])
        self.ctx, self.app = ctx, app
        self._build()

    # ------------------------------------------------------------ 布局
    def _build(self):
        bar = tk.Frame(self, bg=ui.C["bg"])
        bar.pack(fill="x", padx=24, pady=(18, 8))
        tk.Label(bar, text="收集箱", font=(ui.UI, 18, "bold"), bg=ui.C["bg"],
                 fg=ui.C["text"]).pack(side="left")

        tk.Button(bar, text="扫描并处理", command=self._scan, font=ui.F["body"],
                  bg=ui.C["accent"], fg="#fff", relief="flat", padx=14, pady=5,
                  cursor="hand2").pack(side="right")
        tk.Button(bar, text="打开文件夹", command=self._open, font=ui.F["body"],
                  bg=ui.C["card"], fg=ui.C["text"], relief="flat", padx=12, pady=5,
                  highlightthickness=1, highlightbackground=ui.C["line"],
                  cursor="hand2").pack(side="right", padx=(0, 8))

        self.hint = tk.Label(self, text="", font=ui.F["small"], bg=ui.C["bg"],
                             fg=ui.C["muted"], justify="left")
        self.hint.pack(fill="x", padx=24, pady=(0, 6))

        body = tk.Frame(self, bg=ui.C["bg"])
        body.pack(fill="both", expand=True, padx=24, pady=(0, 18))

        # 待处理
        box = tk.Frame(body, bg=ui.C["card"], highlightthickness=1,
                       highlightbackground=ui.C["line"])
        box.pack(fill="both", expand=True)
        tk.Label(box, text="待处理", font=ui.F["body"], bg=ui.C["card"],
                 fg=ui.C["text"]).pack(anchor="w", padx=14, pady=(10, 2))

        cols = ("name", "kind", "why", "size")
        self.tree = ttk.Treeview(box, columns=cols, show="headings", height=8)
        for c, (t, w, anchor) in {
            "name": ("文件", 320, "w"),
            "kind": ("识别为", 120, "w"),
            "why": ("依据", 220, "w"),
            "size": ("大小", 90, "e"),
        }.items():
            self.tree.heading(c, text=t)
            self.tree.column(c, width=w, anchor=anchor)
        self.tree.pack(fill="both", expand=True, padx=12, pady=(0, 10))

        # 未归类 + 已处理
        foot = tk.Frame(body, bg=ui.C["bg"])
        foot.pack(fill="x", pady=(10, 0))

        self.unsorted_box = tk.Frame(foot, bg=ui.C["card"], highlightthickness=1,
                                     highlightbackground=ui.C["line"])
        self.unsorted_box.pack(side="left", fill="both", expand=True, padx=(0, 10))
        tk.Label(self.unsorted_box, text="未归类（等 agent 处理）", font=ui.F["body"],
                 bg=ui.C["card"], fg=ui.C["text"]).pack(anchor="w", padx=14, pady=(9, 2))
        self.unsorted_list = tk.Label(self.unsorted_box, text="", font=ui.F["small"],
                                      bg=ui.C["card"], fg=ui.C["muted"], justify="left",
                                      anchor="w")
        self.unsorted_list.pack(anchor="w", padx=14, pady=(0, 10))

        self.done_box = tk.Frame(foot, bg=ui.C["card"], highlightthickness=1,
                                 highlightbackground=ui.C["line"])
        self.done_box.pack(side="left", fill="both", expand=True)
        tk.Label(self.done_box, text="已处理（最近）", font=ui.F["body"],
                 bg=ui.C["card"], fg=ui.C["text"]).pack(anchor="w", padx=14, pady=(9, 2))
        self.done_list = tk.Label(self.done_box, text="", font=ui.F["small"],
                                  bg=ui.C["card"], fg=ui.C["muted"], justify="left",
                                  anchor="w")
        self.done_list.pack(anchor="w", padx=14, pady=(0, 10))

    # ------------------------------------------------------------ 动作
    def _scan(self):
        try:
            results = collect.scan()
        except Exception as e:                              # noqa: BLE001
            messagebox.showerror("扫描失败", str(e))
            return
        if not results:
            messagebox.showinfo("收集箱", "没有新文件。\n把 md / 账单 csv / 小红书 xlsx 丢进 inbox 再点一次。")
            self.refresh()
            return
        ok = sum(1 for r in results if r["ok"])
        lines = []
        for r in results[:12]:
            lines.append("%s %s → %s" % ("✓" if r["ok"] else "·",
                                         r["file"], str(r.get("msg", ""))[:80]))
        if len(results) > 12:
            lines.append("…还有 %d 个" % (len(results) - 12))
        messagebox.showinfo("处理完成", "共 %d 个，成功 %d\n\n%s" % (len(results), ok, "\n".join(lines)))
        self.refresh()

    def _open(self):
        target = collect.inbox_dir()
        try:
            target.mkdir(parents=True, exist_ok=True)
            os.startfile(str(target))                       # noqa: S606 —— Windows 打开目录
        except OSError:
            try:
                subprocess.Popen(["explorer", str(target)])
            except OSError:
                messagebox.showinfo("收集箱", str(target))

    # ------------------------------------------------------------ 刷新
    def refresh(self):
        try:
            data = collect.overview()
        except Exception as e:                              # noqa: BLE001
            self.hint.config(text="读取收集箱失败：%s" % e)
            return
        self.tree.delete(*self.tree.get_children())
        for item in data["pending"]:
            size = item.get("size") or 0
            human = "%.0f KB" % (size / 1024) if size >= 1024 else "%d B" % size
            self.tree.insert("", "end", values=(item["name"], item["label"],
                                                item["why"], human))
        self.hint.config(
            text="目录：%s　｜　待处理 %d　｜　已处理记录 %d\n"
                 "把文件丢进去再点「扫描并处理」：聊天 md → conversations/，"
                 "支付宝/微信账单 → 账单页，小红书导出表 → 小红书页，认不出的进 unsorted/。"
                 % (data["inbox"], len(data["pending"]), data["state_count"]))

        unsorted_names = [u["name"] for u in data["unsorted"]]
        self.unsorted_list.config(
            text="\n".join(unsorted_names) if unsorted_names else "（空）")
        done_names = ["%s  %s" % (d["at"], d["name"]) for d in data["done"][:8]]
        self.done_list.config(text="\n".join(done_names) if done_names else "（空）")

    def on_show(self, **kw):
        self.refresh()


def make(master, ctx, app):
    return InboxPage(master, ctx, app)
