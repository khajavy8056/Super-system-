# -*- coding: utf-8 -*-
"""build-509 — ارتقای کامل بخش جشنواره‌ها (گزارش مالک):

«جشنواره‌ها درست کار نمی‌کند / قابلیت تولید جشنواره‌های مختلف نیست / خرید بالای
۱۰ میلیون باید خودکار کد تخفیف ۱۵٪ خرید بعدی بسازد و در فاکتور بیاید / در صندوق
بخش جشنواره برای صندوق‌دار باز نمی‌شود.»

آنچه این تست‌ها برای همیشه قفل می‌کنند:
۱) صندوق‌دار (نقش Cashier) به فهرست جشنوارهٔ صندوق می‌رسد — ۲۰۰، نه خطا؛ و پاسخ
   شامل «issue_on_checkout» است (قبل از ثبت بداند کوپن صادر می‌شود).
۲) سناریوی دقیق مالک: جشنوارهٔ ۱۵٪ با آستانهٔ ۱۰M → خرید ۱۲M ⇒ کد NEXT- صادر می‌شود
   با همان ۱۵٪ و نام جشنواره؛ **روی متن رسید چاپ می‌شود** («در فاکتور ارسال شود»)؛
   در پروندهٔ مشتری به‌عنوان مزیت NEXT_PURCHASE دیده می‌شود؛ و تکرار همان فاکتور
   همان کد را می‌دهد (idempotent).
۳) زیر آستانه چیزی صادر نمی‌شود؛ جشنوارهٔ منقضی/مکث نه اعمال می‌شود نه کوپن می‌دهد.
۴) «انواع جشنواره»: ساخت با همهٔ توانمندی‌های مدل (بازهٔ جلالی‌مبدأ، کالاهای هدف،
   فقط اولین خرید، سقف هر مشتری، اولویت، پیامک) و ویرایش/توقف/پایان (PATCH).
۵) قرارداد سورس: صندوق ویندوز راهنمای صدور و خطای واضح دارد؛ فرم ساخت کامل است؛
   اندروید campaignRequest ضد NaN است (ریشهٔ خطای «آماده نشد»).
"""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _mk_campaign(client, h, **over):
    body = {"name": "جشنوارهٔ ۱۰ میلیونی", "discount_type": "PERCENT", "discount_value": 15,
            "min_purchase": 0, "auto_issue_threshold": 10_000_000,
            "auto_issue_validity_days": 30, "auto_issue_sms": True}
    body.update(over)
    r = client.post("/api/marketing/campaigns", headers=h, json=body)
    assert r.status_code == 201, r.text
    return r.json()


