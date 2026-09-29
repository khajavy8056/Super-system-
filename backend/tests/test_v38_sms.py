# -*- coding: utf-8 -*-
"""v3.8 — SMS retry honesty proof (user order §7).

* failures sleep on exponential backoff + jitter (no provider hammering),
* a message is CLAIMED before sending — concurrent dispatchers cannot
  double-send the same row,
* a SENDING row whose worker died (10+ min stale) re-enters the queue,
* manual retry wipes the backoff debt.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from app.database import SessionLocal
from app.models import SmsMessage
from app.services import sms as sms_svc


def _set(client, h, key, value):
    r = client.put("/api/settings", json={"key": key, "value": value}, headers=h)
    assert r.status_code in (200, 201), r.text


def _drain_until(client, h, mid, want, rounds=15):
    """Dispatch repeatedly until OUR row reaches `want` (bounded).

    The test DB is session-scoped and one dispatch pass handles 20 rows, so
    rows left by earlier tests may stand ahead of ours in the queue.
    """
    last = None
    for _ in range(rounds):
        client.post("/api/sms/dispatch", headers=h)
        s = SessionLocal()
        try:
            last = s.get(SmsMessage, mid).status
        finally:
            s.close()
        if last == want:
            return
    raise AssertionError(f"message {mid} never reached {want} (stuck at {last})")


def test_backoff_schedule_bounds():
    for _ in range(50):
        assert 60 <= sms_svc.retry_delay_seconds(1, base=60, cap=3600) <= 120
        assert 120 <= sms_svc.retry_delay_seconds(2, base=60, cap=3600) <= 180
        assert 3600 <= sms_svc.retry_delay_seconds(10, base=60, cap=3600) <= 3660


def test_claim_prevents_double_send_and_stuck_recovers(client, auth_headers, tmp_path):
    log = tmp_path / "v38sms.log"
    _set(client, auth_headers, "sms.file_path", str(log))
    _set(client, auth_headers, "sms.provider", "file")
    mid = client.post("/api/sms/send", headers=auth_headers,
                      json={"phone": "09120000381", "text": "race me"}).json()["id"]
    s = SessionLocal()
    try:  # another live worker owns the row → we must not touch it
        s.get(SmsMessage, mid).status = "SENDING"
        s.commit()
    finally:
        s.close()
    # NOTE: the test DB is session-scoped — other tests' rows may also
    # dispatch here, so every assertion is scoped to OUR message only.
    for _ in range(3):
        client.post("/api/sms/dispatch", headers=auth_headers)
    s = SessionLocal()
    try:
        assert s.get(SmsMessage, mid).status == "SENDING"
        # …but a claim older than 10 minutes belongs to a dead worker
        m = s.get(SmsMessage, mid)
        m.updated_at = datetime.utcnow() - timedelta(minutes=11)
        s.commit()
    finally:
        s.close()
    _drain_until(client, auth_headers, mid, "SENT")
    assert log.read_text(encoding="utf-8").count("09120000381") == 1
    _set(client, auth_headers, "sms.provider", "")


def test_manual_retry_wipes_backoff_debt(client, auth_headers, tmp_path):
    log = tmp_path / "v38sms2.log"
    _set(client, auth_headers, "sms.file_path", str(log))
    _set(client, auth_headers, "sms.provider", "fail")
    _set(client, auth_headers, "sms.max_retries", "1")
    mid = client.post("/api/sms/send", headers=auth_headers,
                      json={"phone": "09120000382", "text": "fail once"}).json()["id"]
    client.post("/api/sms/dispatch", headers=auth_headers)
    r = client.post(f"/api/sms/{mid}/retry", headers=auth_headers)
    assert r.status_code == 200 and r.json()["status"] == "PENDING"
    s = SessionLocal()
    try:
        m = s.get(SmsMessage, mid)
        assert m.retry_count == 0 and m.next_retry_at is None
    finally:
        s.close()
    _set(client, auth_headers, "sms.provider", "file")
    _set(client, auth_headers, "sms.max_retries", "5")
    d = client.post("/api/sms/dispatch", headers=auth_headers).json()
    assert d["sent"] >= 1
    _set(client, auth_headers, "sms.provider", "")
