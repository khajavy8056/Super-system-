"""v3.2 — measured effect in percent + daily series, availability metric, customer purchase-pattern prediction."""
import pathlib

DEMO = pathlib.Path(__file__).resolve().parents[1] / "demo" / "demo_store.db.gz"


def _restore(client, auth_headers):
    r = client.post("/api/system/restore", headers=auth_headers, files={"file": ("demo_store.db.gz", DEMO.read_bytes(), "application/gzip")})
    assert r.status_code == 200, r.text


def test_measured_effects_are_nonzero_with_percent(client, auth_headers):
    _restore(client, auth_headers)
    rows = client.get("/api/insights?status=ACCEPTED,MEASURED&limit=200", headers=auth_headers).json()
    assert rows, "demo must contain executed suggestions"
    measured = [r for r in rows if r["measured_gain"] is not None]
    assert measured
    kinds = {r["kind"] for r in measured}
    # every executed kind in the demo shows a non-zero effect somewhere and a percent figure
    for k in kinds:
        ks = [r for r in measured if r["kind"] == k]
        assert any(abs(float(r["measured_gain"])) > 0 for r in ks), f"{k}: all zero"
        # percent exists whenever the baseline was not zero (CHURN customers had zero sales before — by definition)
        assert any(r["result"].get("profit_pct") is not None or r["result"].get("base_profit_per_day") == 0 for r in ks), f"{k}: no percent"
    # daily before/after series exists for chart-able metrics
    assert any(len((r["result"].get("daily") or {}).get("after", [])) >= 1 for r in measured)
    # VELOCITY uses the availability metric and is non-zero
    vel = [r for r in measured if r["kind"] == "VELOCITY"]
    assert vel and any(abs(float(r["measured_gain"])) > 0 for r in vel)
    assert all(r["metric"]["metric"] in ("availability", "stockout_days") for r in vel)


def test_customer_patterns_endpoint_and_insight(client, auth_headers):
    _restore(client, auth_headers)
    d = client.get("/api/insights/customers/patterns?days=7", headers=auth_headers).json()
    assert d["rows"], "one-year demo must have regular customers due this week"
    r0 = d["rows"][0]
    for k in ("name", "typical_gap", "regularity", "predicted", "due_in", "usual_weekday", "usual_hour", "usual_items", "monthly_profit"):
        assert k in r0
    assert 0 <= r0["regularity"] <= 1 and -1 <= r0["due_in"] <= 7
    client.post("/api/insights/run", headers=auth_headers)
    rows = client.get("/api/insights?status=NEW,ACCEPTED,MEASURED&kind=VISIT_PATTERN&limit=5", headers=auth_headers).json()
    assert rows and rows[0]["actions"][0]["type"] == "visit_sms"


def test_detail_has_readable_evidence(client, auth_headers):
    _restore(client, auth_headers)
    rows = client.get("/api/insights?status=NEW&limit=50", headers=auth_headers).json()
    assert rows
    d = client.get(f"/api/insights/{rows[0]['id']}?narrate=true", headers=auth_headers).json()
    assert d["body"] and d["narrative"] and isinstance(d["evidence"], dict)
