# -*- coding: utf-8 -*-
"""SMTP 发信：配置存取（data/hub/mail.json）+ 发送 + 中文报错。

只依赖标准库：
  · smtplib / email 发信（465 SSL 或 587 STARTTLS）
  · Windows DPAPI（ctypes 调 crypt32）加密保存授权码，换机器解不开需要重填

配置里不放明文密码（DPAPI 不可用时才退回明文，并在 UI 里提示）。
"""
import base64
import ctypes
import email.policy
import json
import os
import smtplib
import socket
import ssl
from ctypes import wintypes
from datetime import datetime
from email.message import EmailMessage
from email.utils import formataddr, formatdate

from . import paths

SECURITY = ("ssl", "starttls", "none")
SECURITY_LABEL = {"ssl": "SSL（465，推荐）",
                  "starttls": "STARTTLS（587）",
                  "none": "明文（仅内网/测试）"}

# 常见邮箱的一键预设：服务器 / 端口 / 加密 / 授权码页面 / 取码步骤
PRESETS = [
    {
        "label": "QQ 邮箱",
        "host": "smtp.qq.com", "port": 465, "security": "ssl",
        "domains": ("qq.com", "foxmail.com"),
        "url": "https://mail.qq.com/",
        "steps": [
            "登录后点右上角「设置」→「账户」",
            "往下找「POP3/IMAP/SMTP/Exchange/CardDAV/CalDAV服务」",
            "点「开启」，按提示用绑定手机发一条短信",
            "页面弹出 16 位授权码 → 点「复制」，回到这里会自动填上",
        ],
    },
    {
        "label": "163 邮箱",
        "host": "smtp.163.com", "port": 465, "security": "ssl",
        "domains": ("163.com",),
        "url": "https://mail.163.com/",
        "steps": [
            "登录后点顶部「设置」→「POP3/SMTP/IMAP」",
            "开启「SMTP 服务」，按提示扫码或发短信验证",
            "点「新增授权密码」，得到 16 位授权码",
            "把它复制下来，回到这里会自动填上（不是邮箱登录密码）",
        ],
    },
    {
        "label": "126 邮箱",
        "host": "smtp.126.com", "port": 465, "security": "ssl",
        "domains": ("126.com",),
        "url": "https://mail.126.com/",
        "steps": [
            "登录后点顶部「设置」→「POP3/SMTP/IMAP」",
            "开启「SMTP 服务」并完成验证",
            "点「新增授权密码」，复制 16 位授权码",
            "回到这里会自动填上",
        ],
    },
    {
        "label": "腾讯企业邮",
        "host": "smtp.exmail.qq.com", "port": 465, "security": "ssl",
        "domains": ("exmail.qq.com",),
        "url": "https://exmail.qq.com/",
        "steps": [
            "登录企业邮 →「设置」→「客户端设置」",
            "开启「安全登录」，生成「客户端专用密码」",
            "把这串密码复制下来（不是登录密码）",
            "回到这里会自动填上",
        ],
    },
    {
        "label": "阿里企业邮",
        "host": "smtp.qiye.aliyun.com", "port": 465, "security": "ssl",
        "domains": ("aliyun.com",),
        "url": "https://qiye.aliyun.com/",
        "steps": [
            "登录企业邮 →「设置」→「客户端设置」",
            "开启 SMTP 服务并生成客户端密码",
            "复制这串密码",
            "回到这里会自动填上",
        ],
    },
    {
        "label": "Gmail",
        "host": "smtp.gmail.com", "port": 465, "security": "ssl",
        "domains": ("gmail.com", "googlemail.com"),
        "url": "https://myaccount.google.com/apppasswords",
        "steps": [
            "先开两步验证（没开的话页面会先让你开）",
            "在「应用专用密码」里新建一个，名字随便填",
            "复制生成的 16 位密码",
            "注意：国内网络直连 smtp.gmail.com 不通（实测），一般用不了",
        ],
    },
    {
        "label": "Outlook",
        "host": "smtp.office365.com", "port": 587, "security": "starttls",
        "domains": ("outlook.com", "hotmail.com", "live.com", "office365.com"),
        "url": "https://account.microsoft.com/security",
        "steps": [
            "登录微软账户 →「安全」→「高级安全选项」",
            "找到「应用密码」并新建（没开两步验证可能看不到）",
            "复制生成的密码",
            "回到这里会自动填上",
        ],
    },
    {
        "label": "自定义",
        "host": "", "port": 465, "security": "ssl",
        "domains": (),
        "url": "",
        "steps": [
            "问邮箱服务商要 SMTP 服务器地址、端口和加密方式",
            "在邮箱后台开启 SMTP 服务，生成「授权码 / 客户端专用密码」",
            "把服务器、端口、授权码填到左边",
        ],
    },
]

DEFAULT = {
    "enabled": True,
    "host": "smtp.qq.com",
    "port": 465,
    "security": "ssl",
    "user": "",
    "from_name": "第二大脑",
    "to": [],
    "password_dpapi": "",
    "password": "",
    "daily": {"enabled": False, "time": "08:30", "last_sent": ""},
}


