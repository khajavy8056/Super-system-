#!/usr/bin/env python3
"""Render the Supermarket System brand mark (§49) into every raster size.

One geometry, one script, every output:

    frontend/icons/logo.svg          hand-authored vector (see make_logo_svg)
    frontend/icons/icon-192.png      PWA / manifest
    frontend/icons/icon-512.png      PWA / manifest (install splash)
    frontend/icons/logo-512.png      full-colour mark on transparent ground
    installer/windows/icon.ico       multi-resolution Windows application icon

Why Pillow instead of an SVG rasteriser: the build sandbox has no libcairo and
no rsvg-convert, and shipping a brand asset that can only be rebuilt on one
machine is how logos drift out of sync with their own source. Pillow is
already a dev dependency, so `python scripts/make_logo.py` reproduces every
file here on any platform.

Usage:
    python scripts/make_logo.py            # write all assets
    python scripts/make_logo.py --check    # verify the committed files match
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
ICONS = ROOT / "frontend" / "icons"
INSTALLER = ROOT / "installer" / "windows"

# --- palette ------------------------------------------------------------------
# Commercial and legible at 16 px: a single hue ramp, no hairlines, no detail
# that disappears when Windows scales the icon down for the taskbar.
TOP = (29, 78, 216, 255)       # #1D4ED8  blue-700
BOTTOM = (14, 165, 233, 255)   # #0EA5E9  sky-500
INK = (255, 255, 255, 255)
SHADOW = (15, 23, 42, 255)     # #0F172A  slate-900


def _rounded(draw: ImageDraw.ImageDraw, box, radius, fill):
    draw.rounded_rectangle(box, radius=radius, fill=fill)


def draw_mark(size: int) -> Image.Image:
    """Draw the brand mark at ``size`` px on a transparent canvas.

    Composition: a shopping trolley whose basket holds an ascending bar chart —
    the trolley says "retail counter", the bars say "this is the system that
    reports on it". Every coordinate is a fraction of ``size`` so the mark is
    identical at 16 px (taskbar) and 512 px (splash).

    Rendering strategy: draw everything on an opaque supersampled canvas, then
    punch the rounded-tile shape out with a single ``putalpha`` at the end.
    (An earlier draft used ``paste(..., mask)`` per layer, which silently
    clobbered the gradient — paste with a mask ignores the source alpha.)
    """
    s = float(size)
    ss = 4  # supersample factor for clean anti-aliased corners
    u = s * ss
    img = Image.new("RGBA", (int(u), int(u)), TOP)
    d = ImageDraw.Draw(img)

    # --- background tile: vertical gradient -----------------------------------
    for y in range(int(u)):
        t = y / max(1.0, u - 1)
        colour = tuple(int(TOP[i] + (BOTTOM[i] - TOP[i]) * t) for i in range(3)) + (255,)
        d.line([(0, y), (u, y)], fill=colour)

    # --- subtle top sheen so the tile reads as a physical app icon ------------
    hl = Image.new("RGBA", (int(u), int(u)), (0, 0, 0, 0))
    ImageDraw.Draw(hl).rectangle([0, 0, u, u * 0.5], fill=(255, 255, 255, 26))
    img = Image.alpha_composite(img, hl)
    d = ImageDraw.Draw(img)

    # --- trolley frame (one continuous thick stroke) --------------------------
    stroke = u * 0.072
    d.line([(u * 0.155, u * 0.265), (u * 0.245, u * 0.265)], fill=INK, width=int(stroke))
    d.line([(u * 0.245, u * 0.265), (u * 0.30, u * 0.40)], fill=INK, width=int(stroke))

    # --- basket outline (open trapezoid, four sides) --------------------------
    basket = [(u * 0.285, u * 0.40), (u * 0.845, u * 0.40),
              (u * 0.775, u * 0.665), (u * 0.345, u * 0.665)]
    for a, b in ((0, 1), (1, 2), (2, 3), (3, 0)):
        d.line([basket[a], basket[b]], fill=INK, width=int(stroke))

    # --- ascending bars inside the basket (the "ERP" half of the mark) --------
    base_y = u * 0.615
    bar_w = u * 0.105
    gap = u * 0.055
    heights = (u * 0.075, u * 0.125, u * 0.175)
    left = u * 0.40
    for i, h in enumerate(heights):
        x0 = left + i * (bar_w + gap)
        d.rounded_rectangle([x0, base_y - h, x0 + bar_w, base_y],
                            radius=bar_w * 0.3, fill=INK)

    # --- wheels ----------------------------------------------------------------
    wheel_r = u * 0.048
    for cx in (u * 0.40, u * 0.715):
        d.ellipse([cx - wheel_r, u * 0.735 - wheel_r, cx + wheel_r, u * 0.735 + wheel_r],
                  fill=INK)

    # --- punch the rounded shape out ------------------------------------------
    mask = Image.new("L", (int(u), int(u)), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, u - 1, u - 1],
                                           radius=int(u * 0.235), fill=255)
    img.putalpha(mask)

    return img.resize((size, size), Image.LANCZOS)


def write_png(path: Path, size: int, *, pad: float = 0.0) -> bytes:
    """Render ``size`` px, optionally inset by ``pad`` fraction for PWA masks."""
    mark = draw_mark(size)
    if pad:
        inner = int(size * (1 - 2 * pad))
        mark = mark.resize((inner, inner), Image.LANCZOS)
        canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        off = (size - inner) // 2
        canvas.paste(mark, (off, off), mark)
        mark = canvas
    path.parent.mkdir(parents=True, exist_ok=True)
    mark.save(path, "PNG", optimize=True)
    return path.read_bytes()


def write_ico(path: Path, sizes=(16, 24, 32, 48, 64, 128, 256)) -> bytes:
    """Multi-resolution .ico — Windows picks the size for the context.

    A single-resolution .ico is what makes a taskbar icon look smeared, so
    every size the shell actually asks for is embedded. Pillow derives each
    frame by downscaling the image you hand it, so the largest size goes in
    and ``sizes`` lists the rest — passing per-frame images produces a file
    with only the first frame in it.
    """
    biggest = max(sizes)
    path.parent.mkdir(parents=True, exist_ok=True)
    draw_mark(biggest).save(path, "ICO", sizes=[(sz, sz) for sz in sizes])
    return path.read_bytes()


LOGO_SVG = """<?xml version="1.0" encoding="UTF-8"?>
<!-- Supermarket System — brand mark (§49).
     Hand-authored so the web panel gets a vector that stays crisp on any DPI
     and prints correctly on a receipt header. Rendered raster twins are
     produced by scripts/make_logo.py from the same geometry. -->
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 128 128" width="128" height="128"
     role="img" aria-label="Supermarket System">
  <defs>
    <linearGradient id="tile" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#1D4ED8"/>
      <stop offset="1" stop-color="#0EA5E9"/>
    </linearGradient>
  </defs>
  <rect x="0" y="0" width="128" height="128" rx="30" fill="url(#tile)"/>
  <rect x="0" y="0" width="128" height="64" rx="30" fill="#FFFFFF" opacity="0.10"/>
  <g fill="none" stroke="#FFFFFF" stroke-width="9.2" stroke-linecap="round" stroke-linejoin="round">
    <path d="M19.8 33.9h11.5l7 17.3"/>
    <path d="M36.5 51.2h71.7l-9 33.9H44.2z"/>
  </g>
  <g fill="#FFFFFF">
    <rect x="47" y="66.6" width="12" height="10.8" rx="3.6"/>
    <rect x="63.5" y="60.2" width="12" height="17.2" rx="3.6"/>
    <rect x="80" y="53.8" width="12" height="23.6" rx="3.6"/>
    <circle cx="51.2" cy="94.1" r="6.1"/>
    <circle cx="91.5" cy="94.1" r="6.1"/>
  </g>
