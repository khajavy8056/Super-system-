# -*- coding: utf-8 -*-
"""v3.7 — till & data security (§34 hardening).

1. SEC-002 — a cashier (no ``pricing.view_cost``) receives cost figures as
   ``None`` (shape preserved) across dashboard / batches / invoices / POS;
   managers still see the numbers.
2. SEC-002 — ``/reports/profit`` requires ``pricing.view_cost`` outright (403).
3. §37 — the manager-configured manual-discount cap (``DISCOUNT_OVER_POLICY``).
4. §6 — caller-supplied unit prices can never override the batch prices.
5. SEC-001b — the setup wizard cannot complete without admin credentials.
6. SEC-001a — production refuses to boot with the factory SECRET_KEY.
"""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest

from app.database import SessionLocal
from app.services.pos import CartItem, checkout as checkout_svc

_n = 2000


def _product_with_batch(client, headers, *, qty=10, buy=1000, sell=2000, **kw):
    global _n
    _n += 1
    p = client.post("/api/products", headers=headers,
                    json={"barcode": f"77000000002{_n:04d}", "name": f"V37 S{_n}"}).json()
    b = client.post("/api/batches/receive", headers=headers,
                    json={"product_id": p["id"], "quantity_received": qty,
                          "buy_price": buy, "sell_price": sell, **kw}).json()
    return p, b


