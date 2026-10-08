# -*- coding: utf-8 -*-
"""build-496 (دور دوم ممیزی) — بازنشانی به تنظیمات کارخانه (Factory Reset).

قراردادهایی که این تست‌ها نگه می‌دارند:

  ۱. «نقشه» یک dry-run است: صدا زدنش هیچ ردیفی را پاک نمی‌کند.
  ۲. بدون عبارت تأیید عیناً، هیچ داده‌ای — و حتی هیچ فایل پشتیبانی — ساخته نمی‌شود.
  ۳. پیش از پاک‌سازی، پشتیبان کامل گرفته می‌شود و **قابل بازیابی** است
     (خودِ فایل با sqlite باز می‌شود و داده‌های قبل از بازنشانی را دارد).
  ۴. پس از بازنشانی، برنامه «قابل استفاده» است: ورود، ثبت کالا و فروش کار می‌کند
     و تنظیمات هویتی (فروشگاه/ارز/پیامک) سر جای خودشان هستند.
  ۵. حالت `keep_catalog` کالاها را نگه می‌دارد و موجودی را صفر می‌کند؛
     حالت `full` کالاها را هم پاک و بانک پیش‌فرض را بازمی‌سازد.

تست مخرب (بندهای ۳ تا ۵) در **زیرفرایند با پایگاه اختصاصی** اجرا می‌شود تا
پایگاه مشترکِ نشستِ تست‌ها را تحت تأثیر نگذارد — همان الگویی که demo_store دارد.
"""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"

