"""v3.5.11 — the device identity must not move, on either platform.

Two shop-reported bugs shared one root cause: the Android identity was derived from
``device_id``, a value the shop PC mints at random (or the phone invents from the clock), so it
changed on every pairing and every re-login after the idle lock. The licence server counted each
new value as another device until it answered MAX_DEVICES_REACHED, and — because the standalone
admin password was hashed *with that same identity* — a correct password started being reported
as wrong.

The desktop had the same class of bug one level down: ``uuid.getnode()`` returns a RANDOM number
whenever it cannot read a MAC address, so a machine with no readable MAC presented a new identity
on every start.

These tests pin the guarantees that replace both.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.database import SessionLocal
from app.routers.mobile import _devices
from app.services import license as lic

JAVA = (Path(__file__).resolve().parents[2] / "mobile-android" / "app" / "src" / "main" / "java"
        / "ir" / "khajavy" / "supermarket")


def _java(name: str) -> str:
    return (JAVA / name).read_text(encoding="utf-8")


class _NoMachineId:
    """Stands in for ``Path`` so the /etc/machine-id probe finds nothing."""

    def __init__(self, *a, **k):
        pass

    def read_text(self, *a, **k):
        raise OSError("no machine-id in this test")


def _force_source(monkeypatch, node: int) -> None:
    """Leave ``uuid.getnode`` as the only thing that can feed the hash."""
    monkeypatch.setattr(lic.platform, "system", lambda: "Plan9")   # not Windows → winreg skipped
    monkeypatch.setattr(lic, "Path", _NoMachineId)
    monkeypatch.setattr(lic.uuid, "getnode", lambda: node)


@pytest.fixture()
def hwid_file(tmp_path, monkeypatch):
    """A private id file plus a cold cache, so each test starts with no published identity."""
    f = tmp_path / "machine.id"
    monkeypatch.setattr(lic, "_hwid_file", lambda: f)
    monkeypatch.setattr(lic, "_HWID", None)
    yield f
    monkeypatch.setattr(lic, "_HWID", None)


# --------------------------------------------------------------------------- desktop identity
def test_hwid_is_frozen_once_published(hwid_file, monkeypatch):
    _force_source(monkeypatch, 0x001122334455)        # multicast bit clear → a real MAC
    first = lic.hwid()
    assert len(first) == 19 and first.count("-") == 3
    assert hwid_file.read_text(encoding="utf-8") == first

    # A different underlying source (new network card, reinstalled OS) must NOT move the
    # identity: that is what made the licence server see a second device.
    monkeypatch.setattr(lic, "_HWID", None)
    _force_source(monkeypatch, 0x0099AABBCCDD)
    assert lic.hwid() == first


def test_invented_mac_is_refused_and_still_stable(hwid_file, monkeypatch):
    invented = 0x011122334455                          # multicast bit SET == CPython's "made up"
    _force_source(monkeypatch, invented)
    out = lic.hwid()
    assert out != lic._format_hwid(f"{invented:012x}"), "used the random value verbatim"
    assert len(out) == 19 and out.count("-") == 3

    # Refusing it is only useful if what we publish instead does not change next start.
    monkeypatch.setattr(lic, "_HWID", None)
    _force_source(monkeypatch, 0x0199999999)           # a different invented value
    assert lic.hwid() == out


# --------------------------------------------------------------------------- paired-device list
def test_pair_token_reuses_the_device_the_phone_already_has(client, auth_headers):
    did = "stable-abc123"
    r1 = client.post("/api/mobile/pair/token", json={"name": "گوشی صندوق", "device_id": did},
                     headers=auth_headers)
    assert r1.status_code == 200, r1.text
    # The phone re-sends the same id after every idle-lock re-login; the PC must refresh the
    # existing row instead of appending another "device".
    r2 = client.post("/api/mobile/pair/token", json={"name": "گوشی صندوق", "device_id": did},
                     headers=auth_headers)
    assert r2.status_code == 200, r2.text
    assert r1.json()["device_id"] == r2.json()["device_id"] == did
    with SessionLocal() as db:
        assert [d["id"] for d in _devices(db)].count(did) == 1


def test_pair_token_without_an_id_still_mints_a_fresh_one(client, auth_headers):
    """QR pairing has no id to offer and must keep creating a new device each time."""
    a = client.post("/api/mobile/pair/token", json={"name": "گوشی (QR)"}, headers=auth_headers).json()
    b = client.post("/api/mobile/pair/token", json={"name": "گوشی (QR)"}, headers=auth_headers).json()
    assert a["device_id"] and b["device_id"] and a["device_id"] != b["device_id"]


def test_reauthenticating_does_not_undo_a_revocation(client, auth_headers):
    did = "stable-revoke-me"
    client.post("/api/mobile/pair/token", json={"device_id": did}, headers=auth_headers)
    assert client.delete(f"/api/mobile/devices/{did}", headers=auth_headers).status_code == 200
    # GET /devices hides revoked rows, so read the stored list.
    client.post("/api/mobile/pair/token", json={"device_id": did}, headers=auth_headers)
    with SessionLocal() as db:
        row = next(d for d in _devices(db) if d["id"] == did)
    assert row["revoked"] is True


# --------------------------------------------------------------------------- Android sources
# The Java cannot be executed here (no device; android.jar's org.json is a stub that throws), so
# these read the shipped source the way test_v20_native_android.py already does. They exist
# because the passOk fix was once written, then silently reverted by a bad file write, and
# NOTHING caught it: the code still compiled, the APK still built, and a release went out with
# the bug in it. A missing guard is what let that happen, not a missing edit.
def test_password_check_is_not_bound_to_the_device_identity():
    src = _java("Local.java")
    assert 'Lic.hwid() + ":"' not in src, "passOk still salts the password with the device id"
    assert "lastIndexOf(':')" in src, "the wizard-era hash comparison went missing"


def test_admin_password_is_stored_device_independently():
    assert 'Lic.hwid() + ":"' not in _java("SetupActivity.java")
    assert 'Local.sha(str("admin_username")' in _java("SetupActivity.java")


def test_phone_identity_is_frozen_and_seeded_from_hardware():
    assert 'Prefs.get("hwid", "")' in _java("Lic.java"), "hwid() is not frozen across runs"
    assert "ANDROID_ID" in _java("Prefs.java"), "the hardware seed is gone"


def test_no_time_based_ids_and_no_mint_on_every_login():
    login = _java("LoginActivity.java")
    assert "Long.toHexString(System.currentTimeMillis())" not in login, "time-based device id is back"
    assert "Prefs.deviceToken(this) == null" in login, "minting a new device on every sign-in again"
    assert "hwidSeed" in _java("SetupActivity.java")
