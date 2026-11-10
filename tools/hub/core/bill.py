# -*- coding: utf-8 -*-
"""账单模块：账户（支付宝/微信/银行卡）+ 导入 + 派生统计。

支付宝后台导出的「账务组合查询」是 Excel 2003 XML（.xls 后缀、内容是 SpreadsheetML），
文件头带 `#账号：<手机号>[<支付宝账号ID>]`，所以可以自动归属到账户，不会串账。

数据落 `data/hub/bills/`（不进 git）：
  · <platform>-<ext_id>.json  单账户：meta + txns（按交易号去重）+ imports
  · 账户列表由文件扫描得出（不用额外的 accounts.json）

其他平台（微信/银行卡）后续按同样结构接入，只要实现 parse_xxx() 即可。
"""
import json
import os
import re
import zipfile
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta

from . import paths, xlsx

NS = {"ss": "urn:schemas-microsoft-com:office:spreadsheet"}

PLATFORM_LABEL = {"alipay": "支付宝", "wechat": "微信", "bank": "银行卡"}

# 可手动指定的分类（明细里双击就能改）
CATEGORIES = ["餐饮", "出行", "购物", "宠物", "理财", "缴费", "通讯",
              "娱乐", "医疗", "住房", "转账", "其他"]

# 关键词 → 分类（先粗分，后续可调）
CATEGORY_RULES = [
    ("理财", ["理财", "余额宝", "基金", "申购", "赎回", "收益", "零钱通"]),
    ("缴费", ["税务", "社保", "公积金", "水费", "电费", "燃气", "话费", "缴费",
              "电信", "中国移动", "中国联通", "宽带"]),
    ("餐饮", ["外卖", "咖啡", "库迪", "瑞幸", "奶茶", "餐厅", "饭", "面馆", "烧烤",
              "肯德基", "麦当劳", "汉堡", "星巴克", "便利店", "超市", "小吃", "食堂",
              "老乡鸡", "夜食", "美团", "饿了么", "LAWSON", "罗森", "全家"]),
    ("出行", ["打车", "滴滴", "高德", "地铁", "公交", "加油", "石油", "石化", "停车",
              "单车", "火车", "机票", "高速"]),
    ("购物", ["淘宝", "天猫", "京东", "拼多多", "商城", "旗舰店", "百货"]),
    ("宠物", ["宠物", "狗粮", "猫粮", "宠物医院", "驱虫", "疫苗"]),
    ("住房", ["房租", "物业", "水费", "电费", "燃气", "宽带"]),
    ("通讯", ["微信认证", "企业微信", "话费", "流量"]),
    ("娱乐", ["电影", "游戏", "会员", "视频", "音乐", "演出", "KTV", "网咖", "电竞",
              "酒吧", "健身", "游泳", "腾讯天游"]),
    ("医疗", ["医院", "药房", "药店", "挂号", "体检"]),
    ("转账", ["转账", "红包", "亲属卡"]),
]


class BillError(RuntimeError):
    """账单导入失败。"""


class PasswordRequired(BillError):
    """加密压缩包需要密码（微信账单）。"""


# ------------------------------------------------------------------ 存储
def data_root():
    return paths.data_dir("hub", "bills")


def _safe(s):
    return re.sub(r"[^0-9A-Za-z_\-]", "_", str(s)) or "unknown"


def account_file(platform, ext_id):
    return data_root() / f"{_safe(platform)}-{_safe(ext_id)}.json"


def _read_json(path, default):
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _write_json(path, obj):
    tmp = str(path) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def load_accounts():
    """扫描账单目录，返回账户 meta 列表（每个账户一个文件）。"""
    out = []
    for p in sorted(data_root().glob("*.json")):
        data = _read_json(p, {})
        meta = data.get("account") or {}
        if meta.get("id"):
            out.append(meta)
    return out


def load_account(account_id):
    for meta in load_accounts():
        if meta.get("id") == account_id:
            return _read_json(account_file(meta["platform"], meta["ext_id"]), {})
    return {}


def remove_account(account_id):
    for meta in load_accounts():
        if meta.get("id") == account_id:
            try:
                os.remove(account_file(meta["platform"], meta["ext_id"]))
            except OSError:
                pass
            return True
    return False


