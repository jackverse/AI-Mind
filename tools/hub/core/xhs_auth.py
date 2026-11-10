# -*- coding: utf-8 -*-
"""小红书登录态：一台机器一份，扫码一次长期有效，加密后落盘。

机制（和抖音 `douyin_auth` 同一套，只是分开存、分开的密钥）：
  · 每个号扫一次码 → 读 `xiaohongshu.com` 的 Cookie → 用本机「登录态密钥」加密
    → 存 `data/hub/xhs/auth.<机器>.json`（进 git，但**默认不跨机共用**）
  · 密钥只在本机 `data/hub/xhs/sync.key`，不进 git；丢了就重新扫码
  · 分片按机器名分开，各机各管自己的登录态（2026-11-04 用户明确要求）；
    别的机器的分片解不开时**跳过**，不影响本机自己登录
  · 同一个号如果在多台机器上都登录过，读的时候取登录时间最新的一份

为什么要加密：Cookie 等于账号身份（`access-token-creator.xiaohongshu.com` 拿到就能
以你的身份调创作者中心），所以不能明文进 git。
"""
import json
import os
import re
import socket
from datetime import datetime

from . import loginkey as lk
from . import paths

DOMAIN = "xhs-auth/v1"
KEY_NAME = "sync.key"
AUTH_GLOB = "auth.*.json"


class AuthError(RuntimeError):
    """密钥缺失 / 密钥不对 / 密文损坏 / 分片读不了。"""


class KeyMissing(AuthError):
    """本机分片在，但本机没有密钥。"""


# ------------------------------------------------------------------ 路径
def store_dir():
    return paths.data_dir("hub", "xhs")


def key_file():
    return store_dir() / KEY_NAME


def data_root():
    """给 `xhs.py` / `xhs_sync.py` 用的字符串路径。"""
    return str(store_dir())


def machine_name():
    """分片文件名用 COMPUTERNAME（ASCII），跨机稳定、能进 git。"""
    raw = os.environ.get("COMPUTERNAME") or socket.gethostname() or "PC"
    return re.sub(r"[^0-9A-Za-z_\-]", "_", raw) or "PC"


def auth_files():
    try:
        return sorted(store_dir().glob(AUTH_GLOB))
    except OSError:
        return []


def local_auth_file():
    return store_dir() / f"auth.{machine_name()}.json"


def has_encrypted_auth():
    return bool(auth_files())


# ------------------------------------------------------------------ 密钥
def load_key():
    """读本机密钥；没有返回 None。"""
    try:
        text = key_file().read_text(encoding="utf-8").strip()
    except OSError:
        return None
    try:
        return lk.decode_key(text)
    except lk.CryptoError as e:
        raise AuthError(f"sync.key 内容不对：{e}")


def save_key(master):
    if not master or len(master) != 32:
        raise AuthError("登录态密钥必须是 32 字节")
    p = key_file()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = str(p) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(lk.encode_key(master) + "\n")
    os.replace(tmp, p)
    try:
        os.chmod(p, 0o600)
    except OSError:
        pass


def ensure_key():
    """有就用，没有就生成一把。返回 (master, created)。

    只有「**本机**分片已经存在、但本机没有密钥」时才必须人工处理（那份分片解不开了）；
    别的机器的分片解不开会被跳过，不影响本机生成自己的密钥、自己扫码登录。
    """
    key = load_key()
    if key:
        return key, False
    if local_auth_file().exists():
        raise KeyMissing("本机的登录态分片在，但本机没有密钥；"
                         "只能删掉 data/hub/xhs/auth.%s.json 后重新扫码登录"
                         % machine_name())
    key = lk.new_key()
    save_key(key)
    return key, True


def local_key_missing():
    """本机分片在、但本机没有密钥（真的需要重新登录的那种缺）。"""
    return local_auth_file().exists() and load_key() is None


def key_text():
    key = load_key()
    return lk.encode_key(key) if key else ""


# ------------------------------------------------------------------ 分片读写
def _read_shard(path, master=None):
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            blob = json.load(f)
    except (OSError, ValueError):
        raise AuthError(f"读不了登录态文件：{os.path.basename(str(path))}")
    master = master or load_key()
    if not master:
        raise KeyMissing("本机没有登录态密钥（data/hub/xhs/sync.key）")
    try:
        data = lk.decrypt(blob, master, DOMAIN)
    except lk.CryptoError as e:
        raise AuthError(str(e))
    data.setdefault("accounts", [])
    return data


def load_shards(strict=False):
    """读全部分片；strict=False 时解不开的分片直接跳过（别的机器、或换过密钥的残留）。"""
    out = []
    master = load_key()
    for p in auth_files():
        try:
            data = _read_shard(p, master)
        except AuthError:
            if strict:
                raise
            continue
        data["_machine"] = data.get("machine") or p.name[len("auth."):-len(".json")]
        out.append(data)
    return out


def sessions():
    """合并所有分片：{handle: {handle,name,cookie,at,machine}}，同一个号取最新。"""
    best = {}
    for shard in load_shards():
        for a in shard.get("accounts") or []:
            handle = str(a.get("handle") or "").strip()
            if not handle:
                continue
            at = str(a.get("at") or "")
            cur = best.get(handle)
            if cur is None or at >= str(cur.get("at") or ""):
                best[handle] = {"handle": handle, "name": a.get("name") or "",
                                "cookie": a.get("cookie") or "", "at": at,
                                "machine": shard.get("_machine") or ""}
    return best


def session(handle):
    return sessions().get(str(handle or "").strip())


def cookie_of(handle):
    s = session(handle)
    return (s or {}).get("cookie") or ""


def has_session(handle):
    return bool(cookie_of(handle))


def read_local_shard():
    p = local_auth_file()
    if not p.exists():
        return {"machine": machine_name(), "updated": "", "accounts": []}
    data = _read_shard(p)
    data.setdefault("machine", machine_name())
    data.setdefault("accounts", [])
    return data


def _write_local(shard, master):
    shard["machine"] = machine_name()
    blob = lk.encrypt(shard, master, DOMAIN)
    p = local_auth_file()
    tmp = str(p) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(blob, f, ensure_ascii=False, indent=1)
        f.write("\n")
    os.replace(tmp, p)


def save_session(handle, cookie, name=""):
    """把某个号的 Cookie 加密写进本机分片；别的机器的分片不动。"""
    handle = str(handle or "").strip()
    if not handle:
        raise AuthError("小红书号不能为空")
    if not str(cookie or "").strip():
        raise AuthError("Cookie 为空")
    master, created = ensure_key()
    shard = read_local_shard()
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    accounts = [a for a in shard.get("accounts") or []
                if str(a.get("handle")) != handle]
    accounts.append({"handle": handle, "name": name or "",
                     "cookie": str(cookie), "at": now})
    shard["accounts"] = accounts
    shard["updated"] = now
    _write_local(shard, master)
    return {"at": now, "created": created}


def remove_session(handle):
    """只删本机分片里的号；别的机器那份保留。"""
    p = local_auth_file()
    if not p.exists():
        return False
    shard = read_local_shard()
    before = len(shard.get("accounts") or [])
    shard["accounts"] = [a for a in shard.get("accounts") or []
                         if str(a.get("handle")) != str(handle)]
    if len(shard["accounts"]) == before:
        return False
    shard["updated"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    _write_local(shard, load_key())
    return True


# ------------------------------------------------------------------ 自检
def _selftest():
    assert lk.selftest()
    return True


if __name__ == "__main__":
    print("selftest", _selftest())
