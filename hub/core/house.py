# -*- coding: utf-8 -*-
"""买房：贷款方案测算 + 多套房源跟踪。

数据：`data/hub/house/house.json`（业务数据，是否进 git 由数据仓库自己决定）。
格式见 hub/README.md「买房」一节；桌面 hub 与 hub-web 共用本模块。

文件结构（节选）：
{
  "version": 1,
  "updated": "YYYY-MM-DD",
  "profile": {
    "city": "", "district": "", "property_type": "",
    "fund": {
      "provident_balance": 0,             # 公积金余额（元）
      "supplementary_balance": 0,        # 补充公积金余额（元）
      "rates": {"provident": 2.6, "commercial": 3.05}   # 年利率 %
    },
    "plans": [
      {"key": "plan1", "name": "组合贷示例",
       "provident":  {"amount": 300000, "years": 18},
       "commercial": {"amount": 300000, "years": 30},
       "quote": {"monthly": 0, "interest_total": 0,
                 "captured": "YYYY-MM-DD", "source": ""}}
    ],
    "default_plan": "plan1"
  },
  "properties": [
    {"id": "h-1", "community": "示例小区", "building": "1号楼", "unit": "101",
     "district": "", "area_name": "",
     "layout": "2室1厅", "area_sqm": 0, "floor": "", "age_years": 0,
     "orientation": "", "decoration": "", "elevator": false,
     "price": 0, "down_payment": null,
     "fees": {"tax": 0, "agency": 0, "other": 0},
     "status": "关注", "rating": 0, "tags": [],
     "url": "", "links": [], "price_history": [], "visits": [], "note": "",
     "first_seen": "YYYY-MM-DD", "updated": "YYYY-MM-DD"}
  ]
}
"""
import json
import os
from datetime import date

from . import paths

STATUSES = ["关注", "约看", "已看", "出价", "放弃", "成交"]
KIND_LABEL = {"provident": "公积金", "commercial": "商贷"}


# ---------------------------------------------------------------- 存储
def data_root():
    return paths.data_dir("hub", "house")


def data_file():
    return data_root() / "house.json"


def default_data():
    return {
        "version": 1,
        "updated": date.today().isoformat(),
        "profile": {
            "city": "",
            "district": "",
            "property_type": "",
            "fund": {
                "provident_balance": 0,
                "supplementary_balance": 0,
                "rates": {"provident": 2.6, "commercial": 3.05},
            },
            "plans": [],
            "default_plan": "",
        },
        "properties": [],
    }


def load():
    p = data_file()
    if not p.is_file():
        data = default_data()
        save(data)
        return data
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = default_data()
    return normalize(data)


def save(data):
    data["updated"] = date.today().isoformat()
    p = data_file()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n",
                   encoding="utf-8")
    os.replace(tmp, p)
    return data


# ---------------------------------------------------------------- 规整
def _num(v, default=0.0):
    try:
        if v is None or v == "":
            return default
        return float(v)
    except (TypeError, ValueError):
        return default


def normalize(data):
    data.setdefault("version", 1)
    prof = data.setdefault("profile", {})
    prof.setdefault("city", "")
    prof.setdefault("district", "")
    prof.setdefault("property_type", "")

    fund = prof.setdefault("fund", {})
    fund["provident_balance"] = _num(fund.get("provident_balance"))
    fund["supplementary_balance"] = _num(fund.get("supplementary_balance"))
    rates = fund.setdefault("rates", {})
    rates["provident"] = _num(rates.get("provident"), 2.6)
    rates["commercial"] = _num(rates.get("commercial"), 3.05)

    plans = []
    for i, raw in enumerate(prof.get("plans") or []):
        plan = dict(raw or {})
        plan.setdefault("key", "plan%d" % (i + 1))
        plan.setdefault("name", plan["key"])
        for kind in ("provident", "commercial"):
            part = dict(plan.get(kind) or {})
            part["amount"] = _num(part.get("amount"))
            part["years"] = int(_num(part.get("years")))
            plan[kind] = part
        plans.append(plan)
    prof["plans"] = plans
    keys = [p["key"] for p in plans]
    if prof.get("default_plan") not in keys:
        prof["default_plan"] = keys[0] if keys else ""

    props = data.get("properties")
    if not isinstance(props, list):
        props = []
    seen = set()
    for raw in props:
        _normalize_prop(raw)
        base = raw.get("id") or "h-property"
        pid, n = base, 1
        while pid in seen:
            n += 1
            pid = "%s-%d" % (base, n)
        raw["id"] = pid
        seen.add(pid)
    data["properties"] = props
    return data


