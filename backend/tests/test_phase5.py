"""Phase-5 acceptance tests: full §49 report set + dashboard SQL aggregates +
code-quality cleanups (BUG-022)."""
from __future__ import annotations

import os
import tempfile
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

_TMP = Path(tempfile.mkdtemp(prefix="supermarket_p5_"))
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_TMP / 'p5.db'}")

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


def _mk(client, H, qty=10, buy=1000, sell=2000, expiry=None):
    global _n
    _n += 1
    bc = f"62{_n:011d}"
    total = sum(int(d) * (3 if i % 2 else 1) for i, d in enumerate(bc))
    bc += str((10 - total % 10) % 10)
    p = client.post("/api/products", headers=H, json={"barcode": bc, "name": f"R5 T{_n}"}).json()
    b = client.post("/api/batches/receive", headers=H, json={
        "product_id": p["id"], "quantity_received": qty, "buy_price": buy,
        "sell_price": sell, "expiry_date": expiry}).json()
    return p, b


@pytest.fixture(scope="module", autouse=True)
def seeded_activity(client, H):
    """Known economic activity all reports are asserted against (DELTA-based:
    other test modules legitimately share today's numbers in the suite run)."""
    base_dash = client.get("/api/reports/dashboard", headers=H).json()
    base_cash = next((r for r in client.get(
        f"/api/reports/cashiers?start={TODAY}&end={TODAY}", headers=H).json()
        if r["username"] == "admin"), None) or {"invoice_count": 0, "total_sales": 0, "profit": 0}
    baseline = {"sales_today": Decimal(str(base_dash["sales"]["today"])),
                "profit_today": Decimal(str(base_dash["profit"]["today"])),
                "inv_value": Decimal(str(base_dash["inventory"]["value"])),
                "cash_cnt": base_cash["invoice_count"],
                "cash_total": Decimal(str(base_cash["total_sales"])),
                "cash_profit": Decimal(str(base_cash["profit"]))}
    p1, b1 = _mk(client, H, qty=10, buy=1000, sell=2000)          # sold 2
    p2, b2 = _mk(client, H, qty=8, buy=500, sell=900)             # sold 1 with discount
    p3, b3 = _mk(client, H, qty=5, buy=2000, sell=3000,
                 expiry=(date.today() + timedelta(days=2)).isoformat())  # expiring
    _mk(client, H, qty=4, buy=4000, sell=5000)                    # second buy price for p-name series
    inv1 = client.post("/api/pos/checkout", headers=H, json={
        "items": [{"product_id": p1["id"], "batch_id": b1["id"], "quantity": 2}],
        "payments": [{"method": "CASH", "amount": 4000}]}).json()
    inv2 = client.post("/api/pos/checkout", headers=H, json={
        "items": [{"product_id": p2["id"], "batch_id": b2["id"], "quantity": 1, "discount": 100}],
        "payments": [{"method": "CASH", "amount": 800}]}).json()
    client.post("/api/inventory/adjust", headers=H, json={
        "batch_id": b3["id"], "new_current_qty": 4, "reason": "شکستگی"})
    return {"p1": p1, "b1": b1, "p2": p2, "b2": b2, "p3": p3, "b3": b3,
            "inv1": inv1, "inv2": inv2, "base": baseline}


TODAY = date.today().isoformat()


def test_dashboard_matches_known_activity(client, H, seeded_activity):
    d = client.get("/api/reports/dashboard", headers=H).json()
    b = seeded_activity["base"]
    # 4000 + (900-100) = 4800 added today
    assert Decimal(str(d["sales"]["today"])) - b["sales_today"] == Decimal("4800")
    assert d["sales"]["invoice_count_today"] >= 2
    # profit: 2*(2000-1000) + 1*(900-500-100) = 2300 added
    assert Decimal(str(d["profit"]["today"])) - b["profit_today"] == Decimal("2300")
    # remaining stock value added: p1 8*1000 + p2 7*500 + p3 4*2000 + p4 4*4000
    assert Decimal(str(d["inventory"]["value"])) - b["inv_value"] == Decimal(
        str(8 * 1000 + 7 * 500 + 4 * 2000 + 4 * 4000))
    assert d["inventory"]["product_count"] >= 4
    # expiry bucket: p3 expires in 2 days -> EXPIRING_3_DAYS
    assert any(e["product_name"] == seeded_activity["p3"]["name"]
               for e in d["expiry"]["EXPIRING_3_DAYS"])


