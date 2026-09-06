"""v1.1.0 — features added by the 350-item completeness audit.

Each test is a real HTTP round-trip through the app (§57: DONE = code +
execution + expected result). Covered here:

  §12  invoice-level discount at checkout (stored, tax after discount)
  §19  cash-drawer pulse attempted on cash sales (honest UNAVAILABLE)
  §79  sub-categories (parent_id, path)
  §109/§130/§131 warehouses, storage locations, batch transfer
  §166 editable SMS patterns, §171 manual retry, §175 management report SMS,
  §176 low-stock alert SMS, §177 provider test
  §209 admin-password confirmation to void a PAID invoice
  §215–§229 settings categories seeded
"""
from __future__ import annotations

H = None


def _h(auth_headers):
    return auth_headers


# --- §12 invoice discount -----------------------------------------------------

def test_invoice_discount_applied_once_and_stored(client, auth_headers, two_batches, milk):
    a = two_batches["a"]["id"]
    # 2 x 60000 = 120000 gross; invoice discount 20000 -> 100000 total
    r = client.post("/api/pos/checkout", headers=auth_headers, json={
        "items": [{"product_id": milk["id"], "batch_id": a, "quantity": 2}],
        "payments": [{"method": "CARD", "amount": 100000}],
        "invoice_discount": 20000})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["total_amount"] == 100000
    assert body["discount"] == 20000
    assert body["invoice_discount"] == 20000
    assert body["drawer"] is None  # card sale -> no drawer pulse


def test_invoice_discount_cannot_exceed_cart(client, auth_headers, two_batches, milk):
    a = two_batches["a"]["id"]
    r = client.post("/api/pos/checkout", headers=auth_headers, json={
        "items": [{"product_id": milk["id"], "batch_id": a, "quantity": 1}],
        "payments": [{"method": "CASH", "amount": 0}],
        "invoice_discount": 70000})
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "INVALID_DISCOUNT"


def test_cart_validate_reports_invoice_discount(client, auth_headers, two_batches, milk):
    a = two_batches["a"]["id"]
    r = client.post("/api/pos/cart/validate", headers=auth_headers, json={
        "items": [{"product_id": milk["id"], "batch_id": a, "quantity": 1}],
        "invoice_discount": 10000})
    assert r.status_code == 200, r.text
    t = r.json()["totals"]
    assert t["invoice_discount"] == 10000 and t["subtotal"] == 50000


# --- §19 cash drawer on cash sale --------------------------------------------

def test_cash_sale_attempts_drawer_pulse_honestly(client, auth_headers, two_batches, milk):
    a = two_batches["a"]["id"]
    r = client.post("/api/pos/checkout", headers=auth_headers, json={
        "items": [{"product_id": milk["id"], "batch_id": a, "quantity": 1}],
        "payments": [{"method": "CASH", "amount": 60000}]})
    assert r.status_code == 201, r.text
    drawer = r.json()["drawer"]
    # No drawer is registered in the test DB — the system must say so, never fake it.
    assert drawer is not None and drawer["ok"] is False
    assert "CASH_DRAWER_UNAVAILABLE" in drawer["message"]


# --- §209 void PAID needs admin password ---------------------------------------

def test_void_paid_requires_admin_password(client, auth_headers, two_batches, milk):
    a = two_batches["a"]["id"]
    inv = client.post("/api/pos/checkout", headers=auth_headers, json={
        "items": [{"product_id": milk["id"], "batch_id": a, "quantity": 1}],
        "payments": [{"method": "CASH", "amount": 60000}]}).json()
    r = client.post(f"/api/invoices/{inv['invoice_id']}/void", headers=auth_headers,
                    json={"reason": "x", "admin_password": "wrong"})
    assert r.status_code == 401
    assert r.json()["detail"]["code"] == "ADMIN_PASSWORD_REQUIRED"
    # the denied attempt is in the audit trail
    logs = client.get("/api/audit?action=VOID_DENIED", headers=auth_headers).json()
    items = logs if isinstance(logs, list) else logs.get("items", [])
    assert any(l.get("action") == "VOID_DENIED" for l in items)
    r = client.post(f"/api/invoices/{inv['invoice_id']}/void", headers=auth_headers,
                    json={"reason": "x", "admin_password": "admin123"})
    assert r.status_code == 200 and r.json()["status"] == "VOID"


