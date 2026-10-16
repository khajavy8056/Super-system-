# -*- coding: utf-8 -*-
"""build-516 — «دکمهٔ مرحلهٔ بعد نیست» + پیشرفت خرید مشتری + شمارش در بازهٔ جشنواره.

از گزارش مالک (اسکرین‌شات واقعی گام ۲ جادوگر):
۱) «مرحلهٔ ۱ دکمهٔ ادامه دارد، مرحلهٔ ۲ به بعد ندارد» — ریشه: دکمه‌های Ui.btn
   عرض match_parent می‌گیرند؛ در ردیف ناوبری، «بازگشت» تمام عرض را می‌خورد و
   «مرحلهٔ بعد» از ردیف بیرون می‌زد. اصلاح ساختاری: هر دو دکمه عرض‌۰ + وزن.
۲) «هر انتخابی که می‌شود باید ارتباطش فراهم باشد و همان‌طور که در واقعیت باید
   عمل کند، خودکار اجرا شود» — هدیه رایگان همیشه به کالای هدف گره می‌خورد.
۳) «هرجا تعداد خرید مهم است، خریدها برای مشتری قشنگ مشخص باشد در مدت زمان
   مشخص و بعد از رسیدن به حد، توکن تولید و ارسال شود»:
   - شمارش خریدها داخل بازهٔ خود جشنواره (از/تا) — هر دو موتور؛
   - پیشرفت روی رسید («خرید ۲ از ۳») + کارت «پیشرفت جشنواره‌ها» در پروندهٔ مشتری؛
   - پیامک صادرشده دلیل دوره را می‌گوید («بابت N خرید شما 🎁»).
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
BACKEND = (ROOT / "backend/app/services/coupons.py").read_text("utf-8")


def test_wizard_nav_buttons_always_visible():
    # ریشهٔ باگ: عرض match_parent در ردیف افقی — باید وزن‌دار شده باشند
    assert "back.setLayoutParams(wNavLp(1f));" in SALES
    assert "next.setLayoutParams(wNavLp(wStep > 1 ? 1.4f : 1f));" in SALES
    assert "android.widget.LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, weight)" in SALES
    # هر دو دکمه در همان ردیف nav اضافه می‌شوند
    assert '"مرحلهٔ بعد"' in SALES and '"بازگشت"' in SALES
    assert "ریشهٔ «دکمهٔ ادامه نیست" in SALES, "توضیح ریشه‌ای باگ کنار کد"
    # مسیرهای قدیمی خطرناک دیگر در ناوبری نباشند
    assert "nav.addView(Ui.ghost(" not in SALES and "nav.addView(Ui.primary(" not in SALES


def test_gift_is_always_tied_to_target_product():
    assert 'if ("GIFT".equals(k)) scope = "PRODUCTS";' in SALES


def test_purchase_count_is_windowed_and_visible():
    # هلپر بازه‌ای در اندروید
    assert "static int countPurchases(long customerId, String fromIso, String untilIso)" in LOCAL
    assert "AND created_at>=?" in LOCAL and "AND created_at<=?" in LOCAL
    # موتور و صدور هر دو از شمارش بازه‌ای استفاده می‌کنند
    assert LOCAL.count('countPurchases(customerId, campaign.optString("valid_from", ""), campaign.optString("valid_until", ""))') >= 2
    # بک‌اند: شمارش داخل بازهٔ جشنواره
    assert "campaign: Campaign | None = None" in BACKEND
    assert "q.where(Invoice.created_at >= campaign.valid_from)" in BACKEND
    assert "_customer_purchase_count(db, customer_id, campaign)" in BACKEND
    # دیده‌شدن پیشرفت: رسید + پروندهٔ مشتری + دلیل در پیامک
    assert '"خرید " + Ui.fa(String.valueOf(inCycle)) + " از "' in LOCAL, "پیشرفت روی رسید"
    assert '"پیشرفت جشنواره‌ها"' in SALES, "کارت پیشرفت در پروندهٔ مشتری"
    assert "خرید دیگر تا کوپن هدیه" in SALES
    assert '"issue_note"' in LOCAL and "بابت " in LOCAL, "دلیل دوره در پیامک"


def test_windowed_count_backend_behaviour(client, auth_headers):
    """فقط خریدهای داخل بازهٔ جشنواره شمرده می‌شوند — نه کل سابقه."""
    import datetime as dt

    from app.database import SessionLocal
    from app.models import Campaign, Customer, Invoice
    from app.services.coupons import CampaignError, evaluate_campaign

    cr = client.post("/api/customers", headers=auth_headers, json={"name": "مشتری ۵۱۶", "phone": "09160000051"})
    assert cr.status_code in (200, 201), cr.text
    cid = cr.json()["id"]

    def mk_campaign(name, valid_from, valid_until="2099-01-01T00:00:00"):
        r = client.post("/api/marketing/campaigns", headers=auth_headers, json={
            "name": name, "discount_type": "PERCENT", "discount_value": 5,
            "min_purchase_count": 2,
            "valid_from": valid_from, "valid_until": valid_until})
        assert r.status_code in (200, 201), r.text
        return r.json()["id"]

    old_id = mk_campaign("دورهٔ قدیمی", "2020-01-01T00:00:00")
    fresh_id = mk_campaign("دورهٔ تازه", "2090-01-01T00:00:00")

    db = SessionLocal()
    try:
        # یک خرید داخل بازهٔ هر دو جشنواره (۱۲۳۴) — یک خرید قبل از «دورهٔ تازه» (۲۰۲۰)
        for year in (2020, 2090):
            db.add(Invoice(invoice_number=f"516-{year}", customer_id=cid, status="PAID",
                           subtotal=Decimal("0"), discount=Decimal("0"), invoice_discount=Decimal("0"),
                           tax=Decimal("0"), total_amount=Decimal("100000"),
                           payment_method="CASH", created_at=dt.datetime(year, 6, 1, 12, 0)))
        db.commit()
        # «دورهٔ قدیمی»: خرید ۲۰۲۰ + ۲۰۹۰ شمرده می‌شود → done=1، خرید جاری = ۲ → مجاز
        ev = evaluate_campaign(db, campaign_id=old_id, amount=Decimal("100000"), customer_id=cid)
        assert ev["min_purchase_count"] == 2
        # «دورهٔ تازه»: فقط خرید ۲۰۹۰ شمرده می‌شود → done=1 → همین خرید دوم است → مجاز
        # (خرید ۲۰۲۰ بیرون بازه است) — برای اثبات، یک خرید ۲۰۹۰ دیگر می‌سازیم که done=1 بماند:
        with pytest.raises(CampaignError) as err:
            # بازهٔ ۲۰۲۶→۲۰۲۷ هیچ‌کدام از دو خرید (۲۰۲۰ و ۲۰۹۰) را نمی‌گیرد:
            strict_id = mk_campaign("سخت‌گیر", "2026-01-02T00:00:00", "2027-01-01T00:00:00")
            evaluate_campaign(db, campaign_id=strict_id, amount=Decimal("100000"), customer_id=cid)
        assert "از خرید شمارهٔ" in err.value.message, "خرید بیرونِ بازه نباید شمرده شود"
    finally:
        db.close()


def test_customer_progress_card_and_receipt_line_anchors():
    # پروندهٔ مشتری: شمارش با پنجرهٔ همان جشنواره + «X از N»
    assert "Local.countPurchases(id, cnp.optString(\"valid_from\", \"\"), cnp.optString(\"valid_until\", \"\"))" in SALES
    assert "Ui.fa(String.valueOf(inCycle)) + \" از \" + Ui.fa(String.valueOf(n2))" in SALES
    # رسید: همان پیشرفت با «خرید X از N»
    assert '"جشنواره " + cnp.optString("name"), "خرید "' in LOCAL


def test_version_pins():
    assert VERSION == "1.0.521" and _app.BUILD == 52100
    assert (ROOT / "mobile-android/BUILD").read_text().strip() == "52100"
    web = (ROOT / "frontend/app.js").read_text("utf-8")
    assert "const UI_BUILD = 521;" in web
    assert f"?v={VERSION}" in (ROOT / "frontend/index.html").read_text("utf-8")
