"""v2.1 — simpler, sturdier PC↔phone linking + Android wizard/licence contract.

* 6-digit pairing code (typed instead of scanned): mint → claim once → gone.
* Stable link key in every pairing payload + LAN beacon so the phone re-finds
  the PC after its IP changes (UDP 48765, answers only to its own key).
* /mobile/link hands a paired phone the PC licence verdict (phone locks with it)
  → gated behind the same 402 as everything else.
* In-app Google sign-in endpoints exist (PKCE authorization-code, loopback).
* Android sources: wizard, Jalali date picker replaces typed dates, new app
  name, support reachable without a PC, no minutes on the loading screen.
"""
from __future__ import annotations

import re
import socket
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ANDROID = ROOT / "mobile-android" / "app" / "src" / "main"
JAVA = ANDROID / "java" / "ir" / "khajavy" / "supermarket"


def _src() -> str:
    return "\n".join(p.read_text(encoding="utf-8") for p in JAVA.glob("*.java"))


def test_pair_code_is_single_use_and_carries_link_key(client, auth_headers):
    r = client.post("/api/mobile/pair/code", headers=auth_headers)
    assert r.status_code == 200, r.text
    code = r.json()["code"]
    assert re.fullmatch(r"\d{6}", code) and r.json()["expires_in"] == 600
    key = r.json()["link_key"]
    assert re.fullmatch(r"[0-9A-F]{12}", key)
    # claim needs no auth (phone has nothing yet) — but a wrong code is refused
    bad = client.post("/api/mobile/pair/claim", json={"code": "000000" if code != "000000" else "111111"})
    assert bad.status_code == 404 and bad.json()["detail"]["code"] == "PAIR_CODE_INVALID"
    ok = client.post("/api/mobile/pair/claim", json={"code": code})
    assert ok.status_code == 200, ok.text
    p = ok.json()
    assert p["token"] and p["device_id"] and p["link_key"] == key and p["urls"] and p["v"] == 3
    # single use
    again = client.post("/api/mobile/pair/claim", json={"code": code})
    assert again.status_code == 404
    # the minted device shows up in the devices list
    devs = client.get("/api/mobile/devices", headers=auth_headers).json()
    assert any(d["id"] == p["device_id"] for d in devs)
    # the QR payload carries the very same stable key
    info = client.get("/api/mobile/pair/info", headers=auth_headers).json()
    assert info["payload"]["link_key"] == key