class MailError(Exception):
    """发信失败：message 是可以直接显示给用户的中文说明。"""


def preset_for(label):
    for p in PRESETS:
        if p["label"] == label:
            return p
    return PRESETS[-1]


def preset_for_address(addr):
    """按邮箱域名猜一个预设（qq.com→QQ、163.com→163…），猜不出返回 None。"""
    addr = (addr or "").strip().lower()
    if "@" not in addr:
        return None
    domain = addr.rsplit("@", 1)[-1]
    for p in PRESETS:
        for d in p["domains"]:
            if domain == d or domain.endswith("." + d):
                return p
    return None


# ---------------------------------------------------------------- 存储
def store_path():
    return paths.data_dir("hub") / "mail.json"


def log_path():
    return paths.data_dir("hub") / "mail.log"


def _norm(data):
    cfg = dict(DEFAULT)
    if isinstance(data, dict):
        cfg.update({k: v for k, v in data.items() if k in DEFAULT})
    cfg["host"] = str(cfg.get("host") or "").strip()
    try:
        cfg["port"] = int(cfg.get("port") or 465)
    except (TypeError, ValueError):
        cfg["port"] = 465
    if cfg.get("security") not in SECURITY:
        cfg["security"] = "ssl"
    for key in ("user", "from_name", "password_dpapi", "password"):
        cfg[key] = str(cfg.get(key) or "").strip()
    to = cfg.get("to")
    if isinstance(to, str):
        to = [t for t in to.replace(";", ",").replace(" ", ",").split(",")]
    cfg["to"] = [str(t).strip() for t in (to or []) if str(t).strip()]
    daily = cfg.get("daily") if isinstance(cfg.get("daily"), dict) else {}
    cfg["daily"] = {"enabled": bool(daily.get("enabled")),
                    "time": str(daily.get("time") or "08:30"),
                    "last_sent": str(daily.get("last_sent") or "")}
    return cfg


def load():
    p = store_path()
    if not p.exists():
        return _norm({})
    try:
        return _norm(json.loads(p.read_text(encoding="utf-8-sig")))
    except (OSError, json.JSONDecodeError):
        return _norm({})


def save(cfg):
    cfg = _norm(cfg)
    p = store_path()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(cfg, ensure_ascii=False, indent=1),
                     encoding="utf-8")
    except OSError as e:
        raise MailError(f"配置写不进去：{e}") from e
    return cfg


# ---------------------------------------------------------------- 授权码
class _Blob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD),
                ("pbData", ctypes.POINTER(ctypes.c_char))]


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


def set_password(cfg, plain):
    """写入授权码：优先 DPAPI，失败退回明文。返回 True=已加密。"""
    plain = (plain or "").strip()
    cfg["password"] = ""
    cfg["password_dpapi"] = ""
    if not plain:
        return True
    try:
        blob = _crypt(plain.encode("utf-8"), unprotect=False)
        cfg["password_dpapi"] = "dpapi1:" + base64.b64encode(blob).decode()
        return True
    except (OSError, ValueError):
        cfg["password"] = plain
        return False


def get_password(cfg):
    """取授权码；DPAPI 解不开（换机器/换用户）就返回空。"""
    if cfg.get("password_dpapi"):
        blob = cfg["password_dpapi"]
        raw = blob.split(":", 1)[1] if ":" in blob else blob
        try:
            return _crypt(base64.b64decode(raw), unprotect=True).decode("utf-8")
        except (OSError, ValueError):
            return ""
    return cfg.get("password") or ""


def has_password(cfg):
    return bool(get_password(cfg))


def is_set_up(cfg=None):
    cfg = cfg or load()
    return bool(cfg["host"] and cfg["user"] and cfg["to"] and has_password(cfg))


def readiness(cfg):
    """未配置时返回一句中文原因，配好了返回空串。"""
    if not cfg["host"]:
        return "还没填 SMTP 服务器"
    if not cfg["user"]:
        return "还没填发件邮箱"
    if not cfg["to"]:
        return "还没填收件邮箱"
    if not has_password(cfg):
        return "授权码没填，或换机器后解不开了（重填一次）"
    return ""


# ---------------------------------------------------------------- 发信
def _recipients(cfg, to=None):
    if to is None:
        return list(cfg["to"])
    if isinstance(to, str):
        to = [to]
    return [str(t).strip() for t in to if str(t).strip()]


def _connect(cfg, timeout=20):
    host, port, sec = cfg["host"], cfg["port"], cfg["security"]
    if sec == "ssl":
        return smtplib.SMTP_SSL(host, port, timeout=timeout,
                                context=ssl.create_default_context())
    server = smtplib.SMTP(host, port, timeout=timeout)
    server.ehlo()
    if sec == "starttls":
        server.starttls(context=ssl.create_default_context())
        server.ehlo()
    return server


