"""Critical POS tests (blueprint §105, §107–108)."""
from decimal import Decimal


def _checkout(client, headers, items, total):
    return client.post("/api/pos/checkout", headers=headers, json={
        "items": items, "payments": [{"method": "CASH", "amount": total}]})


def test_split_sale_between_batches_exact_profit(client, auth_headers, two_batches, milk):
    """Blueprint §107: 2 x BatchA (buy50k/sell60k) + 3 x BatchB (buy55k/sell65k)
    => profit A (20000) + profit B (30000) = 50000."""
    r = _checkout(client, auth_headers, [
        {"product_id": milk["id"], "batch_id": two_batches["a"]["id"], "quantity": 2},
        {"product_id": milk["id"], "batch_id": two_batches["b"]["id"], "quantity": 3},
    ], 315000)
    assert r.status_code == 201, r.text
    body = r.json()
    assert Decimal(str(body["total_amount"])) == Decimal("315000")
    profits = {it["batch_id"]: Decimal(str(it["profit"])) for it in body["items"]}
    assert profits[two_batches["a"]["id"]] == Decimal("20000")
    assert profits[two_batches["b"]["id"]] == Decimal("30000")
    assert sum(profits.values()) == Decimal("50000")


def test_checkout_deducts_batch_stock(client, auth_headers, two_batches, milk):
    _checkout(client, auth_headers, [
        {"product_id": milk["id"], "batch_id": two_batches["a"]["id"], "quantity": 2},
    ], 120000)
    r = client.get(f"/api/batches/{two_batches['a']['id']}", headers=auth_headers)
    assert r.json()["current_qty"] == 8


def test_insufficient_stock_error(client, auth_headers, two_batches, milk):
    r = _checkout(client, auth_headers, [
        {"product_id": milk["id"], "batch_id": two_batches["a"]["id"], "quantity": 99},
    ], 999999)
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "INSUFFICIENT_STOCK"


def test_expired_batch_blocked(client, auth_headers, milk):
    r = client.post("/api/batches/receive", headers=auth_headers, json={
        "product_id": milk["id"], "quantity_received": 3, "buy_price": 100,
        "sell_price": 200, "expiry_date": "2020-01-01"})
    expired_id = r.json()["id"]
    chk = _checkout(client, auth_headers, [
        {"product_id": milk["id"], "batch_id": expired_id, "quantity": 1}], 200)
    assert chk.status_code == 422
    assert chk.json()["detail"]["code"] == "BATCH_EXPIRED"


def test_void_restocks(client, auth_headers, two_batches, milk):
    inv = _checkout(client, auth_headers, [
        {"product_id": milk["id"], "batch_id": two_batches["a"]["id"], "quantity": 2}], 120000).json()
    r = client.post(f"/api/invoices/{inv['invoice_id']}/void", headers=auth_headers, json={"reason": "test"})
    assert r.status_code == 200
    assert r.json()["status"] == "VOID"
    b = client.get(f"/api/batches/{two_batches['a']['id']}", headers=auth_headers).json()
    assert b["current_qty"] == 10


def test_invoice_snapshot_unchanged_after_price_change(client, auth_headers, two_batches, milk):
    """Blueprint §108: after a price change, the old invoice must not change."""
    inv = _checkout(client, auth_headers, [
        {"product_id": milk["id"], "batch_id": two_batches["a"]["id"], "quantity": 1}], 60000).json()
    # change sell price via price version
    client.post("/api/prices", headers=auth_headers, json={
        "product_id": milk["id"], "price_type": "SELL", "price": 99000})
    r = client.get(f"/api/invoices/{inv['invoice_id']}", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["items"][0]["unit_sell_price"] == 60000.0


def test_single_batch_direct_add(client, auth_headers, milk):
    client.post("/api/batches/receive", headers=auth_headers, json={
        "product_id": milk["id"], "quantity_received": 5, "buy_price": 100, "sell_price": 150})
    # No batch_id -> system suggests the only batch (direct add, §12).
    r = client.post("/api/pos/cart/validate", headers=auth_headers, json={
        "items": [{"product_id": milk["id"], "quantity": 2}]})
    assert r.status_code == 200
    assert r.json()["items"][0]["suggested"] is True


def test_unknown_barcode_resolver_manual(client, auth_headers):
    r = client.get("/api/barcode/resolve/9999999999999", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["need_manual"] is True
