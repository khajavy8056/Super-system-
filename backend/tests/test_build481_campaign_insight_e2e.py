# -*- coding: utf-8 -*-
"""build-481 — the mandatory end-to-end scenarios (steps 38–39 of the campaign/intelligence audit).

What is pinned here is the *shape* the owner asked for:

    Insight → Action → real Business Operation → Result → Verification → Resolve

plus the campaign journey (create → activate → purchase → benefit → invoice →
audit), the future-burchase benefit on the customer profile, cashier-selected
festivals at the till, auto-resolution when the manager fixes things elsewhere,
merging similar customer suggestions into one updating card, idempotent actions,
and Persian product search without a scanner.

Every scenario drives the REAL API and asserts the side effect in the data —
never just ``ok: True``.
"""
from __future__ import annotations

import itertools

import pytest

_seq = itertools.count(1)


@pytest.fixture(autouse=True)
def no_leaky_benefits():
    """Shared-DB hygiene: festivals/coupons created here must not discount later tests.

    The suite runs against one shared store; an auto-apply campaign left ACTIVE
    silently discounts every later basket above its threshold (exactly the class
    of cross-test breakage found with flash_sale earlier). Snapshot the marketing
    tables around every test and remove whatever this test added.
    """
    from app.database import SessionLocal
    from app.models import (Campaign, CampaignRedemption, Coupon, CouponRedemption,
                            SyncJob, SmsMessage)
    from sqlalchemy import select

    def _snap():
        with SessionLocal() as db:
            return ({c.id for c in db.execute(select(Campaign)).scalars().all()},
                    {c.id for c in db.execute(select(Coupon)).scalars().all()},
                    {m.id for m in db.execute(select(SmsMessage)).scalars().all()})

    camps_before, coupons_before, sms_before = _snap()
    yield
    with SessionLocal() as db:
        for red in db.execute(select(CampaignRedemption)).scalars().all():
            if red.campaign_id not in camps_before:
                db.delete(red)
        for red in db.execute(select(CouponRedemption)).scalars().all():
            if red.coupon_id not in coupons_before:
                db.delete(red)
        for c in db.execute(select(Campaign)).scalars().all():
            if c.id not in camps_before:
                db.delete(c)
        for c in db.execute(select(Coupon)).scalars().all():
            if c.id not in coupons_before:
                db.delete(c)
        # Leftover PENDING invoice-SMS rows would crowd the shared outbox that a
        # later test drains (20-row window) — take this test's messages out too.
        for m in db.execute(select(SmsMessage)).scalars().all():
            if m.id not in sms_before:
                db.delete(m)
        for j in db.execute(select(SyncJob)).scalars().all():
            if j.job_type == "SMS" and j.reference_type == "Invoice":
                db.delete(j)
        db.commit()


# --------------------------------------------------------------------------- helpers
def _product(client, auth_headers, name=None, barcode=None):
    n = next(_seq)
    r = client.post("/api/products", json={
        "barcode": barcode or f"62699180{n:05d}",
        "name": name or f"Build481 Goods {n}"}, headers=auth_headers)
    assert r.status_code == 201, r.text
    return r.json()


def _receive(client, auth_headers, pid, qty=500, buy=8000, sell=12000, expiry=None):
    body = {"product_id": pid, "quantity_received": qty, "buy_price": buy, "sell_price": sell}
    if expiry:
        body["expiry_date"] = expiry
    r = client.post("/api/batches/receive", headers=auth_headers, json=body)
    assert r.status_code == 201, r.text
    return r.json()


def _customer(client, auth_headers, name=None, phone=None):
    n = next(_seq)
    r = client.post("/api/customers", headers=auth_headers, json={
        "name": name or f"Build481 Cust {n}", "phone": phone or f"09124810{n:04d}"})
    assert r.status_code == 201, r.text
    return r.json()


def _buy(client, auth_headers, pid, qty, amount, customer_id=None, campaign_id=None, coupon=None):
    body = {"items": [{"product_id": pid, "quantity": qty}],
            "payments": [{"method": "CASH", "amount": amount}]}
    if customer_id:
        body["customer_id"] = customer_id
    if campaign_id:
        body["campaign_id"] = campaign_id
    if coupon:
        body["coupon_code"] = coupon
    return client.post("/api/pos/checkout", headers=auth_headers, json=body)


