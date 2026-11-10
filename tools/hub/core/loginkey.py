# -*- coding: utf-8 -*-
"""登录态加密原语：SHAKE256 流加密 + HMAC-SHA256 认证（纯标准库）。

平台模块（`douyin_auth` / `xhs_auth`）自己负责「密钥放哪、分片怎么存」，
这里只管把一个 dict 加密成能进 git 的 JSON blob，以及反过来解回来。

约定：
  · 密钥 32 字节，展示成一串 base32（4 位一组加连字符），只存本机 `<平台>/sync.key`
  · 密文里带 `key_id`（密钥指纹），对不上就直接说"密钥不对"，不用等解出乱码
  · `domain` 把不同平台的子密钥岔开：同一把密钥也解不出另一个平台的密文
"""
import base64
import hashlib
import hmac
import json
import re
import secrets


class CryptoError(RuntimeError):
    """密文格式不对 / 认证失败 / 密钥格式不对。"""


HEAD = {"v": 1, "alg": "shake256-hmac"}


# ------------------------------------------------------------------ 密钥编码
def new_key():
    return secrets.token_bytes(32)


def key_id(master):
    return hashlib.sha256(master).hexdigest()[:12]


def encode_key(raw):
    """32 字节 -> 'ABCD-EFGH-…'（base32，去掉填充，4 位一组）。"""
    s = base64.b32encode(raw).decode("ascii").rstrip("=")
    return "-".join(s[i:i + 4] for i in range(0, len(s), 4))


def decode_key(text):
    """'ABCD-EFGH…' / 带空格 / 小写都能认；长度不对抛 CryptoError。"""
    s = re.sub(r"[\s\-]", "", str(text or "")).upper()
    if not s:
        raise CryptoError("密钥是空的")
    pad = "=" * ((8 - len(s) % 8) % 8)
    try:
        raw = base64.b32decode(s + pad)
    except Exception:                                        # noqa: BLE001
        raise CryptoError("密钥格式不对（应该是一串字母数字，形如 ABCD-EFGH-…）")
    if len(raw) != 32:
        raise CryptoError("密钥长度不对（需要 32 字节 / 52 个字母数字）")
    return raw


def _subkeys(master, domain):
    dom = str(domain or "").encode("utf-8")
    enc = hmac.new(master, dom + b"/enc", hashlib.sha256).digest()
    mac = hmac.new(master, dom + b"/mac", hashlib.sha256).digest()
    return enc, mac


def _keystream(key, nonce, n):
    out = bytearray()
    ctr = 0
    while len(out) < n:
        out.extend(hashlib.shake_256(key + nonce +
                                     ctr.to_bytes(8, "little")).digest(64))
        ctr += 1
    return bytes(out[:n])


def _xor(a, b):
    return bytes(x ^ y for x, y in zip(a, b))


# ------------------------------------------------------------------ 加解密
def encrypt(obj, master, domain):
    if not master or len(master) != 32:
        raise CryptoError("密钥不对（需要 32 字节）")
    enc, mac = _subkeys(master, domain)
    plain = json.dumps(obj, ensure_ascii=False,
                       separators=(",", ":")).encode("utf-8")
    nonce = secrets.token_bytes(16)
    ct = _xor(plain, _keystream(enc, nonce, len(plain)))
    tag = hmac.new(mac, b"v1" + nonce + ct, hashlib.sha256).digest()
    return dict(HEAD, key_id=key_id(master),
                nonce=base64.b64encode(nonce).decode("ascii"),
                ct=base64.b64encode(ct).decode("ascii"),
                tag=base64.b64encode(tag).decode("ascii"))


def decrypt(blob, master, domain):
    if not master:
        raise CryptoError("没有密钥")
    if not isinstance(blob, dict) or blob.get("alg") != HEAD["alg"]:
        raise CryptoError("不认识的登录态格式")
    if blob.get("key_id") and blob["key_id"] != key_id(master):
        raise CryptoError("密钥对不上（key_id 不同）")
    enc, mac = _subkeys(master, domain)
    try:
        nonce = base64.b64decode(str(blob.get("nonce") or ""), validate=True)
        ct = base64.b64decode(str(blob.get("ct") or ""), validate=True)
        tag = base64.b64decode(str(blob.get("tag") or ""), validate=True)
    except Exception:                                        # noqa: BLE001
        raise CryptoError("密文不是合法 base64")
    want = hmac.new(mac, b"v1" + nonce + ct, hashlib.sha256).digest()
    if not hmac.compare_digest(tag, want):
        raise CryptoError("登录态校验失败：密钥不对或文件被改过")
    plain = _xor(ct, _keystream(enc, nonce, len(ct)))
    try:
        return json.loads(plain.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise CryptoError("解密后不是合法 JSON")


# ------------------------------------------------------------------ 自检
def selftest():
    master = new_key()
    domain = "selftest/v1"
    blob = encrypt({"accounts": [{"handle": "1", "cookie": "a=b"}]}, master, domain)
    got = decrypt(blob, master, domain)
    assert got["accounts"][0]["cookie"] == "a=b"
    assert decode_key(encode_key(master)) == master
    bad = dict(blob)
    bad["ct"] = base64.b64encode(b"0" * 8).decode("ascii")
    for broken in (bad, dict(blob, tag=base64.b64encode(b"x" * 32).decode("ascii"))):
        try:
            decrypt(broken, master, domain)
            raise AssertionError("坏密文居然解开了")
        except CryptoError:
            pass
    try:                                    # 换密钥
        decrypt(blob, new_key(), domain)
        raise AssertionError("错密钥居然解开了")
    except CryptoError:
        pass
    try:                                    # 换 platform domain
        decrypt(blob, master, "other/v1")
        raise AssertionError("跨平台居然解开了")
    except CryptoError:
        pass
    return True


if __name__ == "__main__":
    print("selftest", selftest())
