# -*- coding: utf-8 -*-
"""侧栏模块注册表：内置模块的覆盖状态 + 自定义快捷模块 + 外部 .py 插件。

内置模块仍写在 hub.PAGES（随 exe 发行）；这里只负责运行期的「可管理」部分：

  · 隐藏 / 移到回收站 / 还原 / 彻底删除
  · 自定义快捷模块（指向笔记、文件夹、网址、程序）
  · 插件目录 data/hub/modules/*.py 的发现与懒加载

存储：data/hub/modules.json（跟着仓库走，不进 git）

{
  "_meta": {"version": 1},
  "custom": [{"id": "ab12cd34", "title": "项目资料", "icon": "▣",
              "sub": "文件夹", "target_type": "folder",
              "target": "D:/jack/project", "created": "..."}],
  "state": {
     "notes": {"hidden": true},
     "custom:ab12cd34": {"deleted_at": "2026-11-02T09:00:00"},
     "plugin:hello": {"purged": true}
  }
}

state 以模块 key 为索引：内置模块直接用 PAGES 的键，自定义用 custom:<id>，
插件用 plugin:<文件名去 .py>。「彻底删除」只对内置模块留 purged 标记，
自定义模块直接删配置、插件把 .py 移进 .trash。
"""
import ast
import importlib.util
import json
import shutil
import uuid
from datetime import datetime
from pathlib import Path

from . import paths

CUSTOM_PREFIX = "custom:"
PLUGIN_PREFIX = "plugin:"

# 目标类型 -> 中文名 / 默认图标 / 默认副标题
TARGET_TYPES = {
    "note": ("笔记", "▤"),
    "folder": ("文件夹", "▣"),
    "url": ("网址", "↗"),
    "app": ("程序/文件", "▶"),
}
TYPE_LABEL = {k: v[0] for k, v in TARGET_TYPES.items()}
TYPE_ICON = {k: v[1] for k, v in TARGET_TYPES.items()}

PLUGIN_WEIGHT = 15          # 新模块默认权重：排在「统计」后、「设置」前
VALID_PLUGIN_SUFFIX = ".py"

_plugin_cache = {}


# ---------------------------------------------------------------- 存储
def store_path():
    return paths.data_dir("hub") / "modules.json"


def plugin_dir():
    return paths.data_dir("hub", "modules")


def _now():
    return datetime.now().isoformat(timespec="seconds")


def _normalize(data):
    """把读到的 JSON 收敛成可安全使用的结构（容忍手改坏的字段）。"""
    if not isinstance(data, dict):
        data = {}
    data.setdefault("_meta", {"version": 1})
    items = data.get("custom")
    if not isinstance(items, list):
        items = []
    clean = []
    seen = set()
    for it in items:
        if not isinstance(it, dict):
            continue
        iid = str(it.get("id") or "").strip()
        if not iid or iid in seen:
            continue
        seen.add(iid)
        target_type = str(it.get("target_type") or "")
        if target_type not in TARGET_TYPES:
            target_type = "folder"
        clean.append({
            "id": iid,
            "title": str(it.get("title") or "未命名模块"),
            "icon": str(it.get("icon") or TYPE_ICON[target_type])[:4],
            "sub": str(it.get("sub") or TYPE_LABEL[target_type]),
            "target_type": target_type,
            "target": str(it.get("target") or ""),
            "created": str(it.get("created") or ""),
        })
    data["custom"] = clean

    state = data.get("state")
    if not isinstance(state, dict):
        state = {}
    data["state"] = {str(k): v for k, v in state.items() if isinstance(v, dict)}
    return data


def load():
    p = store_path()
    if not p.exists():
        return _normalize({})
    try:
        return _normalize(json.loads(p.read_text(encoding="utf-8-sig")))
    except (OSError, json.JSONDecodeError):
        return _normalize({})


def save(data):
    _normalize(data)
    p = store_path()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data, ensure_ascii=False, indent=1),
                     encoding="utf-8")
    except OSError:
        pass
    return data


# ---------------------------------------------------------------- 状态
def state(data, key):
    st = (data.get("state") or {}).get(key)
    return dict(st) if isinstance(st, dict) else {}


def set_state(data, key, **kv):
    """合并状态字段；值为空（False/None）就把字段删掉，保持 json 干净。"""
    st = state(data, key)
    for k, v in kv.items():
        if v:
            st[k] = v
        else:
            st.pop(k, None)
    if st:
        data.setdefault("state", {})[key] = st
    else:
        (data.get("state") or {}).pop(key, None)
    return st


