# -*- coding: utf-8 -*-
"""build-511 — «جشنوارهٔ ۱۰ میلیونی روی گوشی هیچ کاری نمی‌کند» + تحلیل جشنواره‌ها.

ریشه‌های این نسخه که این تست‌ها برای همیشه قفل می‌کنند:
۱) موتور آفلاین اندروید جشنواره‌های محلیِ ساخته‌شده روی گوشی را در حالت جفت‌شده
   از صلاحیت و صدور کوپن حذف می‌کرد (`localCampaign && !standalone → skip`) —
   عامل پیام «جشنوارهٔ متناسب با این سبد وجود ندارد» و «هیچ اتفاقی نمی‌افتد».
۲) ویرایش جشنواره روی اندروید وجود نداشت — حالا فرم واحد ساخت/ویرایش + PATCH کامل.
۳) «همه‌چیزش باید مشخص باشد با نمودار و جدول» — /marketing/stats حالا
   campaigns_detail (استفاده/کوپن صادره/تخفیف/آخرین استفاده) + redemptions_by_day.
۴) صفحهٔ ورود وب: ورودی‌ها name نداشتند → ذخیرهٔ رمز گوگل کار نمی‌کرد؛ و
   شناسنامهٔ نسخهٔ رابط/بک‌اند باید روی خود صفحهٔ ورود دیده شود.
۵) نوار پرفروش‌ها هنگام خطا بی‌صدا حذف می‌شد → حالا با دلیل دیده می‌شود.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app as _app  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
VERSION = _app.__version__
BUILD = _app.BUILD

ANDROID = ROOT / "mobile-android/app/src/main/java/ir/khajavy/supermarket"
LOCAL = (ANDROID / "Local.java").read_text("utf-8")
SALES = (ANDROID / "SalesScreens.java").read_text("utf-8")
WEB = (ROOT / "frontend/app.js").read_text("utf-8")
IDX = (ROOT / "frontend/index.html").read_text("utf-8")


def test_paired_mode_no_longer_skips_phone_campaigns():
    assert "if (localCampaign != Api.standalone()) continue;" not in LOCAL, \
        "صدور کوپن نباید بر اساس حالت جفت/مستقل جشنواره را حذف کند"
    assert "if (localCampaign && !Api.standalone()) continue;" not in LOCAL, \
        "ریشهٔ «جشنوارهٔ متناسب با این سبد وجود ندارد»: فیلتر جشنوارهٔ محلی در حالت جفت‌شده باید حذف شده باشد"
    assert "جشنوارهٔ متناسب با این سبد وجود ندارد" in LOCAL


def test_android_campaign_edit_and_usage_visible():
    # build-515 — ویرایش با جادوگر ۸ گامی (فرم قدیمی حذف شد)
    assert "void campaignWizard(JSONObject cp)" in SALES, "جادوگر گام‌به‌گام ساخت/ویرایش جشنواره"
    assert "patch(\"/marketing/campaigns/\" + wEdit.optLong(\"id\"), req" in SALES, "ذخیرهٔ ویرایش با PATCH"
    assert "استفاده " in SALES and "بار" in SALES, "تعداد استفاده در فهرست جشنواره‌ها"
    assert "static String trimNum(double v)" in SALES
    # PATCH محلی: همهٔ فیلدها از طریق هلپر واحد
    assert "private static ContentValues campaignValues(JSONObject b)" in LOCAL
    assert 'audit("CAMPAIGN_UPDATE"' in LOCAL, "ویرایش باید در دفتار حسابرسی بیاید"


def test_marketing_stats_exposes_campaign_analytics(client, auth_headers):
    body = {"name": "تحلیلی ۵۱۱", "discount_type": "PERCENT", "discount_value": 10,
            "auto_issue_threshold": 10_000_000, "auto_issue_validity_days": 30}
    r = client.post("/api/marketing/campaigns", headers=auth_headers, json=body)
    assert r.status_code == 201, r.text
    camp = r.json()
    s = client.get("/api/marketing/stats", headers=auth_headers)
    assert s.status_code == 200, s.text
    data = s.json()
    detail = [c for c in data.get("campaigns_detail", []) if c["id"] == camp["id"]]
    assert detail, "آمار باید برای هر جشنواره ردیف داشته باشد"
    row = detail[0]
    for key in ("used_count", "issued_coupons", "redeemed_value", "last_used", "status", "usage_limit"):
        assert key in row, f"ستون تحلیلی {key} باید باشد"
    assert isinstance(data.get("redemptions_by_day"), list)


def test_login_page_carries_name_attributes_and_build_identity():
    assert 'name="username"' in IDX and 'name="password"' in IDX, \
        "بدون name، ذخیرهٔ رمز در گوگل/مرورگر فعال نمی‌شود"
    assert 'id="login-build"' in IDX, "شناسنامهٔ نسخه روی صفحهٔ ورود"
    assert "/system/health" in WEB and "بک‌اند نصب‌شده قدیمی است" in WEB, \
        "صفحهٔ ورود باید نسخهٔ واقعی بک‌اند را نشان دهد و ناسازگاری را هشدار دهد"


def test_fast_movers_visible_on_error():
    assert "نمایش پرفروش‌ها به بک‌اند جدید نیاز دارد" in WEB, \
        "خطا نباید نوار پرفروش‌ها را بی‌صدا حذف کند"
    assert 'id="mk-campaign-chart"' in WEB and "مصرف جشنواره‌ها" in WEB, "نمودار مصرف جشنواره‌ها در بازاریابی"


def test_version_pins_are_current():
    assert f"?v={VERSION}" in IDX, "پین نسخهٔ پوسته باید با انتشار یکی باشد"
    assert f"const UI_BUILD = {BUILD // 100};" in WEB


def test_windows_portable_package_is_complete_system():
    """پایانِ «تنها دارایی ویندوزی، رونویسی UI بود»: بستهٔ پرتابل باید کل سیستم را بدهد."""
    import zipfile
    zp = ROOT / "releases/windows" / f"RasaSystem-Windows-Portable-{VERSION}.zip"
    assert zp.exists(), f"بستهٔ پرتابل {zp.name} ساخته نشده"
    with zipfile.ZipFile(zp) as z:
        names = set(z.namelist())
        run = z.read("RUN.bat").decode("utf-8")
        app_js = z.read("frontend/app.js").decode("utf-8")
    for must in ("RUN.bat", "backend/app/main.py", "backend/requirements-desktop.txt",
                 "installer/windows/run_supermarket.py", "frontend/index.html",
                 "backend/alembic/env.py", "README-WINDOWS.fa.md",
                 "desktop/main.py", "desktop/screens/pos.py"):
        assert must in names, f"بستهٔ پرتابل فاقد {must}"
    assert "run_supermarket.py" in run and "requirements-desktop.txt" in run
    assert f"const UI_BUILD = {BUILD // 100};" in app_js, "پرتابل، رابط کهنه را بسته!"
    # نباید بستهٔ آزمون داخل پرتابل باشد (حجم/اطلاعات داخلی)
    assert not any(n.startswith("backend/tests") for n in names)