def _backdate_invoices(client, auth_headers, customer_id, days_ago_list):
    """Give a customer the past the analyzers need (the API always sells «now»)."""
    from app.database import SessionLocal
    from app.models import Invoice
    from sqlalchemy import select
    from datetime import datetime, timedelta

    with SessionLocal() as db:
        rows = db.execute(select(Invoice).where(Invoice.customer_id == customer_id)
                          .order_by(Invoice.id.desc())).scalars().all()
        for inv, days in zip(rows, days_ago_list):
            inv.created_at = datetime.utcnow() - timedelta(days=days)
        db.commit()


# =========================================================================== §21-26 — campaign at the till
def test_threshold_campaign_auto_applies_at_checkout(client, auth_headers):
    """§21: «خرید بالای X → تخفیف» must really reach the invoice — or not apply at all."""
    from app.database import SessionLocal
    from app.models import Campaign, CampaignRedemption, Invoice
    from sqlalchemy import select

    p = _product(client, auth_headers)
    _receive(client, auth_headers, p["id"], qty=100, buy=8000, sell=10000)
    r = client.post("/api/marketing/campaigns", headers=auth_headers, json={
        "name": "جشنواره آستانه ۴۸۱", "discount_type": "PERCENT", "discount_value": 20,
        "min_purchase": 400000, "auto_apply": True, "usage_limit": 50})
    assert r.status_code == 201, r.text
    camp = r.json()

    # below the threshold → the festival must NOT touch the sale
    r1 = _buy(client, auth_headers, p["id"], qty=1, amount=10000)
    assert r1.status_code == 201, r1.text
    assert r1.json()["benefit_source"] == "NONE"
    assert float(r1.json()["benefit_amount"]) == 0.0

    # at/above the threshold → real benefit, snapshot + redemption + audit
    # gross = 50 × 10,000 = 500,000 → 20% benefit = 100,000 → pay 400,000
    r2 = _buy(client, auth_headers, p["id"], qty=50, amount=400000)
    assert r2.status_code == 201, r2.text
    inv = r2.json()
    assert inv["campaign_id"] == camp["id"]
    assert inv["campaign_name"] == "جشنواره آستانه ۴۸۱"     # snapshot, not a live link
    assert inv["benefit_source"] == "CAMPAIGN"
    assert float(inv["benefit_amount"]) == 100000.0          # 20% of the 500,000 basket
    assert float(inv["discount"]) >= 100000.0

    with SessionLocal() as db:
        reds = db.execute(select(CampaignRedemption).where(CampaignRedemption.campaign_id == camp["id"])).scalars().all()
        assert len(reds) == 1 and float(reds[0].amount) == 100000.0 and reds[0].invoice_id == inv["invoice_id"]
        row = db.get(Campaign, camp["id"])
        assert (row.used_count or 0) == 1
        from app.models import AuditLog
        logs = db.execute(select(AuditLog).where(AuditLog.action == "CAMPAIGN_APPLIED")).scalars().all()
        assert logs, "applying a festival must be audited (who/what/when)"


