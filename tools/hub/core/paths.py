# -*- coding: utf-8 -*-
"""路径定位：仓库根 / notes / kb / data（源码运行与打包后都适用）。

数据统一放仓库内的 `data/`（分类见 data/README.md），不再写 %APPDATA%。
"""
import os
import shutil
import sys
from pathlib import Path

FROZEN = bool(getattr(sys, "frozen", False))


def base_dir():
    if FROZEN:
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent   # tools/hub/


def find_repo_root(explicit=None):
    for cand in (explicit, os.environ.get("HUB_ROOT")):
        if cand:
            p = Path(cand).expanduser()
            if p.is_dir():
                return p.resolve()
    cands = []
    for p in (base_dir(), *base_dir().parents):
        cands.append(p)
    cands.append(Path.cwd())
    for p in cands:
        try:
            if (p / "notes" / "kb").is_dir():
                return p.resolve()
        except OSError:
            continue
    return Path.cwd()


# ---------------------------------------------------------------- 数据目录
def data_dir(*parts, create=True):
    """项目级数据目录：<仓库根>/data[/parts...]。

    所有运行数据都跟着项目走（同一块盘、一起备份/迁移），不再落到 C 盘用户目录。
    """
    d = find_repo_root() / "data"
    if parts:
        d = d.joinpath(*parts)
    if create:
        try:
            d.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
    return d


def legacy_data_dir(*parts):
    """旧版位置：%APPDATA%\\self-knowledge-hub\\...（迁移完就该不存在了）。"""
    base = os.environ.get("APPDATA") or str(Path.home())
    return Path(base).joinpath("self-knowledge-hub", *parts)


def adopt_legacy(src, dst):
    """把旧位置的数据搬进项目 data/：只补齐 dst 里没有的文件，不覆盖。返回搬了几个。"""
    moved = 0
    try:
        if src.is_file() and not dst.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            return 1
        if not src.is_dir():
            return 0
        for p in src.rglob("*"):
            if not p.is_file():
                continue
            target = dst / p.relative_to(src)
            if target.exists():
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, target)
            moved += 1
    except OSError:
        pass
    return moved


class Ctx:
    """全局只读上下文：路径 + 应用引用。"""

    def __init__(self, root=None):
        self.root = find_repo_root(root)
        self.notes = self.root / "notes"
        self.kb = self.notes / "kb"
        self.app = None            # 由 hub 注入，用于导航
        self.loaded = []           # 已懒加载的页面 key（状态栏展示用）

    def subjects(self):
        try:
            return sorted(p.name for p in self.kb.iterdir() if p.is_dir())
        except OSError:
            return []

    # ---------------------------------------------------------- 文件访问
    def note_rels(self):
        """全部笔记的相对路径。"""
        rels = set()
        try:
            for p in self.notes.rglob("*.md"):
                rels.add(p.relative_to(self.root).as_posix())
        except OSError:
            pass
        return sorted(rels)

    def read_text(self, rel):
        rel = rel.replace("\\", "/")
        return (self.root / rel).read_text(encoding="utf-8")

    def write_text(self, rel, text):
        rel = rel.replace("\\", "/")
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")

    def mtime(self, rel):
        try:
            return (self.root / rel.replace("\\", "/")).stat().st_mtime
        except OSError:
            return None
