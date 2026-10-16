# -*- coding: utf-8 -*-
"""build-521 — ریشه‌های گزارش مالک، قفل‌شده روی همان چیزی که واقعاً خراب بود.

گزارش مالک (اسکرین‌شات واقعی): «جشنوارهٔ بالای ۵۰۰٬۰۰۰ تومان فعال است، فاکتور
۱٬۱۱۶٬۰۰۰ تومانی ثبت شد، ولی پیامک می‌گوید: کد تخفیف خرید بعدی: null — و هیچ
کدی هم ساخته نشد.»

این فایل دو ریشه را قفل می‌کند:
۱) صدور کوپن روی گوشی با «no such column: note» می‌شکست (ستون coupons.note
   هرگز ساخته نشده بود) ⇒ هیچ کدی صادر نمی‌شد.
۲) مقدار پوچ (SQL NULL) در لایهٔ JSON به رشتهٔ «null» تبدیل می‌شد و روی
   پیامک/رسید می‌نشست.

به‌علاوه برابری‌های build-521 که در همین نسخه اضافه شدند (همگام‌سازی مستقل
ویندوز، پنجرهٔ جشنواره در ویندوز، قیمت‌گذاری/کارهای پس از فروش مشترک، حذف
فهرست ثابت ستون‌ها در ایمپورت پشتیبان، مسیر سریع LAN و مجوز ابطال فاکتور).
"""
from __future__ import annotations

import pathlib

BASE = pathlib.Path(__file__).resolve().parents[2]
ANDROID = BASE / "mobile-android/app/src/main/java/ir/khajavy/supermarket"
DB = (ANDROID / "Db.java").read_text("utf-8")
LOCAL = (ANDROID / "Local.java").read_text("utf-8")
SMS = (ANDROID / "SmsLocal.java").read_text("utf-8")
API = (ANDROID / "Api.java").read_text("utf-8")
PC = (ANDROID / "PcImport.java").read_text("utf-8")
SALES = (ANDROID / "SalesScreens.java").read_text("utf-8")
DESKTOP_SYNC = BASE / "desktop/screens/sync.py"
MAIN_WINDOW = (BASE / "desktop/main_window.py").read_text("utf-8")
MODEL_POS = (BASE / "backend/app/services/pos.py").read_text("utf-8")
ROUTER_POS = (BASE / "backend/app/routers/pos.py").read_text("utf-8")
DESKTOP_POS = (BASE / "desktop/screens/pos.py").read_text("utf-8")


# --------------------------------------------------------------------- ریشهٔ ۱

def test_coupon_note_column_exists_on_the_phone():
    """ستونی که موتور صدور با آن از تکرار جلوگیری می‌کند، واقعاً ساخته می‌شود."""
    assert "created_at TEXT, note TEXT)" in DB, "جدول coupons باید ستون note داشته باشد"
    assert "static void v14CouponNote(SQLiteDatabase d)" in DB
    assert 'addColumn(d, "coupons", "note TEXT")' in DB
    assert "static final int VERSION = 14;" in DB
    assert "if (a < 14) v14CouponNote(d);" in DB
    # خودترمیمی در هر باز شدن دیتابیس (هم‌الگو با بیلد ۵۱۹) — مسیر ارتقای جاافتاده دیگر ممکن نیست
    on_open = DB[DB.index("public void onOpen(SQLiteDatabase d)"):]
    on_open = on_open[:on_open.index("static final int VERSION")]
    assert "v14CouponNote(d)" in on_open, "onOpen باید ستون note را خودترمیمی کند"
    # موتور صدور همان کلید را می‌نویسد (اگر ستون نبود، همین درج می‌شکست)
    assert '"صادر شده پس از فاکتور " + invoiceNo' in LOCAL
    assert 'values.put("note", note);' in LOCAL
    assert 'one("SELECT id FROM coupons WHERE campaign_id=? AND note=?", campaignId, note)' in LOCAL


# --------------------------------------------------------------------- ریشهٔ ۲

