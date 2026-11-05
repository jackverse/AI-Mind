# -*- coding: utf-8 -*-
"""
hub.py — 第二大脑超级工具（GUI 外壳）

设计要点：
  · 单窗口 + 左侧多入口，页面模块**按需懒加载**：点哪个才 import 哪个（不在启动时加载）
  · 数据来自数据仓库的 notes/ 与 notes/kb/，与 hub-web 共用 review.json（进度互通）
  · 零第三方依赖（tkinter），可 PyInstaller 打成 onedir exe
  · 侧栏模块可管理：内置 / 自定义快捷模块 / data/hub/modules/*.py 插件，
    支持隐藏、回收站、还原、彻底删除（见 core/modules.py）

用法：
  python hub/hub.py                      # 打开壳（默认首页）
  python hub/hub.py --page notes         # 直接进某页
  python hub/hub.py --selftest           # 构建全部页面后退出（打包/回归自检）
  python hub/hub.py --root D:\\path\\to\\vault
"""
import importlib
import os
import sys
import tkinter as tk
from datetime import datetime
from tkinter import messagebox, ttk

import ui
from core import modules, privacy, usage
from core.paths import Ctx

APP_TITLE = "第二大脑"
VERSION = "1.12.1"

# ---------------------------------------------------------------- 导航配置
# 键 -> (图标, 显示名, 副标题, 页面模块, 权重)
#   权重 = 使用频率，越大越靠前；左侧卡片顺序由此自动排序，改数字即改顺序
#   新增页面：这里加一行 + PAGES 对应模块的 make()，其余不用动
PAGES = {
    "home":    ("◎", "首页", "总览", "pages.home", 100),
    "notes":   ("☰", "笔记", "全部 md", "pages.notes", 90),
    "quiz":    ("✎", "刷题", "随机/章节", "pages.quiz", 80),
    "fitness": ("♥", "健身", "体重/打卡", "pages.fitness", 70),
    "timeline": ("≡", "时间线", "在干嘛", "pages.timeline", 68),
    "house":   ("⌂", "买房", "首付/月供/房源", "pages.house", 67),
    "douyin":  ("♪", "抖音", "账号数据", "pages.douyin", 65),
    "eudic":   ("英", "欧路", "生词/学习", "pages.eudic", 63),
    "xhs":     ("✿", "小红书", "笔记数据", "pages.xhs", 60),
    "bills":   ("¥", "账单", "支付宝/微信", "pages.bills", 58),
    "mail":    ("✉", "邮件", "提醒/日报", "pages.mail", 56),
    "wrong":   ("✗", "错题本", "待攻克", "pages.wrong", 40),
    "stats":   ("▦", "统计", "正确率", "pages.stats", 30),
    "settings": ("⚙", "设置", "排序/模块", "pages.settings", 20),
}

# 首页固定第一、设置页提供恢复入口：这两个不给隐藏/删除，防止把管理入口弄丢
PROTECTED = {"home", "settings"}

# 左侧卡片顺序：默认按权重降序（同权重保持字典书写顺序）
NAV_ORDER = sorted(PAGES, key=lambda k: -PAGES[k][4])

SORT_LABEL, SORT_MODES = usage.SORT_LABEL, usage.SORT_MODES


def _round_rect(cv, x0, y0, x1, y1, r, **kw):
    """Canvas 圆角矩形（smooth 多边形近似）。"""
    pts = [x0 + r, y0, x1 - r, y0, x1, y0, x1, y0 + r, x1, y1 - r, x1, y1,
           x1 - r, y1, x0 + r, y1, x0, y1, x0, y1 - r, x0, y0 + r, x0, y0]
    return cv.create_polygon(pts, smooth=True, **kw)


