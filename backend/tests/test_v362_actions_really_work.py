# -*- coding: utf-8 -*-
"""Does pressing «اجرا و سنجش اثر» actually DO the thing it says?

The shop owner's question was exactly this: "when I press execute, do the things it is supposed
to do really happen, or will something get in the way?" A button that returns a green tick
without changing anything is worse than no button, because the shop believes the advice was
applied.

So every action in ``insight_actions.ACTIONS`` is executed here against a real database, and the
test asserts the **side effect in the data** — not just ``ok: True``. ``ok`` is necessary and
not sufficient: an executor can return successfully after silently doing nothing (a customer id
that no longer exists, an SMS provider that is switched off, a product id that was deleted).

Where an action legitimately no-ops because the shop has not enabled the feature (SMS off), the
test asserts the *reported reason* rather than pretending the effect happened — an honest skip
is recorded, a silent one is a bug.
"""
import json

import pytest

from app.services import insight_actions


import itertools

_seq = itertools.count(1)


@pytest.fixture
def store(client, auth_headers):
    """A product with stock, and a customer who has bought it — the minimum real inputs.

    Every test gets its OWN product: a fixed barcode made the second test fail with 409, and
    sharing one product between tests would let one test's price change leak into another.
    """
    n = next(_seq)
    r = client.post("/api/products", json={"barcode": f"62644440{n:05d}", "name": f"Action Goods {n}"},
                    headers=auth_headers)
    assert r.status_code == 201, r.text
    pid = r.json()["id"]
    rr = client.post("/api/batches/receive", headers=auth_headers, json={
        "product_id": pid, "quantity_received": 500, "buy_price": 8000,
        "sell_price": 12000, "consumer_price": 15000})
    assert rr.status_code == 201, rr.text
    rc = client.post("/api/customers", json={"name": f"Action Customer {n}", "phone": f"0912111{n:04d}"},
                     headers=auth_headers)
    assert rc.status_code == 201, rc.text
    cid = rc.json()["id"]
    rs = client.post("/api/pos/checkout", headers=auth_headers, json={
        "items": [{"product_id": pid, "quantity": 2}],
        "payments": [{"method": "CASH", "amount": 24000}], "customer_id": cid})
    assert rs.status_code == 201, rs.text
    return {"pid": pid, "batch_id": rr.json()["id"], "cid": cid}


def _run_one(db, kind, params, admin):
    """Execute a single action and return its result dict."""
    from app.models import Insight

    ins = Insight(kind=kind, dedupe_key=f"acttest:{kind}", title="t", body="b", priority=1,
                  status="NEW", evidence="{}", metric="{}",
                  actions=json.dumps([{"type": kind, "label": "x", "params": params}]))
    db.add(ins)
    db.commit()
    out = insight_actions.execute(db, ins, user=admin)
    return out[0]


@pytest.fixture
def admin_user():
    from app.database import SessionLocal
    from app.models import User
    from sqlalchemy import select

    with SessionLocal() as db:
        return db.execute(select(User).order_by(User.id)).scalars().first()


# --------------------------------------------------------------------------- state-changing actions
def test_set_price_really_changes_the_batch(client, store, admin_user):
    from app.database import SessionLocal
    from app.models import ProductBatch

    with SessionLocal() as db:
        res = _run_one(db, "set_price", {"batch_id": store["batch_id"], "sell_price": 13000}, admin_user)
        db.commit()
        assert res["ok"] is True, res
        assert float(db.get(ProductBatch, store["batch_id"]).sell_price) == 13000.0


def test_set_min_stock_really_changes_the_product(client, store, admin_user):
    from app.database import SessionLocal
    from app.models import Product

    with SessionLocal() as db:
        res = _run_one(db, "set_min_stock", {"product_id": store["pid"], "min_stock": 37}, admin_user)
        db.commit()
        assert res["ok"] is True, res
        assert db.get(Product, store["pid"]).min_stock_alert == 37


def test_set_min_stock_bulk_applies_every_item(client, store, admin_user):
    from app.database import SessionLocal
    from app.models import Product

    with SessionLocal() as db:
        res = _run_one(db, "set_min_stock_bulk",
                       {"items": [{"product_id": store["pid"], "min_stock": 11}]}, admin_user)
        db.commit()
        assert res["ok"] is True, res
        assert db.get(Product, store["pid"]).min_stock_alert == 11


def test_set_prices_bulk_applies_every_item(client, store, admin_user):
    from app.database import SessionLocal
    from app.models import ProductBatch

    with SessionLocal() as db:
        res = _run_one(db, "set_prices_bulk",
                       {"items": [{"batch_id": store["batch_id"], "sell_price": 14000}]}, admin_user)
        db.commit()
        assert res["ok"] is True, res
        assert res["result"]["updated"] == 1, res
        assert float(db.get(ProductBatch, store["batch_id"]).sell_price) == 14000.0


