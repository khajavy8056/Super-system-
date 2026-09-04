"""Audit-phase regression tests (2026-09-04).

These tests assert the CORRECT expected behaviour for bugs confirmed during the
repository audit (see BUG_REPORT.md). They are marked ``xfail(strict=True)`` so
the suite stays honest: while the bug exists the test "expectedly fails"; after
the fix the xfail marker MUST be removed — if it is not, the strict flag turns
the unexpected pass into a failure, so a fix can never silently bypass its
regression test (master rule §65).
"""
from __future__ import annotations

import os
import tempfile
from decimal import Decimal
from pathlib import Path

import pytest

_TMP = Path(tempfile.mkdtemp(prefix="supermarket_reg_"))
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_TMP / 'reg.db'}")

from fastapi.testclient import TestClient  # noqa: E402

from app.database import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models import ExternalSource, ProductResolverResult  # noqa: E402
from app.services.pos import CartItem, PosError, checkout as checkout_svc  # noqa: E402


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


def _product_with_batch(client, headers, *, qty=10, buy=1000, sell=2000):
    global _n
    _n += 1
    p = client.post("/api/products", headers=headers,
                    json={"barcode": f"71000000000{_n:04d}", "name": f"Reg T{_n}"}).json()
    b = client.post("/api/batches/receive", headers=headers,
                    json={"product_id": p["id"], "quantity_received": qty,
                          "buy_price": buy, "sell_price": sell}).json()
    return p, b


# --- BUG-001 -----------------------------------------------------------------
@pytest.mark.xfail(strict=True, reason="BUG-001: discount is subtracted twice at checkout")
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
    assert inv.total_amount == Decimal("1500.00"), (
        f"gross=2000, discount=500 -> total must be 1500, got {inv.total_amount}")


# --- BUG-002 -----------------------------------------------------------------
@pytest.mark.xfail(strict=True, reason="BUG-002: cumulative returns may exceed purchased qty")
def test_reg_002_return_cannot_exceed_item_qty(client, auth_headers):
    p, b = _product_with_batch(client, auth_headers, qty=10, buy=100, sell=200)
    inv = client.post("/api/pos/checkout", headers=auth_headers, json={
        "items": [{"product_id": p["id"], "batch_id": b["id"], "quantity": 2}],
        "payments": [{"method": "CASH", "amount": 400}],
    }).json()

    db = SessionLocal()
    from app.models import InvoiceItem
    from sqlalchemy import select
    item = db.execute(select(InvoiceItem).where(InvoiceItem.invoice_id == inv["invoice_id"])).scalars().first()
    item_id = item.id
    db.close()

    r1 = client.post("/api/returns", headers=auth_headers, json={
        "invoice_id": inv["invoice_id"], "invoice_item_id": item_id, "qty": 2})
    assert r1.status_code == 201
    r2 = client.post("/api/returns", headers=auth_headers, json={
        "invoice_id": inv["invoice_id"], "invoice_item_id": item_id, "qty": 2})
    assert r2.status_code == 422, "returning more than purchased must be rejected"
    stock = client.get(f"/api/batches/{b['id']}", headers=auth_headers).json()["current_qty"]
    assert stock == 10, f"stock inflated to {stock}"


# --- BUG-003 -----------------------------------------------------------------
@pytest.mark.xfail(strict=True, reason="BUG-003: no cross-batch split allocation")
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


# --- BUG-006 -----------------------------------------------------------------
@pytest.mark.xfail(strict=True, reason="BUG-006: external resolver results are never persisted")
def test_reg_004_resolver_results_persist(client, auth_headers, monkeypatch):
    db = SessionLocal()
    db.add(ExternalSource(code=f"reg{__import__('time').time_ns()}", name="reg",
                          source_type="PRODUCT", base_url="http://example.test/{barcode}",
                          is_active=True))
    db.commit()
    db.close()

    class _Resp:
        def raise_for_status(self): pass
        def json(self): return {"name": "Resolved Product", "brand": "RegBrand"}

    import app.services.resolvers as resolvers
    monkeypatch.setattr(resolvers.httpx, "get", lambda *a, **k: _Resp())

    r = client.get("/api/barcode/resolve/7310500000000", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["origin"] == "external"

    db = SessionLocal()
    from sqlalchemy import select as _sel
    rows = db.execute(_sel(ProductResolverResult).where(
        ProductResolverResult.barcode == "7310500000000")).scalars().all()
    db.close()
    assert len(rows) >= 1, "external candidates must be persisted for human review"


# --- BUG-010 -----------------------------------------------------------------
@pytest.mark.xfail(strict=True, reason="BUG-010: secret settings are returned in plaintext")
def test_reg_005_settings_secrets_masked(client, auth_headers):
    key = "audit.test.secret"
    put = client.put("/api/settings", headers=auth_headers,
                     json={"key": key, "value": "SUPER-SECRET-99", "is_secret": True})
    assert put.status_code == 200
    rows = client.get("/api/settings", headers=auth_headers).json()
    row = next(s for s in rows if s["key"] == key)
    assert row.get("is_secret") is True
    assert row["value"] != "SUPER-SECRET-99", "secret value must be masked in API responses"


# --- BUG-022 (price_freshness tz) ---------------------------------------------
@pytest.mark.xfail(strict=True, reason="BUG-022: naive/aware datetime mix raises TypeError")
def test_reg_006_price_freshness_timezone_aware():
    from datetime import datetime, timezone
    from app.services.pricing import price_freshness
    assert price_freshness(datetime.utcnow(), now=datetime.now(timezone.utc)) in {"FRESH", "AGING", "STALE"}
