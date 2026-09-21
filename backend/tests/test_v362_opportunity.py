# -*- coding: utf-8 -*-
"""v3.6.2 — the Opportunity Engine must earn its place in the feed.

The shop owner's red line was explicit: a new analysis is only worth adding if its effect can
be measured with real data, and adding thirty more statistics cards does not make the engine
smarter. So these tests check the things that decide whether it is signal or noise:

* every new kind is registered, labelled and grouped (an ungrouped card is invisible);
* every action it emits really executes, and every metric it names is computable — a card whose
  button fails or whose gain can never be measured is decoration;
* the NO ACTION cards really do not change anything, which is the whole point of them;
* an analyzer that has not met its own minimum-data rule stays silent instead of guessing.
"""
import json

import pytest

from app.services import insight_actions, insights, opportunity

# actions that only write a note/task — everything else changes shop state
PASSIVE = {"note", "shelf_note", "reorder_note"}


def test_new_kinds_are_registered_labelled_and_grouped():
    for kind in opportunity.ANALYZERS:
        assert kind in insights.ANALYZERS, f"{kind} is defined but never registered"
        assert kind in insights.KIND_LABELS, f"{kind} has no Persian label"
        assert any(kind in ks for _, ks in insights.GROUPS.values()), (
            f"{kind} has no UI group, so it would never be counted or shown")


def test_opportunity_analyzers_stay_silent_on_thin_data(client, auth_headers):
    """The shared test database has almost no history — every MinData rule must hold.

    An analyzer that invents a conclusion from three invoices is worse than one that says
    nothing, because the shop cannot tell the two apart.
    """
    from app.database import SessionLocal
    from app.services import insights as ins

    with SessionLocal() as db:
        ctx = ins._load_ctx(db, 90)
        for kind, fn in opportunity.ANALYZERS.items():
            drafts = fn(ctx)
            assert isinstance(drafts, list), f"{kind} did not return a list"
            for d in drafts:
                n = d.evidence.get("n") or d.evidence.get("baskets_recent") or d.evidence.get("weeks")
                if n is not None:
                    assert n >= 8, f"{kind} published a conclusion from only {n} observations"


@pytest.fixture(scope="module")
def engine_run(client, auth_headers):
    """Seed enough history for the new analyzers to fire, then run the engine once.

    Without this the contract checks below pass over zero cards, which proves nothing.
    """
    from datetime import datetime, timedelta

    from app.database import SessionLocal
    from app.models import Invoice
    from sqlalchemy import update

    pids = []
    for i in range(4):
        r = client.post("/api/products", json={"barcode": f"62677770{i:05d}", "name": f"Opp Goods {i}"},
                        headers=auth_headers)
        assert r.status_code == 201, r.text
        pid = r.json()["id"]
        pids.append(pid)
        rr = client.post("/api/batches/receive", headers=auth_headers, json={
            "product_id": pid, "quantity_received": 2000, "buy_price": 9000,
            "sell_price": 11000, "consumer_price": 16000})
        assert rr.status_code == 201, rr.text

    stamps = []
    for c in range(8):
        rc = client.post("/api/customers", json={"name": f"Opp Cust {c}", "phone": f"0914000{c:04d}"},
                         headers=auth_headers)
        assert rc.status_code == 201, rc.text
        cid = rc.json()["id"]
        for k in range(6):
            items = [{"product_id": pids[k % 4], "quantity": 2}]
            if k % 2 == 0:                      # make 0 and 2 co-occur, so pair maths has signal
                items.append({"product_id": pids[(k + 2) % 4], "quantity": 1})
            # the till wants exact tender — PAYMENT_MISMATCH otherwise
            amt = sum(int(it["quantity"]) * 11000 for it in items)
            rs = client.post("/api/pos/checkout", headers=auth_headers, json={
                "items": items, "payments": [{"method": "CASH", "amount": amt}],
                "customer_id": cid})
            assert rs.status_code == 201, rs.text
            stamps.append((rs.json()["invoice_id"], 3 + k * 9 + c, (c * 3 + k) % 12))

    with SessionLocal() as db:
        now = datetime.utcnow()
        for iid, days, hour in stamps:
            db.execute(update(Invoice).where(Invoice.id == iid)
                       .values(created_at=now - timedelta(days=days, hours=hour)))
        db.commit()
        res = insights.run(db, days=90)
        assert not res["errors"], f"analyzers raised: {res['errors']}"
    return res


