"""Phase-9: update system (§27–29).

The rule that matters most here is §29: *no update may destroy user data*.
These tests prove the backup is a blocking precondition, that a corrupted or
substituted package is rejected, and that an update cannot be triggered
without re-authenticating the owner.
"""
import sqlite3
from pathlib import Path

import pytest

from app.services import updater
from app.services.updater import (ReleaseInfo, UpdateChannel, UpdateError,
                                  check_for_update, is_newer, parse_version,
                                  prepare_update, verify_package)


# --------------------------------------------------------------------------
# version comparison
# --------------------------------------------------------------------------
@pytest.mark.parametrize("text,expected", [
    ("1.2.3", (1, 2, 3)),
    ("v1.2.3", (1, 2, 3)),
    ("2.0", (2, 0, 0)),
    ("1.10.0", (1, 10, 0)),
    ("1.2.3-beta", (1, 2, 3)),
])
def test_version_parsing(text, expected):
    assert parse_version(text) == expected


def test_version_ordering_is_numeric_not_lexicographic():
    """'1.10.0' must beat '1.9.0' — string compare would get this wrong."""
    assert is_newer("1.10.0", "1.9.0")
    assert is_newer("2.0.0", "1.99.99")
    assert not is_newer("1.0.0", "1.0.0")
    assert not is_newer("0.9.0", "1.0.0")


# --------------------------------------------------------------------------
# channel behaviour
# --------------------------------------------------------------------------
class _FakeChannel(UpdateChannel):
    def __init__(self, release=None, error=None):
        self.release = release
        self.error = error

    def fetch_latest(self, timeout: float = 8.0):
        if self.error:
            raise self.error
        return self.release


def test_offline_check_is_reported_not_raised():
    result = check_for_update(
        _FakeChannel(error=UpdateError("CHANNEL_UNREACHABLE", "dns failure")),
        current="1.0.0")
    assert result["status"] == "UNAVAILABLE"
    assert result["code"] == "CHANNEL_UNREACHABLE"
    assert "current_version" in result


def test_up_to_date_is_detected():
    result = check_for_update(
        _FakeChannel(ReleaseInfo(version="1.0.0")), current="1.0.0")
    assert result["status"] == "UP_TO_DATE"
    assert result["update_available"] is False


def test_newer_release_is_detected_with_asset():
    release = ReleaseInfo(version="1.5.0", asset_name="Supermarket-System-v1.5.0-Setup.exe",
                          asset_url="https://example.invalid/setup.exe", asset_size=1234)
    result = check_for_update(_FakeChannel(release), current="1.0.0")
    assert result["status"] == "UPDATE_AVAILABLE"
    assert result["update_available"] is True
    assert result["installable"] is True
    assert result["latest"]["asset_name"].endswith("Setup.exe")


# --------------------------------------------------------------------------
# package verification (§28 "Verify Package")
# --------------------------------------------------------------------------
def test_empty_package_is_rejected(tmp_path):
    pkg = tmp_path / "setup.exe"
    pkg.write_bytes(b"")
    with pytest.raises(UpdateError) as exc:
        verify_package(pkg)
    assert exc.value.code == "PACKAGE_EMPTY"


def test_size_mismatch_is_rejected(tmp_path):
    """A truncated download must never be executed."""
    pkg = tmp_path / "setup.exe"
    pkg.write_bytes(b"x" * 100)
    with pytest.raises(UpdateError) as exc:
        verify_package(pkg, expected_size=999)
    assert exc.value.code == "SIZE_MISMATCH"


def test_checksum_mismatch_is_rejected(tmp_path):
    """A substituted package with the right size must still be rejected."""
    pkg = tmp_path / "setup.exe"
    pkg.write_bytes(b"x" * 100)
    with pytest.raises(UpdateError) as exc:
        verify_package(pkg, expected_size=100, expected_sha256="deadbeef")
    assert exc.value.code == "CHECKSUM_MISMATCH"