class NavCard(tk.Canvas):
    """左侧导航卡片：圆角底 + 图标块 + 标题/副标题，悬停与选中换色。

    右键菜单：置顶 / 隐藏 / 移到回收站（首页固定、设置页受保护）。
    """

    W, H = 178, 56

    def __init__(self, master, key, icon, title, sub, command, on_pin,
                 on_hide, on_delete, fixed=False, protected=False, on_wheel=None):
        super().__init__(master, width=self.W, height=self.H, bd=0,
                         highlightthickness=0, bg=ui.C["sidebar"], cursor="hand2")
        self.key = key
        self.command = command
        self.on_pin = on_pin
        self.on_hide = on_hide
        self.on_delete = on_delete
        self.fixed = fixed
        self.protected = protected
        self.pinned = False
        self.active = False
        self._card = _round_rect(self, 1, 1, self.W - 1, self.H - 1, 12,
                                 fill=ui.C["sidebar_card"],
                                 outline=ui.C["sidebar_border"], width=1)
        # 置顶时的左侧竖条
        self._pinbar = _round_rect(self, 4, 15, 8, 41, 2, fill=ui.C["accent"],
                                   outline="")
        self._ibox = _round_rect(self, 13, 13, 43, 43, 9, fill="#34415a",
                                 outline="")
        self._icon = self.create_text(28, 28, text=icon, fill="#a8c2ff",
                                      font=(ui.UI, 11, "bold"))
        self._title = self.create_text(55, 21, text=title, anchor="w",
                                       fill="#dfe6f2", font=(ui.UI, 11, "bold"))
        self._sub = self.create_text(55, 39, text=sub, anchor="w",
                                     fill="#7d8899", font=(ui.UI, 8))
        self._pin = self.create_text(self.W - 12, 11, text="", anchor="e",
                                     fill="#7f8fb0", font=(ui.UI, 8))
        self.bind("<Button-1>", lambda _e: self.command())
        self.bind("<Button-3>", self._popup)
        self.bind("<Enter>", lambda _e: self._paint(hover=True))
        self.bind("<Leave>", lambda _e: self._paint(hover=False))
        if on_wheel is not None:
            self.bind("<MouseWheel>", on_wheel)
        self.set_pinned(False)

    def set_labels(self, icon, title, sub):
        """自定义模块编辑后原地换字，不重排、不闪。"""
        self.itemconfigure(self._icon, text=icon)
        self.itemconfigure(self._title, text=title)
        self.itemconfigure(self._sub, text=sub)

    def set_pinned(self, on):
        """置顶标记：首页显示「固定」（不可取消），其余显示「置顶」。"""
        self.pinned = on
        self.itemconfigure(self._pin,
                           text=("固定" if self.fixed else "置顶") if on else "")
        self.itemconfigure(self._pinbar, state="normal" if on else "hidden")

    def _popup(self, event):
        """右键：置顶 / 隐藏 / 移到回收站。"""
        menu = getattr(self, "_menu", None)
        if menu is None:
            self._menu = menu = tk.Menu(self, tearoff=0)
        menu.delete(0, "end")
        if self.fixed:
            menu.add_command(label="首页固定第一位", state="disabled")
        else:
            menu.add_command(label="取消置顶" if self.pinned else "置顶到最前",
                             command=lambda: self.on_pin(self.key))
        menu.add_separator()
        state = "disabled" if self.protected else "normal"
        menu.add_command(label="隐藏此模块", state=state,
                         command=lambda: self.on_hide(self.key))
        menu.add_command(label="移到回收站", state=state,
                         command=lambda: self.on_delete(self.key))
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _paint(self, hover=False):
        if self.active:
            card, edge = ui.C["sidebar_active"], ui.C["sidebar_active"]
            ibox, icon = "#5b86ea", "white"
            title, sub = "white", "#d9e5ff"
            pin, bar = "#eaf1ff", "white"
        else:
            card = ui.C["sidebar_card_hover"] if hover else ui.C["sidebar_card"]
            edge = ui.C["sidebar_border"]
            ibox, icon = "#34415a", "#a8c2ff"
            title, sub = ("#eef3ff" if hover else "#dfe6f2",
                          "#8e99ab" if hover else "#7d8899")
            pin, bar = ("#9fb6e8" if hover else "#7f8fb0"), ui.C["accent"]
        self.itemconfigure(self._card, fill=card, outline=edge)
        self.itemconfigure(self._ibox, fill=ibox)
        self.itemconfigure(self._icon, fill=icon)
        self.itemconfigure(self._title, fill=title)
        self.itemconfigure(self._sub, fill=sub)
        self.itemconfigure(self._pin, fill=pin)
        self.itemconfigure(self._pinbar, fill=bar)

    def set_active(self, on):
        self.active = on
        self._paint(hover=False)


