"""v2.0 — contract tests for the NATIVE Android app (mobile-android/, Java).

The phone talks to the PC only through JSON; these tests pin that contract:
  * every path the Java code calls exists in the OpenAPI schema,
  * POST + X-HTTP-Method-Override: PATCH works (HttpURLConnection has no PATCH),
  * /mobile/sync applies the op types the phone queues and reconciles a sale
    the phone priced with a stale catalogue instead of dropping it,
  * the pull carries the fields the phone's SQLite needs,
  * no WebView remains in the Android sources (the user's hard requirement).
"""
from __future__ import annotations

import re
from pathlib import Path

ANDROID = Path(__file__).resolve().parents[2] / "mobile-android" / "app" / "src" / "main"
JAVA = ANDROID / "java" / "ir" / "khajavy" / "supermarket"


def _java_sources() -> str:
    return "\n".join(p.read_text(encoding="utf-8") for p in JAVA.glob("*.java"))


def test_native_app_has_no_webview_and_ships_every_section():
    src = _java_sources()
    assert "android.webkit" not in src and "new WebView" not in src and "loadUrl" not in src, "v2.0 must be fully native"
    assert not (JAVA / "MainActivity.java").exists()
    manifest = (ANDROID / "AndroidManifest.xml").read_text(encoding="utf-8")
    assert ".AppActivity" in manifest and "android.intent.category.LAUNCHER" in manifest
    # every section of the Windows app is routable on the phone
    for key in ["pos", "held", "invoices", "customers", "marketing", "products", "receive", "inventory", "stocktake",
                "stockops", "warehouses", "movements", "reports", "accounting", "users", "audit", "settings", "store",
                "sms", "hardware", "diagnostics", "support", "license", "sync", "cloud", "device", "about"]:
        assert f'case "{key}":' in src, f"section {key} missing from native router"
    # guided tour covers each section
    tour = (JAVA / "Tour.java").read_text(encoding="utf-8")
    for key in ["pos", "products", "stocktake", "accounting", "support", "settings"]:
        assert f'{{"{key}",' in tour
    # profit never rendered on the POS screen
    pos = (JAVA / "SalesScreens.java").read_text(encoding="utf-8")
    pos_cls = pos[pos.index("class Pos "):pos.index("class Held ")]
    assert "profit" not in pos_cls.lower() and "سود" not in pos_cls


def test_every_api_path_called_by_the_native_app_exists(client):
    src = _java_sources()
    schema_paths = client.get("/openapi.json").json()["paths"]
    called = set()
    for m in re.finditer(r'(?:get|getQuiet|post|patch|put|delete|call\("[A-Z]+",)\(\s*"(/[^"?]+)', src):
        called.add(m.group(1))
    for m in re.finditer(r'Api\.(?:get|post|patch|put|delete)\(\s*"(/[^"?]+)', src):
        called.add(m.group(1))
    assert len(called) > 60, called
    missing = []
    for raw in called:
        # string-concatenated ids: "/invoices/" + id → prefix match on the schema
        prefix = "/api" + raw.rstrip("/")
        ok = any(p == prefix or p.startswith(prefix + "/") or p.startswith(prefix + "{") or
                 re.match("^" + re.escape(prefix).replace(r"\{", "{") + r"(/|$|\{)", p) for p in schema_paths)
        if not ok:
            missing.append(raw)
    assert not missing, f"native app calls unknown endpoints: {sorted(missing)}"


def test_method_override_turns_post_into_patch(client, auth_headers):
    r = client.post("/api/customers", json={"name": "موبایل", "phone": "09125550001"}, headers=auth_headers)
    assert r.status_code in (200, 201), r.text
    cid = r.json()["id"]
    r = client.post(f"/api/customers/{cid}", json={"notes": "override"},
                    headers={**auth_headers, "X-HTTP-Method-Override": "PATCH"})
    assert r.status_code == 200, r.text
    assert r.json()["notes"] == "override"
    # plain POST to a PATCH-only route is still rejected
    assert client.post(f"/api/customers/{cid}", json={"notes": "x"}, headers=auth_headers).status_code == 405


def test_sync_pull_carries_the_fields_the_phone_db_needs(client, auth_headers):
    r = client.post("/api/mobile/sync", json={"device_id": "t", "cursor": None, "push": [], "pull": True, "limit": 50},
                    headers=auth_headers)
    assert r.status_code == 200, r.text
    pull = r.json()["pull"]
    assert set(pull) == {"products", "batches", "customers"}
    if pull["products"]:
        assert {"brand_id", "min_stock_alert", "has_own_barcode", "unit_id", "barcode"} <= set(pull["products"][0])
    if pull["batches"]:
        assert {"sell_price", "consumer_price", "buy_price", "current_qty", "expiry_date"} <= set(pull["batches"][0])
    if pull["customers"]:
        assert {"last_name", "credit_limit", "phone"} <= set(pull["customers"][0])


def test_sync_reconciles_a_sale_priced_with_a_stale_catalogue(client, auth_headers):
    # product + batch on the PC
    p = client.post("/api/products", json={"name": "نوشابه", "barcode": "6261000000019"}, headers=auth_headers).json()
    b = client.post("/api/batches/receive", json={"product_id": p["id"], "quantity_received": 10, "buy_price": 10000,
                                                   "consumer_price": 20000, "sell_price": 20000}, headers=auth_headers)
    assert b.status_code in (200, 201), b.text
    # the phone still had 18000 in its cache → tendered 18000
    ops = [{"id": "stale-1", "type": "POS_CHECKOUT", "created_at": "2026-01-01T00:00:00",
            "payload": {"items": [{"barcode": "6261000000019", "quantity": 1, "discount": 0}],
                        "payments": [{"method": "CASH", "amount": 18000}], "open_drawer": False}}]
    r = client.post("/api/mobile/sync", json={"device_id": "t", "cursor": None, "push": ops, "pull": False},
                    headers=auth_headers)
    assert r.status_code == 200, r.text
    a = r.json()["applied"][0]
    assert a["status"] == "APPLIED", a
    assert a["result"]["invoice_number"].startswith("INV-")
    assert a["result"]["adjusted"] == {"phone_total": 18000.0, "pc_total": 20000.0}
    # replay is idempotent
    r2 = client.post("/api/mobile/sync", json={"device_id": "t", "cursor": None, "push": ops, "pull": False},
                     headers=auth_headers)
    assert r2.json()["applied"][0]["status"] == "DUPLICATE"
    # stock went down exactly once
    stock = [s for s in client.get("/api/inventory/stock", headers=auth_headers).json() if s["product_id"] == p["id"]][0]
    assert stock["total_stock"] == 9