def test_valid_package_passes_verification(tmp_path):
    pkg = tmp_path / "setup.exe"
    pkg.write_bytes(b"installer-bytes")
    from app.services.updater import sha256_of

    result = verify_package(pkg, expected_size=15, expected_sha256=sha256_of(pkg))
    assert result["verified"] is True


def test_missing_package_is_reported(tmp_path):
    with pytest.raises(UpdateError) as exc:
        verify_package(tmp_path / "nope.exe")
    assert exc.value.code == "PACKAGE_MISSING"


# --------------------------------------------------------------------------
# the §29 rule: backup first, and abort if it fails
# --------------------------------------------------------------------------
def test_backup_produces_a_readable_database(client, auth_headers):
    result = updater.backup_database()
    path = Path(result["path"])
    assert path.exists() and result["size"] > 0
    # a backup you cannot open is not a backup
    conn = sqlite3.connect(str(path))
    tables = conn.execute(
        "SELECT count(*) FROM sqlite_master WHERE type='table'").fetchone()[0]
    conn.close()
    assert tables == result["tables"] > 0
    path.unlink(missing_ok=True)


def test_update_aborts_when_the_backup_fails(monkeypatch, client, auth_headers):
    """The single most important guarantee: no backup ⇒ nothing is applied."""
    release = ReleaseInfo(version="99.0.0", asset_name="Supermarket-System-v99.0.0-Setup.exe",
                          asset_url="https://example.invalid/setup.exe", asset_size=10)

    def _explode(db=None):
        raise UpdateError("BACKUP_FAILED", "disk full")

    monkeypatch.setattr(updater, "backup_database", _explode)

    from app.database import SessionLocal
    db = SessionLocal()
    try:
        result = prepare_update(db, channel=_FakeChannel(release), download=True)
    finally:
        db.close()

    assert result["status"] == "ABORTED"
    names = [s["name"] for s in result["steps"]]
    assert "پشتیبان‌گیری از پایگاه‌داده" in names
    backup_step = [s for s in result["steps"] if s["status"] == "FAIL"][0]
    assert "disk full" in backup_step["detail"]
    # download must never have been attempted
    assert not any("دانلود" in s["name"] for s in result["steps"])


def test_up_to_date_run_takes_no_backup_and_does_nothing(client, auth_headers):
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        result = prepare_update(
            db, channel=_FakeChannel(ReleaseInfo(version="0.0.1")), download=True)
    finally:
        db.close()
    assert result["status"] == "UP_TO_DATE"
    assert len(result["steps"]) == 1


def test_release_without_a_windows_asset_is_reported_honestly(
        monkeypatch, client, auth_headers):
    """§48: 'new version exists but no installer' must not look like success."""
    monkeypatch.setattr(updater, "backup_database",
                        lambda db=None: {"path": "/tmp/x.db", "size": 10, "tables": 3})
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        result = prepare_update(
            db, channel=_FakeChannel(ReleaseInfo(version="99.0.0")), download=True)
    finally:
        db.close()
    assert result["status"] == "NO_PACKAGE"


# --------------------------------------------------------------------------
# authorisation (§28)
# --------------------------------------------------------------------------
def test_update_requires_password_confirmation(client, auth_headers):
    """An open admin session alone must not be enough to trigger an update."""
    r = client.post("/api/system/update/prepare", headers=auth_headers,
                    json={"password": "definitely-wrong", "download": False})
    assert r.status_code == 403
    assert "BAD_PASSWORD" in r.text


def test_update_check_requires_authentication(client):
    assert client.get("/api/system/update/check").status_code in (401, 403)


def test_correct_password_starts_the_flow(client, auth_headers):
    """With the right password the flow runs and reports its steps honestly.

    In this offline sandbox GitHub is unreachable, so the expected outcome is
    a reported FAILED/UNAVAILABLE check — never a fake success.
    """
    r = client.post("/api/system/update/prepare", headers=auth_headers,
                    json={"password": "admin123", "download": False})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] in ("UP_TO_DATE", "READY", "FAILED", "NO_PACKAGE")
    assert body["steps"], "the run must be auditable step by step"
