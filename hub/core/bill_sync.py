# -*- coding: utf-8 -*-
"""账单自动同步：采集浏览器拿支付宝登录态 → 直接调后台查询接口 → 入库。

用到的接口（只认 Cookie + ctoken，不需要页面 securityId）：
  POST /enterprise/fundAccountDetail.json?ctoken=...&_output_charset=utf-8
  表单：ctoken / showType / accountType / settleBillRadio / billUserId /
        startDateInput / endDateInput / pageNum / pageSize / queryEntrance /
        querySettleAccount / switchToFrontEnd / _input_charset
  返回：{status:"succeed", result:{detail:[...], paging:{totalItems,...}, summary:{...}}}

**不做界面自动化**：只通过 CDP 读浏览器 Cookie（扫码登录一次），其余全是 HTTP。
"""
import json
import os
import time as _time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, timedelta

from . import bill, paths
from .xhs_sync import (_call, _cdp_http, _connect, _page_ws, browser_running,
                       open_browser, write_log)

ALIPAY_HOME = "https://b.alipay.com/page/mbillexprod/account/detail"
ALIPAY_LOGIN = "https://b.alipay.com/page/mbillexprod/account/detail"
INIT = "https://mbillexprod.alipay.com/enterprise/fundAccountDetailInit.json"
DETAIL = "https://mbillexprod.alipay.com/enterprise/fundAccountDetail.json"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36")

AUTH_COOKIES = ("ALIPAYJSESSIONID", "ctoken", "zone")


class BillSyncError(RuntimeError):
    pass


def alipay_cookies():
    """读浏览器里所有 .alipay.com 的 Cookie。"""
    ws = _page_ws()
    try:
        _call(ws, "Network.enable")
        res = _call(ws, "Network.getAllCookies")
    finally:
        try:
            ws.close()
        except Exception:
            pass
    jar = {}
    for c in res.get("cookies") or []:
        if "alipay" in (c.get("domain") or ""):
            jar[c["name"]] = c["value"]
    return jar


def _cookie_header(jar=None):
    jar = jar if jar is not None else alipay_cookies()
    return "; ".join(f"{k}={v}" for k, v in jar.items())


def is_logged_in(jar=None):
    jar = jar if jar is not None else alipay_cookies()
    return any(k in jar for k in AUTH_COOKIES)


def is_logged_in_safe():
    """浏览器没开、CDP 不通时返回 False，不抛异常。"""
    try:
        if not browser_running():
            return False
        return probe()
    except Exception:                                    # noqa: BLE001
        return False


def probe(timeout=15):
    """用后台 init 接口判断是否真的登录了（cookie 存在不代表登录）。"""
    jar = alipay_cookies()
    ct = jar.get("ctoken") or ""
    url = INIT + "?ctoken=" + urllib.parse.quote(ct) + "&_output_charset=utf-8"
    req = urllib.request.Request(url, headers={
        "User-Agent": UA, "Cookie": _cookie_header(jar), "Referer": ALIPAY_HOME})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8", "replace"))
        return str(data.get("status")) == "succeed"
    except Exception:                                    # noqa: BLE001
        return False


def open_alipay_login():
    """打开采集浏览器并跳到支付宝账单后台（没登录会显示扫码页）。"""
    if not browser_running():
        open_browser(headless=False)
    ws = _page_ws()
    try:
        _call(ws, "Page.enable")
        _call(ws, "Page.navigate", {"url": ALIPAY_LOGIN})
        _time.sleep(3)
    finally:
        try:
            ws.close()
        except Exception:
            pass


