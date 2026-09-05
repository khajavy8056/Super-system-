"""§6/§16/§18/§33 — per-batch pricing, internal barcodes, search, duplicates.

These cover the gaps found in the v0.3.0 audit:
  §6  every money figure lives on the Batch, never merged onto the Product.
  §16 a loose/bulk item with no manufacturer GTIN still gets a scannable code.
  §18 the cashier can find a product by barcode, name, SKU, code OR brand.
  §33 registering a probable duplicate warns, but never blocks or auto-merges.
"""
from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path

import pytest

_TMP = Path(tempfile.mkdtemp(prefix="supermarket_catalog_"))
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_TMP / 'catalog.db'}")

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


def ean13(prefix12: str) -> str:
    """Hand-written EAN-13s fail checksum validation; compute the check digit."""
    total = sum(int(d) * (3 if i % 2 else 1) for i, d in enumerate(prefix12))
    return prefix12 + str((10 - total % 10) % 10)


def new_barcode() -> str:
    return ean13(f"626{uuid.uuid4().int % 10**9:09d}")


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def H(client):
    r = client.post("/api/auth/login",
                    data={"username": "admin", "password": "admin123"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


# --- §6: per-batch pricing ---------------------------------------------------

def test_batch_carries_its_own_supplier_price_discount_and_tax(client, H):
    """Two receipts of one product keep two independent price sets."""
    bc = new_barcode()
    p = client.post("/api/products", headers=H,
                    json={"barcode": bc, "name": f"روغن {uuid.uuid4().hex[:6]}"})
    assert p.status_code == 201, p.text
    pid = p.json()["id"]

    first = client.post("/api/batches/receive", headers=H, json={
        "product_id": pid, "quantity_received": 10, "buy_price": 50000,
        "supplier_price": 52000, "discount": 2000, "tax": 4500,
        "sell_price": 70000, "consumer_price": 75000})
    assert first.status_code in (200, 201), first.text

    second = client.post("/api/batches/receive", headers=H, json={
        "product_id": pid, "quantity_received": 5, "buy_price": 60000,
        "supplier_price": 61000, "discount": 0, "tax": 5400,
        "sell_price": 80000, "consumer_price": 85000})
    assert second.status_code in (200, 201), second.text

    detail = client.get(f"/api/products/{pid}/detail", headers=H)
    assert detail.status_code == 200, detail.text
    batches = detail.json()["active_batches"]
    assert len(batches) == 2, "receiving must create a second batch, not merge"

    # Sorted newest-first; compare as sets so ordering is not asserted.
    assert {b["supplier_price"] for b in batches} == {52000.0, 61000.0}
    assert {b["discount"] for b in batches} == {2000.0, 0.0}
    assert {b["tax"] for b in batches} == {4500.0, 5400.0}
    assert {b["buy_price"] for b in batches} == {50000.0, 60000.0}
    # The Product itself must expose no price field at all.
    assert not any(k for k in detail.json()["product"] if "price" in k)


def test_product_detail_keeps_depleted_batches_as_price_history(client, H):
    """§5 — a sold-out batch stays visible; it is the purchase-price record."""
    bc = new_barcode()
    pid = client.post("/api/products", headers=H,
                      json={"barcode": bc, "name": f"چای {uuid.uuid4().hex[:6]}"}).json()["id"]
    client.post("/api/batches/receive", headers=H, json={
        "product_id": pid, "quantity_received": 3, "buy_price": 1000,
        "sell_price": 1500})

    batch = client.get(f"/api/batches?product_id={pid}", headers=H).json()[0]
    sale = client.post("/api/pos/checkout", headers=H, json={
        "items": [{"product_id": pid, "batch_id": batch["id"], "quantity": 3}],
        "payments": [{"method": "CASH", "amount": 4500}]})
    assert sale.status_code in (200, 201), sale.text

    detail = client.get(f"/api/products/{pid}/detail", headers=H).json()
    assert detail["total_stock"] == 0
    assert len(detail["depleted_batches"]) == 1, "history must not be deleted"
    assert detail["depleted_batches"][0]["buy_price"] == 1000.0
    assert detail["batch_count"] == 1


# --- §16: internal barcodes --------------------------------------------------

def test_bulk_product_without_barcode_gets_internal_code(client, H):
    """Loose goods (تخمه، حبوبات) have no GTIN but must still be scannable."""
    r = client.post("/api/products", headers=H,
                    json={"name": f"تخمه فله {uuid.uuid4().hex[:6]}",
                          "has_own_barcode": False})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["barcode"].startswith("INT-"), body["barcode"]
    assert body["has_own_barcode"] is False

    # The minted code must be a real, resolvable identity — not a label.
    found = client.get(f"/api/products/{body['id']}", headers=H)
    assert found.status_code == 200
    assert found.json()["barcode"] == body["barcode"]


def test_internal_barcodes_are_unique_across_many_products(client, H):
    """A COUNT-based scheme would collide; the atomic counter must not."""
    codes = set()
    for _ in range(5):
        r = client.post("/api/products", headers=H,
                        json={"name": f"فله {uuid.uuid4().hex[:8]}",
                              "has_own_barcode": False})
        assert r.status_code == 201, r.text
        codes.add(r.json()["barcode"])
    assert len(codes) == 5, f"internal barcodes collided: {codes}"


def test_real_barcode_is_preserved_and_flagged_as_own(client, H):
    bc = new_barcode()
    r = client.post("/api/products", headers=H,
                    json={"barcode": bc, "name": f"شیر {uuid.uuid4().hex[:6]}"})
    assert r.status_code == 201
    assert r.json()["barcode"] == bc
    assert r.json()["has_own_barcode"] is True


# --- §18: POS search ---------------------------------------------------------

def test_pos_search_finds_product_by_brand_name(client, H):
    """A cashier types the brand («دماوند») more often than the full name."""
    brand_name = f"دماوند{uuid.uuid4().hex[:6]}"
    br = client.post("/api/products/brands", headers=H, json={"name": brand_name})
    assert br.status_code in (200, 201), br.text
    brand_id = br.json()["id"]

    bc = new_barcode()
    pid = client.post("/api/products", headers=H, json={
        "barcode": bc, "name": f"آب معدنی {uuid.uuid4().hex[:6]}",
        "brand_id": brand_id}).json()["id"]
    client.post("/api/batches/receive", headers=H, json={
        "product_id": pid, "quantity_received": 4, "buy_price": 2000,
        "sell_price": 3000})

    r = client.get(f"/api/pos/search?q={brand_name}", headers=H)
    assert r.status_code == 200, r.text
    assert pid in [i["product_id"] for i in r.json()["items"]], \
        "brand search returned nothing"


def test_pos_search_by_barcode_sku_and_name(client, H):
    bc, sku = new_barcode(), f"SKU{uuid.uuid4().hex[:8].upper()}"
    name = f"ماکارونی {uuid.uuid4().hex[:6]}"
    pid = client.post("/api/products", headers=H, json={
        "barcode": bc, "sku": sku, "name": name}).json()["id"]
    client.post("/api/batches/receive", headers=H, json={
        "product_id": pid, "quantity_received": 2, "buy_price": 1000,
        "sell_price": 1500})

    for term in (bc, sku, name.split()[0]):
        r = client.get("/api/pos/search", params={"q": term}, headers=H)
        assert r.status_code == 200, r.text
        assert pid in [i["product_id"] for i in r.json()["items"]], \
            f"search by {term!r} failed"


# --- §33: duplicate detection ------------------------------------------------

def test_duplicate_check_warns_on_same_name(client, H):
    name = f"پنیر لیقوان {uuid.uuid4().hex[:6]}"
    pid = client.post("/api/products", headers=H,
                      json={"barcode": new_barcode(), "name": name}).json()["id"]

    r = client.post("/api/products/check-duplicate", headers=H, json={"name": name})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["has_warning"] is True
    assert pid in [c["product_id"] for c in body["possible_duplicates"]]


def test_duplicate_check_normalizes_arabic_letters_and_digits(client, H):
    """«آب معدني» (Arabic ي) and «اب معدنی» (Persian ی) are one product."""
    suffix = uuid.uuid4().hex[:6]
    stored = f"اب معدنی {suffix}"
    client.post("/api/products", headers=H,
                json={"barcode": new_barcode(), "name": stored})

    typed = f"آب معدني {suffix}"  # Arabic yeh + alef madda
    r = client.post("/api/products/check-duplicate", headers=H, json={"name": typed})
    assert r.status_code == 200
    assert r.json()["has_warning"] is True, \
        "Persian/Arabic spelling variants must be folded together"


def test_duplicate_check_reports_exact_barcode_match_separately(client, H):
    """§32 — barcode equality is the hard rule and must be distinguishable."""
    bc = new_barcode()
    pid = client.post("/api/products", headers=H,
                      json={"barcode": bc, "name": f"نوشابه {uuid.uuid4().hex[:6]}"}).json()["id"]

    r = client.post("/api/products/check-duplicate", headers=H,
                    json={"name": "یک نام کاملا متفاوت", "barcode": bc})
    assert r.status_code == 200
    assert r.json()["exact_barcode_match"]["id"] == pid


def test_duplicate_check_is_advisory_and_never_blocks_creation(client, H):
    """Two real products may legitimately share a name — creation must succeed."""
    name = f"سیب زمینی {uuid.uuid4().hex[:6]}"
    first = client.post("/api/products", headers=H,
                        json={"barcode": new_barcode(), "name": name})
    assert first.status_code == 201
    second = client.post("/api/products", headers=H,
                         json={"barcode": new_barcode(), "name": name})
    assert second.status_code == 201, "duplicate detection must not block"
    assert second.json()["id"] != first.json()["id"]


def test_duplicate_check_is_quiet_for_a_genuinely_new_product(client, H):
    r = client.post("/api/products/check-duplicate", headers=H,
                    json={"name": f"کالای یکتا {uuid.uuid4().hex}"})
    assert r.status_code == 200
    assert r.json()["has_warning"] is False
    assert r.json()["possible_duplicates"] == []