def test_cashier_selects_campaign_and_server_revalidates(client, auth_headers):
    """§24–25: the POS list is structured and honest; checkout re-checks every condition."""
    p = _product(client, auth_headers)
    _receive(client, auth_headers, p["id"], qty=100, buy=8000, sell=10000)

    ok_c = client.post("/api/marketing/campaigns", headers=auth_headers, json={
        "name": "جشنواره انتخابی", "discount_type": "FIXED", "discount_value": 5000,
        "min_purchase": 5000, "auto_apply": False}).json()
    high_c = client.post("/api/marketing/campaigns", headers=auth_headers, json={
        "name": "حداقل دست‌نیافتنی", "discount_type": "PERCENT", "discount_value": 50,
        "min_purchase": 90000000, "auto_apply": False}).json()
    paused = client.post("/api/marketing/campaigns", headers=auth_headers, json={
        "name": "متوقف", "discount_type": "PERCENT", "discount_value": 90,
        "min_purchase": 0, "status": "PAUSED"}).json()

    r = client.post("/api/pos/campaigns/eligible", headers=auth_headers,
                    json={"amount": 20000, "product_ids": [p["id"]], "include_auto_apply": False})
    assert r.status_code == 200, r.text
    ids = {c["campaign_id"] for c in r.json()["campaigns"]}
    assert ok_c["id"] in ids
    assert high_c["id"] not in ids, "a campaign whose condition does not hold must not be offered"
    assert paused["id"] not in ids, "a PAUSED campaign must never reach the cashier list"

    # select it → benefit lands on the invoice, counted and audited
    r2 = _buy(client, auth_headers, p["id"], qty=2, amount=15000, campaign_id=ok_c["id"])
    assert r2.status_code == 201, r2.text
    assert r2.json()["campaign_name"] == "جشنواره انتخابی"
    assert float(r2.json()["benefit_amount"]) == 5000.0

    # a PAUSED campaign cannot be forced through the checkout either
    r3 = _buy(client, auth_headers, p["id"], qty=1, amount=10000, campaign_id=paused["id"])
    assert r3.status_code == 422
    assert r3.json()["detail"]["code"] == "CAMPAIGN_INACTIVE"


def test_campaign_edit_never_rewrites_history(client, auth_headers):
    """§22: an edited festival changes the future; past invoices keep their snapshot."""
    p = _product(client, auth_headers)
    _receive(client, auth_headers, p["id"], qty=50, buy=8000, sell=10000)
    c = client.post("/api/marketing/campaigns", headers=auth_headers, json={
        "name": "نام قدیمی", "discount_type": "PERCENT", "discount_value": 10,
        "min_purchase": 0, "auto_apply": False}).json()

    r = _buy(client, auth_headers, p["id"], qty=2, amount=18000, campaign_id=c["id"])  # 20,000 − 10%
    assert r.status_code == 201, r.text
    inv_id = r.json()["invoice_id"]

    upd = client.patch(f"/api/marketing/campaigns/{c['id']}", headers=auth_headers, json={
        "name": "نام جدید", "discount_type": "PERCENT", "discount_value": 3,
        "min_purchase": 0, "status": "ACTIVE"})
    assert upd.status_code == 200, upd.text

    got = client.get(f"/api/invoices/{inv_id}", headers=auth_headers)
    if got.status_code == 200:
        body = got.json()
        assert body.get("campaign_name") == "نام قدیمی", "editing a campaign must not rewrite receipts"
    else:  # invoice detail shape differs — check via the service layer
        from app.database import SessionLocal
        from app.models import Invoice
        with SessionLocal() as db:
            assert db.get(Invoice, inv_id).campaign_name == "نام قدیمی"


def test_campaign_usage_limits_are_enforced(client, auth_headers):
    """§23/§25: total and per-customer slots can never be exceeded — by anyone."""
    p = _product(client, auth_headers)
    _receive(client, auth_headers, p["id"], qty=50, buy=8000, sell=10000)
    c = client.post("/api/marketing/campaigns", headers=auth_headers, json={
        "name": "سقف‌دار ۴۸۱", "discount_type": "FIXED", "discount_value": 1000,
        "min_purchase": 0, "auto_apply": False, "usage_limit": 1}).json()

    r1 = _buy(client, auth_headers, p["id"], qty=1, amount=9000, campaign_id=c["id"])   # 10,000 − 1,000
    assert r1.status_code == 201, r1.text
    r2 = _buy(client, auth_headers, p["id"], qty=1, amount=9000, campaign_id=c["id"])
    assert r2.status_code == 422
    assert r2.json()["detail"]["code"] in ("CAMPAIGN_LIMIT_REACHED", "CAMPAIGN_CUSTOMER_LIMIT")


