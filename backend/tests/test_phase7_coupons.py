"""Phase-7: coupon & campaign engine (§31–38)."""
from datetime import datetime, timedelta
from decimal import Decimal

import pytest


@pytest.fixture()
def stocked(client, auth_headers):
    """A product with plenty of stock at 100,000 each."""
    r = client.post("/api/products", headers=auth_headers,
                    json={"barcode": "6261111100001", "name": "کالای کوپن"})
    if r.status_code == 409:
        r = client.get("/api/products/barcode/6261111100001", headers=auth_headers)
        product = r.json()
    else:
        product = r.json()
    b = client.post("/api/batches/receive", headers=auth_headers, json={
        "product_id": product["id"], "quantity_received": 500, "buy_price": 60000,
        "sell_price": 100000}).json()
    return product, b


def _mk_coupon(client, headers, **kw):
    body = {"discount_type": "PERCENT", "discount_value": 10, "usage_limit": 1}
    body.update(kw)
    r = client.post("/api/marketing/coupons", headers=headers, json=body)
    assert r.status_code == 201, r.text
    return r.json()


def test_percentage_coupon_capped_by_max_discount(client, auth_headers):
    c = _mk_coupon(client, auth_headers, discount_value=10, max_discount=1000000)
    r = client.post("/api/marketing/coupons/validate", headers=auth_headers,
                    json={"code": c["code"], "amount": 50000000})
    assert r.status_code == 200, r.text
    # 10% of 50,000,000 = 5,000,000 -> capped to 1,000,000 (§34)
    assert Decimal(str(r.json()["discount"])) == Decimal("1000000")


def test_minimum_purchase_condition(client, auth_headers):
    c = _mk_coupon(client, auth_headers, discount_value=10, min_purchase=400000)
    low = client.post("/api/marketing/coupons/validate", headers=auth_headers,
                      json={"code": c["code"], "amount": 300000})
    assert low.status_code == 422
    assert low.json()["detail"]["code"] == "MIN_PURCHASE_NOT_MET"

    ok = client.post("/api/marketing/coupons/validate", headers=auth_headers,
                     json={"code": c["code"], "amount": 500000})
    assert ok.status_code == 200
    assert Decimal(str(ok.json()["discount"])) == Decimal("50000")


def test_fixed_amount_coupon(client, auth_headers):
    c = _mk_coupon(client, auth_headers, discount_type="FIXED", discount_value=100000)
    r = client.post("/api/marketing/coupons/validate", headers=auth_headers,
                    json={"code": c["code"], "amount": 500000})
    assert Decimal(str(r.json()["discount"])) == Decimal("100000")


def test_coupon_applied_at_checkout_and_cannot_be_reused(client, auth_headers, stocked):
    product, batch = stocked
    c = _mk_coupon(client, auth_headers, discount_value=10, usage_limit=1)

    # cart of 300,000 -> 10% = 30,000 discount -> pay 270,000
    r = client.post("/api/pos/checkout", headers=auth_headers, json={
        "items": [{"product_id": product["id"], "batch_id": batch["id"], "quantity": 3}],
        "payments": [{"method": "CASH", "amount": 270000}],
        "coupon_code": c["code"]})
    assert r.status_code == 201, r.text
    body = r.json()
    assert Decimal(str(body["discount"])) == Decimal("30000")
    assert Decimal(str(body["total_amount"])) == Decimal("270000")

    after = client.get("/api/marketing/coupons", headers=auth_headers,
                       params={"q": c["code"]}).json()[0]
    assert after["used_count"] == 1
    assert after["status"] == "USED"

    # second attempt must be rejected (§38)
    again = client.post("/api/pos/checkout", headers=auth_headers, json={
        "items": [{"product_id": product["id"], "batch_id": batch["id"], "quantity": 3}],
        "payments": [{"method": "CASH", "amount": 270000}],
        "coupon_code": c["code"]})
    assert again.status_code == 422
    assert again.json()["detail"]["code"] == "COUPON_USED"


def test_multi_use_coupon_respects_limit(client, auth_headers, stocked):
    product, batch = stocked
    c = _mk_coupon(client, auth_headers, discount_type="FIXED",
                   discount_value=10000, usage_limit=2)
    for _ in range(2):
        r = client.post("/api/pos/checkout", headers=auth_headers, json={
            "items": [{"product_id": product["id"], "batch_id": batch["id"], "quantity": 1}],
            "payments": [{"method": "CASH", "amount": 90000}],
            "coupon_code": c["code"]})
        assert r.status_code == 201, r.text
    third = client.post("/api/pos/checkout", headers=auth_headers, json={
        "items": [{"product_id": product["id"], "batch_id": batch["id"], "quantity": 1}],
        "payments": [{"method": "CASH", "amount": 90000}],
        "coupon_code": c["code"]})
    assert third.status_code == 422
    assert third.json()["detail"]["code"] in ("COUPON_USED", "COUPON_LIMIT_REACHED")


