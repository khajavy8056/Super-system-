"""v1.6 — exit-with-backup, offline licence horizon + encrypted vault, mobile pairing & sync."""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta

import pytest

from app.services import license as lic


def test_shutdown_makes_backup_but_does_not_exit_in_tests(client, auth_headers):
    r = client.post("/api/system/shutdown", headers=auth_headers, json={"backup": True})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True and body["exiting"] is False
    assert body["backup"] and body["backup"]["size"] > 0
    names = [b["name"] for b in client.get("/backups", headers=auth_headers).json()]
    assert any(body["backup"]["path"].endswith(n) for n in names)


def test_offline_horizon_is_expiry_date_and_vault_on_lock(client, monkeypatch, auth_headers):
    from app.database import SessionLocal
    good = {"status": "SUCCESS", "type": "FULL", "owner": "Demo", "expires": (date.today() + timedelta(days=30)).isoformat()}
    monkeypatch.setattr(lic, "fetch_remote", lambda url, key, hw: good)
    assert client.post("/api/setup/license/activate", json={"key": "KEY-LGT1-XLWT-DN7D"}).status_code == 200
    with SessionLocal() as db:
        # 20 days without internet but the key is valid for 30 → still allowed
        lic._set(db, "checked_at", (datetime.utcnow() - timedelta(days=20)).isoformat()); db.commit()
        st = lic.state(db)
        assert st["allowed"] is True and st["offline_until"] == good["expires"]
        # past the expiry date → blocked, and the vault archive is written
        lic._set(db, "expires", (date.today() - timedelta(days=1)).isoformat()); db.commit()
        st = lic.state(db)
        assert st["allowed"] is False
        out = lic.lock_vault(db, force=True); db.commit()
        assert out and out["size"] > 0 and out["path"].endswith(".zip")
        import pyzipper
        with pyzipper.AESZipFile(out["path"]) as z:
            z.setpassword(lic.vault_password().encode())
            assert set(z.namelist()) == {"supermarket.db", "vault.json"}
            assert z.read("supermarket.db")[:15] == b"SQLite format 3"
        # wrong password must fail (really encrypted)
        with pyzipper.AESZipFile(out["path"]) as z:
            z.setpassword(b"wrong")
            with pytest.raises(RuntimeError):
                z.read("vault.json")
        lic.clear(db); db.commit()


def test_mobile_pair_info_and_devices(client, auth_headers):
    r = client.get("/api/mobile/pair/info", headers=auth_headers)
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["qr_text"].startswith("SMKT:") and b["payload"]["token"] and b["payload"]["url"].startswith("http://")
    assert b["qr_png"] is None or b["qr_png"].startswith("data:image/png;base64,")
    devs = client.get("/api/mobile/devices", headers=auth_headers).json()
    assert any(d["id"] == b["payload"]["device_id"] for d in devs)
    # the minted token works as a bearer
    tok = {"Authorization": "Bearer " + b["payload"]["token"]}
    assert client.get("/api/auth/me", headers=tok).status_code == 200
    assert client.delete(f"/api/mobile/devices/{b['payload']['device_id']}", headers=auth_headers).status_code == 200
    assert all(d["id"] != b["payload"]["device_id"] for d in client.get("/api/mobile/devices", headers=auth_headers).json())


def test_mobile_sync_push_is_idempotent_and_pull_returns_changes(client, auth_headers, milk, two_batches):
    op_id = uuid.uuid4().hex
    op = {"id": op_id, "type": "POS_CHECKOUT", "payload": {
        "items": [{"product_id": milk["id"], "batch_id": two_batches["a"]["id"], "quantity": 1}],
        "payments": [{"method": "CASH", "amount": 60000}]}}
    r = client.post("/api/mobile/sync", headers=auth_headers, json={"device_id": "dev1", "push": [op], "cursor": None})
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["applied"][0]["status"] == "APPLIED" and b["applied"][0]["result"]["invoice_number"]
    assert any(p["id"] == milk["id"] for p in b["pull"]["products"])
    assert any(x["id"] == two_batches["a"]["id"] for x in b["pull"]["batches"])
    cursor = b["cursor"]
    # replay → duplicate, nothing sold twice
    r2 = client.post("/api/mobile/sync", headers=auth_headers, json={"push": [op], "cursor": cursor, "pull": False})
    assert r2.json()["applied"][0]["status"] == "DUPLICATE"
    qty = client.get(f"/api/batches/{two_batches['a']['id']}", headers=auth_headers)
    if qty.status_code == 200:
        assert float(qty.json()["current_qty"]) == float(two_batches["a"]["current_qty"]) - 1
    # unknown op type is rejected, not crashing
    r3 = client.post("/api/mobile/sync", headers=auth_headers, json={"push": [{"id": "x1", "type": "NOPE", "payload": {}}], "pull": False})
    assert r3.json()["applied"][0]["status"] == "REJECTED"