class App:
    def __init__(self, root, ctx):
        self.tk = root
        self.ctx = ctx
        ctx.app = self
        self.pages = {}        # key -> frame
        self.nav = {}
        self.current = None
        self.usage = usage.load()
        self.sort_mode = usage.get_sort_mode(self.usage)
        self.recording = True          # 自检时不记浏览
        self.modules_data = modules.load()
        self.plugin_errors = []
        self.registry = self._build_registry()
        self.privacy_on = privacy.enabled()

        root.title(f"{APP_TITLE} · 超级工具 v{VERSION}")
        root.geometry("1180x760")
        root.minsize(940, 620)
        root.configure(bg=ui.C["bg"])
        ui.apply_theme(root)

        body = tk.Frame(root, bg=ui.C["bg"])
        body.pack(fill="both", expand=True)

        self.sidebar = tk.Frame(body, bg=ui.C["sidebar"], width=212)
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.propagate(False)

        head = tk.Frame(self.sidebar, bg=ui.C["sidebar"])
        head.pack(fill="x", pady=(20, 14), padx=16)
        tk.Label(head, text=APP_TITLE, font=(ui.UI, 15, "bold"), bg=ui.C["sidebar"],
                 fg="white", anchor="w").pack(fill="x")
        tk.Label(head, text="notes · kb · quiz", font=(ui.UI, 8), bg=ui.C["sidebar"],
                 fg="#6b7688", anchor="w").pack(fill="x")
        self.sort_btn = tk.Label(head, text=f"排序：{SORT_LABEL[self.sort_mode]} ⇄",
                                 font=(ui.UI, 8), bg=ui.C["sidebar"], fg="#8ea6d8",
                                 anchor="w", cursor="hand2")
        self.sort_btn.pack(fill="x", pady=(8, 0))
        self.sort_btn.bind("<Button-1>", lambda _e: self.toggle_sort())

        # 底部固定：隐私开关 + 添加模块 + 版本（先 pack，保证不被导航区挤掉）
        foot = tk.Frame(self.sidebar, bg=ui.C["sidebar"])
        foot.pack(side="bottom", fill="x", padx=16, pady=(0, 12))
        self.privacy_btn = tk.Label(foot, text="", font=(ui.UI, 9),
                                    bg=ui.C["sidebar"], fg="#9fc0ff",
                                    anchor="w", cursor="hand2")
        self.privacy_btn.pack(fill="x", pady=(0, 5))
        self.privacy_btn.bind("<Button-1>", lambda _e: self.toggle_privacy())
        self.privacy_btn.bind("<Enter>", lambda _e: self.privacy_btn.configure(
            fg="#cfe0ff" if self.privacy_on else "#f0cd8a"))
        self.privacy_btn.bind("<Leave>", lambda _e: self._paint_privacy())
        self._paint_privacy()
        add = tk.Label(foot, text="＋ 添加模块", font=(ui.UI, 9),
                       bg=ui.C["sidebar"], fg="#8ea6d8", anchor="w",
                       cursor="hand2")
        add.pack(fill="x", pady=(0, 4))
        add.bind("<Button-1>", lambda _e: self.add_module_dialog())
        add.bind("<Enter>", lambda _e: add.configure(fg="#c3d4f5"))
        add.bind("<Leave>", lambda _e: add.configure(fg="#8ea6d8"))
        tk.Label(foot, text=f"v{VERSION}", font=(ui.UI, 8), bg=ui.C["sidebar"],
                 fg="#5c6675", anchor="w").pack(fill="x")

        # 导航区：模块多了可滚动（滚动条按需显示，避免新模块被折在下面看不见）
        self.nav_holder = tk.Frame(self.sidebar, bg=ui.C["sidebar"])
        self.nav_holder.pack(fill="both", expand=True)
        self.nav_holder.rowconfigure(0, weight=1)
        self.nav_holder.columnconfigure(0, weight=1)
        self.nav_canvas = tk.Canvas(self.nav_holder, bg=ui.C["sidebar"], bd=0,
                                    highlightthickness=0)
        self.nav_bar = ttk.Scrollbar(self.nav_holder, orient="vertical",
                                     command=self.nav_canvas.yview)
        self.nav_canvas.configure(yscrollcommand=self.nav_bar.set)
        self.nav_canvas.grid(row=0, column=0, sticky="nsew")
        self.nav_bar.grid(row=0, column=1, sticky="ns")
        self.nav_bar.grid_remove()
        self._nav_bar_on = False
        self.nav_box = tk.Frame(self.nav_canvas, bg=ui.C["sidebar"])
        self._nav_win = self.nav_canvas.create_window(
            (0, 0), window=self.nav_box, anchor="nw")
        self.nav_box.bind("<Configure>", self._on_nav_body)
        self.nav_canvas.bind("<Configure>", self._on_nav_canvas)
        self.build_nav()

        right = tk.Frame(body, bg=ui.C["bg"])
        right.pack(side="left", fill="both", expand=True)

        self.container = tk.Frame(right, bg=ui.C["bg"])
        self.container.pack(fill="both", expand=True)
        self.container.rowconfigure(0, weight=1)
        self.container.columnconfigure(0, weight=1)

        status = tk.Frame(right, bg="#eaeef6", height=26)
        status.pack(fill="x", side="bottom")
        status.pack_propagate(False)
        self.status = tk.Label(status, text="", font=(ui.UI, 8), bg="#eaeef6",
                               fg=ui.C["muted"], anchor="w")
        self.status.pack(side="left", padx=12)
        tk.Label(status, text=str(ctx.root), font=(ui.UI, 8), bg="#eaeef6",
                 fg=ui.C["muted"], anchor="e").pack(side="right", padx=12)

    # ---------------------------------------------------------------- 模块注册表
    @staticmethod
    def _static_entry(key):
        icon, title, sub, mod_name, weight = PAGES[key]
        return {"key": key, "icon": icon, "title": title, "sub": sub,
                "module": mod_name, "weight": weight, "kind": "builtin",
                "item": None, "hidden": False, "deleted_at": None,
                "protected": key in PROTECTED}

    def _entry_from_state(self, base, key):
        st = modules.state(self.modules_data, key)
        if key in PROTECTED:
            st = {}
        base["hidden"] = bool(st.get("hidden"))
        base["deleted_at"] = st.get("deleted_at")
        base["protected"] = key in PROTECTED
        return base

    def _build_registry(self):
        reg = {}
        for key in PAGES:
            if modules.is_purged(self.modules_data, key) and key not in PROTECTED:
                continue
            reg[key] = self._entry_from_state(self._static_entry(key), key)

        for item in self.modules_data.get("custom", []):
            key = modules.CUSTOM_PREFIX + item["id"]
            if modules.is_purged(self.modules_data, key):
                continue
            reg[key] = self._entry_from_state({
                "key": key,
                "icon": item.get("icon") or modules.TYPE_ICON.get(item.get("target_type"), "◆"),
                "title": item.get("title") or "未命名模块",
                "sub": item.get("sub") or modules.TYPE_LABEL.get(item.get("target_type"), "快捷模块"),
                "module": "pages.custom",
                "weight": modules.PLUGIN_WEIGHT,
                "kind": "shortcut",
                "item": item,
                "protected": False,
            }, key)

        plugins, errors = modules.scan_plugins()
        self.plugin_errors = errors
        for p in plugins:
            if modules.is_purged(self.modules_data, p["key"]):
                continue
            reg[p["key"]] = self._entry_from_state({
                "key": p["key"], "icon": p["icon"], "title": p["title"],
                "sub": p["sub"], "module": None, "weight": p["weight"],
                "kind": "plugin", "item": p, "protected": False,
            }, p["key"])
        return reg

    def module_keys(self, include_deleted=False, include_hidden=True):
        return [k for k, e in self.registry.items()
                if (include_deleted or not e["deleted_at"])
                and (include_hidden or not e["hidden"])]

    # ---------------------------------------------------------------- 导航排序
    def _order(self, include_hidden=False):
        """首页永远第一 → 置顶页（按置顶顺序）→ 其余按当前排序模式。"""
        keys = self.module_keys(include_hidden=include_hidden)
        pins = [k for k in usage.get_pins(self.usage) if k in keys and k != "home"]
        rest = [k for k in keys if k != "home" and k not in pins]

        def stat(k):
            rec = self.usage.get(k, {})
            total = int(rec.get("total", 0))
            if self.sort_mode == "total":
                return (-total, -usage.recent(rec), -self.registry[k]["weight"])
            return (-usage.recent(rec), -total, -self.registry[k]["weight"])

        if self.sort_mode == "default":
            rest.sort(key=lambda k: -self.registry[k]["weight"])
        else:
            rest.sort(key=stat)
        return (["home"] if "home" in keys else []) + pins + rest

    def build_nav(self):
        """按当前排序模式重排左侧卡片；模块被删/隐藏时移除对应卡片。"""
        order = self._order()
        for key in list(self.nav):
            if key not in order:
                self.nav.pop(key).destroy()
        for key in order:
            entry = self.registry[key]
            card = self.nav.get(key)
            if card is None:
                card = NavCard(self.nav_box, key, entry["icon"], entry["title"],
                               entry["sub"], lambda k=key: self.goto(k),
                               self.toggle_pin, self.hide_module,
                               self.recycle_module, fixed=(key == "home"),
                               protected=entry["protected"],
                               on_wheel=self._nav_wheel)
                self.nav[key] = card
            else:
                card.set_labels(entry["icon"], entry["title"], entry["sub"])
            card.pack_forget()
            card.pack(padx=10, pady=(0, 6))
        self._update_marks()

    def _on_nav_body(self, _event=None):
        self.nav_canvas.configure(scrollregion=self.nav_canvas.bbox("all"))
        need = self.nav_box.winfo_reqheight() > self.nav_canvas.winfo_height()
        if need != self._nav_bar_on:
            self._nav_bar_on = need
            if need:
                self.nav_bar.grid()
            else:
                self.nav_bar.grid_remove()
            if self.current:                 # 布局完再保证当前页可见
                self.tk.after_idle(
                    lambda: self._ensure_nav_visible(self.current))

    def _ensure_nav_visible(self, key):
        """当前页的卡片折在可视区外时，把侧栏滚过去。"""
        card = self.nav.get(key)
        if card is None or not self._nav_bar_on:
            return
        self.nav_canvas.update_idletasks()
        top = self.nav_canvas.canvasy(0)
        height = self.nav_canvas.winfo_height()
        total = max(self.nav_box.winfo_height(), 1)
        y, h = card.winfo_y(), card.winfo_height()
        if y < top:
            self.nav_canvas.yview_moveto(max(0.0, y / total))
        elif y + h > top + height:
            self.nav_canvas.yview_moveto(min(1.0, (y + h - height) / total))

    def _on_nav_canvas(self, event):
        self.nav_canvas.itemconfigure(self._nav_win, width=event.width)
        self._on_nav_body()

    def _nav_wheel(self, event):
        self.nav_canvas.yview_scroll(-int(event.delta / 120), "units")

    def toggle_sort(self):
        idx = SORT_MODES.index(self.sort_mode) if self.sort_mode in SORT_MODES else 0
        self.sort_mode = SORT_MODES[(idx + 1) % len(SORT_MODES)]
        usage.set_sort_mode(self.sort_mode, self.usage)
        self.sort_btn.configure(text=f"排序：{SORT_LABEL[self.sort_mode]}")
        self.build_nav()
        self.refresh_status()

    # ---------------------------------------------------------------- 隐私模式
    def _privacy_label(self):
        return ("◉ 隐私模式：开（已脱敏）" if self.privacy_on
                else "○ 隐私模式：关（明文）")

    def _paint_privacy(self):
        try:
            self.privacy_btn.configure(
                text=self._privacy_label(),
                fg="#9fc0ff" if self.privacy_on else "#e0b25f")
        except (AttributeError, tk.TclError):
            pass

    def toggle_privacy(self):
        self.set_privacy(not self.privacy_on)

    def set_privacy(self, on, notify=True):
        """切脱敏：存本机开关 → 重建已加载页面（设置页自己不含账号字段，留着不重建）。"""
        self.privacy_on = privacy.set_enabled(on)
        self._paint_privacy()
        current = self.current
        self.invalidate(keep="settings" if current == "settings" else None)
        if current and current != "settings":
            rec = self.recording
            self.recording = False
            try:
                self.goto(current)
            finally:
                self.recording = rec
        page = self.pages.get("settings")
        if page is not None and hasattr(page, "sync_privacy"):
            page.sync_privacy()
        if notify:
            self.notify("隐私模式已开启：账号信息 / 公积金余额已脱敏"
                        if self.privacy_on
                        else "隐私模式已关闭：显示完整账号与余额")

    def toggle_pin(self, key):
        """置顶/取消置顶（首页固定，不参与）。"""
        if key == "home":
            return
        self.usage, _pinned = usage.toggle_pin(key, self.usage)
        self.build_nav()
        self.refresh_status()
        page = self.pages.get("settings")
        if page is not None and hasattr(page, "refresh"):
            page.refresh()

    def _update_marks(self):
        pins = set(usage.get_pins(self.usage))
        for key, card in self.nav.items():
            card.set_pinned(key == "home" or key in pins)

    # ---------------------------------------------------------------- 模块管理
    def _apply_modules(self):
        """配置变了：重算注册表、清掉已删页面的缓存、重排侧栏。"""
        self.registry = self._build_registry()
        for key in list(self.pages):
            entry = self.registry.get(key)
            if entry is None or entry["deleted_at"]:
                self.pages.pop(key).destroy()
                if key in self.ctx.loaded:
                    self.ctx.loaded.remove(key)
        self.build_nav()
        cur = self.registry.get(self.current) if self.current else None
        if cur is None or cur["deleted_at"]:
            self._switch_home()
        self.refresh_status()
        page = self.pages.get("settings")
        if page is not None and hasattr(page, "refresh_modules"):
            page.refresh_modules()

    def _switch_home(self):
        old = self.recording
        self.recording = False
        try:
            self.goto("home")
        finally:
            self.recording = old

    def notify(self, msg):
        self.status.configure(text=msg)
        self.tk.after(4000, self._restore_status)

    def _restore_status(self):
        try:
            if self.tk.winfo_exists():
                self.refresh_status()
        except tk.TclError:
            pass

    def hide_module(self, key=None):
        key = key or self.current
        entry = self.registry.get(key)
        if entry is None or entry["protected"]:
            self.notify("首页与设置页固定，不能隐藏")
            return
        on = not entry["hidden"]
        modules.set_hidden(self.modules_data, key, on)
        if on and self.current == key:
            self._switch_home()
        self._apply_modules()
        self.notify(("已隐藏：" if on else "已恢复显示：") + entry["title"])

    def recycle_module(self, key):
        entry = self.registry.get(key)
        if entry is None or entry["protected"] or entry["deleted_at"]:
            if entry is not None and entry["protected"]:
                self.notify("首页与设置页固定，不能删除")
            return
        if not messagebox.askyesno(
                "移到回收站",
                f"把「{entry['title']}」移到回收站？\n\n"
                "模块配置不会删除，随时可以在「设置 → 回收站」还原。",
                parent=self.tk):
            return
        modules.recycle(self.modules_data, key)
        if self.current == key:
            self._switch_home()
        self._apply_modules()
        self.notify("已移到回收站：" + entry["title"])

    def restore_module(self, key):
        modules.restore(self.modules_data, key)
        self._apply_modules()
        entry = self.registry.get(key)
        self.notify("已还原：" + (entry["title"] if entry else key))

    def purge_module(self, key):
        entry = self.registry.get(key)
        if entry is None:
            return
        if entry["protected"]:
            self.notify("首页与设置页固定，不能彻底删除")
            return
        kind = entry["kind"]
        extra = {
            "shortcut": "快捷模块的配置会被删除，目标文件不受影响。",
            "plugin": "插件 .py 会移到 data/hub/modules/.trash/（仍可手动找回）。",
            "builtin": "内置模块只是从侧栏移除，可用「重置侧栏」找回。",
        }[kind]
        if not messagebox.askyesno(
                "彻底删除",
                f"彻底删除「{entry['title']}」？\n\n{extra}\n\n此操作不可在界面撤销。",
                parent=self.tk):
            return
        modules.purge(self.modules_data, key)
        if self.current == key:
            self._switch_home()
        self._apply_modules()
        self.notify("已彻底删除：" + entry["title"])

    def reset_modules(self):
        if not messagebox.askyesno(
                "重置侧栏",
                "恢复全部内置模块（清除隐藏/回收站标记）？\n\n"
                "自定义模块与插件不动，回收站里它们仍可还原。",
                parent=self.tk):
            return
        modules.reset_builtin(self.modules_data, set(PAGES))
        self._apply_modules()
        self.notify("已恢复全部内置模块")

    def add_module_dialog(self):
        """侧栏「＋ 添加模块」与设置页共用同一个对话框。"""
        from pages.module_edit import ModuleDialog
        dlg = ModuleDialog(self.tk, self.ctx)
        self.tk.wait_window(dlg)
        if dlg.result:
            return self.add_module(dlg.result)
        return None

    def add_module(self, fields):
        item = modules.add_custom(self.modules_data, **fields)
        key = modules.CUSTOM_PREFIX + item["id"]
        self._apply_modules()
        self.goto(key)
        self.notify("已添加模块：" + item["title"])
        return key

    def edit_module(self, key):
        item = modules.get_item(self.modules_data, key)
        if item is None:
            return
        from pages.module_edit import ModuleDialog
        dlg = ModuleDialog(self.tk, self.ctx, item)
        self.tk.wait_window(dlg)
        if not dlg.result:
            return
        modules.update_custom(self.modules_data, key, **dlg.result)
        if key in self.pages:
            self.pages.pop(key).destroy()
            if key in self.ctx.loaded:
                self.ctx.loaded.remove(key)
        self._apply_modules()
        if self.current == key:
            old = self.recording
            self.recording = False
            try:
                self.goto(key)
            finally:
                self.recording = old
        self.notify("已保存模块：" + dlg.result["title"])

    def create_plugin(self, name):
        path = modules.create_plugin(name)
        self._apply_modules()
        self.notify(f"插件模板已创建：{path}")
        return path

    # ---------------------------------------------------------------- 路由
    def _error_page(self, key, exc):
        frame = tk.Frame(self.container, bg=ui.C["bg"])
        tk.Label(frame, text="模块加载失败", font=ui.F["h2"], bg=ui.C["bg"],
                 fg=ui.C["bad"]).pack(anchor="w", padx=30, pady=(30, 8))
        tk.Label(frame, text=f"{key}\n{exc}", font=ui.F["body"], bg=ui.C["bg"],
                 fg=ui.C["text"], wraplength=760, justify="left").pack(
                     anchor="w", padx=30)
        tk.Label(frame, text="设置 → 侧栏模块 里可以编辑或把它移到回收站。",
                 font=ui.F["small"], bg=ui.C["bg"], fg=ui.C["muted"]).pack(
                     anchor="w", padx=30, pady=(14, 0))
        frame.grid(row=0, column=0, sticky="nsew")
        return frame

    def _ensure_page(self, key, entry):
        if key in self.pages:
            return self.pages[key]
        try:
            if entry["kind"] == "builtin":
                mod = importlib.import_module(entry["module"])  # ← 懒加载
                frame = mod.make(self.container, self.ctx, self)
            elif entry["kind"] == "shortcut":
                mod = importlib.import_module("pages.custom")
                frame = mod.make(self.container, self.ctx, self, key)
            else:
                mod = modules.load_plugin(key)
                frame = mod.make(self.container, self.ctx, self)
        except Exception as e:            # 插件/自定义模块出错不拖垮整个外壳
            frame = self._error_page(key, e)
        if not frame.winfo_manager():
            frame.grid(row=0, column=0, sticky="nsew")
        self.pages[key] = frame
        if key not in self.ctx.loaded:
            self.ctx.loaded.append(key)
        return frame

    def goto(self, key, record=True, force=False, **kw):
        entry = self.registry.get(key)
        if entry is None and force and key in PAGES:
            entry = self._static_entry(key)
        if entry is None or entry.get("deleted_at"):
            if key != "home":
                self.notify(f"模块不可用：{key}（已隐藏或移入回收站）")
            key = "home"
            entry = self.registry.get("home") or self._static_entry("home")
        frame = self._ensure_page(key, entry)
        if record and self.recording:
            self.usage = usage.record(key, self.usage)   # 返回合并视图（多机相加）
        for k, btn in self.nav.items():
            btn.set_active(k == key)
        self.current = key
        frame.tkraise()
        self._ensure_nav_visible(key)
        if hasattr(frame, "on_show"):
            frame.on_show(**kw)
        self.refresh_status()

    def invalidate(self, keep=None):
        """数据源变了（建库 / 换范围）：销毁除设置页外的缓存页面，下次访问重建。"""
        for k in list(self.pages):
            if k in (keep, "settings"):
                continue
            self.pages.pop(k).destroy()
            if k in self.ctx.loaded:
                self.ctx.loaded.remove(k)
        self.ctx.loaded = list(self.pages)

    def refresh_status(self):
        names = " + ".join(self.registry[k]["title"] for k in self.ctx.loaded
                           if k in self.registry) or "无"
        pins = [self.registry[k]["title"] for k in usage.get_pins(self.usage)
                if k in self.registry and k != "home" and not self.registry[k]["deleted_at"]]
        hidden = len(modules.hidden_keys(self.modules_data))
        deleted = len(modules.deleted_keys(self.modules_data))
        self.status.configure(
            text=f"已加载：{names}　｜　排序：{SORT_LABEL[self.sort_mode]}"
                 f"　｜　置顶：{'、'.join(pins) if pins else '无'}"
                 f"　｜　模块 {len(self.registry)} · 隐藏 {hidden} · 回收站 {deleted}")

    # ---------------------------------------------------------------- 生命周期
    def selftest(self, out_path=None):
        """构建全部内置页面（触发懒加载），结果写文件 + 尽力打印。返回是否通过。"""
        lines = []
        ok = False
        self.recording = False          # 自检产生的访问不计入统计
        try:
            for key in NAV_ORDER:
                self.goto(key, force=True)
                lines.append(f"page ok: {key}")
            self.goto("quiz", subject=None, force=True)
            self.goto("home", force=True)
            self.tk.update_idletasks()
            lines.append("已加载页面：" + ", ".join(self.ctx.loaded))
            lines.append("仓库根：" + str(self.ctx.root))
            lines.append("科目：" + ", ".join(self.ctx.subjects()))
            lines.append("模块数：" + str(len(self.registry)))
            lines.append("selftest OK")
            ok = True
        except Exception:
            import traceback
            lines.append("selftest FAILED")
            lines.append(traceback.format_exc())
        text = "\n".join(lines)
        if out_path:
            try:
                with open(out_path, "w", encoding="utf-8") as f:
                    f.write(text)
            except OSError:
                pass
        try:                       # windowed 打包后没有控制台，print 可能不可用
            print(text)
        except Exception:
            pass
        return ok