def _normalize_prop(p):
    p.setdefault("id", "")
    for k in ("community", "building", "unit", "district", "area_name",
              "layout", "floor", "orientation", "decoration", "status",
              "url", "note"):
        p.setdefault(k, "")
    p["area_sqm"] = _num(p.get("area_sqm"))
    p["age_years"] = _num(p.get("age_years"))
    p["price"] = _num(p.get("price"))
    down = p.get("down_payment")
    p["down_payment"] = None if down in (None, "") else _num(down)
    p["rating"] = int(_num(p.get("rating")))
    p["elevator"] = bool(p.get("elevator"))
    fees = p.setdefault("fees", {})
    for k in ("tax", "agency", "other"):
        fees[k] = _num(fees.get(k))
    if p.get("status") not in STATUSES:
        p["status"] = "关注"
    if not isinstance(p.get("tags"), list):
        p["tags"] = [t.strip() for t in str(p.get("tags") or "").split(",") if t.strip()]

    links = []
    for item in p.get("links") or []:
        if isinstance(item, str):
            links.append({"url": item, "title": _url_title(item), "added": ""})
        elif isinstance(item, dict) and item.get("url"):
            links.append({"url": item["url"],
                          "title": item.get("title") or _url_title(item["url"]),
                          "added": item.get("added", "")})
    p["links"] = links

    hist = []
    for item in p.get("price_history") or []:
        if isinstance(item, dict) and item.get("price"):
            hist.append({"date": item.get("date", ""),
                         "price": _num(item["price"]),
                         "note": item.get("note", "")})
    p["price_history"] = sorted(hist, key=lambda h: h.get("date") or "")

    visits = []
    for item in p.get("visits") or []:
        if isinstance(item, dict) and item.get("note"):
            visits.append({"date": item.get("date", ""), "note": item["note"]})
        elif isinstance(item, str):
            visits.append({"date": "", "note": item})
    p["visits"] = sorted(visits, key=lambda v: v.get("date") or "")

    today = date.today().isoformat()
    p.setdefault("first_seen", today)
    p.setdefault("updated", p.get("first_seen") or today)


def _url_title(url):
    try:
        host = url.split("//", 1)[-1].split("/", 1)[0]
        return host.replace("www.", "") or "链接"
    except (AttributeError, IndexError):
        return "链接"


# ---------------------------------------------------------------- 增删改
def _blank():
    today = date.today().isoformat()
    return {
        "id": "", "community": "", "building": "", "unit": "",
        "district": "", "area_name": "", "layout": "", "area_sqm": 0,
        "floor": "", "age_years": 0, "orientation": "", "decoration": "",
        "elevator": False, "price": 0, "down_payment": None,
        "fees": {"tax": 0, "agency": 0, "other": 0},
        "status": "关注", "rating": 0, "tags": [],
        "url": "", "links": [], "price_history": [], "visits": [],
        "note": "", "first_seen": today, "updated": today,
    }


def new_id(data):
    today = date.today().strftime("%Y%m%d")
    ids = {p.get("id") for p in data.get("properties") or []}
    n = 1
    while "h%s-%d" % (today, n) in ids:
        n += 1
    return "h%s-%d" % (today, n)


def add(data, fields):
    p = _blank()
    p.update(fields or {})
    p["id"] = new_id(data)
    today = date.today().isoformat()
    p["first_seen"] = today
    p["updated"] = today
    if p.get("price"):
        p["price_history"] = [{"date": today, "price": p["price"], "note": "首次记录"}]
    data.setdefault("properties", []).append(p)
    save(data)
    return p


def get(data, pid):
    for p in data.get("properties") or []:
        if p.get("id") == pid:
            return p
    return None


def update(data, pid, fields):
    p = get(data, pid)
    if p is None:
        return None
    old_price = _num(p.get("price"))
    p.update(fields or {})
    today = date.today().isoformat()
    p["updated"] = today
    new_price = _num(p.get("price"))
    if new_price and abs(new_price - old_price) > 0.5:
        hist = p.setdefault("price_history", [])
        if not hist or hist[-1].get("price") != new_price:
            hist.append({"date": today, "price": new_price, "note": "改价"})
    save(data)
    return p


def remove(data, pid):
    props = data.get("properties") or []
    data["properties"] = [p for p in props if p.get("id") != pid]
    save(data)


def add_visit(data, pid, note, day=None):
    p = get(data, pid)
    if p is None or not note:
        return None
    p.setdefault("visits", []).append(
        {"date": day or date.today().isoformat(), "note": note})
    p["updated"] = date.today().isoformat()
    save(data)
    return p


# ---------------------------------------------------------------- 贷款测算
def monthly_payment(principal, rate_pct, years):
    """等额本息月供（元）。"""
    principal = _num(principal)
    years = int(_num(years))
    if principal <= 0 or years <= 0:
        return 0.0
    r = _num(rate_pct) / 100.0 / 12.0
    n = years * 12
    if r <= 0:
        return principal / n
    return principal * r * (1 + r) ** n / ((1 + r) ** n - 1)


