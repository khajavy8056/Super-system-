# -*- coding: utf-8 -*-
"""v3.7 — POS financial proof (§6–§8 hardening).

The Phase-0 suite already proves the exact §6 scenario (A=3/B=10, buy 7 →
3+4 with per-batch profit), return caps and no-oversell. These tests close the
remaining gaps:

1. §7 — N concurrent checkouts from shared stock ALL get valid, UNIQUE,
   sequential invoice numbers (the old race test only proved one winner).
2. §6 — line + invoice + coupon discounts combined with tax are each counted
   exactly once: gross − Σdiscounts + tax(gross − Σdiscounts).
3. §10 — a coupon can never push the total below zero (pricing-law direction).
"""
from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta
from decimal import Decimal

from app.database import SessionLocal
from app.models import ProductBatch
from app.services.pos import CartItem, checkout as checkout_svc

_n = 1000


def _product_with_batch(client, headers, *, qty=10, buy=1000, sell=2000, **kw):
    global _n
    _n += 1
    p = client.post("/api/products", headers=headers,
                    json={"barcode": f"77000000000{_n:04d}", "name": f"V37 T{_n}"}).json()
    b = client.post("/api/batches/receive", headers=headers,
                    json={"product_id": p["id"], "quantity_received": qty,
                          "buy_price": buy, "sell_price": sell, **kw}).json()
    return p, b


def test_concurrent_checkouts_all_get_unique_numbers(client, auth_headers):
    """§7 — 4 terminals sell qty 1 each from stock 4: 4 sales, 4 unique numbers."""
    p, b = _product_with_batch(client, auth_headers, qty=4, buy=100, sell=200)
    barrier = threading.Barrier(4)
    results: list = []
    lock = threading.Lock()

    def sell_one():
        s = SessionLocal()
        try:
            barrier.wait(timeout=10)
            inv = checkout_svc(
                s, items=[CartItem(product_id=p["id"], batch_id=b["id"], quantity=1)],
                payments=[{"method": "CASH", "amount": Decimal("200")}])
            s.commit()
            with lock:
                results.append(("OK", inv.invoice_number))
        except Exception as exc:  # noqa: BLE001 — collected, asserted below
            s.rollback()
            with lock:
                results.append(("ERR", getattr(exc, "code", type(exc).__name__)))
        finally:
            s.close()

    threads = [threading.Thread(target=sell_one) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert not any(t.is_alive() for t in threads), "checkout thread hung"

    oks = sorted(n for st, n in results if st == "OK")
    assert len(oks) == 4, f"all 4 concurrent sales must succeed, got {results}"
    assert len(set(oks)) == 4, f"invoice numbers must be unique: {oks}"
    seqs = sorted(int(n.rsplit("-", 1)[1]) for n in oks)
    assert seqs == list(range(seqs[0], seqs[0] + 4)), f"numbers must be sequential: {oks}"

    s = SessionLocal()
    try:
        assert s.get(ProductBatch, b["id"]).current_qty == 0
    finally:
        s.close()


def test_line_invoice_coupon_discounts_counted_once_with_tax(client, auth_headers):
    """§6 — gross 4000, line 300, invoice 200, coupon 100, tax 10% → 3740."""
    p, b = _product_with_batch(client, auth_headers, qty=10, buy=500, sell=2000)
    now = datetime.utcnow()
    code = f"V37-{_n}"
    r = client.post("/api/marketing/coupons", headers=auth_headers, json={
        "code": code, "discount_type": "FIXED", "discount_value": 100,
        "valid_from": (now - timedelta(days=1)).isoformat(),
        "valid_until": (now + timedelta(days=1)).isoformat(),
        "usage_limit": 10})
    assert r.status_code == 201, r.text

    r = client.post("/api/pos/checkout", headers=auth_headers, json={
        "items": [{"product_id": p["id"], "batch_id": b["id"], "quantity": 2, "discount": 300}],
        "invoice_discount": 200,
        "coupon_code": code,
        "tax_rate": 10,
        "payments": [{"method": "CASH", "amount": 3740}],
    })
    assert r.status_code == 201, r.text
    body = r.json()
    assert Decimal(str(body["subtotal"])) == Decimal("4000")
    assert Decimal(str(body["discount"])) == Decimal("600")       # 300 + 200 + 100
    assert Decimal(str(body["tax"])) == Decimal("340")            # 10% of 3400
    assert Decimal(str(body["total_amount"])) == Decimal("3740")


def test_oversized_coupon_clamps_total_at_zero(client, auth_headers):
    """§10 — a FIXED coupon larger than the basket cannot create a negative total."""
    p, b = _product_with_batch(client, auth_headers, qty=10, buy=500, sell=1000)
    now = datetime.utcnow()
    code = f"BIG-{_n}"
    r = client.post("/api/marketing/coupons", headers=auth_headers, json={
        "code": code, "discount_type": "FIXED", "discount_value": 999999,
        "valid_from": (now - timedelta(days=1)).isoformat(),
        "valid_until": (now + timedelta(days=1)).isoformat(),
        "usage_limit": 10})
    assert r.status_code == 201, r.text

    r = client.post("/api/pos/checkout", headers=auth_headers, json={
        "items": [{"product_id": p["id"], "batch_id": b["id"], "quantity": 1}],
        "coupon_code": code,
        "payments": [{"method": "CASH", "amount": 0}],
    })
    assert r.status_code == 201, r.text
    body = r.json()
    assert Decimal(str(body["total_amount"])) == Decimal("0")
    assert Decimal(str(body["discount"])) == Decimal("1000")  # clamped to gross
