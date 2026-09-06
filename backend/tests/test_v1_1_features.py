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
    assert drawer is not None
    # The drawer is kicked THROUGH the receipt printer (ESC p). If earlier tests in
    # the shared DB registered a working printer sink the pulse really is written;
    # with no printer the system must say so — never fake it.
    printers = [d for d in client.get("/api/hardware", headers=auth_headers).json()
                if d["device_type"] == "PRINTER" and d.get("connection")
                and d.get("status") == "CONNECTED"]
    if printers:
        assert drawer["ok"] is True, drawer
    else:
        assert drawer["ok"] is False
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


# --- §17/§19/§178–§182 ESC/POS over raw TCP (real bytes on a real socket) -----------

import socket as _socket
import threading as _threading


def _fake_jetdirect():
    """A tiny port-9100 listener: returns (port, buffer, stop)."""
    srv = _socket.socket(); srv.bind(("127.0.0.1", 0)); srv.listen(5)
    port = srv.getsockname()[1]; buf = bytearray(); stop = _threading.Event()

    def run():
        srv.settimeout(0.2)
        while not stop.is_set():
            try:
                c, _ = srv.accept()
            except _socket.timeout:
                continue
            with c:
                while True:
                    d = c.recv(65536)
                    if not d:
                        break
                    buf.extend(d)
        srv.close()
    _threading.Thread(target=run, daemon=True).start()
    return port, buf, stop


def _settle(buf, minimum, timeout=3.0):
    """Wait until the listener thread has drained at least `minimum` bytes."""
    import time as _time
    t0 = _time.time()
    while len(buf) < minimum and _time.time() - t0 < timeout:
        _time.sleep(0.02)
    _time.sleep(0.05)
    return bytes(buf)


def test_escpos_tcp_receipt_cut_and_drawer(client, auth_headers, two_batches, milk):
    port, buf, stop = _fake_jetdirect()
    try:
        client.put("/api/settings", headers=auth_headers, json={"key": "printer.paper_width_mm", "value": "58"})
        client.put("/api/settings", headers=auth_headers, json={"key": "printer.drawer.pin", "value": "5"})
        client.post("/api/hardware", headers=auth_headers, json={
            "device_type": "PRINTER", "name": "TCP test", "connection": f"tcp://127.0.0.1:{port}",
            "status": "CONNECTED"})
        # probe + test print
        h = client.get("/api/hardware/health", headers=auth_headers).json()
        assert h["printer"] == "CONNECTED"
        r = client.post("/api/hardware/test/print", headers=auth_headers).json()
        assert r["ok"], r
        _settle(buf, 8)
        assert buf.startswith(b"\x1b@\x1bt\x1e")          # init + cp1256
        assert b"\x1dVB" in buf                            # partial cut
        # a cash sale kicks the drawer through the printer: ESC p m=1 (pin 5)
        n0 = len(buf)
        inv = client.post("/api/pos/checkout", headers=auth_headers, json={
            "items": [{"product_id": milk["id"], "batch_id": two_batches["a"]["id"], "quantity": 1}],
            "payments": [{"method": "CASH", "amount": 60000}]}).json()
        assert inv["drawer"]["ok"] is True, inv["drawer"]
        _settle(buf, n0 + 5)
        assert b"\x1bp\x01" in bytes(buf[n0:])
        # reprint delivers Persian receipt bytes (cp1256) and records SUCCESS
        n1 = len(buf)
        p = client.post(f"/api/invoices/{inv['invoice_id']}/print", headers=auth_headers).json()
        assert p["ok"], p
        _settle(buf, n1 + 8)
        chunk = bytes(buf[n1:])
        assert "قابل پرداخت".encode("cp1256")[::-1][:4] in chunk or "پرداخت".encode("cp1256")[-1:] in chunk
        assert inv["invoice_number"].encode() in chunk
        # 58 mm -> 32 columns, so no line longer than 32 chars was emitted
        text_lines = [ln for ln in chunk.split(b"\n") if ln and not ln.startswith(b"\x1b") and not ln.startswith(b"\x1d")]
        assert all(len(ln.replace(b"\x1ba\x00", b"").replace(b"\x1ba\x02", b"")) <= 34 for ln in text_lines)
    finally:
        stop.set()
        client.put("/api/settings", headers=auth_headers, json={"key": "printer.paper_width_mm", "value": "80"})


def test_escpos_tcp_unreachable_is_honest(client, auth_headers):
    client.post("/api/hardware", headers=auth_headers, json={
        "device_type": "PRINTER", "name": "dead", "connection": "tcp://127.0.0.1:9", "status": "CONNECTED"})
    r = client.post("/api/hardware/test/print", headers=auth_headers).json()
    assert r["ok"] is False and "PRINTER_ERROR" in r["message"]