# ------------------------------------------------------------------ 解析
def _cell_values(row):
    vals = []
    for cell in row.findall("ss:Cell", NS):
        data = cell.find("ss:Data", NS)
        vals.append("" if data is None else (data.text or ""))
    return vals


def _read_xml_bytes(raw):
    """把 SpreadsheetML 解析成二维表；兼容 zip 包一层。"""
    root = ET.fromstring(raw)
    table = root.find("ss:Worksheet/ss:Table", NS)
    if table is None:
        raise BillError("不是 Excel XML 表格")
    return [_cell_values(r) for r in table.findall("ss:Row", NS)]


def _rows_from_file(path):
    path = str(path)
    if path.lower().endswith(".zip"):
        with zipfile.ZipFile(path) as zf:
            names = [n for n in zf.namelist() if n.lower().endswith((".xls", ".xml"))]
            if not names:
                raise BillError("压缩包里没有账单表格")
            return _read_xml_bytes(zf.read(names[0]))
    with open(path, "rb") as f:
        return _read_xml_bytes(f.read())


def _money(text):
    s = str(text or "").replace("¥", "").replace(",", "").replace("元", "").strip()
    if not s or s in ("-", "—", "/"):
        return 0.0
    try:
        return round(float(s), 2)
    except ValueError:
        return 0.0


def categorize(biz_type, item, counterparty_name):
    text = f"{biz_type} {item} {counterparty_name}"
    for cat, words in CATEGORY_RULES:
        if any(w in text for w in words):
            return cat
    if "转账" in text or "红包" in text:
        return "转账"
    return "其他"


def parse_alipay(path):
    """解析支付宝「账务组合查询」：返回 {account, txns, period}。"""
    rows = _rows_from_file(path)
    if not rows:
        raise BillError("账单是空的")

    account = {"platform": "alipay", "name": "", "phone": "", "ext_id": ""}
    header_idx = None
    for i, row in enumerate(rows[:10]):
        joined = " ".join(row)
        m = re.search(r"#账号[:：]\s*(\d+)\[(\d+)\]", joined)
        if m and not account["phone"]:
            account["phone"] = m.group(1)
            account["ext_id"] = m.group(2)
        if "支付宝交易号" in joined and "入账时间" in joined:
            header_idx = i
            break
    if header_idx is None:
        raise BillError("认不出支付宝账单（表头里没找到「支付宝交易号/入账时间」）")

    header = [str(h).replace(" ", "") for h in rows[header_idx]]
    idx = {}
    for i, h in enumerate(header):
        idx[h] = i

    def col(row, *names):
        for n in names:
            i = idx.get(n)
            if i is not None and i < len(row):
                return str(row[i]).strip()
        return ""

    txns = []
    for row in rows[header_idx + 1:]:
        if not row or not any(str(c).strip() for c in row):
            continue
        first = str(row[0]).strip()
        if first.startswith("#"):
            period = re.search(r"#查询起始日期：(\S+ \S+)查询终止日期：(\S+ \S+)", first)
            if period:
                continue
            continue
        trade_no = col(row, "支付宝交易号")
        when = col(row, "入账时间")
        if not trade_no or not when:
            continue
        income = _money(col(row, "收入（+元）", "收入(+元)"))
        expense = _money(col(row, "支出（-元）", "支出(-元)"))
        amount = expense or income
        if not amount:
            continue
        biz = col(row, "账务类型")
        item = col(row, "商品名称")
        cp_account = col(row, "对方账户")
        cp_name = col(row, "对方名称")
        d = when[:10]
        txns.append({
            "trade_no": trade_no,
            "time": when,
            "date": d,
            "month": d[:7],
            "direction": "expense" if expense else "income",
            "amount": round(amount, 2),
            "balance": _money(col(row, "账户余额（元）", "账户余额(元)")),
            "biz_type": biz,
            "item": item,
            "counterparty": cp_account,
            "counterparty_name": cp_name,
            "category": categorize(biz, item, cp_name),
            "note": col(row, "备注") or col(row, "付款备注"),
            "platform": "alipay",
        })

    if not account["ext_id"]:
        account["ext_id"] = "unknown-" + re.sub(r"\D", "", os.path.basename(str(path)))[:20]
    if not account["name"]:
        phone = account["phone"]
        account["name"] = (f"支付宝 {phone[:3]}****{phone[-4:]}" if len(phone) >= 7
                           else "支付宝")
    account["id"] = f"alipay:{account['ext_id']}"
    account["platform"] = "alipay"
    account["label"] = PLATFORM_LABEL["alipay"]
    return {"account": account, "txns": txns}


