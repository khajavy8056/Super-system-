"""Phase-9: customer credit accounts / دفتر حساب مشتری (§30–35).

These tests exercise the accounting invariants, not just the happy path:
the ledger must stay append-only, the balance must always equal the sum of
its own history, and a failed sale must never leave a debt behind.
"""
from decimal import Decimal
from uuid import uuid4

import pytest

# The `client` fixture is session-scoped against ONE shared SQLite database and
# customer creation is idempotent by phone, so a hardcoded number can silently
# return another test file's customer. Every phone here is unique per run.
_seq = 0


def _phone() -> str:
    return "0939" + uuid4().hex[:7]


@pytest.fixture()
def customer(client, auth_headers):
    global _seq
    _seq += 1
    r = client.post("/api/customers", headers=auth_headers, json={
        "name": "محمد", "last_name": "رضایی",
        "phone": _phone(), "address": "تهران، خیابان ولیعصر",
        "credit_limit": 5_000_000})
    assert r.status_code == 201, r.text
    return r.json()


@pytest.fixture()
def product(client, auth_headers):
    global _seq
    _seq += 1
    p = client.post("/api/products", headers=auth_headers, json={
        "barcode": f"6269{_seq:03d}00007", "name": f"کالای نسیه {_seq}"}).json()
    client.post("/api/batches/receive", headers=auth_headers, json={
        "product_id": p["id"], "quantity_received": 100,
        "buy_price": 50_000, "sell_price": 80_000})
    return p


def _sell_on_account(client, auth_headers, product, customer, qty=2):
    """Checkout paying entirely with the ACCOUNT tender."""
    total = 80_000 * qty
    return client.post("/api/pos/checkout", headers=auth_headers, json={
        "items": [{"product_id": product["id"], "quantity": qty}],
        "payments": [{"method": "ACCOUNT", "amount": total}],
        "customer_id": customer["id"]})


# --------------------------------------------------------------------------
# profile (§30, §42)
# --------------------------------------------------------------------------
def test_customer_profile_holds_the_full_record(client, auth_headers, customer):
    got = client.get(f"/api/customers/{customer['id']}", headers=auth_headers).json()
    assert got["last_name"] == "رضایی"
    assert got["address"] == "تهران، خیابان ولیعصر"
    assert got["credit_enabled"] is True
    assert Decimal(str(got["balance"])) == 0


def test_customer_can_be_registered_with_only_a_phone(client, auth_headers):
    """§42: a number with no name must still be storable."""
    phone = _phone()
    r = client.post("/api/customers", headers=auth_headers,
                    json={"name": "", "phone": phone})
    assert r.status_code == 201, r.text
    assert r.json()["phone"] == phone


def test_creating_the_same_phone_twice_is_idempotent(client, auth_headers):
    phone = _phone()
    a = client.post("/api/customers", headers=auth_headers,
                    json={"name": "علی", "phone": phone}).json()
    b = client.post("/api/customers", headers=auth_headers,
                    json={"name": "علی دوم", "phone": phone}).json()
    assert a["id"] == b["id"], "duplicate phone must not create a second account"


# --------------------------------------------------------------------------
# selling on account (§34)
# --------------------------------------------------------------------------
def test_sale_on_account_creates_debt_and_marks_invoice_unpaid(
        client, auth_headers, product, customer):
    r = _sell_on_account(client, auth_headers, product, customer, qty=2)
    assert r.status_code in (200, 201), r.text
    inv = r.json()
    assert inv["payment_status"] == "ON_ACCOUNT"

    stmt = client.get(f"/api/customers/{customer['id']}/ledger",
                      headers=auth_headers).json()
    assert Decimal(str(stmt["balance"])) == 160_000
    assert stmt["entries"][0]["entry_type"] == "CREDIT_SALE"
    assert stmt["entries"][0]["invoice_id"] == inv["invoice_id"]