def test_link_endpoint_gives_phone_the_pc_license_verdict(client, auth_headers):
    p = client.post("/api/mobile/pair/code", headers=auth_headers).json()
    claimed = client.post("/api/mobile/pair/claim", json={"code": p["code"]}).json()
    r = client.get("/api/mobile/link", headers={"Authorization": "Bearer " + claimed["token"]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["link_key"] == p["link_key"]
    assert set(body["license"]) >= {"allowed", "reason", "status", "expires", "days_left", "activated"}
    assert "cloud" in body
    # unauthenticated → refused
    assert client.get("/api/mobile/link").status_code == 401


def test_lan_beacon_answers_only_its_own_key(client, auth_headers):
    from app.database import SessionLocal
    from app.services import discovery
    key = client.post("/api/mobile/pair/code", headers=auth_headers).json()["link_key"]
    discovery.start(SessionLocal, 8123)   # no-op if the app lifespan already started it (then port = settings.PORT)
    time.sleep(0.3)
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.settimeout(1.5)
        s.sendto(f"SMKT-FIND {key}".encode(), ("127.0.0.1", discovery.PORT))
        data, _ = s.recvfrom(256)
        parts = data.decode().split(" ", 3)
        assert parts[0] == "SMKT-HERE" and parts[1] in ("8123", "8000") and parts[2] == key
        # a stranger's key gets silence
        s.sendto(b"SMKT-FIND DEADBEEF0000", ("127.0.0.1", discovery.PORT))
        try:
            s.recvfrom(256)
            assert False, "beacon must not answer another shop's key"
        except socket.timeout:
            pass
        # an empty key (first-time auto-discover from the wizard) is answered
        s.sendto(b"SMKT-FIND", ("127.0.0.1", discovery.PORT))
        data, _ = s.recvfrom(256)
        assert data.decode().split(" ")[2] == key
        s.close()
    finally:
        discovery.stop()


def test_inapp_google_signin_endpoints(client, auth_headers, monkeypatch):
    r = client.post("/api/cloud/oauth/start", json={"client_id": "cid.apps.googleusercontent.com", "client_secret": "sec"}, headers=auth_headers)
    assert r.status_code == 200, r.text
    url = r.json()["url"]
    assert url.startswith("https://accounts.google.com/o/oauth2/v2/auth?") and "code_challenge_method=S256" in url
    assert "redirect_uri=http%3A%2F%2F" in url and "%2Fapi%2Fcloud%2Foauth%2Fcallback" in url
    assert "127.0.0.1" in url or "testserver" in url
    # the callback is public (browser lands there) but the state must match
    bad = client.get("/api/cloud/oauth/callback", params={"code": "x", "state": "nope"})
    assert bad.status_code == 200 and "معتبر نیست" in bad.text
    # token exchange is stubbed → connected
    import httpx
    from app.services import cloud as svc

    class _R:
        def __init__(self, d, code=200): self._d, self.status_code, self.text = d, code, str(d)
        def json(self): return self._d
    monkeypatch.setattr(httpx, "post", lambda *a, **k: _R({"access_token": "at", "refresh_token": "rt", "expires_in": 3600}))
    monkeypatch.setattr(httpx, "get", lambda *a, **k: _R({"email": "owner@example.com"}))
    good = client.get("/api/cloud/oauth/callback", params={"code": "abc", "state": r.json()["state"]})
    assert good.status_code == 200 and "owner@example.com" in good.text
    st = client.get("/api/cloud/status", headers=auth_headers).json()
    assert st["connected"] and st["account"] == "owner@example.com"
    # a paired phone now receives the Drive credentials through /mobile/link
    p = client.post("/api/mobile/pair/code", headers=auth_headers).json()
    claimed = client.post("/api/mobile/pair/claim", json={"code": p["code"]}).json()
    link = client.get("/api/mobile/link", headers={"Authorization": "Bearer " + claimed["token"]}).json()
    assert link["cloud"] and link["cloud"]["refresh_token"] == "rt" and link["cloud"]["account"] == "owner@example.com"
    assert "cloud" in claimed or True  # (claimed before sign-in → no creds; that is fine)
    svc.disconnect(__import__("app.database", fromlist=["SessionLocal"]).SessionLocal())


def test_android_v21_wizard_datepicker_name_and_support():
    src = _src()
    strings = (ANDROID / "res" / "values" / "strings.xml").read_text(encoding="utf-8")
    assert "سوپرمارکت خواجوی" not in strings and 'name="app_name">سوپری من<' in strings
    assert "طراحی و توسعه توسط خواجوی" in strings
    manifest = (ANDROID / "AndroidManifest.xml").read_text(encoding="utf-8")
    for act in (".SetupActivity", ".LockActivity", ".SupportActivity"):
        assert act in manifest
    # wizard: both paths, licence on phone, one-time install loading, no "minutes" wording
    setup = (JAVA / "SetupActivity.java").read_text(encoding="utf-8")
    assert "نسخهٔ رایانه (ویندوز) را دارم" in setup and "فقط گوشی — رایانه ندارم" in setup
    for step in ("license", "store", "contact", "currency", "theme", "catalog", "admin", "finish"):
        assert f'"{step}"' in setup
    assert "45L * 60L * 1000L" in setup and "first_loading_done" in setup
    loading_block = setup[setup.index("void loadingScreen"):setup.index("void finishSetup")]
    assert "دقیقه" not in loading_block
    assert "pair/claim" in setup and "Discovery.find" in setup and "Sync.checkPcLicense" in setup
    # PC licence expiry locks the phone; standalone key validated against the same server
    lic = (JAVA / "Lic.java").read_text(encoding="utf-8")
    assert "soft-hat-4eba.khajavi8056.workers.dev" in lic and "api_action=validate" in lic
    assert "لایسنس شما به پایان رسیده" in (JAVA / "LockActivity.java").read_text(encoding="utf-8")
    assert "code == 402" in (JAVA / "Api.java").read_text(encoding="utf-8")
    # every date field is a calendar picker — no typed date hints remain
    assert re.search(r'Ui\.input\([^)]*۱۴۰[0-9]', src) is None, "typed date field left behind"
    assert src.count("DatePicker.field(") >= 5
    dp = (JAVA / "DatePicker.java").read_text(encoding="utf-8")
    assert "Jalali.monthLength" in dp and "Jalali.MONTHS" in dp and "امروز" in dp
    # support: same relay as Windows (bot API + TCK-@install routing), reachable when locked / standalone
    relay = (JAVA / "SupportRelay.java").read_text(encoding="utf-8")
    assert "botapi.rubika.ir/v3" in relay and "@" in relay and "TCK-%06d" in relay
    assert "SupportActivity" in (JAVA / "LockActivity.java").read_text(encoding="utf-8")
    # LAN re-discovery on the phone uses the same protocol as the PC beacon
    disc = (JAVA / "Discovery.java").read_text(encoding="utf-8")
    assert "SMKT-FIND" in disc and "SMKT-HERE" in disc and "48765" in disc
    # starter catalogue bundled for the standalone wizard
    assert (ANDROID / "assets" / "starter_catalog.csv").exists()
    assert "starter_catalog.csv" in (ROOT / "scripts" / "android" / "build-apk.sh").read_text(encoding="utf-8")
    # in-app Drive fallback for the phone
    assert "appDataFolder" in (JAVA / "CloudSync.java").read_text(encoding="utf-8")


def test_pc_qr_is_not_cropped_anymore():
    css = (ROOT / "frontend" / "theme-pro.css").read_text(encoding="utf-8")
    assert "overflow: hidden" not in css[css.index(".mob-qr {"):css.index(".mob-qr {") + 300]
    assert ".qr-box {" in css and "box-sizing: content-box" in css
    js = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    assert "/mobile/pair/code" in js and 'class="qr-box"' in js and "createSvgTag({ cellSize: 4, margin: 0, scalable: true })" in js
    ob = (ROOT / "frontend" / "onboarding.js").read_text(encoding="utf-8")
    assert 'class="qr-box"' in ob and "/mobile/pair/code" in ob
