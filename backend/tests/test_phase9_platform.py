"""Phase-9: store profile, trusted time, Persian calendar, theme, about
(§22, §23, §25, §59).
"""
from datetime import datetime, timedelta

import pytest

from app.services.timeservice import (check_time_sync, format_jalali,
                                      from_jalali, to_jalali)


# --------------------------------------------------------------------------
# Persian (Jalali) calendar — §22
# --------------------------------------------------------------------------
@pytest.mark.parametrize("gregorian,expected", [
    (datetime(2026, 9, 5), (1405, 6, 14)),
    (datetime(2026, 3, 21), (1405, 1, 1)),     # Nowruz 1405
    (datetime(2025, 3, 20), (1403, 12, 30)),   # last day of a leap year
    (datetime(2024, 3, 20), (1403, 1, 1)),     # Nowruz 1403
    (datetime(2023, 3, 21), (1402, 1, 1)),
    (datetime(2021, 3, 21), (1400, 1, 1)),
    (datetime(2000, 1, 1), (1378, 10, 11)),
    (datetime(1979, 2, 11), (1357, 11, 22)),   # 22 Bahman
    (datetime(1951, 1, 1), (1329, 10, 11)),
])
def test_jalali_conversion_matches_known_dates(gregorian, expected):
    assert to_jalali(gregorian) == expected


def test_jalali_round_trips_for_every_day_across_a_century():
    """A calendar that cannot round-trip will mis-date financial records."""
    day = datetime(1950, 1, 1)
    bad = []
    for _ in range(40_000):  # ~109 years
        jy, jm, jd = to_jalali(day)
        if from_jalali(jy, jm, jd) != (day.year, day.month, day.day):
            bad.append(day.date())
        day += timedelta(days=1)
    assert not bad, f"{len(bad)} round-trip failures, first: {bad[:3]}"


def test_jalali_month_and_day_are_always_in_range():
    day = datetime(2000, 1, 1)
    for _ in range(12_000):
        jy, jm, jd = to_jalali(day)
        assert 1 <= jm <= 12, (day, jm)
        assert 1 <= jd <= 31, (day, jd)
        if jm >= 7:
            assert jd <= 30
        day += timedelta(days=1)


def test_persian_formatting_uses_persian_digits_and_month_names():
    text = format_jalali(datetime(2026, 9, 5, 14, 30))
    assert "شهریور" in text
    assert "۱۴۰۵" in text
    assert not any(c.isdigit() and c.isascii() for c in text)


# --------------------------------------------------------------------------
# trusted time — §22
# --------------------------------------------------------------------------
def test_unreachable_ntp_reports_unverified_never_pass():
    """§48/§61: an unreachable time source must not be reported as success."""
    result = check_time_sync(["203.0.113.1"], timeout=0.4)  # TEST-NET-3, black hole
    assert result["status"] == "UNVERIFIED"
    assert result["network_utc"] is None
    assert result["local_utc"]
    assert result["errors"]


def test_time_endpoint_returns_both_calendars(client, auth_headers):
    got = client.get("/api/settings/time", headers=auth_headers).json()
    assert got["timezone"] == "Asia/Tehran"
    assert got["timezone_resolved"] is True
    assert got["utc"] and got["local"]
    assert got["jalali"] and got["gregorian"]
    assert got["weekday"]


def test_time_verify_endpoint_reports_honestly(client, auth_headers):
    """Runs a real NTP query; offline sandboxes must yield UNVERIFIED, not PASS."""
    r = client.post("/api/settings/time/verify", headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["status"] in ("PASS", "WARNING", "UNVERIFIED")
    if body["status"] == "UNVERIFIED":
        assert body["drift_seconds"] is None
    else:
        assert isinstance(body["drift_seconds"], (int, float))


# --------------------------------------------------------------------------
# store profile — §25
# --------------------------------------------------------------------------
def test_store_profile_round_trips(client, auth_headers):
    payload = {
        "name": "سوپرمارکت خواجوی",
        "phone": "021-88776655",
        "address": "تهران، خیابان آزادی، پلاک ۱۲",
        "city": "تهران",
        "tax_id": "411222333",
        "receipt_note": "از خرید شما سپاسگزاریم",
    }
    r = client.put("/api/settings/store-profile", headers=auth_headers, json=payload)
    assert r.status_code == 200, r.text
    got = client.get("/api/settings/store-profile", headers=auth_headers).json()
    for key, value in payload.items():
        assert got[key] == value


def test_store_profile_is_readable_by_any_user_for_receipts(client, auth_headers):
    """The POS must be able to print a header without settings.manage."""
    r = client.get("/api/settings/store-profile", headers=auth_headers)
    assert r.status_code == 200
    assert "name" in r.json()


# --------------------------------------------------------------------------
# theme — §23
# --------------------------------------------------------------------------
def test_theme_defaults_to_auto_and_resolves_to_a_real_mode(client, auth_headers):
    got = client.get("/api/settings/theme", headers=auth_headers).json()
    assert got["theme"] in ("auto", "light", "dark")
    assert got["resolved"] in ("light", "dark"), "clients need a concrete mode"


def test_theme_can_be_pinned_and_schedule_configured(client, auth_headers):
    r = client.put("/api/settings/theme", headers=auth_headers,
                   json={"theme": "dark"})
    assert r.status_code == 200
    assert r.json()["theme"] == "dark"
    assert r.json()["resolved"] == "dark", "an explicit mode overrides the schedule"

    r = client.put("/api/settings/theme", headers=auth_headers,
                   json={"theme": "auto", "light_at": "06:30", "dark_at": "18:45"})
    body = r.json()
    assert body["light_at"] == "06:30" and body["dark_at"] == "18:45"
    assert body["resolved"] in ("light", "dark")


def test_invalid_theme_is_rejected(client, auth_headers):
    r = client.put("/api/settings/theme", headers=auth_headers,
                   json={"theme": "neon"})
    assert r.status_code == 422


# --------------------------------------------------------------------------
# about — §59
# --------------------------------------------------------------------------
def test_about_reports_version_and_developer(client, auth_headers):
    got = client.get("/api/settings/about", headers=auth_headers).json()
    assert got["developer"] == "خواجوی"
    assert got["version"]
    assert got["app_name"]
