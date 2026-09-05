"""Pricing tests (blueprint §107 price history, §28 no destructive update)."""


def test_price_history_versions(client, auth_headers, milk):
    r1 = client.post("/api/prices", headers=auth_headers, json={
        "product_id": milk["id"], "price_type": "SELL", "price": 120})
    r2 = client.post("/api/prices", headers=auth_headers, json={
        "product_id": milk["id"], "price_type": "SELL", "price": 130})
    history = client.get(f"/api/prices/history/{milk['id']}", headers=auth_headers).json()
    assert len(history) == 2
    # Old version is closed (not destroyed), new one is active.
    assert history[0]["price"] == 130.0 and history[0]["is_active"] is True
    assert history[1]["price"] == 120.0 and history[1]["is_active"] is False


def test_suggest_price_uses_cost_and_margin(client, auth_headers, milk):
    client.post("/api/batches/receive", headers=auth_headers, json={
        "product_id": milk["id"], "quantity_received": 5, "buy_price": 100, "sell_price": 150})
    r = client.post("/api/prices/suggest", headers=auth_headers, json={
        "product_id": milk["id"], "target_margin": 20})
    assert r.status_code == 200
    assert r.json()["suggested"] == 120.0
