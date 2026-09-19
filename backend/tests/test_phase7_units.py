"""Phase-7: decimal quantities & the unit system (§25)."""
from decimal import Decimal


def _unit(client, headers, name):
    units = client.get("/api/units", headers=headers).json()
    for u in units:
        if u["name"] == name:
            return u
    raise AssertionError(f"unit {name} missing: {[u['name'] for u in units]}")


def test_default_units_are_seeded_with_decimal_flags(client, auth_headers):
    kg = _unit(client, auth_headers, "کیلوگرم")
    piece = _unit(client, auth_headers, "عدد")
    assert kg["allow_decimal"] is True and kg["decimals"] == 3
    assert piece["allow_decimal"] is False


def _rice(client, headers, barcode="6260999900011"):
    kg = _unit(client, headers, "کیلوگرم")
    r = client.post("/api/products", headers=headers,
                    json={"barcode": barcode, "name": "برنج طارم", "unit_id": kg["id"]})
    assert r.status_code == 201, r.text
    p = r.json()
    b = client.post("/api/batches/receive", headers=headers, json={
        "product_id": p["id"], "quantity_received": 25.5, "buy_price": 100000,
        "sell_price": 140000})
    assert b.status_code == 201, b.text
    return p, b.json()


def test_receive_and_sell_fractional_kilograms(client, auth_headers):
    product, batch = _rice(client, auth_headers, "6260999900011")
    assert Decimal(str(batch["current_qty"])) == Decimal("25.5")

    r = client.post("/api/pos/checkout", headers=auth_headers, json={
        "items": [{"product_id": product["id"], "batch_id": batch["id"], "quantity": 12.5}],
        "payments": [{"method": "CASH", "amount": 1750000}]})
    assert r.status_code == 201, r.text
    body = r.json()
    assert Decimal(str(body["total_amount"])) == Decimal("1750000")
    assert Decimal(str(body["items"][0]["qty"])) == Decimal("12.5")

    left = client.get(f"/api/batches/{batch['id']}", headers=auth_headers).json()
    assert Decimal(str(left["current_qty"])) == Decimal("13")


def test_fractional_quantity_rejected_for_piece_unit(client, auth_headers):
    piece = _unit(client, auth_headers, "عدد")
    p = client.post("/api/products", headers=auth_headers, json={
        "barcode": "6260999900022", "name": "نوشابه", "unit_id": piece["id"]}).json()
    b = client.post("/api/batches/receive", headers=auth_headers, json={
        "product_id": p["id"], "quantity_received": 10, "buy_price": 10000,
        "sell_price": 15000}).json()

    r = client.post("/api/pos/checkout", headers=auth_headers, json={
        "items": [{"product_id": p["id"], "batch_id": b["id"], "quantity": 2.5}],
        "payments": [{"method": "CASH", "amount": 37500}]})
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "INVALID_QUANTITY"


def test_decimal_stocktake_count(client, auth_headers):
    product, batch = _rice(client, auth_headers, "6260999900033")
    st = client.post("/api/inventory/stocktakes", headers=auth_headers,
                     json={"name": "انبارگردانی اعشاری",
                           "batch_ids": [batch["id"]]}).json()
    item = st["items"][0]
    r = client.post("/api/inventory/stocktakes/count", headers=auth_headers,
                    json={"item_id": item["id"], "physical_qty": 24.25})
    assert r.status_code == 200, r.text
    body = r.json()
    assert Decimal(str(body["physical_qty"])) == Decimal("24.25")
    assert Decimal(str(body["difference"])) == Decimal("-1.25")
