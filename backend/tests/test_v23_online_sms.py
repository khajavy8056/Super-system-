"""v2.3 — invoice SMS independent of printing, in-app SMS guide, online relay, stable port, fullscreen, bg install, biometrics."""
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
JAVA = ROOT / "mobile-android" / "app" / "src" / "main" / "java" / "ir" / "khajavy" / "supermarket"
MANIFEST = ROOT / "mobile-android" / "app" / "src" / "main" / "AndroidManifest.xml"


def test_sms_guide_endpoint_reports_missing_steps(client, auth_headers):
    for k in ("sms.provider", "sms.username", "sms.password", "sms.api_key", "sms.melipayamak_body_id"):
        client.put("/api/settings", json={"key": k, "value": ""}, headers=auth_headers)
    r = client.get("/api/sms/guide", headers=auth_headers)
    assert r.status_code == 200
    g = r.json()
    assert len(g["steps"]) >= 7 and any("ملی" in s["title"] for s in g["steps"])
    assert "sms.provider" in g["state"]["missing"] and g["state"]["ready"] is False
    # configure melipayamak pattern mode → readiness flips
    for k, v in {"sms.provider": "melipayamak", "sms.melipayamak_mode": "pattern", "sms.username": "u", "sms.password": "p", "sms.melipayamak_body_id": "123"}.items():
        assert client.put("/api/settings", json={"key": k, "value": v, "is_secret": k == "sms.password"}, headers=auth_headers).status_code in (200, 201)
    g = client.get("/api/sms/guide", headers=auth_headers).json()
    assert g["state"]["ready"] is True and g["state"]["missing"] == []


@pytest.fixture()
def sample_product(client, auth_headers, milk):
    b = client.post("/api/batches/receive", headers=auth_headers, json={"product_id": milk["id"], "quantity_received": 50, "buy_price": 10000, "sell_price": 20000})
    assert b.status_code == 201, b.text
    return {"product_id": milk["id"], "batch_id": b.json()["id"]}


def test_invoice_sms_sent_when_printing_off_and_skipped_when_disabled(client, auth_headers, sample_product):
    from app.database import SessionLocal
    from app.models import SmsMessage
    # printing OFF, sms ON
    client.put("/api/settings", json={"key": "pos.print_after_checkout", "value": "false"}, headers=auth_headers)
    client.put("/api/settings", json={"key": "sms.send_invoice", "value": "true"}, headers=auth_headers)
    client.put("/api/settings", json={"key": "sms.provider", "value": "file"}, headers=auth_headers)
    body = {"items": [{"product_id": sample_product["product_id"], "quantity": 1, "batch_id": sample_product["batch_id"]}],
            "payments": [{"method": "CASH", "amount": 20000}], "customer_phone": "09120000239", "customer_name": "تست پیامک"}
    r = client.post("/api/pos/checkout", json=body, headers=auth_headers)
    assert r.status_code in (200, 201), r.text
    with SessionLocal() as db:
        n1 = db.query(SmsMessage).filter(SmsMessage.phone == "09120000239").count()
    assert n1 == 1
    # sms OFF → no new message
    client.put("/api/settings", json={"key": "sms.send_invoice", "value": "false"}, headers=auth_headers)
    r = client.post("/api/pos/checkout", json=body, headers=auth_headers)
    assert r.status_code in (200, 201), r.text
    with SessionLocal() as db:
        n2 = db.query(SmsMessage).filter(SmsMessage.phone == "09120000239").count()
    assert n2 == 1


def test_relay_config_and_pairing_payload(client, auth_headers, monkeypatch):
    monkeypatch.setenv("PORT", "8765")
    r = client.put("/api/cloud/relay", json={"url": "relay.example.ir", "enabled": True}, headers=auth_headers)
    assert r.status_code == 200
    st = r.json()
    assert st["url"] == "https://relay.example.ir" and st["store"] and st["has_key"]
    link = client.get("/api/mobile/link", headers=auth_headers).json()
    assert link["relay"]["url"] == "https://relay.example.ir" and link["relay"]["store"] == st["store"] and len(link["relay"]["key"]) >= 16
    assert all(u.endswith(":8765") for u in link["lan"])
    code = client.post("/api/mobile/pair/code", headers=auth_headers).json()
    assert all(a.endswith(":8765") for a in code["addresses"])
    claim = client.post("/api/mobile/pair/claim", json={"code": code["code"]}).json()
    assert claim["relay"]["store"] == st["store"] and claim["port"] == 8765