def test_reorder_note_really_adds_to_the_order_list(client, store, admin_user):
    from app.database import SessionLocal
    from app.models import SystemSetting
    from sqlalchemy import select

    with SessionLocal() as db:
        res = _run_one(db, "reorder_note",
                       {"product_id": store["pid"], "qty": 20, "products": [store["pid"]]}, admin_user)
        db.commit()
        assert res["ok"] is True, res
        row = db.execute(select(SystemSetting).where(SystemSetting.key == "insights.reorder_list")).scalar_one_or_none()
        assert row, "no reorder list was written"
        assert any(x["product_id"] == store["pid"] for x in json.loads(row.value)), row.value


def test_shelf_note_and_note_really_create_a_task(client, store, admin_user):
    from app.database import SessionLocal
    from app.models import Notification
    from sqlalchemy import select, func

    with SessionLocal() as db:
        before = db.execute(select(func.count(Notification.id))).scalar()
        for kind, params in [("shelf_note", {"products": [store["pid"]]}), ("note", {})]:
            res = _run_one(db, kind, params, admin_user)
            assert res["ok"] is True, res
        db.commit()
        after = db.execute(select(func.count(Notification.id))).scalar()
    assert after - before >= 2, f"expected 2 task notifications, got {after - before}"


def test_enable_nudges_and_pos_nudge_really_write_settings(client, store, admin_user):
    from app.database import SessionLocal
    from app.models import SystemSetting
    from sqlalchemy import select

    with SessionLocal() as db:
        assert _run_one(db, "enable_nudges", {}, admin_user)["ok"] is True
        assert _run_one(db, "pos_nudge", {"a": store["pid"], "b": store["pid"]}, admin_user)["ok"] is True
        db.commit()
        row = db.execute(select(SystemSetting).where(SystemSetting.key == "insights.pos_nudges")).scalar_one_or_none()
    assert row and row.value == "true", "pos nudges were not actually enabled"


def test_set_setting_writes_the_key(client, admin_user):
    from app.database import SessionLocal
    from app.models import SystemSetting
    from sqlalchemy import select

    with SessionLocal() as db:
        res = _run_one(db, "set_setting", {"key": "insights.probe_key", "value": "probe_value"}, admin_user)
        db.commit()
        assert res["ok"] is True, res
        row = db.execute(select(SystemSetting).where(SystemSetting.key == "insights.probe_key")).scalar_one_or_none()
    assert row and row.value == "probe_value"


def test_set_credit_limit_really_changes_the_customer(client, store, admin_user):
    from app.database import SessionLocal
    from app.models import Customer

    with SessionLocal() as db:
        res = _run_one(db, "set_credit_limit",
                       {"customers": [{"customer_id": store["cid"], "limit": 900000}]}, admin_user)
        db.commit()
        assert res["ok"] is True, res
        assert float(db.get(Customer, store["cid"]).credit_limit) == 900000.0


def test_tag_customers_really_tags(client, store, admin_user):
    from app.database import SessionLocal
    from app.models import Customer

    with SessionLocal() as db:
        res = _run_one(db, "tag_customers",
                       {"tags": {"ارزشمند": [store["cid"]]}}, admin_user)
        db.commit()
        assert res["ok"] is True, res
        c = db.get(Customer, store["cid"])
        assert "ارزشمند" in (getattr(c, "tags", "") or "") + (getattr(c, "notes", "") or ""), \
            "the tag was not stored anywhere on the customer"


# --------------------------------------------------------------------------- campaigns and coupons
@pytest.mark.parametrize("kind,params_key", [
    ("vip_coupons", "customer_ids"),
    ("winback_sms", "customer_ids"),
])
def test_coupon_actions_really_issue_coupons(client, store, admin_user, kind, params_key):
    from app.database import SessionLocal
    from app.models import Campaign, Coupon
    from sqlalchemy import select, func

    with SessionLocal() as db:
        before_c = db.execute(select(func.count(Coupon.id))).scalar()
        before_camp = db.execute(select(func.count(Campaign.id))).scalar()
        res = _run_one(db, kind, {params_key: [store["cid"]], "percent": 10, "days": 14}, admin_user)
        db.commit()
        assert res["ok"] is True, res
        after_c = db.execute(select(func.count(Coupon.id))).scalar()
        after_camp = db.execute(select(func.count(Campaign.id))).scalar()
    assert after_camp > before_camp, f"{kind} did not create a campaign"
    assert after_c > before_c, f"{kind} reported success but issued no coupon to the customer"


