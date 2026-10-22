# -*- coding: utf-8 -*-
"""build-517 — «مرحلهٔ آخر ذخیره نمی‌شود» + استفادهٔ درست از هر نوع جشنوارهٔ جادوگر.

ریشهٔ گزارش مالک: در حالت جفت‌شده وقتی رایانه در دسترس نبود، POST فقط یک Toast
زودگذر می‌داد و جشنواره هیچ‌جا ذخیره نمی‌شد؛ fallback محلی فقط برای GET بود.
اصلاح: قطع اتصال ⇒ ذخیرهٔ محلی (فوراً روی گوشی فعال) با پیام صادقانه؛ سایر
خطاها ⇒ خط سرخ دائمی داخل جادوگر (نه Toast). بعلاوه باگ optInt روی boolean که
«هدیهٔ خرید بعدی» را در حالت مستقل به تخفیفِ همین خرید تبدیل می‌کرد.

این فایل رفتار «استفاده» را هم برای هر چهار نوع جادوگر با همان بدنهٔ JSON که
wSaveInner می‌سازد، سرتاسری قفل می‌کند: ساخت → فهرست → ارزیابی/ثبت فروش → کوپن.
"""
from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
import app as _app  # noqa: E402

ANDROID = ROOT / "mobile-android/app/src/main/java/ir/khajavy/supermarket"
LOCAL = (ANDROID / "Local.java").read_text("utf-8")
SALES = (ANDROID / "SalesScreens.java").read_text("utf-8")


def _mk_sellable(client, h, barcode, name, sell):
    """همان مسیر تست کارکردهٔ ۵۰۹: محصول + رسید انبار با دسته (برای GIFT/CATEGORY)."""
    cat = client.post("/api/products/categories", headers=h, json={"name": f"دستهٔ {name}"}).json()
    pid = client.post("/api/products", headers=h, json={
        "barcode": barcode, "name": name, "category_id": cat["id"]}).json()["id"]
    batch = client.post("/api/batches/receive", headers=h, json={
        "product_id": pid, "quantity_received": 500, "buy_price": sell // 3,
        "sell_price": sell}).json()["id"]
    return pid, batch


def _wizard_next_spend_body(name="هدیهٔ خرید بعدی بالای ۵,۰۰۰,۰۰۰ تومان"):
    """دقیقاً همان کلیدهایی که wSaveInner برای «هدیهٔ خرید بعدی + شرط مبلغ» می‌فرستد."""
    return {"name": name, "status": "ACTIVE", "discount_type": "PERCENT",
            "discount_value": 7, "min_purchase": 0, "min_purchase_count": 0,
            "reward_next_only": True, "auto_issue_threshold": 5_000_000,
            "auto_issue_validity_days": 30, "auto_issue_sms": True,
            "target_type": "ALL", "target_ids": [], "auto_apply": False,
            "stackable": False, "first_purchase_only": False}


def test_wizard_next_spend_creates_lists_and_issues(client, auth_headers):
    h = auth_headers
    r = client.post("/api/marketing/campaigns", headers=h, json=_wizard_next_spend_body())
    assert r.status_code in (200, 201), r.text
    created = r.json()
    assert created["reward_next_only"] is True and created["min_purchase_count"] == 0

    lst = client.get("/api/marketing/campaigns", headers=h).json()
    assert any(c["id"] == created["id"] for c in lst), "جشنوارهٔ ساخته‌شده باید در فهرست بیاید"

    # استفاده: روی همین فاکتور تخفیف نمی‌شود (پاداش فقط خرید بعدی است)
    from app.services.coupons import CampaignError, evaluate_campaign
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        from app.services.coupons import CampaignError as CE
        try:
            evaluate_campaign(db, campaign_id=created["id"], amount=Decimal("8000000"))
            raise AssertionError("NEXT باید روی همین فاکتور اعمال نشود")
        except CE as err:
            assert err.code == "CAMPAIGN_NEXT_REWARD"
    finally:
        db.close()

    # و با فروش بالای آستانه، کوپن مخصوص مشتری صادر می‌شود
    pid, batch = _mk_sellable(client, h, "6265170000001", "گوشت ۵۱۷", 3_000_000)
    cid = client.post("/api/customers", headers=h, json={"name": "مشتری ۵۱۷", "phone": "09170000001"}).json()["id"]
    chk = client.post("/api/pos/checkout", headers=h, json={
        "items": [{"product_id": pid, "batch_id": batch, "quantity": 2}],
        "payments": [{"method": "CASH", "amount": 6_000_000}], "customer_id": cid})
    assert chk.status_code == 201, chk.text
    ic = chk.json().get("issued_coupon")
    assert ic and ic["code"], "فروش بالای ۵M باید کوپن خرید بعدی بدهد"
    assert ic["discount_value"] == 7, "کوپن باید همان ۷٪ جشنوارهٔ جادوگر باشد"


def test_wizard_count_kind_issues_on_every_nth(client, auth_headers):
    h = auth_headers
    body = {"name": "هر ۲ خرید هدیه", "status": "ACTIVE", "discount_type": "PERCENT",
            "discount_value": 10, "min_purchase": 0, "min_purchase_count": 2,
            "reward_next_only": True, "auto_issue_validity_days": 30,
            "auto_issue_sms": True, "target_type": "ALL", "target_ids": [],
            "auto_apply": False, "stackable": False, "first_purchase_only": False}
    r = client.post("/api/marketing/campaigns", headers=h, json=body)
    assert r.status_code in (200, 201), r.text
    pid, batch = _mk_sellable(client, h, "6265170000002", "برنج ۵۱۷", 500_000)
    cid = client.post("/api/customers", headers=h, json={"name": "مشتری شمارشی", "phone": "09170000002"}).json()["id"]

    def checkout():
        c = client.post("/api/pos/checkout", headers=h, json={
            "items": [{"product_id": pid, "batch_id": batch, "quantity": 1}],
            "payments": [{"method": "CASH", "amount": 500_000}], "customer_id": cid})
        assert c.status_code == 201, c.text
        return c.json()

    first, second = checkout(), checkout()
    codes = [x.get("issued_coupon") for x in (first, second)]
    assert codes[1] and codes[1]["code"], "خرید دوم (مضرب N=۲) باید کوپن بدهد"
    assert not (codes[0] and codes[0].get("campaign_id")), "خرید اول نباید از جشنوارهٔ تعدادی کوپن بدهد"


