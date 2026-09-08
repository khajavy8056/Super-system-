"""v1.5 — licence activation (online, cached, 24h recheck, gate), setup wizard, bottom alerts."""
from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest

from app.services import license as lic


@pytest.fixture(autouse=True)
def _reset_license(client, monkeypatch):
    from app.database import SessionLocal
    with SessionLocal() as db:
        lic.clear(db); db.commit()
    yield
    with SessionLocal() as db:
        lic.clear(db); db.commit()


def _remote(answers):
    calls = []

    def fake(url, key, hw):
        calls.append((url, key, hw))
        a = answers.get(key, {"status": "INVALID", "message": "لایسنس یافت نشد"})
        if isinstance(a, Exception):
            raise a
        return a
    fake.calls = calls
    return fake


GOOD = {"KEY-LGT1-XLWT-DN7D": {"status": "SUCCESS", "type": "FULL", "owner": "Demo",
                               "expires": (date.today() + timedelta(days=10)).isoformat()}}


def test_hwid_is_stable_and_formatted():
    a, b = lic.hwid(), lic.hwid()
    assert a == b and len(a) == 19 and a.count("-") == 3


def test_activate_success_caches_state(client, monkeypatch):
    fake = _remote(GOOD); monkeypatch.setattr(lic, "fetch_remote", fake)
    r = client.post("/api/setup/license/activate", json={"key": "key-lgt1-xlwt-dn7d"})
    assert r.status_code == 200, r.text
    st = r.json()
    assert st["activated"] and st["allowed"] and st["type"] == "FULL" and st["owner"] == "Demo"
    assert st["days_left"] == 10 and st["key_masked"].startswith("KEY-") and st["hwid"] == lic.hwid()
    assert fake.calls[0][1] == "KEY-LGT1-XLWT-DN7D" and fake.calls[0][2] == lic.hwid()
    # GET state does not hit the network again
    n = len(fake.calls)
    assert client.get("/api/setup/license").json()["allowed"] is True
    assert len(fake.calls) == n


def test_activate_rejections_map_server_messages(client, monkeypatch):
    monkeypatch.setattr(lic, "fetch_remote", _remote({
        "KEY-MAXD-0000-0000": {"status": "MAX_DEVICES_REACHED", "message": "سقف تعداد دستگاه مجاز تکمیل شده است"}}))
    r = client.post("/api/setup/license/activate", json={"key": "KEY-MAXD-0000-0000"})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "MAX_DEVICES_REACHED"
    assert "سقف" in r.json()["detail"]["message"]
    r = client.post("/api/setup/license/activate", json={"key": "KEY-NOPE-0000-0000"})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "INVALID"
    assert client.get("/api/setup/license").json()["allowed"] is False


def test_network_failure_on_activation_is_503_and_not_cached(client, monkeypatch):
    monkeypatch.setattr(lic, "fetch_remote", _remote({"KEY-NET0-0000-0000": lic.LicenseError("NETWORK", "قطع")}))
    r = client.post("/api/setup/license/activate", json={"key": "KEY-NET0-0000-0000"})
    assert r.status_code == 503 and r.json()["detail"]["code"] == "NETWORK"
    assert client.get("/api/setup/license").json()["activated"] is False


def test_recheck_every_24h_revokes_on_rejection_but_tolerates_network(client, monkeypatch):
    from app.database import SessionLocal
    fake = _remote(GOOD); monkeypatch.setattr(lic, "fetch_remote", fake)
    assert client.post("/api/setup/license/activate", json={"key": "KEY-LGT1-XLWT-DN7D"}).status_code == 200
    with SessionLocal() as db:
        assert lic.is_recheck_due(db) is False
        lic.recheck(db); assert len(fake.calls) == 1            # not due → no call
        lic._set(db, "checked_at", (datetime.utcnow() - timedelta(hours=25)).isoformat()); db.commit()
        assert lic.is_recheck_due(db) is True
        # network down → keep ACTIVE
        monkeypatch.setattr(lic, "fetch_remote", _remote({"KEY-LGT1-XLWT-DN7D": lic.LicenseError("NETWORK", "قطع")}))
        st = lic.recheck(db); db.commit()
        assert st["allowed"] is True and st["last_error"] and "NETWORK" in st["last_error"]
        # server says INVALID → revoke
        monkeypatch.setattr(lic, "fetch_remote", _remote({}))
        st = lic.recheck(db, force=True); db.commit()
        assert st["status"] == "REVOKED" and st["allowed"] is False


