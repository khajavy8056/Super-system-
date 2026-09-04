"""Audit-phase regression tests (2026-09-04) + Phase-0 acceptance tests.

REG-00x tests assert the CORRECT expected behaviour for bugs found during the
repository audit (BUG_REPORT.md). Fixed in Phase 0: REG-001/002/003/005/006 —
their xfail markers were removed, so any regression now fails the suite.
REG-004 (external resolver persistence) stays xfail until Phase 1.
"""
from __future__ import annotations

import os
import tempfile
import threading
import time
from decimal import Decimal
from pathlib import Path

import pytest

_TMP = Path(tempfile.mkdtemp(prefix="supermarket_reg_"))
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_TMP / 'reg.db'}")

from fastapi.testclient import TestClient  # noqa: E402

from app.database import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models import ExternalSource, InvoiceItem, ProductResolverResult  # noqa: E402
from app.services.pos import CartItem, checkout as checkout_svc  # noqa: E402
from sqlalchemy import select  # noqa: E402


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def auth_headers(client):
    r = client.post("/api/auth/login", data={"username": "admin", "password": "admin123"})
    assert r.status_code == 200
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


_n = 0


def _product_with_batch(client, headers, *, qty=10, buy=1000, sell=2000, **kw):
    global _n
    _n += 1
    p = client.post("/api/products", headers=headers,
                    json={"barcode": f"71000000000{_n:04d}", "name": f"Reg T{_n}"}).json()
    b = client.post("/api/batches/receive", headers=headers,
                    json={"product_id": p["id"], "quantity_received": qty,
                          "buy_price": buy, "sell_price": sell, **kw}).json()
    return p, b


# --- BUG-001 (FIXED phase 0) --------------------------------------------------
def test_reg_001_discount_counted_once(client, auth_headers):
    p, b = _product_with_batch(client, auth_headers, qty=10, buy=1000, sell=2000)
    db = SessionLocal()
    try:
        inv = checkout_svc(
            db,
            items=[CartItem(product_id=p["id"], batch_id=b["id"], quantity=1, discount=Decimal("500"))],
            payments=[{"method": "CASH", "amount": Decimal("1500")}],
        )
        db.commit()
    finally:
        db.close()
    assert inv.total_amount == Decimal("1500.00")
    assert inv.subtotal == Decimal("2000.00")  # gross
    assert inv.discount == Decimal("500.00")


def test_discount_via_api_with_tax(client, auth_headers):
    """gross=2000+1000, line discounts=500, tax 10% -> taxable 2500, tax 250, total 2750."""
    p, b = _product_with_batch(client, auth_headers, qty=10, buy=500, sell=2000)
    p2, b2 = _product_with_batch(client, auth_headers, qty=10, buy=400, sell=1000)
    r = client.post("/api/pos/checkout", headers=auth_headers, json={
        "items": [
            {"product_id": p["id"], "batch_id": b["id"], "quantity": 1, "discount": 300},
            {"product_id": p2["id"], "batch_id": b2["id"], "quantity": 1, "discount": 200},
        ],
        "tax_rate": 10,
        "payments": [{"method": "CASH", "amount": 2750}],
    })
    assert r.status_code == 201, r.text
    body = r.json()
    assert Decimal(str(body["subtotal"])) == Decimal("3000")      # gross
    assert Decimal(str(body["discount"])) == Decimal("500")
    assert Decimal(str(body["tax"])) == Decimal("250")            # 10% of 2500
    assert Decimal(str(body["total_amount"])) == Decimal("2750")  # counted once


