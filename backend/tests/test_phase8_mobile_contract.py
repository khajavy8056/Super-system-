"""Phase-8: the contract the mobile PWA depends on (§10-13, §21).

The phone is a first-class client, not a shrunken desktop. Every endpoint the
mobile app calls is pinned here with the exact field names `frontend/mobile/app.js`
reads, so a backend refactor breaks a test instead of silently breaking the phone
of a person standing in an aisle.
"""
import json
import re
from pathlib import Path

import pytest

MOBILE_JS = Path(__file__).resolve().parents[2] / "frontend" / "mobile" / "app.js"


_seq = 0


@pytest.fixture()
def sellable(client, auth_headers):
    """A weighted product (decimal unit) with two priced batches."""
    global _seq
    _seq += 1
    units = client.get("/api/units", headers=auth_headers).json()
    kg = next(u for u in units if u["allow_decimal"])
    p = client.post("/api/products", headers=auth_headers, json={
        "barcode": f"6268{_seq:03d}00001", "name": f"پنیر محلی {_seq}",
        "sku": f"MOB-{_seq}", "unit_id": kg["id"]}).json()
    for price in (120000, 135000):
        client.post("/api/batches/receive", headers=auth_headers, json={
            "product_id": p["id"], "quantity_received": 10,
            "buy_price": price - 20000, "sell_price": price,
            "consumer_price": price + 5000})
    return p


# --------------------------------------------------------------------------
# home screen
# --------------------------------------------------------------------------
def test_home_dashboard_exposes_every_kpi_the_phone_renders(client, auth_headers):
    d = client.get("/api/reports/dashboard", headers=auth_headers).json()
    assert {"today", "month", "invoice_count_today", "avg_invoice_today"} <= set(d["sales"])
    assert {"today", "month"} <= set(d["profit"])
    assert {"value", "product_count", "low_stock_count", "no_stock_count"} <= set(d["inventory"])
    # the five expiry buckets the mobile home screen lists
    for bucket in ("EXPIRED", "EXPIRING_TODAY", "EXPIRING_3_DAYS",
                   "EXPIRING_7_DAYS", "EXPIRING_30_DAYS"):
        assert isinstance(d["expiry"][bucket], list)


def test_active_sessions_feed_drives_the_resume_card(client, auth_headers):
    r = client.get("/api/inventory/stocktake-sessions/active", headers=auth_headers)
    assert r.status_code == 200
    for s in r.json():
        assert {"id", "name", "counted", "total", "percent", "resumable"} <= set(s)


def test_currency_and_units_bootstrap_the_mobile_formatter(client, auth_headers):
    cur = client.get("/api/settings/currency", headers=auth_headers).json()
    assert cur["code"] in ("IRT", "IRR") and cur["label"]
    units = client.get("/api/units", headers=auth_headers).json()
    assert any(u["allow_decimal"] for u in units), "weighted goods need a decimal unit"
    assert all({"id", "name", "symbol", "allow_decimal", "decimals"} <= set(u) for u in units)


def test_me_returns_permissions_so_tabs_can_be_hidden(client, auth_headers):
    me = client.get("/api/auth/me", headers=auth_headers).json()
    assert isinstance(me["permissions"], list) and me["permissions"]
    assert "pos.sell" in me["permissions"]


# --------------------------------------------------------------------------
# mobile POS: scan -> pick price -> qty -> pay
# --------------------------------------------------------------------------
def test_scan_lookup_returns_batches_the_sheet_needs(client, auth_headers, sellable):
    r = client.get("/api/pos/search", headers=auth_headers,
                   params={"q": sellable["barcode"], "limit": 5}).json()
    item = r["items"][0]
    assert item["product_id"] == sellable["id"]
    assert item["exact"] is True
    assert item["price_count"] == 2, "two prices must stay two prices — never merged"
    assert item["unit"]["allow_decimal"] is True
    for b in item["batches"]:
        assert {"batch_id", "batch_number", "sell_price", "consumer_price",
                "current_qty", "expiry_date", "days_left", "is_recommended"} <= set(b)
    assert sum(1 for b in item["batches"] if b["is_recommended"]) == 1


def test_mobile_checkout_with_decimal_qty_and_chosen_batch(client, auth_headers, sellable):
    search = client.get("/api/pos/search", headers=auth_headers,
                        params={"q": sellable["barcode"]}).json()["items"][0]
    batch = search["batches"][1]           # cashier deliberately picks the 2nd price
    qty = 1.25
    amount = float(batch["sell_price"]) * qty
    r = client.post("/api/pos/checkout", headers=auth_headers, json={
        "items": [{"product_id": sellable["id"], "batch_id": batch["batch_id"],
                   "quantity": qty}],
        "payments": [{"method": "CARD", "amount": amount}]})
    assert r.status_code in (200, 201), r.text
    inv = r.json()
    assert inv["invoice_number"]
    assert float(inv["total_amount"]) == pytest.approx(amount)
    after = client.get("/api/pos/search", headers=auth_headers,
                       params={"q": sellable["barcode"]}).json()["items"][0]
    chosen = next(b for b in after["batches"] if b["batch_id"] == batch["batch_id"])
    assert float(chosen["current_qty"]) == pytest.approx(10 - qty)