# --- §79 sub-categories --------------------------------------------------------

def test_subcategory_parent_and_path(client, auth_headers):
    parent = client.post("/api/products/categories", headers=auth_headers,
                         json={"name": "لبنیات-تست"}).json()
    child = client.post("/api/products/categories", headers=auth_headers,
                        json={"name": "پنیر-تست", "parent_id": parent["id"]})
    assert child.status_code == 201, child.text
    assert child.json()["parent_id"] == parent["id"]
    cats = client.get("/api/products/categories", headers=auth_headers).json()
    row = next(c for c in cats if c["id"] == child.json()["id"])
    assert row["parent_name"] == "لبنیات-تست"
    assert row["path"] == "لبنیات-تست / پنیر-تست"
    r = client.post("/api/products/categories", headers=auth_headers,
                    json={"name": "x", "parent_id": 999999})
    assert r.status_code == 404


# --- §109 / §130 / §131 warehouses ------------------------------------------------

def test_default_warehouse_created_and_listed(client, auth_headers):
    r = client.get("/api/warehouses", headers=auth_headers)
    assert r.status_code == 200, r.text
    rows = r.json()
    assert any(w["is_default"] for w in rows)


def test_create_warehouse_location_and_transfer(client, auth_headers, two_batches, milk):
    w = client.post("/api/warehouses", headers=auth_headers,
                    json={"name": "انبار پشتی", "code": "BACK"})
    assert w.status_code == 201, w.text
    wid = w.json()["id"]
    loc = client.post(f"/api/warehouses/{wid}/locations", headers=auth_headers,
                      json={"name": "قفسه A1"})
    assert loc.status_code == 201, loc.text

    a = two_batches["a"]  # qty 10
    r = client.post("/api/warehouses/transfer", headers=auth_headers, json={
        "batch_id": a["id"], "quantity": 4, "to_warehouse_id": wid,
        "to_location_id": loc.json()["id"], "reason": "چیدمان"})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["source_current_qty"] == 6
    assert out["dest_current_qty"] == 4 and out["dest_batch_id"] != a["id"]
    assert out["dest_warehouse_id"] == wid

    # the destination batch keeps the SAME cost basis (§104 real COGS)
    dest = client.get(f"/api/batches/{out['dest_batch_id']}", headers=auth_headers).json()
    assert dest["buy_price"] == a["buy_price"] and dest["sell_price"] == a["sell_price"]
    assert dest["warehouse_id"] == wid

    # both TRANSFER movements exist
    mv = client.get("/api/inventory/movements?limit=50", headers=auth_headers).json()
    kinds = [m["movement_type"] for m in mv]
    assert "TRANSFER_OUT" in kinds and "TRANSFER_IN" in kinds

    # stock is conserved: 6 + 4 + batch B 20 = 30
    stock = client.get("/api/inventory/stock", headers=auth_headers).json()
    me = next(s for s in stock if s["product_id"] == milk["id"])
    assert me["total_stock"] == 30

    # over-transfer refused
    r = client.post("/api/warehouses/transfer", headers=auth_headers, json={
        "batch_id": a["id"], "quantity": 999, "to_warehouse_id": wid})
    assert r.status_code == 400


# --- SMS §166 / §171 / §175 / §176 / §177 -------------------------------------------

def _use_file_provider(client, auth_headers, tmp_path):
    client.put("/api/settings", headers=auth_headers,
               json={"key": "sms.provider", "value": "file"})
    client.put("/api/settings", headers=auth_headers,
               json={"key": "sms.file_path", "value": str(tmp_path / "sms.log")})
    client.put("/api/settings", headers=auth_headers,
               json={"key": "sms.admin_phone", "value": "09120000000"})


def test_sms_templates_listed_with_placeholders(client, auth_headers):
    r = client.get("/api/sms/templates", headers=auth_headers)
    assert r.status_code == 200, r.text
    kinds = {t["kind"]: t for t in r.json()}
    assert {"invoice", "debt_reminder", "coupon", "low_stock", "daily_report"} <= set(kinds)
    assert "amount" in kinds["invoice"]["placeholders"]