_CHILD = r'''
import json, os, sqlite3, sys, tempfile
from pathlib import Path

work = Path(os.environ["FR_WORK"])
work.mkdir(parents=True, exist_ok=True)
os.environ["DATABASE_URL"] = f"sqlite:///{work / 'shop.db'}"
os.environ["SECRET_KEY"] = "test-secret-key-that-is-long-enough-for-hs256"
os.environ["ADMIN_USERNAME"] = "admin"
os.environ["ADMIN_PASSWORD"] = "admin123"
os.environ["SUPERMARKET_LICENSE_GATE"] = "0"
os.environ["FR_WORK"] = str(work)

from fastapi.testclient import TestClient
from app.main import app

out = {}
with TestClient(app) as c:
    tok = c.post("/api/auth/login", data={"username": "admin", "password": "admin123"}).json()["access_token"]
    h = {"Authorization": f"Bearer {tok}"}
    c.put("/api/settings", json={"key": "store.name", "value": "فروشگاه آزمایشی فر"}, headers=h)
    product = c.post("/api/products", json={"barcode": "6260000009100", "name": "کالای آزمایشی فر"}, headers=h).json()
    batch = c.post("/api/batches/receive", headers=h, json={
        "product_id": product["id"], "quantity_received": 20, "buy_price": 1000, "sell_price": 2000,
        "expiry_date": (__import__("datetime").date.today() + __import__("datetime").timedelta(days=60)).isoformat(),
    }).json()
    sale = c.post("/api/pos/checkout", headers=h, json={
        "items": [{"product_id": product["id"], "batch_id": batch["id"], "quantity": 3}],
        "payments": [{"method": "CASH", "amount": 6000}]})
    out["sale_status"] = sale.status_code
    # تنظیمات عملیاتی پس از فروش تغییر می‌کند تا معلوم باشد بازنشانی آن‌ها را
    # به پیش‌فرض برگردانده (مالیات ۹٪ ⇒ باید به ۰ برگردد).
    c.put("/api/settings", json={"key": "pos.tax_rate", "value": "9"}, headers=h)
    customer = c.post("/api/customers", json={"name": "مشتری فر", "phone": "09120000000"}, headers=h)
    out["customer_status"] = customer.status_code
    bank_before = len(c.get("/api/products?query=شیر", headers=h).json().get("items", []))

    plan = c.get("/api/system/factory-reset/plan", headers=h).json()
    out["plan_delete_total"] = plan["delete_total"]
    out["plan_tables"] = len(plan["delete"])
    out["plan_keep_tables"] = [row["table"] for row in plan["keep"]]
    out["plan_kept_settings_has_store"] = any(k.startswith("store.") for k in plan["settings_kept"])
    out["plan_reset_settings_has_tax"] = any(s["key"] == "pos.tax_rate" for s in plan["settings_reset"])
    out["plan_warnings"] = len(plan["warnings"])
    products_after_plan = len(c.get("/api/products", headers=h).json().get("items", []))
    out["plan_is_dry_run"] = products_after_plan >= 1

    bad = c.post("/api/system/factory-reset", json={"confirmation": "نه", "mode": "full"}, headers=h)
    out["bad_phrase_status"] = bad.status_code
    out["backups_after_bad_phrase"] = len(c.get("/api/system/backups", headers=h).json())
    out["invoices_after_bad_phrase"] = len(c.get("/api/invoices", headers=h).json().get("items", []))

    keep = c.post("/api/system/factory-reset", headers=h,
                  json={"confirmation": "بازنشانی", "mode": "keep_catalog", "reason": "test"}).json()
    out["keep_backup"] = keep["backup_path"]
    out["keep_deleted_total"] = keep["deleted_total"]
    out["keep_products"] = len(c.get("/api/products", headers=h).json().get("items", []))
    out["keep_invoices"] = len(c.get("/api/invoices", headers=h).json().get("items", []))
    stock = c.get(f"/api/batches?product_id={product['id']}", headers=h)
    out["keep_batches_status"] = stock.status_code
    out["keep_batches_rows"] = len(stock.json()) if stock.status_code == 200 else -1
    out["keep_settings_store_name"] = next((r["value"] for r in c.get("/api/settings", headers=h).json()
                                            if r["key"] == "store.name"), None)
    out["keep_settings_tax"] = next((r["value"] for r in c.get("/api/settings", headers=h).json()
                                     if r["key"] == "pos.tax_rate"), None)
    out["keep_users"] = len(c.get("/api/users", headers=h).json())
    me = c.get("/api/auth/me", headers=h)
    out["me_after_keep"] = me.status_code
    new_sale = c.post("/api/products", json={"barcode": "6260000009200", "name": "پس از بازنشانی"}, headers=h)
    out["usable_after_keep"] = new_sale.status_code == 201

    full = c.post("/api/system/factory-reset", headers=h,
                  json={"confirmation": "بازنشانی", "mode": "full"}).json()
    out["full_backup"] = full["backup_path"]
    out["full_deleted_total"] = full["deleted_total"]
    listing = c.get("/api/products", headers=h).json()
    out["full_products"] = len(listing.get("items", []))
    out["full_products_total"] = listing.get("total")
    # کالای «خودِ فروشگاه» (ساختهٔ پیش از بازنشانی) نباید باقی مانده باشد
    out["full_old_product_hits"] = len(c.get("/api/products?q=کالای آزمایشی فر", headers=h).json().get("items", []))
    old_batches = c.get(f"/api/batches?product_id={product['id']}", headers=h)
    out["full_old_product_batches"] = -1 if old_batches.status_code == 404 else len(old_batches.json())
    out["full_bank_rows"] = None             # from the DB file below
    out["catalog_reseeded"] = full.get("catalog_reseeded")
    out["full_users"] = len(c.get("/api/users", headers=h).json())
    out["full_me"] = c.get("/api/auth/me", headers=h).status_code
    created = c.post("/api/products", json={"barcode": "6260000009300", "name": "کالای تازه پس از full"}, headers=h)
    out["full_usable"] = created.status_code == 201
    out["audit_actions"] = [row["action"] for row in c.get("/api/audit", headers=h).json()[:10]]
    out["manifest_exists"] = Path(full["manifest_path"]).is_file()

# --- پشتیبانِ گرفته‌شده باید یک پایگاه سالم و قابل بازیابی باشد ---
# پشتیبانِ «حفظ کالا» درست پیش از پاک‌شدن فاکتورها گرفته شده است، پس باید خودِ
# فروش و کالاها را داشته باشد؛ همین سندِ «قابل بازگشت بودن» است.
raw = sqlite3.connect(out["keep_backup"])
try:
    out["keep_backup_integrity"] = raw.execute("PRAGMA integrity_check").fetchone()[0]
    out["keep_backup_invoices"] = raw.execute("SELECT COUNT(*) FROM invoices").fetchone()[0]
    out["keep_backup_products"] = raw.execute("SELECT COUNT(*) FROM products").fetchone()[0]
    out["keep_backup_items"] = raw.execute("SELECT COUNT(*) FROM invoice_items").fetchone()[0]
finally:
    raw.close()
raw = sqlite3.connect(out["full_backup"])
try:
    out["full_backup_integrity"] = raw.execute("PRAGMA integrity_check").fetchone()[0]
    out["full_backup_products"] = raw.execute("SELECT COUNT(*) FROM products").fetchone()[0]
finally:
    raw.close()

now = sqlite3.connect(work / "shop.db")
try:
    out["full_bank_rows"] = now.execute("SELECT COUNT(*) FROM product_bank").fetchone()[0]
    # دقیقاً یک کالا در پایگاه هست: همان که بعد از بازنشانی ساخته شد.
    out["full_products_db_after_new"] = now.execute("SELECT COUNT(*) FROM products").fetchone()[0]
    out["full_settings_rows"] = now.execute("SELECT COUNT(*) FROM system_settings").fetchone()[0]
finally:
    now.close()

print("__FR__" + json.dumps(out, ensure_ascii=False, default=str))
'''


