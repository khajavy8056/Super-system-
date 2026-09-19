"""v3.5 — PRO intelligence pack (59 analyzers), AI advisor plumbing, groups, new actions."""
import json
import pathlib

DEMO = pathlib.Path(__file__).resolve().parents[1] / "demo" / "demo_store.db.gz"


def _restore(client, auth_headers):
    r = client.post("/api/system/restore", headers=auth_headers, files={"file": ("demo_store.db.gz", DEMO.read_bytes(), "application/gzip")})
    assert r.status_code == 200, r.text


def test_registry_has_60_kinds_and_groups_cover_all():
    from app.services import insights
    assert len(insights.ANALYZERS) >= 59
    assert set(insights.ANALYZERS) <= set(insights.KIND_LABELS)
    grouped = {k for _, ks in insights.GROUPS.values() for k in ks}
    assert set(insights.ANALYZERS) <= grouped


def test_all_actions_referenced_exist():
    import re
    from app.services import insight_actions, insights_pro
    src = pathlib.Path(insights_pro.__file__).read_text(encoding="utf-8")
    used = set(re.findall(r'"type": "([a-z_]+)"', src))
    assert used <= set(insight_actions.ACTIONS), used - set(insight_actions.ACTIONS)


def test_run_produces_pro_kinds_without_errors(client, auth_headers):
    _restore(client, auth_headers)
    r = client.post("/api/insights/run", headers=auth_headers).json()
    assert not r["errors"], r["errors"]
    rows = client.get("/api/insights?status=NEW&limit=300", headers=auth_headers).json()
    kinds = {x["kind"] for x in rows}
    pro = {"CUST_FAVORITE", "CUST_ITEM_DUE", "REORDER_POINT", "PEAK_HOURS", "SURPRISE", "UNREGISTERED_SALES"}
    assert pro <= kinds, pro - kinds
    assert all("group" in x for x in rows)
    g = client.get("/api/insights/groups", headers=auth_headers).json()
    assert g["analyzers"] >= 59 and sum(x["open"] for x in g["groups"]) == len(rows)
    sub = client.get("/api/insights?status=NEW&group=customer&limit=300", headers=auth_headers).json()
    assert sub and all(x["group"] == "customer" for x in sub)


def test_personal_sms_action_and_accept(client, auth_headers):
    _restore(client, auth_headers)
    client.post("/api/insights/run", headers=auth_headers)
    rows = client.get("/api/insights?status=NEW&kind=CUST_ITEM_DUE", headers=auth_headers).json()
    assert rows
    ins = rows[0]
    act = ins["actions"][0]
    assert act["type"] == "personal_sms" and act["params"]["customers"] and all(c["text"] for c in act["params"]["customers"])
    # every customer gets a *different* text (their own product)
    assert len({c["text"] for c in act["params"]["customers"]}) > 1
    r = client.post(f"/api/insights/{ins['id']}/accept", headers=auth_headers)
    assert r.status_code == 200, r.text
    d = client.get(f"/api/insights/{ins['id']}", headers=auth_headers).json()
    assert d["status"] == "ACCEPTED" and d["baseline"]


def test_ai_presets_and_report(client, auth_headers):
    _restore(client, auth_headers)
    p = client.get("/api/insights/ai/presets", headers=auth_headers).json()
    ids = {x["id"] for x in p["presets"]}
    assert {"openrouter", "groq", "gemini", "ollama"} <= ids and any(x["free"] for x in p["presets"])
    r = client.post("/api/insights/ai/preset", headers=auth_headers, json={"preset": "groq", "api_key": "gsk_test"}).json()
    assert r["online"] and r["preset"] == "groq" and "groq.com" in r["base_url"] and r["has_key"]
    rep = client.get("/api/insights/ai/report", headers=auth_headers).json()
    assert rep["store"]["invoices_90d"] > 0 and rep["open_suggestions"] is not None
    # nothing personal leaves: no phone numbers anywhere in the report
    assert "phone" not in json.dumps(rep)
    # advisor without network → friendly 502, no crash
    r = client.post("/api/insights/ai/advise", headers=auth_headers)
    assert r.status_code == 502 and r.json()["detail"]


def test_ai_advisor_parses_and_applies(client, auth_headers, monkeypatch):
    _restore(client, auth_headers)
    from app.services import ai_narrator
    fake = {"summary": "فروش ماه اخیر رشد داشته.", "suggestions": [
        {"title": "پیشنهاد پای صندوق را روشن کنید", "why": "میانگین فاکتور پایین است", "steps": ["تنظیمات", "فعال"], "priority": 1, "expected_gain_toman_month": 500000, "action": {"type": "enable_nudges", "params": {}}},
        {"title": "کمپین آستانه", "why": "…", "steps": [], "priority": 2, "expected_gain_toman_month": 0, "action": {"type": "threshold_campaign", "params": {"percent": 50, "min_purchase": 300000, "days": 10}}},
        {"title": "تنظیم ناامن", "why": "…", "steps": [], "priority": 3, "action": {"type": "set_setting", "params": {"key": "auth.admin_password", "value": "x"}}},
    ]}
    monkeypatch.setattr(ai_narrator, "_chat", lambda db, messages, max_tokens=400: "```json\n" + json.dumps(fake, ensure_ascii=False) + "\n```")
    client.post("/api/insights/ai/preset", headers=auth_headers, json={"preset": "openrouter", "api_key": "k"})
    r = client.post("/api/insights/ai/advise", headers=auth_headers)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["created"] == 3
    rows = [client.get(f"/api/insights/{i}", headers=auth_headers).json() for i in d["ids"]]
    assert all(x["kind"] == "AI_ADVISOR" for x in rows)
    assert rows[0]["actions"][0]["type"] == "enable_nudges"
    assert rows[1]["actions"][0]["params"]["percent"] == 10           # clamped
    assert rows[2]["actions"][0]["type"] == "note"                    # unsafe setting downgraded
    a = client.post(f"/api/insights/{rows[0]['id']}/accept", headers=auth_headers)
    assert a.status_code == 200
    s = client.get("/api/settings", headers=auth_headers).json()
    vals = {x["key"]: x["value"] for x in (s if isinstance(s, list) else s.get("items", []))}
    assert vals.get("insights.pos_nudges") == "true"
