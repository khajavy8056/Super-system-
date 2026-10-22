"""v3.1 — restore of the bundled demo (gzip), forecast/calibration, phone-only customers at checkout."""
import pathlib

DEMO = pathlib.Path(__file__).resolve().parents[1] / "demo" / "demo_store.db.gz"


def test_restore_demo_gz_then_plan(client, auth_headers):
    r = client.post("/api/system/restore", headers=auth_headers, files={"file": ("demo_store.db.gz", DEMO.read_bytes(), "application/gzip")})
    assert r.status_code == 200, r.text
    # calibration is learned from the demo's measured actions
    r = client.post("/api/insights/plan/learn", headers=auth_headers)
    assert r.status_code == 200
    cal = r.json()["calibration"]
    assert cal, "measured insights in the demo must produce a calibration table"
    # v3.8 honesty contract (user-ordered change): ratios are recorded RAW — the old
    # [0.15, 2.5] clamp silently rewrote real losses as +15 % wins. The demo data
    # happens to sit inside the old band, but nothing guarantees that anymore; what
    # IS guaranteed is finite ratios plus full outcome statistics (see
    # test_v38_calibration_honest.py for the negative-outcome proof).
    import math
    for k, v in cal.items():
        assert v["n"] >= 1 and math.isfinite(v["ratio"])
        assert v["n_positive"] + v["n_zero"] + v["n_negative"] == v["n"]
        assert v["mae"] is not None and v["mean_error"] is not None
        assert v["direction_accuracy"] is not None and len(v["ratio_ci95"]) == 2
    # re-run analyzers → expected gains are calibrated and carry a forecast band
    r = client.post("/api/insights/run", headers=auth_headers)
    assert r.status_code == 200
    plan = client.get("/api/insights/plan?horizon=90", headers=auth_headers).json()
    assert plan["model"]["weeks_of_history"] >= 20
    assert plan["baseline"]["profit_month"] > 0
    assert len(plan["forecast"]) >= 12 and plan["forecast"][-1]["cum_plan"] >= plan["forecast"][-1]["cum_baseline"]
    assert plan["forecast"][-1]["cum_low"] <= plan["forecast"][-1]["cum_plan"] <= plan["forecast"][-1]["cum_high"]
    assert plan["model"]["measured_count"] >= 5 and plan["model"]["direction_accuracy"] is not None
    for it in plan["items"]:
        assert it["low_month"] <= it["gain_month"] <= it["high_month"]
        assert it["confidence"] in ("low", "medium", "high", "n/a")
    # detail card of an open suggestion has a what-if prediction
    lst = client.get("/api/insights?status=NEW&limit=5", headers=auth_headers).json()
    if lst:
        d = client.get(f"/api/insights/{lst[0]['id']}", headers=auth_headers).json()
        assert "prediction" in d and d["evidence"].get("forecast") is not None


def test_phone_backup_rejected_with_clear_message(client, auth_headers, tmp_path):
    import sqlite3
    p = tmp_path / "phone.db"
    c = sqlite3.connect(p)
    for t in ("products", "invoices", "batches", "kv", "ops"):
        c.execute(f"CREATE TABLE {t}(id INTEGER)")
    c.commit(); c.close()
    r = client.post("/api/system/restore", headers=auth_headers, files={"file": ("phone.db", p.read_bytes(), "application/octet-stream")})
    assert r.status_code == 400 and "موبایل" in r.text


def test_checkout_phone_only_creates_customer_and_is_recognised(client, auth_headers, milk, two_batches):
    # milk fixture: product with stock (see conftest)
    def body():
        q = client.post("/api/pos/cart/validate", headers=auth_headers, json={"items": [{"product_id": milk["id"], "quantity": 1}]}).json()
        total = float(q["totals"]["subtotal"])
        return {"items": [{"product_id": milk["id"], "quantity": 1}], "payments": [{"method": "CASH", "amount": total}],
                "customer_phone": "۰۹۱۲ ۱۱۱-۲۲۳۳"}
    r = client.post("/api/pos/checkout", headers=auth_headers, json=body())
    assert r.status_code in (200, 201), r.text
    c = client.get("/api/customers/phone/09121112233", headers=auth_headers)
    assert c.status_code == 200
    cust = c.json()
    assert cust["phone"] == "09121112233" and cust["last_name"] is None and cust["name"]
    # second purchase with the same number → same customer, no duplicate
    r2 = client.post("/api/pos/checkout", headers=auth_headers, json=body())
    assert r2.status_code in (200, 201)
    assert r2.json().get("customer_id") == cust["id"]
    lst = client.get("/api/customers?q=09121112233", headers=auth_headers).json()
    assert len([x for x in lst if x["phone"] == "09121112233"]) == 1
    # phone-only customer creation through the customers API (name optional)
    r3 = client.post("/api/customers", headers=auth_headers, json={"phone": "09355550000"})
    assert r3.status_code in (200, 201) and r3.json()["name"]