def test_failed_checkout_does_not_burn_the_coupon(client, auth_headers, stocked):
    """The coupon is consumed inside the sale transaction — a rejected sale
    (payment mismatch) must roll it back."""
    product, batch = stocked
    c = _mk_coupon(client, auth_headers, discount_value=10)
    bad = client.post("/api/pos/checkout", headers=auth_headers, json={
        "items": [{"product_id": product["id"], "batch_id": batch["id"], "quantity": 3}],
        "payments": [{"method": "CASH", "amount": 999}],  # wrong amount
        "coupon_code": c["code"]})
    assert bad.status_code == 422
    row = client.get("/api/marketing/coupons", headers=auth_headers,
                     params={"q": c["code"]}).json()[0]
    assert row["used_count"] == 0 and row["status"] == "ACTIVE"


def test_customer_specific_coupon(client, auth_headers, stocked):
    product, batch = stocked
    cust = client.post("/api/customers", headers=auth_headers,
                       json={"name": "علی", "phone": "09120000001"}).json()
    other = client.post("/api/customers", headers=auth_headers,
                        json={"name": "رضا", "phone": "09120000002"}).json()
    c = _mk_coupon(client, auth_headers, discount_value=10, customer_id=cust["id"])

    denied = client.post("/api/marketing/coupons/validate", headers=auth_headers,
                         json={"code": c["code"], "amount": 300000,
                               "customer_id": other["id"]})
    assert denied.status_code == 422
    assert denied.json()["detail"]["code"] == "COUPON_NOT_YOURS"

    ok = client.post("/api/marketing/coupons/validate", headers=auth_headers,
                     json={"code": c["code"], "amount": 300000, "customer_id": cust["id"]})
    assert ok.status_code == 200


def test_expired_and_blocked_coupons(client, auth_headers):
    past = (datetime.utcnow() - timedelta(days=1)).isoformat()
    expired = _mk_coupon(client, auth_headers, discount_value=10, valid_until=past)
    r = client.post("/api/marketing/coupons/validate", headers=auth_headers,
                    json={"code": expired["code"], "amount": 500000})
    assert r.json()["detail"]["code"] == "COUPON_EXPIRED"

    blocked = _mk_coupon(client, auth_headers, discount_value=10)
    client.post(f"/api/marketing/coupons/{blocked['id']}/block", headers=auth_headers)
    r2 = client.post("/api/marketing/coupons/validate", headers=auth_headers,
                     json={"code": blocked["code"], "amount": 500000})
    assert r2.json()["detail"]["code"] == "COUPON_BLOCKED"


def test_next_purchase_coupon_is_auto_issued(client, auth_headers, stocked):
    """§36: a campaign threshold issues a coupon for the customer's NEXT visit."""
    product, batch = stocked
    camp = client.post("/api/marketing/campaigns", headers=auth_headers, json={
        "name": "جشنواره پاییز", "discount_type": "PERCENT", "discount_value": 10,
        "min_purchase": 400000, "max_discount": 1000000,
        "auto_issue_threshold": 1000000, "auto_issue_validity_days": 30})
    assert camp.status_code == 201, camp.text

    cust = client.post("/api/customers", headers=auth_headers,
                       json={"name": "مشتری وفادار", "phone": "09121110000"}).json()
    r = client.post("/api/pos/checkout", headers=auth_headers, json={
        "items": [{"product_id": product["id"], "batch_id": batch["id"], "quantity": 15}],
        "payments": [{"method": "CASH", "amount": 1500000}],
        "customer_id": cust["id"]})
    assert r.status_code == 201, r.text
    issued = r.json()["issued_coupon"]
    assert issued and issued["code"].startswith("NEXT-")

    # the issued coupon works on a following purchase above its minimum
    nxt = client.post("/api/marketing/coupons/validate", headers=auth_headers,
                      json={"code": issued["code"], "amount": 500000,
                            "customer_id": cust["id"]})
    assert nxt.status_code == 200
    assert Decimal(str(nxt.json()["discount"])) == Decimal("50000")


def test_coupon_sms_is_queued_for_the_customer(client, auth_headers, stocked):
    product, batch = stocked
    cust = client.post("/api/customers", headers=auth_headers,
                       json={"name": "پیامکی", "phone": "09121112222"}).json()
    r = client.post("/api/pos/checkout", headers=auth_headers, json={
        "items": [{"product_id": product["id"], "batch_id": batch["id"], "quantity": 1}],
        "payments": [{"method": "CASH", "amount": 100000}],
        "customer_id": cust["id"]})
    assert r.status_code == 201
    invoice_id = r.json()["invoice_id"]
    msgs = client.get("/api/sms", headers=auth_headers).json()
    mine = [m for m in msgs if m.get("phone") == "09121112222"]
    assert mine, "invoice SMS was not queued"
    jobs = client.get("/api/diagnostics/sync/jobs", headers=auth_headers).json()
    assert any(j["job_type"] == "SMS" for j in jobs)


def test_checkout_creates_customer_from_phone_only(client, auth_headers, stocked):
    """§30: a bare phone number is enough to create/attach a customer."""
    product, batch = stocked
    r = client.post("/api/pos/checkout", headers=auth_headers, json={
        "items": [{"product_id": product["id"], "batch_id": batch["id"], "quantity": 1}],
        "payments": [{"method": "CASH", "amount": 100000}],
        "customer_phone": "09129998888"})
    assert r.status_code == 201, r.text
    found = client.get("/api/customers/phone/09129998888", headers=auth_headers)
    assert found.status_code == 200
