"""Inventory + stocktaking tests (blueprint §106, §109)."""


def test_stocktake_reconciliation(client, auth_headers, milk):
    # System: batch with qty 30.
    b = client.post("/api/batches/receive", headers=auth_headers, json={
        "product_id": milk["id"], "quantity_received": 30, "buy_price": 100}).json()
    st = client.post("/api/inventory/stocktakes", headers=auth_headers, json={"name": "Audit 1"}).json()
    item = next(i for i in st["items"] if i["batch_id"] == b["id"])
    # Physical count = 28 -> difference -2.
    c = client.post("/api/inventory/stocktakes/count", headers=auth_headers, json={
        "item_id": item["id"], "physical_qty": 28})
    assert c.json()["difference"] == -2
    # v0.2 flow (§19): complete -> PENDING_APPROVAL -> manager approve -> adjust
    done = client.post(f"/api/inventory/stocktakes/{st['id']}/complete", headers=auth_headers)
    assert done.json()["status"] == "PENDING_APPROVAL"
    not_yet = client.get(f"/api/batches/{b['id']}", headers=auth_headers).json()
    assert not_yet["current_qty"] == 30, "no change before approval"
    approved = client.post(f"/api/inventory/stocktakes/{st['id']}/approve", headers=auth_headers)
    assert approved.status_code == 200 and approved.json()["status"] == "ADJUSTED"
    b2 = client.get(f"/api/batches/{b['id']}", headers=auth_headers).json()
    assert b2["current_qty"] == 28


def test_adjustment_creates_movement_and_audit(client, auth_headers, milk):
    b = client.post("/api/batches/receive", headers=auth_headers, json={
        "product_id": milk["id"], "quantity_received": 10, "buy_price": 100}).json()
    client.post("/api/inventory/adjust", headers=auth_headers, json={
        "batch_id": b["id"], "new_current_qty": 7, "reason": "found missing"})
    moves = client.get("/api/inventory/movements", headers=auth_headers).json()
    types = [m["movement_type"] for m in moves]
    assert "ADJUSTMENT" in types
    audit = client.get("/api/audit?action=STOCK_ADJUSTED", headers=auth_headers).json()
    assert len(audit) >= 1


def test_waste_reduces_stock(client, auth_headers, milk):
    b = client.post("/api/batches/receive", headers=auth_headers, json={
        "product_id": milk["id"], "quantity_received": 10, "buy_price": 100}).json()
    r = client.post("/api/inventory/waste", headers=auth_headers, json={
        "batch_id": b["id"], "new_current_qty": 3})
    assert r.json()["current_qty"] == 7
