"""Phase-3 acceptance tests: real SMS pipeline (BUG-015), honest printing
(BUG-016), kiosk unlock (§7), customers API."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

_TMP = Path(tempfile.mkdtemp(prefix="supermarket_p3_"))
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_TMP / 'p3.db'}")

from fastapi.testclient import TestClient  # noqa: E402

from app.database import init_db  # noqa: E402
from app.main import app  # noqa: E402

init_db()


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def admin_h(client):
    r = client.post("/api/auth/login", data={"username": "admin", "password": "admin123"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture(scope="module")
def cashier_h(client, admin_h):
    client.post("/api/users", headers=admin_h, json={
        "username": "kasa3", "password": "kasa1234", "full_name": "Cashier 3", "roles": ["Cashier"]})
    r = client.post("/api/auth/login", data={"username": "kasa3", "password": "kasa1234"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def set_setting(client, H, key, value):
    r = client.put("/api/settings", headers=H, json={"key": key, "value": value})
    assert r.status_code == 200, r.text


_n = 0


def _mk_product_batch(client, H, qty=5, buy=1000, sell=2000):
    global _n
    _n += 1
    p = client.post("/api/products", headers=H,
                    json={"barcode": f"91000000000{_n:04d}", "name": f"P3 T{_n}"}).json()
    b = client.post("/api/batches/receive", headers=H,
                    json={"product_id": p["id"], "quantity_received": qty,
                          "buy_price": buy, "sell_price": sell}).json()
    return p, b


# --- SMS: honest pipeline (BUG-015) ---------------------------------------------

def test_sms_file_provider_delivers(client, admin_h, tmp_path):
    log = tmp_path / "sms_out.log"
    set_setting(client, admin_h, "sms.worker_interval_seconds", "3600")  # deterministic tests
    set_setting(client, admin_h, "sms.file_path", str(log))
    set_setting(client, admin_h, "sms.provider", "file")

    r = client.post("/api/sms/send", headers=admin_h,
                    json={"phone": "09120000001", "text": "پیام تست فروشگاه"})
    assert r.status_code == 201
    msg_id = r.json()["id"]

    d = client.post("/api/sms/dispatch", headers=admin_h).json()
    assert d["sent"] >= 1

    rows = client.get("/api/sms", headers=admin_h).json()
    mine = next(m for m in rows if m["id"] == msg_id)
    assert mine["status"] == "SENT" and mine["sent_at"]
    assert "09120000001" in log.read_text(encoding="utf-8")


def test_sms_no_provider_stays_pending_honestly(client, admin_h):
    set_setting(client, admin_h, "sms.provider", "")
    r = client.post("/api/sms/send", headers=admin_h,
                    json={"phone": "09120000002", "text": "queued without provider"})
    assert r.status_code == 201
    msg_id = r.json()["id"]
    d = client.post("/api/sms/dispatch", headers=admin_h).json()
    assert d["reason"] == "NO_PROVIDER_CONFIGURED"
    rows = client.get("/api/sms", headers=admin_h).json()
    mine = next(m for m in rows if m["id"] == msg_id)
    assert mine["status"] == "PENDING", "must never be faked as SENT"


def test_sms_failure_retries_then_fails(client, admin_h):
    set_setting(client, admin_h, "sms.provider", "fail")
    set_setting(client, admin_h, "sms.max_retries", "2")
    r = client.post("/api/sms/send", headers=admin_h,
                    json={"phone": "09120000003", "text": "will fail"})
    msg_id = r.json()["id"]

    client.post("/api/sms/dispatch", headers=admin_h)
    rows = client.get("/api/sms", headers=admin_h).json()
    mine = next(m for m in rows if m["id"] == msg_id)
    assert mine["status"] == "RETRYING" and mine["retry_count"] == 1
    assert "ALWAYS_FAIL" in mine["error_message"]

    client.post("/api/sms/dispatch", headers=admin_h)
    rows = client.get("/api/sms", headers=admin_h).json()
    mine = next(m for m in rows if m["id"] == msg_id)
    assert mine["status"] == "FAILED" and mine["retry_count"] == 2
    set_setting(client, admin_h, "sms.provider", "")


# --- Printing honesty (BUG-016) ----------------------------------------------------

def test_print_never_fakes_success_without_driver(client, admin_h):
    p, b = _mk_product_batch(client, admin_h)
    inv = client.post("/api/pos/checkout", headers=admin_h, json={
        "items": [{"product_id": p["id"], "batch_id": b["id"], "quantity": 1}],
        "payments": [{"method": "CASH", "amount": 2000}]}).json()

    # a "CONNECTED" printer with no real connection/driver
    client.post("/api/hardware", headers=admin_h, json={
        "device_type": "PRINTER", "name": "Ghost Printer", "status": "CONNECTED"})
    r = client.post(f"/api/invoices/{inv['invoice_id']}/print", headers=admin_h).json()
    assert r["ok"] is False
    assert r["print_status"] == "FAILED"
    assert "NOT_SUPPORTED" in r["message"]
    audit = client.get("/api/audit?action=PRINT_FAILED", headers=admin_h).json()
    assert any("Ghost" or a["reference"] for a in audit)

    # the sale itself is untouched (§20)
    got = client.get(f"/api/invoices/{inv['invoice_id']}", headers=admin_h).json()
    assert got["status"] == "PAID"


def test_print_real_file_sink_and_escpos_driver_missing(client, admin_h, tmp_path):
    p, b = _mk_product_batch(client, admin_h)
    inv = client.post("/api/pos/checkout", headers=admin_h, json={
        "items": [{"product_id": p["id"], "batch_id": b["id"], "quantity": 1}],
        "payments": [{"method": "CASH", "amount": 2000}]}).json()

    sink = tmp_path / "receipt.txt"
    client.post("/api/hardware", headers=admin_h, json={
        "device_type": "PRINTER", "name": "File sink", "status": "CONNECTED",
        "connection": f"file://{sink}"})
    r = client.post(f"/api/invoices/{inv['invoice_id']}/print", headers=admin_h).json()
    assert r["ok"] is True and r["print_status"] == "SUCCESS"
    assert sink.exists() and "INVOICE" in sink.read_text(encoding="utf-8")

    client.post("/api/hardware", headers=admin_h, json={
        "device_type": "PRINTER", "name": "EscposPrinter", "status": "CONNECTED",
        "connection": "escpos:usb:0416:5011"})
    r2 = client.post("/api/hardware/test/print", headers=admin_h).json()
    # honest: driver package not installed in this environment
    assert r2["ok"] is False
    assert "DRIVER_UNAVAILABLE" in r2["message"] or "escpos" in r2["message"]


# --- Kiosk (§7) ----------------------------------------------------------------------

def test_kiosk_config_available_to_cashier(client, cashier_h):
    r = client.get("/api/pos/kiosk/config", headers=cashier_h)
    assert r.status_code == 200
    assert r.json()["shortcut"]


def test_kiosk_unlock_requires_admin(client, admin_h, cashier_h):
    # wrong password -> 401
    r = client.post("/api/pos/kiosk/unlock",
                    json={"username": "admin", "password": "wrong"})
    assert r.status_code == 401
    # cashier (no settings.manage) -> 403 even with correct password
    r = client.post("/api/pos/kiosk/unlock",
                    json={"username": "kasa3", "password": "kasa1234"})
    assert r.status_code == 403
    # admin -> ok
    r = client.post("/api/pos/kiosk/unlock",
                    json={"username": "admin", "password": "admin123"})
    assert r.status_code == 200 and r.json()["ok"] is True
    audit = client.get("/api/audit?action=KIOSK_UNLOCKED", headers=admin_h).json()
    assert len(audit) >= 1
    denied = client.get("/api/audit?action=KIOSK_UNLOCK_DENIED", headers=admin_h).json()
    assert len(denied) >= 1


# --- Customers (POS integration) ------------------------------------------------------

def test_customers_idempotent_create_and_lookup(client, cashier_h):
    r1 = client.post("/api/customers", headers=cashier_h,
                     json={"name": "علی احمدی", "phone": "09123334455"})
    assert r1.status_code == 201
    r2 = client.post("/api/customers", headers=cashier_h,
                     json={"name": "_duplicate", "phone": "09123334455"})
    assert r2.json()["id"] == r1.json()["id"], "same phone must not duplicate"
    got = client.get("/api/customers/phone/09123334455", headers=cashier_h)
    assert got.status_code == 200 and got.json()["name"] == "علی احمدی"
    missing = client.get("/api/customers/phone/09120000999", headers=cashier_h)
    assert missing.status_code == 404
    lst = client.get("/api/customers?q=0912333", headers=cashier_h)
    assert any(c["phone"] == "09123334455" for c in lst.json())
