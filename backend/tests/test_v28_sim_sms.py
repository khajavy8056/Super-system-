"""v2.8 — invoice SMS through the paired phone's SIM card (provider «phone»)."""
from __future__ import annotations

from app.database import SessionLocal
from app.models import SmsMessage
from app.services import sms as sms_svc


def _set(client, h, key, value):
    r = client.put("/api/settings", json={"key": key, "value": value, "is_secret": False}, headers=h)
    assert r.status_code in (200, 201), r.text


def test_phone_provider_hands_off_to_phone_and_reports_back(client, auth_headers):
    _set(client, auth_headers, "sms.provider", "phone")
    r = client.post("/api/sms/send", json={"phone": "09121234567", "text": "فاکتور ۱۲۳"}, headers=auth_headers)
    assert r.status_code == 201, r.text
    sid = r.json()["id"]
    # PC dispatcher does nothing (no retries burnt)
    d = client.post("/api/sms/dispatch", headers=auth_headers).json()
    assert d["reason"] == "PHONE_SIM_HANDOFF" and d["skipped"] >= 1
    # phone drains the outbox
    ob = client.get("/api/sms/outbox?device_id=phone-A", headers=auth_headers).json()
    assert any(m["id"] == sid and m["phone"] == "09121234567" for m in ob["messages"])
    # a failed attempt → RETRYING, then success → SENT
    r = client.post("/api/sms/outbox/report", json={"id": sid, "status": "RETRYING", "error": "no signal"}, headers=auth_headers)
    assert r.json()["status"] == "RETRYING"
    r = client.post("/api/sms/outbox/report", json={"id": sid, "status": "SENT", "response": "sim:1:1"}, headers=auth_headers)
    assert r.json()["status"] == "SENT"
    s = SessionLocal()
    try:
        m = s.get(SmsMessage, sid)
        assert m.status == "SENT" and m.provider_response == "sim:1:1" and m.sent_at is not None
    finally:
        s.close()
    # test-connection reports the phone as connected; guide shows the device
    t = client.post("/api/sms/test-connection", headers=auth_headers).json()
    assert t["provider"] == "phone" and t["status"] == "OK"
    g = client.get("/api/sms/guide", headers=auth_headers).json()
    assert g["state"]["phone_device"] == "phone-A" and any(st["n"] == 0 for st in g["steps"])


def test_outbox_empty_for_other_providers(client, auth_headers):
    _set(client, auth_headers, "sms.provider", "file")
    ob = client.get("/api/sms/outbox?device_id=phone-B", headers=auth_headers).json()
    assert ob["messages"] == [] and ob["provider"] == "file"
