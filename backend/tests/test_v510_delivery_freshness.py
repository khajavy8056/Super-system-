# -*- coding: utf-8 -*-
"""build-510 — «آپدیت نصب شد ولی هیچ تغییری دیده نشد» — پایان کلاسِ خطا.

گزارش مالک پس از ۵۰۸/۵۰۹: «هیچ‌کدام از تغییرات را نمی‌بینم». ریشه: پین نسخهٔ
`?v=` در index.html از ۱٫۰٫۴۹۶ به بعد هرگز عوض نشده بود و WebView2 همان
`app.js` کهنهٔ کش‌شده را اجرا می‌کرد؛ در نتیجه همهٔ امکان‌های فقط-رابطی
(نوار پرفروش‌ها، فرم جشنواره، بنرها) روی دستگاه هرگز نرسیده بودند.

این تست‌ها برای همیشه قفل می‌کنند:
۱) پین نسخهٔ همهٔ اسکریپت/استایل‌های پوسته == نسخهٔ انتشار (بالا/پایین رفتن
   نسخه بدون به‌روزکردن پین = تست قرمز).
۲) سرور فایل‌های پوسته را با `Cache-Control: no-cache` می‌فرستد (کش مجبور به
   revalidate؛ کلاس «رابط کهنه از کش» بی‌اعتبار می‌شود).
۳) health نسخه و بیلد بک‌اند را می‌دهد و رابط بر اساس آن ناسازگاری را هشدار می‌دهد.
۴) زیپ ویندوز و APKِ همین نسخه واقعاً محتوای تازه را داخل خودشان دارند (نه
   بستهٔ کهنه با اسم تازه).
"""
from __future__ import annotations

import re
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
import sys as _sys
_sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app as _app  # noqa: E402 — نسخه از منبع واحد (build-511: ضدشکستن با bump)
from tests.release_gate import require_artifact  # noqa: E402

VERSION = _app.__version__
BUILD = _app.BUILD


def _pins(html: str) -> list[str]:
    return re.findall(r"\?v=([0-9.]+)", html)


def test_shell_version_pins_match_release():
    idx = (ROOT / "frontend/index.html").read_text("utf-8")
    pins = _pins(idx)
    assert pins and all(p == VERSION for p in pins), f"پین کهنه در index.html: {sorted(set(pins))}"
    app = (ROOT / "frontend/app.js").read_text("utf-8")
    m = re.search(r"const UI_BUILD = (\d+);", app)
    assert m and int(m.group(1)) == BUILD // 100, "UI_BUILD با بیلد هم‌خوان نیست"
    mob = (ROOT / "frontend/mobile/index.html").read_text("utf-8")
    mpins = _pins(mob)
    assert mpins and all(p == VERSION for p in mpins), f"پین کهنه در mobile/index.html: {sorted(set(mpins))}"


def test_backend_serves_shell_with_no_cache(client):
    r = client.get("/app.js")
    assert r.status_code == 200, r.status_code
    assert "no-cache" in r.headers.get("cache-control", ""), "app.js باید no-cache باشد"
    r2 = client.get("/")
    assert r2.status_code == 200
    assert f"?v={VERSION}" in r2.text, "index.html سروشده باید پین نسخهٔ جاری را داشته باشد"
    assert "1.0.496" not in r2.text, "پین کهنه نباید هیچ‌جا مانده باشد"


def test_health_exposes_version_and_build(client):
    r = client.get("/api/system/health")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["version"] == VERSION and body["build"] == BUILD, body


def test_desktop_zip_ships_current_ui():
    zp = require_artifact(ROOT / "releases/windows" / f"RasaSystemDesktopUI-{VERSION}.zip")
    with zipfile.ZipFile(zp) as z:
        app = z.read("frontend/app.js").decode("utf-8")
        idx = z.read("frontend/index.html").decode("utf-8")
    assert f"const UI_BUILD = {BUILD // 100};" in app, "زیپ، app.js کهنه را بسته!"
    for marker in ("issue_on_checkout", 'id="cm-thr"', "pos-fast", "پس از ثبت چند فاکتور"):
        assert marker in app, f"زیپ فاقد نشانگر تازه: {marker}"
    assert f"?v={VERSION}" in idx and "1.0.496" not in idx, "index.html داخل زیپ کهنه است"


def test_android_apk_ships_current_features():
    apk = ROOT / "releases/android" / f"RasaSystemMobile-{VERSION}.apk"
    assert apk.exists(), f"{apk.name} ساخته نشده"
    with zipfile.ZipFile(apk) as z:
        dex = b"".join(z.read(n) for n in z.namelist() if n.endswith(".dex"))
    assert b"fastMovers" in dex, "نوار پرفروش‌ها در APK نیست"
    assert b"issue_on_checkout" in dex, "راهنمای کوپن خرید بعدی در APK نیست"
    assert "جشنواره".encode("utf-8") in dex and "پرفروش".encode("utf-8") in dex


def test_ui_backend_pairing_guard_and_visible_identity():
    app = (ROOT / "frontend/app.js").read_text("utf-8")
    assert "بک‌اند نصب‌شده قدیمی‌تر" in app, "هشدار جفت‌ناسازی رابط/بک‌اند باید باشد"
    assert "/system/health" in app, "رابط باید نسخهٔ واقعی بک‌اند را بخواند"
    assert "۱٫۰٫۴۹۷" not in app, "نسخهٔ خشک‌شدهٔ قدیمی در داشبورد نمانده باشد"
    sales = (ROOT / "mobile-android/app/src/main/java/ir/khajavy/supermarket/SalesScreens.java").read_text("utf-8")
    assert "با ثبت همین فاکتور…" in sales, "بنر کوپن خرید بعدی اندروید باید باشد"
    sys_src = (ROOT / "backend/app/main.py").read_text("utf-8")
    assert "_RevalidatingStaticFiles" in sys_src and "no-cache" in sys_src