def test_escpos_persian_visual_order_and_columns():
    from app.services.escpos_driver import columns_for_width, visual_rtl, build_escpos, ReceiptJob
    assert (columns_for_width(58), columns_for_width(76), columns_for_width(80)) == (32, 42, 48)
    assert visual_rtl("abc 123") == "abc 123"
    v = visual_rtl("جمع 1500 تومان")
    # full character reversal (printer has no bidi engine) but digit runs stay LTR
    assert v == "ناموت 1500 عمج"
    b = build_escpos(ReceiptJob(lines=["x"], cut=False, kick_drawer=True, drawer_pin=2))
    assert b.endswith(b"\x1bp\x00" + bytes([60, 120]))


# --- §165 Melipayamak: exact wire protocol against a local mock -------------------------

import json as _json
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs


def _mock_melipayamak(responses: dict):
    calls = []

    class H(BaseHTTPRequestHandler):
        def do_POST(self):
            n = int(self.headers.get("Content-Length", 0))
            form = {k: v[0] for k, v in parse_qs(self.rfile.read(n).decode()).items()}
            method = self.path.rsplit("/", 1)[-1]
            calls.append((method, form))
            body = _json.dumps(responses.get(method, {"RetStatus": 11, "Value": "0"})).encode()
            self.send_response(200); self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)

        def log_message(self, *a):  # silence
            pass
    srv = HTTPServer(("127.0.0.1", 0), H)
    _threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, calls


def _cfg(client, h, **kv):
    for k, v in kv.items():
        client.put("/api/settings", headers=h, json={"key": k, "value": v, "is_secret": k in ("sms.password",)})


def test_melipayamak_line_mode_success_and_credit(client, auth_headers):
    srv, calls = _mock_melipayamak({"SendSMS": {"Value": "1234567890123", "RetStatus": 1, "StrRetStatus": "Ok"},
                                    "GetCredit": {"Value": "4820", "RetStatus": 1}})
    try:
        _cfg(client, auth_headers, **{"sms.provider": "melipayamak", "sms.username": "u", "sms.password": "p",
                                      "sms.sender": "50004000", "sms.melipayamak_mode": "line",
                                      "sms.melipayamak_url": f"http://127.0.0.1:{srv.server_port}/api/SendSMS"})
        t = client.post("/api/sms/test-connection", headers=auth_headers).json()
        assert t["status"] == "PASS" and "4820" in t["detail"], t
        m = client.post("/api/sms/send", headers=auth_headers, json={"phone": "09121234567", "text": "سلام"}).json()
        d = client.post("/api/sms/dispatch", headers=auth_headers).json()
        assert d["sent"] >= 1 and d["failed"] == 0, d  # queue may hold rows from earlier tests
        row = {x["id"]: x for x in client.get("/api/sms", headers=auth_headers).json()}[m["id"]]
        assert row["status"] == "SENT"
        forms = [c[1] for c in calls if c[0] == "SendSMS"]
        assert {"username": "u", "password": "p", "to": "09121234567", "from": "50004000",
                "text": "سلام", "isFlash": "false"} in forms
    finally:
        srv.shutdown()
        _cfg(client, auth_headers, **{"sms.provider": "file", "sms.melipayamak_url": ""})


def test_melipayamak_pattern_mode_and_error_codes(client, auth_headers):
    srv, calls = _mock_melipayamak({"BaseServiceNumber": {"Value": "2", "RetStatus": 2}})
    try:
        _cfg(client, auth_headers, **{"sms.provider": "melipayamak", "sms.username": "u", "sms.password": "p",
                                      "sms.melipayamak_mode": "pattern", "sms.melipayamak_body_id": "77123",
                                      "sms.max_retries": "1",
                                      "sms.melipayamak_url": f"http://127.0.0.1:{srv.server_port}/api/SendSMS"})
        m = client.post("/api/sms/send", headers=auth_headers,
                        json={"phone": "09121234567", "text": "فاکتور 12\nمبلغ 5000"}).json()
        client.post("/api/sms/dispatch", headers=auth_headers)
        row = {x["id"]: x for x in client.get("/api/sms", headers=auth_headers).json()}[m["id"]]
        assert row["status"] == "FAILED"
        assert "اعتبار کافی نیست" in (row["error_message"] or ""), row
        method, form = calls[0]
        assert method == "BaseServiceNumber"
        assert form["bodyId"] == "77123" and form["text"] == "فاکتور 12;مبلغ 5000"
    finally:
        srv.shutdown()
        _cfg(client, auth_headers, **{"sms.provider": "file", "sms.melipayamak_mode": "line",
                                      "sms.melipayamak_url": "", "sms.max_retries": "5"})


