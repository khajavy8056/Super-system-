#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""RASA SYSTEM (رسا سیستم) — brand identity generator.

v1.0.526 — the identity now comes from **one master artwork** instead of code
geometry: ``docs/brand/logo-master.png`` (1254×1254, provided by the owner in
October 2026 — shopping cart + ascending green bars, Persian wordmark, tagline
«نرم‌افزار مدیریت فروشگاه»).  Every shipped asset is a deterministic crop /
resize / re-composition of that file, so there is exactly one place to change
the logo and no way for the app, the installer, the panel and the APK icon to
drift apart again.

    frontend/icons/logo.svg              tile mark (vector wrapper, panel/login/PWA)
    frontend/icons/mark.svg              standalone mark on transparent ground
    frontend/icons/mark-mono.svg         monochrome mark (print, one-colour use)
    frontend/icons/logo-rtl.svg          full lockup — Persian wordmark
    frontend/icons/logo-ltr.svg          full lockup — Latin wordmark
    frontend/icons/logo-dark.svg         full lockup on dark ground
    frontend/icons/icon-192.png          PWA / manifest
    frontend/icons/icon-512.png          PWA / manifest
    frontend/icons/icon-maskable-512.png PWA (Android mask safe-zone)
    frontend/icons/logo-512.png          mark, transparent ground
    frontend/icons/logo-512-dark.png     mark, transparent ground, dark-theme tint
    installer/windows/icon.ico           Windows application icon (multi-size)
    mobile-android/.../mipmap-*/ic_launcher.png          Android launcher (5 densities)
    mobile-android/.../drawable/rasa_logo.png            in-app mark / notification large icon
    mobile-android/.../drawable-*/ic_stat_rasa.png       status-bar small icon (5 densities)
    docs/brand/*.svg|png                 marketing / print lockups

Why the small icon is a separate asset
--------------------------------------
Android draws the status-bar icon from its **alpha channel only** — a full-colour
launcher PNG passed to ``setSmallIcon`` is rendered as a solid white blob, and a
framework icon (``android.R.drawable.ic_dialog_info``, the «!» the owner kept
seeing) replaces the product identity with a system glyph.  ``ic_stat_rasa`` is
the cart silhouette in pure white/alpha at 24 dp, so notifications in the status
bar, the lock screen and the shade all carry the RASA mark.  The full-colour
mark is attached as ``setLargeIcon`` alongside it.

Rebuild everything with:
    python scripts/make_logo.py            # write every asset
    python scripts/make_logo.py --check    # verify committed assets (CI)

Rasterisation is Pillow only: the sandbox has no libcairo, and shipping brand
assets that rebuild on exactly one machine is how a logo drifts away from its
own source.  ``.svg`` outputs are single-image SVG wrappers around the raster
(the master is a bitmap, not a path set) — browsers, Inkscape and print all
render them, and they keep one source of truth.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import io
import sys
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
ICONS = ROOT / "frontend" / "icons"
ANDROID_RES = ROOT / "mobile-android" / "app" / "src" / "main" / "res"
INSTALLER = ROOT / "installer" / "windows"
BRAND = ROOT / "docs" / "brand"
FONTS = ROOT / "frontend" / "fonts"

#: The single source of truth.  Everything below is derived from it.
MASTER = BRAND / "logo-master.png"

#: Regions inside the master (measured once, in master pixels):
#:   cart   — the cart + bars glyph, no wordmark
#:   lockup — cart + Persian wordmark + tagline
CART_BOX = (231, 205, 1020, 750)
LOCKUP_BOX = (149, 205, 1104, 1067)
INK_THRESHOLD = 24                    # distance from white before a pixel counts

# --- palette -------------------------------------------------------------------
GREEN = (16, 185, 129, 255)     # #10B981 — success / growth (matches the app's --ok)
GOLD = (255, 198, 90, 255)      # #FFC65A  (--gold)
INK = (255, 255, 255, 255)
DARK_BG = (8, 20, 46, 255)      # #08142E  panel dark surface
LIGHT_BG = (255, 255, 255, 255)
MUTED_LIGHT = (84, 100, 137, 255)
MUTED_DARK = (173, 185, 220, 255)

BRAND_FA = "رسا سیستم"
BRAND_FULL_FA = "نرم‌افزار مدیریت فروشگاه"
BRAND_LTR = "RASA SYSTEM"
TAGLINE_FA = "مدیریت هوشمند فروشگاه"
TAGLINE_LTR = "SUPERMARKET MANAGEMENT"

TILE_RADIUS = 0.227             # rounded-square ratio, same as every shipped icon


# --- master artwork -------------------------------------------------------------
def _content_bbox(img: Image.Image) -> tuple[int, int, int, int]:
    bbox = img.getchannel("A").point(lambda v: 255 if v > 8 else 0).getbbox()
    if not bbox:  # pragma: no cover
        raise SystemExit("master artwork appears to be blank")
    return bbox


@lru_cache(maxsize=1)
def _cart() -> Image.Image:
    """Cart + bars glyph, cropped out of the master and trimmed."""
    src = Image.open(MASTER)
    cart = src.crop(CART_BOX)
    m = _flatten_crop(cart)
    return m


def _flatten_crop(img: Image.Image) -> Image.Image:
    """White→alpha un-blend: colour recovered, ground removed."""
    src = img.convert("RGB")
    px = src.load()
    out = Image.new("RGBA", src.size, (0, 0, 0, 0))
    dst = out.load()
    w, h = src.size
    for y in range(h):
        for x in range(w):
            r, g, b = px[x, y]
            a = 255 - min(r, g, b)
            if a <= INK_THRESHOLD:
                dst[x, y] = (0, 0, 0, 0)
                continue
            a_frac = a / 255.0
            un = tuple(max(0, min(255, int(round((c - (1 - a_frac) * 255) / max(a_frac, 0.02)))))
                       for c in (r, g, b))
            dst[x, y] = (un[0], un[1], un[2], 255 if a >= 250 else a)
    return out


@lru_cache(maxsize=1)
def _mark_trimmed() -> Image.Image:
    cart = _cart()
    return cart.crop(_content_bbox(cart))


def _fit(img: Image.Image, box_w: int, box_h: int, *, pad: float = 0.0) -> Image.Image:
    """Scale ``img`` to fit inside the box, keeping the aspect ratio."""
    avail_w = max(1, int(box_w * (1 - 2 * pad)))
    avail_h = max(1, int(box_h * (1 - 2 * pad)))
    ratio = min(avail_w / img.width, avail_h / img.height)
    size = (max(1, int(round(img.width * ratio))), max(1, int(round(img.height * ratio))))
    return img.resize(size, Image.LANCZOS)


def _rounded_mask(size: int, radius_ratio: float) -> Image.Image:
    ss = 4
    mask = Image.new("L", (size * ss, size * ss), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, size * ss - 1, size * ss - 1),
                                           radius=int(size * ss * radius_ratio), fill=255)
    return mask.resize((size, size), Image.LANCZOS)


def draw_mark(size: int = 256, *, ground: str = "tile", pad: float = 0.13,
              tint: tuple[int, int, int, int] | None = None) -> Image.Image:
    """The RASA mark at ``size`` px.

    ground: ``tile``  — rounded white tile (app icon, installer, launcher)
            ``none``  — transparent background
            ``maskable`` — full-bleed white square with the glyph inside the
                           Android mask safe zone (66 % of the canvas)
            ``dark``/``light`` — flat ground for lockups
    pad:    empty margin around the glyph, as a fraction of the tile
    tint:   repaint the glyph in a single colour (mono/print use)
    """
    ss = 3
    S = size * ss
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    if ground == "tile":
        tile = Image.new("RGBA", (S, S), LIGHT_BG)
        img.paste(tile, (0, 0), _rounded_mask(size, TILE_RADIUS).resize((S, S), Image.LANCZOS))
    elif ground == "maskable":
        img.paste(Image.new("RGBA", (S, S), LIGHT_BG), (0, 0))
        pad = max(pad, 0.17)
    elif ground in ("dark", "light"):
        img.paste(Image.new("RGBA", (S, S), DARK_BG if ground == "dark" else LIGHT_BG),
                  (0, 0), _rounded_mask(size, 0.0).resize((S, S), Image.LANCZOS))
    glyph = _mark_trimmed()
    if tint is not None:
        solid = Image.new("RGBA", glyph.size, tint[:3] + (255,))
        solid.putalpha(glyph.getchannel("A"))
        glyph = solid
    glyph = _fit(glyph, S, S, pad=pad)
    # the artwork is wider than tall; centre the visual mass slightly high so
    # the cart wheels do not sit on the tile edge
    img.alpha_composite(glyph, ((S - glyph.width) // 2, int((S - glyph.height) * 0.46)))
    return img.resize((size, size), Image.LANCZOS)


def draw_status_icon(size: int = 24) -> Image.Image:
    """Status-bar icon: white glyph on transparency, 24 dp, ~1 px optical padding.

    Android uses the alpha channel only, so the glyph is flattened to a solid
    white silhouette — anything else renders as a white blob or a system «!».
    """
    ss = 6
    S = size * ss
    canvas = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    glyph = _fit(_mark_trimmed(), S, S, pad=0.10)
    white = Image.new("RGBA", glyph.size, (255, 255, 255, 255))
    white.putalpha(glyph.getchannel("A"))
    canvas.alpha_composite(white, ((S - glyph.width) // 2, (S - glyph.height) // 2))
    return canvas.resize((size, size), Image.LANCZOS)


# --- Persian/Latin text (for the composed lockups) -------------------------------
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


def _latin_font(px: int) -> ImageFont.FreeTypeFont:
    key = ("dejavu", px)
    if key not in _font_cache:
        path = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
        _font_cache[key] = ImageFont.truetype(path, px)
    return _font_cache[key]


def _shape_fa(text: str) -> str:
    """Persian text ready for a non-shaping renderer (Pillow)."""
    import arabic_reshaper
    from bidi.algorithm import get_display
    return get_display(arabic_reshaper.reshape(text))


# --- lockups --------------------------------------------------------------------
def draw_lockup(width: int = 1600, *, dark: bool = False, latin: bool = False,
                master: bool = False) -> Image.Image:
    """Full lockup: mark + wordmark + tagline.

    ``master=True`` pastes the owner's artwork verbatim (the Persian lockup on
    its light ground is the authoritative composition).  The dark and Latin
    variants are composed here, because the master ships only that rendering.
    """
    if master:
        src = Image.open(MASTER).convert("RGB").crop(LOCKUP_BOX)
        scale = width / src.width
        return src.resize((width, max(1, int(src.height * scale))), Image.LANCZOS).convert("RGBA")

    mark = int(width * 0.15)
    gap = int(mark * 0.28)
    f_title = _latin_font(int(mark * 0.60)) if latin else _font(int(mark * 0.52), "Bold")
    f_sub = _latin_font(int(mark * 0.19)) if latin else _font(int(mark * 0.20), "Regular")
    title = BRAND_LTR if latin else _shape_fa(BRAND_FA)
    sub = TAGLINE_LTR if latin else _shape_fa(TAGLINE_FA)

    probe = ImageDraw.Draw(Image.new("RGBA", (8, 8)))
    tw = max(probe.textlength(title, font=f_title), probe.textlength(sub, font=f_sub))
    h = int(mark * 1.42)
    W = mark + gap + int(tw) + int(mark * 0.34)
    img = Image.new("RGBA", (W, h), DARK_BG if dark else LIGHT_BG)
    tile = draw_mark(mark, ground="tile", pad=0.12)
    x_mark = int(mark * 0.17) if latin else W - mark - int(mark * 0.17)
    img.alpha_composite(tile, (x_mark, (h - mark) // 2))
    ink = (240, 244, 255, 255) if dark else (16, 28, 60, 255)
    muted = MUTED_DARK if dark else MUTED_LIGHT
    d = ImageDraw.Draw(img)
    left = x_mark + mark + gap

    def put(text, font, fill, cy):
        w = d.textlength(text, font=font)
        x = left if latin else x_mark - gap - w
        d.text((x, cy - font.size * 0.72), text, font=font, fill=fill)
    put(title, f_title, ink, h * 0.42)
    put(sub, f_sub, muted, h * 0.76)
    return img


# --- SVG ------------------------------------------------------------------------
def _data_uri(img: Image.Image) -> str:
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


def svg_wrap(img: Image.Image, name: str, *, label: str = "RASA SYSTEM") -> str:
    """Single-image SVG wrapper (the master is a bitmap; this keeps one source)."""
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<!-- RASA SYSTEM (رسا سیستم) — {name}. Generated by scripts/make_logo.py from
     docs/brand/logo-master.png; edit the master, never this file. -->
<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink"
     viewBox="0 0 {img.width} {img.height}" width="{img.width}" height="{img.height}"
     role="img" aria-label="{label}">
  <image width="{img.width}" height="{img.height}" href="{_data_uri(img)}"
         xlink:href="{_data_uri(img)}" />
</svg>
'''


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

    # --- vectors (single-image wrappers around the master-derived raster)
    add(ICONS / "logo.svg", lambda: svg_wrap(draw_mark(256), "logo", label="رسا سیستم").encode())
    add(ICONS / "mark.svg", lambda: svg_wrap(draw_mark(256, ground="none"),
                                             "mark", label="RASA SYSTEM mark").encode())
    add(ICONS / "mark-mono.svg", lambda: svg_wrap(
        draw_mark(256, ground="none", tint=(17, 24, 39, 255)), "mark-mono",
        label="RASA SYSTEM mark (one colour)").encode())
    add(ICONS / "logo-rtl.svg", lambda: svg_wrap(
        draw_lockup(1200, master=True), "logo-rtl", label="رسا سیستم — RASA SYSTEM").encode())
    add(ICONS / "logo-ltr.svg", lambda: svg_wrap(
        draw_lockup(1200, latin=True), "logo-ltr").encode())
    add(ICONS / "logo-dark.svg", lambda: svg_wrap(
        draw_lockup(1200, dark=True, latin=True), "logo-dark").encode())

    # --- raster marks (PWA + panel + receipts)
    add(ICONS / "icon-192.png", lambda: _png_bytes(draw_mark(192)))
    add(ICONS / "icon-512.png", lambda: _png_bytes(draw_mark(512)))
    add(ICONS / "icon-maskable-512.png", lambda: _png_bytes(draw_mark(512, ground="maskable")))
    add(ICONS / "logo-512.png", lambda: _png_bytes(draw_mark(512, ground="none")))
    add(ICONS / "logo-512-dark.png", lambda: _png_bytes(draw_mark(512, ground="dark", pad=0.16)))

    # --- Windows application icon (multi-resolution ICO, built from the tile)
    def _ico() -> bytes:
        base = draw_mark(256)
        buf = io.BytesIO()
        base.save(buf, format="ICO", sizes=[(16, 16), (24, 24), (32, 32), (48, 48),
                                            (64, 64), (128, 128), (256, 256)])
        return buf.getvalue()
    add(INSTALLER / "icon.ico", _ico)

    # --- Android launcher icons (mdpi…xxxhdpi, 48/72/96/144/192 px)
    for density, px in (("mdpi", 48), ("hdpi", 72), ("xhdpi", 96), ("xxhdpi", 144), ("xxxhdpi", 192)):
        add(ANDROID_RES / f"mipmap-{density}" / "ic_launcher.png", (lambda p=px: _png_bytes(draw_mark(p))))
    add(ANDROID_RES / "drawable" / "rasa_logo.png",
        lambda: _png_bytes(draw_mark(256, ground="none")))

    # --- Android status-bar notification icons (alpha-only, 24 dp)
    for density, px in (("mdpi", 24), ("hdpi", 36), ("xhdpi", 48), ("xxhdpi", 72), ("xxxhdpi", 96)):
        add(ANDROID_RES / f"drawable-{density}" / "ic_stat_rasa.png",
            (lambda p=px: _png_bytes(draw_status_icon(p))))

    # --- brand folder (marketing / print)
    add(BRAND / "logo-light.svg", lambda: svg_wrap(draw_lockup(1200, latin=True), "logo-light").encode())
    add(BRAND / "logo-dark.svg", lambda: svg_wrap(draw_lockup(1200, dark=True, latin=True), "logo-dark").encode())
    add(BRAND / "logo-fa.svg", lambda: svg_wrap(draw_lockup(1200, master=True), "logo-fa",
                                                label="رسا سیستم — RASA SYSTEM").encode())
    add(BRAND / "logo-light.png", lambda: _png_bytes(draw_lockup(1600, latin=True)))
    add(BRAND / "logo-dark.png", lambda: _png_bytes(draw_lockup(1600, dark=True, latin=True)))
    add(BRAND / "logo-fa.png", lambda: _png_bytes(draw_lockup(1600, master=True)))
    add(BRAND / "mark.svg", lambda: svg_wrap(draw_mark(256, ground="none"), "mark",
                                             label="RASA SYSTEM mark").encode())
    add(BRAND / "mark-tile.svg", lambda: svg_wrap(draw_mark(256), "mark-tile",
                                                  label="RASA SYSTEM").encode())
    add(BRAND / "icon-1024.png", lambda: _png_bytes(draw_mark(1024)))
    add(BRAND / "icon-mono-1024.png", lambda: _png_bytes(
        draw_mark(1024, ground="none", tint=(17, 24, 39, 255))))
    return targets


def main() -> int:
    ap = argparse.ArgumentParser(description="Generate every RASA SYSTEM brand asset from the master artwork")
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
    print(f"✓ wrote {written} brand asset(s) from {MASTER.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