def test_sms_test_connection_and_daily_report(client, auth_headers, tmp_path):
    _use_file_provider(client, auth_headers, tmp_path)
    r = client.post("/api/sms/test-connection", headers=auth_headers)
    assert r.status_code == 200 and r.json()["status"] == "PASS", r.text

    r = client.post("/api/sms/daily-report", headers=auth_headers)
    assert r.status_code == 201, r.text
    assert "گزارش" in r.json()["text"]
    sid = r.json()["id"]
    d = client.post("/api/sms/dispatch", headers=auth_headers).json()
    assert d["sent"] >= 1
    rows = {m["id"]: m for m in client.get("/api/sms", headers=auth_headers).json()}
    assert rows[sid]["status"] == "SENT"
    # already sent -> retry refused (409)
    assert client.post(f"/api/sms/{sid}/retry", headers=auth_headers).status_code == 409


def test_sms_manual_retry_requeues_failed(client, auth_headers, tmp_path):
    client.put("/api/settings", headers=auth_headers, json={"key": "sms.provider", "value": "fail"})
    client.put("/api/settings", headers=auth_headers, json={"key": "sms.max_retries", "value": "1"})
    msg = client.post("/api/sms/send", headers=auth_headers,
                      json={"phone": "09121111111", "text": "retry me"}).json()
    client.post("/api/sms/dispatch", headers=auth_headers)
    rows = {m["id"]: m for m in client.get("/api/sms", headers=auth_headers).json()}
    assert rows[msg["id"]]["status"] == "FAILED"
    r = client.post(f"/api/sms/{msg['id']}/retry", headers=auth_headers)
    assert r.status_code == 200 and r.json()["status"] == "PENDING"
    assert client.post("/api/sms/999999/retry", headers=auth_headers).status_code == 404
    # restore
    client.put("/api/settings", headers=auth_headers, json={"key": "sms.provider", "value": "file"})
    client.put("/api/settings", headers=auth_headers, json={"key": "sms.max_retries", "value": "5"})


def test_low_stock_alert_sms_queued_by_scan(client, auth_headers, tmp_path):
    _use_file_provider(client, auth_headers, tmp_path)
    client.put("/api/settings", headers=auth_headers,
               json={"key": "sms.low_stock_alert", "value": "true"})
    p = client.post("/api/products", headers=auth_headers,
                    json={"name": "کالای کم‌موجود", "min_stock_alert": 50}).json()
    client.post("/api/batches/receive", headers=auth_headers, json={
        "product_id": p["id"], "quantity_received": 1, "buy_price": 10, "sell_price": 20})
    r = client.post("/jobs/expiry-scan", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert r.json().get("low_stock", 0) >= 1
    assert r.json().get("low_stock_sms_id")
    rows = {m["id"]: m for m in client.get("/api/sms", headers=auth_headers).json()}
    txt = rows[r.json()["low_stock_sms_id"]]["text"]
    assert "هشدار انبار" in txt and "کالای کم‌موجود" in txt
    client.put("/api/settings", headers=auth_headers,
               json={"key": "sms.low_stock_alert", "value": "false"})


def test_invoice_sms_uses_editable_pattern(client, auth_headers, two_batches, milk, tmp_path):
    _use_file_provider(client, auth_headers, tmp_path)
    client.put("/api/settings", headers=auth_headers,
               json={"key": "sms.template.invoice", "value": "TPL {invoice} = {amount}"})
    a = two_batches["a"]["id"]
    inv = client.post("/api/pos/checkout", headers=auth_headers, json={
        "items": [{"product_id": milk["id"], "batch_id": a, "quantity": 1}],
        "payments": [{"method": "CASH", "amount": 60000}],
        "customer_phone": "09125555555"}).json()
    rows = client.get("/api/sms", headers=auth_headers).json()
    mine = [m for m in rows if inv["invoice_number"] in m["text"]]
    assert mine and mine[0]["text"].startswith("TPL ")


# --- §215–§229 settings categories -------------------------------------------------

def test_settings_cover_all_required_categories(client, auth_headers):
    keys = {s["key"] for s in client.get("/api/settings", headers=auth_headers).json()}
    for prefix in ("store.", "pos.", "inventory.", "stocktake.", "expiry.", "products.",
                   "barcode.", "pricing.", "customers.", "ledger.", "marketing.", "sms.",
                   "sms.template.", "printer.", "printer.drawer.", "network.", "security.",
                   "backup.", "time.", "ui.", "sync."):
        assert any(k.startswith(prefix) for k in keys), prefix
    assert "pos.currency" in keys
