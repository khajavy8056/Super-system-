"""v1.3: scheduled stocktakes + alarm feed + richer wizard payload."""
from __future__ import annotations

from datetime import date, timedelta


def test_scheduled_stocktake_appears_in_upcoming_with_days_left(client, auth_headers):
    soon = (date.today() + timedelta(days=2)).isoformat()
    r = client.post("/api/inventory/stocktakes", headers=auth_headers,
                    json={"name": "شمارش قفسه‌های یخچالی", "scheduled_for": soon, "reminder_note": "اول یخچال‌ها"})
    assert r.status_code == 201, r.text
    sid = r.json()["id"]
    assert r.json()["scheduled_for"] == soon

    up = client.get("/api/inventory/stocktakes-upcoming", headers=auth_headers).json()
    mine = next(a for a in up if a["id"] == sid)
    assert mine["days_left"] == 2 and mine["level"] == "soon" and mine["reminder_note"] == "اول یخچال‌ها"

    # overdue -> loudest level
    r2 = client.post("/api/inventory/stocktakes", headers=auth_headers,
                     json={"name": "قدیمی", "scheduled_for": (date.today() - timedelta(days=1)).isoformat()})
    up = client.get("/api/inventory/stocktakes-upcoming", headers=auth_headers).json()
    assert next(a for a in up if a["id"] == r2.json()["id"])["level"] == "overdue"

    # far future is outside the default horizon
    r3 = client.post("/api/inventory/stocktakes", headers=auth_headers,
                     json={"name": "دور", "scheduled_for": (date.today() + timedelta(days=60)).isoformat()})
    up = client.get("/api/inventory/stocktakes-upcoming", headers=auth_headers).json()
    assert all(a["id"] != r3.json()["id"] for a in up)

    detail = client.get(f"/api/inventory/stocktakes/{sid}", headers=auth_headers).json()
    assert detail["scheduled_for"] == soon
    for it in detail["items"]:
        assert {"batch_number", "expiry_date", "location", "image_url", "unit_id"} <= set(it)
    lst = client.get("/api/inventory/stocktakes", headers=auth_headers).json()
    assert next(s for s in lst if s["id"] == sid)["scheduled_for"] == soon
