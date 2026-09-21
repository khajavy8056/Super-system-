"""v1.7 — support tickets relayed through the vendor inbox (stubbed relay)."""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from app.services import support as svc


class _Relay(BaseHTTPRequestHandler):
    calls: list = []
    updates: list = []
    seq: int = 0
    uploaded: int = 0

    def do_GET(self):
        raw = "log line from support".encode()
        self.send_response(200); self.send_header("content-length", str(len(raw))); self.end_headers(); self.wfile.write(raw)

    def log_message(self, *a):  # silence
        pass

    def do_POST(self):
        n = int(self.headers.get("content-length") or 0)
        rawin = self.rfile.read(n)
        method = self.path.rsplit("/", 1)[-1]
        try:
            body = json.loads(rawin or b"{}")
        except ValueError:
            body = {"_multipart": n}
        _Relay.calls.append((self.path, body))
        if method == "getUpdates":
            out = {"status": "OK", "data": {"updates": _Relay.updates, "next_offset_id": "x"}}
        elif method in ("sendMessage", "sendLocation", "sendFile"):
            _Relay.seq += 1
            out = {"status": "OK", "data": {"message_id": f"m{_Relay.seq}"}}
        elif method == "requestSendFile":
            out = {"status": "OK", "data": {"upload_url": f"http://127.0.0.1:{self.server.server_port}/upload"}}
        elif method == "upload":
            _Relay.uploaded = n
            out = {"status": "OK", "data": {"file_id": "F123"}}
        elif method == "getFile":
            out = {"status": "OK", "data": {"download_url": f"http://127.0.0.1:{self.server.server_port}/dl/report.txt"}}
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


def test_offline_support_ticket_op_is_replayed_by_mobile_sync(client, auth_headers):
    """v1.7: a request written on the phone while the PC was unreachable arrives
    through the LAN sync queue and is stored (and relayed) like a direct one."""
    op = {"id": "tk-op-1", "type": "SUPPORT_TICKET",
          "payload": {"type": "BUG", "priority": "HIGH", "subject": "چاپگر گوشی آفلاین", "description": "d",
                      "device": "Android", "latitude": 35.7, "longitude": 51.4, "accuracy_m": 8}}
    r = client.post("/api/mobile/sync", headers=auth_headers, json={"device_id": "devq", "push": [op], "pull": False})
    assert r.status_code == 200, r.text
    res = r.json()["applied"][0]
    assert res["status"] == "APPLIED", res
    assert res["result"]["number"]
    # idempotent: same op id is not applied twice
    r2 = client.post("/api/mobile/sync", headers=auth_headers, json={"device_id": "devq", "push": [op], "pull": False})
    assert r2.json()["applied"][0]["status"] in ("APPLIED", "DUPLICATE")
    lst = client.get("/api/support/tickets?limit=50", headers=auth_headers).json()
    mine = [t for t in lst if t["subject"] == "چاپگر گوشی آفلاین"]
    assert len(mine) == 1 and mine[0]["latitude"] == 35.7 and mine[0]["device"] == "Android"



def _mk_ticket(client, auth_headers, subject):
    r = client.post("/api/support/tickets", headers=auth_headers, json={"type": "QUESTION", "subject": subject, "description": "d", "device": "Windows"})
    assert r.status_code == 201, r.text
    return r.json()