def is_hidden(data, key):
    return bool(state(data, key).get("hidden"))


def is_deleted(data, key):
    return bool(state(data, key).get("deleted_at"))


def is_purged(data, key):
    return bool(state(data, key).get("purged"))


def hidden_keys(data):
    return [k for k, v in (data.get("state") or {}).items()
            if isinstance(v, dict) and v.get("hidden")]


def deleted_keys(data):
    return [k for k, v in (data.get("state") or {}).items()
            if isinstance(v, dict) and v.get("deleted_at")]


# ---------------------------------------------------------------- 隐藏/回收站
def set_hidden(data, key, on):
    set_state(data, key, hidden=bool(on))
    return save(data)


def recycle(data, key):
    """移入回收站：只打删除时间戳，配置一概不删。"""
    set_state(data, key, hidden=False, deleted_at=_now())
    return save(data)


def restore(data, key):
    """从回收站还原：清掉删除标记，恢复为显示。"""
    set_state(data, key, deleted_at=None, purged=None)
    return save(data)


def purge(data, key):
    """彻底删除（调用方负责二次确认）。

    · 内置模块：只留 purged 标记，代码不动，可通过「重置侧栏」找回
    · 自定义模块：删掉 custom 配置
    · 插件：.py 移进 data/hub/modules/.trash/（仍可手动找回），并留 purged 标记
    """
    if key.startswith(CUSTOM_PREFIX):
        iid = key[len(CUSTOM_PREFIX):]
        data["custom"] = [it for it in data.get("custom", []) if it.get("id") != iid]
        (data.get("state") or {}).pop(key, None)
    elif key.startswith(PLUGIN_PREFIX):
        path = plugin_path(key)
        if path is not None and path.is_file():
            _trash_file(path)
        set_state(data, key, hidden=False, deleted_at=None, purged=True)
    else:
        set_state(data, key, hidden=False, deleted_at=None, purged=True)
    return save(data)


def _trash_file(path):
    trash = plugin_dir() / ".trash"
    try:
        trash.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        shutil.move(str(path), str(trash / f"{stamp}-{path.name}"))
    except OSError:
        pass


def reset_builtin(data, builtin_keys):
    """恢复全部内置模块（清隐藏/回收站/彻底删除标记），自定义与插件不动。"""
    st = data.get("state") or {}
    for k in list(st):
        if k in builtin_keys:
            st.pop(k, None)
    data["state"] = st
    return save(data)


# ---------------------------------------------------------------- 自定义模块
def get_item(data, key):
    if not key.startswith(CUSTOM_PREFIX):
        return None
    iid = key[len(CUSTOM_PREFIX):]
    for it in data.get("custom", []):
        if it.get("id") == iid:
            return it
    return None


def add_custom(data, title, icon, sub, target_type, target):
    item = {
        "id": uuid.uuid4().hex[:8],
        "title": title.strip() or "未命名模块",
        "icon": (icon.strip() or TYPE_ICON.get(target_type, "✦"))[:4],
        "sub": sub.strip() or TYPE_LABEL.get(target_type, "快捷方式"),
        "target_type": target_type if target_type in TARGET_TYPES else "folder",
        "target": target.strip(),
        "created": _now(),
    }
    data.setdefault("custom", []).append(item)
    save(data)
    return item


def update_custom(data, key, **fields):
    item = get_item(data, key)
    if item is None:
        return None
    for k in ("title", "icon", "sub", "target_type", "target"):
        if k in fields and fields[k] is not None:
            item[k] = fields[k]
    save(data)
    return item


def custom_keys(data):
    return [CUSTOM_PREFIX + it["id"] for it in data.get("custom", [])]


# ---------------------------------------------------------------- 插件
def plugin_path(key):
    if not key.startswith(PLUGIN_PREFIX):
        return None
    stem = key[len(PLUGIN_PREFIX):]
    if not stem or any(c in stem for c in '\\/:*?"<>|'):
        return None
    return plugin_dir() / (stem + VALID_PLUGIN_SUFFIX)


def _read_meta(path):
    """静态读 META（ast 字面量），不执行插件代码，保证启动不被插件拖慢/搞崩。"""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    except (OSError, SyntaxError, UnicodeDecodeError, ValueError):
        return {}
    meta = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for tgt in node.targets:
            if isinstance(tgt, ast.Name) and tgt.id == "META":
                try:
                    val = ast.literal_eval(node.value)
                except (ValueError, SyntaxError, TypeError):
                    val = None
                if isinstance(val, dict):
                    meta = val
    return meta