def test_personal_coupons_really_issues_to_that_customer(client, store, admin_user):
    from app.database import SessionLocal
    from app.models import Coupon
    from sqlalchemy import select, func

    with SessionLocal() as db:
        before = db.execute(select(func.count(Coupon.id))).scalar()
        res = _run_one(db, "personal_coupons",
                       {"customers": [{"customer_id": store["cid"], "percent": 12}]}, admin_user)
        db.commit()
        assert res["ok"] is True, res
        after = db.execute(select(func.count(Coupon.id))).scalar()
    assert after > before, "personal_coupons reported success but issued nothing"


def test_threshold_campaign_sets_the_minimum_purchase(client, admin_user):
    from app.database import SessionLocal
    from app.models import Campaign
    from sqlalchemy import select

    with SessionLocal() as db:
        res = _run_one(db, "threshold_campaign", {"percent": 7, "days": 10, "min_purchase": 500000}, admin_user)
        db.commit()
        assert res["ok"] is True, res
        camp = db.execute(select(Campaign).order_by(Campaign.id.desc())).scalars().first()
        assert camp is not None and float(camp.min_purchase) == 500000.0


def test_flash_sale_and_bundle_campaign_create_a_campaign(client, store, admin_user):
    from app.database import SessionLocal
    from app.models import Campaign
    from sqlalchemy import select, func

    with SessionLocal() as db:
        before = db.execute(select(func.count(Campaign.id))).scalar()
        for kind, params in [("flash_sale", {"percent": 8, "days": 5}),
                             ("bundle_campaign", {"product_id": store["pid"], "percent": 12})]:
            res = _run_one(db, kind, params, admin_user)
            assert res["ok"] is True, res
        db.commit()
        after = db.execute(select(func.count(Campaign.id))).scalar()
    assert after - before >= 2, f"expected 2 campaigns, got {after - before}"


def test_markdown_ladder_applies_the_first_step(client, store, admin_user):
    from app.database import SessionLocal
    from app.models import ProductBatch

    with SessionLocal() as db:
        res = _run_one(db, "markdown_ladder",
                       {"batch_id": store["batch_id"],
                        "ladder": [{"from_day": 0, "percent": 10},
                                   {"from_day": 14, "percent": 20}]}, admin_user)
        db.commit()
        assert res["ok"] is True, res
        price = float(db.get(ProductBatch, store["batch_id"]).sell_price)
    assert price < 12000.0, f"the first markdown step was not applied (price still {price})"


# --------------------------------------------------------------------------- SMS actions
SMS_ACTIONS = [
    ("personal_sms", lambda s: {"customers": [{"id": s["cid"], "text": "سلام"}]}),
    ("visit_sms", lambda s: {"customers": [{"id": s["cid"], "day": 3}]}),
    ("sms_buyers", lambda s: {"product_id": s["pid"], "percent": 10}),
    ("debt_reminders", lambda s: {}),
]


@pytest.mark.parametrize("kind,build", SMS_ACTIONS, ids=[k for k, _ in SMS_ACTIONS])
def test_sms_actions_either_send_or_say_why_not(client, store, admin_user, kind, build):
    """An SMS action must not report plain success while sending nothing.

    Either messages are queued/sent, or the result names the reason (provider off, no
    recipients, no debtors). "ok with nothing" is the failure mode this pins down.
    """
    from app.database import SessionLocal
    from app.models import SmsMessage
    from sqlalchemy import select, func

    with SessionLocal() as db:
        before = db.execute(select(func.count(SmsMessage.id))).scalar()
        res = _run_one(db, kind, build(store), admin_user)
        db.commit()
        assert res["ok"] is True, res
        after = db.execute(select(func.count(SmsMessage.id))).scalar()

    result = res.get("result") or {}
    sent = after - before or int(result.get("sent", 0) or 0) or int(result.get("sms", 0) or 0)
    # "there were no debtors" is a legitimate outcome, not a silent failure
    explained = (any(k in result for k in ("skipped", "reason", "no_debtors", "no_customers"))
                 or result.get("debtors") == 0 or result.get("buyers") == 0
                 or result.get("customers") == 0)
    assert sent > 0 or explained, (
        f"{kind} returned ok but queued no message and gave no reason: {result}")


def test_a_customer_id_that_does_not_match_is_reported_not_swallowed(client, store, admin_user):
    """The silent-success failure mode, pinned directly.

    These executors used to ``continue`` past an unmatched id and return ok with nothing done.
    Now they must say so, because a green tick over a no-op is worse than an error.
    """
    from app.database import SessionLocal

    with SessionLocal() as db:
        res = _run_one(db, "set_credit_limit",
                       {"customers": [{"customer_id": 999999, "limit": 500000}]}, admin_user)
        db.commit()
    assert res["ok"] is True
    assert res["result"].get("updated") == 0
    assert res["result"].get("skipped") == "no_matching_customers", (
        f"a payload that matched no customer looked like success: {res['result']}")