def test_relay_server_roundtrip():
    """The self-hosted relay: phone call ↔ PC pull/reply, keyed per store."""
    import importlib.util
    import threading
    spec = importlib.util.spec_from_file_location("relay_server", ROOT / "relay" / "server.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    with TestClient(mod.app) as c:
        _relay_roundtrip(c)


def _relay_roundtrip(c):
    import threading
    key = "k" * 24
    # PC not connected yet → 503
    assert c.post("/r/shop1/call", params={"key": key}, json={"method": "GET", "path": "/api/health"}).status_code == 503
    # PC comes online, then answers the next request
    assert c.get("/r/shop1/pull", params={"key": key, "wait": 0.1}).json() == {"requests": []}
    out = {}

    def pc():
        got = c.get("/r/shop1/pull", params={"key": key, "wait": 5}).json()["requests"]
        out["req"] = got[0]
        c.post("/r/shop1/reply", params={"key": key}, json={"id": got[0]["id"], "status": 200, "headers": {"content-type": "application/json"}, "body": json.dumps({"ok": True})})

    t = threading.Thread(target=pc)
    t.start()
    r = c.post("/r/shop1/call", params={"key": key}, json={"method": "GET", "path": "/api/health", "headers": {"Authorization": "Bearer x"}})
    t.join(5)
    assert r.status_code == 200 and r.json()["status"] == 200 and json.loads(r.json()["body"]) == {"ok": True}
    assert out["req"]["path"] == "/api/health" and out["req"]["headers"]["Authorization"] == "Bearer x"
    # wrong key is rejected
    assert c.get("/r/shop1/status", params={"key": "wrong-key-1234"}).status_code == 401
    # beacon
    assert c.post("/r/shop1/beacon", params={"key": key}, json={"lan": ["192.168.1.7"], "port": 8765}).json()["ok"]
    assert c.get("/r/shop1/beacon", params={"key": key}).json()["lan"] == ["192.168.1.7"]


def test_launcher_stable_port_and_fullscreen():
    src = (ROOT / "installer" / "windows" / "run_supermarket.py").read_text(encoding="utf-8")
    assert "def stable_port(" in src and "PREFERRED_PORT = 8765" in src and 'os.environ["PORT"] = str(port)' in src
    assert "fullscreen=kiosk, frameless=kiosk" in src and "--kiosk" in src
    disc = (ROOT / "backend" / "app" / "services" / "discovery.py").read_text(encoding="utf-8")
    assert 'os.environ.get("PORT"' in disc


def test_android_v23_sources():
    m = MANIFEST.read_text(encoding="utf-8")
    assert "FOREGROUND_SERVICE" in m and ".InstallService" in m and "USE_BIOMETRIC" in m
    for f, needles in {
        "SmsLocal.java": ["BaseServiceNumber", "SendSMS", "kavenegar", "renderInvoice", "flush()"],
        "SalesScreens.java": ["SmsLocal.enqueueAndSend"],
        "AdminScreens.java": ["SmsLocal.GUIDE", "آموزش راه‌اندازی", "ارسال پیامک فاکتور به محض تأیید"],
        "Relay.java": ["/call?key=", "pcOnline"],
        "Api.java": ["viaRelay", "healthAt", "pc_lan_json"],
        "InstallService.java": ["startForeground", "install_t0", "percent()"],
        "SetupActivity.java": ["InstallService.start", "resumeInstallIfRunning"],
        "Biometric.java": ["BiometricPrompt", "createConfirmDeviceCredentialIntent"],
        "AppActivity.java": ["bioGate()"],
        "LoginActivity.java": ["ورود با اثر انگشت"],
        "Screens.java": ["Relay.available()", "bio_lock"],
    }.items():
        src = (JAVA / f).read_text(encoding="utf-8")
        for n in needles:
            assert n in src, f"{f}: {n}"
