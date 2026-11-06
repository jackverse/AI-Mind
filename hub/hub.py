# -*- coding: utf-8 -*-
"""AI-Mind — 抖音 / 小红书数据工作台（桌面端）。

只做两件事：抖音账号数据、小红书账号数据。页面懒加载，数据来自 `--root` / `HUB_ROOT`
指向的数据仓库（`data/hub/`），代码仓库本身不放数据。

用法：
  python hub/hub.py                      # 打开壳（默认抖音）
  python hub/hub.py --page xhs           # 直接进小红书
  python hub/hub.py --selftest           # 构建两个页面后退出（回归自检）
  python hub/hub.py --root D:\\path\\to\\vault
  python hub/hub.py --douyin-sync        # 无窗口同步（计划任务用）
  python hub/hub.py --xhs-sync
  python hub/hub.py --daily-sync         # 抖音 + 小红书
"""
import importlib
import os
import sys
import tkinter as tk

import ui
from core import privacy
from core.paths import Ctx

APP_TITLE = "AI-Mind · 抖音 / 小红书"
VERSION = "0.0.1"

PAGES = {
    "douyin": ("♪", "抖音", "账号数据", "pages.douyin"),
    "xhs": ("✿", "小红书", "笔记数据", "pages.xhs"),
}
NAV_ORDER = ["douyin", "xhs"]


def _round_rect(cv, x0, y0, x1, y1, r, **kw):
    pts = [x0 + r, y0, x1 - r, y0, x1, y0, x1, y0 + r, x1, y1 - r, x1, y1,
           x1 - r, y1, x0 + r, y1, x0, y1, x0, y1 - r, x0, y0 + r, x0, y0]
    return cv.create_polygon(pts, smooth=True, **kw)


class NavCard(tk.Canvas):
    """侧栏卡片：图标 + 标题 + 副标题，悬停/选中换色。"""

    W, H = 178, 60

    def __init__(self, master, icon, title, sub, command):
        super().__init__(master, width=self.W, height=self.H, bd=0,
                         highlightthickness=0, bg=ui.C["sidebar"], cursor="hand2")
        self.command = command
        self.active = False
        self._card = _round_rect(self, 1, 1, self.W - 1, self.H - 1, 12,
                                 fill=ui.C["sidebar_card"],
                                 outline=ui.C["sidebar_border"], width=1)
        self._ibox = _round_rect(self, 13, 15, 43, 45, 9, fill="#34415a", outline="")
        self._icon = self.create_text(28, 30, text=icon, fill="#a8c2ff",
                                      font=(ui.UI, 11, "bold"))
        self._title = self.create_text(55, 23, text=title, anchor="w",
                                       fill="#dfe6f2", font=(ui.UI, 11, "bold"))
        self._sub = self.create_text(55, 41, text=sub, anchor="w",
                                     fill="#7d8899", font=(ui.UI, 8))
        self.bind("<Button-1>", lambda _e: self.command())
        self.bind("<Enter>", lambda _e: self._paint(hover=True))
        self.bind("<Leave>", lambda _e: self._paint(hover=False))

    def set_active(self, on):
        self.active = bool(on)
        self._paint()

    def _paint(self, hover=False):
        if self.active:
            card, edge, ibox, icon = (ui.C["sidebar_active"], ui.C["sidebar_active"],
                                      "#5b86ea", "white")
            title, sub = "white", "#d9e5ff"
        else:
            card = ui.C["sidebar_card_hover"] if hover else ui.C["sidebar_card"]
            edge = ui.C["sidebar_border"]
            ibox, icon = "#34415a", "#a8c2ff"
            title, sub = ("#eef3ff" if hover else "#dfe6f2",
                          "#8e99ab" if hover else "#7d8899")
        self.itemconfigure(self._card, fill=card, outline=edge)
        self.itemconfigure(self._ibox, fill=ibox)
        self.itemconfigure(self._icon, fill=icon)
        self.itemconfigure(self._title, fill=title)
        self.itemconfigure(self._sub, fill=sub)


