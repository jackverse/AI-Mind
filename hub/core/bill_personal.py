# -*- coding: utf-8 -*-
"""支付宝个人账单（consumeprod）自动抓取：只读页面，不点任何按钮。

机制：
  · 列表是 `POST /record/standard.htm` 的表单提交，返回服务端渲染的 HTML
  · 每次新查询都可能被 302 到 checkSecurity.htm，要求手机扫码验证；验证通过后
    页面自动回到账单并渲染数据
  · 我们的做法：用页面自己的表单提交（form.submit，属于“导航”，不是点界面），
    然后读渲染出来的表格；遇到校验页就把它留在前台让用户扫码，扫完继续

只读 DOM，不模拟点击/输入；授权动作全部由用户完成。
"""
import json
import re
import time

from . import bill
from .xhs_sync import (_call, _cdp_http, _connect, _eval, open_browser,
                       browser_running, write_log)

BASE = "https://consumeprod.alipay.com/record/standard.htm"


class AuthRequired(RuntimeError):
    def __init__(self, url, kind="login"):
        self.url = url
        self.kind = kind
        super().__init__("需要授权：" + url)


class PersonalError(RuntimeError):
    pass


def _page():
    tabs = [t for t in (_cdp_http("/json/list") or []) if t.get("type") == "page"]
    if not tabs:
        raise PersonalError("浏览器里没有标签页")
    tab = next((t for t in tabs
                if "consumeprod" in (t.get("url") or "")
                or "auth.alipay" in (t.get("url") or "")
                or "checkSecurity" in (t.get("url") or "")), tabs[0])
    return _connect(tab["webSocketDebuggerUrl"])


def state():
    ws = _page()
    try:
        _call(ws, "Runtime.enable")
        return _eval(ws, """(() => ({
            url: location.href,
            title: document.title,
            ready: document.readyState,
            rows: (document.body.innerText || '').split('流水号').length - 1
        }))()""")
    finally:
        ws.close()


def navigate(url, wait=3.0):
    ws = _page()
    try:
        _call(ws, "Page.enable")
        _call(ws, "Page.navigate", {"url": url})
    finally:
        ws.close()
    time.sleep(wait)


def submit_form(params):
    """在页面里创建一个表单并提交（等价于页面自己的查询，不是点按钮）。"""
    js = """(() => {
      const f = document.createElement('form');
      f.method = 'POST';
      f.action = 'https://consumeprod.alipay.com/record/standard.htm';
      const p = %s;
      for (const k in p) {
        const i = document.createElement('input');
        i.type = 'hidden'; i.name = k; i.value = p[k];
        f.appendChild(i);
      }
      document.body.appendChild(f);
      f.submit();
      return true;
    })()""" % json.dumps(params, ensure_ascii=False)
    ws = _page()
    try:
        _call(ws, "Runtime.evaluate", {"expression": js, "returnByValue": True})
    finally:
        try:
            ws.close()
        except Exception:
            pass
    time.sleep(3)


ROWS_JS = r"""(() => Array.from(document.querySelectorAll('#tradeRecordsIndex tbody tr.J-item')).map(tr => {
  const timeTd = tr.querySelector('td.time');
  const nameTd = tr.querySelector('td.name');
  const link = tr.querySelector('td.name a[href]');
  const amt = tr.querySelector('td.amount');
  const st = tr.querySelector('td.status');
  const trade = tr.querySelector('a.J-tradeNo');
  const party = nameTd ? nameTd.querySelector('p.name') : null;
  return {
    time: timeTd ? timeTd.innerText.replace(/\s+/g, ' ').trim() : '',
    title: link ? link.innerText.trim() : '',
    party: party ? party.innerText.trim() : '',
    trade_no: trade ? (trade.getAttribute('data-clipboard-text') || '') : '',
    amount: amt ? amt.innerText.replace(/\s+/g, ' ').trim() : '',
    status: st ? st.innerText.replace(/\s+/g, ' ').trim() : '',
    href: link ? link.getAttribute('href') : ''
  };
}))()"""


def extract_rows():
    ws = _page()
    try:
        _call(ws, "Runtime.enable")
        return _eval(ws, ROWS_JS) or []
    finally:
        ws.close()


def _fmt_time(href, text):
    m = re.search(r"gmtBizCreate=(\d{14})", href or "")
    if m:
        s = m.group(1)
        return f"{s[:4]}-{s[4:6]}-{s[6:8]} {s[8:10]}:{s[10:12]}:{s[12:14]}"
    # 兜底：今天/昨天 HH:MM（只到分钟，日期按今天/昨天推）
    from datetime import date, timedelta
    today = date.today()
    m = re.search(r"(\d{1,2}):(\d{2})", text or "")
    if not m:
        return ""
    day = today
    if "昨天" in text:
        day = today - timedelta(days=1)
    return f"{day.isoformat()} {int(m.group(1)):02d}:{m.group(2)}:00"