def test_walk_in_customer_cannot_buy_on_account(client, auth_headers, product):
    """§34: the 'add to account' option must not exist for مشتری آزاد."""
    r = client.post("/api/pos/checkout", headers=auth_headers, json={
        "items": [{"product_id": product["id"], "quantity": 1}],
        "payments": [{"method": "ACCOUNT", "amount": 80_000}]})
    assert r.status_code in (400, 409, 422)
    assert "ACCOUNT_REQUIRES_CUSTOMER" in r.text


def test_cash_sale_to_registered_customer_creates_no_debt(
        client, auth_headers, product, customer):
    r = client.post("/api/pos/checkout", headers=auth_headers, json={
        "items": [{"product_id": product["id"], "quantity": 1}],
        "payments": [{"method": "CASH", "amount": 80_000}],
        "customer_id": customer["id"]})
    assert r.status_code in (200, 201), r.text
    assert r.json()["payment_status"] == "PAID"
    bal = client.get(f"/api/customers/{customer['id']}",
                     headers=auth_headers).json()["balance"]
    assert Decimal(str(bal)) == 0


def test_credit_limit_is_enforced(client, auth_headers, product):
    small = client.post("/api/customers", headers=auth_headers, json={
        "name": "سقف کم", "phone": _phone(), "credit_limit": 100_000}).json()
    r = client.post("/api/pos/checkout", headers=auth_headers, json={
        "items": [{"product_id": product["id"], "quantity": 5}],  # 400,000
        "payments": [{"method": "ACCOUNT", "amount": 400_000}],
        "customer_id": small["id"]})
    assert r.status_code in (400, 409, 422)
    assert "CREDIT_LIMIT_EXCEEDED" in r.text
    # and crucially: the rejected sale left no debt behind
    bal = client.get(f"/api/customers/{small['id']}",
                     headers=auth_headers).json()["balance"]
    assert Decimal(str(bal)) == 0


def test_failed_checkout_does_not_create_a_debt(client, auth_headers, customer, product):
    """A sale that fails after the ledger step must roll the debt back."""
    before = client.get(f"/api/customers/{customer['id']}",
                        headers=auth_headers).json()["balance"]
    r = client.post("/api/pos/checkout", headers=auth_headers, json={
        "items": [{"product_id": product["id"], "quantity": 999999}],  # no stock
        "payments": [{"method": "ACCOUNT", "amount": 1}],
        "customer_id": customer["id"]})
    assert r.status_code >= 400
    after = client.get(f"/api/customers/{customer['id']}",
                       headers=auth_headers).json()["balance"]
    assert Decimal(str(after)) == Decimal(str(before))


# --------------------------------------------------------------------------
# settlement (§32)
# --------------------------------------------------------------------------
def test_partial_then_full_settlement(client, auth_headers, product, customer):
    _sell_on_account(client, auth_headers, product, customer, qty=2)  # 160,000

    part = client.post(f"/api/customers/{customer['id']}/settle",
                       headers=auth_headers,
                       json={"amount": 60_000, "method": "CASH"})
    assert part.status_code == 200, part.text
    assert Decimal(str(part.json()["balance"])) == 100_000
    assert part.json()["settled_in_full"] is False

    rest = client.post(f"/api/customers/{customer['id']}/settle",
                       headers=auth_headers, json={"method": "CARD"})
    assert rest.status_code == 200, rest.text
    assert Decimal(str(rest.json()["balance"])) == 0
    assert rest.json()["settled_in_full"] is True


def test_overpayment_is_rejected(client, auth_headers, product, customer):
    _sell_on_account(client, auth_headers, product, customer, qty=1)  # 80,000
    r = client.post(f"/api/customers/{customer['id']}/settle",
                    headers=auth_headers, json={"amount": 500_000})
    assert r.status_code == 422
    assert "OVERPAYMENT" in r.text


def test_settling_with_no_debt_is_rejected(client, auth_headers, customer):
    r = client.post(f"/api/customers/{customer['id']}/settle",
                    headers=auth_headers, json={})
    assert r.status_code == 409
    assert "NO_DEBT" in r.text