@pytest.fixture(scope="module")
def reset_report() -> dict:
    work = Path(tempfile.mkdtemp(prefix="factory_reset_"))
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([str(BACKEND), env.get("PYTHONPATH", "")])
    env["FR_WORK"] = str(work)
    proc = subprocess.run([sys.executable, "-c", _CHILD], capture_output=True, text=True,
                          env=env, cwd=str(BACKEND), timeout=600)
    marker = [line for line in proc.stdout.splitlines() if line.startswith("__FR__")]
    assert marker, f"child produced no report\nSTDOUT:\n{proc.stdout[-3000:]}\nSTDERR:\n{proc.stderr[-3000:]}"
    return json.loads(marker[-1][len("__FR__"):])


def test_plan_is_a_dry_run_and_describes_the_whole_operation(reset_report):
    assert reset_report["plan_is_dry_run"], "نقشه نباید چیزی پاک کند"
    assert reset_report["plan_delete_total"] > 0 and reset_report["plan_tables"] > 20
    assert "role_permissions" in reset_report["plan_keep_tables"]
    assert "units" in reset_report["plan_keep_tables"] and "product_bank" in reset_report["plan_keep_tables"]
    assert reset_report["plan_kept_settings_has_store"], "پروفایل فروشگاه باید حفظ شود"
    assert reset_report["plan_reset_settings_has_tax"], "تنظیمات عملیاتی باید بازنشانی شوند"
    assert reset_report["plan_warnings"] >= 2


def test_without_the_confirmation_phrase_nothing_is_deleted_or_backed_up(reset_report):
    assert reset_report["bad_phrase_status"] == 400
    assert reset_report["backups_after_bad_phrase"] == 0, "با عبارت غلط حتی پشتیبان هم ساخته نمی‌شود"
    assert reset_report["sale_status"] == 201, "پیش‌نیاز تست: فروش باید ثبت شده باشد"
    assert reset_report["invoices_after_bad_phrase"] >= 1, "با عبارت غلط هیچ فاکتوری پاک نمی‌شود"


def test_keep_catalog_mode_keeps_the_product_list_and_zeroes_the_operations(reset_report):
    assert reset_report["keep_deleted_total"] > 0
    assert reset_report["keep_products"] >= 2, "حالت حفظ کالا نباید فهرست کالاها را پاک کند"
    assert reset_report["keep_invoices"] == 0, "فاکتورها باید پاک شوند"
    assert reset_report["keep_batches_status"] == 200
    assert reset_report["keep_batches_rows"] == 0, "همهٔ Batchها باید پاک شده باشند (موجودی صفر)"
    assert reset_report["keep_settings_store_name"] == "فروشگاه آزمایشی فر", "پروفایل فروشگاه حفظ می‌شود"
    assert reset_report["keep_settings_tax"] == "0", "تنظیمات عملیاتی به پیش‌فرض برمی‌گردد"
    assert reset_report["keep_users"] >= 1 and reset_report["me_after_keep"] == 200
    assert reset_report["usable_after_keep"], "پس از بازنشانی باید بتوان کالای تازه ثبت کرد"


