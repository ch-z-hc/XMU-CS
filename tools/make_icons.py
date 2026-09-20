#!/usr/bin/env python3
"""Generate the schedule app icon set from one geometric design.

The icon is deliberately dependency-free: it draws a small calendar with
colorful class blocks, matching the color language used by schedule.html.
"""

from __future__ import annotations

import math
import struct
import zlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"
SRC = 512

# Palette from fetch_schedule.py
BLUE_TOP = (10, 49, 91)       # #0a315b
BLUE_BOTTOM = (24, 118, 173)  # #1876ad
BLUE_BRAND = (23, 105, 170)   # #1769aa
BLUE_DARK = (11, 55, 100)     # #0b3764
WHITE = (255, 255, 255)
LINE = (228, 234, 241)        # #e4eaf1
COOL_RED = (223, 90, 84)      # #df5a54
GREEN = (59, 146, 118)        # #3b9276
TEAL = (52, 140, 157)         # #348c9d
ORANGE = (202, 123, 58)       # #ca7b3a
PURPLE = (141, 103, 186)      # #8d67ba
ROSE = (200, 94, 103)         # #c85e67
INDIGO = (101, 117, 185)      # #6575b9

TOP_COLORS = [COOL_RED, BLUE_BRAND, GREEN, PURPLE]
BOTTOM_COLORS = [TEAL, ORANGE, ROSE, INDIGO]


def mix(a, b, t):
    t = min(1.0, max(0.0, t))
    return tuple(a[i] * (1 - t) + b[i] * t for i in range(3))


def blend(base, color, alpha):
    if alpha <= 0:
        return base
    alpha = min(1.0, max(0.0, alpha))
    return tuple(base[i] * (1 - alpha) + color[i] * alpha for i in range(3))


def alpha_from_sdf(sdf):
    # ~1 px feather, enough to look smooth when the source is downscaled.
    return min(1.0, max(0.0, 0.5 - sdf))


def round_rect_sdf(px, py, x, y, w, h, r):
    cx, cy = x + w / 2, y + h / 2
    qx = abs(px - cx) - (w / 2 - r)
    qy = abs(py - cy) - (h / 2 - r)
    outside = math.hypot(max(qx, 0.0), max(qy, 0.0))
    inside = min(max(qx, qy), 0.0)
    return outside + inside - r


def circle_sdf(px, py, cx, cy, r):
    return math.hypot(px - cx, py - cy) - r


def add_alpha(color, sdf, opacity=1.0):
    return alpha_from_sdf(sdf) * opacity


def sample(px, py):
    """Return the RGB color of the 512x512 design at one sample point."""

    # Background: the same diagonal blue gradient as the page hero.
    t = (px + py) / (2 * SRC)
    color = mix(BLUE_TOP, BLUE_BOTTOM, t)

    # Very subtle decorative shapes keep the icon from looking flat.
    color = blend(color, WHITE, add_alpha(WHITE, circle_sdf(px, py, 454, 70, 128), 0.045))
    color = blend(color, WHITE, add_alpha(WHITE, circle_sdf(px, py, 52, 474, 112), 0.035))

    # Soft shadow behind the calendar card.
    shadow_alpha = add_alpha(BLUE_DARK, round_rect_sdf(px, py, 110, 120, 304, 304, 62), 0.14)
    color = blend(color, BLUE_DARK, shadow_alpha)

    # Calendar tabs.
    for tx in (144, 310):
        tab_alpha = add_alpha(BLUE_DARK, round_rect_sdf(px, py, tx, 72, 58, 74, 29))
        color = blend(color, BLUE_DARK, tab_alpha)

    # White calendar card.
    card_sdf = round_rect_sdf(px, py, 112, 112, 288, 288, 58)
    card_alpha = alpha_from_sdf(card_sdf)
    color = blend(color, WHITE, card_alpha)

    if card_alpha > 0:
        # Blue header, clipped by the card.
        header_alpha = card_alpha * add_alpha(BLUE_BRAND, round_rect_sdf(px, py, 112, 112, 288, 84, 58))
        color = blend(color, BLUE_BRAND, header_alpha)

        # Tiny dots on the header, like dates on a paper calendar.
        for i in range(6):
            dot_x = 146 + i * 42
            dot_alpha = card_alpha * add_alpha(WHITE, circle_sdf(px, py, dot_x, 154, 7), 0.42)
            color = blend(color, WHITE, dot_alpha)

        # Grid rows.
        for line_y in (235, 302, 369):
            line_alpha = card_alpha * add_alpha(LINE, round_rect_sdf(px, py, 138, line_y, 236, 4, 0))
            color = blend(color, LINE, line_alpha)

        # Class blocks: top and bottom rows mirror the schedule view colors.
        for row_y, colors in ((238, TOP_COLORS), (310, BOTTOM_COLORS)):
            for i, block_color in enumerate(colors):
                bx = 140 + i * 60
                block_alpha = card_alpha * add_alpha(block_color, round_rect_sdf(px, py, bx, row_y, 48, 58, 17))
                color = blend(color, block_color, block_alpha)

    return color


