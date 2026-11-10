# -*- coding: utf-8 -*-
"""收集箱：把丢进 `notes/inbox/` 的文件认出来，路由到该去的地方。

设计原则：
  · **只认格式，不猜内容**——按后缀 + 前几行文字 + 表格表头判断类型，不需要模型；
  · **认不出来也不丢**——一律进 `notes/inbox/unsorted/`，等人或 agent 处理；
  · 处理成功的原件移进 `notes/inbox/done/YYYY-MM/`，保留可追溯；
  · 同一份文件按 sha256 去重（`data/hub/inbox/state.json`），重复投放直接跳过。

类型与去处：
  chat   大模型聊天 md（有 `## 我`/`## 助手` 或 `- 会话：`） → notes/conversations/
  alipay 支付宝/微信账单（csv/zip/xls/xlsx，表头有「交易时间/收/支」等）→ core.bill.import_file → data/hub/bills
  xhs    小红书导出表（xlsx，表头认得出「笔记标题/曝光量/点击率」） → core.xhs.import_file → data/hub/xhs
  text   普通 md/txt → notes/inbox/unsorted/（留给 agent）
  other  认不出的 → notes/inbox/unsorted/

CLI：
  python tools/hub/hub.py --collect        # 扫一遍 inbox
  python tools/hub/core/collect.py --dry   # 只看会怎么处理，不动文件
"""
import hashlib
import json
import os
import shutil
from datetime import datetime
from pathlib import Path

from . import paths

KIND_LABEL = {
    "chat": "聊天记录",
    "alipay": "支付宝/微信账单",
    "xhs": "小红书导出表",
    "text": "文本",
    "other": "认不出",
}

MOVE_KINDS = {"chat", "alipay", "xhs"}


# ---------------------------------------------------------------- 路径
def root():
    return paths.find_repo_root()


def inbox_dir():
    return root() / "notes" / "inbox"


def done_dir(when=None):
    when = when or datetime.now()
    return inbox_dir() / "done" / when.strftime("%Y-%m")


def unsorted_dir():
    return inbox_dir() / "unsorted"


def state_path():
    return paths.data_dir("hub", "inbox") / "state.json"


