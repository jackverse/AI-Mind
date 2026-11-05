# -*- coding: utf-8 -*-
"""每日提醒的计划任务：用 Windows 自带 schtasks 注册 `hub.exe --remind`。

不依赖第三方库，也不需要管理员权限（任务建在当前用户下，登录后按点触发）。
"""
import os
import re
import subprocess
import sys
from pathlib import Path

TASK_NAME = "第二大脑-邮件提醒"
_NO_WINDOW = 0x08000000 if os.name == "nt" else 0


def _run(args):
    """跑 schtasks，返回 (returncode, 输出文本)。"""
    try:
        p = subprocess.run(args, capture_output=True, creationflags=_NO_WINDOW,
                           timeout=20)
    except (OSError, subprocess.TimeoutExpired) as e:
        return 1, f"{e}"
    raw = (p.stdout or b"") + (p.stderr or b"")
    text = raw.decode("mbcs", errors="replace") if os.name == "nt" else \
        raw.decode("utf-8", errors="replace")
    return p.returncode, text.strip()


def command():
    """计划任务要跑的命令行（带引号）。"""
    if getattr(sys, "frozen", False):                 # 打包后的 hub.exe
        return f'"{sys.executable}" --remind'
    hub_py = Path(__file__).resolve().parent.parent / "hub.py"
    exe = Path(sys.executable)
    py = exe.with_name("pythonw.exe")
    runner = py if py.exists() else exe               # 源码运行用 pythonw，不出黑框
    return f'"{runner}" "{hub_py}" --remind'


def status():
    """返回 (是否已安装, 说明)。"""
    if os.name != "nt":
        return False, "只有 Windows 支持计划任务"
    code, out = _run(["schtasks", "/Query", "/TN", TASK_NAME, "/FO", "LIST", "/V"])
    if code != 0:
        return False, "还没安装"
    next_run = ""
    for line in out.splitlines():
        line = line.strip()
        if line.startswith(("下次运行时间", "Next Run Time")):
            next_run = re.split(r"[:：]", line, 1)[-1].strip()
            break
    return True, (f"每天 {next_run}" if next_run else "已安装")


def install(hhmm):
    """按 HH:MM 建/更新每天的计划任务。返回 (ok, 说明)。"""
    if os.name != "nt":
        return False, "只有 Windows 支持计划任务"
    m = re.fullmatch(r"\s*(\d{1,2})[:：](\d{2})\s*", hhmm or "")
    if not m:
        return False, "时间格式要写成 08:30 这样"
    hour, minute = int(m.group(1)), int(m.group(2))
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return False, "时间超出范围"
    when = f"{hour:02d}:{minute:02d}"
    code, out = _run(["schtasks", "/Create", "/F", "/TN", TASK_NAME,
                      "/TR", command(), "/SC", "DAILY", "/ST", when])
    if code != 0:
        return False, f"安装失败：{out or 'schtasks 返回 ' + str(code)}"
    return True, f"已设置每天 {when} 发送提醒"


def remove():
    if os.name != "nt":
        return False, "只有 Windows 支持计划任务"
    code, out = _run(["schtasks", "/Delete", "/TN", TASK_NAME, "/F"])
    if code == 0:
        return True, "已移除计划任务"
    if "找不到" in out or "cannot find" in out.lower() or "不存在" in out:
        return True, "本来就没有安装"
    return False, f"移除失败：{out}"