def render(size, supersample=3):
    """Render the icon at `size` px with simple box-filter antialiasing."""
    rows = []
    step = 1.0 / supersample
    for py in range(size):
        row = bytearray()
        for px in range(size):
            acc = [0.0, 0.0, 0.0]
            for sy in range(supersample):
                for sx in range(supersample):
                    x = (px + (sx + 0.5) * step) * SRC / size
                    y = (py + (sy + 0.5) * step) * SRC / size
                    rgb = sample(x, y)
                    for i in range(3):
                        acc[i] += rgb[i]
            n = supersample * supersample
            row.extend(int(round(v / n)) for v in acc)
        rows.append(bytes(row))
    return rows


def write_png(path: Path, size: int):
    rows = render(size)

    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + kind
            + data
            + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
        )

    raw = b"".join(b"\x00" + row for row in rows)
    png = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )
    path.write_bytes(png)


def write_svg(path: Path):
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512">
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="#0a315b"/>
      <stop offset="1" stop-color="#1876ad"/>
    </linearGradient>
    <clipPath id="card"><rect x="112" y="112" width="288" height="288" rx="58"/></clipPath>
  </defs>
  <rect width="512" height="512" rx="112" fill="url(#bg)"/>
  <circle cx="454" cy="70" r="128" fill="#fff" opacity=".045"/>
  <circle cx="52" cy="474" r="112" fill="#fff" opacity=".035"/>
  <rect x="110" y="120" width="304" height="304" rx="62" fill="#0b3764" opacity=".14"/>
  <rect x="144" y="72" width="58" height="74" rx="29" fill="#0b3764"/>
  <rect x="310" y="72" width="58" height="74" rx="29" fill="#0b3764"/>
  <rect x="112" y="112" width="288" height="288" rx="58" fill="#fff"/>
  <g clip-path="url(#card)">
    <rect x="112" y="112" width="288" height="84" fill="#1769aa"/>
    <g fill="#fff" opacity=".42">
      <circle cx="146" cy="154" r="7"/><circle cx="188" cy="154" r="7"/>
      <circle cx="230" cy="154" r="7"/><circle cx="272" cy="154" r="7"/>
      <circle cx="314" cy="154" r="7"/><circle cx="356" cy="154" r="7"/>
    </g>
    <g stroke="#e4eaf1" stroke-width="4">
      <line x1="138" y1="235" x2="374" y2="235"/>
      <line x1="138" y1="302" x2="374" y2="302"/>
      <line x1="138" y1="369" x2="374" y2="369"/>
    </g>
    <g>
      <rect x="140" y="238" width="48" height="58" rx="17" fill="#df5a54"/>
      <rect x="200" y="238" width="48" height="58" rx="17" fill="#1769aa"/>
      <rect x="260" y="238" width="48" height="58" rx="17" fill="#3b9276"/>
      <rect x="320" y="238" width="48" height="58" rx="17" fill="#8d67ba"/>
      <rect x="140" y="310" width="48" height="58" rx="17" fill="#348c9d"/>
      <rect x="200" y="310" width="48" height="58" rx="17" fill="#ca7b3a"/>
      <rect x="260" y="310" width="48" height="58" rx="17" fill="#c85e67"/>
      <rect x="320" y="310" width="48" height="58" rx="17" fill="#6575b9"/>
    </g>
  </g>
</svg>"""
    path.write_text(svg, encoding="utf-8")


def main():
    ASSETS.mkdir(parents=True, exist_ok=True)
    write_svg(ASSETS / "icon-source.svg")
    for name, size in (
        ("icon-512.png", 512),
        ("icon-192.png", 192),
        ("apple-touch-icon.png", 180),
        ("favicon.png", 64),
    ):
        write_png(ASSETS / name, size)
        print(f"wrote {ASSETS / name}")


if __name__ == "__main__":
    main()