# --- BUG-002 (FIXED phase 0) --------------------------------------------------
def test_reg_002_return_cannot_exceed_item_qty(client, auth_headers):
    p, b = _product_with_batch(client, auth_headers, qty=10, buy=100, sell=200)
    inv = client.post("/api/pos/checkout", headers=auth_headers, json={
        "items": [{"product_id": p["id"], "batch_id": b["id"], "quantity": 2}],
        "payments": [{"method": "CASH", "amount": 400}],
    }).json()

    db = SessionLocal()
    item = db.execute(select(InvoiceItem).where(InvoiceItem.invoice_id == inv["invoice_id"])).scalars().first()
    item_id = item.id
    db.close()

    r1 = client.post("/api/returns", headers=auth_headers, json={
        "invoice_id": inv["invoice_id"], "invoice_item_id": item_id, "qty": 2})
    assert r1.status_code == 201
    r2 = client.post("/api/returns", headers=auth_headers, json={
        "invoice_id": inv["invoice_id"], "invoice_item_id": item_id, "qty": 2})
    assert r2.status_code == 422, "returning more than purchased must be rejected"
    assert r2.json()["detail"]["code"] == "RETURN_EXCEEDS_PURCHASE"
    stock = client.get(f"/api/batches/{b['id']}", headers=auth_headers).json()["current_qty"]
    assert stock == 10, f"stock inflated to {stock}"
    invoice = client.get(f"/api/invoices/{inv['invoice_id']}", headers=auth_headers).json()
    assert invoice["status"] == "REFUNDED", "fully returned invoice must be REFUNDED (BUG-019)"


def test_partial_return_keeps_partially_refunded(client, auth_headers):
    p, b = _product_with_batch(client, auth_headers, qty=10, buy=100, sell=200)
    inv = client.post("/api/pos/checkout", headers=auth_headers, json={
        "items": [{"product_id": p["id"], "batch_id": b["id"], "quantity": 3}],
        "payments": [{"method": "CASH", "amount": 600}]}).json()
    db = SessionLocal()
    item = db.execute(select(InvoiceItem).where(InvoiceItem.invoice_id == inv["invoice_id"])).scalars().first()
    item_id = item.id
    db.close()
    r = client.post("/api/returns", headers=auth_headers, json={
        "invoice_id": inv["invoice_id"], "invoice_item_id": item_id, "qty": 1})
    assert r.status_code == 201
    invoice = client.get(f"/api/invoices/{inv['invoice_id']}", headers=auth_headers).json()
    assert invoice["status"] == "PARTIALLY_REFUNDED"


# --- BUG-003 (FIXED phase 0) --------------------------------------------------
def test_reg_003_multi_batch_auto_split(client, auth_headers):
    global _n
    _n += 1
    p = client.post("/api/products", headers=auth_headers,
                    json={"barcode": f"72000000000{_n:04d}", "name": f"Split T{_n}"}).json()
    a = client.post("/api/batches/receive", headers=auth_headers, json={
        "product_id": p["id"], "quantity_received": 3, "buy_price": 10, "sell_price": 20}).json()
    bb = client.post("/api/batches/receive", headers=auth_headers, json={
        "product_id": p["id"], "quantity_received": 10, "buy_price": 12, "sell_price": 22}).json()
    r = client.post("/api/pos/checkout", headers=auth_headers, json={
        "items": [{"product_id": p["id"], "quantity": 7}],  # no batch -> auto allocation
        "payments": [{"method": "CASH", "amount": 3 * 20 + 4 * 22}],
    })
    assert r.status_code == 201, r.text
    items = r.json()["items"]
    assert len(items) == 2
    by_batch = {it["batch_id"]: it["qty"] for it in items}
    assert by_batch == {a["id"]: 3, bb["id"]: 4}
    # profit uses each batch's real cost (§36): 3*(20-10) + 4*(22-12) = 70
    assert sum(Decimal(str(it["profit"])) for it in items) == Decimal("70")


def test_explicit_batch_selection_does_not_split(client, auth_headers):
    """The cashier deliberately chose a batch -> the sale stays within it (§17)."""
    p, b = _product_with_batch(client, auth_headers, qty=3, buy=10, sell=20)
    client.post("/api/batches/receive", headers=auth_headers, json={
        "product_id": p["id"], "quantity_received": 10, "buy_price": 12, "sell_price": 22})
    r = client.post("/api/pos/checkout", headers=auth_headers, json={
        "items": [{"product_id": p["id"], "batch_id": b["id"], "quantity": 7}],
        "payments": [{"method": "CASH", "amount": 140}]})
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "INSUFFICIENT_STOCK"


