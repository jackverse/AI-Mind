# -*- coding: utf-8 -*-
"""极简 xlsx 读取器（零第三方依赖）。

xlsx 本质是个 zip：workbook.xml 里列工作表，sharedStrings.xml 存共享字符串，
worksheets/sheetN.xml 存单元格。只做「读出表格」这一件事，够用即可。

支持：共享字符串（含富文本 runs）、内联字符串、数字、布尔、公式缓存值、
      稀疏行（按单元格 r 属性还原列位置）、百分比/时长等以文本存的指标。
不支持：合并单元格、样式、图片——导出表用不到。
"""
import re
import zipfile
import xml.etree.ElementTree as ET

MAIN = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
PKG_REL = "{http://schemas.openxmlformats.org/package/2006/relationships}"
DOC_REL = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"

_COL_RE = re.compile(r"^([A-Z]+)")


def _col_index(ref):
    """'B7' -> 1（0 基列号）"""
    if not ref:
        return None
    m = _COL_RE.match(ref)
    if not m:
        return None
    n = 0
    for ch in m.group(1):
        n = n * 26 + (ord(ch) - 64)
    return n - 1


def _text_of(node):
    """拼接 <t> 文本（富文本会拆成多个 <r><t>）。"""
    if node is None:
        return ""
    parts = [t.text or "" for t in node.iter(MAIN + "t")]
    return "".join(parts)


def _shared_strings(z):
    try:
        raw = z.read("xl/sharedStrings.xml")
    except KeyError:
        return []
    root = ET.fromstring(raw)
    return [_text_of(si) for si in root.findall(MAIN + "si")]


def sheet_names(path):
    """列出工作表名（顺序与 Excel 一致）。"""
    with zipfile.ZipFile(path) as z:
        wb = ET.fromstring(z.read("xl/workbook.xml"))
    return [sh.get("name") for sh in wb.iter(MAIN + "sheet")]


def _sheet_paths(path):
    """[(sheet_name, zip 内路径)]"""
    with zipfile.ZipFile(path) as z:
        wb = ET.fromstring(z.read("xl/workbook.xml"))
        rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
    targets = {r.get("Id"): r.get("Target") for r in rels}
    out = []
    for sh in wb.iter(MAIN + "sheet"):
        rid = sh.get(DOC_REL + "id")
        target = (targets.get(rid) or "").lstrip("/")
        if not target:
            continue
        if not target.startswith("xl/"):
            target = "xl/" + target
        out.append((sh.get("name"), target))
    return out


def read_sheet(path, sheet=0):
    """读一张表，返回二维列表（行 × 列）。

    sheet 可以是序号（0 基）或表名。空单元格为 None，数字为 float，
    文本为 str。行尾的空列会被裁掉，中间的空列保留，保证列位置对齐。
    """
    with zipfile.ZipFile(path) as z:
        shared = _shared_strings(z)
        sheets = _sheet_paths(path)
        if not sheets:
            return []
        if isinstance(sheet, int):
            if sheet >= len(sheets):
                return []
            name, target = sheets[sheet]
        else:
            match = [s for s in sheets if s[0] == sheet]
            if not match:
                return []
            name, target = match[0]
        raw = z.read(target)

    root = ET.fromstring(raw)
    data = root.find(MAIN + "sheetData")
    if data is None:
        return []

    rows = []
    for row in data.findall(MAIN + "row"):
        cells = []
        auto = 0
        for c in row.findall(MAIN + "c"):
            idx = _col_index(c.get("r"))
            if idx is None:
                idx = auto
            auto = idx + 1
            while len(cells) < idx:
                cells.append(None)
            cells.append(_cell_value(c, shared))
        while cells and cells[-1] is None:
            cells.pop()
        rows.append(cells)
    while rows and not any(v is not None and v != "" for v in rows[-1]):
        rows.pop()
    return rows


def _cell_value(c, shared):
    t = c.get("t")
    if t == "inlineStr":
        return _text_of(c.find(MAIN + "is")) or None

    v = c.find(MAIN + "v")
    if v is None or v.text is None:
        return None
    text = v.text

    if t == "s":
        try:
            return shared[int(text)]
        except (ValueError, IndexError):
            return None
    if t == "str":
        return text or None
    if t == "b":
        return text == "1"
    if t == "e":            # 错误值 #N/A 之类
        return None

    try:
        f = float(text)
    except ValueError:
        return text
    return int(f) if f.is_integer() else f


# ------------------------------------------------------------------ 取值工具
def to_num(v, default=None):
    """单元格 -> 数字。容忍 '2,874' '28.64%' '-'(空) 等。百分比按 % 折成小数。"""
    if v is None:
        return default
    if isinstance(v, bool):
        return float(v)
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip()
    if not s or s in ("-", "—", "--", "N/A", "/"):
        return default
    s = s.replace(",", "").replace(" ", "")
    pct = s.endswith("%")
    if pct:
        s = s[:-1]
    try:
        f = float(s)
    except ValueError:
        return default
    return f / 100.0 if pct else f


def to_ratio(v, default=None):
    """百分比率 -> 0~1 小数。'8.22%' 与 '0.0822' 都认。"""
    if isinstance(v, str):
        s = v.strip()
        if s.endswith("%"):
            n = to_num(s)
            return n
    n = to_num(v)
    return n if n is not None else default


def to_seconds(v, default=None):
    """'5.50s' / '00:05' / 5.5 -> 秒"""
    if v is None:
        return default
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return float(v)
    s = str(v).strip()
    if not s or s in ("-", "—"):
        return default
    s = s.rstrip("sS秒")
    if ":" in s:
        parts = [to_num(p, 0.0) for p in s.split(":")]
        total = 0.0
        for p in parts:
            total = total * 60 + p
        return total
    return to_num(s, default)


def col_index(headers, *names):
    """按表头文字找列号，找不到返回 None。认「包含」不认必须相等，容忍空格。"""
    norm = [str(h or "").replace(" ", "").strip() for h in headers]
    for want in names:
        w = want.replace(" ", "")
        for i, h in enumerate(norm):
            if h == w:
                return i
        for i, h in enumerate(norm):
            if w and w in h:
                return i
    return None
