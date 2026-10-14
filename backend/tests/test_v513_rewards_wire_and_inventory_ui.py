# -*- coding: utf-8 -*-
"""build-513 — «کوپن خرید بعدی برای جشنوارهٔ خودکار صادر نمی‌شود» + انبار تصویری + جست‌وجوی نام.

از اسکرین‌شات مالک (شیت دلایل) مشخص شد جشنواره‌های او واقعاً «پایان‌شان» گذشته و
چکِ «خودکار» جلوی دیدن دلیل واقعی را می‌گرفت؛ صدور کوپن هم به‌خاطر همان بازه،
بی‌صدا رد می‌شد. قفل‌های این نسخه:
۱) ترتیب تشخیص: اول موانع واقعی (بازه/حداقل/سقف/اولین‌خرید)، «خودکار» آخر — هر دو سکو.
۲) تاریخِ خالی/ناقابل‌تجزیه هرگز «گذشته» تلقی نمی‌شود (قاعدهٔ امن windowKey).
۳) صدور بی‌صدا ممنوع: رد شدن صدور در دفتر حسابرسی ثبت می‌شود (COUPON_ISSUE_SKIP).
۴) مسیر جفت‌شدهٔ آنلاین هم صدور را اجرا می‌کند (قبلاً فقط مسیر موتور محلی).
۵) انبار و موجودی: تصویر + دسته (بانک کالا) + جست‌وجوی نام/بارکد.
۶) ورود کالا: جست‌وجوی نام کنار اسکن بارکد (آفلاین).
۷) بک‌اند: category_name در خروجی کالا + ترتیب rejections.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
import app as _app  # noqa: E402

VERSION = _app.__version__
BUILD = _app.BUILD

ANDROID = ROOT / "mobile-android/app/src/main/java/ir/khajavy/supermarket"
LOCAL = (ANDROID / "Local.java").read_text("utf-8")
SALES = (ANDROID / "SalesScreens.java").read_text("utf-8")
STOCK = (ANDROID / "StockScreens.java").read_text("utf-8")
DB = (ANDROID / "Db.java").read_text("utf-8")
QT = (ROOT / "desktop/screens/products.py").read_text("utf-8")
SVC = (ROOT / "backend/app/services/coupons.py").read_text("utf-8")


def test_issue_skip_is_never_silent_and_windows_are_safe():
    assert "COUPON_ISSUE_SKIP" in LOCAL, "رد شدن صدور باید در حسابرسی بیاید"
    assert "تاریخ «پایان» را تمدید کنید" in LOCAL, "دلیل باید اقدام‌پذیر باشد"
    # قاعدهٔ امن: تاریخ خراب = بدون محدودیت، نه «گذشته»
    assert "ناقابل‌تجزیه = بدون محدودیت" in LOCAL
    assert "windowKey(String value)" in LOCAL


def test_picker_order_real_blockers_first_both_engines():
    # اندروید: چک خودکار باید بعد از قضاوت تخفیف (آخر) بیاید
    aa = LOCAL.index('pickerExclude = !request.optBoolean("include_auto_apply"')
    dd = LOCAL.index('if (discount <= 0 || !Double.isFinite(discount))')
    pe = LOCAL.index('if (pickerExclude) {')
    assert aa < dd < pe, "«خودکار» باید بعد از موانع واقعی تفسیر شود"
    # بک‌اند: همین ترتیب
    svc_aa = SVC.index('if not include_auto_apply and c.auto_apply:')
    svc_ev = SVC.index('ev = evaluate_campaign(')
    assert svc_ev < svc_aa, "بک‌اند هم باید اول واقعی‌ها را بگوید"
    assert "خودکار اعمال می‌شود و در فهرست انتخاب نمی‌آید" in SVC


def test_both_checkout_paths_issue_rewards():
    assert 'issueLocalAutoCoupons(saleRow, no, total);' in LOCAL, "مسیر موتور محلی"
    assert 'Local.issueLocalAutoCoupons(saleRow, no, total);' in SALES, \
        "مسیر جفت‌شدهٔ آنلاین (Db.localSale) هم باید صدور را اجرا کند"


def test_inventory_images_category_and_search():
    assert "bk.category FROM bank bk" in DB, "دسته از بانک کالا"
    assert '"image_url", c.getString(6)' in DB
    assert "Ui.pitem(c, thumbSrc" in STOCK, "انبار باید کاشی تصویری داشته باشد"
    assert "دسته: " in STOCK
    assert "جست‌وجوی نام یا بارکد…" in STOCK, "جست‌وجو در انبار"
    assert "void searchProduct()" in STOCK, "جست‌وجوی نام در ورود کالا"
    assert "بارکد یا نام کالا…" in STOCK


def test_windows_native_category_image_and_search():
    assert '"دسته"' in QT, "ستون دسته در جدول ویندوز"
    assert "_local_icon(product.image_url)" in QT, "تصویر محلی در جدول ویندوز"
    assert 'setPlaceholderText("جست‌وجو…")' in QT, "جست‌وجوی نام/بارکد در ویندوز"


def test_backend_product_out_has_category_name(client, auth_headers):
    h = auth_headers
    cat = client.post("/api/products/categories", headers=h, json={"name": "لبنیات ۵۱۳"})
    assert cat.status_code in (200, 201), cat.text
    cid = cat.json()["id"]
    pr = client.post("/api/products", headers=h, json={"barcode": "6265130000001", "name": "شیر ۵۱۳", "category_id": cid})
    assert pr.status_code in (200, 201), pr.text
    pid = pr.json()["id"]
    got = client.get(f"/api/products/{pid}", headers=h).json()
    assert got.get("category_name") == "لبنیات ۵۱۳", got.get("category_name")


def test_rejections_put_real_reason_first(client, auth_headers):
    h = auth_headers
    client.post("/api/marketing/campaigns", headers=h, json={
        "name": "خودکارِ دست‌نیافتنی ۵۱۳", "discount_type": "PERCENT", "discount_value": 5,
        "min_purchase": 900_000_000, "auto_apply": True})
    el = client.post("/api/pos/campaigns/eligible", headers=h,
                     json={"amount": 10_000, "product_ids": [], "include_auto_apply": False})
    assert el.status_code == 200, el.text
    data = el.json()
    row = next((x for x in data.get("rejections", []) if x["name"] == "خودکارِ دست‌نیافتنی ۵۱۳"), None)
    assert row is not None, "جشنواره باید در فهرست دلایل باشد"
    assert "خودکار" not in row["reason"], f"دلیل واقعی نباید پشت «خودکار» پنهان شود: {row}"
    assert "حداقل خرید" in row["reason"] or "شرایط" in row["reason"], row


def test_version_pins_current():
    web = (ROOT / "frontend/app.js").read_text("utf-8")
    idx = (ROOT / "frontend/index.html").read_text("utf-8")
    assert f"const UI_BUILD = {BUILD // 100};" in web
    assert f"?v={VERSION}" in idx