def _post_detail(cookie, bill_user_id, start, end, page=1, size=50, timeout=90):
    ct = ""
    for part in cookie.split(";"):
        part = part.strip()
        if part.startswith("ctoken="):
            ct = part.split("=", 1)[1]
            break
    data = {
        "ctoken": ct,
        "_output_charset": "utf-8",
        "showType": "0",
        "accountType": "",
        "settleBillRadio": "1",
        "billUserId": str(bill_user_id),
        "startDateInput": start,
        "endDateInput": end,
        "pageNum": str(page),
        "pageSize": str(size),
        "queryEntrance": "1",
        "querySettleAccount": "false",
        "switchToFrontEnd": "true",
        "_input_charset": "gbk",
    }
    url = (DETAIL + "?ctoken=" + urllib.parse.quote(ct) +
           "&_output_charset=utf-8")
    req = urllib.request.Request(url, data=urllib.parse.urlencode(data).encode(),
                                 headers={
                                     "User-Agent": UA,
                                     "Cookie": cookie,
                                     "Referer": ALIPAY_HOME,
                                     "Content-Type":
                                         "application/x-www-form-urlencoded; charset=UTF-8",
                                     "X-Requested-With": "XMLHttpRequest",
                                     "Accept": "application/json, text/plain, */*",
                                 })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
    except urllib.error.HTTPError as e:
        raise BillSyncError(f"HTTP {e.code}：{e.read()[:120]}")
    except urllib.error.URLError as e:
        raise BillSyncError(f"网络错误：{e.reason}")
    try:
        obj = json.loads(raw.decode("utf-8", "replace"))
    except ValueError:
        raise BillSyncError("接口返回的不是 JSON：" + raw[:160].decode("utf-8", "replace"))
    if str(obj.get("status")) == "succeed":
        return obj
    if str(obj.get("status")) in ("deny", "login") or obj.get("stat") == "deny":
        raise BillSyncError(
            "登录已失效（接口返回 deny，被带去登录页）。点「同步支付宝」重新扫码，"
            "扫完**先别关**那个浏览器窗口，工具要在同一个窗口里把数据拉完")
    raise BillSyncError(f"接口报错：status={obj.get('status')}")


def fetch_details(bill_user_id, start, end, cookie, log=None):
    """把区间内的账务明细全部翻页拉下来（原始 dict 列表）。"""
    out, page, size = [], 1, 50
    while True:
        obj = _post_detail(cookie, bill_user_id, start, end, page, size)
        res = obj.get("result") or {}
        rows = res.get("detail") or []
        out.extend(rows)
        paging = res.get("paging") or {}
        total = int(paging.get("totalItems") or 0)
        if log:
            log(f"  第 {page} 页：{len(rows)} 条（累计 {len(out)}/{total}）")
        if len(out) >= total or not rows:
            break
        page += 1
        if page > 200:
            break
    return out


def _money(text):
    try:
        return round(float(str(text or "0").replace(",", "").strip()), 2)
    except ValueError:
        return 0.0


def to_txn(item):
    """后台 detail 项 → 账单统一结构。"""
    amount = _money(item.get("tradeAmount"))
    when = str(item.get("tradeTime") or "")
    d = str(item.get("transDate") or when[:10])
    biz = str(item.get("accountType") or "")
    goods = str(item.get("goodsTitle") or "")
    name = str(item.get("otherAccountFullname") or "")
    return {
        "trade_no": str(item.get("tradeNo") or item.get("accountLogId") or ""),
        "time": when,
        "date": d,
        "month": d[:7],
        "direction": "expense" if amount < 0 else "income",
        "amount": abs(amount),
        "balance": _money(item.get("balance")),
        "biz_type": biz,
        "item": goods,
        "counterparty": str(item.get("otherAccount") or
                            item.get("otherAccountEmail") or ""),
        "counterparty_name": name,
        "category": bill.categorize(biz, goods, name),
        "note": str(item.get("transMemo") or item.get("buyerMemo") or ""),
        "platform": "alipay",
    }


def sync_alipay(days=180, log=None, accounts=None):
    """把每个已绑定支付宝账户最近 days 天的明细拉下来入库（最多 180 天）。

    定时任务在凌晨跑，浏览器不会开着：这里会临时起一个无头浏览器读 Cookie，
    读完就关，全程不碰界面。
    """
    log = log or write_log
    if days > 180:
        raise BillSyncError("支付宝账单最多回看 180 天，days 别超过 180")
    started = False
    if not browser_running():
        started = open_browser(headless=True)
        _time.sleep(1)
    try:
        return _sync_alipay_inner(days, log, accounts)
    finally:
        if started:
            from .xhs_sync import close_browser
            close_browser()