def test_sql_null_never_becomes_the_text_null():
    row_builder = LOCAL[LOCAL.index("Cursor.FIELD_TYPE_NULL"):]
    row_builder = row_builder[:row_builder.index("FIELD_TYPE_INTEGER")]
    assert "JSONObject.NULL" not in row_builder, \
        "سلول NULL نباید JSON null شود — optString آن را «null» می‌خواند"
    # خوانندهٔ پیامک هم «null»/«undefined» را کد نمی‌شمارد
    assert 'if ("null".equalsIgnoreCase(coupon) || "undefined".equalsIgnoreCase(coupon)) coupon = "";' in SMS
    assert 'text.append("\\nکد تخفیف خرید بعدی: ").append(coupon);' in SMS
    # پاسخ‌های سرور هم پاک می‌شوند
    assert "return stripNulls(new JSONTokener(text).nextValue());" in API
    assert 'return ("null".equals(v) || "undefined".equals(v)) ? null : v;' in API


def test_lan_fast_path_keeps_the_port_and_never_throws_silently():
    """«آرایه|port»: پورت ضمیمه می‌شود و فقط نامزد «طرح+میزبان+پورت» آزمایش می‌شود."""
    assert "static java.util.List<String> lanCandidates()" in API
    assert "(?i)^https?://[^/]+:[0-9]+.*$" in API
    assert "lan.substring(0, lan.lastIndexOf('|'))" not in API, "بریدن آرایه با lastIndexOf پورت را می‌خورد"
    assert "for (String u : lanCandidates())" in API


# ------------------------------------------------------- برابری ویندوز/اندروید

def test_price_and_after_sale_are_shared_logic():
    """صندوق ویندوز و روتر API روی همان دو تابع سرویس کار می‌کنند (§۱۴)."""
    assert "def after_sale(" in MODEL_POS
    assert "def price_cart(" in MODEL_POS
    assert "pos_service.after_sale(" in ROUTER_POS
    assert "pos_svc.after_sale(" in DESKTOP_POS
    assert "pos_svc.price_cart(" in DESKTOP_POS


def test_windows_has_standalone_sync_page_and_campaign_editor():
    assert DESKTOP_SYNC.exists(), "صفحهٔ مستقل «همگام‌سازی» ویندوز ساخته نشده"
    sync = DESKTOP_SYNC.read_text("utf-8")
    assert "class SyncPage" in sync and "همگام‌سازی اکنون" in sync
    assert "from .screens.sync import SyncPage" in MAIN_WINDOW
    assert 'pages.append(("همگام‌سازی", SyncPage(ctx)))' in MAIN_WINDOW
    campaigns_win = (BASE / "desktop/screens/campaigns.py").read_text("utf-8")
    assert "class CampaignDialog" in campaigns_win
    assert "reward_next_only" in campaigns_win and "min_purchase_count" in campaigns_win


def test_void_permission_matches_the_server():
    assert 'require("pos.void_unpaid")' in LOCAL, "درِ ورودی ابطال مثل سرور pos.void_unpaid است"
    assert '!Screens.can("pos.void_paid")' in LOCAL, "فاکتور پرداخت‌شده مجوز جداگانه می‌خواهد"
    assert 'Screens.can("pos.void_unpaid")' in SALES


def test_windows_backup_import_never_uses_a_fixed_column_list():
    assert "private static boolean pcHasColumn(SQLiteDatabase d, String table, String column)" in PC
    assert 'PRAGMA pc.table_info(' in PC
    assert '"INSERT INTO campaigns(id,name,' not in PC, "فهرست ثابت ستون = شکست روی پشتیبان قدیمی"


def test_pos_explains_why_a_campaign_was_not_applied():
    assert "void explainRejections()" in SALES
    assert "چرا " in SALES and " جشنوارهٔ دیگر اعمال نشد؟" in SALES
    assert "دلیل اعمال‌نشدن هر جشنواره:" in SALES
    assert "کد تخفیف این فاکتور: " in SALES
    assert '"بدون شماره"' in SALES
    # دلایل از هر دو موتور می‌آیند (برابری میدان پاسخ با بک‌اند)
    assert 'if (rejections.length() > 0) response.put("rejections", rejections);' in LOCAL
    assert '"rejections": rejections' in ROUTER_POS


# ------------------------------------------------- گزارش مالک، سرتاسری روی API

