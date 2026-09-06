"""Phase-7: resumable stocktaking + mobile feed + offline replay (§7–14, §51)."""
from decimal import Decimal

import pytest


_seq = 0


@pytest.fixture()
def session_with_items(client, auth_headers):
    global _seq
    _seq += 1
    ids = []
    for i in range(5):
        p = client.post("/api/products", headers=auth_headers, json={
            "barcode": f"6262{_seq:03d}2{i:04d}", "name": f"کالای شمارش {_seq}-{i}"}).json()
        client.post("/api/batches/receive", headers=auth_headers, json={
            "product_id": p["id"], "quantity_received": 10 + i, "buy_price": 1000,
            "sell_price": 2000})
        ids.append(p["id"])
    st = client.post("/api/inventory/stocktakes", headers=auth_headers, json={
        "name": "انبارگردانی شعبه ۱", "area": "قفسه A", "product_ids": ids}).json()
    return st


def test_progress_is_tracked_and_session_is_resumable(client, auth_headers, session_with_items):
    sid = session_with_items["id"]
    items = session_with_items["items"]
    assert len(items) == 5

    p0 = client.get(f"/api/inventory/stocktakes/{sid}/progress", headers=auth_headers).json()
    assert p0["counted"] == 0 and p0["total"] == 5 and p0["percent"] == 0.0

    for it in items[:3]:
        r = client.post("/api/inventory/stocktakes/count", headers=auth_headers,
                        json={"item_id": it["id"], "physical_qty": 7})
        assert r.status_code == 200, r.text

    p1 = client.get(f"/api/inventory/stocktakes/{sid}/progress", headers=auth_headers).json()
    assert p1["counted"] == 3 and p1["remaining"] == 2
    assert p1["percent"] == 60.0
    assert p1["resumable"] is True
    assert p1["cursor_item_id"] == items[2]["id"]
    # the next item to show after a restart is item #4
    assert p1["next_item_id"] == items[3]["id"]


def test_active_sessions_endpoint_lists_resumable_work(client, auth_headers, session_with_items):
    r = client.get("/api/inventory/stocktake-sessions/active", headers=auth_headers)
    assert r.status_code == 200
    assert any(s["id"] == session_with_items["id"] for s in r.json())


def test_mobile_item_feed_paginates_and_carries_display_data(client, auth_headers,
                                                             session_with_items):
    sid = session_with_items["id"]
    r = client.get(f"/api/inventory/stocktakes/{sid}/items", headers=auth_headers,
                   params={"limit": 2})
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["items"]) == 2
    first = body["items"][0]
    for key in ("product_name", "barcode", "image_url", "system_qty", "batch_number"):
        assert key in first
    assert body["next_cursor"] == body["items"][-1]["id"]

    page2 = client.get(f"/api/inventory/stocktakes/{sid}/items", headers=auth_headers,
                       params={"limit": 2, "cursor": body["next_cursor"]}).json()
    assert page2["items"][0]["id"] > body["next_cursor"]


def test_offline_bulk_replay_applies_and_reports_rejections(client, auth_headers,
                                                            session_with_items):
    sid = session_with_items["id"]
    items = session_with_items["items"]
    r = client.post("/api/inventory/stocktakes/count/bulk", headers=auth_headers, json={
        "counts": [
            {"item_id": items[0]["id"], "physical_qty": 9, "client_key": "k1"},
            {"item_id": items[1]["id"], "physical_qty": 12, "client_key": "k2"},
            {"item_id": 999999, "physical_qty": 1, "client_key": "k3"},  # gone
        ]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["applied"] == 2 and body["rejected"] == 1
    keys = {x["client_key"]: x["ok"] for x in body["results"]}
    assert keys == {"k1": True, "k2": True, "k3": False}

    progress = client.get(f"/api/inventory/stocktakes/{sid}/progress",
                          headers=auth_headers).json()
    assert progress["counted"] == 2


def test_full_stocktake_lifecycle_creates_adjustment(client, auth_headers,
                                                     session_with_items):
    sid = session_with_items["id"]
    items = session_with_items["items"]
    # system says 10 for the first item; physically there are 8
    client.post("/api/inventory/stocktakes/count", headers=auth_headers,
                json={"item_id": items[0]["id"], "physical_qty": 8, "reason": "کسری"})

    done = client.post(f"/api/inventory/stocktakes/{sid}/complete", headers=auth_headers)
    assert done.status_code == 200, done.text
    assert done.json()["status"] == "PENDING_APPROVAL"
    diffs = done.json()["differences"]
    assert any(Decimal(str(d["difference"])) == Decimal("-2") for d in diffs)

    batch_id = items[0]["batch_id"]
    approve = client.post(f"/api/inventory/stocktakes/{sid}/approve", headers=auth_headers)
    assert approve.status_code == 200
    assert approve.json()["status"] == "ADJUSTED"

    b = client.get(f"/api/batches/{batch_id}", headers=auth_headers).json()
    assert Decimal(str(b["current_qty"])) == Decimal("8")

    moves = client.get("/api/inventory/movements", headers=auth_headers).json()
    assert any(m.get("movement_type") == "STOCKTAKE" for m in moves)


def test_counting_is_closed_after_completion(client, auth_headers, session_with_items):
    sid = session_with_items["id"]
    items = session_with_items["items"]
    client.post("/api/inventory/stocktakes/count", headers=auth_headers,
                json={"item_id": items[0]["id"], "physical_qty": 10})
    client.post(f"/api/inventory/stocktakes/{sid}/complete", headers=auth_headers)
    late = client.post("/api/inventory/stocktakes/count", headers=auth_headers,
                       json={"item_id": items[1]["id"], "physical_qty": 5})
    assert late.status_code == 422


def test_scan_barcode_finds_the_session_item(client, auth_headers, session_with_items):
    sid = session_with_items["id"]
    first = client.get(f"/api/inventory/stocktakes/{sid}/items",
                       headers=auth_headers, params={"limit": 1}).json()["items"][0]
    r = client.get(f"/api/inventory/stocktakes/{sid}/item-by-barcode/{first['barcode']}",
                   headers=auth_headers)
    assert r.status_code == 200, r.text
    assert r.json()["items"][0]["id"] == first["id"]