def test_auto_split_apportions_line_discount(client, auth_headers):
    global _n
    _n += 1
    p = client.post("/api/products", headers=auth_headers,
                    json={"barcode": f"73000000000{_n:04d}", "name": f"SplitD T{_n}"}).json()
    client.post("/api/batches/receive", headers=auth_headers, json={
        "product_id": p["id"], "quantity_received": 3, "buy_price": 10, "sell_price": 20})
    client.post("/api/batches/receive", headers=auth_headers, json={
        "product_id": p["id"], "quantity_received": 10, "buy_price": 12, "sell_price": 20})
    r = client.post("/api/pos/checkout", headers=auth_headers, json={
        "items": [{"product_id": p["id"], "quantity": 7, "discount": 70}],
        "payments": [{"method": "CASH", "amount": 7 * 20 - 70}]})
    assert r.status_code == 201, r.text
    body = r.json()
    assert Decimal(str(body["discount"])) == Decimal("70")
    assert Decimal(str(body["total_amount"])) == Decimal("70")  # 140 gross - 70 discount
    assert sum(Decimal(str(it["discount"])) for it in body["items"]) == Decimal("70")


# --- BUG-004/005 (FIXED phase 0): atomicity under concurrency ------------------
def test_concurrent_checkouts_unique_numbers_and_no_oversell(client, auth_headers):
    p, b = _product_with_batch(client, auth_headers, qty=5, buy=100, sell=200)
    results: list = []
    lock = threading.Lock()

    def sell_all():
        s = SessionLocal()
        try:
            inv = checkout_svc(
                s,
                items=[CartItem(product_id=p["id"], batch_id=b["id"], quantity=5)],
                payments=[{"method": "CASH", "amount": Decimal("1000")}],
            )
            s.commit()
            with lock:
                results.append(("OK", inv.invoice_number))
        except Exception as exc:
            s.rollback()
            with lock:
                results.append(("ERR", getattr(exc, "code", type(exc).__name__)))
        finally:
            s.close()

    threads = [threading.Thread(target=sell_all) for _ in range(2)]
    for t in threads:
        t.start()
        time.sleep(0.05)  # let the first read-validate, then race the deduction
    for t in threads:
        t.join()

    ok = [r for r in results if r[0] == "OK"]
    db = SessionLocal()
    from app.models import ProductBatch
    batch = db.get(ProductBatch, b["id"])
    qty = batch.current_qty
    db.close()
    assert len(ok) == 1, f"exactly one sale of 5 units must succeed, got {results}"
    assert qty == 0, f"oversell detected: stock={qty}"
    numbers = {r[1] for r in ok}
    assert len(numbers) == 1  # single sale — but numbering tested separately


def test_invoice_numbers_sequential_and_unique(client, auth_headers):
    p, b = _product_with_batch(client, auth_headers, qty=100, buy=10, sell=20)
    nums = []
    for _ in range(3):
        r = client.post("/api/pos/checkout", headers=auth_headers, json={
            "items": [{"product_id": p["id"], "batch_id": b["id"], "quantity": 1}],
            "payments": [{"method": "CASH", "amount": 20}]})
        assert r.status_code == 201, r.text
        nums.append(r.json()["invoice_number"])
    assert len(set(nums)) == 3
    seqs = sorted(int(n.rsplit("-", 1)[1]) for n in nums)
    assert seqs == list(range(seqs[0], seqs[0] + 3)), "numbers must be sequential"


# --- ADR-001: PriceVersion is the strategic price source ----------------------
def test_receive_inherits_active_price_version(client, auth_headers):
    global _n
    _n += 1
    p = client.post("/api/products", headers=auth_headers,
                    json={"barcode": f"74000000000{_n:04d}", "name": f"PV T{_n}"}).json()
    first = client.post("/api/batches/receive", headers=auth_headers, json={
        "product_id": p["id"], "quantity_received": 5, "buy_price": 100, "sell_price": 150}).json()
    # first batch seeds the price history (ADR-001)
    hist = client.get(f"/api/prices/history/{p['id']}", headers=auth_headers).json()
    assert any(h["source"] == "batch_initial" and Decimal(str(h["price"])) == Decimal("150")
               for h in hist), "first batch must seed a SELL price version"
    # change the strategic price
    r = client.post("/api/prices", headers=auth_headers, json={
        "product_id": p["id"], "price_type": "SELL", "price": 199})
    assert r.status_code == 201
    # a new batch without explicit price inherits the new version...
    second = client.post("/api/batches/receive", headers=auth_headers, json={
        "product_id": p["id"], "quantity_received": 5, "buy_price": 120}).json()
    assert Decimal(str(second["sell_price"])) == Decimal("199")
    # ...while the old batch keeps its own price (§16 old/new price)
    got = client.get(f"/api/batches/{first['id']}", headers=auth_headers).json()
    assert Decimal(str(got["sell_price"])) == Decimal("150")


