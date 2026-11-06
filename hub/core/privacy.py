# -*- coding: utf-8 -*-
"""隐私模式：账号昵称 / 抖音号 / 小红书号 / 手机号 / 邮箱 脱敏展示。

**只改显示，不动数据**：`data/hub` 里的 json 仍是明文，关掉开关立刻恢复原样。
所以截图/投屏前先看一眼侧栏底部的开关是不是「开」。

打码规则（尽量保留可辨识度，但看不出完整账号）：

| 类型 | 例子 | 脱敏后 |
|---|---|---|
| 抖音号 / 小红书号（纯数字） | 12345678901 | 123******01 |
| 昵称 | 示例昵称 | 示*** |
| 手机号 | 13800138000 | 138****8000 |
| 邮箱 | example@example.com | ex***@example.com |
| 未知文本里的 8 位以上数字 | 12345678 | 123***78 |

设置按机器分片存 `data/hub/privacy.<机器>.json`，
**默认开启**：第一次打开 hub 就是脱敏状态，自己要用明文点一下侧栏底部即可。
"""
import json
import os
import re
import socket
from datetime import datetime

from . import paths

_KEY = "enabled"

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_PHONE_RE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
_DIGITS_RE = re.compile(r"(?<!\d)\d{8,}(?!\d)")


# ---------------------------------------------------------------- 设置
def host_id():
    """本机标识：COMPUTERNAME（Windows）/ hostname，清洗成文件名安全的形式。"""
    raw = os.environ.get("COMPUTERNAME") or socket.gethostname() or "local"
    clean = re.sub(r"[^A-Za-z0-9_.-]", "_", raw).strip("._")
    return (clean or "local")[:40]


def store_path():
    """本机分片：隐私开关是「这台机器当前要不要遮」，不跨机同步。"""
    return paths.data_dir("hub") / f"privacy.{host_id()}.json"


def load():
    try:
        data = json.loads(store_path().read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def enabled():
    """默认开：没存过设置时按「开」算，避免第一次截图就漏。"""
    value = load().get(_KEY, True)
    if isinstance(value, str):
        return value.strip().lower() not in ("0", "false", "no", "off", "")
    return bool(value)


def set_enabled(on):
    path = store_path()
    data = load()
    data[_KEY] = bool(on)
    data["updated"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        pass
    return bool(on)


def toggle():
    return set_enabled(not enabled())


def status_text():
    return "开 · 账号已脱敏" if enabled() else "关 · 显示明文"


# ---------------------------------------------------------------- 打码
def _s(v):
    return "" if v is None else str(v).strip()


def mask_handle(value):
    """抖音号 / 小红书号：纯数字保留前 3 后 2，中间打星。"""
    s = _s(value)
    if not s:
        return ""
    if re.fullmatch(r"\d+", s):
        if len(s) <= 2:
            return "*" * len(s)
        if len(s) <= 5:
            return s[0] + "*" * (len(s) - 1)
        return s[:3] + "*" * (len(s) - 5) + s[-2:]
    # 字母数字混排（小红书有些号）：保留头 2 尾 1
    if len(s) <= 2:
        return s[0] + "*" * (len(s) - 1)
    if len(s) <= 4:
        return s[0] + "*" * (len(s) - 2) + s[-1]
    return s[:2] + "***" + s[-1]


def mask_name(value):
    """昵称 / 备注名：只留第一个字。"""
    s = _s(value)
    if not s:
        return ""
    if len(s) == 1:
        return "*"
    if len(s) == 2:
        return s[0] + "*"
    return s[0] + "***"


def mask_phone(value):
    s = re.sub(r"\D", "", _s(value))
    if not s:
        return ""
    if len(s) == 11:
        return s[:3] + "****" + s[-4:]
    if len(s) > 4:
        return s[:2] + "*" * (len(s) - 4) + s[-2:]
    return "*" * len(s)


def mask_email(value):
    s = _s(value)
    m = re.fullmatch(r"([^@\s]+)@([^@\s]+)", s)
    if not m:
        return mask_name(s)
    local, domain = m.groups()
    keep = local[:2] if len(local) > 2 else local[:1]
    return keep + "***@" + domain


def mask_text(value, names=None):
    """自由文本：邮箱、手机号、8 位以上数字打码；names 里的名字按昵称规则替换。

    笔记正文、同步日志、时间线摘要都走它——工作流是「按字符串扫」，
    所以不用逐处改数据，也不影响原文。
    """
    s = "" if value is None else str(value)   # 保留换行/空白，别把渲染的段落吃掉
    if not s:
        return ""
    s = _EMAIL_RE.sub(lambda m: mask_email(m.group(0)), s)
    s = _PHONE_RE.sub(lambda m: mask_phone(m.group(0)), s)
    s = _DIGITS_RE.sub(lambda m: mask_handle(m.group(0)), s)
    for name in sorted({_s(n) for n in (names or []) if len(_s(n)) >= 2},
                       key=len, reverse=True):
        s = s.replace(name, mask_name(name))
    return s


# ---------------------------------------------------------------- 给页面用的「按开关取显示值」
def show_handle(value):
    return mask_handle(value) if enabled() else _s(value)


def show_name(value):
    return mask_name(value) if enabled() else _s(value)


def show_phone(value):
    return mask_phone(value) if enabled() else _s(value)


def show_email(value):
    return mask_email(value) if enabled() else _s(value)


def show_text(value, names=None):
    if enabled():
        return mask_text(value, names)
    return "" if value is None else str(value)