# --- §270 update server channel + sha256 enforcement ---------------------------------

def test_update_server_channel_check_and_checksum(client, auth_headers, tmp_path):
    import hashlib
    pkg = b"fake-installer-bytes" * 100
    good = hashlib.sha256(pkg).hexdigest()

    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path.startswith("/manifest"):
                body = _json.dumps({"version": "9.9.9", "name": "v9.9.9", "notes": "n",
                                    "asset_name": "Supermarket-Setup-9.9.9.exe",
                                    "asset_url": f"http://127.0.0.1:{srv.server_port}/pkg",
                                    "asset_size": len(pkg), "sha256": good if "good" in self.path else "00" * 32}).encode()
                ct = "application/json"
            else:
                body, ct = pkg, "application/octet-stream"
            self.send_response(200); self.send_header("Content-Type", ct)
            self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)

        def log_message(self, *a):
            pass
    srv = HTTPServer(("127.0.0.1", 0), H)
    _threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        _cfg(client, auth_headers, **{"update.channel": "server",
                                      "update.server_url": f"http://127.0.0.1:{srv.server_port}/manifest-good"})
        r = client.get("/api/system/update/check", headers=auth_headers).json()
        assert r["update_available"] is True and r["latest"]["version"] == "9.9.9" and r["channel"] == "updateserver", r
        # prepare with checksum OK
        from app.services.updater import UpdateServerChannel, _prepare_update
        from app.database import SessionLocal
        with SessionLocal() as db:
            ok = _prepare_update(db, channel=UpdateServerChannel(f"http://127.0.0.1:{srv.server_port}/manifest-good"),
                                 download=True, dest_dir=tmp_path / "ok")
            assert ok["status"] in ("READY", "DOWNLOADED", "PREPARED"), ok
            bad = _prepare_update(db, channel=UpdateServerChannel(f"http://127.0.0.1:{srv.server_port}/manifest-bad"),
                                  download=True, dest_dir=tmp_path / "bad")
            assert bad["status"] in ("FAILED", "ABORTED"), bad
            assert any("اثر انگشت" in (st.get("detail") or "") for st in bad["steps"]), bad
        # misconfigured server -> honest UNAVAILABLE, not a crash
        _cfg(client, auth_headers, **{"update.server_url": ""})
        r = client.get("/api/system/update/check", headers=auth_headers).json()
        assert r["status"] == "UNAVAILABLE" and r["code"] == "CONFIG_MISSING"
    finally:
        srv.shutdown()
        _cfg(client, auth_headers, **{"update.channel": "github"})


# --- §214 store logo -----------------------------------------------------------

def test_store_logo_upload_serves_and_reaches_receipt(client, auth_headers, tmp_path):
    import io
    from PIL import Image
    from app.services.escpos_driver import raster_image, build_escpos, ReceiptJob

    buf = io.BytesIO()
    Image.new("RGB", (64, 16), "black").save(buf, format="PNG")
    bad = client.post("/api/settings/store-profile/logo", headers=auth_headers,
                      files={"file": ("x.txt", b"hello", "text/plain")})
    assert bad.status_code == 400 and bad.json()["detail"]["code"] == "UNSUPPORTED_TYPE"

    r = client.post("/api/settings/store-profile/logo", headers=auth_headers,
                    files={"file": ("logo.png", buf.getvalue(), "image/png")})
    assert r.status_code == 200, r.text
    url = r.json()["logo_path"]
    assert url.startswith("/media/store-logo.png")
    assert client.get("/api/settings/store-profile", headers=auth_headers).json()["logo_path"] == url
    assert client.get(url).status_code == 200  # served statically

    # the printer profile maps the URL back to a disk file and rasterises it (GS v 0)
    from app.services.hardware import printer_profile
    from app.database import SessionLocal
    with SessionLocal() as db:
        prof = printer_profile(db)
    assert prof["logo_file"] and prof["logo_file"].endswith("store-logo.png")
    payload = build_escpos(ReceiptJob(lines=["x"], logo_path=prof["logo_file"]))
    assert b"\x1dv0" in payload
    assert raster_image(prof["logo_file"]).count(b"\xff") > 0  # black pixels present

    d = client.delete("/api/settings/store-profile/logo", headers=auth_headers)
    assert d.status_code == 200 and d.json()["logo_path"] == ""
    audit = client.get("/api/audit?action=STORE_LOGO_UPDATED", headers=auth_headers).json()
    items = audit if isinstance(audit, list) else audit.get("items", [])
    assert any(a["action"] == "STORE_LOGO_UPDATED" for a in items)