def _has_make(path):
    try:
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    except (OSError, SyntaxError, UnicodeDecodeError, ValueError):
        return False
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "make":
            return True
    return False


def scan_plugins():
    """返回 (插件列表, 错误列表)。

    插件 = data/hub/modules/ 下的 *.py（.trash 与 _ 开头的文件不算）。
    META 只做静态解析；缺 make() 或语法错误的文件记进 errors，不进侧栏。
    """
    found, errors = [], []
    try:
        files = sorted(plugin_dir().glob("*.py"))
    except OSError:
        files = []
    for path in files:
        if path.name.startswith("_"):
            continue
        key = PLUGIN_PREFIX + path.stem
        if not _has_make(path):
            errors.append(f"{path.name}：缺少 make(master, ctx, app)")
            continue
        meta = _read_meta(path)
        title = str(meta.get("title") or path.stem)[:20]
        icon = str(meta.get("icon") or "✦")[:4]
        sub = str(meta.get("sub") or "插件")[:24]
        try:
            weight = int(meta.get("weight", PLUGIN_WEIGHT))
        except (TypeError, ValueError):
            weight = PLUGIN_WEIGHT
        found.append({"key": key, "path": path, "title": title, "icon": icon,
                      "sub": sub, "weight": weight})
    return found, errors


def load_plugin(key):
    """按需加载插件模块（导入失败就把异常抛给调用方显示）。"""
    path = plugin_path(key)
    if path is None or not path.is_file():
        raise FileNotFoundError(f"插件不存在：{key}")
    mtime = path.stat().st_mtime
    hit = _plugin_cache.get(key)
    if hit and hit[0] == mtime:
        return hit[1]
    mod_name = "hub_plugin_" + path.stem
    spec = importlib.util.spec_from_file_location(mod_name, str(path))
    if spec is None or spec.loader is None:
        raise ImportError(f"无法加载插件：{path.name}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    _plugin_cache[key] = (mtime, mod)
    return mod


PLUGIN_TEMPLATE = '''# -*- coding: utf-8 -*-
"""hub 插件模板：把本文件放在 data/hub/modules/ 下，重启 hub 即出现在侧栏。

约定：
  META = {"title": 显示名, "icon": 图标(1 个字/emoji), "sub": 副标题, "weight": 排序权重}
  make(master, ctx, app) -> tk.Frame：返回一个塞进主区域的 Frame

可直接用外壳的 ui / core：
    import ui
    from core import usage, paths, store, daily
ctx：仓库上下文（ctx.root / ctx.notes / ctx.kb / ctx.read_text）
app：主程序（app.goto("notes") 跳页、app.registry 看模块表）
"""
import tkinter as tk

META = {"title": "{title}", "icon": "✦", "sub": "插件", "weight": 15}


def make(master, ctx, app):
    frame = tk.Frame(master, bg="#f4f6fa")

    tk.Label(frame, text="{title}", font=("Microsoft YaHei UI", 18, "bold"),
             bg="#f4f6fa", fg="#1c2333").pack(anchor="w", padx=30, pady=(26, 6))
    tk.Label(frame, text="这是插件模板，改 make() 就能长成任何样子。",
             font=("Microsoft YaHei UI", 10), bg="#f4f6fa",
             fg="#6b7688").pack(anchor="w", padx=30)
    tk.Label(frame, text="仓库：" + str(ctx.root), font=("Consolas", 9),
             bg="#f4f6fa", fg="#6b7688").pack(anchor="w", padx=30, pady=(18, 0))
    return frame
'''


def create_plugin(name):
    """按模板新建一个插件文件，返回路径（重名时自动加序号）。"""
    stem = "".join(c for c in (name or "").strip()
                   if c not in '\\/:*?"<>|').strip() or "my_module"
    plugin_dir().mkdir(parents=True, exist_ok=True)
    path = plugin_dir() / (stem + ".py")
    n = 2
    while path.exists():
        path = plugin_dir() / f"{stem}-{n}.py"
        n += 1
    title = path.stem
    path.write_text(PLUGIN_TEMPLATE.replace("{title}", title), encoding="utf-8")
    return path


def plugin_errors_note(errors):
    return "；".join(errors) if errors else ""