</svg>
"""


def write_svg(path: Path) -> bytes:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(LOGO_SVG.lstrip(), encoding="utf-8")
    return path.read_bytes()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true",
                    help="fail if the committed assets differ from a fresh render")
    args = ap.parse_args()

    targets = [
        (ICONS / "icon-192.png", lambda p: write_png(p, 192)),
        (ICONS / "icon-512.png", lambda p: write_png(p, 512)),
        (ICONS / "logo-512.png", lambda p: write_png(p, 512)),
        (INSTALLER / "icon.ico", write_ico),
        (ICONS / "logo.svg", write_svg),
    ]

    if not args.check:
        for path, render in targets:
            data = render(path)
            print(f"wrote {path.relative_to(ROOT)}  ({len(data)} bytes)")
        return 0

    bad = []
    for path, render in targets:
        fresh = render(path.with_suffix(path.suffix + ".fresh"))
        current = path.read_bytes() if path.exists() else None
        path.with_suffix(path.suffix + ".fresh").unlink(missing_ok=True)
        # PNG/ICO encoders are deterministic for identical input, so a byte
        # comparison is a real drift check rather than a fuzzy one.
        if current != fresh:
            bad.append(path.relative_to(ROOT))
    if bad:
        print("out of date:", ", ".join(str(b) for b in bad))
        return 1
    print("all brand assets up to date")
    return 0


if __name__ == "__main__":
    sys.exit(main())
