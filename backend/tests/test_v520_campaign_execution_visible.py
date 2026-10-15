# -*- coding: utf-8 -*-
"""build-520 — «جشنواره عمل نمی‌کند» ریشه‌ای:

۱) جشنوارهٔ «خودکار» دیگر از فهرست صندوق‌دار حذف نمی‌شود (قبلاً صندوق‌دار
   هیچ نمی‌دید و فکر می‌کرد جشنواره کار نمی‌کند).
۲) جشنواره‌های «هدیهٔ خرید بعدی» و «هر N خرید» بنر «کد هدیه در راه است»
   می‌گیرند — از خودِ جدول جشنواره‌ها، نه از لیست ردشده‌ها.
۳) اعلان واضح «جشنوارهٔ … خودکار اعمال شد» در سبد.
"""
import pathlib

BASE = pathlib.Path(__file__).resolve().parents[2]
LOCAL = (BASE / "mobile-android/app/src/main/java/ir/khajavy/supermarket/Local.java").read_text("utf-8")
SALES = (BASE / "mobile-android/app/src/main/java/ir/khajavy/supermarket/SalesScreens.java").read_text("utf-8")
COUPONS = (BASE / "backend/app/services/coupons.py").read_text("utf-8")


def test_android_auto_campaign_stays_in_picker():
    assert "pickerExclude" not in LOCAL, "حذف خودکار از فهرست = «صندوق‌دار نمی‌تواند انتخاب کند»"
    assert "جشنوارهٔ خودکار هم در فهرست صندوق‌دار می‌آید" in LOCAL
    # درخواست فهرست دیگر include_auto_apply=false نمی‌فرستد
    assert 'request.put("include_auto_apply", false)' not in SALES


def test_gift_banner_from_campaign_table_both_engines():
    # اندروید: هینت از جدول (reward_next_only=0) + شمارش تا N
    assert "SELECT * FROM campaigns WHERE status='ACTIVE' AND reward_next_only=0" in LOCAL
    assert "با این خرید کوپن صادر می‌شود" in LOCAL
    assert "countPurchases((long) optFin(b, \"customer_id\", 0)" in LOCAL
    # سرور: همان بنر برای min_purchase_count با customer_id
    assert "Campaign.min_purchase_count > 0" in COUPONS
    assert "با این خرید کوپن صادر می‌شود" in COUPONS


def test_cart_shows_gift_banner_and_auto_toast():
    # قرص «🎁 کد هدیه» در نوار سبد
    assert '"🎁 کد هدیه"' in SALES
    assert "giftHint" in SALES
    # اعلان اعمال خودکار + خوانا با مبلغ
    assert "خودکار اعمال شد (−" in SALES
    # بنر از issue_on_checkout خوانده می‌شود
    assert 'response.optJSONArray("issue_on_checkout")' in SALES


def test_gift_banner_excludes_gift_and_inactive():
    # هدیهٔ رایگان (GIFT) بنر کوپن نمی‌گیرد — جایزه‌اش کالای رایگان است
    seg = LOCAL[LOCAL.index("java.util.HashSet<Long> hinted"):]
    seg = seg[:seg.index("            if (hints.length() > 0)")]
    assert '"GIFT".equalsIgnoreCase(c.optString("discount_type"))' in seg
    assert "reward_next_only=0" in seg


def test_count_banner_fires_end_to_end_api(client, auth_headers):
    """هر N خرید: با رسیدن به خرید Nاُم، issue_on_checkout بنر «با این خرید کوپن صادر می‌شود» می‌دهد."""
    import datetime as dt
    from decimal import Decimal

    from app.database import SessionLocal
    from app.models import Customer, Invoice

    cr = client.post("/api/customers", headers=auth_headers, json={"name": "مشتری ۵۲۰", "phone": "09160000052"})
    assert cr.status_code in (200, 201), cr.text
    cid = cr.json()["id"]

    r = client.post("/api/marketing/campaigns", headers=auth_headers, json={
        "name": "هر دو خرید یک هدیه", "discount_type": "PERCENT", "discount_value": 20,
        "min_purchase_count": 2, "auto_issue_validity_days": 30, "auto_issue_sms": 1,
        "valid_from": "2020-01-01T00:00:00", "valid_until": "2099-01-01T00:00:00"})
    assert r.status_code in (200, 201), r.text

    db = SessionLocal()
    try:
        # یک خریدِ قبلی؛ این خریدِ جدید، دومین خرید است ⇒ دقیقاً لحظهٔ صدور کوپن
        for i in range(1):
            db.add(Invoice(invoice_number=f"520-{i}", customer_id=cid, status="PAID",
                           subtotal=Decimal("0"), discount=Decimal("0"), invoice_discount=Decimal("0"),
                           tax=Decimal("0"), total_amount=Decimal("100000"),
                           payment_method="CASH", created_at=dt.datetime.utcnow()))
        db.commit()
    finally:
        db.close()

    r = client.post("/api/pos/campaigns/eligible", headers=auth_headers,
                    json={"amount": 100000, "product_ids": [], "customer_id": cid})
    assert r.status_code == 200, r.text
    body = r.json()
    hints = body.get("issue_on_checkout") or []
    assert any("با این خرید کوپن صادر می‌شود" in (hh.get("name") or "") for hh in hints), body
    names = [x.get("name", "") for x in body.get("campaigns", [])]
    assert any("هر دو خرید یک هدیه" in n for n in names), body
