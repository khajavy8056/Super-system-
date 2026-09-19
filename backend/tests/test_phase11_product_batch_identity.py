"""§30/§32 — Product identity vs Batch lifecycle. The non-negotiable core.

Rules under test:
  1. A Product has ONE identity; buying more of it is NOT a new Product.
  2. Each receipt MAY create a new Batch.
  3. buy/sell price, qty, received & expiry dates belong to the BATCH and are
     never overwritten onto the Product.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

_TMP = Path(tempfile.mkdtemp(prefix="supermarket_identity_"))
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_TMP / 'identity.db'}")

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


def ean13(prefix12: str) -> str:
    total = sum(int(d) * (3 if i % 2 else 1) for i, d in enumerate(prefix12))
    return prefix12 + str((10 - total % 10) % 10)


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def H(client):
    r = client.post("/api/auth/login",
                    data={"username": "admin", "password": "admin123"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


BC = ean13("626099000001")


@pytest.fixture(scope="module")
def damavand(client, H):
    """Test A — define the product once."""
    r = client.post("/api/products", headers=H, json={
        "barcode": BC, "name": "آب معدنی دماوند ۱.۵ لیتری",
        "min_stock_alert": 10})
    assert r.status_code in (200, 201), r.text
    return r.json()


def _receive(client, H, **kw):
    return client.post("/api/batches/receive", headers=H, json=kw)


def test_A_product_created_once(damavand):
    assert damavand["barcode"] == BC
    assert damavand["id"]


def test_B_first_receipt_creates_batch_001(client, H, damavand):
    r = _receive(client, H, barcode=BC, quantity_received=50,
                 buy_price=30000, sell_price=40000, consumer_price=40000)
    assert r.status_code in (200, 201), r.text
    b = r.json()
    assert float(b["current_qty"]) == 50
    assert float(b["buy_price"]) == 30000


def test_C_same_barcode_again_reuses_product_and_adds_a_batch(client, H, damavand):
    """The headline scenario: buying more must NOT duplicate the Product."""
    r = _receive(client, H, barcode=BC, quantity_received=80,
                 buy_price=35000, sell_price=45000, consumer_price=45000)
    assert r.status_code in (200, 201), r.text

    # exactly ONE product carries this barcode
    found = client.get(f"/api/products?q={BC}", headers=H).json()["items"]
    matching = [p for p in found if p["barcode"] == BC]
    assert len(matching) == 1, f"Product duplicated: {matching}"
    assert matching[0]["id"] == damavand["id"], "Product identity changed"

    # two batches, 130 total
    batches = client.get(f"/api/batches?product_id={damavand['id']}",
                         headers=H).json()
    mine = [b for b in batches if b["product_id"] == damavand["id"]]
    assert len(mine) == 2, f"expected 2 batches, got {len(mine)}"
    assert sum(float(b["current_qty"]) for b in mine) == 130


def test_C2_prices_are_per_batch_and_not_merged(client, H, damavand):
    batches = client.get(f"/api/batches?product_id={damavand['id']}",
                         headers=H).json()
    mine = sorted((b for b in batches if b["product_id"] == damavand["id"]),
                  key=lambda b: b["id"])
    assert [float(b["buy_price"]) for b in mine] == [30000, 35000]
    assert [float(b["sell_price"]) for b in mine] == [40000, 45000]


def test_D_selling_60_consumes_batches_without_duplicating_product(client, H, damavand):
    pid = damavand["id"]
    opts = client.get(f"/api/pos/batch-options/{pid}", headers=H).json()["options"]
    assert opts, "no sellable batch options"

    # Sell 60 across batches following the system's own allocation policy.
    remaining, items = 60.0, []
    for o in sorted(opts, key=lambda o: o["batch_id"]):
        if remaining <= 0:
            break
        take = min(remaining, float(o["current_qty"]))
        items.append({"product_id": pid, "batch_id": o["batch_id"],
                      "quantity": take})
        remaining -= take
    assert remaining == 0, "not enough stock to sell 60"

    total = sum(i["quantity"] * float(
        next(o for o in opts if o["batch_id"] == i["batch_id"])["sell_price"])
        for i in items)
    r = client.post("/api/pos/checkout", headers=H, json={
        "items": items, "payments": [{"method": "CASH", "amount": total}]})
    assert r.status_code in (200, 201), r.text

    batches = client.get(f"/api/batches?product_id={pid}", headers=H).json()
    mine = sorted((b for b in batches if b["product_id"] == pid),
                  key=lambda b: b["id"])
    assert sum(float(b["current_qty"]) for b in mine) == 70

    # still exactly one product
    found = client.get(f"/api/products?q={BC}", headers=H).json()["items"]
    assert len([p for p in found if p["barcode"] == BC]) == 1


def test_E_invoice_item_records_the_batch_it_came_from(client, H, damavand):
    """§7 — batch_id must be persisted on the sold line."""
    invs = client.get("/api/invoices?limit=5", headers=H).json()
    rows = invs["items"] if isinstance(invs, dict) else invs
    assert rows, "no invoices"
    detail = client.get(f"/api/invoices/{rows[0]['id']}", headers=H).json()
    assert detail["items"], "invoice has no lines"
    for line in detail["items"]:
        assert line.get("batch_id"), f"InvoiceItem without batch_id: {line}"


def test_F_zero_qty_batches_remain_in_history(client, H, damavand):
    """§5 — depleted batches stay visible, never deleted."""
    batches = client.get(f"/api/batches?product_id={damavand['id']}",
                         headers=H).json()
    mine = [b for b in batches if b["product_id"] == damavand["id"]]
    assert len(mine) == 2, "a depleted batch disappeared from history"
