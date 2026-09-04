"""Phase-4 acceptance tests: mobile/PWA serving + mobile stocktaking APIs (§21–27)."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

_TMP = Path(tempfile.mkdtemp(prefix="supermarket_p4_"))
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_TMP / 'p4.db'}")

from fastapi.testclient import TestClient  # noqa: E402

from app.database import init_db  # noqa: E402
from app.main import app  # noqa: E402

init_db()


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def H(client):
    r = client.post("/api/auth/login", data={"username": "admin", "password": "admin123"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


_n = 0


def ean13(prefix12: str) -> str:
    total = sum(int(d) * (3 if i % 2 else 1) for i, d in enumerate(prefix12))
    return prefix12 + str((10 - total % 10) % 10)


# --- PWA static assets -----------------------------------------------------------

def test_mobile_page_served(client):
    r = client.get("/mobile/")
    assert r.status_code == 200
    assert "mobile/app.js" in r.text
    assert "manifest.webmanifest" in r.text


def test_manifest_and_sw_served(client):
    m = client.get("/manifest.webmanifest")
    assert m.status_code == 200
    body = m.json()
    assert body["start_url"] == "/mobile/"
    assert any(i["src"] == "/icons/icon-192.png" for i in body["icons"])
    sw = client.get("/sw.js")
    assert sw.status_code == 200 and "supermarket-shell" in sw.text
    icon = client.get("/icons/icon-192.png")
    assert icon.status_code == 200 and icon.headers["content-type"].startswith("image/png")


def test_sw_never_touches_api(client):
    """Documented policy: /api must be network-only (checked by sw.js source)."""
    sw = client.get("/sw.js").text
    assert 'url.pathname.startsWith("/api")' in sw


# --- Mobile stocktaking flow -------------------------------------------------------

def _mk_product_batch(client, H, name, qty, expiry=None):
    global _n
    _n += 1
    bc = ean13(f"45{_n:010d}")  # 12 unique digits + check digit
    p = client.post("/api/products", headers=H, json={"barcode": bc, "name": name}).json()
    b = client.post("/api/batches/receive", headers=H, json={
        "product_id": p["id"], "quantity_received": qty, "buy_price": 1000,
        "sell_price": 1500, "expiry_date": expiry}).json()
    return p, b


def test_stocktake_items_carry_product_info(client, H):
    """The mobile UI needs product_name/barcode/image in one call."""
    p, b = _mk_product_batch(client, H, "Mobile Milk", 15)
    st = client.post("/api/inventory/stocktakes", headers=H, json={"name": "M1"}).json()
    item = next(i for i in st["items"] if i["batch_id"] == b["id"])
    detail = client.get(f"/api/inventory/stocktakes/{st['id']}", headers=H).json()
    row = next(i for i in detail["items"] if i["id"] == item["id"])
    assert row["product_name"] == "Mobile Milk"
    assert row["barcode"] == p["barcode"]
    assert "system_qty" in row and "status" in row


def test_item_by_barcode_found(client, H):
    p, b = _mk_product_batch(client, H, "Mobile Soda", 7)
    st = client.post("/api/inventory/stocktakes", headers=H, json={"name": "M2"}).json()
    r = client.get(f"/api/inventory/stocktakes/{st['id']}/item-by-barcode/{p['barcode']}", headers=H)
    assert r.status_code == 200
    body = r.json()
    assert body["product"]["name"] == "Mobile Soda"
    assert any(i["batch_id"] == b["id"] for i in body["items"])


def test_item_by_barcode_errors_are_classified(client, H):
    p, b = _mk_product_batch(client, H, "Mobile Bread", 5)
    st = client.post("/api/inventory/stocktakes", headers=H, json={"name": "M3"}).json()
    # unknown barcode -> PRODUCT_NOT_FOUND
    r = client.get(f"/api/inventory/stocktakes/{st['id']}/item-by-barcode/{ean13('460000000009')}", headers=H)
    assert r.status_code == 404 and r.json()["detail"]["code"] == "PRODUCT_NOT_FOUND"
    # valid product not in this session -> ITEM_NOT_IN_SESSION
    p2, _ = _mk_product_batch(client, H, "Not In Session", 5)
    r2 = client.get(f"/api/inventory/stocktakes/{st['id']}/item-by-barcode/{p2['barcode']}", headers=H)
    assert r2.status_code == 404 and r2.json()["detail"]["code"] == "ITEM_NOT_IN_SESSION"


def test_mobile_full_count_flow_via_api(client, H):
    """The exact API sequence the mobile app performs (online mode)."""
    p, b = _mk_product_batch(client, H, "Mobile Juice", 12)
    st = client.post("/api/inventory/stocktakes", headers=H, json={"name": "M4"}).json()
    # scan -> find
    found = client.get(f"/api/inventory/stocktakes/{st['id']}/item-by-barcode/{p['barcode']}", headers=H).json()
    item = found["items"][0]
    # count -> save immediately
    c = client.post("/api/inventory/stocktakes/count", headers=H,
                    json={"item_id": item["id"], "physical_qty": 11, "reason": "mobile"})
    assert c.status_code == 200 and c.json()["difference"] == -1
    # resume: progress shows 1 counted
    prog = client.get(f"/api/inventory/stocktakes/{st['id']}/progress", headers=H).json()
    assert prog["counted"] == 1
    # finish -> approval (as in phase 2)
    client.post(f"/api/inventory/stocktakes/{st['id']}/complete", headers=H)
    client.post(f"/api/inventory/stocktakes/{st['id']}/approve", headers=H)
    batch = client.get(f"/api/batches/{b['id']}", headers=H).json()
    assert batch["current_qty"] == 11


def test_mobile_replay_after_session_closed_is_conflict_not_silent(client, H):
    """Offline queue replay: a count for a closed session must be REJECTED by
    the server (the mobile app turns this into a human conflict, §26)."""
    p, b = _mk_product_batch(client, H, "Mobile Cheese", 9)
    st = client.post("/api/inventory/stocktakes", headers=H, json={"name": "M5"}).json()
    found = client.get(f"/api/inventory/stocktakes/{st['id']}/item-by-barcode/{p['barcode']}", headers=H).json()
    item = found["items"][0]
    client.post(f"/api/inventory/stocktakes/{st['id']}/complete", headers=H)
    client.post(f"/api/inventory/stocktakes/{st['id']}/approve", headers=H)
    late = client.post("/api/inventory/stocktakes/count", headers=H,
                       json={"item_id": item["id"], "physical_qty": 3, "reason": "sync از حالت آفلاین"})
    assert late.status_code == 422, "server must refuse; conflict resolution stays human"
