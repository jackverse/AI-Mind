# -*- coding: utf-8 -*-
"""敏感串的本地加密：Windows DPAPI。

只做一件事：把授权码/令牌加密成 ``dpapi1:<base64>``，同机同用户可解；
换机器/换用户解不开（返回空，让上层提示重填）。DPAPI 不可用时退回明文，
并在调用方 UI 里提示。

和 core/mailer.py 里的实现同源；单独抽出来给欧路模块用，不动邮件代码。
"""
import base64
import ctypes
import os
from ctypes import wintypes

PREFIX = "dpapi1:"


class _Blob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD),
                ("pbData", ctypes.POINTER(ctypes.c_char))]


def available():
    return os.name == "nt"


def _crypt(data, unprotect):
    """Windows DPAPI 加解密；非 Windows / 调用失败抛 OSError。"""
    if os.name != "nt":
        raise OSError("DPAPI 只在 Windows 可用")
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    crypt32.CryptProtectData.argtypes = [
        ctypes.POINTER(_Blob), wintypes.LPCWSTR, ctypes.POINTER(_Blob),
        ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD,
        ctypes.POINTER(_Blob)]
    crypt32.CryptUnprotectData.argtypes = [
        ctypes.POINTER(_Blob), ctypes.POINTER(wintypes.LPWSTR),
        ctypes.POINTER(_Blob), ctypes.c_void_p, ctypes.c_void_p,
        wintypes.DWORD, ctypes.POINTER(_Blob)]
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p

    buf = ctypes.create_string_buffer(data, len(data))
    blob_in = _Blob(len(data), buf)
    blob_out = _Blob()
    if unprotect:
        ok = crypt32.CryptUnprotectData(
            ctypes.byref(blob_in), None, None, None, None, 0x1,
            ctypes.byref(blob_out))
    else:
        ok = crypt32.CryptProtectData(
            ctypes.byref(blob_in), None, None, None, None, 0x1,
            ctypes.byref(blob_out))
    if not ok:
        raise OSError(f"DPAPI 调用失败（{ctypes.get_last_error()}）")
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        kernel32.LocalFree(blob_out.pbData)


def seal(plain):
    """加密并返回存储串；失败退回明文（调用方可据 need_encrypt 提示）。"""
    plain = (plain or "").strip()
    if not plain:
        return ""
    try:
        blob = _crypt(plain.encode("utf-8"), unprotect=False)
        return PREFIX + base64.b64encode(blob).decode()
    except (OSError, ValueError):
        return plain


def open_sealed(value):
    """解密；明文原样返回；DPAPI 解不开（换机器/换用户）返回空串。"""
    value = (value or "").strip()
    if not value:
        return ""
    if not value.startswith(PREFIX):
        return value
    try:
        return _crypt(base64.b64decode(value[len(PREFIX):]),
                      unprotect=True).decode("utf-8")
    except (OSError, ValueError):
        return ""


def is_sealed(value):
    return (value or "").startswith(PREFIX)