def test_sales_report_daily_groups(client, H):
    r = client.get(f"/api/reports/sales?start={TODAY}&end={TODAY}&group=daily", headers=H).json()
    assert r["group"] == "daily"
    row = next(g for g in r["groups"] if g["date"] == TODAY)
    assert row and Decimal(str(row["total"])) >= Decimal("4800")  # includes other modules
    assert row["invoice_count"] >= 2


def test_sales_report_product_groups(client, H, seeded_activity):
    r = client.get(f"/api/reports/sales?start={TODAY}&end={TODAY}&group=product", headers=H).json()
    names = {g["product"]: g for g in r["groups"]}
    p1 = names[seeded_activity["p1"]["name"]]
    assert p1["qty"] == 2 and Decimal(str(p1["revenue"])) == Decimal("4000")
    p2 = names[seeded_activity["p2"]["name"]]
    assert Decimal(str(p2["revenue"])) == Decimal("800")


def test_cashier_report(client, H, seeded_activity):
    rows = client.get(f"/api/reports/cashiers?start={TODAY}&end={TODAY}", headers=H).json()
    admin = next(r for r in rows if r["username"] == "admin")
    b = seeded_activity["base"]
    assert admin["invoice_count"] - b["cash_cnt"] == 2
    assert Decimal(str(admin["total_sales"])) - b["cash_total"] == Decimal("4800")
    assert Decimal(str(admin["profit"])) - b["cash_profit"] == Decimal("2300")


def test_inventory_report(client, H, seeded_activity):
    rows = client.get("/api/reports/inventory", headers=H).json()
    p1 = next(r for r in rows if r["product_id"] == seeded_activity["p1"]["id"])
    assert p1["total_qty"] == 8 and Decimal(str(p1["value_at_cost"])) == Decimal("8000")
    p2 = next(r for r in rows if r["product_id"] == seeded_activity["p2"]["id"])
    assert p2["total_qty"] == 7


def test_purchase_cost_history(client, H, seeded_activity):
    rows = client.get("/api/reports/purchase-cost", headers=H)
    assert rows.status_code == 200
    rows = rows.json()
    assert len(rows) >= 4
    assert all("buy_price" in r and "received_at" in r for r in rows)
    assert rows[0]["received_at"] >= rows[-1]["received_at"]  # newest first


def test_expiry_report_full(client, H, seeded_activity):
    buckets = client.get("/api/reports/expiry", headers=H).json()
    assert any(i["product_name"] == seeded_activity["p3"]["name"]
               for i in buckets.get("EXPIRING_3_DAYS", []))


def test_adjustments_report(client, H, seeded_activity):
    rows = client.get("/api/reports/adjustments", headers=H).json()
    row = next(r for r in rows if r["product_name"] == seeded_activity["p3"]["name"])
    assert row["movement_type"] == "ADJUSTMENT" and row["note"] == "شکستگی"
    assert row["by"] == "admin"


def test_products_pagination_total_is_real_count(client, H):
    for _ in range(3):
        _mk(client, H, qty=1, buy=1, sell=2)
    r = client.get("/api/products?limit=2", headers=H).json()
    assert r["total"] >= 7          # all products, not just the page
    assert len(r["items"]) == 2     # page size respected


def test_profit_by_batch_still_consistent(client, H, seeded_activity):
    rows = client.get(f"/api/reports/profit?start={TODAY}&end={TODAY}", headers=H).json()
    b1 = next(r for r in rows if r["batch_id"] == seeded_activity["b1"]["id"])
    assert Decimal(str(b1["profit"])) == Decimal("2000")


def test_purchase_cost_requires_cost_permission(client, H):
    client.post("/api/users", headers=H, json={
        "username": "kasa5", "password": "kasa1234", "roles": ["Cashier"]})
    t = client.post("/api/auth/login", data={"username": "kasa5", "password": "kasa1234"}).json()["access_token"]
    C = {"Authorization": f"Bearer {t}"}
    assert client.get("/api/reports/purchase-cost", headers=C).status_code == 403
    assert client.get("/api/reports/inventory", headers=C).status_code == 200