def test_non_stackable_campaign_rejects_a_coupon(client, auth_headers):
    p = _product(client, auth_headers)
    _receive(client, auth_headers, p["id"], qty=50, buy=8000, sell=10000)
    c = client.post("/api/marketing/campaigns", headers=auth_headers, json={
        "name": "غیرقابل‌ترکیب", "discount_type": "PERCENT", "discount_value": 5,
        "min_purchase": 0, "auto_apply": False, "stackable": False}).json()
    cp = client.post("/api/marketing/coupons", headers=auth_headers, json={
        "discount_type": "PERCENT", "discount_value": 5, "min_purchase": 0}).json()

    r = _buy(client, auth_headers, p["id"], qty=2, amount=15000,
             campaign_id=c["id"], coupon=cp["code"])
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "CAMPAIGN_NOT_STACKABLE"


# =========================================================================== §27-29 — future purchase benefit
def test_future_purchase_benefit_customer_profile_and_sms(client, auth_headers):
    """Purchase #1 → future benefit on the profile → Purchase #2 uses it → SMS trail."""
    from app.database import SessionLocal
    from app.models import Coupon, SmsMessage
    from sqlalchemy import select

    p = _product(client, auth_headers)
    _receive(client, auth_headers, p["id"], qty=100, buy=8000, sell=10000)
    camp = client.post("/api/marketing/campaigns", headers=auth_headers, json={
        "name": "مزیت خرید بعدی ۴۸۱", "discount_type": "PERCENT", "discount_value": 20,
        "min_purchase": 300000, "auto_issue_threshold": 100000,
        "auto_issue_validity_days": 14, "auto_issue_sms": True}).json()
    cust = _customer(client, auth_headers)

    r1 = _buy(client, auth_headers, p["id"], qty=10, amount=100000, customer_id=cust["id"])
    assert r1.status_code == 201, r1.text
    issued = r1.json()["issued_coupon"]
    assert issued and issued["code"].startswith("NEXT-"), "the future benefit must be issued at checkout"

    # the customer profile shows it as a real, conditional benefit (§28)
    ben = client.get(f"/api/customers/{cust['id']}/benefits", headers=auth_headers)
    assert ben.status_code == 200, ben.text
    rows = [b for b in ben.json()["benefits"] if b["code"] == issued["code"]]
    assert rows, "the issued benefit must appear on the customer profile"
    b = rows[0]
    assert b["status"] == "ACTIVE"
    assert "300000" in b["condition"] or float(b["min_purchase"]) == 300000.0
    assert b["discount_type"] == "PERCENT" and float(b["discount_value"]) == 20.0
    assert b["valid_until"] and b["source"] == "NEXT_PURCHASE"

    # Purchase #2 above the condition → the benefit really discounts the till
    r2 = _buy(client, auth_headers, p["id"], qty=30, amount=240000,
              customer_id=cust["id"], coupon=issued["code"])   # 300,000 − 20%
    assert r2.status_code == 201, r2.text
    assert r2.json()["benefit_source"] in ("COUPON", "CAMPAIGN+COUPON")
    assert float(r2.json()["benefit_amount"]) == 60000.0      # 20% of 300,000

    # lifecycle: USED on the profile, and the redemption is auditable
    ben2 = client.get(f"/api/customers/{cust['id']}/benefits", headers=auth_headers).json()
    row2 = [x for x in ben2["benefits"] if x["code"] == issued["code"]][0]
    assert row2["status"] == "USED"
    with SessionLocal() as db:
        c = db.execute(select(Coupon).where(Coupon.code == issued["code"])).scalar_one()
        assert c.used_count == 1 and c.status == "USED"
        msgs = db.execute(select(SmsMessage).where(SmsMessage.reference_type == "Invoice")).scalars().all()
        assert any(issued["code"] in (m.text or "") for m in msgs), \
            "the invoice SMS must carry the future-benefit code (auto SMS, §29)"