# ---------------------------------------------------------------- 状态
def _load_state():
    p = state_path()
    try:
        data = json.loads(p.read_text(encoding="utf-8-sig"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError, ValueError):
        return {}


def _save_state(data):
    p = state_path()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError:
        pass


def file_hash(path):
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
    except OSError:
        return ""
    return h.hexdigest()[:32]


# ---------------------------------------------------------------- 识别
def _head_text(path, limit=4000):
    try:
        raw = Path(path).read_bytes()[:limit * 4]
    except OSError:
        return ""
    for enc in ("utf-8-sig", "gb18030", "utf-16"):
        try:
            return raw.decode(enc, errors="strict")[:limit]
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", errors="replace")[:limit]


def detect(path):
    """返回 (kind, 说明)。只看文件名/后缀/开头几行/表头。"""
    p = Path(path)
    suffix = p.suffix.lower()
    name = p.name

    if suffix in (".md", ".markdown", ".txt", ".text", ".log"):
        text = _head_text(p)
        if "## 我" in text and "## 助手" in text:
            return "chat", "有「我/助手」分节"
        if "- 会话：" in text or "会话：`session-" in text:
            return "chat", "带会话头"
        return "text", "纯文本"

    if suffix in (".csv", ".tsv"):
        text = _head_text(p)
        if "交易时间" in text or "交易创建时间" in text:
            return "alipay", "账单 CSV 表头"
        if "交易单号" in text:
            return "alipay", "微信账单 CSV 表头"
        return "other", "认不出的 CSV"

    if suffix == ".zip":
        text = ""
        try:
            import zipfile
            with zipfile.ZipFile(p) as z:
                csvs = [n for n in z.namelist() if n.lower().endswith(".csv")]
                if csvs:
                    text = z.read(csvs[0])[:8000].decode("utf-8", errors="replace")
        except Exception:                                   # noqa: BLE001
            pass
        if "交易时间" in text or "交易创建时间" in text or "交易单号" in text:
            return "alipay", "压缩包里的账单 CSV"
        return "other", "压缩包（认不出）"

    if suffix in (".xlsx", ".xlsm", ".xls"):
        try:
            from . import xlsx
            for sheet in xlsx.sheet_names(str(p))[:4]:
                rows = xlsx.read_sheet(str(p), sheet)
                from . import xhs
                kind, _hdr = xhs.sheet_kind(rows)
                if kind is not None:
                    return "xhs", "小红书表：%s" % sheet
                joined = " ".join(" ".join(str(c) for c in r[:12]) for r in rows[:6])
                if "交易时间" in joined or "交易创建时间" in joined or "交易单号" in joined:
                    return "alipay", "账单表：%s" % sheet
        except Exception:                                   # noqa: BLE001
            pass
        return "other", "表格（认不出）"

    return "other", "不支持的格式"


# ---------------------------------------------------------------- 处理
def _unique(path):
    if not path.exists():
        return path
    n = 2
    while True:
        cand = path.with_name("%s-%d%s" % (path.stem, n, path.suffix))
        if not cand.exists():
            return cand
        n += 1


def _move(path, folder):
    try:
        folder.mkdir(parents=True, exist_ok=True)
        target = _unique(folder / Path(path).name)
        shutil.move(str(path), str(target))
        return target
    except OSError:
        return None


def _handle_chat(path):
    """把聊天 md 收进 notes/conversations/（已有会话格式原样搬，换统一文件名）。"""
    src = Path(path)
    text = _head_text(src, 4000)
    if "## 我" not in text:
        return False, "缺少「## 我」分节，不像聊天记录"
    stem = src.stem
    try:
        mtime = datetime.fromtimestamp(src.stat().st_mtime)
    except OSError:
        mtime = datetime.now()
    if len(stem) < 11 or stem[4] != "-" or stem[7] != "-":
        stem = "%s-%s" % (mtime.strftime("%Y-%m-%d"), stem)
    target = _unique(root() / "notes" / "conversations" / (stem + ".md"))
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(target))
    return True, target.relative_to(root()).as_posix()


def _handle_alipay(path):
    from . import bill
    stats = bill.import_file(str(path))
    return True, json.dumps(stats, ensure_ascii=False)[:300]


def _handle_xhs(path):
    from . import xhs
    accounts = xhs.load_accounts()
    if not accounts:
        return False, "还没有绑定小红书账号（先在 hub 的小红书页绑一个）"
    info = xhs.import_file(str(path), accounts[0].get("handle"))
    return True, json.dumps(info, ensure_ascii=False)[:300]


def process(path, dry=False):
    """处理一个文件，返回结果 dict。"""
    p = Path(path)
    kind, why = detect(p)
    result = {"file": p.name, "kind": kind, "why": why, "ok": False, "target": "", "msg": ""}
    if dry:
        result["msg"] = "（dry-run，未处理）"
        return result

    try:
        if kind == "chat":
            ok, msg = _handle_chat(p)
        elif kind == "alipay":
            ok, msg = _handle_alipay(p)
        elif kind == "xhs":
            ok, msg = _handle_xhs(p)
        elif kind == "text":
            target = _move(p, unsorted_dir())
            ok, msg = bool(target), (target.relative_to(root()).as_posix() if target else "移动失败")
        else:
            target = _move(p, unsorted_dir())
            ok, msg = bool(target), (target.relative_to(root()).as_posix() if target else "移动失败")
    except Exception as e:                                  # noqa: BLE001
        ok, msg = False, "%s: %s" % (type(e).__name__, e)

    result["ok"] = ok
    result["msg"] = str(msg)[:300]

    if ok and kind in MOVE_KINDS and p.exists():
        moved = _move(p, done_dir())
        if moved is not None:
            result["moved"] = moved.relative_to(root()).as_posix()
    elif ok:
        result["moved"] = result["msg"]
        result["target"] = result["msg"]
    return result