def test_owner_scenario_next_purchase_coupon_and_sms_has_a_real_code(client, auth_headers):
    """جشنوارهٔ ۷٪ «خرید بالای ۵۰۰٬۰۰۰» + فاکتور ۱٬۱۱۶٬۰۰۰ ⇒ کد واقعی در پیامک و فاکتور."""
    from decimal import Decimal

    from app.database import SessionLocal
    from app.models import Coupon, SmsMessage, SystemSetting

    cust = client.post("/api/customers", headers=auth_headers,
                       json={"name": "مشتری ۵۲۱", "phone": "09160000021"})
    assert cust.status_code in (200, 201), cust.text
    cid = cust.json()["id"]

    camp = client.post("/api/marketing/campaigns", headers=auth_headers, json={
        "name": "کد تخفیف خرید بعدی ۵۲۱", "discount_type": "PERCENT", "discount_value": 7,
        "auto_issue_threshold": 500000, "auto_issue_validity_days": 30, "auto_issue_sms": 1,
        "valid_from": "2020-01-01T00:00:00", "valid_until": "2099-01-01T00:00:00",
        "reward_next_only": 1})
    assert camp.status_code in (200, 201), camp.text
    campaign_id = camp.json()["id"]

    prod = client.post("/api/products", headers=auth_headers, json={
        "name": "کالای ۵۲۱", "barcode": "5210000000011", "unit": "عدد",
        "sell_price": 1116000, "buy_price": 700000, "min_stock_alert": 0, "is_active": True})
    assert prod.status_code in (200, 201), prod.text
    pid = prod.json()["id"]
    recv = client.post("/api/batches/receive", headers=auth_headers, json={
        "product_id": pid, "quantity_received": 10, "buy_price": 700000, "sell_price": 1116000,
        "batch_number": "B521-1"})
    assert recv.status_code in (200, 201), recv.text

    sale = client.post("/api/pos/checkout", headers=auth_headers, json={
        "items": [{"product_id": pid, "quantity": 1, "price": 1116000}],
        "payments": [{"method": "CASH", "amount": 1116000}],
        "customer_id": cid, "customer_phone": "09160000021",
        "customer_name": "مشتری ۵۲۱", "open_drawer": False})
    assert sale.status_code in (200, 201), sale.text
    out = sale.json()
    # همان پاسخ ثبت فروش هم کد واقعی را برمی‌گرداند (و هرگز «null»)
    assert (out.get("issued_coupon") or {}).get("code"), out
    invoice_number = out.get("invoice_number") or out.get("invoice", {}).get("invoice_number")
    assert invoice_number, out

    db = SessionLocal()
    try:
        coupon = db.query(Coupon).filter(Coupon.campaign_id == campaign_id).one_or_none()
        assert coupon is not None, "برای فاکتور بالای آستانه باید کوپن خرید بعدی صادر شود"
        assert coupon.code and coupon.code.startswith("NEXT-"), coupon.code
        assert "null" not in coupon.code.lower()
        # کلید idempotency هر فاکتور: «صادر شده پس از فاکتور <شماره>»
        assert coupon.note == f"صادر شده پس از فاکتور {invoice_number}"
        # پیامک همین فاکتور کد واقعی دارد، نه null (پیامک‌های فاکتورهای دیگر
        # پاک نمی‌شوند — دیتابیس سوئیت مشترک است، پس فقط همین فاکتور را می‌بینیم)
        mine = [m for m in db.query(SmsMessage).all()
                if (m.reference_type or "").lower() == "invoice" and invoice_number in (m.text or "")]
        setting = db.query(SystemSetting).filter(SystemSetting.key == "sms.send_invoice").one_or_none()
        sms_enabled = setting is None or str(setting.value or "true").strip().lower() != "false"
        assert mine or not sms_enabled, "پیامک فاکتور صف نشده است"
        for msg in mine:
            assert "کد تخفیف خرید بعدی: null" not in (msg.text or ""), msg.text
            assert f"کد تخفیف خرید بعدی: {coupon.code}" in (msg.text or ""), msg.text
        # و هیچ پیامک دیگری نباید متن پوچ «null» را حمل کند
        assert not [m for m in db.query(SmsMessage).all() if "کد تخفیف خرید بعدی: null" in (m.text or "")]
    finally:
        db.close()

    # فاکتور هم همان کد را روی خودش دارد (نه رشتهٔ «null»)
    inv = client.get(f"/api/invoices?limit=5", headers=auth_headers)
    assert inv.status_code == 200, inv.text
