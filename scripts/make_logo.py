#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""RASA SYSTEM (رسا سیستم) — brand identity generator.

One geometry, one script, every output the product ships:

    frontend/icons/logo.svg              tile mark (vector, panel/login/PWA)
    frontend/icons/mark.svg              standalone mark on transparent ground
    frontend/icons/mark-mono.svg         monochrome mark (print, one-colour use)
    frontend/icons/logo-rtl.svg          full lockup — Persian wordmark
    frontend/icons/logo-ltr.svg          full lockup — Latin wordmark
    frontend/icons/logo-dark.svg         full lockup on dark ground
    frontend/icons/icon-192.png          PWA / manifest
    frontend/icons/icon-512.png          PWA / manifest
    frontend/icons/icon-maskable-512.png PWA (Android mask safe-zone)
    frontend/icons/logo-512.png          mark, transparent ground
    installer/windows/icon.ico           Windows application icon (multi-size)
    mobile-android/.../mipmap-*/ic_launcher.png   Android launcher (5 densities)
    docs/brand/*.svg|png                 marketing / print lockups

Why the mark looks like this (identity rules, see docs/BRAND.md):
  • three ascending bars on a solid **counter/shelf line** — retail + growth;
  • a gold **node** floating over the tallest bar — data and intelligence;
  • a soft rounded **tile** — a serious business application, not a toy.
It deliberately avoids the shopping-cart / basket / barcode clichés so the mark
can stand alone (app icon, badge, receipt header) without the wordmark.

Rebuild everything with:
    backend/.venv/bin/python scripts/make_logo.py
    backend/.venv/bin/python scripts/make_logo.py --check   # digest check (CI)

Rasterisation is Pillow, not an SVG engine: the sandbox has no libcairo and
shipping brand assets that only rebuild on one machine is how a logo drifts
away from its own source. Persian wordmarks are shaped with arabic_reshaper +
python-bidi and rendered from the repo's own Vazirmatn (SIL OFL) — converted
from the shipped woff2 on the fly, so no font is downloaded.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
ICONS = ROOT / "frontend" / "icons"
ANDROID_RES = ROOT / "mobile-android" / "app" / "src" / "main" / "res"
INSTALLER = ROOT / "installer" / "windows"
BRAND = ROOT / "docs" / "brand"
FONTS = ROOT / "frontend" / "fonts"

# --- palette -------------------------------------------------------------------
# Cobalt → violet is the product accent (panel, Android, POS tiles). Gold is the
# one warm accent used only for the intelligence node — it survives a 16 px
# downscale as a single readable dot, which is exactly its job.
TOP = (37, 99, 235, 255)        # #2563EB  cobalt  (--primary)
BOTTOM = (124, 77, 255, 255)    # #7C4DFF  violet  (--accent)
GOLD = (255, 198, 90, 255)      # #FFC65A  (--gold)
INK = (255, 255, 255, 255)
INK_SOFT = (232, 238, 255, 255)
DARK_BG = (8, 20, 46, 255)      # #08142E  panel dark surface
LIGHT_BG = (255, 255, 255, 255)

BRAND_FA = "رسا سیستم"
BRAND_FULL_FA = "مدیریت سوپرمارکت رسا سیستم"
BRAND_LTR = "RASA SYSTEM"
TAGLINE_FA = "مدیریت هوشمند سوپرمارکت"
TAGLINE_LTR = "SUPERMARKET INTELLIGENCE"

# --- mark geometry (normalised 0..1 of the tile) --------------------------------
#: (x, y, w, h) — bars ascend left→right; the counter is the solid ground under
#: them (retail shelf), the node sits on the tallest bar (intelligence).
BARS = ((0.255, 0.545, 0.118, 0.230),
        (0.441, 0.432, 0.118, 0.343),
        (0.627, 0.305, 0.118, 0.470))
COUNTER = (0.205, 0.786, 0.590, 0.075)
NODE = (0.697, 0.331, 0.092)          # centre-x, centre-y, diameter — sits on the tallest bar (live data point)


def _rounded(draw: ImageDraw.ImageDraw, box, radius, fill):
    draw.rounded_rectangle(box, radius=radius, fill=fill)


def _tile_gradient(size: int) -> Image.Image:
    img = Image.new("RGBA", (1, size))
    for y in range(size):
        t = y / max(1, size - 1)
        img.putpixel((0, y), tuple(round(TOP[i] + (BOTTOM[i] - TOP[i]) * t) for i in range(4)))
    return img.resize((size, size), Image.BILINEAR)


def draw_mark(size: int, *, radius_ratio: float = 0.227, ground: str = "tile",
              bar_color=INK, node_color=GOLD, inset: float = 0.0) -> Image.Image:
    """The RASA mark at ``size`` px.

    ground: ``tile`` (gradient rounded square), ``none`` (transparent),
            ``maskable`` (gradient filling the square edge-to-edge for Android
            adaptive icons), ``dark``/``light`` (flat grounds for lockups).
    """
    ss = 4                                            # supersample, then downsample
    S = size * ss
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    pad = int(S * inset)
    box = (pad, pad, S - 1 - pad, S - 1 - pad)
    r = int((box[2] - box[0]) * radius_ratio)
    if ground == "tile":
        grad = _tile_gradient(box[2] - box[0])
        mask = Image.new("L", (box[2] - box[0], box[3] - box[1]), 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, mask.width - 1, mask.height - 1), radius=r, fill=255)
        img.paste(grad, (box[0], box[1]), mask)
        glow = Image.new("RGBA", (S, S), (0, 0, 0, 0))
        ImageDraw.Draw(glow).ellipse((-S * 0.25, -S * 0.45, S * 0.75, S * 0.35), fill=(255, 255, 255, 34))
        tile_mask = Image.new("L", (S, S), 0)
        tile_mask.paste(mask, (box[0], box[1]))
        img = Image.alpha_composite(img, Image.composite(glow, Image.new("RGBA", (S, S), (0, 0, 0, 0)), tile_mask))
    elif ground == "maskable":
        img.paste(_tile_gradient(S), (0, 0))
    elif ground in ("dark", "light"):
        flat = Image.new("RGBA", (S, S), DARK_BG if ground == "dark" else LIGHT_BG)
        mask = Image.new("L", (S, S), 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, S - 1, S - 1), radius=r, fill=255)
        img.paste(flat, (0, 0), mask)
    d = ImageDraw.Draw(img)
    m = (box[2] - box[0])                             # mark spans the tile, minus its own padding
    origin_x, origin_y = box[0], box[1]
    scale = m * (1.0 - 2 * 0.0)
    for bx, by, bw, bh in BARS:
        x0, y0 = origin_x + bx * m, origin_y + by * m
        x1, y1 = x0 + bw * m, y0 + bh * m
        _rounded(d, (x0, y0, x1, y1), radius=(x1 - x0) / 2 * 0.92, fill=bar_color)
    cx, cy, cw, ch = COUNTER
    x0, y0 = origin_x + cx * m, origin_y + cy * m
    _rounded(d, (x0, y0, x0 + cw * m, y0 + ch * m), radius=(ch * m) / 2 * 0.96, fill=bar_color)
    nx, ny, nd = NODE
    rr = nd * m / 2
    ncx, ncy = origin_x + nx * m, origin_y + ny * m
    d.ellipse((ncx - rr, ncy - rr, ncx + rr, ncy + rr), fill=node_color)
    return img.resize((size, size), Image.LANCZOS)


def _svg_shapes(scale: float = 1.0, dx: float = 0.0, dy: float = 0.0, bar="#fff", node="#FFC65A") -> str:
    """SVG fragment for the mark, computed from the same normalised geometry."""
    out = []
    for bx, by, bw, bh in BARS:
        x, y, w, h = (bx + dx) * scale, (by + dy) * scale, bw * scale, bh * scale
        out.append(f'<rect x="{x:.4f}" y="{y:.4f}" width="{w:.4f}" height="{h:.4f}" rx="{w / 2 * 0.92:.4f}" fill="{bar}"/>')
    cx, cy, cw, ch = COUNTER
    x, y, w, h = (cx + dx) * scale, (cy + dy) * scale, cw * scale, ch * scale
    out.append(f'<rect x="{x:.4f}" y="{y:.4f}" width="{w:.4f}" height="{h:.4f}" rx="{h / 2 * 0.96:.4f}" fill="{bar}"/>')
    nx, ny, nd = NODE
    out.append(f'<circle cx="{(nx + dx) * scale:.4f}" cy="{(ny + dy) * scale:.4f}" r="{nd * scale / 2:.4f}" fill="{node}"/>')
    return "\n    ".join(out)


_TILE_DEFS = f'''<defs>
    <linearGradient id="rasaTile" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#2563EB"/>
      <stop offset="1" stop-color="#7C4DFF"/>
    </linearGradient>
  </defs>'''


def svg_mark(size: int = 256, *, tile: bool = True, radius_ratio: float = 0.227,
             rounded_rect: bool = True, label: str = "RASA SYSTEM") -> str:
    r = size * radius_ratio
    tile_el = (f'<rect width="{size}" height="{size}" rx="{r:.2f}" fill="url(#rasaTile)"/>'
               if tile else "")
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<!-- RASA SYSTEM (رسا سیستم) — brand mark. Generated by scripts/make_logo.py;
     edit the geometry there, not here, or the raster assets drift out of sync. -->
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {size} {size}" width="{size}" height="{size}"
     role="img" aria-label="{label}">
  {_TILE_DEFS if tile else ""}
  {tile_el}
  <g transform="translate({size * 0.135:.4f} {size * 0.135:.4f}) scale({size * 0.73 / size:.6f})">
    {_svg_shapes(scale=size)}
  </g>
</svg>
'''


def svg_lockup(*, dark: bool = False, latin: bool = False) -> str:
    """Full lockup: mark + wordmark + tagline, laid out for its reading direction.

    Latin lockups put the mark on the LEFT and read outward to the right; the
    Persian lockup is mirrored (mark on the right, text right-aligned) so the
    eye enters the way Persian is read. One geometry either way.
    """
    h = 300
    mark = 208
    gap = 46
    text_block = 640 if not latin else 560
    W = mark + gap + text_block
    ink = "#F5F6FF" if dark else "#101C3C"
    muted = "#ADB9DC" if dark else "#546489"
    title = BRAND_LTR if latin else BRAND_FA
    sub = TAGLINE_LTR if latin else TAGLINE_FA
    full = "RASA SYSTEM — supermarket management" if latin else BRAND_FULL_FA
    mark_x = 0 if latin else W - mark
    text_x = mark + gap if latin else W - mark - gap
    anchor = "start" if latin else "end"
    letter = 0 if latin else 1.5
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<!-- RASA SYSTEM (رسا سیستم) — full lockup, {"dark ground" if dark else "light ground"}, {"Latin" if latin else "Persian"}.
     Generated by scripts/make_logo.py — edit mark geometry there, not here. -->
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {h}" width="{W}" height="{h}"
     role="img" aria-label="رسا سیستم — RASA SYSTEM">
  {_TILE_DEFS}
  <g>
    <rect x="{mark_x}" y="{(h - mark) / 2:.0f}" width="{mark}" height="{mark}" rx="{mark * 0.227:.2f}" fill="url(#rasaTile)"/>
    <g transform="translate({mark_x + mark * 0.135:.2f} {(h - mark) / 2 + mark * 0.135:.2f}) scale({mark * 0.73 / mark:.4f})">
      {_svg_shapes(scale=mark)}
    </g>
  </g>
  <g font-family="Vazirmatn, Tahoma, 'Segoe UI', sans-serif" text-anchor="{anchor}" direction="{"ltr" if latin else "rtl"}" xml:lang="{"en" if latin else "fa"}">
    <text x="{text_x}" y="{h / 2 - 24}" font-size="64" font-weight="700" fill="{ink}" letter-spacing="{letter}">{title}</text>
    <text x="{text_x}" y="{h / 2 + 20}" font-size="26" font-weight="600" fill="{muted}" letter-spacing="{0 if latin else 1.2}">{sub}</text>
    <text x="{text_x}" y="{h / 2 + 56}" font-size="22" fill="{muted}" opacity=".8">{full}</text>
  </g>
</svg>
'''


# --- Persian/Latin raster text (for PNG lockups) --------------------------------
_font_cache: dict[tuple[str, int], ImageFont.FreeTypeFont] = {}


def _vazirmatn(weight: str = "Bold") -> Path:
    """Vazirmatn as a TTF, converted from the shipped woff2 (no downloads)."""
    ttf = Path("/tmp") / f"Vazirmatn-{weight}.ttf"
    if ttf.exists():
        return ttf
    from fontTools.ttLib import TTFont
    f = TTFont(str(FONTS / f"Vazirmatn-{weight}.woff2"))
    f.flavor = None
    f.save(str(ttf))
    return ttf


def _font(px: int, weight: str = "Bold") -> ImageFont.FreeTypeFont:
    key = (weight, px)
    if key not in _font_cache:
        _font_cache[key] = ImageFont.truetype(str(_vazirmatn(weight)), px)
    return _font_cache[key]


def _shape_fa(text: str) -> str:
    """Persian text ready for a non-shaping renderer (Pillow)."""
    import arabic_reshaper
    from bidi.algorithm import get_display
    return get_display(arabic_reshaper.reshape(text))


def draw_lockup(width: int = 1600, *, dark: bool = False, latin: bool = False) -> Image.Image:
    """Raster lockup — same rules as the vector one (mirrored for Persian)."""
    mark = max(96, int(width * 0.13))
    gap = int(mark * 0.22)
    f_title = _font(int(mark * 0.44), "Bold")
    f_sub = _font(int(mark * 0.175), "Regular")
    f_full = _font(int(mark * 0.145), "Regular")
    title = BRAND_LTR if latin else _shape_fa(BRAND_FA)
    sub = TAGLINE_LTR if latin else _shape_fa(TAGLINE_FA)
    full = "Supermarket management platform" if latin else _shape_fa(BRAND_FULL_FA)

    probe = ImageDraw.Draw(Image.new("RGBA", (8, 8)))
    tw = max(probe.textlength(title, font=f_title), probe.textlength(sub, font=f_sub),
             probe.textlength(full, font=f_full))
    text_block = int(tw) + 8
    h = int(mark * 1.32)
    W = mark + gap + text_block + int(mark * 0.18)
    img = Image.new("RGBA", (W, h), (0, 0, 0, 0))
    img.paste(Image.new("RGBA", (W, h), DARK_BG if dark else LIGHT_BG), (0, 0))
    img.alpha_composite(draw_mark(mark, ground="tile"), ((W - mark) // 2 if latin else W - mark - int(mark * 0.09), (h - mark) // 2))
    ink = (245, 246, 255, 255) if dark else (16, 28, 60, 255)
    muted = (173, 185, 220, 255) if dark else (84, 100, 137, 255)
    x_left = int(mark * 0.09) + mark + gap
    d = ImageDraw.Draw(img)

    def put(text, font, fill, dy):
        w = d.textlength(text, font=font)
        x = x_left if latin else W - x_left - w
        d.text((x, h / 2 + dy), text, font=font, fill=fill)
    put(title, f_title, ink, -mark * 0.46)
    put(sub, f_sub, muted, -mark * 0.02)
    put(full, f_full, muted, mark * 0.24)
    return img


# --- writers --------------------------------------------------------------------
def _png_bytes(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def _digest(img: Image.Image) -> str:
    """Perceptual digest — stable across Pillow/encoder versions (byte hashes are not)."""
    small = img.convert("RGBA").resize((32, 32), Image.LANCZOS)
    return hashlib.sha256(small.tobytes()).hexdigest()[:16]


def build_targets() -> dict[Path, callable]:
    targets: dict[Path, callable] = {}

    def add(path: Path, fn):
        targets[path] = fn

    # --- vectors
    add(ICONS / "logo.svg", lambda: svg_mark(256, tile=True).encode())
    add(ICONS / "mark.svg", lambda: svg_mark(256, tile=False).encode())
    add(ICONS / "mark-mono.svg", lambda: svg_mark(256, tile=False, label="RASA SYSTEM mark")
        .replace('fill="#fff"', 'fill="currentColor"').replace('fill="#FFC65A"', 'fill="currentColor"').encode())
    add(ICONS / "logo-ltr.svg", lambda: svg_lockup(dark=False, latin=True).encode())
    add(ICONS / "logo-rtl.svg", lambda: svg_lockup(dark=False, latin=False).encode())
    add(ICONS / "logo-dark.svg", lambda: svg_lockup(dark=True, latin=True).encode())

    # --- raster marks (PWA + panel + receipts)
    add(ICONS / "icon-192.png", lambda: _png_bytes(draw_mark(192)))
    add(ICONS / "icon-512.png", lambda: _png_bytes(draw_mark(512)))
    add(ICONS / "icon-maskable-512.png", lambda: _png_bytes(draw_mark(512, ground="maskable")))
    add(ICONS / "logo-512.png", lambda: _png_bytes(draw_mark(512, ground="none")))
    add(ICONS / "logo-512-dark.png", lambda: _png_bytes(draw_mark(512, ground="none")))

    # --- Windows application icon (multi-resolution ICO, built from the tile)
    def _ico() -> bytes:
        base = draw_mark(256)
        buf = io.BytesIO()
        base.save(buf, format="ICO", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
        return buf.getvalue()
    add(INSTALLER / "icon.ico", _ico)

    # --- Android launcher icons (mdpi…xxxhdpi, 48/72/96/144/192 px)
    for density, px in (("mdpi", 48), ("hdpi", 72), ("xhdpi", 96), ("xxhdpi", 144), ("xxxhdpi", 192)):
        add(ANDROID_RES / f"mipmap-{density}" / "ic_launcher.png", (lambda p=px: _png_bytes(draw_mark(p))))
    add(ANDROID_RES / "drawable" / "rasa_logo.png", lambda: _png_bytes(draw_mark(256, ground="none")))

    # --- brand folder (marketing / print)
    add(BRAND / "logo-light.svg", lambda: svg_lockup(dark=False, latin=True).encode())
    add(BRAND / "logo-dark.svg", lambda: svg_lockup(dark=True, latin=True).encode())
    add(BRAND / "logo-fa.svg", lambda: svg_lockup(dark=False, latin=False).encode())
    add(BRAND / "logo-light.png", lambda: _png_bytes(draw_lockup(1600, dark=False, latin=True)))
    add(BRAND / "logo-dark.png", lambda: _png_bytes(draw_lockup(1600, dark=True, latin=True)))
    add(BRAND / "logo-fa.png", lambda: _png_bytes(draw_lockup(1600, dark=False, latin=False)))
    add(BRAND / "mark.svg", lambda: svg_mark(256, tile=False).encode())
    add(BRAND / "mark-tile.svg", lambda: svg_mark(256, tile=True).encode())
    add(BRAND / "icon-1024.png", lambda: _png_bytes(draw_mark(1024)))
    add(BRAND / "icon-mono-1024.png", lambda: _png_bytes(
        draw_mark(1024, ground="none", bar_color=(17, 24, 39, 255), node_color=(17, 24, 39, 255))))
    return targets


def main() -> int:
    ap = argparse.ArgumentParser(description="Generate every RASA SYSTEM brand asset from one geometry")
    ap.add_argument("--check", action="store_true", help="verify committed assets match the generator (digest, not bytes)")
    args = ap.parse_args()
    targets = build_targets()
    problems, written = [], 0
    for path, fn in targets.items():
        data = fn()
        if args.check:
            if not path.exists():
                problems.append(f"missing: {path.relative_to(ROOT)}")
                continue
            if path.suffix == ".svg":
                if path.read_bytes() != data:
                    problems.append(f"stale: {path.relative_to(ROOT)}")
            else:
                try:
                    cur = Image.open(path)
                    if _digest(cur) != _digest(Image.open(io.BytesIO(data))):
                        problems.append(f"stale: {path.relative_to(ROOT)}")
                except Exception as exc:  # noqa: BLE001
                    problems.append(f"unreadable: {path.relative_to(ROOT)} ({exc})")
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        written += 1
    if args.check:
        for p in problems:
            print("✗", p)
        print("brand assets OK" if not problems else f"{len(problems)} problem(s)")
        return 1 if problems else 0
    print(f"✓ wrote {written} brand asset(s)")
    for path in sorted(targets):
        print("  ", path.relative_to(ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