def scan(dry=False, force=False, folder=None):
    """扫 inbox 根目录下的文件（不进子目录），返回结果列表。"""
    src = Path(folder) if folder else inbox_dir()
    if not src.is_dir():
        return []
    state = _load_state()
    results = []
    for p in sorted(src.iterdir()):
        if p.is_dir() or p.name.startswith("."):
            continue
        digest = file_hash(p)
        known = state.get(digest)
        if known and not force:
            results.append({"file": p.name, "kind": known.get("kind", "?"),
                            "ok": bool(known.get("ok")), "why": "已处理过（跳过）",
                            "msg": known.get("msg", ""), "target": known.get("target", "")})
            continue
        res = process(p, dry=dry)
        results.append(res)
        # 只记成功的：失败的下次还会重试（绑定账号后就能过），不用 --force
        if not dry and digest and res["ok"]:
            state[digest] = {
                "at": datetime.now().strftime("%Y-%m-%d %H:%M"),
                "name": p.name, "kind": res["kind"], "ok": res["ok"],
                "msg": res.get("msg", ""), "target": res.get("target", ""),
            }
    if not dry:
        _save_state(state)
    return results


# ---------------------------------------------------------------- 概览（给页面）
def overview():
    """收集箱现状：待处理文件、各类数量、最近处理结果。"""
    pending = []
    src = inbox_dir()
    if src.is_dir():
        for p in sorted(src.iterdir()):
            if p.is_dir() or p.name.startswith("."):
                continue
            kind, why = detect(p)
            pending.append({"name": p.name, "kind": kind, "label": KIND_LABEL.get(kind, kind),
                            "why": why, "size": p.stat().st_size if p.is_file() else 0})
    done = []
    done_root = inbox_dir() / "done"
    if done_root.is_dir():
        for p in sorted(done_root.rglob("*"), reverse=True):
            if p.is_file():
                done.append({"name": p.name, "at": p.parent.name,
                             "path": p.relative_to(root()).as_posix()})
            if len(done) >= 30:
                break
    unsorted_files = []
    if unsorted_dir().is_dir():
        unsorted_files = [{"name": p.name, "path": p.relative_to(root()).as_posix()}
                          for p in sorted(unsorted_dir().iterdir()) if p.is_file()][:30]
    return {"inbox": str(inbox_dir().relative_to(root())), "pending": pending,
            "done": done, "unsorted": unsorted_files,
            "state_count": len(_load_state())}


# ---------------------------------------------------------------- CLI
def scan_cli(quiet=False):
    results = scan()
    if not results:
        if not quiet:
            print("[collect] 收件箱是空的：%s" % inbox_dir())
        return 0
    bad = 0
    for r in results:
        flag = "ok " if r["ok"] else "skip"
        if not r["ok"]:
            bad += 1
        if not quiet:
            detail = r.get("why") if r.get("why") == "已处理过（跳过）" else r.get("msg", "")
            print("[collect] %-5s %-8s %-28s %s" % (
                flag, r["kind"], r["file"][:28], str(detail)[:60]))
    if not quiet:
        print("[collect] %d 个文件，成功 %d，未处理 %d" % (len(results), len(results) - bad, bad))
    return 0 if bad < len(results) else 1


# 跟着 --daily-sync 一起跑（hub 启动时静态扫这个 DAILY）
DAILY = {"label": "收集箱", "func": "daily_cli", "weight": 50}


def daily_cli():
    return scan_cli(quiet=True)


if __name__ == "__main__":
    import sys
    dry = "--dry" in sys.argv
    forced = "--force" in sys.argv
    res = scan(dry=dry, force=forced)
    for r in res:
        print("%-5s %-8s %-30s %s" % ("ok" if r["ok"] else "wait", r["kind"],
                                      r["file"][:30], str(r.get("msg", ""))[:70]))
    print("共 %d 个" % len(res))