def test_mobile_coupon_validate_matches_the_payment_sheet_payload(client, auth_headers, sellable):
    client.post("/api/marketing/coupons", headers=auth_headers, json={
        "code": f"MOB{_seq}OFF", "discount_type": "PERCENT", "discount_value": 10,
        "usage_limit": 5})
    r = client.post("/api/marketing/coupons/validate", headers=auth_headers, json={
        "code": f"MOB{_seq}OFF", "amount": 200000, "customer_phone": None})
    assert r.status_code == 200, r.text
    assert float(r.json()["discount"]) == 20000


# --------------------------------------------------------------------------
# inventory & stock-in from the phone
# --------------------------------------------------------------------------
def test_stock_list_has_the_fields_the_inventory_tab_shows(client, auth_headers, sellable):
    rows = client.get("/api/inventory/stock", headers=auth_headers).json()
    row = next(r for r in rows if r["product_id"] == sellable["id"])
    assert {"name", "barcode", "total_stock", "min_stock_alert", "unit_id"} <= set(row)


def test_stock_in_by_barcode_works_without_knowing_the_product_id(client, auth_headers, sellable):
    """The phone scans a barcode; it must not need an internal id."""
    r = client.post("/api/batches/receive", headers=auth_headers, json={
        "barcode": sellable["barcode"], "quantity_received": 3.5,
        "buy_price": 100000, "sell_price": 140000})
    assert r.status_code in (200, 201), r.text
    assert r.json()["batch_number"]


def test_barcode_lookup_endpoint_used_by_the_stock_in_form(client, auth_headers, sellable):
    r = client.get(f"/api/products/barcode/{sellable['barcode']}", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["name"] == sellable["name"]


# --------------------------------------------------------------------------
# 'more' menu list screens
# --------------------------------------------------------------------------
def test_more_menu_list_endpoints_all_answer(client, auth_headers):
    assert isinstance(client.get("/api/products", headers=auth_headers,
                                 params={"limit": 100}).json()["items"], list)
    assert isinstance(client.get("/api/customers", headers=auth_headers).json(), list)
    assert isinstance(client.get("/api/marketing/coupons", headers=auth_headers,
                                 params={"limit": 50}).json(), list)
    assert isinstance(client.get("/api/invoices", headers=auth_headers).json()["items"], list)


# --------------------------------------------------------------------------
# static guard: the shipped JS must not call an endpoint that does not exist
# --------------------------------------------------------------------------
def test_every_api_path_in_mobile_js_exists_in_the_openapi_schema(client):
    src = MOBILE_JS.read_text(encoding="utf-8")
    schema_paths = client.get("/openapi.json").json()["paths"]

    called = set(re.findall(r'api\(\s*[`"\']([^`"\'?]+)', src))
    called |= set(re.findall(r'api\(\s*`([^`?]+)', src))
    missing = []
    for raw in called:
        # normalise template holes: `/products/barcode/${x}` -> a matcher
        pattern = "^" + re.escape("/api" + raw).replace(r"\$\{", "\x00").split("\x00")[0]
        if not any(re.match(pattern.rstrip("/") + r"(/|$|\{)", p) for p in schema_paths):
            missing.append(raw)
    assert not missing, f"mobile app calls unknown endpoints: {missing}"


def test_mobile_app_never_hardcodes_a_localhost_backend():
    """The phone is not the server: hardcoding localhost breaks LAN use (§27)."""
    src = MOBILE_JS.read_text(encoding="utf-8")
    assert "localhost" not in src and "127.0.0.1" not in src
    assert 'const API = "/api"' in src, "mobile must use a relative API base"


def test_service_worker_never_caches_or_fakes_api_responses():
    sw = (MOBILE_JS.parents[1] / "sw.js").read_text(encoding="utf-8")
    assert 'url.pathname.startsWith("/api")' in sw, "API must be network-only"


def test_mobile_root_without_trailing_slash_redirects(client):
    """A phone user types "<lan-ip>:8000/m" by hand; a bare StaticFiles mount
    404s on that and only answers "/m/"."""
    r = client.get("/m", follow_redirects=False)
    assert r.status_code in (301, 307, 308), \
        f"/m must redirect to /m/, got {r.status_code}"
    assert r.headers["location"].endswith("/m/")
    assert client.get("/m", follow_redirects=True).status_code == 200
