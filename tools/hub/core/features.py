# -*- coding: utf-8 -*-
"""功能开关：抖音 / 小红书。

只影响侧栏入口和首页卡片，不删任何已同步的数据；关掉再打开数据还在。
存在 <数据目录>/data/hub/features.json。
"""
import json
from pathlib import Path

from . import paths

KEYS = ("douyin", "xhs")
DEFAULT = {"douyin": True, "xhs": True}


def _file(root=None):
    base = (Path(root) / "data" / "hub") if root else paths.data_dir("hub")
    return base / "features.json"


def load(root=None):
    data = dict(DEFAULT)
    try:
        raw = json.loads(_file(root).read_text(encoding="utf-8"))
        for k in KEYS:
            if k in raw:
                data[k] = bool(raw[k])
    except (OSError, ValueError):
        pass
    return data


def set_enabled(key, on, root=None):
    if key not in KEYS:
        return load(root)
    data = load(root)
    data[key] = bool(on)
    try:
        f = _file(root)
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError:
        pass
    return data