# --------------------------------------------------------------------------
# ledger integrity (the reason this module exists)
# --------------------------------------------------------------------------
def test_balance_always_equals_the_sum_of_its_own_history(
        client, auth_headers, product, customer):
    _sell_on_account(client, auth_headers, product, customer, qty=3)   # +240,000
    client.post(f"/api/customers/{customer['id']}/settle",
                headers=auth_headers, json={"amount": 40_000})          # -40,000
    _sell_on_account(client, auth_headers, product, customer, qty=1)   # +80,000
    client.post(f"/api/customers/{customer['id']}/settle",
                headers=auth_headers, json={"amount": 80_000})          # -80,000

    stmt = client.get(f"/api/customers/{customer['id']}/ledger",
                      headers=auth_headers).json()
    assert Decimal(str(stmt["balance"])) == 200_000

    replayed = sum(Decimal(str(e["amount"])) for e in stmt["entries"])
    assert replayed == Decimal(str(stmt["balance"]))

    verify = client.get(f"/api/customers/{customer['id']}/ledger/verify",
                        headers=auth_headers).json()
    assert verify["ok"] is True, verify["mismatches"]
    assert Decimal(str(verify["computed_balance"])) == 200_000


def test_corrections_are_reversing_entries_not_edits(
        client, auth_headers, product, customer):
    _sell_on_account(client, auth_headers, product, customer, qty=1)
    before = client.get(f"/api/customers/{customer['id']}/ledger",
                        headers=auth_headers).json()

    r = client.post(f"/api/customers/{customer['id']}/ledger/adjust",
                    headers=auth_headers,
                    json={"entry_type": "ADJUSTMENT_CREDIT", "amount": 30_000,
                          "note": "تخفیف توافقی"})
    assert r.status_code == 200, r.text

    after = client.get(f"/api/customers/{customer['id']}/ledger",
                       headers=auth_headers).json()
    assert len(after["entries"]) == len(before["entries"]) + 1, "history must grow"
    assert Decimal(str(after["balance"])) == 50_000
    # the original sale row is still present, untouched
    original = [e for e in after["entries"] if e["entry_type"] == "CREDIT_SALE"]
    assert original and Decimal(str(original[0]["amount"])) == 80_000


def test_statement_totals_and_history(client, auth_headers, product, customer):
    _sell_on_account(client, auth_headers, product, customer, qty=2)
    client.post(f"/api/customers/{customer['id']}/settle",
                headers=auth_headers, json={"amount": 50_000})
    stmt = client.get(f"/api/customers/{customer['id']}/ledger",
                      headers=auth_headers).json()
    assert Decimal(str(stmt["total_charged"])) == 160_000
    assert Decimal(str(stmt["total_paid"])) == 50_000
    assert stmt["customer"]["phone"] == customer["phone"]


def test_invoice_history_is_linked_to_the_customer(
        client, auth_headers, product, customer):
    _sell_on_account(client, auth_headers, product, customer, qty=1)
    rows = client.get(f"/api/customers/{customer['id']}/invoices",
                      headers=auth_headers).json()
    assert rows and rows[0]["payment_status"] == "ON_ACCOUNT"


# --------------------------------------------------------------------------
# debtor list drives SMS reminders (§35)
# --------------------------------------------------------------------------
def test_debtors_list_only_returns_real_debt(client, auth_headers, product, customer):
    _sell_on_account(client, auth_headers, product, customer, qty=2)
    debtors = client.get("/api/customers/debtors", headers=auth_headers).json()
    mine = [d for d in debtors if d["customer_id"] == customer["id"]]
    assert mine and Decimal(str(mine[0]["balance"])) == 160_000
    assert mine[0]["phone"] == customer["phone"]

    client.post(f"/api/customers/{customer['id']}/settle",
                headers=auth_headers, json={})
    after = client.get("/api/customers/debtors", headers=auth_headers).json()
    assert not [d for d in after if d["customer_id"] == customer["id"]], \
        "a settled customer must drop off the reminder list"