def test_full_mode_returns_a_fresh_state_and_reseeds_the_default_bank(reset_report):
    # کالاهای فروشگاه پاک و کاتالوگ پیش‌فرض همراه برنامه بازسازی می‌شود (موجودی صفر)
    reseed = reset_report["catalog_reseeded"] or {}
    assert reseed.get("ok") and int(reseed.get("created", 0)) > 1000, "کاتالوگ پیش‌فرض باید بازسازی شود"
    assert reset_report["full_old_product_hits"] == 0, "کالای ساختهٔ فروشگاه باید پاک شده باشد"
    assert reset_report["full_old_product_batches"] in (0, -1), "موجودی کالای قدیمی نباید برگردد"
    assert (reset_report["full_products_total"] or 0) > 1000, "کاتالوگ پیش‌فرض باید در فهرست دیده شود"
    assert reset_report["full_bank_rows"] > 0, "بانک کالای پیش‌فرض باید سر جایش باشد"
    assert reset_report["full_settings_rows"] > 10, "تنظیمات پیش‌فرض باید بازسازی شوند"
    assert reset_report["full_users"] >= 1 and reset_report["full_me"] == 200, "ورود پس از بازنشانی باید کار کند"
    assert reset_report["full_usable"], "ثبت کالا پس از بازنشانی کامل باید کار کند"
    assert "FACTORY_RESET" in reset_report["audit_actions"], "خود عملیات باید در حسابرسی ثبت شود"
    assert reset_report["manifest_exists"], "نقشهٔ اجراشده باید کنار پشتیبان ذخیره شود"


def test_the_backup_taken_before_the_reset_is_restorable_with_all_the_data(reset_report):
    """قاعدهٔ ایمنی: اگر پشتیبان قابل بازیابی نباشد، بازنشانی اصلاً معنا ندارد."""
    assert reset_report["keep_backup_integrity"] == "ok"
    assert reset_report["keep_backup_invoices"] >= 1, "پشتیبان باید فاکتور پیش از بازنشانی را داشته باشد"
    assert reset_report["keep_backup_items"] >= 1
    assert reset_report["keep_backup_products"] >= 2
    assert reset_report["full_backup_integrity"] == "ok"
    assert reset_report["full_backup_products"] >= 1000, "پشتیبان کامل باید کل کاتالوگ را داشته باشد"


def test_plan_endpoint_is_dry_run_on_the_live_session(client, auth_headers, milk):
    plan = client.get("/api/system/factory-reset/plan", headers=auth_headers)
    assert plan.status_code == 200, plan.text
    data = plan.json()
    assert data["confirmation_phrase"] == "بازنشانی"
    assert data["mode"] == "full" and "keep_catalog" in data["modes"]
    assert data["delete_total"] >= 0 and data["keep"] and data["warnings"]
    # dry-run یعنی هیچ‌چیز تغییر نکرده است
    assert client.get("/api/products", headers=auth_headers).json()["items"], "کالای تست باید سر جایش باشد"
    assert client.get("/api/auth/me", headers=auth_headers).status_code == 200


def test_plan_and_execute_refuse_non_admins(client, auth_headers):
    from tests.test_v488_people import _login, _mkuser

    # کاربر با مجوز settings.manage اما بدون نقش Administrator
    _mkuser(client, auth_headers, "fr_manager", roles=["Manager"])
    headers = _login(client, "fr_manager", "pass1234")
    plan = client.get("/api/system/factory-reset/plan", headers=headers)
    assert plan.status_code == 403, plan.text
    run = client.post("/api/system/factory-reset", headers=headers,
                      json={"confirmation": "بازنشانی", "mode": "full"})
    assert run.status_code == 403, run.text

    # کاربر بدون مجوز تنظیمات
    _mkuser(client, auth_headers, "fr_seller", roles=["Salesperson"])
    seller = _login(client, "fr_seller", "pass1234")
    assert client.get("/api/system/factory-reset/plan", headers=seller).status_code == 403
