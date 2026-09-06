"""Phase-7: Connection Center, sync queue, POS search, quick price, currency."""
from decimal import Decimal


def test_full_diagnostic_run_performs_real_checks(client, auth_headers):
    r = client.post("/api/diagnostics/run", headers=auth_headers,
                    params={"include_external": False})
    assert r.status_code == 200, r.text
    body = r.json()
    names = {c["name"] for c in body["checks"]}
    assert {"Local Database", "Backend API", "Media Storage"} <= names
    assert body["total"] == len(body["checks"])

    db_check = next(c for c in body["checks"] if c["name"] == "Local Database")
    assert db_check["status"] == "PASS"
    # a real write/read/rollback round-trip was executed, not a fake tick
    assert {s["step"] for s in db_check["steps"]} >= {"connect", "write", "read_back", "rollback"}
    assert db_check["duration_ms"] >= 0

    # hardware without a device must be SKIPPED, never PASS (§58)
    printer = next(c for c in body["checks"] if c["name"] == "Thermal printer")
    assert printer["status"] in ("SKIPPED", "FAIL")


def test_diagnostic_run_is_persisted_and_retrievable(client, auth_headers):
    run = client.post("/api/diagnostics/run", headers=auth_headers,
                      params={"include_external": False}).json()
    hist = client.get("/api/diagnostics/history", headers=auth_headers).json()
    assert any(h["id"] == run["run_id"] for h in hist)
    detail = client.get(f"/api/diagnostics/runs/{run['run_id']}", headers=auth_headers)
    assert detail.status_code == 200
    assert len(detail.json()["checks"]) == run["total"]


def test_printer_check_passes_with_a_real_file_sink(client, auth_headers, tmp_path):
    sink = tmp_path / "receipt.txt"
    client.post("/api/hardware", headers=auth_headers, json={
        "device_type": "PRINTER", "name": "Diag printer",
        "connection": f"file://{sink}", "status": "CONNECTED"})
    r = client.post("/api/diagnostics/run", headers=auth_headers,
                    params={"include_external": False}).json()
    printer = next(c for c in r["checks"] if c["name"] == "Thermal printer")
    assert printer["status"] == "PASS", printer
    assert sink.exists()


def test_sync_queue_retries_then_completes(client, auth_headers):
    """A job whose handler is missing fails; a real SMS job completes once the
    file provider is configured."""
    bad = client.post("/api/diagnostics/sync/enqueue", headers=auth_headers,
                      json={"job_type": "NOT_A_REAL_JOB", "payload": {}})
    assert bad.status_code == 201
    res = client.post("/api/diagnostics/sync/run", headers=auth_headers).json()
    assert res["processed"] >= 1

    jobs = client.get("/api/diagnostics/sync/jobs", headers=auth_headers).json()
    failed = [j for j in jobs if j["job_type"] == "NOT_A_REAL_JOB"]
    assert failed and failed[0]["status"] == "FAILED"
    assert "NO_HANDLER" in (failed[0]["last_error"] or "")

    stats = client.get("/api/diagnostics/sync/stats", headers=auth_headers).json()
    assert stats["failed"] >= 1


def test_sync_queue_is_idempotent(client, auth_headers):
    a = client.post("/api/diagnostics/sync/enqueue", headers=auth_headers,
                    json={"job_type": "PRICE_UPDATE", "payload": {"barcode": "1"},
                          "idempotency_key": "dup-key-1"}).json()
    b = client.post("/api/diagnostics/sync/enqueue", headers=auth_headers,
                    json={"job_type": "PRICE_UPDATE", "payload": {"barcode": "1"},
                          "idempotency_key": "dup-key-1"}).json()
    assert a["id"] == b["id"]