# ------------------------------------------------------------------ 支付宝个人账单 CSV
CSV_HEADER_KEYS = ("交易时间", "交易对方")


def _decode_bytes(raw):
    for enc in ("utf-8-sig", "gb18030"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace")


def _csv_rows(text):
    import csv
    import io
    return list(csv.reader(io.StringIO(text)))


def find_account_by_mask(mask):
    """用账单里的「账号:138******41」匹配已绑定账户（比后 2~6 位）。"""
    m = re.match(r"(\d{2,4})\*+(\w{2,8})", str(mask or ""))
    if not m:
        return None
    pre, suf = m.group(1), m.group(2)
    for a in load_accounts():
        if a.get("platform") != "alipay":
            continue
        phone = str(a.get("phone") or "")
        if phone.startswith(pre) and phone.endswith(suf):
            return a
    return None


def _zip_read_csv(path, password=None):
    with zipfile.ZipFile(path) as zf:
        names = [n for n in zf.namelist() if n.lower().endswith(".csv")]
        if not names:
            raise BillError("压缩包里没有 CSV")
        pwd = password.encode("utf-8") if password else None
        try:
            return zf.read(names[0], pwd=pwd)
        except RuntimeError:
            raise PasswordRequired("这个压缩包有密码（微信账单），需要输入解压密码")


def parse_wechat_csv(path, password=None):
    """解析微信「个人对账」账单 CSV（加密 zip 也行）。

    表头：交易时间,交易类型,交易对方,商品,收/支,金额(元),支付方式,当前状态,交易单号,商户单号,备注
    """
    path = str(path)
    if path.lower().endswith(".zip"):
        raw = _zip_read_csv(path, password)
    else:
        with open(path, "rb") as f:
            raw = f.read()
    text = _decode_bytes(raw)
    rows = _csv_rows(text)
    header_idx = None
    for i, row in enumerate(rows[:20]):
        joined = ",".join(row)
        if "交易时间" in joined and ("收/支" in joined or "金额" in joined):
            header_idx = i
            break
    if header_idx is None:
        raise BillError("认不出微信账单 CSV（没找到「交易时间/收/支」表头）")
    header = [h.strip().replace("\ufeff", "") for h in rows[header_idx]]

    def col(row, *names):
        for n in names:
            if n in header:
                i = header.index(n)
                if i < len(row):
                    return str(row[i]).strip()
        return ""

    txns = []
    for row in rows[header_idx + 1:]:
        if not row or not any(str(c).strip() for c in row):
            continue
        when = col(row, "交易时间")
        if not when or "交易时间" in when:
            continue
        amount_raw = col(row, "金额(元)", "金额（元）", "金额").replace("¥", "").replace(",", "").strip()
        try:
            amount = float(amount_raw)
        except ValueError:
            continue
        direction_raw = col(row, "收/支")
        direction = "income" if "收" in direction_raw else "expense"
        biz = col(row, "交易类型")
        item = col(row, "商品")
        party = col(row, "交易对方")
        txns.append({
            "trade_no": col(row, "交易单号", "交易订单号") or f"{when}-{amount}-{party}",
            "time": when,
            "date": when[:10],
            "month": when[:7],
            "direction": direction,
            "amount": round(abs(amount), 2),
            "balance": 0.0,
            "biz_type": biz or "微信支付",
            "item": item,
            "counterparty": party,
            "counterparty_name": party,
            "category": categorize(biz, item, party),
            "note": col(row, "备注"),
            "platform": "wechat",
            "pay_method": col(row, "支付方式"),
        })
    return {"account": {"platform": "wechat", "ext_id": "personal",
                        "id": "wechat:personal", "name": "微信支付账单",
                        "label": "微信"},
            "txns": txns}


def _excel_datetime(v):
    """Excel 日期序列号（如 46326.559）→ 'YYYY-MM-DD HH:MM:SS'。"""
    s = str(v).strip()
    if re.fullmatch(r"\d+(\.\d+)?", s):
        base = datetime(1899, 12, 30)
        return (base + timedelta(days=float(s))).strftime("%Y-%m-%d %H:%M:%S")
    return s


def parse_wechat_xlsx(path):
    """解析微信「账单流水」xlsx（App/PC 导出，带前导说明行）。"""
    rows = xlsx.read_sheet(path, xlsx.sheet_names(path)[0])
    header_idx = None
    for i, row in enumerate(rows[:40]):
        joined = ",".join(str(c) for c in row)
        if "交易时间" in joined and "收/支" in joined:
            header_idx = i
            break
    if header_idx is None:
        raise BillError("认不出微信 xlsx 账单（没找到「交易时间/收/支」表头）")
    header = [str(h).strip() for h in rows[header_idx]]

    def col(row, *names):
        for n in names:
            if n in header:
                i = header.index(n)
                if i < len(row):
                    return str(row[i]).strip()
        return ""

    txns = []
    for row in rows[header_idx + 1:]:
        if not row or not any(str(c).strip() for c in row):
            continue
        when = _excel_datetime(col(row, "交易时间"))
        if not when or "交易时间" in when:
            continue
        amount_raw = col(row, "金额(元)", "金额（元）", "金额").replace("¥", "").replace(",", "").strip()
        try:
            amount = float(amount_raw)
        except ValueError:
            continue
        direction_raw = col(row, "收/支")
        if "收" in direction_raw and "支" not in direction_raw:
            direction = "income"
        elif "支" in direction_raw:
            direction = "expense"
        else:
            continue                                  # 中性交易（充值/提现）不统计
        biz = col(row, "交易类型")
        item = col(row, "商品")
        party = col(row, "交易对方")
        txns.append({
            "trade_no": col(row, "交易单号") or f"{when}-{amount}-{party}",
            "time": when,
            "date": when[:10],
            "month": when[:7],
            "direction": direction,
            "amount": round(abs(amount), 2),
            "balance": 0.0,
            "biz_type": biz or "微信支付",
            "item": item,
            "counterparty": party,
            "counterparty_name": party,
            "category": categorize(biz, item, party),
            "note": col(row, "备注") + ((" · " + col(row, "当前状态"))
                                        if col(row, "当前状态") else ""),
            "platform": "wechat",
            "pay_method": col(row, "支付方式"),
        })
    return {"account": {"platform": "wechat", "ext_id": "personal",
                        "id": "wechat:personal", "name": "微信支付账单",
                        "label": "微信"},
            "txns": txns}


def parse_alipay_csv(path):
    """解析支付宝个人账单导出的 CSV（网页「电子对账单」/ App 对账）。

    表头一般：交易时间,交易分类,交易对方,对方账号,商品说明,收/支,金额,收/付款方式,
              交易状态,交易订单号,商家订单号,备注
    前面可能带几行说明（含「账号:138******41」），用来自动归到已绑定账户。
    """
    path = str(path)
    if path.lower().endswith(".zip"):
        raw = _zip_read_csv(path, password)
    else:
        with open(path, "rb") as f:
            raw = f.read()
    text = _decode_bytes(raw)
    rows = _csv_rows(text)
    header_idx = None
    for i, row in enumerate(rows[:20]):
        joined = ",".join(row)
        if "交易时间" in joined and ("收/支" in joined or "金额" in joined):
            header_idx = i
            break
    if header_idx is None:
        raise BillError("认不出支付宝个人账单 CSV（没找到「交易时间/收/支」表头）")

    header = [h.strip().replace("\ufeff", "") for h in rows[header_idx]]
    mask = ""
    for row in rows[:header_idx]:
        m = re.search(r"账号[:：]\s*([0-9*]+)", ",".join(row))
        if m:
            mask = m.group(1)
            break

    def col(row, *names):
        for n in names:
            if n in header:
                i = header.index(n)
                if i < len(row):
                    return str(row[i]).strip()
        return ""

    txns = []
    for row in rows[header_idx + 1:]:
        if not row or not any(str(c).strip() for c in row):
            continue
        when = col(row, "交易时间", "创建时间")
        if not when or "交易时间" in when:
            continue
        amount_raw = col(row, "金额", "金额（元）").replace("¥", "").replace(",", "").strip()
        try:
            amount = float(amount_raw)
        except ValueError:
            continue
        direction_raw = col(row, "收/支", "收支")
        if "收" in direction_raw and "支" not in direction_raw:
            direction = "income"
        elif "支" in direction_raw:
            direction = "expense"
        else:
            direction = "income" if amount > 0 and "收入" in direction_raw else "expense"
        category_raw = col(row, "交易分类")
        counterparty = col(row, "交易对方")
        item = col(row, "商品说明")
        txns.append({
            "trade_no": col(row, "交易订单号", "交易号") or f"{when}-{amount}-{counterparty}",
            "time": when,
            "date": when[:10],
            "month": when[:7],
            "direction": direction,
            "amount": round(abs(amount), 2),
            "balance": 0.0,
            "biz_type": category_raw or "个人账单",
            "item": item,
            "counterparty": col(row, "对方账号"),
            "counterparty_name": counterparty,
            "category": categorize(category_raw, item, counterparty),
            "note": col(row, "备注"),
            "platform": "alipay",
        })
    account = find_account_by_mask(mask) or {
        "platform": "alipay", "ext_id": "personal",
        "id": "alipay:personal", "name": "支付宝个人账单", "label": "支付宝"}
    return {"account": account, "txns": txns}


# ------------------------------------------------------------------ 导入
def import_file(path, password=None):
    """导入一个账单文件，自动识别平台和格式。返回统计 dict。"""
    path = str(path)
    lower = path.lower()
    if lower.endswith(".csv") or (lower.endswith(".zip") and _zip_has_csv(path)):
        if lower.endswith(".zip"):
            text = _decode_bytes(_zip_read_csv(path, password))
        else:
            with open(path, "rb") as f:
                text = _decode_bytes(f.read())
        if "交易单号" in text[:4000] or "微信支付" in text[:1000]:
            parsed = parse_wechat_csv(path, password)
        else:
            parsed = parse_alipay_csv(path)
        parsed["file"] = path
        return _merge(parsed)

    if lower.endswith((".xlsx", ".xlsm")):
        parsed = parse_wechat_xlsx(path)
        parsed["file"] = path
        return _merge(parsed)

    rows = _rows_from_file(path)
    joined = " ".join(" ".join(r) for r in rows[:5])
    if "支付宝交易号" in joined or "账务组合查询" in path:
        parsed = parse_alipay(path)
        parsed["file"] = path
    else:
        raise BillError("认不出这个账单文件（支持支付宝「账务组合查询」和「个人账单 CSV」）")
    return _merge(parsed)


def _zip_has_csv(path):
    try:
        with zipfile.ZipFile(path) as zf:
            return any(n.lower().endswith(".csv") for n in zf.namelist())
    except (OSError, zipfile.BadZipFile):
        return False


def _merge(parsed):
    return merge_txns(parsed["account"], parsed["txns"],
                      source=os.path.basename(str(parsed.get("file") or "")))


def merge_txns(account, incoming, source=""):
    """按交易号把一批交易并进账户文件（自动建号），返回统计。

    保留用户手写的备注 / 「不计入统计」标记——重新同步不会覆盖掉。
    """
    path = account_file(account["platform"], account["ext_id"])
    data = _read_json(path, {})
    old = data.get("txns") or []
    index = {t.get("trade_no"): i for i, t in enumerate(old)}
    keep = ("user_note", "excluded", "user_category", "marked_at")
    added = updated = 0
    for t in incoming:
        key = t.get("trade_no")
        if key in index:
            prev = old[index[key]]
            for f in keep:
                if f in prev:
                    t[f] = prev[f]
            old[index[key]] = t
            updated += 1
        else:
            index[key] = len(old)
            old.append(t)
            added += 1
    old.sort(key=lambda t: t.get("time") or "", reverse=True)

    meta = dict(account)
    meta.setdefault("created", datetime.now().strftime("%Y-%m-%d %H:%M"))
    meta["updated"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    imports = (data.get("imports") or [])[-20:]
    imports.append({"file": source or "api",
                    "at": datetime.now().strftime("%Y-%m-%d %H:%M"),
                    "rows": len(incoming)})
    dates = [t["date"] for t in old if t.get("date")]
    _write_json(path, {
        "account": meta,
        "txns": old,
        "imports": imports,
        "range": [min(dates), max(dates)] if dates else [],
    })
    return {"account": meta, "added": added, "updated": updated,
            "rows": len(incoming), "total": len(old)}


def find_alipay_account(bill_user_id):
    """按 billUserId（支付宝账号前 16 位）找已绑定账户；找不到给个待建 meta。"""
    bill_user_id = str(bill_user_id)
    for a in load_accounts():
        if a.get("platform") == "alipay" and (
                str(a.get("ext_id")) == bill_user_id
                or str(a.get("ext_id")).startswith(bill_user_id)):
            return a
    tail = bill_user_id[-4:]
    return {"platform": "alipay", "ext_id": bill_user_id,
            "id": f"alipay:{bill_user_id}", "name": f"支付宝 {tail}",
            "phone": "", "label": "支付宝"}


def update_txn(account_id, trade_no, **fields):
    """改单笔的备注 / 排除标记（不删数据，随时可恢复）。"""
    for meta in load_accounts():
        if meta.get("id") != account_id:
            continue
        path = account_file(meta["platform"], meta["ext_id"])
        data = _read_json(path, {})
        for t in data.get("txns") or []:
            if t.get("trade_no") == trade_no:
                for k in ("user_note", "excluded", "user_category"):
                    if k in fields:
                        t[k] = fields[k]
                t["marked_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
                _write_json(path, data)
                return t
        return None
    return None


# ------------------------------------------------------------------ 统计
def _as_date(s):
    try:
        return datetime.strptime(str(s)[:10], "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def summarize(account_ids=None, days=30, today=None):
    """把所有（或指定）账户的交易合成一份视图。"""
    today = today or date.today()
    start = today - timedelta(days=days - 1)
    accounts = [a for a in load_accounts()
                if not account_ids or a["id"] in account_ids]

    txns = []
    for meta in accounts:
        data = _read_json(account_file(meta["platform"], meta["ext_id"]), {})
        for t in data.get("txns") or []:
            t = dict(t)
            t["account_id"] = meta["id"]
            t["account_name"] = meta.get("name") or meta["id"]
            t["category"] = t.get("user_category") or t.get("category") or "其他"
            txns.append(t)
    txns.sort(key=lambda t: t.get("time") or "", reverse=True)

    in_window = [t for t in txns if _as_date(t.get("date")) and
                 start <= _as_date(t["date"]) <= today]
    active = [t for t in in_window if not t.get("excluded")]
    excluded_count = len(in_window) - len(active)

    expense = sum(t["amount"] for t in active if t["direction"] == "expense")
    income = sum(t["amount"] for t in active if t["direction"] == "income")

    by_day = {}
    for t in active:
        rec = by_day.setdefault(t["date"], {"date": t["date"], "expense": 0.0,
                                            "income": 0.0, "count": 0})
        rec[t["direction"]] += t["amount"]
        rec["count"] += 1
    daily = []
    cur = start
    while cur <= today:
        key = cur.strftime("%Y-%m-%d")
        daily.append(by_day.get(key, {"date": key, "expense": 0.0,
                                      "income": 0.0, "count": 0}))
        cur += timedelta(days=1)

    cats = {}
    for t in active:
        if t["direction"] == "expense":
            cats[t["category"]] = round(cats.get(t["category"], 0.0) + t["amount"], 2)
    top_cats = sorted(cats.items(), key=lambda kv: -kv[1])

    merchants = {}
    for t in active:
        if t["direction"] != "expense":
            continue
        name = t.get("counterparty_name") or t.get("item") or "未知"
        rec = merchants.setdefault(name, {"name": name, "amount": 0.0, "count": 0})
        rec["amount"] = round(rec["amount"] + t["amount"], 2)
        rec["count"] += 1
    top_merchants = sorted(merchants.values(), key=lambda m: -m["amount"])[:8]

    this_month = [t for t in txns if str(t.get("date", "")).startswith(today.strftime("%Y-%m"))
                  and not t.get("excluded")]
    month_expense = sum(t["amount"] for t in this_month if t["direction"] == "expense")

    return {
        "accounts": accounts,
        "txns": in_window,
        "all_count": len(txns),
        "excluded_count": excluded_count,
        "window": [start.strftime("%Y-%m-%d"), today.strftime("%Y-%m-%d")],
        "days": daily,
        "expense": round(expense, 2),
        "income": round(income, 2),
        "count": len(active),
        "avg_day": round(expense / max(1, days), 2),
        "categories": top_cats,
        "merchants": top_merchants,
        "month_expense": round(month_expense, 2),
        "month": today.strftime("%Y-%m"),
    }


def fmt_money(v, sign=True):
    try:
        return (f"{v:,.2f}")
    except (TypeError, ValueError):
        return "-"
