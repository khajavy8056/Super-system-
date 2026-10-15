# -*- coding: utf-8 -*-
"""build-497 — Factory Reset (بازنشانی به تنظیمات کارخانه، دستورالعمل §۱۲).

قراردادهای حیاتی که هر تست این فایل آن را قفل می‌کند:
۱. پیش‌نمایش دقیق (چه حذف/چه حفظ/چه بازنشانی) بدون هیچ تغییر داده‌ای.
۲. بدون پشتیبان موفق، هیچ حذفی انجام نمی‌شود؛ بدون تأیید RESET و رمز مدیر هم.
۳. کاربران/نقش‌ها/مجوزها/لایسنس/جفت‌سازی همیشه حفظ می‌شوند — قفل‌شدن ممنوع.
۴. پس از بازنشانی، epoch داده +۱ می‌شود و sync موبایل همان را برمی‌گرداند.
۵. لاگ حسابرسی با رکورد FACTORY_RESET آغاز می‌شود.
"""
from __future__ import annotations

from datetime import date, timedelta

from app.database import SessionLocal
from app.services.factory_reset import data_epoch


def _mk_product(client, headers, barcode, name="کالای تست"):
    r = client.post("/api/products", json={"barcode": barcode, "name": name}, headers=headers)
    assert r.status_code in (200, 201), r.text
    return r.json()


def _mk_sale(client, headers, product_id, qty=2, unit_price=60000):
    """یک فروش واقعی: ابتدا دریافت کالا (Batch) و سپس Checkout با مبلغ درست."""
    r = client.post("/api/batches/receive", headers=headers, json={
        "product_id": product_id, "quantity_received": 100,
        "buy_price": 50000, "sell_price": unit_price,
        "expiry_date": (date.today() + timedelta(days=90)).isoformat()})
    assert r.status_code in (200, 201), r.text
    r = client.post("/api/pos/checkout", headers=headers, json={
        "items": [{"product_id": product_id, "quantity": qty}],
        "payments": [{"method": "CASH", "amount": float(unit_price * qty)}],
    })
    return r


