# -*- coding: utf-8 -*-
"""build-514 — «کوپن خرید بعدی برای جشنوارهٔ اعمال‌شده ساخته نمی‌شود» + گزارش جشنواره + تصویر انبار.

از گزارش مالک (v1.0.513): «جشنواره خودکار شناسایی می‌شود ولی کوپن تخفیف برای
مشتری ایجاد نمی‌شود، نه روی فاکتور می‌آید نه پیام جدا می‌رود؛ گزارش عملکرد هر
جشنواره (چند بار استفاده، چند کوپن، چقدر مصرف) در بخش جشنواره‌ها باشد؛ تصاویر
در انبار نمی‌آید و باید یک‌بار ذخیره محلی شوند.»

قفل‌های این نسخه:
۱) صدور کوپن خرید بعدی دو منبع دارد: آستانه‌دارِ رسیده + جشنوارهٔ اعمال‌شده روی
   همان فاکتور (حتی بدون آستانه) — مختص مشتریِ همان فاکتور، با کد روی فاکتور
   و پیامک جدا.
۲) گزارش هر جشنواره: استفاده/سقف/کوپن صادره/مجموع تخفیف/آخرین استفاده — ردیف
   لیست اندروید (لمس طولانی = شیت گزارش) و صفحهٔ نیتیو «جشنواره‌ها» در ویندوز.
۳) تصویر انبار از بانک کالا هم fallback می‌شود؛ بارگیری یک‌بار در files/thumbs
   کش می‌شود (پایپ‌لاین Images از قبل؛ با دادهٔ بانک حالا واقعاً دیده می‌شود).
۴) بستهٔ پرتابل ویندوز باید پکیج desktop/ را داشته باشد (رفع نبودِ رابط نیتیو).
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
import app as _app  # noqa: E402
from tests.release_gate import require_artifact  # noqa: E402

VERSION = _app.__version__
BUILD = _app.BUILD

ANDROID = ROOT / "mobile-android/app/src/main/java/ir/khajavy/supermarket"
LOCAL = (ANDROID / "Local.java").read_text("utf-8")
SALES = (ANDROID / "SalesScreens.java").read_text("utf-8")
STOCK = (ANDROID / "StockScreens.java").read_text("utf-8")
DBJ = (ANDROID / "Db.java").read_text("utf-8")
IMG = (ANDROID / "Images.java").read_text("utf-8")
QT_NAV = (ROOT / "desktop/main_window.py").read_text("utf-8")
QT_CAMP = (ROOT / "desktop/screens/campaigns.py").read_text("utf-8")


def test_reward_coupon_for_applied_campaign_even_without_threshold():
    assert 'picked.put(campaign.optLong("id"), campaign);' in LOCAL
    assert 'if (appliedId > 0) {' in LOCAL and 'WHERE id=? OR pc_id=?' in LOCAL, \
        "جشنوارهٔ اعمال‌شده روی فاکتور باید منبع صدور باشد (حتی بدون آستانه)"
    assert "دو منبع صدور کوپن خرید بعدی" in LOCAL


def test_campaign_performance_report_android():
    assert "void campaignReport(JSONObject cp" in SALES, "شیت گزارش جشنواره"
    assert "setOnLongClickListener(v -> { campaignReport(cp" in SALES
    assert "کوپن خرید بعدی صادرشده" in SALES and "مجموع تخفیف داده‌شده" in SALES
    assert "آخرین استفاده" in SALES and "دفعات استفاده" in SALES
    assert "static int countWhere(String table" in LOCAL
    assert "static double sumInvoices(String column" in LOCAL
    assert "static String lastInvoiceUse(long campaignId)" in LOCAL
    # خود ردیف لیست هم اعداد را دارد
    assert "کوپن صادره " in SALES and "تخفیف داده‌شده " in SALES


def test_inventory_image_from_bank_and_disk_cache():
    assert "IFNULL(NULLIF(p.image_url,''), IFNULL((SELECT bk.image_url FROM bank bk" in DBJ, \
        "تصویر انبار باید از بانک کالا هم بیفتد"
    assert "files/thumbs" in IMG, "کش محلی تصاویر (بارگیری فقط یک‌بار)"
    assert "new File(thumbDir(c), Integer.toHexString(url.hashCode()) + \".jpg\")" in IMG


def test_windows_native_campaigns_page():
    assert "class CampaignsPage(QWidget)" in QT_CAMP
    assert "کوپن صادره" in QT_CAMP and "مجموع تخفیف داده‌شده" in QT_CAMP
    assert "Invoice.benefit_amount" in QT_CAMP
    assert '"جشنواره‌ها", CampaignsPage(ctx)' in QT_NAV, "صفحه در ناوبری ویندوز"


def test_portable_carries_native_desktop_package():
    import zipfile
    zp = require_artifact(ROOT / "releases/windows" / f"RasaSystem-Windows-Portable-{VERSION}.zip")
    with zipfile.ZipFile(zp) as z:
        names = set(z.namelist())
    assert "desktop/main.py" in names, "پرتابل باید پکیج desktop/ را داشته باشد (رابط نیتیو)"
    assert "desktop/screens/campaigns.py" in names


def test_version_pins_current():
    web = (ROOT / "frontend/app.js").read_text("utf-8")
    idx = (ROOT / "frontend/index.html").read_text("utf-8")
    assert f"const UI_BUILD = {BUILD // 100};" in web
    assert f"?v={VERSION}" in idx
