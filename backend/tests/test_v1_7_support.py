"""v1.7 — support tickets relayed through the vendor inbox (stubbed relay)."""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from app.services import support as svc


class _Relay(BaseHTTPRequestHandler):
    calls: list = []
    updates: list = []

    def log_message(self, *a):  # silence
        pass

    def do_POST(self):
        n = int(self.headers.get("content-length") or 0)
        body = json.loads(self.rfile.read(n) or b"{}")
        method = self.path.rsplit("/", 1)[-1]
        _Relay.calls.append((self.path, body))
        if method == "getUpdates":
            out = {"status": "OK", "data": {"updates": _Relay.updates, "next_offset_id": "x"}}
        elif method in ("sendMessage", "sendLocation"):
            out = {"status": "OK", "data": {"message_id": "m1"}}
        else:
            out = {"status": "INVALID_INPUT"}
        raw = json.dumps(out).encode()
        self.send_response(200); self.send_header("content-type", "application/json"); self.send_header("content-length", str(len(raw))); self.end_headers(); self.wfile.write(raw)


@pytest.fixture
def relay(monkeypatch):
    srv = HTTPServer(("127.0.0.1", 0), _Relay)
    t = threading.Thread(target=srv.serve_forever, daemon=True); t.start()
    _Relay.calls.clear()
    _Relay.updates[:] = [{"type": "NewMessage", "chat_id": "b0other", "new_message": {"sender_username": "someone", "text": "hi"}},
                         {"type": "NewMessage", "chat_id": "b0owner", "new_message": {"sender_username": "khajavi8056", "text": "/start"}}]
    monkeypatch.setattr(svc.settings, "SUPPORT_RELAY_URL", f"http://127.0.0.1:{srv.server_port}/v3")
    monkeypatch.setattr(svc.settings, "SUPPORT_RELAY_TOKEN", "TESTTOKEN")
    monkeypatch.setattr(svc.settings, "SUPPORT_INBOX_ID", "")
    yield srv
    srv.shutdown()


def test_types_listed_in_persian(client, auth_headers):
    r = client.get("/api/support/types", headers=auth_headers)
    ids = {t["id"] for t in r.json()["types"]}
    assert {"BUG", "FEATURE", "QUESTION", "HARDWARE"} <= ids
    assert all(t["label"] and not t["label"].isascii() for t in r.json()["types"])


def test_ticket_is_relayed_with_store_info_and_location(client, auth_headers, relay):
    client.put("/api/settings/store-profile", headers=auth_headers,
               json={"name": "سوپرمارکت آزمایشی", "phone": "02112345678", "city": "تهران", "address": "خیابان آزادی ۱۲"})
    r = client.post("/api/support/tickets", headers=auth_headers, json={
        "type": "BUG", "priority": "HIGH", "subject": "چاپگر فاکتور چاپ نمی‌کند", "description": "بعد از فروش، رسید سفید بیرون می‌آید",
        "device": "Windows", "latitude": 35.6997, "longitude": 51.3380, "accuracy_m": 12})
    assert r.status_code == 201, r.text
    t = r.json()
    assert t["number"].startswith("TCK-") and t["status"] == "SENT" and t["status_label"] == "ارسال‌شده به پشتیبانی"
    paths = [p for p, _ in _Relay.calls]
    assert any(p.endswith("/TESTTOKEN/getUpdates") for p in paths)
    send = [b for p, b in _Relay.calls if p.endswith("/sendMessage")][0]
    assert send["chat_id"] == "b0owner"                     # owner's chat chosen, not the other one
    for needle in ("TCK-", "ثبت خرابی", "چاپگر فاکتور", "سوپرمارکت آزمایشی", "02112345678", "تهران", "35.699700, 51.338000", "maps.google.com", "Windows"):
        assert needle in send["text"], needle
    loc = [b for p, b in _Relay.calls if p.endswith("/sendLocation")][0]
    assert loc == {"chat_id": "b0owner", "latitude": "35.699700", "longitude": "51.338000"}
    # no transport name leaks into API output
    assert "rubika" not in json.dumps(t).lower()
    lst = client.get("/api/support/tickets", headers=auth_headers).json()
    assert lst[0]["number"] == t["number"]


def test_ticket_offline_is_queued_then_resent(client, auth_headers, monkeypatch):
    monkeypatch.setattr(svc.settings, "SUPPORT_RELAY_URL", "http://127.0.0.1:9/v3")   # unreachable
    monkeypatch.setattr(svc.settings, "SUPPORT_RELAY_TOKEN", "T")
    monkeypatch.setattr(svc.settings, "SUPPORT_INBOX_ID", "b0owner")
    r = client.post("/api/support/tickets", headers=auth_headers, json={"type": "FEATURE", "subject": "گزارش سود به تفکیک برند"})
    assert r.status_code == 201
    assert r.json()["status"] == "FAILED"          # stored locally, waiting
    assert r.json()["last_error"] and "http" not in r.json()["last_error"].lower()
    jobs = client.get("/api/diagnostics/sync/jobs", headers=auth_headers).json()
    assert any(j["job_type"] == "SUPPORT_TICKET" for j in (jobs if isinstance(jobs, list) else jobs.get("items", [])))


def test_bad_type_rejected(client, auth_headers):
    r = client.post("/api/support/tickets", headers=auth_headers, json={"type": "NOPE", "subject": "xxx"})
    assert r.status_code == 422