def _mk_sellable(client, h, barcode, name, sell):
    pid = client.post("/api/products", json={"barcode": barcode, "name": name}, headers=h).json()["id"]
    batch = client.post("/api/batches/receive", headers=h, json={
        "product_id": pid, "quantity_received": 500, "buy_price": sell // 3, "sell_price": sell}).json()["id"]
    return pid, batch


def test_cashier_can_open_pos_campaigns_and_sees_issue_hint(client, auth_headers):
    _mk_campaign(client, auth_headers)
    ru = client.post("/api/users", json={"username": "cash509", "password": "cash12345",
                                         "full_name": "صندوق‌دار جشنواره", "roles": ["Cashier"]},
                     headers=auth_headers)
    assert ru.status_code == 201, ru.text
    login = client.post("/api/auth/login", data={"username": "cash509", "password": "cash12345"})
    tok = {"Authorization": f"Bearer {login.json()['access_token']}"}
    r = client.post("/api/pos/campaigns/eligible", headers=tok,
                    json={"amount": 12_000_000, "product_ids": [], "include_auto_apply": True})
    assert r.status_code == 200, f"صندوق‌دار باید جشنواره‌ها را ببیند: {r.text}"
    body = r.json()
    assert "campaigns" in body and "issue_on_checkout" in body
    hints = body["issue_on_checkout"]
    assert hints and hints[0]["discount_value"] == 15 and hints[0]["threshold"] == 10_000_000, \
        "صندوق باید قبل از ثبت بداند کوپن خرید بعدی صادر می‌شود"


def test_owner_scenario_threshold_coupon_on_receipt_and_customer(client, auth_headers):
    camp = _mk_campaign(client, auth_headers)
    pid, batch = _mk_sellable(client, auth_headers, "6265090000001", "یخچال تست ۵۰۹", 12_000_000)
    cid = client.post("/api/customers", json={"name": "مشتری ۵۰۹", "phone": "09122220000"},
                      headers=auth_headers).json()["id"]

    # فروش بالای آستانه (۲ عدد = ۲۴M):
    r = client.post("/api/pos/checkout", headers=auth_headers, json={
        "items": [{"product_id": pid, "batch_id": batch, "quantity": 2}],
        "payments": [{"method": "CASH", "amount": 24_000_000}], "customer_id": cid})
    assert r.status_code == 201, r.text
    inv = r.json()
    ic = inv["issued_coupon"]
    assert ic and ic["code"].startswith("NEXT-"), "خرید بالای ۱۰M باید خودکار کد بدهد"
    assert ic["discount_value"] == 15 and ic["discount_type"] == "PERCENT", "کد باید همان ۱۵٪ جشنواره باشد"
    assert ic["campaign_name"] == camp["name"]

    # «در فاکتور ارسال شود»: کد روی متنِ رسید چاپ می‌شود
    rc = client.get(f"/api/invoices/{inv['invoice_id']}/receipt", headers=auth_headers)
    assert rc.status_code == 200
    text = rc.json()["receipt_text"]
    assert ic["code"] in text and "خرید بعدی" in text, \
        "کد تخفیف خرید بعدی باید روی خودِ فاکتور/رسید چاپ شود"

    # در پروندهٔ مشتری به‌عنوان مزیت NEXT_PURCHASE دیده می‌شود
    ben = client.get(f"/api/customers/{cid}/benefits", headers=auth_headers).json()
    assert any(b.get("code") == ic["code"] and b.get("source") == "NEXT_PURCHASE"
               for b in ben.get("benefits", [])), "کوپن باید در پروندهٔ مشتری باشد"

    # idempotent: فاکتور همان، دوباره صدور ⇒ همان کد (نه کد تازه)
    from app.database import SessionLocal
    from app.models import Coupon
    from app.models import Invoice as Inv
    from app.services import coupons as coupon_svc
    s = SessionLocal()
    try:
        row = s.get(Inv, inv["invoice_id"])
        again = coupon_svc.issue_next_purchase_coupon(s, invoice=row, user=None,
                                                      customer=row.customer)
        s.commit()
    finally:
        s.close()
    assert again is not None and again.code == ic["code"], "تکرارِ همان فاکتور کد دوباره نسازد"
    s2 = SessionLocal()
    try:
        n = len(s2.execute(
            __import__("sqlalchemy").select(Coupon).where(
                Coupon.note == f"صادر شده پس از فاکتور {inv['invoice_number']}")).scalars().all())
        assert n == 1, f"برای یک فاکتور فقط یک کوپن: {n}"
    finally:
        s2.close()


def test_expired_and_paused_campaigns_issue_nothing(client, auth_headers):
    # منقضی با آستانهٔ بالاتر: ترتیبِ اولویتِ صدور به آن می‌رسد ولی باید رد شود
    past = (datetime.utcnow() - timedelta(days=2)).isoformat()
    _mk_campaign(client, auth_headers, name="منقضی ۵۰۹", auto_issue_threshold=60_000_000,
                 valid_until=past)
    _mk_campaign(client, auth_headers, name="زندهٔ ۵۰۹", auto_issue_threshold=55_000_000)
    pid, batch = _mk_sellable(client, auth_headers, "6265090000002", "کالای منقضی‌سنج", 15_000_000)
    r = client.post("/api/pos/checkout", headers=auth_headers, json={
        "items": [{"product_id": pid, "batch_id": batch, "quantity": 4}],
        "payments": [{"method": "CASH", "amount": 60_000_000}]})
    assert r.status_code == 201, r.text
    ic = r.json()["issued_coupon"]
    assert ic and ic["campaign_name"] == "زندهٔ ۵۰۹", \
        f"جشنوارهٔ منقضی نباید کوپن بدهد: {ic}"

    # مکثِ همهٔ جشنواره‌ها ⇒ نه وعدهٔ صدور در صندوق، نه کوپن
    camps = client.get("/api/marketing/campaigns", headers=auth_headers).json()
    for c in camps:
        if c["status"] == "ACTIVE":
            rp = client.patch(f"/api/marketing/campaigns/{c['id']}", headers=auth_headers,
                              json={**c, "status": "PAUSED"})
            assert rp.status_code == 200, rp.text
    el = client.post("/api/pos/campaigns/eligible", headers=auth_headers,
                     json={"amount": 60_000_000, "product_ids": []}).json()
    assert not el["issue_on_checkout"], "جشنوارهٔ مکث نباید کوپن وعده بدهد"


def test_campaign_full_variety_roundtrip_and_update(client, auth_headers):
    soon = (datetime.utcnow() + timedelta(days=1)).isoformat()
    end = (datetime.utcnow() + timedelta(days=10)).isoformat()
    body = {"name": "جشنوارهٔ کالای مشخص", "description": "فقط روی نوشیدنی",
            "discount_type": "FIXED", "discount_value": 50_000, "min_purchase": 200_000,
            "max_discount": 40_000, "max_purchase": 5_000_000, "usage_limit": 100,
            "per_customer_limit": 2, "priority": 1, "first_purchase_only": True,
            "target_type": "PRODUCTS", "target_ids": [11, 22], "stackable": True,
            "auto_apply": True, "auto_issue_threshold": None, "auto_issue_sms": False,
            "valid_from": soon, "valid_until": end, "status": "ACTIVE"}
    r = client.post("/api/marketing/campaigns", headers=auth_headers, json=body)
    assert r.status_code == 201, r.text
    got = r.json()
    for k in ("description", "max_purchase", "usage_limit", "per_customer_limit", "priority",
              "first_purchase_only", "target_type", "target_ids", "stackable", "auto_apply",
              "valid_from", "valid_until"):
        assert got[k] == body[k], f"فیلد {k} درست ذخیره نشده"
    # ویرایش (PATCH) — مکث و تغییر مقدار
    body["discount_value"] = 75_000
    body["status"] = "PAUSED"
    r2 = client.patch(f"/api/marketing/campaigns/{got['id']}", headers=auth_headers, json=body)
    assert r2.status_code == 200, r2.text
    assert r2.json()["discount_value"] == 75_000 and r2.json()["status"] == "PAUSED"


def test_source_contract_campaigns_complete():
    web = (ROOT / "frontend/app.js").read_text("utf-8")
    assert 'id="cm-thr"' in web and 'id="cm-percust"' in web and 'id="cm-first"' in web, \
        "فرم ساخت جشنواره باید کامل باشد (آستانه، سقف هر مشتری، اولین خرید)"
    assert "jalali.toGregorian" in web, "تاریخ‌های جلالی فرم باید به میلادی تبدیل شوند"
    assert "issue_on_checkout" in web, "صندوق باید راهنمای صدور کوپن را نشان دهد"
    assert "campaignSetStatus" in web and "_campaignCache" in web, "مدیریت کمپین (ویرایش/توقف/پایان)"
    assert "campaignRequest()" in (ROOT / "mobile-android/app/src/main/java/ir/khajavy/supermarket/SalesScreens.java").read_text("utf-8")
    sales = (ROOT / "mobile-android/app/src/main/java/ir/khajavy/supermarket/SalesScreens.java").read_text("utf-8")
    assert "JSONObject campaignRequest() {" in sales and "finBenefit(lineAmounts.optDouble(key))" in sales, \
        "campaignRequest اندروید باید ضد NaN باشد (ریشهٔ خطای «آماده نشد»)"
    hw = (ROOT / "backend/app/services/hardware.py").read_text("utf-8")
    assert "کد تخفیف خرید بعدی" in hw, "رسید باید کد کوپن را چاپ کند"