# --- BUG-010 (FIXED phase 0): secret settings ---------------------------------
def test_reg_005_settings_secrets_masked(client, auth_headers):
    key = "audit.test.secret"
    put = client.put("/api/settings", headers=auth_headers,
                     json={"key": key, "value": "SUPER-SECRET-99", "is_secret": True})
    assert put.status_code == 200
    rows = client.get("/api/settings", headers=auth_headers).json()
    row = next(s for s in rows if s["key"] == key)
    assert row.get("is_secret") is True
    assert row["value"] != "SUPER-SECRET-99", "secret value must be masked in API responses"
    assert row.get("has_value") is True
    # keeping the old value via sentinel
    keep = client.put("/api/settings", headers=auth_headers,
                      json={"key": key, "value": "__KEEP__", "is_secret": True})
    assert keep.status_code == 200
    db = SessionLocal()
    from app.models import SystemSetting
    s = db.execute(select(SystemSetting).where(SystemSetting.key == key)).scalar_one()
    db.close()
    assert s.value == "SUPER-SECRET-99", "sentinel must not overwrite the stored secret"


# --- BUG-020 (FIXED phase 0): no raw 500s -------------------------------------
def test_unhandled_exception_returns_friendly_error(client, auth_headers, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("simulated crash — secret details")

    from app.routers import pos as pos_router
    monkeypatch.setattr(pos_router.pos_svc, "checkout", boom)
    c2 = TestClient(app, raise_server_exceptions=False)
    r = c2.post("/api/pos/checkout", headers=auth_headers, json={
        "items": [{"product_id": 1, "quantity": 1}],
        "payments": [{"method": "CASH", "amount": 1}]})
    assert r.status_code == 500
    detail = r.json()["detail"]
    assert detail["code"] == "INTERNAL_ERROR"
    assert "simulated crash" not in detail["message"], "raw exception text must not leak"
    assert detail.get("error_id"), "an error id for support must be present"


# --- BUG-022 (FIXED phase 0): timezone-aware freshness ------------------------
def test_reg_006_price_freshness_timezone_aware():
    from datetime import datetime, timezone
    from app.services.pricing import price_freshness
    assert price_freshness(datetime.utcnow(), now=datetime.now(timezone.utc)) in {"FRESH", "AGING", "STALE"}


# --- BUG-006 (FIXED phase 1): external resolver results persistence ----------
def test_reg_004_resolver_results_persist(client, auth_headers, monkeypatch):
    db = SessionLocal()
    db.add(ExternalSource(code=f"reg{time.time_ns()}", name="reg",
                          source_type="PRODUCT", base_url="http://example.test/{barcode}",
                          is_active=True))
    db.commit()
    db.close()

    import httpx
    import app.services.providers.base as pbase

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"name": "Resolved Product", "brand": "RegBrand"})

    real_client = httpx.Client
    monkeypatch.setattr(pbase.httpx, "Client",
                        lambda *a, **k: real_client(transport=httpx.MockTransport(handler)))

    # POST is the side-effectful lookup; GET stays read-only (design fix)
    r = client.post("/api/barcode/resolve/5901234123457", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["origin"] == "external"
    assert r.json()["need_manual"] is True  # external data ALWAYS needs human review (BUG-007)

    db = SessionLocal()
    rows = db.execute(select(ProductResolverResult).where(
        ProductResolverResult.barcode == "5901234123457")).scalars().all()
    db.close()
    monkeypatch.undo()
    assert len(rows) >= 1, "external candidates must be persisted for human review"
