"""v1.7 — internet sync through a Drive-compatible stub (device flow, ops mailbox, snapshot)."""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

import pytest


class _Drive(BaseHTTPRequestHandler):
    files: dict = {}     # id -> {name, content}
    polls = 0

    def log_message(self, *a):
        pass

    def _send(self, obj, code=200, raw=None):
        body = raw if raw is not None else json.dumps(obj).encode()
        self.send_response(code); self.send_header("content-type", "application/json"); self.send_header("content-length", str(len(body))); self.end_headers(); self.wfile.write(body)

    def do_GET(self):
        u = urlparse(self.path); q = parse_qs(u.query)
        if u.path == "/drive/files":
            cond = q.get("q", [""])[0]
            out = []
            for fid, f in _Drive.files.items():
                if "name contains 'ops-'" in cond and not f["name"].startswith("ops-"): continue
                if "name = '" in cond and f["name"] != cond.split("'")[1]: continue
                out.append({"id": fid, "name": f["name"], "modifiedTime": "2026-09-08T00:00:00Z"})
            return self._send({"files": out})
        if u.path.startswith("/drive/files/"):
            fid = u.path.rsplit("/", 1)[-1]
            return self._send(None, raw=_Drive.files[fid]["content"])
        if u.path == "/userinfo":
            return self._send({"email": "owner@example.com"})
        self._send({"error": "nf"}, 404)

    def do_POST(self):
        n = int(self.headers.get("content-length") or 0); raw = self.rfile.read(n)
        u = urlparse(self.path)
        if u.path == "/device/code":
            return self._send({"device_code": "DC1", "user_code": "ABCD-EFGH", "verification_url": "https://www.google.com/device", "expires_in": 1800, "interval": 1})
        if u.path == "/token":
            form = parse_qs(raw.decode())
            if form.get("grant_type", [""])[0].endswith("device_code"):
                _Drive.polls += 1
                if _Drive.polls < 2: return self._send({"error": "authorization_pending"}, 428)
                return self._send({"access_token": "AT1", "refresh_token": "RT1", "expires_in": 3600})
            return self._send({"access_token": "AT2", "expires_in": 3600})
        if u.path == "/upload/files":
            return self._send({"id": self._store(raw, None)})
        self._send({"error": "nf"}, 404)

    def do_PATCH(self):
        n = int(self.headers.get("content-length") or 0); raw = self.rfile.read(n)
        fid = urlparse(self.path).path.rsplit("/", 1)[-1]
        self._send({"id": self._store(raw, fid)})

    def do_DELETE(self):
        _Drive.files.pop(urlparse(self.path).path.rsplit("/", 1)[-1], None)
        self.send_response(204); self.end_headers()

    def _store(self, raw, fid):
        boundary = raw.split(b"\r\n", 1)[0]
        parts = raw.split(boundary)
        meta = json.loads(parts[1].split(b"\r\n\r\n", 1)[1].strip())
        content = parts[2].split(b"\r\n\r\n", 1)[1].rsplit(b"\r\n", 1)[0]
        fid = fid or f"f{len(_Drive.files) + 1}"
        name = meta.get("name") or _Drive.files[fid]["name"]
        _Drive.files[fid] = {"name": name, "content": content}
        return fid


@pytest.fixture
def drive(client, auth_headers):
    srv = HTTPServer(("127.0.0.1", 0), _Drive)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    _Drive.files.clear(); _Drive.polls = 0
    base = f"http://127.0.0.1:{srv.server_port}"
    for k, val in {"cloud.device_url": base + "/device/code", "cloud.token_url": base + "/token", "cloud.api_url": base + "/drive",
                   "cloud.upload_url": base + "/upload", "cloud.userinfo_url": base + "/userinfo"}.items():
        assert client.put("/api/settings", headers=auth_headers, json={"key": k, "value": val}).status_code in (200, 201)
    yield base
    srv.shutdown()


def test_device_flow_connects_account(client, auth_headers, drive):
    st = client.get("/api/cloud/status", headers=auth_headers).json()
    assert st["connected"] is False and st["provider_label"] == "Google Drive"
    r = client.post("/api/cloud/connect/start", headers=auth_headers, json={"client_id": "cid", "client_secret": "sec"})
    assert r.status_code == 200 and r.json()["user_code"] == "ABCD-EFGH" and "google.com/device" in r.json()["verification_url"]
    assert client.post("/api/cloud/connect/poll", headers=auth_headers).json()["status"] == "PENDING"
    r = client.post("/api/cloud/connect/poll", headers=auth_headers).json()
    assert r["status"] == "CONNECTED" and r["account"] == "owner@example.com"
    st = client.get("/api/cloud/status", headers=auth_headers).json()
    assert st["connected"] and st["enabled"] and st["account"] == "owner@example.com"
    # the pairing QR now carries the cloud mailbox for the phone
    info = client.get("/api/mobile/pair/info", headers=auth_headers).json()
    assert info["payload"]["cloud"]["refresh_token"] == "RT1" and info["payload"]["v"] == 2


def test_sync_applies_phone_ops_and_publishes_snapshot(client, auth_headers, drive, milk):
    client.post("/api/cloud/connect/start", headers=auth_headers, json={"client_id": "cid", "client_secret": "sec"})
    _Drive.polls = 5
    assert client.post("/api/cloud/connect/poll", headers=auth_headers).json()["status"] == "CONNECTED"
    # a phone dropped an ops file into the mailbox while away from the shop Wi-Fi
    ops = {"device_id": "phone-1", "push": [
        {"id": "op-cloud-1", "type": "CUSTOMER_CREATE", "payload": {"name": "مشتری ابری", "phone": "09120000001"}},
        {"id": "op-cloud-2", "type": "POS_CHECKOUT", "payload": {"items": [], "payments": []}},   # invalid → rejected, must not block
    ]}
    _Drive.files["f9"] = {"name": "ops-phone-1-1.json", "content": json.dumps(ops, ensure_ascii=False).encode()}
    r = client.post("/api/cloud/sync-now", headers=auth_headers)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["files"] == 1 and out["applied"] == 1 and out["snapshot"] is True
    assert "f9" not in _Drive.files                                   # consumed
    names = {f["name"] for f in _Drive.files.values()}
    assert "snapshot.json" in names
    snap = json.loads([f for f in _Drive.files.values() if f["name"] == "snapshot.json"][0]["content"])
    assert any(p["name"] == milk["name"] for p in snap["products"]) and any(c["phone"] == "09120000001" for c in snap["customers"])
    custs = client.get("/api/customers", headers=auth_headers).json()
    assert any(c["phone"] == "09120000001" for c in custs)
    # replay of the same ops file is idempotent
    _Drive.files["f10"] = {"name": "ops-phone-1-2.json", "content": json.dumps(ops, ensure_ascii=False).encode()}
    out2 = client.post("/api/cloud/sync-now", headers=auth_headers).json()
    assert out2["applied"] == 0
    assert sum(1 for c in client.get("/api/customers", headers=auth_headers).json() if c["phone"] == "09120000001") == 1


def test_sync_without_account_is_a_clean_error(client, auth_headers):
    client.post("/api/cloud/disconnect", headers=auth_headers)
    assert client.get("/api/cloud/status", headers=auth_headers).json()["connected"] is False
    r = client.post("/api/cloud/sync-now", headers=auth_headers)
    assert r.status_code == 400 and r.json()["detail"]["code"] == "NOT_CONNECTED"