def build_message(cfg, subject, body, to):
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = formataddr((cfg["from_name"] or "第二大脑", cfg["user"]))
    msg["To"] = ", ".join(to)
    msg["Date"] = formatdate(localtime=True)
    msg.set_content(body, subtype="plain", charset="utf-8")
    return msg


def send(cfg, subject, body, to=None, timeout=20, log=True):
    """同步发信。成功返回 {recipients, seconds}；失败抛 MailError。"""
    cfg = _norm(cfg)
    reason = readiness(cfg)
    if reason:
        raise MailError(reason + "。到「邮件」页填好再试。")
    to = _recipients(cfg, to)
    password = get_password(cfg)
    msg = build_message(cfg, subject, body, to)
    started = datetime.now()
    server = None
    try:
        server = _connect(cfg, timeout)
        try:
            server.login(cfg["user"], password)
        except UnicodeEncodeError as e:
            raise MailError(
                "授权码里混进了非英文/非数字字符。\n"
                "授权码是一串 ASCII 字母数字（QQ 邮箱 16 位），重新复制一次。") from e
        # 强制 7bit 序列化（中文走 base64）：send_message 会按 SMTP 策略把正文
        # 改成 8bit 直传，部分老服务器/中继会吃掉 8bit，收件人看到乱码。
        data = msg.as_bytes(policy=email.policy.SMTP.clone(cte_type="7bit"))
        refused = server.sendmail(cfg["user"], to, data)
        if refused:
            bad = "、".join(refused)
            raise MailError(f"部分收件人被拒：{bad}")
    except smtplib.SMTPAuthenticationError as e:
        raise MailError(
            "登录被拒（535）：邮箱地址或授权码不对。\n"
            "QQ/163 邮箱要去网页版「设置 → 账户」开启 SMTP 服务，"
            "填它生成的授权码，而不是登录密码。") from e
    except smtplib.SMTPServerDisconnected as e:
        raise MailError(
            "服务器中途断开连接（没给错误码）。\n"
            "最常见是授权码不对被风控（QQ 邮箱会直接掐线），"
            "或当前网络 IP 被邮箱限制。先在网页端重新生成授权码，"
            "再用 465 + SSL 重试。") from e
    except smtplib.SMTPRecipientsRefused as e:
        bad = "、".join(e.recipients or [])
        raise MailError(f"收件人被服务器拒绝：{bad}（地址写错或对方拒收）") from e
    except smtplib.SMTPSenderRefused as e:
        raise MailError(f"发件人被服务器拒绝：{e.smtp_error}") from e
    except smtplib.SMTPConnectError as e:
        raise MailError(f"连不上 {cfg['host']}:{cfg['port']}（{e.smtp_code}）") from e
    except (socket.timeout, TimeoutError) as e:
        raise MailError(
            f"连接 {cfg['host']}:{cfg['port']} 超时。\n"
            "检查网络；端口优先用 465 + SSL（587 在国内部分网络会断）。") from e
    except ssl.SSLError as e:
        raise MailError(
            f"TLS 握手失败：{e}。\n"
            "确认「加密」选项和端口匹配（465→SSL，587→STARTTLS）。") from e
    except smtplib.SMTPException as e:
        raise MailError(f"SMTP 出错：{e}") from e
    except OSError as e:
        raise MailError(
            f"连接 {cfg['host']}:{cfg['port']} 失败：{e}\n"
            "检查服务器地址拼写、端口、以及有没有被防火墙/公司网络拦掉。") from e
    finally:
        if server is not None:
            try:
                server.quit()
            except (smtplib.SMTPException, OSError):
                pass

    seconds = (datetime.now() - started).total_seconds()
    if log:
        write_log(f"OK   {cfg['user']} → {', '.join(to)}  "
                  f"主题《{subject}》 {seconds:.1f}s")
    return {"recipients": to, "seconds": seconds}


def send_test(cfg):
    """发一封测试邮件：把当前配置本身写进正文，方便排查。"""
    to = cfg["to"][0] if cfg["to"] else cfg["user"]
    body = (
        "这是一封来自 hub 的测试邮件。\n\n"
        f"发件邮箱：{cfg['user']}\n"
        f"服务器：{cfg['host']}:{cfg['port']}（{cfg['security']}）\n"
        f"收件人：{', '.join(cfg['to'] or [to])}\n"
        f"时间：{datetime.now():%Y-%m-%d %H:%M:%S}\n\n"
        "收到说明 SMTP 配置可用，之后「每日提醒」就能发到这个地址。\n"
    )
    return send(cfg, "hub 邮件测试", body)


def write_log(line):
    """追加一行到 data/hub/mail.log（最多留 500 行）。"""
    p = log_path()
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        lines = []
        if p.exists():
            try:
                lines = p.read_text(encoding="utf-8").splitlines()
            except OSError:
                lines = []
        lines.append(f"{stamp}  {line}")
        p.write_text("\n".join(lines[-500:]) + "\n", encoding="utf-8")
    except OSError:
        pass
