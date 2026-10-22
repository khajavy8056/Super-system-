# -*- coding: utf-8 -*-
"""v1.0.526 — the owner's logo, everywhere, including the status bar.

Context (owner report, مهر ۱۴۰۵):
  «لوگوی برنامه تغییر می‌کند … در نسخهٔ اندروید نوتیفیکیشن‌هایی که دریافت می‌کنیم به
   شکلی که علامت تعجب می‌آید؛ باید همان لوگوی برنامه مشخص باشد.»

Two separate failures were behind that complaint, and each one gets a test here:

1. **The identity had no single source.** ``scripts/make_logo.py`` drew the mark
   from hand-written geometry, so replacing the artwork meant editing code in
   five places and the shipped assets drifted apart. Now the artwork itself
   (``docs/brand/logo-master.png``) is the source and every asset is derived
   from it — ``--check`` proves the committed files still match.
2. **Notifications never used the app icon.** ``Notify.java`` asked for
   ``android.R.drawable.ic_dialog_info`` — the system «!» — because a
   full-colour launcher PNG cannot be used as a status-bar icon (Android draws
   only its alpha channel, so it becomes a white blob). The fix is a dedicated
   alpha-only silhouette asset, and a regression test that fails if anyone
   reintroduces a framework glyph.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
ANDROID = ROOT / "mobile-android" / "app" / "src" / "main"
RES = ANDROID / "res"
JAVA = ANDROID / "java" / "ir" / "khajavy" / "supermarket"
MASTER = ROOT / "docs" / "brand" / "logo-master.png"

STATUS_SIZES = (("mdpi", 24), ("hdpi", 36), ("xhdpi", 48), ("xxhdpi", 72), ("xxxhdpi", 96))
LAUNCHER_SIZES = (("mdpi", 48), ("hdpi", 72), ("xhdpi", 96), ("xxhdpi", 144), ("xxxhdpi", 192))


# --- 1. one artwork, one source ---------------------------------------------------
def test_master_artwork_exists_and_is_the_source_of_truth():
    assert MASTER.exists(), "لوگوی اصلی (docs/brand/logo-master.png) وجود ندارد"
    from PIL import Image
    im = Image.open(MASTER)
    assert im.width >= 512 and im.height >= 512, f"رزولوشن لوگوی اصلی کم است: {im.size}"
    # the generator must point at that exact file, not at a copy
    script = (ROOT / "scripts" / "make_logo.py").read_text(encoding="utf-8")
    assert 'MASTER = BRAND / "logo-master.png"' in script


def test_every_shipped_brand_asset_is_regenerated_from_the_master():
    """اگر کسی لوگو را دستی عوض کند، این آزمون (و CI) قرمز می‌شود."""
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "make_logo.py"), "--check"],
                       capture_output=True, text=True, timeout=600)
    assert r.returncode == 0, r.stdout + r.stderr


def test_the_panel_android_and_windows_all_show_the_same_mark():
    """یک هندسه → آیکون پنل، لانچر اندروید و آیکون ویندوز باید یک نشان باشند."""
    from PIL import Image
    ref = Image.open(ROOT / "frontend" / "icons" / "icon-512.png").convert("RGBA").resize((32, 32), Image.LANCZOS)
    for path in (RES / "mipmap-xxxhdpi" / "ic_launcher.png",
                 ROOT / "docs" / "brand" / "icon-1024.png"):
        im = Image.open(path).convert("RGBA").resize((32, 32), Image.LANCZOS)
        diff = sum(abs(a - b) for pa, pb in zip(ref.getdata(), im.getdata()) for a, b in zip(pa, pb))
        assert diff / (32 * 32 * 4) < 6, f"{path.name} با نشان پنل یکی نیست"


# --- 2. notifications carry the product mark --------------------------------------
def test_status_bar_icon_is_generated_for_every_density():
    from PIL import Image
    digests = set()
    for density, px in STATUS_SIZES:
        p = RES / f"drawable-{density}" / "ic_stat_rasa.png"
        assert p.exists(), f"آیکون نوار وضعیت برای {density} ساخته نشده"
        im = Image.open(p).convert("RGBA")
        assert im.size == (px, px), f"{density}: باید {px}px باشد، هست {im.size}"
        # Android paints the alpha channel only → white silhouette, no colour glyph
        r, g, b, a = im.split()
        assert a.getextrema()[0] == 0, f"{density}: آیکون باید شفافیت داشته باشد"
        assert a.getbbox() is not None, f"{density}: آیکون خالی است"
        solid = [(pr, pg, pb) for pr, pg, pb, pa in im.getdata() if pa > 200]
        assert solid, f"{density}: هیچ پیکسل مات ندارد"
        assert all(px_ == (255, 255, 255) for px_ in solid), f"{density}: باید تک‌رنگ سفید باشد (آلفا-محور)"
        digests.add(im.resize((16, 16), Image.LANCZOS).tobytes())
    assert len(digests) == len(STATUS_SIZES), "آیکون‌های هر چگالی باید مستقل رندر شده باشند"


def _code_only(java: str) -> str:
    """Drop // and /* */ comments so historical notes in the doc block do not fail the check."""
    import re
    java = re.sub(r"/\*.*?\*/", "", java, flags=re.S)
    return "\n".join(line.split("//")[0] for line in java.splitlines())


def test_notifications_use_the_product_mark_not_a_system_glyph():
    notify = _code_only((JAVA / "Notify.java").read_text(encoding="utf-8"))
    assert "R.drawable.ic_stat_rasa" in notify, "نشان برنامه در اعلان‌ها استفاده نشده"
    assert "setLargeIcon" in notify, "لوگوی رنگی برای اعلان باز‌شده تنظیم نشده"
    for banned in ("android.R.drawable.ic_dialog_info", "android.R.drawable.stat_sys_download"):
        assert banned not in notify, f"آیکون سیستمی «{banned}» دوباره برگشته (همان علامت تعجب)"


def test_full_colour_logo_asset_used_as_large_icon_exists():
    p = RES / "drawable" / "rasa_logo.png"
    assert p.exists(), "drawable/rasa_logo.png برای setLargeIcon ساخته نشده"
    from PIL import Image
    im = Image.open(p).convert("RGBA")
    assert im.size[0] >= 128 and im.getchannel("A").getbbox() is not None
    # it must be in colour, otherwise the shade would show a white blob again
    colours = {c for c in im.convert("RGB").getdata() if c != (255, 255, 255)}
    assert len(colours) > 50, "لوگوی بزرگ باید رنگی باشد"


def test_launcher_icons_are_still_per_density_and_full_size():
    from PIL import Image
    for density, px in LAUNCHER_SIZES:
        p = RES / f"mipmap-{density}" / "ic_launcher.png"
        assert p.exists(), f"آیکون لانچر {density} نیست"
        assert Image.open(p).size == (px, px)


@pytest.mark.parametrize("asset", [
    "frontend/icons/logo.svg",
    "frontend/icons/icon-192.png",
    "frontend/icons/icon-512.png",
    "installer/windows/icon.ico",
    "docs/brand/logo-fa.png",
])
def test_brand_asset_is_a_real_file(asset):
    p = ROOT / asset
    assert p.exists() and p.stat().st_size > 400, f"دارایی برند خالی/ناقص است: {asset}"