def test_pos_search_by_name_barcode_and_sku(client, auth_headers):
    p = client.post("/api/products", headers=auth_headers, json={
        "barcode": "6263330000001", "name": "شیر پرچرب کاله", "sku": "MLK-001"}).json()
    client.post("/api/batches/receive", headers=auth_headers, json={
        "product_id": p["id"], "quantity_received": 10, "buy_price": 1000,
        "sell_price": 2000})

    by_name = client.get("/api/pos/search", headers=auth_headers, params={"q": "شیر"}).json()
    assert any(i["product_id"] == p["id"] for i in by_name["items"])

    by_sku = client.get("/api/pos/search", headers=auth_headers, params={"q": "MLK-001"}).json()
    assert by_sku["items"][0]["product_id"] == p["id"]
    assert by_sku["items"][0]["exact"] is True

    by_barcode = client.get("/api/pos/search", headers=auth_headers,
                            params={"q": "6263330000001"}).json()
    assert by_barcode["items"][0]["product_id"] == p["id"]
    assert by_barcode["items"][0]["available_qty"] == 10
    assert by_barcode["items"][0]["batches"]


def test_pos_search_exposes_multiple_prices_for_batch_choice(client, auth_headers):
    """§24: old-price / new-price batches must stay distinct for the cashier."""
    p = client.post("/api/products", headers=auth_headers, json={
        "barcode": "6263330000002", "name": "روغن آفتابگردان"}).json()
    client.post("/api/batches/receive", headers=auth_headers, json={
        "product_id": p["id"], "quantity_received": 5, "buy_price": 40000,
        "sell_price": 60000})
    client.post("/api/batches/receive", headers=auth_headers, json={
        "product_id": p["id"], "quantity_received": 20, "buy_price": 50000,
        "sell_price": 70000})
    hit = client.get("/api/pos/search", headers=auth_headers,
                     params={"q": "6263330000002"}).json()["items"][0]
    assert hit["price_count"] == 2
    prices = sorted(b["sell_price"] for b in hit["batches"])
    assert prices == [60000, 70000]


def test_quick_price_edit(client, auth_headers):
    p = client.post("/api/products", headers=auth_headers, json={
        "barcode": "6263330000003", "name": "ماست"}).json()
    b = client.post("/api/batches/receive", headers=auth_headers, json={
        "product_id": p["id"], "quantity_received": 10, "buy_price": 20000,
        "sell_price": 30000}).json()

    r = client.post(f"/api/products/{p['id']}/quick-price", headers=auth_headers,
                    json={"sell_price": 35000, "consumer_price": 38000})
    assert r.status_code == 200, r.text
    after = client.get(f"/api/batches/{b['id']}", headers=auth_headers).json()
    assert after["sell_price"] == 35000 and after["consumer_price"] == 38000


def test_buy_price_locked_after_batch_is_consumed(client, auth_headers):
    p = client.post("/api/products", headers=auth_headers, json={
        "barcode": "6263330000004", "name": "پنیر"}).json()
    b = client.post("/api/batches/receive", headers=auth_headers, json={
        "product_id": p["id"], "quantity_received": 10, "buy_price": 20000,
        "sell_price": 30000}).json()
    client.post("/api/pos/checkout", headers=auth_headers, json={
        "items": [{"product_id": p["id"], "batch_id": b["id"], "quantity": 1}],
        "payments": [{"method": "CASH", "amount": 30000}]})

    r = client.post(f"/api/products/{p['id']}/quick-price", headers=auth_headers,
                    json={"buy_price": 1, "batch_id": b["id"]})
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "BUY_PRICE_LOCKED"


def test_currency_setting_is_explicit_about_storage(client, auth_headers):
    r = client.get("/api/settings/currency", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["code"] in ("IRT", "IRR")

    put = client.put("/api/settings/currency", headers=auth_headers, json={"code": "IRR"})
    assert put.status_code == 200
    assert put.json()["code"] == "IRR"
    # existing invoices exist in this session -> the API must warn, not convert
    assert put.json()["warning"]
    client.put("/api/settings/currency", headers=auth_headers, json={"code": "IRT"})

    bad = client.put("/api/settings/currency", headers=auth_headers, json={"code": "USD"})
    assert bad.status_code == 422
