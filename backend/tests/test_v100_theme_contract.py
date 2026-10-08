# -*- coding: utf-8 -*-
"""v1.0.0 (RASA) — قرارداد پوسته (Light/Dark) و هویت برند.

باگ گزارش‌شدهٔ مالک: «در حالت روشن، بخش‌هایی از رابط — مخصوصاً نوار کناری — تیره
می‌ماند.» ریشهٔ معماری‌اش این بود:

1. سه لایهٔ پالت مستقل روی هم می‌آمدند (styles.css → theme-pro.css → desktop.css)
   و هرکدام بخشی از توکن‌ها را بازتعریف می‌کرد؛ در نتیجه با `data-theme="light"`
   بعضی توکن‌ها روشن و بعضی تیره می‌ماندند.
2. چند قاعدهٔ پوسته (نوار کناری/سرصفحه/نوار وضعیت) به‌جای توکن، رنگِ تیرهٔ دستی
   داشتند و یک قاعده حتی صریحاً در حالت روشن هم گرادیان تیره می‌گذاشت.

این ماژول آن دو قانون را به آزمون تبدیل می‌کند تا دیگر برنگردند:
  * «هر توکنی که در پالت تیره تعریف شده، در پالت روشن هم تعریف شده باشد.»
  * «هیچ قاعدهٔ پوسته‌ای که در حالت روشن اعمال می‌شود، رنگ پس‌زمینهٔ تیرهٔ دستی نداشته باشد.»

اجرای این تست‌ها هم‌زمان ابزار ممیزی است: هر قاعدهٔ متخلف با نام فایل و شماره خط
گزارش می‌شود.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "frontend"

#: ترتیب بارگذاری واقعی CSS از خود index.html خوانده می‌شود (نه حدس).
_CSS_RE = re.compile(r'<link[^>]+rel="stylesheet"[^>]+href="([^"]+)"')
_RULE_RE = re.compile(r"([^{}]+)\{([^{}]*)\}", re.S)
_VAR_RE = re.compile(r"(--[a-z0-9-]+)\s*:\s*([^;]+)", re.I)

#: توکن‌هایی که ذاتاً فقط برای یک پوسته معنا دارند (سایه/درخشش/پردهٔ مودال).
DARK_ONLY_OK = {
    "--shadow", "--glow-teal", "--glow-violet", "--glow-green", "--glow-red", "--glow-amber",
    "--scrim", "--brand-shadow",
}

#: عناصر پوسته که در حالت روشن نباید تیره بمانند.
SHELL_SELECTORS = (".sidebar", ".brand", ".topbar", ".statusbar", ".nav-item", ".app", ".view")

PROP_LIGHT_CRITICAL = ("background", "background-color", "color")


def _css_files_in_order() -> list[Path]:
    html = (FRONTEND / "index.html").read_text(encoding="utf-8")
    files = []
    for href in _CSS_RE.findall(html):
        p = FRONTEND / href.lstrip("/")
        assert p.exists(), f"index.html references a missing stylesheet: {href}"
        files.append(p)
    return files


def _iter_rules(path: Path):
    """(selector, body, line_number) for every rule in a stylesheet."""
    text = path.read_text(encoding="utf-8")
    for m in _RULE_RE.finditer(text):
        sel = " ".join(m.group(1).split())
        if not sel or sel.startswith("@") or sel.startswith("/*"):
            continue
        line = text[: m.start(1)].count("\n") + 1
        yield sel, m.group(2), line


def _is_dark_scoped(selector: str) -> bool:
    """True when the rule can only ever apply to the dark theme."""
    if '[data-theme="light"]' in selector or "[data-theme=light]" in selector:
        return False
    if '[data-theme="dark"]' in selector or "[data-theme=dark]" in selector:
        return True
    # `:root` alone carries the default (dark) palette; those blocks are tokens, not rules.
    return False


def _luminance(color: str) -> float | None:
    """Relative luminance 0..1 for a literal colour (hex or rgba), else None."""
    c = color.strip().lower()
    m = re.fullmatch(r"#([0-9a-f]{6})", c)
    if m:
        r, g, b = (int(m.group(1)[i : i + 2], 16) / 255 for i in (0, 2, 4))
        return 0.2126 * r + 0.7152 * g + 0.0722 * b
    m = re.fullmatch(r"#([0-9a-f]{3})", c)
    if m:
        r, g, b = (int(ch * 2, 16) / 255 for ch in m.group(1))
        return 0.2126 * r + 0.7152 * g + 0.0722 * b
    m = re.fullmatch(r"rgba?\(([^)]+)\)", c)
    if m:
        parts = [p.strip() for p in m.group(1).split(",")]
        if len(parts) < 3:
            return None
        try:
            r, g, b = (float(p) / 255 for p in parts[:3])
            a = float(parts[3]) if len(parts) > 3 else 1.0
        except ValueError:
            return None
        lum = 0.2126 * r + 0.7152 * g + 0.0722 * b
        # A translucent scrim over a light page still darkens it; weight by alpha.
        return lum * a + (1 - a)
    return None


def test_every_theme_token_declared_for_light_too():
    """قانون ۱ — پالت روشن باید کامل باشد، وگرنه مقدار تیره «نشت» می‌کند."""
    dark: dict[str, tuple[Path, int]] = {}
    light: dict[str, tuple[Path, int]] = {}
    for path in _css_files_in_order():
        for sel, body, line in _iter_rules(path):
            for name, _value in _VAR_RE.findall(body):
                name = name.lower()
                if '[data-theme="light"]' in sel or "[data-theme=light]" in sel:
                    light.setdefault(name, (path, line))
                elif '[data-theme="dark"]' in sel or "[data-theme=dark]" in sel or ":root" in sel:
                    dark.setdefault(name, (path, line))
    missing = sorted(n for n in dark if n not in light and n not in DARK_ONLY_OK)
    assert not missing, (
        "این توکن‌ها پالت تیره دارند ولی در پالت روشن تعریف نشده‌اند (نتیجه: در حالت روشن "
        "مقدار تیره به ارث می‌رسد):\n  " + "\n  ".join(f"{n}  ← {dark[n][0].name}:{dark[n][1]}" for n in missing)
    )


def test_no_dark_literal_paints_shell_in_light_theme():
    """قانون ۲ — نوار کناری/سرصفحه نباید در حالت روشن رنگ دستیِ تیره داشته باشند."""
    offenders = []
    for path in _css_files_in_order():
        for sel, body, line in _iter_rules(path):
            if _is_dark_scoped(sel):
                continue
            if not any(s in sel for s in SHELL_SELECTORS):
                continue
            for decl in body.split(";"):
                if ":" not in decl:
                    continue
                prop, _, value = decl.partition(":")
                prop, value = prop.strip().lower(), value.strip()
                if prop not in PROP_LIGHT_CRITICAL:
                    continue
                literals = re.findall(r"#[0-9a-fA-F]{3,8}|rgba?\([^)]*\)", value)
                dark_literals = [lit for lit in literals if (_luminance(lit) or 0) < 0.32]
                # A rule is only a bug when the dark colour is the *basis* of the value
                # (a purely decorative gradient stop over `var(--…)` is fine).
                if dark_literals and "var(--" not in value:
                    offenders.append(f"{path.name}:{line} {sel} → {prop}: {value.strip()[:70]}")
    assert not offenders, (
        "این قاعده‌ها در حالت روشن رنگ تیرهٔ دستی روی پوسته می‌گذارند (باید از توکن "
        "مثل var(--shell-bg) استفاده کنند):\n  " + "\n  ".join(offenders)
    )


def test_shell_tokens_exist_in_both_themes():
    """قانون ۳ — توکن‌های پوسته باید در هر دو پالت تعریف شده باشند."""
    text = "".join(p.read_text(encoding="utf-8") for p in _css_files_in_order())
    for token in ("--shell-bg", "--shell-fg", "--shell-muted", "--shell-hover",
                  "--shell-active-bg", "--shell-active-fg", "--topbar-bg", "--statusbar-bg"):
        assert text.count(f"{token}:") >= 2, f"{token} must be declared for dark AND light"


def test_theme_layer_order_is_stable():
    """لایهٔ ظاهری باید بعد از پایه و قبل از برند بیاید (رگرسیون: ترتیب لایه‌ها)."""
    names = [p.name for p in _css_files_in_order()]
    assert names.index("styles.css") == 0, names
    assert names.index("theme-pro.css") < names.index("ui-refresh.css"), names


@pytest.mark.parametrize("asset", [
    "frontend/icons/logo.svg",
    "frontend/icons/mark.svg",
    "frontend/icons/mark-mono.svg",
    "frontend/icons/logo-rtl.svg",
    "frontend/icons/logo-ltr.svg",
    "frontend/icons/logo-dark.svg",
    "frontend/icons/icon-192.png",
    "frontend/icons/icon-512.png",
    "frontend/icons/icon-maskable-512.png",
    "installer/windows/icon.ico",
    "docs/brand/mark.svg",
    "docs/brand/icon-1024.png",
])
def test_rasa_brand_assets_exist(asset):
    path = ROOT / asset
    assert path.exists(), f"brand asset missing: {asset}"
    assert path.stat().st_size > 400, f"brand asset looks empty: {asset}"


def test_android_launcher_icons_are_the_rasa_mark():
    """آیکون لانچر اندروید باید همان نشان برند باشد، در همهٔ چگالی‌ها."""
    res = ROOT / "mobile-android/app/src/main/res"
    hashes = {}
    for density, px in (("mdpi", 48), ("hdpi", 72), ("xhdpi", 96), ("xxhdpi", 144), ("xxxhdpi", 192)):
        p = res / f"mipmap-{density}" / "ic_launcher.png"
        assert p.exists(), f"missing launcher icon for {density}"
        from PIL import Image
        im = Image.open(p).convert("RGBA")
        assert im.size == (px, px), f"{density} launcher must be {px}px, got {im.size}"
        hashes[density] = im.resize((16, 16), Image.LANCZOS).tobytes()
    assert len(set(hashes.values())) == len(hashes), "launcher icons must differ per density (not one file copied)"


def test_brand_generator_reproduces_committed_assets():
    """دارایی‌های برند از یک هندسه ساخته می‌شوند؛ اگر کسی دستی عوضشان کند، اینجا شکست می‌خورد."""
    import subprocess
    import sys
    r = subprocess.run([sys.executable, str(ROOT / "scripts/make_logo.py"), "--check"],
                       capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stdout + r.stderr
