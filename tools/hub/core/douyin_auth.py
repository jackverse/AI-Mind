# -*- coding: utf-8 -*-
"""抖音登录态：一次扫码，加密后跟着 git 走，多台机器共用。

为什么要自己加密：
  · 抖音的登录态就是一组 Cookie（sessionid / sid_guard …），拿到就能以你的身份
    访问创作者中心，所以不能明文进 git；
  · 但 DSH 的两台机器要共用一次授权，DPAPI 那种「绑本机」的方案又不行。
  · 折中：用一把「同步密钥」做 SHAKE256 流加密 + HMAC-SHA256 认证，
    密文放 data/hub/douyin/auth.<机器>.json 进 git，密钥只在本机 sync.key。

  · 每台机器一个分片：auth.<机器>.json，互不覆盖；
  · 读的时候按 handle 合并，同一个号取登录时间最新的一份；
  · 换机器：把 sync.key 里的密钥粘一次（或复制文件），之后长期不用再管；
  · 也可以「各机各管」：别的机器的分片解不开就跳过，本机自己生成自己的密钥照样登录
    （2026-11-04 用户明确要求：登录态每台电脑维护自己的就好）。

只做数据维护需要的读接口，不写任何抖音侧数据（见 douyin_sync.ALLOWED）。
"""
import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import socket
from datetime import datetime

from . import paths

KEY_NAME = "sync.key"
AUTH_GLOB = "auth.*.json"
PLAIN_HEAD = {"v": 1, "alg": "shake256-hmac"}


class AuthError(RuntimeError):
    """密钥缺失 / 密钥不对 / 密文损坏。"""


class KeyMissing(AuthError):
    """本机还没有同步密钥，但仓库里有加密的登录态。"""


# ------------------------------------------------------------------ 路径
def store_dir():
    return paths.data_dir("hub", "douyin")


def key_file():
    return store_dir() / KEY_NAME


def machine_name():
    """机器名：用 COMPUTERNAME（ASCII），别名只在显示时用。

    分片文件名要跨机稳定、能进 git，所以不用中文别名（会被压成下划线）。
    """
    raw = os.environ.get("COMPUTERNAME") or socket.gethostname() or "PC"
    safe = re.sub(r"[^0-9A-Za-z_\-]", "_", raw) or "PC"
    return safe


def auth_files():
    d = store_dir()
    try:
        return sorted(d.glob(AUTH_GLOB))
    except OSError:
        return []


def local_auth_file():
    return store_dir() / f"auth.{machine_name()}.json"


# ------------------------------------------------------------------ 密钥
def _b32encode(raw):
    s = base64.b32encode(raw).decode("ascii").rstrip("=")
    return "-".join(s[i:i + 4] for i in range(0, len(s), 4))


def _b32decode(text):
    s = re.sub(r"[\s\-]", "", str(text or "")).upper()
    if not s:
        return b""
    pad = "=" * ((8 - len(s) % 8) % 8)
    try:
        return base64.b32decode(s + pad)
    except Exception:                                    # noqa: BLE001
        raise AuthError("同步密钥格式不对（应该是一串字母数字，形如 ABCD-EFGH-…）")


def new_key():
    return secrets.token_bytes(32)


def key_id(master):
    return hashlib.sha256(master).hexdigest()[:12]


def load_key():
    """读本机密钥；没有返回 None。"""
    try:
        text = key_file().read_text(encoding="utf-8").strip()
    except OSError:
        return None
    raw = _b32decode(text)
    if len(raw) != 32:
        raise AuthError("sync.key 长度不对（应为 32 字节）")
    return raw


def ensure_key():
    """有就用，没有就生成一把。返回 (master, created)。

    只有「**本机**分片已经存在、但本机没有密钥」时才必须导入：那种情况再造一把，
    本机这份分片就永远解不开了。
    别的机器的分片（auth.<别的机器>.json）读的时候解不开会跳过，不影响本机生成自己的密钥
    ——2026-11-04 用户定：登录态每台电脑各维护自己的。
    """
    key = load_key()
    if key:
        return key, False
    if local_auth_file().exists():
        raise KeyMissing("本机的登录态分片在，但本机没有同步密钥；"
                         "先到「登录 → 同步密钥」导入本机那把（别生成新的，否则这份分片解不开）")
    key = new_key()
    save_key(key)
    return key, True


