# -*- coding: utf-8 -*-
"""极简 Markdown → tkinter.Text 渲染（标题/列表/表格/代码块/引用/加粗/行内码/链接）。"""
import re
import webbrowser

INLINE_RE = re.compile(r"(\*\*.+?\*\*|`[^`]+`|\[[^\]]+\]\([^)]+\))")


def _dw(s):
    """显示宽度：CJK 算 2 格。"""
    return sum(2 if ord(c) > 0x2E80 else 1 for c in s)


def _pad(s, width):
    return s + " " * max(0, width - _dw(s))


def _split_row(line):
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|"):
        line = line[:-1]
    return [c.strip() for c in line.split("|")]


def _is_sep_row(cells):
    return bool(cells) and all(re.fullmatch(r":?-{2,}:?", c) for c in cells)


def render(text, markdown, fonts, on_link=None, mask=None):
    """把 markdown 渲染进 Text（调用前需 text 处于 normal 状态）。

    mask: 可选的脱敏函数（隐私模式）——只处理可见文字，代码块与链接 URL 原样保留。
    """
    text.configure(state="normal")
    text.delete("1.0", "end")

    def m(s):
        return mask(s) if mask else s

    def ins(s, *tags):
        text.insert("end", m(s), tags)

    def inline(s, *tags):
        _inline(text, s, tags[0] if tags else "p", on_link, mask)

    lines = markdown.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]

        # 代码块
        if line.strip().startswith("```"):
            i += 1
            buf = []
            while i < n and not lines[i].strip().startswith("```"):
                buf.append(lines[i])
                i += 1
            i += 1
            text.insert("end", "\n".join(buf) + "\n", "code")   # 代码块不脱敏
            continue

        # 表格
        if line.lstrip().startswith("|") and line.count("|") >= 2:
            rows = []
            while i < n and lines[i].lstrip().startswith("|"):
                cells = _split_row(lines[i])
                if not _is_sep_row(cells):
                    rows.append(cells)
                i += 1
            if rows:
                ncol = max(len(r) for r in rows)
                widths = [max(_dw(m(r[c])) if c < len(r) else 0 for r in rows)
                          for c in range(ncol)]
                for ri, r in enumerate(rows):
                    cells = [(r[c] if c < len(r) else "") for c in range(ncol)]
                    txt = "  ".join(_pad(c2, widths[ci]) for ci, c2 in enumerate(cells))
                    ins(txt.rstrip() + "\n", "th" if ri == 0 else "td")
                ins("\n")
            continue

        s = line.rstrip()

        # 标题
        mo = re.match(r"^(#{1,6})\s+(.*)$", s)
        if mo:
            lvl = min(len(mo.group(1)), 4)
            ins(mo.group(2).strip() + "\n", f"h{lvl}")
            i += 1
            continue

        # 分隔线
        if re.fullmatch(r"\s*([-*_])\1{2,}\s*", s):
            ins("─" * 46 + "\n", "hr")
            i += 1
            continue

        # 引用
        if s.lstrip().startswith(">"):
            body = s.lstrip()[1:].strip()
            inline("│ " + body + "\n", "quote")
            i += 1
            continue

        # 列表
        mo = re.match(r"^(\s*)([-*+]|\d+[.)])\s+(.*)$", s)
        if mo:
            indent = " " * min(len(mo.group(1)) // 2, 3) * 2
            marker = mo.group(2)
            bullet = "•" if not marker[0].isdigit() else marker if marker.endswith(".") else marker
            inline(f"{indent}{bullet} {mo.group(3)}\n", "li")
            i += 1
            continue

        # 空行
        if not s.strip():
            ins("\n")
            i += 1
            continue

        # 普通段落
        inline(s + "\n", "p")
        i += 1

    text.configure(state="disabled")


def _inline(text, s, tag, on_link, mask=None):
    def m(x):
        return mask(x) if mask else x

    pos = 0
    for mo in INLINE_RE.finditer(s):
        if mo.start() > pos:
            text.insert("end", m(s[pos:mo.start()]), tag)
        tok = mo.group(0)
        if tok.startswith("**"):
            text.insert("end", m(tok[2:-2]), (tag, "bold"))
        elif tok.startswith("`"):
            text.insert("end", m(tok[1:-1]), (tag, "code_inline"))
        else:
            label, url = re.match(r"\[([^\]]+)\]\(([^)]+)\)", tok).groups()
            tagname = f"link{abs(hash(url)) % 100000}"
            text.insert("end", m(label), (tag, "link", tagname))
            if on_link:
                on_link(text, tagname, url)
            else:
                text.tag_bind(tagname, "<Button-1>",
                              lambda _e, u=url: webbrowser.open(u))
        pos = mo.end()
    if pos < len(s):
        text.insert("end", m(s[pos:]), tag)
