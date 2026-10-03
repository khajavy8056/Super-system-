# -*- coding: utf-8 -*-
"""انتشار: نسخه‌ها، APK و بستهٔ رابط ویندوز دست‌به‌دست هم هستند.

نام فایل برای تاریخچه حفظ شده (نسخهٔ بتا v4.8.0 این قرارداد را ساخت)؛ از v1.0.0
(RASA) به بعد همان محافظت‌ها با برند و شمارهٔ بیلد جدید اجرا می‌شوند.

سه چیزی که در انتشارهای قبلی می‌توانست لیز بخورد و مدیر را گیج کند:
  ۱. نام فایل APK با ``__version__`` برنامه یکی نباشد؛
  ۲. نسخهٔ نصب‌کنندهٔ ویندوز (``setup.iss``) عقب بماند؛
  ۳. بستهٔ رابط ویندوز بدون فایل «بازآرایی ظاهر» بسته‌بندی شود، پس کاربر
     فایل CSS جدید را نبیند و بگوید «ظاهرش که عوض نشد».
"""
import hashlib
import re
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RELEASES = ROOT / "releases"
VERSION = re.search(r'__version__\s*=\s*"([^"]+)"',
                    (ROOT / "backend" / "app" / "__init__.py").read_text(encoding="utf-8")).group(1)


def _sha_matches(path: Path) -> bool:
    side = path.with_suffix(path.suffix + ".sha256")
    if not side.exists():
        return False
    return hashlib.sha256(path.read_bytes()).hexdigest() == side.read_text().split()[0]


def test_version_is_the_single_source_of_truth_everywhere():
    """v1.0.0 build 486 — همهٔ کانال‌ها (بک‌اند، نصب‌کننده، اندروید) یک نسخه می‌گویند.

    build-484 note: the pin follows the release, exactly like the migration-head
    pin does — «بیلد ۴۸۹» = 48900. The contract is unchanged: one explicit BUILD
    file, never smaller than the semantic version's weighted code.
    """
    assert VERSION == "1.0.0", VERSION
    setup = (ROOT / "installer" / "windows" / "setup.iss").read_text(encoding="utf-8")
    assert f'#define MyAppVersion "{VERSION}"' in setup, "نسخهٔ نصب‌کنندهٔ ویندوز با بک‌اند یکی نیست"
    assert "RASA SYSTEM" in setup and "RasaSystem" in setup, "نام برند در نصب‌کننده نیست"
    # بیلد ۴۸۹ = 48900 است و کد نسخهٔ اندروید هرگز نباید از نسخهٔ معنایی عقب بماند
    build = (ROOT / "mobile-android" / "BUILD").read_text(encoding="utf-8").strip()
    assert build.isdigit() and int(build) == 48900, build
    major, minor, patch = (int(x) for x in VERSION.split("."))
    semver_code = major * 10000 + minor * 100 + patch
    assert max(int(build), semver_code) == 48900
    strings = (ROOT / "mobile-android" / "app" / "src" / "main" / "res" / "values"
               / "strings.xml").read_text(encoding="utf-8")
    assert 'name="app_name">رسا سیستم<' in strings, "نام برند اندروید به‌روز نیست"


def test_released_apk_is_the_current_version_and_signed_structure_is_sound():
    apk = RELEASES / "android" / f"RasaSystemMobile-{VERSION}.apk"
    assert apk.exists(), f"APK نسخهٔ جاری در releases/android نیست: {apk.name}"
    assert _sha_matches(apk), "فایل sha256 با محتوای APK یکی نیست"
    with zipfile.ZipFile(apk) as z:
        names = z.namelist()
        assert "AndroidManifest.xml" in names and "classes.dex" in names and "resources.arsc" in names
        assert not any(n.startswith("lib/") for n in names), "این نسخه نباید کتابخانهٔ نیتیو داشته باشد"