# =========================================================================== §6-9/§18 — auto-resolve & lifecycle
def test_insight_lifecycle_update_merge_resolve(client, auth_headers):
    """Create → Active → update-in-place with new targets → auto-resolve when fixed.

    A tiny deterministic analyzer plays the role of every customer-target rule in
    the product («به A/B/C تخفیف بده»): the SAME open card must absorb target D
    instead of spawning a twin (step 11), and when the condition clears — even
    without the manager ever opening the card — the engine resolves it (steps 6–9).
    """
    from app.database import SessionLocal
    from app.models import Insight
    from app.services import insights as svc
    from sqlalchemy import select

    state = {"targets": []}

    def an(ctx):
        rows = [{"customer_id": t, "name": f"C{t}"} for t in state["targets"]]
        if not rows:
            return []
        return [svc.Draft(
            kind="B481_LIFECYCLE", dedupe_key="cohort", title=f"{len(rows)} هدف",
            body="rule", priority=2, evidence={"rows": rows, "targets": [r["customer_id"] for r in rows]},
            actions=[{"type": "note", "label": "y", "params": {}}],
            expected_gain=150000.0, metric={"metric": "customer_sales", "window_days": 14})]

    old = svc.ANALYZERS.get("B481_LIFECYCLE")
    svc.ANALYZERS["B481_LIFECYCLE"] = an
    try:
        state["targets"] = [101, 102, 103]
        svc.run(db_session_factory=None) if False else None
        with SessionLocal() as db:
            res = svc.run(db, kinds=["B481_LIFECYCLE"])
            assert res["created"] >= 1
        with SessionLocal() as db:
            row = db.execute(select(Insight).where(Insight.kind == "B481_LIFECYCLE")).scalars().first()
            assert row is not None and row.status == "NEW"
            first_id, first_created = row.id, row.created_at
            ev = __import__("json").loads(row.evidence)
            assert sorted(ev["targets"]) == [101, 102, 103]

        # target D joins while the card is still open → SAME card updates (steps 10–11)
        state["targets"] = [101, 102, 103, 104]
        with SessionLocal() as db:
            svc.run(db, kinds=["B481_LIFECYCLE"])
        with SessionLocal() as db:
            rows = db.execute(select(Insight).where(Insight.kind == "B481_LIFECYCLE")).scalars().all()
            assert len(rows) == 1, f"expected one merged card, got {len(rows)}"
            assert rows[0].id == first_id, "the open card must be updated, not replaced"
            ev = __import__("json").loads(rows[0].evidence)
            assert sorted(ev["targets"]) == [101, 102, 103, 104]

        # the manager fixes the underlying condition elsewhere → auto-resolved NOW
        state["targets"] = []
        with SessionLocal() as db:
            svc.run(db, kinds=["B481_LIFECYCLE"])
        with SessionLocal() as db:
            row = db.get(Insight, first_id)
            assert row.status == "RESOLVED", "a cleared condition must close the card by itself"
            assert row.resolved_at is not None
            res = __import__("json").loads(row.resolution)
            assert res["reason"] == "condition_cleared"

        # the condition comes back → a NEW cycle is born; the old card stays resolved (step 12)
        state["targets"] = [201]
        with SessionLocal() as db:
            svc.run(db, kinds=["B481_LIFECYCLE"])
        with SessionLocal() as db:
            rows = db.execute(select(Insight).where(Insight.kind == "B481_LIFECYCLE")).scalars().all()
            assert len(rows) == 2
            assert db.get(Insight, first_id).status == "RESOLVED", "an old card must never resurrect"
            assert any(r.status == "NEW" and r.id != first_id for r in rows)
    finally:
        if old is None:
            svc.ANALYZERS.pop("B481_LIFECYCLE", None)
        else:
            svc.ANALYZERS["B481_LIFECYCLE"] = old
        with SessionLocal() as db:
            for r in db.execute(select(Insight).where(Insight.kind == "B481_LIFECYCLE")).scalars():
                db.delete(r)
            db.commit()


