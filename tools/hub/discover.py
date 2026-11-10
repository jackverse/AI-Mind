# -*- coding: utf-8 -*-
"""自动发现：往后加模块不用改 hub.py。

两条扩展点，约定都写在模块文件自己的顶部：

1. 页面（侧栏一页）
   pages/foo.py 里写
       META = {"icon": "✦", "title": "名字", "sub": "副标题", "weight": 50}
   然后实现 make(master, ctx, app) -> tk.Frame（可再加 on_show(**kw)）。
   hub.py 不用改一行，重启即出现在侧栏。

2. 每日任务（--daily-sync 会跑）
   core/foo_sync.py 里写
       DAILY = {"label": "抖音", "func": "main_cli", "weight": 50}
   func 是模块内的零参函数（返回 0 成功）。加数据源也不用改 hub.py。

为什么还要 pages/_manifest.py：
  PyInstaller 打 onedir exe 后 `pages/*.py` 源码不在磁盘上（进了 PYZ 归档），
  静态扫描扫不到，所以打包前用 `python discover.py --write` 把当时的
  META 固化成 pages/_manifest.py（普通模块，跟着进 exe）。
  开发态永远以源码为准，_manifest 只是 exe 的兜底。

命令行：
  python tools/hub/discover.py                 # 看当前发现结果
  python tools/hub/discover.py --write         # 重新生成 pages/_manifest.py
  python tools/hub/discover.py --hidden-imports # 给 build.ps1 用的模块名列表
"""
import ast
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PAGES_DIR = HERE / "pages"
CORE_DIR = HERE / "core"

SKIP_PREFIX = ("_", ".")
DEFAULT_WEIGHT = 50
DEFAULT_ICON = "✦"


# ---------------------------------------------------------------- 静态解析
def read_literal(path, name):
    """静态读顶层 `name = <字面量>`，不执行代码（插件/页面写坏了不影响启动）。"""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    except (OSError, SyntaxError, ValueError, UnicodeDecodeError):
        return None
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for tgt in node.targets:
            if isinstance(tgt, ast.Name) and tgt.id == name:
                try:
                    return ast.literal_eval(node.value)
                except (ValueError, SyntaxError, TypeError):
                    return None
    return None


def has_function(path, name):
    try:
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    except (OSError, SyntaxError, ValueError, UnicodeDecodeError):
        return False
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return True
    return False


def _py_files(folder):
    try:
        return sorted(p for p in folder.glob("*.py")
                      if not p.name.startswith(SKIP_PREFIX))
    except OSError:
        return []


# ---------------------------------------------------------------- 扫描
def scan_pages(folder=None):
    """返回 {key: (icon, title, sub, module, weight)}；没有 META 的文件直接忽略。"""
    folder = folder or PAGES_DIR
    found = {}
    for path in _py_files(folder):
        meta = read_literal(path, "META")
        if not isinstance(meta, dict):
            continue
        if not has_function(path, "make"):
            continue
        key = path.stem
        title = str(meta.get("title") or key)[:12]
        icon = str(meta.get("icon") or DEFAULT_ICON)[:4]
        sub = str(meta.get("sub") or "")[:20]
        try:
            weight = int(meta.get("weight", DEFAULT_WEIGHT))
        except (TypeError, ValueError):
            weight = DEFAULT_WEIGHT
        found[key] = (icon, title, sub, "pages." + key, weight)
    return found


def scan_daily(folder=None):
    """返回 [{key, label, module, func, weight}]，按 weight 降序。"""
    folder = folder or CORE_DIR
    found = []
    for path in _py_files(folder):
        spec = read_literal(path, "DAILY")
        if not isinstance(spec, dict):
            continue
        func = str(spec.get("func") or "main_cli")
        if not has_function(path, func):
            continue
        try:
            weight = int(spec.get("weight", DEFAULT_WEIGHT))
        except (TypeError, ValueError):
            weight = DEFAULT_WEIGHT
        found.append({
            "key": path.stem,
            "label": str(spec.get("label") or path.stem),
            "module": "core." + path.stem,
            "func": func,
            "weight": weight,
        })
    found.sort(key=lambda d: -d["weight"])
    return found


# ---------------------------------------------------------------- 冻结兜底
def _manifest():
    try:
        from pages import _manifest as m
        return m
    except Exception:                                   # noqa: BLE001
        return None


def pages():
    """开发态扫源码；扫不到（打包后）用 pages/_manifest.py。"""
    found = scan_pages()
    if found:
        return found
    m = _manifest()
    if m is not None and isinstance(getattr(m, "PAGES", None), dict):
        return dict(m.PAGES)
    return {}


def daily_tasks():
    found = scan_daily()
    if found:
        return found
    m = _manifest()
    if m is not None and isinstance(getattr(m, "DAILY", None), list):
        return list(m.DAILY)
    return []


# ---------------------------------------------------------------- 生成
def write_manifest():
    found_pages = scan_pages()
    found_daily = scan_daily()
    if not found_pages:
        raise SystemExit("没扫到任何页面：检查 pages/*.py 里的 META")
    lines = [
        "# -*- coding: utf-8 -*-",
        '"""自动生成，别手改：python tools/hub/discover.py --write',
        "",
        "打包成 exe 后 pages/*.py 源码不在磁盘上，hub 靠这份清单还原侧栏与每日任务。",
        '"""',
        "",
        "PAGES = {",
    ]
    for key in sorted(found_pages, key=lambda k: -found_pages[k][4]):
        lines.append("    %r: %r," % (key, found_pages[key]))
    lines.append("}")
    lines.append("")
    lines.append("DAILY = [")
    for item in found_daily:
        lines.append("    %r," % (item,))
    lines.append("]")
    lines.append("")
    target = PAGES_DIR / "_manifest.py"
    target.write_text("\n".join(lines), encoding="utf-8")
    return target, found_pages, found_daily


def hidden_imports():
    """给 PyInstaller 的 --hidden-import 用：pages / core 下全部模块名。"""
    names = []
    for path in _py_files(PAGES_DIR):
        names.append("pages." + path.stem)
    for path in _py_files(CORE_DIR):
        names.append("core." + path.stem)
    names.append("core.paths")
    names.append("core.modules")
    names.append("pages._manifest")
    seen, out = set(), []
    for n in names:
        if n not in seen:
            seen.add(n)
            out.append(n)
    return out


def main(argv):
    # Windows 控制台默认 GBK，图标里有 ☰ ♪ 这类字符，直接打会 UnicodeEncodeError
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass
    if "--write" in argv:
        target, p, d = write_manifest()
        print("写入 %s：页面 %d 个、每日任务 %d 个"
              % (target.relative_to(HERE.parent.parent), len(p), len(d)))
        return 0
    if "--hidden-imports" in argv:
        for name in hidden_imports():
            print(name)
        return 0
    p = pages()
    d = daily_tasks()
    print("页面 %d 个：" % len(p))
    for key, (icon, title, sub, module, weight) in sorted(p.items(), key=lambda kv: -kv[1][4]):
        print("  %-10s %s %-6s %-12s w=%s  %s" % (key, icon, title, sub, weight, module))
    print("每日任务 %d 个：" % len(d))
    for item in d:
        print("  %-12s %-8s w=%s  %s.%s" % (item["key"], item["label"],
                                             item["weight"], item["module"], item["func"]))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