def plan_stats(profile, plan):
    """单个方案的月供/利息；公积金先还完时给出之后的月供。"""
    rates = ((profile or {}).get("fund") or {}).get("rates") or {}
    loans = []
    for kind in ("provident", "commercial"):
        part = (plan or {}).get(kind) or {}
        amount = _num(part.get("amount"))
        years = int(_num(part.get("years")))
        rate = _num(rates.get(kind))
        m = monthly_payment(amount, rate, years)
        loans.append({
            "kind": kind, "label": KIND_LABEL[kind], "amount": amount,
            "years": years, "rate": rate, "monthly": m,
            "interest": m * years * 12 - amount if years else 0.0,
            "total": m * years * 12 if years else 0.0,
        })
    monthly = sum(l["monthly"] for l in loans)
    interest = sum(l["interest"] for l in loans)
    live = [l for l in loans if l["amount"] > 0 and l["years"] > 0]
    shortest = min((l["years"] for l in live), default=0)
    after = sum(l["monthly"] for l in live if l["years"] > shortest)
    quote = (plan or {}).get("quote") or {}
    q_monthly = _num(quote.get("monthly"), 0)
    return {
        "key": (plan or {}).get("key", ""),
        "name": (plan or {}).get("name", ""),
        "short": (plan or {}).get("short", ""),
        "condition": (plan or {}).get("condition", ""),
        "loans": loans,
        "active": live,
        "amount": sum(l["amount"] for l in loans),
        "monthly": monthly,
        "interest": interest,
        "after_monthly": after,
        "shortest_years": shortest,
        "quote": quote,
        "quote_ok": bool(q_monthly) and abs(monthly - q_monthly) <= 0.5,
    }


def all_plans(profile):
    return [plan_stats(profile, p) for p in (profile or {}).get("plans") or []]


def plan_kind(st):
    live = (st or {}).get("active") or []
    if len(live) > 1:
        return "组合贷"
    kinds = {l["kind"] for l in live}
    if kinds == {"provident"}:
        return "纯公积金"
    return "纯商贷" if kinds == {"commercial"} else "贷款"


def plan_desc(st):
    """「组合贷 100 万（公积金 50 万 / 20 年 + 商贷 50 万 / 30 年）」"""
    live = (st or {}).get("active") or []
    if not live:
        return "—"
    parts = " + ".join("%s %s / %s 年" % (l["label"], fmt_wan(l["amount"]), l["years"])
                       for l in live)
    return "%s %s（%s）" % (plan_kind(st), fmt_wan(st["amount"]), parts)


def find_plan(profile, key=None):
    plans = (profile or {}).get("plans") or []
    if not plans:
        return None
    key = key or (profile or {}).get("default_plan")
    for p in plans:
        if p.get("key") == key:
            return p
    return plans[0]


def afford(profile, prop, plan_key=None):
    """按方案估算一套房的首付/月供（元）。

    首付留空时按「总价 − 可贷总额」算；首付填了但贷款超过可贷总额时按上限截断。
    """
    plan = find_plan(profile, plan_key)
    st = plan_stats(profile, plan) if plan else None
    cap = st["amount"] if st else 0.0
    price = _num((prop or {}).get("price"))
    down = (prop or {}).get("down_payment")
    if down in (None, ""):
        down = max(0.0, price - cap)
    down = max(0.0, min(_num(down), price))
    loan = max(0.0, price - down)
    over = loan > cap + 0.5
    if over and cap:
        loan = cap
        down = max(0.0, price - cap)
    scale = (loan / cap) if cap else 0.0
    monthly = 0.0
    if st:
        for l in st["loans"]:
            monthly += monthly_payment(l["amount"] * scale, l["rate"], l["years"])
    fees = (prop or {}).get("fees") or {}
    fee_total = sum(_num(fees.get(k)) for k in ("tax", "agency", "other"))
    area = _num((prop or {}).get("area_sqm"))
    return {
        "price": price,
        "loan": loan,
        "down": down,
        "down_ratio": (down / price) if price else 0.0,
        "monthly": monthly,
        "fee_total": fee_total,
        "cash": down + fee_total,
        "over_cap": over,
        "unit_price": (price / area) if area else 0.0,
        "plan": st,
    }


# ---------------------------------------------------------------- 展示
def display_name(p):
    parts = [p.get("community") or "", p.get("building") or "", p.get("unit") or ""]
    name = " ".join(x for x in parts if x).strip()
    return name or "未命名房源"


def location(p):
    return "·".join(x for x in ((p or {}).get("district"), (p or {}).get("area_name")) if x)


def fmt_money(v):
    return "{:,.0f}".format(_num(v))


def fmt_wan(v, nd=None):
    w = _num(v) / 10000.0
    if nd is not None:
        return ("{:,.%df}" % nd).format(w) + " 万"
    if abs(w) >= 100:
        s = "{:,.0f}".format(w)
    elif abs(w) >= 10:
        s = "{:,.1f}".format(w).rstrip("0").rstrip(".")
    else:
        s = "{:,.2f}".format(w).rstrip("0").rstrip(".")
    return s + " 万"


def fmt_unit(v):
    v = _num(v)
    return "{:,.0f}".format(v) if v else "—"


def status_counts(props):
    out = {s: 0 for s in STATUSES}
    for p in props or []:
        s = p.get("status") or "关注"
        out[s] = out.get(s, 0) + 1
    return out