def test_customer_actions_accept_either_id_spelling(client, store, admin_user):
    """Analyzers have used both ``customer_id`` and ``id``; neither may silently do nothing."""
    from app.database import SessionLocal
    from app.models import Customer

    with SessionLocal() as db:
        res = _run_one(db, "set_credit_limit",
                       {"customers": [{"id": store["cid"], "limit": 700000}]}, admin_user)
        db.commit()
        assert res["result"].get("updated") == 1, res
        assert float(db.get(Customer, store["cid"]).credit_limit) == 700000.0


# --------------------------------------------------------------------------- coverage guard
def test_every_registered_action_is_covered_by_this_file(client):
    """So a new executor cannot land without anyone checking that it works."""
    covered = {"set_price", "set_min_stock", "set_min_stock_bulk", "set_prices_bulk",
               "reorder_note", "shelf_note", "note", "enable_nudges", "pos_nudge", "set_setting",
               "set_credit_limit", "tag_customers", "vip_coupons", "winback_sms",
               "threshold_campaign", "flash_sale", "bundle_campaign", "markdown_ladder",
               "personal_sms", "visit_sms", "sms_buyers", "debt_reminders", "personal_coupons"}
    missing = set(insight_actions.ACTIONS) - covered
    assert not missing, (
        f"these actions have no execution test: {sorted(missing)} — add a case that asserts the "
        "real side effect, not just ok: True")
    stale = covered - set(insight_actions.ACTIONS)
    assert not stale, f"this file tests actions that no longer exist: {sorted(stale)}"


def test_every_action_of_every_real_insight_executes(client, auth_headers):
    """End-to-end: run the engine, then press every button on every card it produced.

    This is the question the shop owner actually asked. A per-executor test can pass while the
    analyzers feed them a payload shape they do not understand, so the only complete answer is
    to run the real engine and really execute what it emits.
    """
    from datetime import datetime, timedelta

    from app.database import SessionLocal
    from app.models import Insight, Invoice, User
    from sqlalchemy import select, update

    pids = []
    for i in range(3):
        r = client.post("/api/products", json={"barcode": f"62655550{i:05d}", "name": f"E2E Goods {i}"},
                        headers=auth_headers)
        assert r.status_code == 201, r.text
        pid = r.json()["id"]
        pids.append(pid)
        rr = client.post("/api/batches/receive", headers=auth_headers, json={
            "product_id": pid, "quantity_received": 900, "buy_price": 9000,
            "sell_price": 10000, "consumer_price": 14000})
        assert rr.status_code == 201, rr.text

    stamps = []
    for c in range(6):
        rc = client.post("/api/customers", json={"name": f"E2E Cust {c}", "phone": f"0913000{c:04d}"},
                         headers=auth_headers)
        assert rc.status_code == 201, rc.text
        cid = rc.json()["id"]
        for k in range(5):
            rs = client.post("/api/pos/checkout", headers=auth_headers, json={
                "items": [{"product_id": pids[k % 3], "quantity": 2},
                          {"product_id": pids[(k + 1) % 3], "quantity": 1}],
                "payments": [{"method": "CASH", "amount": 30000}], "customer_id": cid})
            assert rs.status_code == 201, rs.text
            stamps.append((rs.json()["invoice_id"], 4 + k * 11 + c, (c * 2 + k) % 12))

    with SessionLocal() as db:
        now = datetime.utcnow()
        for iid, days, hour in stamps:
            db.execute(update(Invoice).where(Invoice.id == iid)
                       .values(created_at=now - timedelta(days=days, hours=hour)))
        db.commit()

        from app.services import insights
        res = insights.run(db, days=90)
        assert not res["errors"], f"analyzers raised: {res['errors']}"

        admin = db.execute(select(User).order_by(User.id)).scalars().first()
        tried, failed = 0, []
        for row in db.execute(select(Insight).where(Insight.status == "NEW")).scalars():
            for e in insights.accept(db, row, user=admin)["executed"]:
                tried += 1
                if not e.get("ok"):
                    failed.append((row.kind, e.get("type"), e.get("error")))
        db.commit()

    print(f"\n>>> executed {tried} actions across the produced insights, {len(failed)} failed")
    assert tried, "no insight produced an executable action — nothing was verified"
    assert not failed, (
        f"{len(failed)} of {tried} actions failed when actually executed: {failed[:8]}")
