# -*- coding: utf-8 -*-
"""build-515 — جادوگر ۸ گامی تعریف جشنواره + شرط تعداد خرید + هدیه رایگان + دسته.

درخواست مالک: «تعریف جشنواره باید مرحله‌ای باشد نه یک فرم؛ ۷-۸ گام با انتخاب‌های
مختلف تا جشنواره‌های خیلی متنوع ساخته شود؛ مثلاً وقتی فلان‌قدر خرید شد — یا سه‌چهار
بار خرید — پاداش برای خریدِ بعدی‌اش داده شود، نه همان خرید.»

قفل‌ها:
۱) جادوگر ۸ گامی اندروید (نوع → شرط → محدوده → زمان → پاداش → تنظیمات →
   پیش‌نمایش → تایید) با نوار گام‌ها؛ ویرایش هم با همان جادوگر.
۲) شرط «تعداد خرید» (min_purchase_count) — هر دو موتور + صدور شمارشی (مضرب N).
۳) پاداش «هدیه رایگان» (GIFT): تا N عدد از کالای هدف رایگان می‌شود — هر دو موتور.
۴) هدف‌گیری «دسته» (CATEGORY) — هر دو موتور.
۵) «هدیهٔ خرید بعدی» (reward_next_only): پاداش فقط کوپنِ خرید بعدی است.
"""
from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
import app as _app  # noqa: E402

VERSION = _app.__version__

ANDROID = ROOT / "mobile-android/app/src/main/java/ir/khajavy/supermarket"
LOCAL = (ANDROID / "Local.java").read_text("utf-8")
SALES = (ANDROID / "SalesScreens.java").read_text("utf-8")
DBJ = (ANDROID / "Db.java").read_text("utf-8")
MOBILE_PY = (ROOT / "backend/app/routers/mobile.py").read_text("utf-8")
QT_NAV = (ROOT / "desktop/main_window.py").read_text("utf-8")


# ---------------------------------------------------------------- جادوگر UI
def test_wizard_is_eight_steps_with_stepper():
    assert "void campaignWizard(JSONObject cp)" in SALES
    for step in ["wStepKind", "wStepCond", "wStepScope", "wStepTime",
                 "wStepReward", "wStepExtras", "wStepReview", "wStepDone"]:
        assert f"void {step}()" in SALES, f"گام {step} در جادوگر"
    assert "for (int i = 1; i <= 8; i++) head.addView(wDot(i, wStep));" in SALES, "نوار گام‌های ۱ تا ۸"
    assert "\"مرحلهٔ بعد\"" in SALES and "\"بازگشت\"" in SALES
    # فرم قدیمی حذف شده باشد (یک مسیر، نه دو)
    assert "void campaignForm(" not in SALES


def test_wizard_choices_match_mockup():
    # گام ۱ — چهار نوع مثل موکاپ
    for opt in ["هدیهٔ خرید بعدی", "تخفیف درصدی", "تخفیف مبلغی", "هدیه رایگان"]:
        assert opt in SALES
    # گام ۲ — شرط مبلغ یا تعداد
    assert "\"مبلغ خرید\"" in SALES and "\"تعداد خرید\"" in SALES
    # گام ۳ — همه/دسته/کالا + گام ۴ — بدون محدودیت/تاریخ/مدت
    assert "همهٔ محصولات" in SALES and "دسته‌های خاص" in SALES and "محصولات مشخص" in SALES
    assert "بدون محدودیت زمانی" in SALES and "تاریخ مشخص" in SALES and "مدت زمان" in SALES


def test_wizard_review_and_done():
    assert "\"پیش‌نمایش و تایید\"" in SALES and "مشاهدهٔ جشنواره‌ها" in SALES
    assert "ایجاد جشنوارهٔ جدید" in SALES


# ---------------------------------------------------------------- شرط تعداد خرید
def test_purchase_count_condition_both_engines():
    assert "min_purchase_count INTEGER NOT NULL DEFAULT 0" in DBJ
    assert "این جشنواره از خرید شمارهٔ" in LOCAL, "رد صادقانه با شمارهٔ خرید فعلی"
    assert "CAMPAIGN_PURCHASE_COUNT" in (ROOT / "backend/app/services/coupons.py").read_text("utf-8")
    # صدور شمارشی: مضرب N → کوپن خرید بعدی
    assert "SELECT * FROM campaigns WHERE status='ACTIVE' AND min_purchase_count>0" in LOCAL
    # سینک سرور → گوشی فیلد جدید را می‌آورد
    assert '"min_purchase_count"' in MOBILE_PY