def test_wizard_percent_direct_applies_at_pos(client, auth_headers):
    h = auth_headers
    body = {"name": "۵٪ بالای یک میلیون", "status": "ACTIVE", "discount_type": "PERCENT",
            "discount_value": 5, "min_purchase": 1_000_000, "min_purchase_count": 0,
            "reward_next_only": False, "auto_issue_validity_days": 30,
            "auto_issue_sms": True, "target_type": "ALL", "target_ids": [],
            "auto_apply": False, "stackable": False, "first_purchase_only": False}
    r = client.post("/api/marketing/campaigns", headers=h, json=body)
    assert r.status_code in (200, 201), r.text
    cid = r.json()["id"]
    el = client.post("/api/pos/campaigns/eligible", headers=h,
                     json={"amount": 2_000_000, "product_ids": [], "include_auto_apply": True})
    assert el.status_code == 200
    row = next((c for c in el.json()["campaigns"] if c["campaign_id"] == cid), None)
    assert row and row["discount"] == 100_000, "۵٪ از ۲M باید ۱۰۰هزار تخفیف بدهد"


def test_wizard_gift_creates_and_applies_to_target_line(client, auth_headers):
    h = auth_headers
    pid, batch = _mk_sellable(client, h, "6265170000003", "نوشابهٔ هدیهٔ ۵۱۷", 40_000)
    body = {"name": "هدیهٔ نوشابه", "status": "ACTIVE", "discount_type": "GIFT",
            "discount_value": 1, "min_purchase": 0, "min_purchase_count": 0,
            "reward_next_only": False, "auto_issue_validity_days": 30,
            "auto_issue_sms": True, "target_type": "PRODUCTS", "target_ids": [pid],
            "auto_apply": False, "stackable": False, "first_purchase_only": False}
    r = client.post("/api/marketing/campaigns", headers=h, json=body)
    assert r.status_code in (200, 201), r.text
    cid = r.json()["id"]
    el = client.post("/api/pos/campaigns/eligible", headers=h, json={
        "amount": 120_000, "product_ids": [pid],
        "line_amounts": {str(pid): 120_000}, "line_qtys": {str(pid): 3},
        "include_auto_apply": True})
    assert el.status_code == 200
    row = next((c for c in el.json()["campaigns"] if c["campaign_id"] == cid), None)
    assert row and row["discount"] == 40_000 and "رایگان" in (row.get("gift_note") or ""), \
        "۱ عدد از ۳ عدد ۴۰هزارتایی باید رایگان شود"
    # بدون کالای هدف در سبد → دلیل دقیق
    el2 = client.post("/api/pos/campaigns/eligible", headers=h, json={
        "amount": 120_000, "product_ids": [999999999], "include_auto_apply": True})
    rej = next((x for x in el2.json().get("rejections", []) if x["name"] == "هدیهٔ نوشابه"), None)
    assert rej and "کالای هدیه" in rej["reason"]


def test_phone_side_fixes_locked():
    # build-518 — ذخیره «محلی-اول»: Local.handle قبل از هر تماس شبکه‌ای
    assert "void wSaveLocalFirst() throws Exception" in SALES
    assert SALES.index("Local.handle(method, path, req.toString())") < SALES.index("Api.post(\"/marketing/campaigns\"", SALES.index("void wSaveLocalFirst"))
    # در دسترس نبودن رایانه خطا نیست؛ فقط یادآوری همگام‌سازی
    assert "همگام‌سازی با رایانه بعد از اتصال انجام می‌شود" in SALES
    assert "اتصال به رایانه را بررسی کنید" not in SALES, "پیام اتصال در مسیر ذخیره ممنوع"
    # خطای سختِ محلی (مجوز/اعتبارسنجی) هنوز داخل جادوگر دیده می‌شود
    assert "⚠ \" + wSaveError" in SALES
    assert "catch (Throwable error) {" in SALES and "wSaveError(\"ذخیره انجام نشد: \" + msg);" in SALES
    # اتصال پس از انتقال: pc_id لینک می‌شود (سینک بعدی تمیز جایگزین می‌کند)
    assert 'Local.exec("UPDATE campaigns SET pc_id=?, is_local=0 WHERE id=?", sid, lrow)' in SALES
    # باگ optInt روی boolean
    assert 'v.put("reward_next_only", offerFlag(b, "reward_next_only") ? 1 : 0);' in LOCAL


def test_version_pins_517():
    # v1.0.526 — derive from app.BUILD instead of a frozen release literal.
    build = _app.BUILD
    assert _app.__version__.split(".")[-1] == str(build // 100)
    assert (ROOT / "mobile-android/BUILD").read_text().strip() == str(build)
    assert f"const UI_BUILD = {build // 100};" in (ROOT / "frontend/app.js").read_text("utf-8")
    assert f"?v={_app.__version__}" in (ROOT / "frontend/index.html").read_text("utf-8")