def test_low_stock_insight_resolves_after_receiving_goods(client, auth_headers):
    """The owner's exact story: «کمبود موجودی» → manager stocks up elsewhere → card closes.

    A VELOCITY card is produced by the REAL engine over REAL backdated sales, the
    manager receives goods from the Inventory screen WITHOUT touching the card,
    and the next intelligence pass resolves it.
    """
    from app.database import SessionLocal
    from app.models import Insight
    from app.services import insights as svc
    from sqlalchemy import select

    p = _product(client, auth_headers)
    # big-enough velocity/margin that the card lands in the engine's top-10 even
    # when earlier tests left a busy database behind (the engine ranks cards).
    _receive(client, auth_headers, p["id"], qty=36, buy=8000, sell=50000)   # tiny cover
    cust = _customer(client, auth_headers)
    stamps = []
    for k in range(6):                       # 6 sale-days inside the 28-day window
        r = _buy(client, auth_headers, p["id"], qty=6, amount=300000, customer_id=cust["id"])
        assert r.status_code == 201, r.text
        stamps.append(r.json()["invoice_id"])
    _backdate_invoices(client, auth_headers, cust["id"], [26, 21, 16, 11, 6, 2])

    try:
        with SessionLocal() as db:
            svc.run(db, kinds=["VELOCITY"])
        with SessionLocal() as db:
            rows = db.execute(select(Insight).where(Insight.kind == "VELOCITY",
                                                    Insight.dedupe_key == f"product:{p['id']}")).scalars().all()
            assert rows, "a product this close to empty must raise a VELOCITY card"
            card = rows[0]
            assert card.status == "NEW"
            ev = __import__("json").loads(card.evidence)
            assert ev["stock"] <= 6

        # the manager stocks up in Inventory — no insight button involved
        _receive(client, auth_headers, p["id"], qty=500, buy=8000, sell=12000)

        with SessionLocal() as db:
            svc.run(db, kinds=["VELOCITY"])
        with SessionLocal() as db:
            card = db.get(Insight, card.id)
            assert card.status == "RESOLVED", (
                f"stock was replenished elsewhere — the card must auto-resolve, stays {card.status}")
            assert card.resolved_at is not None
    finally:
        with SessionLocal() as db:
            for r in db.execute(select(Insight).where(Insight.dedupe_key == f"product:{p['id']}")).scalars():
                db.delete(r)
            db.commit()


def test_customer_cohort_is_one_updating_card(client, auth_headers):
    """«به A/B/C تخفیف بده» is ONE suggestion; D joins the same card; the fix closes it.

    Driven through the REAL ``CUST_RETURN_ABUSE`` cohort analyzer (three customers
    abusing returns): one merged card, updated in place when a fourth joins, and
    auto-resolved once their behaviour normalises — nobody opens the card at all.
    """
    from app.database import SessionLocal
    from app.models import InvoiceItem, Insight
    from app.services import insights as svc
    from sqlalchemy import select

    def seed_returner():
        c = _customer(client, auth_headers)
        p = _product(client, auth_headers)
        _receive(client, auth_headers, p["id"], qty=500, buy=8000, sell=12000)
        item_ids = []
        for _ in range(7):                   # 7 visits
            r = _buy(client, auth_headers, p["id"], qty=1, amount=12000, customer_id=c["id"])
            assert r.status_code == 201, r.text
            with SessionLocal() as db:
                items = db.execute(select(InvoiceItem).where(
                    InvoiceItem.invoice_id == r.json()["invoice_id"])).scalars().all()
                item_ids.append((r.json()["invoice_id"], items[0].id))
        for inv_id, iid in item_ids[:3]:     # 3 completed returns → rate 3/7
            rr = client.post("/api/returns", headers=auth_headers,
                             json={"invoice_id": inv_id, "invoice_item_id": iid, "qty": 1, "reason": "test"})
            assert rr.status_code == 201, rr.text
        return c, p

    try:
        a_cust, a_p = seed_returner()
        b_cust, b_p = seed_returner()

        with SessionLocal() as db:
            svc.run(db, kinds=["CUST_RETURN_ABUSE"])
        with SessionLocal() as db:
            rows = db.execute(select(Insight).where(Insight.kind == "CUST_RETURN_ABUSE")).scalars().all()
            live = [r for r in rows if r.status in ("NEW", "SNOOZED")]
            assert live, "return abusers must raise one merged advice"
            card = live[0]
            assert len(rows) == 1, f"two abusers must share ONE card, got {len(rows)}"
            ev = __import__("json").loads(card.evidence)
            merged = sorted(ev["targets"])
            assert a_cust["id"] in merged and b_cust["id"] in merged, merged

        # customer D starts behaving the same way → the SAME card absorbs D
        d_cust, d_p = seed_returner()
        with SessionLocal() as db:
            svc.run(db, kinds=["CUST_RETURN_ABUSE"])
        with SessionLocal() as db:
            rows = db.execute(select(Insight).where(Insight.kind == "CUST_RETURN_ABUSE")).scalars().all()
            assert len(rows) == 1, f"customer D must join the existing card, not spawn a twin ({len(rows)} rows)"
            assert rows[0].id == card.id
            ev = __import__("json").loads(rows[0].evidence)
            assert d_cust["id"] in ev["targets"], "the updated card must list the new target"

        # everyone settles down (new purchases dilute the return rate) → auto-resolve
        for c, p in ((a_cust, a_p), (b_cust, b_p), (d_cust, d_p)):
            for _ in range(10):
                r = _buy(client, auth_headers, p["id"], qty=1, amount=12000, customer_id=c["id"])
                assert r.status_code == 201, r.text
        with SessionLocal() as db:
            svc.run(db, kinds=["CUST_RETURN_ABUSE"])
        with SessionLocal() as db:
            row = db.get(Insight, card.id)
            assert row.status == "RESOLVED", (
                f"behaviour normalised — the card must auto-resolve, stays {row.status}")
    finally:
        with SessionLocal() as db:
            for r in db.execute(select(Insight).where(Insight.kind == "CUST_RETURN_ABUSE")).scalars():
                db.delete(r)
            db.commit()