def test_windows_ui_bundle_carries_the_new_look():
    latest = RELEASES / "windows" / f"RasaSystemDesktopUI-{VERSION}.zip"
    assert latest.exists(), f"بستهٔ رابط نسخهٔ جاری با برند جدید ساخته نشده: {latest.name}"
    assert _sha_matches(latest), "فایل sha256 با محتوای بستهٔ رابط ویندوز یکی نیست"
    with zipfile.ZipFile(latest) as z:
        names = z.namelist()
        assert "frontend/ui-refresh.css" in names, "لایهٔ بازآرایی ظاهر در بسته نیست"
        assert "frontend/rasa-ui.css" in names, "لایهٔ طراحی v1.0.0 (RASA) در بسته نیست"
        index = z.read("frontend/index.html").decode("utf-8")
        assert 'href="ui-refresh.css"' in index and 'href="rasa-ui.css"' in index
        assert index.index("desktop.css") < index.index("ui-refresh.css"), "باید بعد از desktop.css بارگذاری شود"
        assert index.index("ui-refresh.css") < index.index("rasa-ui.css"), "rasa-ui.css باید لایهٔ آخر باشد"
        sw = z.read("frontend/sw.js").decode("utf-8")
        assert "/ui-refresh.css" in sw and "/rasa-ui.css" in sw, "کش آفلاین PWA باید لایه‌های ظاهر را داشته باشد"
        assert not any(n.endswith((".db", ".exe")) for n in names)


def test_old_desktop_bundle_stays_frozen():
    """بستهٔ ۳٫۶٫۶ یک انتشار تاریخی است و بازنویسی نمی‌شود."""
    old = RELEASES / "windows" / "SupermarketDesktopUI-3.6.6.zip"
    assert old.exists() and _sha_matches(old)
    assert hashlib.sha256(old.read_bytes()).hexdigest() == \
        "c60648813ec84df4d347fa901da0f857095b608914c0170415d63cea7061c011"


def test_android_engine_knows_the_new_expiry_timeline_and_verification():
    """نسخهٔ اندروید باید همان دو قابلیت اصلی این نسخه را داشته باشد (نه فقط نام)."""
    java = ROOT / "mobile-android" / "app" / "src" / "main" / "java" / "ir" / "khajavy" / "supermarket"
    insights = (java / "Insights.java").read_text(encoding="utf-8")
    for token in ("conservativeVelocity", "expiryPlan", "sellableNow", "write_off_waste",
                  "healthScan", "healthReport", "ADVISORY"):
        assert token in insights, token
    sales = (java / "SalesScreens.java").read_text(encoding="utf-8")
    assert "Insights.nudges" in sales, "مسیر آفلاین پیشنهاد پای صندوق روی گوشی"
    assert "applyMarkdownSteps" in (java / "Db.java").read_text(encoding="utf-8"), \
        "پیش از فروش باید پله‌های سررسیدشده اعمال شوند"
    sms = (java / "SmsLocal.java").read_text(encoding="utf-8")
    assert "renderInvoiceShort" in sms and "────" in sms, "چیدمان مرتب پیامک فاکتور روی گوشی"


def test_android_sms_templates_list_the_same_placeholders_as_the_server():
    """v4.8.0 — فهرست جای‌نگهدارها در تنظیمات گوشی باید مثل سرور باشد.

    قالب پیش‌فرض فاکتور روی سرور «{items}» گرفت (ردیف‌های مرتب کالاها) اما فهرست
    اندروید جا مانده بود؛ مدیر روی گوشی فقط {store} {invoice} {amount} {currency}
    را می‌دید و فکر می‌کرد جای ردیف کالاها خالی است.
    """
    server = (ROOT / "backend" / "app" / "services" / "sms.py").read_text(encoding="utf-8")
    java = (ROOT / "mobile-android" / "app" / "src" / "main" / "java" / "ir" / "khajavy"
            / "supermarket" / "Local.java").read_text(encoding="utf-8")
    assert '"{store} {invoice} {items} {amount} {currency}"' in java
    assert "{items}" in server


def test_pos_nudge_reason_uses_persian_digits_everywhere():
    """متن پیشنهاد صندوق روی هر سه رابط باید ارقام فارسی داشته باشد (نه «20 روز»)."""
    py = (ROOT / "backend" / "app" / "services" / "insights.py").read_text(encoding="utf-8")
    assert "_fa(c['days_left'])" in py
    router = (ROOT / "backend" / "app" / "routers" / "insights.py").read_text(encoding="utf-8")
    assert "svc._fa(alive['days_left'])" in router
    java = (ROOT / "mobile-android" / "app" / "src" / "main" / "java" / "ir" / "khajavy"
            / "supermarket" / "Insights.java").read_text(encoding="utf-8")
    assert 'fa(live.optInt("days_left"))' in java
    js = (ROOT / "frontend" / "insights.js").read_text(encoding="utf-8")
    assert "fa(n.days_left)" in js