class App:
    def __init__(self, root, ctx):
        self.tk = root
        self.ctx = ctx
        self.pages = {}
        self.nav = {}
        self.current = None
        self.privacy_on = privacy.enabled()
        root.title(f"{APP_TITLE}  v{VERSION}")
        root.geometry("1180x760")
        root.minsize(920, 600)
        ui.apply_theme(root)
        self._build()

    # ---------------------------------------------------------------- 布局
    def _build(self):
        self.side = tk.Frame(self.tk, bg=ui.C["sidebar"], width=200)
        self.side.pack(side="left", fill="y")
        self.side.pack_propagate(False)

        brand = tk.Frame(self.side, bg=ui.C["sidebar"])
        brand.pack(fill="x", padx=18, pady=(22, 4))
        tk.Label(brand, text="AI-Mind", font=(ui.UI, 16, "bold"),
                 bg=ui.C["sidebar"], fg="white").pack(anchor="w")
        tk.Label(brand, text="抖音 / 小红书", font=(ui.UI, 9),
                 bg=ui.C["sidebar"], fg="#7d8899").pack(anchor="w", pady=(2, 0))

        self.nav_box = tk.Frame(self.side, bg=ui.C["sidebar"])
        self.nav_box.pack(fill="x", padx=10, pady=(18, 0))
        for key in NAV_ORDER:
            icon, title, sub, _mod = PAGES[key]
            card = NavCard(self.nav_box, icon, title, sub, lambda k=key: self.goto(k))
            card.pack(fill="x", pady=(0, 8))
            self.nav[key] = card

        foot = tk.Frame(self.side, bg=ui.C["sidebar"])
        foot.pack(side="bottom", fill="x", padx=16, pady=14)
        self.privacy_btn = tk.Label(foot, text="", font=(ui.UI, 9),
                                    bg=ui.C["sidebar"], cursor="hand2")
        self.privacy_btn.pack(fill="x", pady=(0, 6))
        self.privacy_btn.bind("<Button-1>", lambda _e: self.toggle_privacy())
        tk.Label(foot, text=f"v{VERSION}", font=(ui.UI, 8),
                 bg=ui.C["sidebar"], fg="#5d6878").pack(anchor="w")
        self._paint_privacy()

        self.main = tk.Frame(self.tk, bg=ui.C["bg"])
        self.main.pack(side="left", fill="both", expand=True)
        self.content = tk.Frame(self.main, bg=ui.C["bg"])
        self.content.pack(fill="both", expand=True)
        self.status = tk.Label(self.main, text="", font=ui.F["small"], anchor="w",
                               bg="#eef2f8", fg=ui.C["muted"], padx=14, pady=5)
        self.status.pack(fill="x", side="bottom")
        self._restore_status()

    # ---------------------------------------------------------------- 路由
    def goto(self, key, **kw):
        if key not in PAGES:
            key = NAV_ORDER[0]
        if key not in self.pages:
            mod = importlib.import_module(PAGES[key][3])
            self.pages[key] = mod.make(self.content, self.ctx, self)
        for frame in self.pages.values():
            frame.pack_forget()
        frame = self.pages[key]
        frame.pack(fill="both", expand=True)
        self.current = key
        for k, card in self.nav.items():
            card.set_active(k == key)
        if hasattr(frame, "on_show"):
            frame.on_show(**kw)
        self.ctx.loaded = list(self.pages)
        self._restore_status()

    def _restore_status(self):
        root = str(self.ctx.root)
        if len(root) > 78:
            root = root[:34] + " … " + root[-36:]
        self.status.configure(text=f"数据仓库：{root}")

    def notify(self, msg, ms=4000):
        self.status.configure(text=msg)
        self.tk.after(ms, self._restore_status)

    # ---------------------------------------------------------------- 隐私
    def _privacy_label(self):
        return ("◉ 隐私模式：开（已脱敏）" if self.privacy_on
                else "○ 隐私模式：关（明文）")

    def _paint_privacy(self):
        self.privacy_btn.configure(
            text=self._privacy_label(),
            fg="#9fc0ff" if self.privacy_on else "#e0b25f")

    def toggle_privacy(self):
        self.set_privacy(not self.privacy_on)

    def set_privacy(self, on, notify=True):
        self.privacy_on = privacy.set_enabled(on)
        self._paint_privacy()
        current = self.current
        for frame in self.pages.values():
            frame.destroy()
        self.pages.clear()
        self.ctx.loaded = []
        if current:
            self.goto(current)
        if notify:
            self.notify("隐私模式已开启：账号信息已脱敏"
                        if self.privacy_on
                        else "隐私模式已关闭：显示完整账号")

    # ---------------------------------------------------------------- 自检
    def selftest(self, out_path=None):
        lines, ok = [], False
        try:
            for key in NAV_ORDER:
                self.goto(key)
                lines.append(f"page ok: {key}")
            self.tk.update_idletasks()
            lines.append("已加载页面：" + ", ".join(self.ctx.loaded))
            lines.append("仓库根：" + str(self.ctx.root))
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
        try:
            print(text)
        except Exception:
            pass
        return ok


# ---------------------------------------------------------------- 入口
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

    if "--douyin-sync" in argv:
        from core import douyin_sync
        return douyin_sync.main_cli()
    if "--douyin-login" in argv:
        from core import douyin_sync
        return douyin_sync.login_cli()
    if "--douyin-probe" in argv:
        from core import douyin_sync
        return douyin_sync.probe_cli()
    if "--xhs-sync" in argv:
        from core import xhs_sync
        return xhs_sync.main_cli()
    if "--xhs-login" in argv:
        from core import xhs_sync
        return xhs_sync.login_cli()
    if "--daily-sync" in argv:
        from core import douyin_sync, xhs_sync
        rc_dy = douyin_sync.main_cli()
        rc_xhs = xhs_sync.main_cli()
        return 0 if (rc_dy == 0 or rc_xhs == 0) else 1

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

    app.goto(page or NAV_ORDER[0])
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
