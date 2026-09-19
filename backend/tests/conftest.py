from __future__ import annotations

import os
import tempfile
from datetime import date, timedelta
from pathlib import Path

import pytest

# Point the app at a throwaway database BEFORE importing app modules.
_TMP = Path(tempfile.mkdtemp(prefix="supermarket_test_"))
os.environ["DATABASE_URL"] = f"sqlite:///{_TMP / 'test.db'}"
os.environ["SECRET_KEY"] = "test-secret-key-that-is-long-enough-for-hs256"
os.environ["ADMIN_USERNAME"] = "admin"
os.environ["ADMIN_PASSWORD"] = "admin123"
os.environ.setdefault("SUPERMARKET_LICENSE_GATE", "0")
os.environ.setdefault("SUPERMARKET_ONLINE_LOOKUPS", "1")  # v3.4: online lookups are off in production; legacy tests exercise them explicitly  # v1.5: gate tested explicitly in test_v1_5_license_setup.py

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="session")
def auth_headers(client):
    r = client.post("/api/auth/login", data={"username": "admin", "password": "admin123"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _days_from_now(days: int) -> str:
    """ISO date ``days`` from today — fixtures must never hard-code a calendar date."""
    return (date.today() + timedelta(days=days)).isoformat()


_FA_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")


def fa_digits(text: str) -> str:
    """``receipt_text`` localises numbers to Persian digits (v2.8 layout), so a test
    that looks for an invoice number inside a receipt must look for THIS form."""
    return str(text).translate(_FA_DIGITS)


_barcode_counter = 0


@pytest.fixture()
def milk(client, auth_headers):
    global _barcode_counter
    _barcode_counter += 1
    barcode = f"62600000000{_barcode_counter:04d}"
    r = client.post("/api/products", json={"barcode": barcode, "name": f"Milk X {_barcode_counter}L"},
                    headers=auth_headers)
    assert r.status_code == 201, r.text
    return r.json()


@pytest.fixture()
def two_batches(client, auth_headers, milk):
    """Batch A: buy 50000/sell 60000 qty 10; Batch B: buy 55000/sell 65000 qty 20.

    Expiry dates are RELATIVE to today. They used to be hard-coded
    ("2026-09-10" / "2026-09-20"), which silently turned into a time bomb: once
    the calendar passed 2026-09-10 batch A became an EXPIRED batch, every
    checkout against it returned BATCH_EXPIRED and 16 tests started failing for
    a reason that had nothing to do with the code under test.
    """
    r1 = client.post("/api/batches/receive", headers=auth_headers, json={
        "product_id": milk["id"], "quantity_received": 10, "buy_price": 50000,
        "sell_price": 60000, "expiry_date": _days_from_now(30)})
    r2 = client.post("/api/batches/receive", headers=auth_headers, json={
        "product_id": milk["id"], "quantity_received": 20, "buy_price": 55000,
        "sell_price": 65000, "expiry_date": _days_from_now(60)})
    assert r1.status_code == 201 and r2.status_code == 201
    return {"a": r1.json(), "b": r2.json()}
