#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""hub-web — 抖音 / 小红书数据的浏览器版。

只读 `data/hub/douyin` 与 `data/hub/xhs`：账号列表、作品/笔记明细、趋势与指标。
数据仓库用 `--root` / `HUB_ROOT` 指定；代码仓库本身不放数据。

用法：
    python hub-web/server.py --root D:\\path\\to\\vault
    python hub-web/server.py --root D:\\path\\to\\vault --host 0.0.0.0
    python hub-web/server.py --root D:\\path\\to\\vault --export
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
    """数据仓库：--root > HUB_ROOT > 代码仓库自身（无数据时展示空状态）。"""
    ap = argparse.ArgumentParser(add_help=False)
    ap.add_argument("--root")
    ns, _ = ap.parse_known_args(argv)
    raw = ns.root or os.environ.get("HUB_ROOT")
    root = Path(raw).expanduser().resolve() if raw else APP_ROOT
    os.environ["HUB_ROOT"] = str(root)
    return root


ROOT = _vault_root(sys.argv[1:])
sys.path.insert(0, str(HUB))

from core import douyin, xhs  # noqa: E402

LOCK = threading.Lock()
CACHE = {"at": 0.0, "data": None}
CACHE_TTL = 2.0

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


def _safe(fn, default):
    """单个板块出错不连累整包。"""
    try:
        return fn()
    except Exception as exc:            # noqa: BLE001 —— 自用工具，错误直接带给前端
        return {"error": f"{type(exc).__name__}: {exc}"} if default is None else default


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


def build_bundle():
    return {
        "meta": {
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "mode": "live",
        },
        "douyin": _safe(_douyin, {"accounts": [], "views": {}, "profiles": {}}),
        "xhs": _safe(_xhs, {"accounts": [], "views": {}}),
    }


def get_bundle(force=False):
    now = time.time()
    if not force and CACHE["data"] and now - CACHE["at"] < CACHE_TTL:
        return CACHE["data"]
    data = build_bundle()
    CACHE.update({"at": now, "data": data})
    return data


# ------------------------------------------------------------------ HTTP
class Handler(BaseHTTPRequestHandler):
    server_version = "hub-web/2.0"

    def log_message(self, fmt, *args):      # 只留一行、别刷屏
        sys.stderr.write("[hub-web] " + (fmt % args) + "\n")

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

    def do_GET(self):
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        if path == "/api/bundle":
            return self._json(get_bundle())
        if path == "/api/health":
            return self._json({"ok": True,
                               "generated_at": get_bundle()["meta"]["generated_at"]})
        return self._static(path)

    def do_HEAD(self):
        return self.do_GET()

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
    out.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")),
                   encoding="utf-8")
    size = out.stat().st_size / 1024
    print(f"已导出 {out}（{size:.0f} KB）")
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="抖音 / 小红书数据的网页版")
    ap.add_argument("--root", default=None,
                    help="数据仓库目录（含 data/hub/）；默认取 HUB_ROOT 或本仓库")
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