def test_quality_gate_suppresses_valueless_suggestions(client, auth_headers):
    """«کمتر پیشنهاد بده، اما درست‌تر» — zero-impact nice-to-haves never reach the screen."""
    from app.database import SessionLocal
    from app.models import Insight
    from app.services import insights as svc
    from sqlalchemy import select

    def an(ctx):
        return [
            svc.Draft(kind="B481_GATE", dedupe_key="noise", title="n", body="b", priority=4,
                      evidence={"rows": [1]}, actions=[{"type": "note", "label": "n", "params": {}}],
                      expected_gain=0.0, metric={}),
            svc.Draft(kind="B481_GATE", dedupe_key="value", title="v", body="b", priority=1,
                      evidence={"rows": [1]}, actions=[{"type": "note", "label": "n", "params": {}}],
                      expected_gain=250000.0, metric={}),
        ]

    old = svc.ANALYZERS.get("B481_GATE")
    svc.ANALYZERS["B481_GATE"] = an
    try:
        with SessionLocal() as db:
            res = svc.run(db, kinds=["B481_GATE"])
        with SessionLocal() as db:
            rows = {r.dedupe_key: r for r in db.execute(
                select(Insight).where(Insight.kind == "B481_GATE")).scalars().all()}
            assert "value" in rows, "a high-impact card must publish"
            assert "noise" not in rows, "zero-impact nice-to-have chatter must be suppressed"
            assert res.get("suppressed", {}).get("zero_impact_low_priority", 0) >= 1
    finally:
        if old is None:
            svc.ANALYZERS.pop("B481_GATE", None)
        else:
            svc.ANALYZERS["B481_GATE"] = old
        with SessionLocal() as db:
            for r in db.execute(select(Insight).where(Insight.kind == "B481_GATE")).scalars():
                db.delete(r)
            db.commit()