def _alert(text, error=False):
    """无控制台的 windowed exe 里也能把结果告诉用户（手动跑 --mail-test 时）。"""
    try:
        import ctypes
        icon = 0x10 if error else 0x40
        ctypes.windll.user32.MessageBoxW(None, text, "hub 邮件测试", icon)
    except Exception:
        pass


def main(argv):
    page = None
    root_dir = None
    selftest = "--selftest" in argv
    if "--page" in argv:
        page = argv[argv.index("--page") + 1]
    if "--root" in argv:
        root_dir = argv[argv.index("--root") + 1]
        # 核心模块用 paths.find_repo_root() 找数据目录，统一走同一个根
        os.environ["HUB_ROOT"] = os.path.abspath(os.path.expanduser(root_dir))

    # 邮件：--mail-test 发一封测试信；--remind 发每日提醒（计划任务调用）
    if "--mail-test" in argv or "--remind" in argv:
        from core import mailer, reminder
        ctx = Ctx(root_dir)
        cfg = mailer.load()
        try:
            if "--mail-test" in argv:
                info = mailer.send_test(cfg)
                mailer.write_log("测试邮件 OK → " + "、".join(info["recipients"]))
                _alert("测试邮件已发送 → " + "、".join(info["recipients"]))
                return 0
            if not cfg["daily"]["enabled"]:
                mailer.write_log("跳过每日提醒：未启用")
                return 0
            subject, body = reminder.digest(ctx)
            info = mailer.send(cfg, subject, body)
            cfg["daily"]["last_sent"] = datetime.now().strftime("%Y-%m-%d %H:%M")
            try:
                mailer.save(cfg)
            except mailer.MailError:
                pass
            mailer.write_log("提醒已发送 → " + "、".join(info["recipients"]))
            return 0
        except mailer.MailError as e:
            mailer.write_log("发送失败：" + str(e).replace("\n", " "))
            if "--mail-test" in argv:
                _alert("发送失败：\n\n" + str(e), error=True)
            return 1

    # 计划任务入口：hub.exe --xhs-sync（不开 GUI，只跑导出 + 写日志）
    if "--xhs-sync" in argv:
        from core import xhs_sync
        return xhs_sync.main_cli()

    # 抖音：--douyin-sync 同步全部账号；--douyin-login 扫码；--douyin-probe 抓原始响应
    if "--douyin-sync" in argv:
        from core import douyin_sync
        return douyin_sync.main_cli()
    if "--douyin-login" in argv:
        from core import douyin_sync
        return douyin_sync.login_cli()
    if "--douyin-probe" in argv:
        from core import douyin_sync
        return douyin_sync.probe_cli()

    # 欧路词典：--eudic-sync 同步全部账号；加 --full 全量重建
    if "--eudic-sync" in argv:
        from core import eudic
        return eudic.sync_all_cli(full="--full" in argv)

    # 调试/兜底：命令行扫码登录
    if "--xhs-login" in argv:
        from core import xhs_sync
        return xhs_sync.login_cli()

    # 支付宝账单：扫码登录 + 拉一次账单
    if "--bill-login" in argv:
        from core import bill_sync
        return bill_sync.login_cli()

    # 每日总同步：抖音 + 小红书 + 支付宝账单 + 欧路词典
    if "--daily-sync" in argv:
        from core import bill_sync, douyin_sync, eudic, xhs_sync
        rc_dy = douyin_sync.main_cli()
        rc_xhs = xhs_sync.main_cli()
        try:
            bill_sync.sync_alipay(days=180)
            rc_bill = 0
        except Exception as e:                            # noqa: BLE001
            bill_sync.write_log(f"账单同步失败：{e}")
            rc_bill = 1
        rc_eudic = eudic.sync_all_cli()
        return 0 if (rc_dy == 0 or rc_xhs == 0 or rc_bill == 0 or rc_eudic == 0) else 1

    try:
        from ctypes import windll
        windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass

    ctx = Ctx(root_dir)

    root = tk.Tk()
    app = App(root, ctx)

    if selftest:
        ok = app.selftest(os.environ.get("HUB_SELFTEST_OUT"))
        root.destroy()
        return 0 if ok else 1

    app.goto(page or "home")
    if os.environ.get("HUB_AUTOSTART"):
        frame = app.pages.get(app.current)
        if hasattr(frame, "start"):
            frame.start()

    # 后台盯着 Downloads：支付宝导出文件一落地就自动解析入库
    def _bill_watch():
        import time as _time
        from core import bill_sync
        while True:
            try:
                bill_sync.scan_downloads()
            except Exception:                    # noqa: BLE001
                pass
            _time.sleep(300)

    import threading
    threading.Thread(target=_bill_watch, daemon=True).start()

    # 居中
    root.update_idletasks()
    w, h = root.winfo_width(), root.winfo_height()
    x = (root.winfo_screenwidth() - w) // 2
    y = (root.winfo_screenheight() - h) // 2 - 30
    root.geometry(f"+{x}+{y}")

    # 开发用：HUB_SHOT=路径 时截取窗口并退出（依赖 Pillow，打包版无此依赖）
    shot = os.environ.get("HUB_SHOT")
    if shot:
        root.attributes("-topmost", True)
        root.lift()

        def grab():
            try:
                # 动态导入：避免 PyInstaller 静态分析把 Pillow/numpy 打进发行包
                grab_mod = __import__("PIL.ImageGrab", fromlist=["grab"])
                x0, y0 = root.winfo_rootx(), root.winfo_rooty()
                grab_mod.grab(bbox=(x0, y0, x0 + root.winfo_width(),
                                    y0 + root.winfo_height())).save(shot)
                print("shot saved:", shot)
            except Exception as e:            # pragma: no cover
                print("shot failed:", e)
            finally:
                root.destroy()
        delay = int(os.environ.get("HUB_SHOT_DELAY", "1500"))
        root.after(delay, grab)

    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