def test_two_way_conversation_routes_replies_to_the_right_store(client, auth_headers, relay):
    """Operator answers in the support bot (Reply on our message, or text starting
    with TCK-xxxxxx@HWID8); other stores' traffic is ignored; the answer shows
    up in the app with an unread badge."""
    mine = svc.install_id()
    t = _mk_ticket(client, auth_headers, "سؤال دربارهٔ گزارش")
    assert t["status"] == "SENT"
    sent = [b for p, b in _Relay.calls if p.endswith("/sendMessage")][-1]
    assert f"{t['number']}@{mine}" in sent["text"] and "کد فروشگاه" in sent["text"]
    # relay id of our ticket message
    from app.database import SessionLocal
    from app.models import SupportTicket
    with SessionLocal() as db:
        ref = db.get(SupportTicket, t["id"]).relay_ref
    assert ref
    inbox = _Relay.calls[-1][1]["chat_id"] if "chat_id" in _Relay.calls[-1][1] else sent["chat_id"]
    _Relay.updates[:] = [
        # 1) proper Reply on our message
        {"type": "NewMessage", "chat_id": inbox, "new_message": {"message_id": "r1", "text": "سلام، گزارش را از منوی گزارش‌ها → فروش بگیرید", "reply_to_message_id": ref, "sender_type": "User"}},
        # 2) another store's thread (different hwid) — must be ignored
        {"type": "NewMessage", "chat_id": inbox, "new_message": {"message_id": "r2", "text": "TCK-000001@DEADBEEF: this is for another store", "sender_type": "User"}},
        # 3) explicit reference without Reply
        {"type": "NewMessage", "chat_id": inbox, "new_message": {"message_id": "r3", "text": f"{t['number']}@{mine} — همچنین فیلتر تاریخ را بررسی کنید", "sender_type": "User"}},
        # 4) unrelated chatter
        {"type": "NewMessage", "chat_id": inbox, "new_message": {"message_id": "r4", "text": "hello", "sender_type": "User"}},
    ]
    r = client.post("/api/support/poll", headers=auth_headers)
    assert r.status_code == 200 and r.json()["received"] == 2, r.text
    assert client.get("/api/support/unread", headers=auth_headers).json()["unread"] == 2
    lst = client.get("/api/support/tickets", headers=auth_headers).json()
    assert next(x for x in lst if x["id"] == t["id"])["unread"] == 2
    conv = client.get(f"/api/support/tickets/{t['id']}/messages", headers=auth_headers).json()
    texts = [m["text"] for m in conv["messages"] if m["direction"] == "IN"]
    assert texts == ["سلام، گزارش را از منوی گزارش‌ها → فروش بگیرید", "همچنین فیلتر تاریخ را بررسی کنید"]
    assert client.get("/api/support/unread", headers=auth_headers).json()["unread"] == 0  # opened → read
    # polling again does not duplicate (same message ids)
    client.post("/api/support/poll", headers=auth_headers)
    conv = client.get(f"/api/support/tickets/{t['id']}/messages", headers=auth_headers).json()
    assert len([m for m in conv["messages"] if m["direction"] == "IN"]) == 2


def test_store_reply_with_attachment_is_uploaded_and_threaded(client, auth_headers, relay, tmp_path):
    t = _mk_ticket(client, auth_headers, "چاپگر")
    _Relay.calls.clear()
    r = client.post(f"/api/support/tickets/{t['id']}/messages", headers=auth_headers,
                    data={"text": "این هم لاگ چاپگر"}, files={"file": ("printer.log", b"x" * 5000, "text/plain")})
    assert r.status_code == 201, r.text
    m = r.json()
    assert m["status"] == "SENT" and m["attachment_name"] == "printer.log" and m["attachment_size"] == 5000
    paths = [p.rsplit("/", 1)[-1] for p, _ in _Relay.calls]
    assert "requestSendFile" in paths and "upload" in paths and "sendFile" in paths
    sf = [b for p, b in _Relay.calls if p.endswith("/sendFile")][-1]
    assert sf["file_id"] == "F123" and sf.get("reply_to_message_id") and f"{t['number']}@{svc.install_id()}" in sf["text"]
    # text-only follow-up, and a support reply with a file is downloaded to media
    r = client.post(f"/api/support/tickets/{t['id']}/messages", headers=auth_headers, data={"text": "ممنون"})
    assert r.status_code == 201 and r.json()["status"] == "SENT"
    _Relay.updates[:] = [{"type": "NewMessage", "chat_id": sf["chat_id"], "new_message": {"message_id": "rf1", "text": "", "reply_to_message_id": sf["reply_to_message_id"],
                                                                                       "file": {"file_id": "FX", "file_name": "report.txt", "size": "21"}, "sender_type": "User"}}]
    assert client.post("/api/support/poll", headers=auth_headers).json()["received"] == 1
    conv = client.get(f"/api/support/tickets/{t['id']}/messages", headers=auth_headers).json()
    inc = [x for x in conv["messages"] if x["direction"] == "IN"][-1]
    assert inc["attachment_url"] and inc["attachment_url"].startswith("/media/support/") and inc["attachment_name"] == "report.txt"
    got = client.get(inc["attachment_url"])
    assert got.status_code == 200 and got.content == b"log line from support"
    # empty message rejected
    assert client.post(f"/api/support/tickets/{t['id']}/messages", headers=auth_headers, data={"text": "  "}).status_code == 422