# =========================================================================== step 35 — idempotency
def test_executing_twice_never_duplicates_business_objects(client, auth_headers):
    """«دوبار روی اجرا» must not create a twin festival or a twin coupon."""
    import json as _json

    from app.database import SessionLocal
    from app.models import Campaign, Insight, Invoice
    from app.services import insight_actions, insights as svc
    from sqlalchemy import select

    with SessionLocal() as db:
        ins = Insight(kind="B481_IDEM", dedupe_key="x", title="t", body="b", priority=1,
                      status="NEW", evidence="{}", metric="{}",
                      actions=_json.dumps([{"type": "flash_sale", "label": "f",
                                            "params": {"percent": 10, "days": 5}}]))
        db.add(ins)
        db.commit()
        out1 = insight_actions.execute(db, ins, user=None)
        out2 = insight_actions.execute(db, ins, user=None)     # the double-click
        db.commit()
        assert out1[0]["ok"] and out2[0]["ok"], (out1, out2)
        camp_ids = {out1[0]["result"]["campaign_id"], out2[0]["result"]["campaign_id"]}
        assert len(camp_ids) == 1, "a second execution must reuse the first festival, not create a twin"
        n = db.execute(select(Campaign).where(Campaign.source_insight_id == ins.id)).scalars().all()
        assert len(n) == 1

        # the future-benefit coupon is issued at most once per invoice
        inv = db.execute(select(Invoice).order_by(Invoice.id.desc())).scalars().first()
        assert inv is not None
        from app.services import coupons as coupon_svc
        c1 = coupon_svc.issue_next_purchase_coupon(db, invoice=inv, customer=None, user=None)
        c2 = coupon_svc.issue_next_purchase_coupon(db, invoice=inv, customer=None, user=None)
        db.commit()
        if c1 is not None:
            assert c2 is not None and c1.id == c2.id, "one invoice must never issue the same benefit twice"


def test_accepting_twice_is_rejected(client, auth_headers):
    """The «اجرا» button is one-shot per card: a double click cannot double-execute."""
    from app.database import SessionLocal
    from app.models import Insight
    from app.services import insights as svc
    from sqlalchemy import select

    def an(ctx):
        return [svc.Draft(kind="B481_ACCEPT", dedupe_key="one", title="t", body="b", priority=1,
                          evidence={"rows": [1]}, actions=[{"type": "note", "label": "n", "params": {}}],
                          expected_gain=120000.0, metric={})]

    old = svc.ANALYZERS.get("B481_ACCEPT")
    svc.ANALYZERS["B481_ACCEPT"] = an
    try:
        with SessionLocal() as db:
            svc.run(db, kinds=["B481_ACCEPT"])
        with SessionLocal() as db:
            row = db.execute(select(Insight).where(Insight.kind == "B481_ACCEPT")).scalars().first()
            iid = row.id
        r1 = client.post(f"/api/insights/{iid}/accept", headers=auth_headers, json={})
        assert r1.status_code == 200, r1.text
        r2 = client.post(f"/api/insights/{iid}/accept", headers=auth_headers, json={})
        assert r2.status_code == 409, "accepting an executed card again must be refused"
    finally:
        if old is None:
            svc.ANALYZERS.pop("B481_ACCEPT", None)
        else:
            svc.ANALYZERS["B481_ACCEPT"] = old
        with SessionLocal() as db:
            for r in db.execute(select(Insight).where(Insight.kind == "B481_ACCEPT")).scalars():
                db.delete(r)
            db.commit()


# =========================================================================== steps 30–32 — product search
def test_product_search_without_a_scanner(client, auth_headers):
    """Barcode, name, partial name and Persian normalization must all find the product."""
    p = _product(client, auth_headers, name="کفیر پرچرب یک‌لیتری دماوند", barcode="6269919900123")

    def find(term):
        r = client.get(f"/api/pos/search?q={term}&limit=200", headers=auth_headers)
        assert r.status_code == 200, r.text
        return [i["product_id"] for i in r.json()["items"]]

    assert p["id"] in find("6269919900123"), "manual barcode entry must work"
    assert p["id"] in find("کفیر پرچرب"), "product name must work"
    assert p["id"] in find("پرچرب یک"), "partial name must work"
    # Persian normalization: ي/ی, ک/ك, half-space vs space
    assert p["id"] in find("كفير پرچرب يك ليتري دماوند"), "ي/ی and ك/ک and half-spaces must normalize"
    assert p["id"] in find("کفیر پرچرب یک لیتری دماوند"), "half-space vs space must normalize"
    # Persian digits typed for the barcode
    assert p["id"] in find("۶۲۶۹۹۱۹۹۰۰۱۲۳"), "Persian digits must match an ASCII barcode"
    # the products list endpoint (used by modals) shares the same engine
    r = client.get("/api/products?q=کفیر دماوند", headers=auth_headers)
    assert r.status_code == 200
    assert any(x["id"] == p["id"] for x in r.json()["items"])
