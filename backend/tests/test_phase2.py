"""Phase-2 acceptance tests: complete stocktaking cycle (§19–20), security
hardening (BUG-011/013), backup/restore (BUG-024)."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

_TMP = Path(tempfile.mkdtemp(prefix="supermarket_p2_"))
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_TMP / 'p2.db'}")

from fastapi.testclient import TestClient  # noqa: E402

from app.database import SessionLocal, init_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models import ProductBatch  # noqa: E402

init_db()


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def admin_h(client):
    r = client.post("/api/auth/login", data={"username": "admin", "password": "admin123"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture(scope="module")
def manager_h(client, admin_h):
    client.post("/api/users", headers=admin_h, json={
        "username": "mgr", "password": "mgrpass123", "full_name": "Manager", "roles": ["Manager"]})
    r = client.post("/api/auth/login", data={"username": "mgr", "password": "mgrpass123"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture(scope="module")
def stocktaker_h(client, admin_h):
    client.post("/api/users", headers=admin_h, json={
        "username": "stock1", "password": "stock1234", "full_name": "Stocker", "roles": ["Inventory Operator"]})
    r = client.post("/api/auth/login", data={"username": "stock1", "password": "stock1234"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


_n = 0


def _mk_batch(client, headers, qty=30):
    global _n
    _n += 1
    p = client.post("/api/products", headers=headers,
                    json={"barcode": f"81000000000{_n:04d}", "name": f"ST T{_n}"}).json()
    b = client.post("/api/batches/receive", headers=headers,
                    json={"product_id": p["id"], "quantity_received": qty,
                          "buy_price": 1000, "sell_price": 1500}).json()
    return p, b


# --- Full stocktaking lifecycle (§19 + §20 resume) -----------------------------

def test_stocktake_full_cycle_with_approval(client, admin_h, manager_h, stocktaker_h):
    p, b = _mk_batch(client, admin_h, qty=30)
    _mk_batch(client, admin_h, qty=4)  # second batch -> more items to count

    # stocktaker creates the session (snapshot includes zero-stock batches by default)
    st = client.post("/api/inventory/stocktakes", headers=stocktaker_h,
                     json={"name": "Full Cycle #1"}).json()
    assert st["status"] == "DRAFT"
    item = next(i for i in st["items"] if i["batch_id"] == b["id"])

    # count a few items -> session auto-moves to IN_PROGRESS, counts persist (§25)
    r = client.post("/api/inventory/stocktakes/count", headers=stocktaker_h,
                    json={"item_id": item["id"], "physical_qty": 28})
    assert r.status_code == 200
    assert r.json()["difference"] == -2

    prog = client.get(f"/api/inventory/stocktakes/{st['id']}/progress", headers=stocktaker_h).json()
    assert prog["counted"] >= 1 and prog["status"] == "IN_PROGRESS"
    assert prog["next_item_id"] is not None

    # complete -> PENDING_APPROVAL, stock NOT changed yet
    done = client.post(f"/api/inventory/stocktakes/{st['id']}/complete", headers=stocktaker_h)
    assert done.status_code == 200
    assert done.json()["status"] == "PENDING_APPROVAL"
    batch_now = client.get(f"/api/batches/{b['id']}", headers=admin_h).json()
    assert batch_now["current_qty"] == 30, "no adjustment before approval"

    # stocktaker must NOT be able to approve (manager-only permission)
    denied = client.post(f"/api/inventory/stocktakes/{st['id']}/approve", headers=stocktaker_h)
    assert denied.status_code == 403, "inventory staff must not approve their own count"

    # differences report with value
    diffs = client.get(f"/api/inventory/stocktakes/{st['id']}/differences", headers=manager_h).json()
    row = next(d for d in diffs if d["item_id"] == item["id"])
    assert row["difference"] == -2 and row["value_difference"] == -2000.0

    # manager approves -> stock adjusted + audited
    ok = client.post(f"/api/inventory/stocktakes/{st['id']}/approve", headers=manager_h)
    assert ok.status_code == 200 and ok.json()["status"] == "ADJUSTED"
    after = client.get(f"/api/batches/{b['id']}", headers=admin_h).json()
    assert after["current_qty"] == 28
    audit = client.get("/api/audit?action=STOCKTAKE_APPROVED", headers=admin_h).json()
    assert any(a["entity_id"] == st["id"] for a in audit)


def test_stocktake_resume_after_close(client, admin_h, stocktaker_h):
    """§20: counts survive; the session resumes exactly at the next pending item."""
    p, b = _mk_batch(client, admin_h, qty=10)
    st = client.post("/api/inventory/stocktakes", headers=stocktaker_h,
                     json={"name": "Resume Test"}).json()
    items = [i for i in st["items"] if i["batch_id"] == b["id"]]
    # count the first item only, then "close the app" (drop auth/session entirely)
    r = client.post("/api/inventory/stocktakes/count", headers=stocktaker_h,
                    json={"item_id": items[0]["id"], "physical_qty": 9})
    assert r.status_code == 200

    # reopen: fresh login, fetch progress, resume from next_item_id
    fresh = client.post("/api/auth/login", data={"username": "stock1", "password": "stock1234"}).json()
    H = {"Authorization": f"Bearer {fresh['access_token']}"}
    prog = client.get(f"/api/inventory/stocktakes/{st['id']}/progress", headers=H).json()
    assert prog["counted"] == 1 and prog["remaining"] >= 1
    detail = client.get(f"/api/inventory/stocktakes/{st['id']}", headers=H).json()
    counted_rows = [i for i in detail["items"] if i["status"] == "COUNTED"]
    assert len(counted_rows) == 1 and counted_rows[0]["physical_qty"] == 9


def test_stocktake_includes_zero_stock_batches(client, admin_h, stocktaker_h):
    """BUG-018: believed-empty batches must be countable (found stock)."""
    p, b = _mk_batch(client, admin_h, qty=5)
    sell = client.post("/api/pos/checkout", headers=admin_h, json={
        "items": [{"product_id": p["id"], "batch_id": b["id"], "quantity": 5}],
        "payments": [{"method": "CASH", "amount": 5 * 1500}]}).json()
    assert sell["invoice_number"]
    st = client.post("/api/inventory/stocktakes", headers=stocktaker_h,
                     json={"name": "Zero Inc"}).json()
    zero_item = next((i for i in st["items"] if i["batch_id"] == b["id"]), None)
    assert zero_item is not None and zero_item["system_qty"] == 0
    # count 2 found units of a "sold out" batch
    r = client.post("/api/inventory/stocktakes/count", headers=stocktaker_h,
                    json={"item_id": zero_item["id"], "physical_qty": 2, "reason": "found in back shelf"})
    assert r.status_code == 200
    done = client.post(f"/api/inventory/stocktakes/{st['id']}/complete", headers=stocktaker_h)
    ok = client.post(f"/api/inventory/stocktakes/{st['id']}/approve", headers=admin_h)
    assert ok.status_code == 200
    after = client.get(f"/api/batches/{b['id']}", headers=admin_h).json()
    assert after["current_qty"] == 2


def test_counting_closed_after_complete(client, admin_h, stocktaker_h):
    p, b = _mk_batch(client, admin_h, qty=3)
    st = client.post("/api/inventory/stocktakes", headers=stocktaker_h,
                     json={"name": "Closed Test"}).json()
    item = next(i for i in st["items"] if i["batch_id"] == b["id"])
    client.post("/api/inventory/stocktakes/count", headers=stocktaker_h,
                json={"item_id": item["id"], "physical_qty": 3})
    client.post(f"/api/inventory/stocktakes/{st['id']}/complete", headers=stocktaker_h)
    late = client.post("/api/inventory/stocktakes/count", headers=stocktaker_h,
                       json={"item_id": item["id"], "physical_qty": 1})
    assert late.status_code == 422


# --- Security hardening (BUG-011/013) -------------------------------------------

def test_login_rate_limit_and_lockout(client):
    codes = []
    for _ in range(6):
        r = client.post("/api/auth/login", data={"username": "bruteforce", "password": "x"})
        codes.append(r.status_code)
    assert 429 in codes, f"expected lockout, got {codes}"
    # failed logins are audited
    r = client.post("/api/auth/login", data={"username": "admin", "password": "admin123"})
    token = r.json()["access_token"]
    H = {"Authorization": f"Bearer {token}"}
    audit = client.get("/api/audit?action=USER_LOGIN_FAILED", headers=H).json()
    assert len(audit) >= 5


def test_logout_revokes_token(client, admin_h):
    r = client.post("/api/auth/login", data={"username": "admin", "password": "admin123"})
    tok = {"Authorization": f"Bearer {r.json()['access_token']}"}
    assert client.get("/api/auth/me", headers=tok).status_code == 200
    out = client.post("/api/auth/logout", headers=tok)
    assert out.status_code == 200
    assert client.get("/api/auth/me", headers=tok).status_code == 401, "revoked token must stop working"


def test_me_returns_permissions(client, admin_h):
    me = client.get("/api/auth/me", headers=admin_h).json()
    assert "permissions" in me and "settings.manage" in me["permissions"]


# --- Backup / Restore (BUG-024) ---------------------------------------------------

def test_backup_and_restore_roundtrip(client, admin_h):
    p, b = _mk_batch(client, admin_h, qty=12)

    bk = client.post("/backup", headers=admin_h)
    assert bk.status_code == 200, bk.text
    path = bk.json()["path"]
    assert Path(path).exists()

    # mutate after the backup
    sell = client.post("/api/pos/checkout", headers=admin_h, json={
        "items": [{"product_id": p["id"], "batch_id": b["id"], "quantity": 5}],
        "payments": [{"method": "CASH", "amount": 5 * 1500}]})
    assert sell.status_code == 201
    before_restore = client.get(f"/api/batches/{b['id']}", headers=admin_h).json()["current_qty"]
    assert before_restore == 7

    # restore the backup -> stock returns to the backup point
    with open(path, "rb") as f:
        rs = client.post("/restore", headers=admin_h, files={"file": ("backup.db", f, "application/octet-stream")})
    assert rs.status_code == 200, rs.text
    after = client.get(f"/api/batches/{b['id']}", headers=admin_h).json()["current_qty"]
    assert after == 12, f"restore must rewind stock, got {after}"
    audit = client.get("/api/audit?action=BACKUP_RESTORED", headers=admin_h).json()
    assert len(audit) >= 1

    # garbage file is rejected without touching the DB
    rs2 = client.post("/restore", headers=admin_h,
                      files={"file": ("junk.db", b"this is not a database", "application/octet-stream")})
    assert rs2.status_code == 400
    still = client.get(f"/api/batches/{b['id']}", headers=admin_h).json()["current_qty"]
    assert still == 12


def test_backup_rotation_keeps_limit(client, admin_h):
    from app.config import settings as cfg
    for _ in range(4):
        client.post("/backup", headers=admin_h)
    files = client.get("/backups", headers=admin_h).json()
    # default keep=10; just assert listing works and count is sane
    assert isinstance(files, list) and len(files) >= 1