def local_key_missing():
    """本机分片在、但本机没有密钥（真的需要导入才行的那种缺）。"""
    return local_auth_file().exists() and load_key() is None


def save_key(master):
    if len(master) != 32:
        raise AuthError("同步密钥必须是 32 字节")
    p = key_file()
    tmp = str(p) + ".tmp"
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(_b32encode(master) + "\n")
    os.replace(tmp, p)
    try:
        os.chmod(p, 0o600)
    except OSError:
        pass


def key_text(master=None):
    return _b32encode(master if master is not None else load_key() or b"")


def import_key(text, check=True):
    """把另一台机器的密钥粘进来。返回 master。"""
    raw = _b32decode(text)
    if len(raw) != 32:
        raise AuthError("这把密钥长度不对（需要 32 字节 / 52 个字母数字）")
    if check and auth_files():
        # 能解开任意一个分片才算对
        ok = 0
        for p in auth_files():
            try:
                decrypt_file(p, raw)
                ok += 1
            except AuthError:
                continue
        if not ok:
            raise AuthError("密钥对不上：仓库里的登录态解不开，确认是另一台机器上那把")
    save_key(raw)
    return raw


# ------------------------------------------------------------------ 加解密
def _subkeys(master):
    enc = hmac.new(master, b"douyin-auth/v1/enc", hashlib.sha256).digest()
    mac = hmac.new(master, b"douyin-auth/v1/mac", hashlib.sha256).digest()
    return enc, mac


def _keystream(key, nonce, n):
    out = bytearray()
    ctr = 0
    while len(out) < n:
        out.extend(hashlib.shake_256(key + nonce + ctr.to_bytes(8, "little")).digest(64))
        ctr += 1
    return bytes(out[:n])


def _xor(a, b):
    return bytes(x ^ y for x, y in zip(a, b))


def _b64(raw):
    return base64.b64encode(raw).decode("ascii")


def _unb64(text):
    try:
        return base64.b64decode(str(text or ""), validate=True)
    except Exception:                                    # noqa: BLE001
        raise AuthError("密文不是合法 base64")


def encrypt(obj, master=None):
    master = master or load_key()
    if not master:
        raise KeyMissing("还没有同步密钥：先在「抖音 → 登录 → 同步密钥」里生成")
    enc, mac = _subkeys(master)
    plain = json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    nonce = secrets.token_bytes(16)
    ct = _xor(plain, _keystream(enc, nonce, len(plain)))
    tag = hmac.new(mac, b"v1" + nonce + ct, hashlib.sha256).digest()
    return dict(PLAIN_HEAD, key_id=key_id(master), nonce=_b64(nonce),
                ct=_b64(ct), tag=_b64(tag))