@pytest.fixture(scope="module")
def cashier_h(client, auth_headers):
    client.post("/api/users", headers=auth_headers, json={
        "username": "v37cashier", "password": "kasa1234",
        "full_name": "V37 Cashier", "roles": ["Cashier"]})
    r = client.post("/api/auth/login", data={"username": "v37cashier", "password": "kasa1234"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_cashier_dashboard_costs_redacted(client, auth_headers, cashier_h):
    d = client.get("/api/reports/dashboard", headers=cashier_h).json()
    assert d["profit"] is None, "cashier must not see profit"
    assert d["accounting"] is None, "cashier must not see the accounting block"
    assert d["inventory"]["value"] is None, "at-cost stock value must be redacted"
    # …but the till-relevant figures stay visible (regression: redaction must not blank the page)
    assert isinstance(d["sales"]["today"], (int, float))
    m = client.get("/api/reports/dashboard", headers=auth_headers).json()
    assert isinstance(m["profit"]["today"], (int, float))
    assert isinstance(m["accounting"], dict)


def test_cashier_batches_and_invoices_redacted(client, auth_headers, cashier_h):
    p, b = _product_with_batch(client, auth_headers, qty=5, buy=1000, sell=2500)
    rows = client.get("/api/batches", headers=cashier_h).json()
    mine = next(r for r in rows if r["id"] == b["id"])
    assert mine["buy_price"] is None
    assert mine["sell_price"] == 2500  # selling prices are till data, not cost
    mgr = client.get(f"/api/batches/{b['id']}", headers=auth_headers).json()
    assert mgr["buy_price"] == 1000

    r = client.post("/api/pos/checkout", headers=cashier_h, json={
        "items": [{"product_id": p["id"], "batch_id": b["id"], "quantity": 1}],
        "tax_rate": 0,
        "payments": [{"method": "CASH", "amount": 2500}]})
    assert r.status_code == 201, r.text
    inv_id = r.json()["invoice_id"]
    assert r.json()["items"][0]["unit_buy_price"] is None
    assert r.json()["items"][0]["profit"] is None
    got = client.get(f"/api/invoices/{inv_id}", headers=cashier_h).json()
    assert got["items"][0]["unit_buy_price"] is None
    got_mgr = client.get(f"/api/invoices/{inv_id}", headers=auth_headers).json()
    assert got_mgr["items"][0]["unit_buy_price"] == 1000


def test_profit_requires_cost_permission(client, auth_headers, cashier_h):
    r = client.get("/api/reports/profit", headers=cashier_h)
    assert r.status_code == 403, r.text
    assert client.get("/api/reports/profit", headers=auth_headers).status_code == 200


def test_manual_discount_cap_enforced(client, auth_headers):
    p, b = _product_with_batch(client, auth_headers, qty=10, buy=100, sell=1000)
    client.put("/api/settings", headers=auth_headers,
               json={"key": "pos.max_manual_discount_pct", "value": "10"})
    try:
        body = {"items": [{"product_id": p["id"], "batch_id": b["id"],
                           "quantity": 2, "discount": 600}],
                "tax_rate": 0,
                "payments": [{"method": "CASH", "amount": 1400}]}
        r = client.post("/api/pos/checkout", headers=auth_headers, json=body)
        assert r.status_code == 422, r.text
        assert r.json()["detail"]["code"] == "DISCOUNT_OVER_POLICY"
        body["items"][0]["discount"] = 100
        body["payments"] = [{"method": "CASH", "amount": 1900}]
        assert client.post("/api/pos/checkout", headers=auth_headers, json=body).status_code == 201
    finally:
        client.put("/api/settings", headers=auth_headers,
                   json={"key": "pos.max_manual_discount_pct", "value": "0"})


def test_cart_item_prices_resolved_from_batch(client, auth_headers):
    """A caller that stuffs prices into CartItem gets them overwritten from the batch."""
    p, b = _product_with_batch(client, auth_headers, qty=10, buy=1000, sell=2000)
    s = SessionLocal()
    try:
        inv = checkout_svc(
            s, items=[CartItem(product_id=p["id"], batch_id=b["id"], quantity=Decimal(1),
                               unit_sell_price=Decimal("1"), unit_buy_price=Decimal("999999"))],
            payments=[{"method": "CASH", "amount": Decimal("2000")}])
        s.commit()
        assert inv.total_amount == Decimal("2000"), f"batch price must win, got {inv.total_amount}"
        assert inv.items[0].unit_sell_price == Decimal("2000")
        assert inv.items[0].unit_buy_price == Decimal("1000")
    finally:
        s.close()


def test_setup_requires_admin_credentials(client, auth_headers, monkeypatch):
    from app.models import SystemSetting
    from app.services import license as lic
    from app.services.timeservice import local_today
    from sqlalchemy import select

    def fake(url, key, hw):
        return {"status": "SUCCESS", "type": "FULL", "owner": "V37",
                "expires": (local_today() + timedelta(days=10)).isoformat()}
    monkeypatch.setattr(lic, "fetch_remote", fake)
    client.post("/api/setup/license/activate", json={"key": "KEY-V371-0000-0000"})
    with SessionLocal() as db:
        row = db.execute(select(SystemSetting).where(SystemSetting.key == "setup.done")).scalar_one_or_none()
        if row is None:
            row = SystemSetting(key="setup.done", value="")
            db.add(row)
        else:
            row.value = ""
        db.commit()
    try:
        r = client.post("/api/setup/complete", json={"store_name": "x"})
        assert r.status_code == 422, r.text
        assert r.json()["detail"]["code"] == "ADMIN_REQUIRED"
        r = client.post("/api/setup/complete", json={
            "store_name": "x", "admin_username": "admin", "admin_password": "admin123"})
        assert r.status_code == 200, r.text
        assert r.json()["admin_username"] == "admin"
    finally:
        with SessionLocal() as db:
            row = db.execute(select(SystemSetting).where(SystemSetting.key == "setup.done")).scalar_one_or_none()
            if row is None:
                db.add(SystemSetting(key="setup.done", value="1"))
            elif not row.value:
                row.value = "1"
            db.commit()


def test_production_refuses_default_secret():
    import pydantic
    from app.config import DEFAULT_SECRET_KEY, Settings
    with pytest.raises(pydantic.ValidationError):
        Settings(ENVIRONMENT="production", SECRET_KEY=DEFAULT_SECRET_KEY)
    # non-production keeps working with the default (dev/test ergonomics)
    assert Settings(ENVIRONMENT="development", SECRET_KEY=DEFAULT_SECRET_KEY).SECRET_KEY == DEFAULT_SECRET_KEY


def test_permissions_policy_header_present(client):
    r = client.get("/api/reports/dashboard", headers={})
    assert r.status_code in (401, 403)  # unauthenticated — but headers still applied
    assert "camera=()" in r.headers.get("Permissions-Policy", "")
