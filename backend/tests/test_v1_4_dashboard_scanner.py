"""v1.4 — neon dashboard payload + barcode-scanner discovery/wedge detection."""
from __future__ import annotations

from app.services import hardware as hw


def test_dashboard_has_v14_blocks(client, auth_headers, two_batches, milk):
    r = client.post("/api/pos/checkout", headers=auth_headers, json={
        "items": [{"product_id": milk["id"], "batch_id": two_batches["a"]["id"], "quantity": 2}],
        "payments": [{"method": "CASH", "amount": 120000}]})
    assert r.status_code in (200, 201), r.text
    d = client.get("/api/reports/dashboard", headers=auth_headers).json()
    assert isinstance(d["trend"], list) and len(d["trend"]) == 7
    assert {"date", "sales", "profit"} <= set(d["trend"][-1])
    tops = d["top_products"]
    assert tops and all(0 < t["share_pct"] <= 100 for t in tops)
    assert sum(t["share_pct"] for t in tops) <= 100.5
    assert len(tops) <= 5 and all({"name", "qty", "profit", "image_url", "product_id"} <= set(t) for t in tops)
    # the ranking is a projection of the same sales the per-product report sees
    from app.database import SessionLocal
    from app.services.reports import _top_products
    from datetime import datetime, timedelta
    with SessionLocal() as db:
        allp = _top_products(db, datetime.utcnow() - timedelta(days=1), datetime.utcnow() + timedelta(days=1), limit=10000)
    mine = next(t for t in allp if t["product_id"] == milk["id"])
    assert mine["qty"] >= 2
    assert {"cash", "bank", "card", "receivables", "payables", "month_net_profit"} <= set(d["accounting"])
    assert d["accounting"]["cash"] >= 120000


def test_scanner_wedge_detection_thresholds():
    assert hw.detect_scanner([8, 10, 12, 9, 11, 7]) is True          # burst -> scanner
    assert hw.detect_scanner([180, 220, 150, 300, 90]) is False      # human typing
    assert hw.detect_scanner([]) is False


def test_scanner_discover_registers_device(client, auth_headers, monkeypatch):
    monkeypatch.setattr(hw, "_enumerate_usb", lambda: [
        {"name": "Honeywell Voyager 1200g", "vid": 0x0C2E, "pid": 0x0B61, "class": "HIDClass", "instance": r"HID\VID_0C2E&PID_0B61"},
        {"name": "Generic Mouse", "vid": 0x046D, "pid": 0xC077, "class": "HIDClass", "instance": r"HID\VID_046D"},
    ])
    r = client.get("/api/hardware/scanner/discover", headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["scanners"]) == 1
    s = body["scanners"][0]
    assert s["mode"] == "HID_KEYBOARD" and s["ready"] is True
    assert body["registered"] and body["registered"]["status"] == "CONNECTED"
    health = client.get("/api/hardware/health", headers=auth_headers).json()
    assert health["scanner"] == "CONNECTED"


def test_scanner_discover_empty_is_honest(client, auth_headers, monkeypatch):
    monkeypatch.setattr(hw, "_enumerate_usb", lambda: [])
    r = client.get("/api/hardware/scanner/discover", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["scanners"] == [] and r.json()["registered"] is None


def test_scanner_detect_endpoint(client, auth_headers):
    r = client.post("/api/hardware/scanner/detect", headers=auth_headers, json={"intervals_ms": [5, 6, 7, 8, 5, 6]})
    assert r.status_code == 200 and r.json()["is_scanner"] is True