def test_offline_grace_expires_after_7_days(client, monkeypatch):
    from app.database import SessionLocal
    monkeypatch.setattr(lic, "fetch_remote", _remote(GOOD))
    assert client.post("/api/setup/license/activate", json={"key": "KEY-LGT1-XLWT-DN7D"}).status_code == 200
    with SessionLocal() as db:
        lic._set(db, "checked_at", (datetime.utcnow() - timedelta(days=8)).isoformat()); db.commit()
        st = lic.state(db)
        assert st["allowed"] is False and "۷ روز" in st["reason"]


def test_gate_blocks_api_without_license(client, auth_headers, monkeypatch):
    import app.main as m
    monkeypatch.setattr(m, "_LICENSE_GATE_ENABLED", True)
    r = client.get("/api/products", headers=auth_headers)
    assert r.status_code == 402 and r.json()["detail"]["code"] == "LICENSE_REQUIRED"
    assert client.get("/health").status_code == 200
    assert client.get("/api/setup/status").status_code == 200
    monkeypatch.setattr(lic, "fetch_remote", _remote(GOOD))
    assert client.post("/api/setup/license/activate", json={"key": "KEY-LGT1-XLWT-DN7D"}).status_code == 200
    assert client.get("/api/products", headers=auth_headers).status_code == 200


def test_setup_wizard_complete_then_locked(client, monkeypatch, auth_headers):
    from app.database import SessionLocal
    from app.models import SystemSetting
    from sqlalchemy import select
    with SessionLocal() as db:
        for k in ("setup.done", "setup.done_at", "setup.starter_imported"):
            row = db.execute(select(SystemSetting).where(SystemSetting.key == k)).scalar_one_or_none()
            if row: row.value = ""
        db.commit()
    st = client.get("/api/setup/status").json()
    assert st["setup_done"] is False and st["loading_seconds"] == 120 and st["install_loading_seconds"] == 45 * 60
    # licence required before completing
    r = client.post("/api/setup/complete", json={"store_name": "فروشگاه آزمون"})
    assert r.status_code == 402
    monkeypatch.setattr(lic, "fetch_remote", _remote(GOOD))
    client.post("/api/setup/license/activate", json={"key": "KEY-LGT1-XLWT-DN7D"})
    r = client.post("/api/setup/complete", json={
        "store_name": "فروشگاه آزمون", "currency": "IRT", "theme": "dark", "printer_width_mm": 80,
        "admin_username": "admin", "admin_password": "admin123", "admin_full_name": "مدیر"})
    assert r.status_code == 200, r.text
    st2 = client.get("/api/setup/status").json()
    assert st2["setup_done"] is True and st2["first_loading_done"] is True  # v1.5.1: install screen only once, inside the wizard
    assert st2["loading_seconds"] == 120
    assert client.get("/api/settings/store-profile", headers=auth_headers).json()["name"] == "فروشگاه آزمون"
    # second completion refused
    assert client.post("/api/setup/complete", json={"store_name": "x"}).status_code == 409
    # bad admin creds validated
    with SessionLocal() as db:
        row = db.execute(select(SystemSetting).where(SystemSetting.key == "setup.done")).scalar_one(); row.value = ""; db.commit()
    r = client.post("/api/setup/complete", json={"admin_username": "a", "admin_password": "123"})
    assert r.status_code == 422
    client.post("/api/setup/complete", json={"admin_username": "admin", "admin_password": "admin123"})
    assert client.post("/api/setup/loading-done", headers=auth_headers).status_code == 200
    assert client.get("/api/setup/status").json()["loading_seconds"] == 120


def test_alerts_expiry_hours_days_and_license(client, auth_headers, monkeypatch, milk):
    monkeypatch.setattr(lic, "fetch_remote", _remote(GOOD))
    client.post("/api/setup/license/activate", json={"key": "KEY-LGT1-XLWT-DN7D"})
    today = date.today()
    for d in (0, 2):
        r = client.post("/api/batches/receive", headers=auth_headers, json={
            "product_id": milk["id"], "quantity_received": 3, "buy_price": 1000, "sell_price": 1500,
            "expiry_date": (today + timedelta(days=d)).isoformat()})
        assert r.status_code in (200, 201), r.text
    a = client.get("/api/setup/alerts", headers=auth_headers).json()
    kinds = [i["kind"] for i in a["items"]]
    assert kinds[0] == "LICENSE" and a["items"][0]["days_left"] == 10   # ≤14 days → shown first
    exp = [i for i in a["items"] if i["kind"] == "EXPIRY"]
    assert exp and exp[0]["days_left"] == 0 and "ساعت" in exp[0]["body"] and exp[0]["severity"] == "CRITICAL"
    assert any(i["days_left"] == 2 and "روز" in i["body"] for i in exp)
