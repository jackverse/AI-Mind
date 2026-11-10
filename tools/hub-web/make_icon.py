# -*- coding: utf-8 -*-
"""生成 iOS 主屏幕图标（apple-touch-icon.png）与 PWA 用 PNG 图标。

iOS 不认 SVG 的 apple-touch-icon，必须给 180×180 的 PNG；顺手出 192/512 给安卓加桌面用。
图案照 icon.svg：圆角方块渐变底 + 白菱形 + 圆点 + 竖线。

用法：python tools/hub-web/make_icon.py
"""
from pathlib import Path

from PIL import Image, ImageDraw

WEB = Path(__file__).resolve().parent / "web"
TOP = (0x2a, 0x3d, 0x66)
BOTTOM = (0x3d, 0x6e, 0xe0)


def _bg(size):
    img = Image.new("RGB", (size, size))
    px = img.load()
    for y in range(size):
        t = y / max(size - 1, 1)
        color = tuple(int(TOP[i] + (BOTTOM[i] - TOP[i]) * t) for i in range(3))
        for x in range(size):
            px[x, y] = color
    return img


def _mask(size, radius_ratio=0.2266):
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        (0, 0, size - 1, size - 1), radius=int(size * radius_ratio), fill=255)
    return mask


def draw(size=512):
    img = _bg(size).convert("RGBA")
    draw_ = ImageDraw.Draw(img)
    s = size / 512.0

    def pt(x, y):
        return (x * s, y * s)

    # 白菱形描边
    draw_.polygon([pt(256, 96), pt(376, 216), pt(256, 336), pt(136, 216)],
                  outline=(255, 255, 255, 255), width=max(int(26 * s), 2))
    # 圆点
    cx, cy, r = pt(256, 216)[0], pt(256, 216)[1], 34 * s
    draw_.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(255, 255, 255, 255))
    # 竖线
    x0, y0 = pt(256, 366)
    x1, y1 = pt(256, 416)
    draw_.line((x0, y0, x1, y1), fill=(255, 255, 255, 255), width=max(int(26 * s), 2))

    img.putalpha(_mask(size))
    return img


def main():
    out = {
        "apple-touch-icon.png": 180,
        "icon-192.png": 192,
        "icon-512.png": 512,
    }
    for name, size in out.items():
        path = WEB / name
        draw(size).save(path, "PNG")
        print("写入", path.name, size)
    # 掩膜用的圆角透明度在 iOS 上会被再裁一次，方形底更稳：另存一版不透明的
    flat = draw(180).convert("RGB")
    flat.save(WEB / "apple-touch-icon.png", "PNG")
    print("apple-touch-icon.png 保持不透明（iOS 自己会圆角）")


if __name__ == "__main__":
    main()