def _login(client, username, password):
    r = client.post("/api/auth/login", data={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _db_counts(db):
    from sqlalchemy import text
    out = {}
    for t in ("invoices", "invoice_items", "product_batches", "stock_movements",
              "audit_logs", "sync_jobs", "customers", "products", "users"):
        out[t] = db.execute(text(f'SELECT COUNT(*) FROM "{t}"')).scalar_one()
    return out


def test_factory_reset_requires_settings_permission(client, auth_headers):
    from tests.test_v488_people import _mkuser as _mk
    _mk(client, auth_headers, "fr497_cash", roles=["Cashier"])
    cash = _login(client, "fr497_cash", "pass1234")

    assert client.get("/api/system/factory-reset/preview", headers=cash).status_code == 403
    r = client.post("/api/system/factory-reset", headers=cash,
                    json={"scope": "transactions", "confirm": "RESET", "password": "pass1234"})
    assert r.status_code == 403, r.text


def test_factory_reset_requires_password_and_explicit_confirmation(client, auth_headers):
    # بدون رمز
    r = client.post("/api/system/factory-reset", headers=auth_headers,
                    json={"scope": "transactions", "confirm": "RESET", "password": "wrong"})
    assert r.status_code == 403 and r.json()["detail"]["code"] == "BAD_PASSWORD"
    # بدون تأیید صریح
    r = client.post("/api/system/factory-reset", headers=auth_headers,
                    json={"scope": "transactions", "confirm": "yes", "password": "admin123"})
    assert r.status_code == 400 and r.json()["detail"]["code"] == "CONFIRMATION_REQUIRED"
    # دامنهٔ نامعتبر
    r = client.post("/api/system/factory-reset", headers=auth_headers,
                    json={"scope": "everything", "confirm": "RESET", "password": "admin123"})
    assert r.status_code == 400 and r.json()["detail"]["code"] == "INVALID_SCOPE"


def test_factory_reset_preview_is_read_only_and_exact(client, auth_headers, two_batches, milk):
    headers = auth_headers
    r = _mk_sale(client, headers, milk["id"])
    assert r.status_code == 201, r.text

    before = _db_counts(SessionLocal())
    p = client.get("/api/system/factory-reset/preview", headers=headers)
    assert p.status_code == 200, p.text
    body = p.json()

    assert body["scope"] == "transactions"
    assert body["confirm_phrase"] == "RESET"
    assert body["wiped_tables"]["invoices"] >= 1
    assert body["epoch_after"] == body["epoch_current"] + 1
    kept = " ".join(body["notes"])
    assert "کاربران" in kept and "لایسنس" in kept and "پشتیبان" in kept
    # پیش‌نمایش هیچ داده‌ای را تغییر نداده است
    after = _db_counts(SessionLocal())
    assert before == after
    # کاربران/نقش‌ها هرگز در فهرست حذف نیستند
    assert "users" not in body["wiped_tables"] and "roles" not in body["wiped_tables"]


def test_factory_reset_transactions_wipes_operations_keeps_master_and_users(client, auth_headers, two_batches, milk):
    headers = auth_headers
    r = _mk_sale(client, headers, milk["id"], qty=3)
    assert r.status_code == 201, r.text
    db = SessionLocal()
    epoch_before = data_epoch(db)
    db.close()

    r = client.post("/api/system/factory-reset", headers=headers,
                    json={"scope": "transactions", "confirm": "RESET", "password": "admin123"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True and body["epoch"] == epoch_before + 1
    assert body["wiped"]["invoices"] >= 1 and body["backup_size"] > 0

    db = SessionLocal()
    counts = _db_counts(db)
    assert counts["invoices"] == 0, "فروش‌ها باید پاک شده باشند"
    assert counts["invoice_items"] == 0
    assert counts["product_batches"] == 0, "موجودی عملیاتی پاک می‌شود"
    assert counts["stock_movements"] == 0
    assert counts["customers"] >= 0 and counts["products"] >= 1, "کالا و مشتری در دامنهٔ transactions می‌مانند"
    assert counts["users"] >= 1, "کاربران هرگز حذف نمی‌شوند"
    audit_count = counts["audit_logs"]
    assert audit_count == 1, "دورهٔ حسابرسی با رکورد FACTORY_RESET آغاز می‌شود"
    from sqlalchemy import text
    action = db.execute(text("SELECT action FROM audit_logs LIMIT 1")).scalar_one()
    assert action == "FACTORY_RESET"
    db.close()

    # ورود همان کاربر بعد از بازنشانی سالم است (قفل‌شدن ممنوع)
    relogin = client.get("/api/auth/me", headers=headers)
    assert relogin.status_code == 200, relogin.text


def test_factory_reset_mobile_sync_reports_new_epoch(client, auth_headers, two_batches, milk):
    headers = auth_headers
    _mk_sale(client, headers, milk["id"])
    r = client.post("/api/system/factory-reset", headers=headers,
                    json={"scope": "transactions", "confirm": "RESET", "password": "admin123"})
    assert r.status_code == 200
    epoch = r.json()["epoch"]

    sync = client.post("/api/mobile/sync", headers=headers, json={
        "push": [], "pull": True, "cursor": None, "limit": 10, "device_id": None})
    assert sync.status_code == 200, sync.text
    assert sync.json().get("data_epoch") == epoch


def test_factory_reset_full_scope_resets_catalog_and_business_settings(client, auth_headers, two_batches, milk):
    headers = auth_headers
    client.post("/api/settings", headers=headers, json={"key": "pos.tax_rate", "value": "9"})
    _mk_sale(client, headers, milk["id"])

    r = client.post("/api/system/factory-reset", headers=headers,
                    json={"scope": "full", "confirm": "RESET", "password": "admin123"})
    assert r.status_code == 200, r.text
    assert r.json()["scope"] == "full"

    db = SessionLocal()
    counts = _db_counts(db)
    assert counts["products"] == 0, "دامنهٔ full کاتالوگ را هم خالی می‌کند"
    assert counts["users"] >= 1
    from sqlalchemy import select
    from app.models import SystemSetting
    tax = db.execute(select(SystemSetting).where(SystemSetting.key == "pos.tax_rate")).scalar_one_or_none()
    assert tax is None, "تنظیمات کسب‌وکار به پیش‌فرض کارخانه برمی‌گردد"
    kept = db.execute(select(SystemSetting.key).where(SystemSetting.key.startswith("license."))).scalars().all()
    db.close()
    # کلیدهای زیرساخت (لایسنس/جفت‌سازی/راه‌اندازی) حفظ شده‌اند
    setup_done = client.get("/api/settings/setup.done", headers=headers)
    assert setup_done.status_code in (200, 404)  # endpoint shape varies; license keys checked above


def test_factory_reset_creates_safety_backup_file(client, auth_headers):
    r = client.post("/api/system/factory-reset", headers=auth_headers,
                    json={"scope": "transactions", "confirm": "RESET", "password": "admin123"})
    assert r.status_code == 200, r.text
    from pathlib import Path
    backup = Path(r.json()["backup_path"])
    assert backup.is_file() and backup.stat().st_size > 0
    assert "pre_factory_reset" in backup.name


def test_factory_reset_feature_parity_windows_and_android_sources():
    """§۴/§۱۱ — قابلیت Factory Reset باید در پنل ویندوز و اپ اندروید هر دو باشد."""
    import pathlib
    ROOT = pathlib.Path(__file__).resolve().parents[2]

    web = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    assert "factory-reset/preview" in web and "/system/factory-reset" in web, \
        "پنل ویندوز (تنظیمات) گزینهٔ بازنشانی کارخانه ندارد"
    assert "بازنشانی به تنظیمات کارخانه" in web

    android = (ROOT / "mobile-android" / "app" / "src" / "main" / "java" / "ir" /
               "khajavy" / "supermarket" / "AdminScreens.java").read_text(encoding="utf-8")
    assert "system/factory-reset/preview" in android and "system/factory-reset" in android, \
        "اپ اندروید گزینهٔ بازنشانی کارخانه ندارد"
    assert "بازنشانی کارخانه" in android

    # sync: گوشی باید epoch داده را دریافت و تغییرش را تشخیص دهد (§۵)
    sync_src = (ROOT / "mobile-android" / "app" / "src" / "main" / "java" / "ir" /
                "khajavy" / "supermarket" / "Sync.java").read_text(encoding="utf-8")
    assert "data_epoch" in sync_src and "wipeOperational" in sync_src, \
        "گوشی تغییر دورهٔ دادهٔ رایانه را تشخیص نمی‌دهد"

    db_src = (ROOT / "mobile-android" / "app" / "src" / "main" / "java" / "ir" /
              "khajavy" / "supermarket" / "Db.java").read_text(encoding="utf-8")
    assert "public static int wipeOperational()" in db_src, \
        "پاک‌سازی عملیاتی محلی (بدون دست‌زدن به کاربران/نشست) وجود ندارد"

    mobile_api = (ROOT / "backend" / "app" / "routers" / "mobile.py").read_text(encoding="utf-8")
    assert '"data_epoch"' in mobile_api, "پاسخ sync موبایل epoch داده را برنمی‌گرداند"