def decrypt(blob, master=None):
    master = master or load_key()
    if not master:
        raise KeyMissing("本机没有同步密钥（data/hub/douyin/sync.key）")
    if not isinstance(blob, dict) or blob.get("alg") != PLAIN_HEAD["alg"]:
        raise AuthError("不认识的登录态格式")
    if blob.get("key_id") and blob["key_id"] != key_id(master):
        raise AuthError("同步密钥对不上（key_id 不同），换另一台机器那把")
    enc, mac = _subkeys(master)
    nonce = _unb64(blob.get("nonce"))
    ct = _unb64(blob.get("ct"))
    tag = _unb64(blob.get("tag"))
    want = hmac.new(mac, b"v1" + nonce + ct, hashlib.sha256).digest()
    if not hmac.compare_digest(tag, want):
        raise AuthError("登录态校验失败：密钥不对或文件被改过")
    plain = _xor(ct, _keystream(enc, nonce, len(ct)))
    try:
        return json.loads(plain.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise AuthError("登录态解密后不是合法 JSON")


# ------------------------------------------------------------------ 分片读写
def decrypt_file(path, master=None):
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            blob = json.load(f)
    except (OSError, ValueError):
        raise AuthError(f"读不了登录态文件：{os.path.basename(str(path))}")
    data = decrypt(blob, master)
    data.setdefault("accounts", [])
    return data


def load_shards(strict=False):
    """读全部分片。strict=True 时密钥缺失/不对直接抛错。"""
    out = []
    master = load_key()
    for p in auth_files():
        try:
            data = decrypt_file(p, master)
        except KeyMissing:
            if strict:
                raise
            continue
        except AuthError:
            if strict:
                raise
            continue
        data["_file"] = p.name
        data["_machine"] = data.get("machine") or p.name[len("auth."):-len(".json")]
        out.append(data)
    return out


def load_sessions(strict=False):
    """合并所有分片：{handle: {handle,name,cookie,at,machine}}，同一个号取最新。"""
    best = {}
    for shard in load_shards(strict=strict):
        for a in shard.get("accounts") or []:
            handle = str(a.get("handle") or "").strip()
            if not handle:
                continue
            at = str(a.get("at") or "")
            cur = best.get(handle)
            if cur is None or at >= str(cur.get("at") or ""):
                best[handle] = {
                    "handle": handle,
                    "name": a.get("name") or "",
                    "cookie": a.get("cookie") or "",
                    "at": at,
                    "machine": shard.get("_machine") or "",
                }
    return best


def read_local_shard():
    p = local_auth_file()
    if not p.exists():
        return {"machine": machine_name(), "updated": "", "accounts": []}
    try:
        data = decrypt_file(p)
    except KeyMissing:
        raise
    data.setdefault("machine", machine_name())
    data.setdefault("accounts", [])
    return data


def save_session(handle, cookie, name=""):
    """把某个号的 Cookie 加密写进本机分片；其他机器的分片不动。"""
    handle = str(handle or "").strip()
    if not handle:
        raise AuthError("抖音号不能为空")
    if not cookie:
        raise AuthError("Cookie 为空")
    master, _created = ensure_key()
    shard = read_local_shard()
    shard["machine"] = machine_name()
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    accounts = [a for a in shard.get("accounts") or []
                if str(a.get("handle")) != handle]
    accounts.append({"handle": handle, "name": name or "", "cookie": cookie, "at": now})
    shard["accounts"] = accounts
    shard["updated"] = now
    blob = encrypt(shard, master)
    p = local_auth_file()
    tmp = str(p) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(blob, f, ensure_ascii=False, indent=1)
        f.write("\n")
    os.replace(tmp, p)
    return now


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
    master = load_key()
    shard["updated"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    blob = encrypt(shard, master)
    tmp = str(p) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(blob, f, ensure_ascii=False, indent=1)
    os.replace(tmp, p)
    return True


def has_encrypted_auth():
    return bool(auth_files())


def rotate_all(new_master):
    """换密钥：用旧密钥解开全部分片，再用新密钥重新加密。返回处理的分片数。"""
    old = load_key()
    if not old:
        raise KeyMissing("当前没有密钥，直接导入新的即可")
    plain = []
    for p in auth_files():
        plain.append((p, decrypt_file(p, old)))
    for p, data in plain:
        data.pop("_file", None)
        data.pop("_machine", None)
        blob = encrypt(data, new_master)
        tmp = str(p) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(blob, f, ensure_ascii=False, indent=1)
            f.write("\n")
        os.replace(tmp, p)
    save_key(new_master)
    return len(plain)


# ------------------------------------------------------------------ 自检
def _selftest():
    master = new_key()
    blob = encrypt({"accounts": [{"handle": "1", "cookie": "sessionid=x"}]}, master)
    got = decrypt(blob, master)
    assert got["accounts"][0]["cookie"] == "sessionid=x"
    assert _b32decode(_b32encode(master)) == master
    bad = dict(blob)
    bad["ct"] = _b64(b"0" * 8)
    try:
        decrypt(bad, master)
        raise AssertionError("坏密文居然解开了")
    except AuthError:
        pass
    try:
        decrypt(blob, new_key())
        raise AssertionError("错密钥居然解开了")
    except AuthError:
        pass
    return True


if __name__ == "__main__":
    print("selftest", _selftest())