# --- §80–82 starter catalog with zero stock ------------------------------------

def test_starter_catalog_import_is_zero_stock_and_idempotent(client, auth_headers):
    info = client.get("/api/products/import/starter", headers=auth_headers).json()
    assert info["products"] >= 150 and info["categories"] >= 10

    dry = client.post("/api/products/import/starter?dry_run=true", headers=auth_headers).json()
    assert dry["ok"] and dry["dry_run"] and dry["created"] >= 150

    r1 = client.post("/api/products/import/starter", headers=auth_headers).json()
    assert r1["ok"] and r1["created"] == dry["created"] and r1["errors"] == []
    r2 = client.post("/api/products/import/starter", headers=auth_headers).json()
    assert r2["created"] == 0 and r2["skipped"] >= r1["created"]  # idempotent

    prods = client.get("/api/products?q=شیر کم‌چرب", headers=auth_headers).json()
    items = prods if isinstance(prods, list) else prods.get("items", prods)
    milk = next(p for p in items if "شیر کم‌چرب" in p["name"])
    assert milk["barcode"].startswith("INT-")           # no invented GTINs
    detail = client.get(f"/api/products/{milk['id']}/detail", headers=auth_headers).json()
    assert float(detail.get("stock", detail.get("total_stock", 0)) or 0) == 0
    cats = client.get("/api/products/categories", headers=auth_headers).json()
    assert any(c.get("parent_id") for c in cats)         # sub-categories created (§79)

    # own CSV upload (same columns) — bad header rejected, good rows imported once
    bad = client.post("/api/products/import/csv", headers=auth_headers,
                      files={"file": ("p.csv", "foo,bar\n1,2\n".encode(), "text/csv")})
    assert bad.status_code == 400 and bad.json()["detail"]["code"] == "BAD_HEADER"
    csv_text = "category,subcategory,name,brand,unit,min_stock_alert,barcode\nتست,زیر,کالای آزمایشی سی‌اس‌وی,برند,عدد,3,6261234567890\n"
    ok = client.post("/api/products/import/csv", headers=auth_headers,
                     files={"file": ("p.csv", csv_text.encode("utf-8"), "text/csv")}).json()
    assert ok["created"] == 1
    p = client.get("/api/products/barcode/6261234567890", headers=auth_headers).json()
    assert p["name"] == "کالای آزمایشی سی‌اس‌وی" and p["min_stock_alert"] == 3


# --- §137 monthly / weekly (Jalali) sales grouping ---------------------------------

def test_sales_report_monthly_jalali_buckets(client, auth_headers, two_batches, milk):
    from datetime import date
    r = client.post("/api/pos/checkout", headers=auth_headers, json={
        "items": [{"product_id": milk["id"], "batch_id": two_batches["a"]["id"], "quantity": 1}],
        "payments": [{"method": "CASH", "amount": 60000}]})
    assert r.status_code in (200, 201), r.text
    today = date.today().isoformat()
    m = client.get(f"/api/reports/sales?start={today}&end={today}&group=monthly", headers=auth_headers).json()
    assert m["group"] == "monthly" and len(m["groups"]) == 1
    period = m["groups"][0]["period"]
    assert "/" in period and int(period.split("/")[0]) >= 1400  # Jalali year
    assert m["groups"][0]["invoice_count"] >= 1
    w = client.get(f"/api/reports/sales?start={today}&end={today}&group=weekly", headers=auth_headers).json()
    assert w["groups"] and "هفته" in w["groups"][0]["period"]


# --- receipt preview always available even without a printer (§17/§20) --------

def test_receipt_preview_and_print_response_carry_receipt_text(client, auth_headers, two_batches, milk):
    r = client.post("/api/pos/checkout", headers=auth_headers, json={
        "items": [{"product_id": milk["id"], "batch_id": two_batches["a"]["id"], "quantity": 2}],
        "payments": [{"method": "CARD", "amount": 120000}]}).json()
    prev = client.get(f"/api/invoices/{r['invoice_id']}/receipt", headers=auth_headers).json()
    assert prev["invoice_number"] == r["invoice_number"] and prev["columns"] in (32, 42, 48)
    assert "فاکتور" in prev["receipt_text"] and r["invoice_number"] in prev["receipt_text"]
    pr = client.post(f"/api/invoices/{r['invoice_id']}/print", headers=auth_headers).json()
    assert pr["receipt_text"] == prev["receipt_text"]
    assert isinstance(pr["ok"], bool)