def _to_txn(row):
    amount_text = (row.get("amount") or "").replace(" ", "")
    m = re.search(r"([+-]?)\s*([\d,]+(?:\.\d+)?)", amount_text)
    if not m:
        return None
    amount = float(m.group(2).replace(",", ""))
    sign = m.group(1)
    when = _fmt_time(row.get("href"), row.get("time"))
    party = (row.get("party") or "").rstrip("| ").strip()
    biz = row.get("title") or ""
    return {
        "trade_no": row.get("trade_no") or f"{when}-{amount}-{party}",
        "time": when,
        "date": when[:10],
        "month": when[:7],
        "direction": "expense" if sign == "-" or (sign == "" and "支出" in amount_text) else "income",
        "amount": amount,
        "balance": 0.0,
        "biz_type": biz,
        "item": " ".join(x for x in (biz, party) if x),
        "counterparty": party,
        "counterparty_name": party,
        "category": bill.categorize(biz, party, ""),
        "note": "",
        "platform": "alipay",
    }


def _params(start, end, page):
    return {
        "dateType": "createDate",
        "dateRange": "custom",
        "beginDate": start.strftime("%Y.%m.%d"),
        "endDate": end.strftime("%Y.%m.%d"),
        "beginTime": "00:00",
        "endTime": "24:00",
        "tradeType": "ALL",
        "status": "all",
        "fundFlow": "all",
        "keyword": "",
        "keyValue": "",
        "minAmount": "",
        "maxAmount": "",
        "pageNum": str(page),
    }


def _wait_login(timeout=300, on_status=None):
    """等用户在 auth.alipay.com 完成扫码登录。"""
    on_status = on_status or (lambda _s: None)
    deadline = time.time() + timeout
    while time.time() < deadline:
        url = state().get("url") or ""
        if "auth.alipay.com" in url or "/login" in url:
            on_status("请在浏览器里用支付宝扫码登录…")
            time.sleep(3)
            continue
        return True
    raise AuthRequired("login", "login")


def _wait_security(timeout=300, on_status=None):
    """等用户过掉 checkSecurity 的扫码验证，回到账单页。"""
    on_status = on_status or (lambda _s: None)
    deadline = time.time() + timeout
    while time.time() < deadline:
        st = state()
        url = st.get("url") or ""
        if "checkSecurity" in url:
            on_status("请在浏览器里用支付宝扫码验证身份…")
            time.sleep(3)
            continue
        if "consumeprod.alipay.com" in url:
            return st
        time.sleep(2)
    raise AuthRequired("security", "security")


def sync_personal(days=31, on_status=None, log=None):
    """拉最近 days 天的个人账单（按账号去重入库）；授权由用户在浏览器里完成。"""
    from datetime import date, timedelta
    on_status = on_status or (lambda _s: None)
    log = log or write_log

    if not browser_running():
        open_browser(headless=False)
    navigate(BASE, wait=4)

    st = state()
    if "auth.alipay.com" in (st.get("url") or "") or "/login" in (st.get("url") or ""):
        _wait_login(on_status=on_status)
        navigate(BASE, wait=4)

    end = date.today()
    start = end - timedelta(days=days - 1)
    on_status("正在提交查询…")
    submit_form(_params(start, end, 1))
    st = state()
    if "checkSecurity" in (st.get("url") or ""):
        _wait_security(on_status=on_status)
        st = state()
        if st.get("rows", 0) == 0:
            submit_form(_params(start, end, 1))
    rows = extract_rows()
    if not rows:
        raise PersonalError("没抓到明细（页面可能没数据或没登录）")
    out = [t for t in (_to_txn(r) for r in rows) if t]

    if not out:
        raise PersonalError("没抓到明细（页面可能没数据或没登录）")

    accounts = [a for a in bill.load_accounts() if a.get("platform") == "alipay"]
    meta = accounts[0] if accounts else {
        "platform": "alipay", "ext_id": "personal",
        "id": "alipay:personal", "name": "支付宝个人账单", "label": "支付宝"}
    info = bill.merge_txns(meta, out, source="consumeprod")
    log(f"个人账单：{start} ~ {end} 抓到 {len(out)} 条，新增 {info['added']} / 更新 {info['updated']}")
    return {"ok": True, "added": info["added"], "updated": info["updated"],
            "total": info["total"], "rows": len(out)}