def _sync_alipay_inner(days, log, accounts):
    if not probe():
        raise BillSyncError("支付宝没登录：先点「同步支付宝」扫码")
    cookie = _cookie_header()

    targets = accounts or [a for a in bill.load_accounts()
                           if a.get("platform") == "alipay"]
    if not targets:
        raise BillSyncError("还没有支付宝账户：先导入一次后台导出的账单")

    end_day = date.today() + timedelta(days=1)
    start_day = date.today() - timedelta(days=days - 1)
    start = start_day.strftime("%Y-%m-%d") + " 00:00:00"
    end = end_day.strftime("%Y-%m-%d") + " 00:00:00"

    out = []
    for meta in targets:
        bill_user = str(meta.get("ext_id") or "")[:16]
        log(f"拉支付宝明细：{meta.get('name') or bill_user} {start[:10]} ~ {end[:10]}")
        rows = fetch_details(bill_user, start, end, cookie, log)
        txns = [to_txn(r) for r in rows if r.get("tradeNo")]
        info = bill.merge_txns(meta, txns, source="api")
        log(f"  ✓ {info['account'].get('name')}：新增 {info['added']} / 更新 {info['updated']}")
        out.append(info)
    return {"ok": True, "accounts": out}


def login_and_sync(days=180, timeout=300, on_status=None):
    """扫码登录支付宝 → 自动拉一次账单（给「同步支付宝」按钮用）。"""
    on_status = on_status or (lambda _s: None)
    on_status("正在打开支付宝登录页…")
    open_alipay_login()
    on_status("浏览器已打开：用支付宝扫码登录…")
    deadline = _time.time() + timeout
    while _time.time() < deadline:
        if probe():
            break
        _time.sleep(2)
    else:
        raise BillSyncError("等扫码超时，重试一次")
    on_status("登录成功，开始拉账单…")
    return sync_alipay(days=days)


def login_cli():
    """hub.exe --bill-login：命令行扫码 + 拉一次账单。"""
    try:
        result = login_and_sync(days=30, on_status=write_log)
        write_log(f"账单同步完成：{len(result.get('accounts') or [])} 个账户")
        return 0
    except Exception as e:                                # noqa: BLE001
        write_log(f"账单同步失败：{e}")
        return 1


# ------------------------------------------------------------------ 导出文件自动导入
def downloads_dir():
    return os.path.join(os.environ.get("USERPROFILE") or os.path.expanduser("~"),
                        "Downloads")


def desktop_dir():
    """真实桌面路径（可能被安全软件/同步盘重定向到其他盘）。"""
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders")
        val, _ = winreg.QueryValueEx(key, "Desktop")
        path = os.path.expandvars(val)
        if os.path.isdir(path):
            return path
    except Exception:                                    # noqa: BLE001
        pass
    return os.path.join(os.environ.get("USERPROFILE") or os.path.expanduser("~"),
                        "Desktop")


def _seen_file():
    return paths.data_dir("hub", "bills") / "imported.json"


def _load_seen():
    try:
        with open(_seen_file(), "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _save_seen(seen):
    try:
        p = _seen_file()
        with open(str(p) + ".tmp", "w", encoding="utf-8") as f:
            json.dump(seen, f, ensure_ascii=False, indent=1)
        os.replace(str(p) + ".tmp", str(p))
    except OSError:
        pass


BILL_NAME_HINTS = ("账单", "支付宝", "alipay", "微信", "wechat", "交易记录", "对账", "流水")


def scan_downloads(log=None, folder=None):
    """扫描 Downloads/桌面，把新出现的账单文件自动导进去（导出一次即可）。

    只认文件名带「账单/支付宝/微信/alipay/交易记录/对账/流水」的 csv/zip/xls/xlsx；
    同一个文件（名字+大小+修改时间）只导一次。
    """
    log = log or write_log
    folders = [folder] if folder else [downloads_dir(), desktop_dir()]
    seen = _load_seen()
    out = []
    for base in folders:
        try:
            names = os.listdir(base)
        except OSError:
            continue
        for name in names:
            low = name.lower()
            if not low.endswith((".csv", ".zip", ".xls", ".xlsx")):
                continue
            if not any(h in name.lower() or h in name for h in BILL_NAME_HINTS):
                continue
            path = os.path.join(base, name)
            try:
                st = os.stat(path)
            except OSError:
                continue
            key = f"{name}|{st.st_size}|{int(st.st_mtime)}"
            if key in seen:
                continue
            try:
                info = bill.import_file(path)
            except Exception:                            # noqa: BLE001
                continue                                 # 不是账单文件/需要密码，跳过
            seen[key] = _time.strftime("%Y-%m-%d %H:%M")
            out.append(info)
            log(f"自动导入 {name}：{info['account'].get('name')} "
                f"新增 {info['added']} / 更新 {info['updated']}")
    if out:
        _save_seen(seen)
    return out