def test_next_purchase_reward_not_discount_now():
    assert "reward_next_only" in (ROOT / "backend/app/models/marketing.py").read_text("utf-8")
    assert "CAMPAIGN_NEXT_REWARD" in (ROOT / "backend/app/services/coupons.py").read_text("utf-8")
    assert "پاداش این جشنواره کوپن خرید بعدی است" in LOCAL


# ---------------------------------------------------------------- هدیه رایگان + دسته
def test_gift_reward_engine_backend(client, auth_headers):
    """ساخت با API واقعی (اعتبارسنجی اسکیما) + ارزیابی موتور سرور."""
    h = auth_headers
    cat = client.post("/api/products/categories", headers=h, json={"name": "نوشیدنی۵۱۵"})
    assert cat.status_code in (200, 201), cat.text
    pr = client.post("/api/products", headers=h, json={"barcode": "515000000001", "name": "نوشابهٔ هدیه", "category_id": cat.json()["id"]})
    assert pr.status_code in (200, 201), pr.text
    gift_id = pr.json()["id"]
    cr = client.post("/api/marketing/campaigns", headers=h, json={
        "name": "دو تا بخرد یکی رایگان", "discount_type": "GIFT", "discount_value": 1,
        "target_type": "PRODUCTS", "target_ids": [gift_id]})
    assert cr.status_code in (200, 201), cr.text
    cid = cr.json()["id"]
    from app.database import SessionLocal
    from app.services.coupons import CampaignError, evaluate_campaign
    from decimal import Decimal

    db = SessionLocal()
    try:
        # کالای هدیه در سبد → همان خط رایگان
        ev = evaluate_campaign(db, campaign_id=cid, amount=Decimal("40000"),
                               product_ids=[gift_id], line_amounts={gift_id: Decimal("40000")},
                               line_qtys={gift_id: Decimal("2")})
        assert ev["discount"] == Decimal("20000") and "رایگان" in ev["gift_note"]
        # کالای هدیه در سبد نیست → پیام دقیق
        with pytest.raises(CampaignError) as err:
            evaluate_campaign(db, campaign_id=cid, amount=Decimal("90000"),
                              product_ids=[999999], line_amounts={999999: Decimal("90000")})
        assert "کالای هدیه در سبد نیست" in err.value.message
    finally:
        db.close()


def test_category_target_engine_backend(client, auth_headers):
    h = auth_headers
    cat = client.post("/api/products/categories", headers=h, json={"name": "لبنیات۵۱۵"})
    assert cat.status_code in (200, 201), cat.text
    pr = client.post("/api/products", headers=h, json={"barcode": "515000000002", "name": "شیر ۵۱۵", "category_id": cat.json()["id"]})
    assert pr.status_code in (200, 201), pr.text
    milk_id = pr.json()["id"]
    cr = client.post("/api/marketing/campaigns", headers=h, json={
        "name": "۵٪ دسته لبنیات", "discount_type": "PERCENT", "discount_value": 5,
        "target_type": "CATEGORY", "target_ids": ["لبنیات۵۱۵"]})
    assert cr.status_code in (200, 201), cr.text
    cid = cr.json()["id"]
    from app.database import SessionLocal
    from app.services.coupons import CampaignError, evaluate_campaign
    from decimal import Decimal

    db = SessionLocal()
    try:
        ev = evaluate_campaign(db, campaign_id=cid, amount=Decimal("100000"),
                               product_ids=[milk_id], line_amounts={milk_id: Decimal("100000")},
                               line_qtys={milk_id: Decimal("1")})
        assert ev["discount"] == Decimal("5000") and ev["scope_amount"] == Decimal("100000")
    finally:
        db.close()


# ---------------------------------------------------------------- سیم‌کشی POS اندروید
def test_android_pos_request_carries_lines_for_new_rules():
    assert "line_qtys" in SALES and "line_categories" in SALES, "تعداد و دستهٔ هر خط سبد"
    assert "SELECT category FROM bank WHERE barcode=? LIMIT 1" in SALES
    # موتور محلی: هدف دسته‌ای + پاداش GIFT
    assert '"CATEGORY".equalsIgnoreCase(campaign.optString("target_type", "ALL"))' in LOCAL
    assert '"GIFT".equalsIgnoreCase(campaign.optString("discount_type", "PERCENT"))' in LOCAL
    assert "عدد رایگان" in LOCAL


def test_version_pins_and_migration():
    mg = (ROOT / "backend/app/routers/marketing.py").read_text("utf-8")
    assert "GIFT" in mg and "CATEGORY" in mg, "اسکیمای ساخت/ویرایش جشنواره"
    assert "min_purchase_count" in mg and "reward_next_only" in mg
    mig = list((ROOT / "backend/alembic/versions").glob("*build515_campaign_wizard.py"))
    assert mig, "مایگریشن build-515"
    assert f"?v={VERSION}" in (ROOT / "frontend/index.html").read_text("utf-8")