def test_every_opportunity_action_executes_and_metric_is_computable(client, auth_headers, engine_run):
    """Same contract as the rest of the engine, re-checked for the new kinds.

    Payload shape is the part that breaks silently: the executor reads ``a["params"]`` and
    indexes it directly, so a draft that puts keys at the top level passes every name-only
    check and then raises KeyError when the owner presses the button.
    """
    from app.database import SessionLocal
    from app.models import Insight
    from sqlalchemy import select

    import inspect
    import re

    supported = set(insight_actions.ACTIONS)
    # read the supported metric kinds out of the function itself, so this cannot drift
    metrics = set(re.findall(r'm == "([a-z_]+)"', inspect.getsource(insights._metric_value)))

    with SessionLocal() as db:
        rows = db.execute(select(Insight)).scalars().all()
    checked = 0
    for row in rows:
        if row.kind not in opportunity.ANALYZERS:
            continue
        for a in json.loads(row.actions or "[]"):
            assert a["type"] in supported, f"{row.kind}: no executor for {a['type']!r}"
            pr = a.get("params")
            assert isinstance(pr, dict), (
                f"{row.kind}/{a['type']}: payload must sit under 'params', got {type(pr).__name__}")
            checked += 1
        spec = json.loads(row.metric or "{}")
        assert spec.get("metric") in metrics, (
            f"{row.kind}: metric {spec.get('metric')!r} is not computable, so the effect of this "
            "card can never be measured — it fails the owner's own acceptance rule")
    fired = {row.kind for row in rows if row.kind in opportunity.ANALYZERS}
    assert fired, (
        "none of the new analyzers fired on the seeded store — the contract check above ran "
        "over zero cards and proves nothing")
    assert checked, "the fired cards carry no actions to check"


def test_no_action_cards_really_take_no_action(client, auth_headers, engine_run):
    """The NO ACTION layer must not sneak in a state change.

    A card that says "do nothing" while carrying a coupon or a price change is worse than no
    card at all — the owner trusts it and the engine spends margin anyway.
    """
    from app.database import SessionLocal
    from app.models import Insight
    from sqlalchemy import select

    with SessionLocal() as db:
        rows = db.execute(select(Insight).where(Insight.kind.in_(
            ["NO_DISCOUNT_NEEDED", "NEXT_BEST_ACTION"]))).scalars().all()

    for row in rows:
        for a in json.loads(row.actions or "[]"):
            assert a["type"] in PASSIVE, (
                f"{row.kind} claims to be a do-nothing/decide card but carries {a['type']!r}, "
                "which changes shop state")
        if row.kind == "NEXT_BEST_ACTION":
            ev = json.loads(row.evidence or "{}")
            assert ev.get("verdict"), "a NEXT_BEST_ACTION card must state its verdict"


def test_no_discount_needed_is_a_real_recommendation_not_a_guess(client, auth_headers, engine_run):
    """If the analyzer does fire, it must name customers and show the growth it measured."""
    from app.database import SessionLocal
    from app.models import Insight
    from sqlalchemy import select

    with SessionLocal() as db:
        row = db.execute(select(Insight).where(Insight.kind == "NO_DISCOUNT_NEEDED")).scalars().first()
    if row is None:
        pytest.skip("not enough purchase history on this database for the MinData rule")
    ev = json.loads(row.evidence or "{}")
    assert ev.get("customer_ids"), "the card recommends doing nothing to nobody"
    for r in ev.get("rows", []):
        assert r["growth"] > 0, f"a customer with non-growing basket is in the do-not-discount list: {r}"
