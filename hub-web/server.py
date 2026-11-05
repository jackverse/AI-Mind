#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""hub-web —— 把 hub 的视图搬到浏览器里。

为什么要有它：hub 是 tkinter 桌面程序，只能在开着的那台 Windows 上用。
这一层把同样的数据（notes/ + data/hub/）做成一个网页：手机连同一 Wi-Fi 就能看，
换台电脑不用装 Python；导出成静态快照后还能直接挂 GitHub Pages。

用法：
    python hub-web/server.py --root D:\\path\\to\\vault   # 指定数据仓库
    python hub-web/server.py --host 0.0.0.0             # 手机同局域网可访问
    python hub-web/server.py --open                     # 起服务并打开浏览器
    python hub-web/server.py --export                   # 只导出静态快照到 web/data/bundle.json

数据仓库 = 任意包含 `notes/kb/` 的目录（本仓库不含任何数据）。
只读边界：除了「刷题」写 notes/kb/<科目>/review.json（和桌面 hub 共用一份进度），
其余全部只读。不做登录、不做同步、不碰 data/hub 的写入。
"""
import argparse
import json
import os
import socket
import sys
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

APP_ROOT = Path(__file__).resolve().parents[1]     # 代码仓库：hub/ 与 hub-web/ 所在处
HUB = APP_ROOT / "hub"
WEB = Path(__file__).resolve().parent / "web"


def _vault_root(argv):
    """数据仓库：--root > HUB_ROOT > 代码仓库自身（无 notes 时展示空状态）。"""
    ap = argparse.ArgumentParser(add_help=False)
    ap.add_argument("--root")
    ns, _ = ap.parse_known_args(argv)
    raw = ns.root or os.environ.get("HUB_ROOT")
    root = Path(raw).expanduser().resolve() if raw else APP_ROOT
    os.environ["HUB_ROOT"] = str(root)
    return root


ROOT = _vault_root(sys.argv[1:])
sys.path.insert(0, str(HUB))

from core import bill, daily, douyin, eudic, store, timeline, xhs  # noqa: E402

LOCK = threading.Lock()
CACHE = {"at": 0.0, "data": None}
CACHE_TTL = 2.0

TITLE_RE = __import__("re").compile(r"^#\s+(.+)$", __import__("re").M)

MIME = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".webmanifest": "application/manifest+json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
    ".woff2": "font/woff2",
}


# ------------------------------------------------------------------ 工具
def _plain(obj):
    """把 core 的返回值变成可 JSON 的结构（去掉 fmt_* 这类函数）。"""
    if callable(obj):
        return None
    if isinstance(obj, dict):
        return {str(k): _plain(v) for k, v in obj.items() if not callable(v)}
    if isinstance(obj, (list, tuple)):
        return [_plain(v) for v in obj]
    if isinstance(obj, float):
        if obj != obj or obj in (float("inf"), float("-inf")):
            return None
        return round(obj, 6)
    return obj


def _note_title(text, stem):
    for line in text.splitlines():
        m = TITLE_RE.match(line.strip())
        if m:
            return m.group(1).strip()
    return stem


def _notes():
    files, texts = [], {}
    for p in sorted((ROOT / "notes").rglob("*.md")):
        rel = p.relative_to(ROOT).as_posix()
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
            stat = p.stat()
        except OSError:
            continue
        texts[rel] = text
        inner = rel[len("notes/"):]
        group = str(Path(inner).parent.as_posix())
        files.append({
            "path": rel,
            "name": p.name,
            "title": _note_title(text, p.stem),
            "group": "" if group == "." else group,
            "mtime": int(stat.st_mtime),
            "size": stat.st_size,
        })
    files.sort(key=lambda f: (-f["mtime"], f["path"]))
    return files, texts


def _safe(fn, default=None):
    """单个板块出错不连累整包。"""
    try:
        return fn()
    except Exception as exc:            # noqa: BLE001 —— 自用工具，错误直接带给前端
        return {"error": f"{type(exc).__name__}: {exc}"} if default is None else default


def _fitness(rows):
    return {
        "rows": rows,
        "summary": daily.summary(rows),
        "series": [{"date": d, "weight": w} for d, w in daily.weight_series(rows)],
        "moving": [{"date": d, "weight": w} for d, w in daily.moving_avg(daily.weight_series(rows))],
        "parts": [{"part": p, "count": n} for p, n in daily.part_counts(rows)],
        "calendar": [{"date": d, "status": s} for d, s in daily.calendar(rows, n=30)],
    }


def _accounts(kind):
    try:
        return kind.load_accounts()
    except Exception:
        return []


def _douyin():
    accounts = _accounts(douyin)
    handles = [a.get("handle") for a in accounts if a.get("handle")]
    views, profiles = {}, {}
    for h in handles:
        views[h] = _plain(douyin.summarize([h]))
        try:
            profiles[h] = _plain(douyin.load(h).get("profile") or {})
        except Exception:
            profiles[h] = {}
    if handles:
        views["__all__"] = _plain(douyin.summarize(handles))
        fans = [profiles.get(h, {}).get("fans") for h in handles]
        fans = [f for f in fans if isinstance(f, (int, float))]
        profiles["__all__"] = {
            "fans": sum(fans) if fans else None,
            "fans_new": sum(profiles.get(h, {}).get("fans_new") or 0 for h in handles),
            "fans_delta": sum(profiles.get(h, {}).get("fans_delta") or 0 for h in handles),
        }
    return {"accounts": _plain(accounts), "views": views, "profiles": profiles}


def _xhs():
    accounts = _accounts(xhs)
    handles = [a.get("handle") for a in accounts if a.get("handle")]
    views = {}
    for h in handles:
        views[h] = _plain(xhs.summarize([h]))
    if handles:
        views["__all__"] = _plain(xhs.summarize(handles))
    return {"accounts": _plain(accounts), "views": views}


def _bills():
    accounts = _accounts(bill)
    views = {"__all__": _plain(bill.summarize(None))}
    for a in accounts:
        views[a["id"]] = _plain(bill.summarize([a["id"]]))
    return {"accounts": _plain(accounts), "views": views}


def _eudic():
    accounts = _accounts(eudic)
    if not accounts:
        return {"accounts": [], "summary": None}
    return {"accounts": _plain(accounts), "summary": _plain(eudic.summarize())}


def _quiz():
    kb = ROOT / "notes" / "kb"
    subjects = store.overview(kb)
    out = []
    for row in subjects:
        name = row["subject"]
        qs = store.load_questions(kb, name)
        if not qs:
            continue
        rv = store.load_review(kb, name)
        mastered = sum(1 for v in rv.values() if v.get("mastered"))
        out.append({
            "subject": name,
            "total": len(qs),
            "seen": row["seen"],
            "wrong": row["wrong"],
            "mastered": mastered,
            "questions": [
                {
                    "id": q.get("id"),
                    "chapter": q.get("chapter", ""),
                    "type": q.get("type", "choice"),
                    "q": q.get("q", ""),
                    "options": q.get("options") or {},
                    "answer": q.get("answer", ""),
                    "analysis": q.get("analysis", ""),
                }
                for q in qs
            ],
            "review": rv,
        })
    return {"subjects": out}


def build_bundle():
    files, texts = _notes()
    daily_text = texts.get("notes/daily-log.md", "")
    index_text = texts.get("notes/index.md", "")

    rows = daily.parse_text(daily_text)

    home = {
        "subjects": 0,
        "questions": 0,
        "wrong": 0,
        "notes": len(files),
        "recent": files[:6],
        "today": datetime.now().strftime("%Y-%m-%d"),
        "week": timeline.weekday(datetime.now().strftime("%Y-%m-%d")),
    }
    quiz = _safe(_quiz, {"subjects": []})
    subjects = quiz.get("subjects") or []
    home["subjects"] = len(subjects)
    home["questions"] = sum(s["total"] for s in subjects)
    home["wrong"] = sum(s["wrong"] for s in subjects)

    orders = {p["path"]: p["title"] for p in files}

    bundle = {
        "meta": {
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "machine": socket.gethostname(),
            "root": str(ROOT),
            "mode": "live",
        },
        "home": home,
        "notes": {"files": files, "texts": texts, "titles": orders},
        "fitness": _safe(lambda: _fitness(rows), {"error": "解析日报失败"}),
        "timeline": _safe(lambda: {
            "days": timeline.build(daily_text, index_text),
            "summary": timeline.summary(timeline.build(daily_text, index_text)),
        }, {"days": []}),
        "douyin": _safe(_douyin, {"accounts": [], "views": {}}),
        "xhs": _safe(_xhs, {"accounts": [], "views": {}}),
        "bills": _safe(_bills, {"accounts": [], "views": {}}),
        "eudic": _safe(_eudic, {"accounts": [], "summary": None}),
        "quiz": quiz,
    }
    return bundle


def get_bundle(force=False):
    now = time.time()
    if not force and CACHE["data"] and now - CACHE["at"] < CACHE_TTL:
        return CACHE["data"]
    data = build_bundle()
    CACHE.update({"at": now, "data": data})
    return data


# ------------------------------------------------------------------ HTTP
class Handler(BaseHTTPRequestHandler):
    server_version = "hub-web/1.0"

    def log_message(self, fmt, *args):      # 只留一行、别刷屏
        sys.stderr.write("[hub-web] " + (fmt % args) + "\n")

    # -- 响应助手 --------------------------------------------------
    def _send(self, code, body=b"", ctype="application/json; charset=utf-8"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"))

    # -- GET -------------------------------------------------------
    def do_GET(self):
        parsed = urlparse(self.path)
        path = unquote(parsed.path)

        if path == "/api/bundle":
            return self._json(get_bundle())
        if path == "/api/health":
            return self._json({"ok": True, "generated_at": get_bundle()["meta"]["generated_at"]})

        return self._static(path)

    def do_HEAD(self):
        return self.do_GET()

    # -- POST ------------------------------------------------------
    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path != "/api/answer":
            return self._json({"ok": False, "error": "not found"}, 404)
        try:
            length = int(self.headers.get("Content-Length") or 0)
            payload = json.loads(self.rfile.read(length) or b"{}")
        except (ValueError, json.JSONDecodeError):
            return self._json({"ok": False, "error": "bad json"}, 400)

        subject = str(payload.get("subject") or "")
        qid = str(payload.get("id") or "")
        ok = bool(payload.get("ok"))
        kb = ROOT / "notes" / "kb"
        valid = {p.name for p in kb.iterdir() if p.is_dir()} if kb.is_dir() else set()
        if subject not in valid or not qid:
            return self._json({"ok": False, "error": "bad subject/id"}, 400)

        with LOCK:
            review = store.load_review(kb, subject)
            state = store.apply_answer(review, qid, ok)
            store.save_review(kb, subject, review)
            stats = store.overview(kb)
        CACHE["at"] = 0
        row = next((r for r in stats if r["subject"] == subject), None)
        return self._json({"ok": True, "state": state, "subject": row})

    # -- 静态文件 --------------------------------------------------
    def _static(self, path):
        if path in ("", "/"):
            path = "/index.html"
        rel = path.lstrip("/")
        target = (WEB / rel).resolve()
        try:
            target.relative_to(WEB.resolve())
        except ValueError:
            return self._send(403, b"forbidden", "text/plain; charset=utf-8")
        if not target.is_file():
            # 前端是 hash 路由，回落到 index.html
            if "." not in Path(rel).name:
                target = WEB / "index.html"
            else:
                return self._send(404, b"not found", "text/plain; charset=utf-8")
        ctype = MIME.get(target.suffix.lower(), "application/octet-stream")
        try:
            body = target.read_bytes()
        except OSError:
            return self._send(404, b"not found", "text/plain; charset=utf-8")
        return self._send(200, body, ctype)


def lan_ips():
    ips = set()
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("223.5.5.5", 80))
        ips.add(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if not ip.startswith("127."):
                ips.add(ip)
    except OSError:
        pass
    return sorted(ips)


def export(path=None):
    data = get_bundle(force=True)
    data["meta"]["mode"] = "static"
    out = Path(path) if path else WEB / "data" / "bundle.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    size = out.stat().st_size / 1024
    print(f"已导出 {out}（{size:.0f} KB）")
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="hub 的网页版：手机/浏览器看同一份数据")
    ap.add_argument("--root", default=None,
                    help="数据仓库目录（含 notes/kb/）；默认取 HUB_ROOT 或本仓库")
    ap.add_argument("--host", default="127.0.0.1", help="监听地址；手机访问用 0.0.0.0")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--export", nargs="?", const="", default=None,
                    help="只导出静态快照（可选输出路径）")
    ap.add_argument("--open", action="store_true", help="启动后打开浏览器")
    args = ap.parse_args(argv)

    if args.export is not None:
        export(args.export or None)
        return 0

    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    url = f"http://127.0.0.1:{args.port}/"
    print(f"hub-web 已启动：{url}")
    if args.host not in ("127.0.0.1", "localhost"):
        for ip in lan_ips():
            print(f"  同一 Wi-Fi 的手机可访问：http://{ip}:{args.port}/")
    print("  Ctrl+C 停止")
    if args.open:
        import webbrowser
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
