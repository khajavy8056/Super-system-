from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

# Point the app at a throwaway database BEFORE importing app modules.
_TMP = Path(tempfile.mkdtemp(prefix="supermarket_test_"))
os.environ["DATABASE_URL"] = f"sqlite:///{_TMP / 'test.db'}"
os.environ["SECRET_KEY"] = "test-secret-key-that-is-long-enough-for-hs256"
os.environ["ADMIN_USERNAME"] = "admin"
os.environ["ADMIN_PASSWORD"] = "admin123"

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
    """Batch A: buy 50000/sell 60000 qty 10; Batch B: buy 55000/sell 65000 qty 20."""
    r1 = client.post("/api/batches/receive", headers=auth_headers, json={
        "product_id": milk["id"], "quantity_received": 10, "buy_price": 50000,
        "sell_price": 60000, "expiry_date": "2026-09-10"})
    r2 = client.post("/api/batches/receive", headers=auth_headers, json={
        "product_id": milk["id"], "quantity_received": 20, "buy_price": 55000,
        "sell_price": 65000, "expiry_date": "2026-09-20"})
    assert r1.status_code == 201 and r2.status_code == 201
    return {"a": r1.json(), "b": r2.json()}
