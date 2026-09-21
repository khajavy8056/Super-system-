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


# --------------------------------------------------------------------------
# Regression: ledger rows were persisted with created_at = NULL because the
# migration emitted the column without DEFAULT now() while the model relied
# solely on server_default. The UI then rendered every entry as 1348/10/11.
# --------------------------------------------------------------------------
def test_ledger_entries_have_a_creation_timestamp(client, auth_headers):
    import uuid
    phone = "0939" + uuid.uuid4().hex[:7]
    cust = client.post("/api/customers", headers=auth_headers, json={
        "name": "تست زمان", "phone": phone, "credit_limit": 1000000}).json()

    r = client.post(f"/api/customers/{cust['id']}/ledger/adjust",
                    headers=auth_headers,
                    json={"amount": 25000, "entry_type": "ADJUSTMENT_DEBIT",
                          "note": "بدهی ابتدای دوره"})
    assert r.status_code in (200, 201), r.text

    entries = client.get(f"/api/customers/{cust['id']}/ledger",
                         headers=auth_headers).json()["entries"]
    assert entries, "expected at least one ledger entry"
    for e in entries:
        assert e["created_at"], f"ledger entry persisted without created_at: {e}"


def test_timestamp_mixin_defaults_are_python_side():
    """The Python-side default must exist so correctness does not depend on
    whatever DDL happens to be on disk."""
    from app.models.sales import CustomerLedgerEntry
    for col in ("created_at", "updated_at"):
        c = CustomerLedgerEntry.__table__.c[col]
        assert c.default is not None, f"{col} has no Python-side default"


# --------------------------------------------------------------------------
# Debt reminder SMS (§35)
# --------------------------------------------------------------------------
def _debtor(client, auth_headers, amount=75000):
    import uuid
    phone = "0939" + uuid.uuid4().hex[:7]
    c = client.post("/api/customers", headers=auth_headers, json={
        "name": "بدهکار", "phone": phone, "credit_limit": 10_000_000}).json()
    client.post(f"/api/customers/{c['id']}/ledger/adjust", headers=auth_headers,
                json={"amount": amount, "entry_type": "ADJUSTMENT_DEBIT",
                      "note": "تست"})
    return c


def test_debt_reminder_queues_a_rendered_message(client, auth_headers):
    c = _debtor(client, auth_headers)
    r = client.post(f"/api/customers/{c['id']}/debt-reminder",
                    headers=auth_headers, json={})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] == "PENDING"
    assert body["phone"] == c["phone"]
    # placeholders must be substituted, never leaked to the customer
    assert "{customer}" not in body["text"] and "{amount}" not in body["text"]
    assert "بدهکار" in body["text"]
    assert "75,000" in body["text"]
    assert "تومان" in body["text"]


def test_debt_reminder_refuses_when_there_is_no_debt(client, auth_headers):
    import uuid
    c = client.post("/api/customers", headers=auth_headers, json={
        "name": "بی‌بدهی", "phone": "0939" + uuid.uuid4().hex[:7]}).json()
    r = client.post(f"/api/customers/{c['id']}/debt-reminder",
                    headers=auth_headers, json={})
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "NO_DEBT"


def test_debt_reminder_requires_a_phone_number(client, auth_headers):
    c = client.post("/api/customers", headers=auth_headers,
                    json={"name": "بدون تلفن"}).json()
    client.post(f"/api/customers/{c['id']}/ledger/adjust", headers=auth_headers,
                json={"amount": 5000, "entry_type": "ADJUSTMENT_DEBIT"})
    r = client.post(f"/api/customers/{c['id']}/debt-reminder",
                    headers=auth_headers, json={})
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "NO_PHONE"


def test_debt_reminder_unknown_customer_is_404(client, auth_headers):
    r = client.post("/api/customers/999999/debt-reminder",
                    headers=auth_headers, json={})
    assert r.status_code == 404


def test_debt_reminder_accepts_an_explicit_override(client, auth_headers):
    c = _debtor(client, auth_headers)
    r = client.post(f"/api/customers/{c['id']}/debt-reminder",
                    headers=auth_headers, json={"text": "متن دستی"})
    assert r.status_code == 201
    assert r.json()["text"] == "متن دستی"
