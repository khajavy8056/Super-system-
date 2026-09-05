def test_receive_creates_new_batch_not_overwrite(client, auth_headers, milk):
    r1 = client.post("/api/batches/receive", headers=auth_headers, json={
        "product_id": milk["id"], "quantity_received": 10, "buy_price": 50000, "sell_price": 60000})
    r2 = client.post("/api/batches/receive", headers=auth_headers, json={
        "product_id": milk["id"], "quantity_received": 5, "buy_price": 55000, "sell_price": 65000})
    assert r1.json()["batch_number"] != r2.json()["batch_number"]
    # Historical buy price of batch 1 is preserved (§28).
    assert r1.json()["buy_price"] == 50000.0
    assert r2.json()["buy_price"] == 55000.0


def test_batch_number_format(client, auth_headers, milk):
    r = client.post("/api/batches/receive", headers=auth_headers, json={
        "product_id": milk["id"], "quantity_received": 1, "buy_price": 100})
    assert r.json()["batch_number"].startswith("B-")


def test_batch_options_show_old_and_new_price(client, auth_headers, two_batches, milk):
    r = client.get(f"/api/pos/batch-options/{milk['id']}", headers=auth_headers)
    assert r.status_code == 200
    prices = sorted(o["sell_price"] for o in r.json()["options"])
    assert prices == [60000.0, 65000.0]
    # One of them is recommended.
    assert any(o["is_recommended"] for o in r.json()["options"])


def test_delete_batch_with_stock_rejected(client, auth_headers, two_batches):
    r = client.delete(f"/api/batches/{two_batches['a']['id']}", headers=auth_headers)
    assert r.status_code == 400
