# -*- coding: utf-8 -*-
"""v3.6.1 — the engine may never propose a price the shop is not allowed to charge.

The bug this pins down
----------------------
``a_price_gap`` and ``insights_pro.a_negative_margin`` both computed a target price as
``buy_price × 1.12`` and proposed it with ``set_price``, without ever looking at
``consumer_price`` — the price printed on the pack, which is a legal ceiling in Iranian retail.
For any item bought dearer than its own printed price, the card told the shop to sell above the
ceiling: profit on paper, impossible at the till. ``PRICE_ROUNDING`` had the same flaw in a
subtler form, because rounding *up* is a price increase in all but name.

Both branches shipped this, which is why the fix lives in one module
(``app/services/pricing_law.py``) and is enforced twice: analyzers must ask it what is legal,
and the executor refuses to write an illegal price even if an analyzer gets it wrong.
"""
import json

import pytest

from app.services import pricing_law
from app.services.pricing_law import PriceLawError

BUY = 50_000       # what the shop paid
SELL = 51_000      # ~2 % margin — thin enough to trigger PRICE_GAP
CONSUMER = 45_000  # printed on the pack, and BELOW cost: no legal price makes money


def test_ceiling_helpers():
    class B:
        consumer_price = CONSUMER
        sell_price = SELL
        buy_price = BUY

    class NoCeiling:
        consumer_price = 0
        sell_price = SELL
        buy_price = BUY

    assert pricing_law.ceiling(B) == CONSUMER
    assert pricing_law.ceiling(NoCeiling) is None, "0 must mean unknown, not unlimited"
    assert pricing_law.clamp_sell(B, 99_000) == CONSUMER
    assert pricing_law.clamp_sell(NoCeiling, 99_000) == 99_000

    hr = pricing_law.headroom(B, BUY)
    assert hr["verdict"] == "unprofitable", "ceiling below cost means pricing cannot help"

    with pytest.raises(PriceLawError):
        pricing_law.guard_sell_price(B, CONSUMER + 1)
    assert pricing_law.guard_sell_price(B, CONSUMER) == CONSUMER


def _actions_of(row):
    """Actions arrive as a list from the API and as a JSON string from a DB row — accept both."""
    a = row.get("actions") if isinstance(row, dict) else row.actions
    if isinstance(a, str):
        a = json.loads(a or "[]")
    return a or []


def _proposal_prices(insights_rows):
    """Every (kind, batch_id, price) an insight proposes to write."""
    for row in insights_rows:
        for a in _actions_of(row):
            pr = a.get("params") or {}
            if a["type"] == "set_price":
                yield row["kind"], pr.get("batch_id"), float(pr.get("sell_price", 0))
            elif a["type"] == "set_prices_bulk":
                for it in pr.get("items", []):
                    yield row["kind"], it.get("batch_id"), float(it.get("sell_price", 0))


def test_no_suggestion_exceeds_the_consumer_price(client, auth_headers):
    r = client.post("/api/products", json={"barcode": "6261234000019", "name": "Overpriced Goods"},
                    headers=auth_headers)
    assert r.status_code == 201, r.text
    pid = r.json()["id"]
    rr = client.post("/api/batches/receive", headers=auth_headers, json={
        "product_id": pid, "quantity_received": 400, "buy_price": BUY,
        "sell_price": SELL, "consumer_price": CONSUMER})
    assert rr.status_code == 201, rr.text
    batch_id = rr.json()["id"]

    # PRICE_GAP only fires on something that actually sells, so sell it.
    for _ in range(12):
        c = client.post("/api/pos/checkout", headers=auth_headers, json={
            "items": [{"product_id": pid, "quantity": 2}],
            "payments": [{"method": "CASH", "amount": SELL * 2}]})
        assert c.status_code == 201, c.text

    assert client.post("/api/insights/run", json={}, headers=auth_headers).status_code == 200
    rows = client.get("/api/insights", params={"status": "ALL", "limit": 500},
                      headers=auth_headers).json()

    # Anti-vacuity: the scenario must actually have produced pricing advice about this product,
    # otherwise "nothing illegal was proposed" would pass for the wrong reason.
    about = [x for x in rows if x.get("evidence", {}).get("batch_id") == batch_id
             or x.get("evidence", {}).get("product_id") == pid]
    assert about, f"the thin-margin overpriced item produced no insight at all; rows={len(rows)}"

    illegal = [(k, b, p) for k, b, p in _proposal_prices(rows)
               if b == batch_id and p > CONSUMER]
    assert not illegal, (
        f"the engine proposed selling above the printed consumer price ({CONSUMER}): {illegal}. "
        "That sale is not legal, so the card is decoration at best and a complaint at worst.")

    # And the advice must say what IS possible, not stay silent about the ceiling.
    gap = [x for x in about if x["kind"] == "PRICE_GAP"]
    if gap:
        assert "مصرف‌کننده" in gap[0]["title"] + gap[0]["body"], (
            "the card proposes no price change but never explains that the consumer price is "
            "why — the shop is left guessing")


def test_executor_refuses_an_illegal_price_even_from_a_handwritten_insight(client, auth_headers):
    """Defence in depth: a bad analyzer, or an old row, still cannot write an illegal price."""
    from app.database import SessionLocal
    from app.models import Insight, ProductBatch, User
    from app.services import insight_actions
    from sqlalchemy import select

    r = client.post("/api/products", json={"barcode": "6261234000026", "name": "Guarded Goods"},
                    headers=auth_headers)
    pid = r.json()["id"]
    rr = client.post("/api/batches/receive", headers=auth_headers, json={
        "product_id": pid, "quantity_received": 10, "buy_price": BUY,
        "sell_price": SELL, "consumer_price": CONSUMER})
    batch_id = rr.json()["id"]

    with SessionLocal() as db:
        admin = db.execute(select(User).order_by(User.id)).scalars().first()
        fake = Insight(kind="PRICE_GAP", dedupe_key="test:guard", title="t", body="b",
                       priority=1, status="NEW", evidence="{}", metric="{}",
                       actions=json.dumps([{"type": "set_price", "label": "x",
                                            "params": {"batch_id": batch_id, "sell_price": 99_000}}]))
        db.add(fake)
        db.commit()
        res = insight_actions.execute(db, fake, user=admin)
        db.rollback()
        after = float(db.get(ProductBatch, batch_id).sell_price)

    assert res[0]["ok"] is False, f"an illegal price was accepted: {res}"
    assert "مصرف‌کننده" in res[0]["error"], f"the refusal is not explained: {res[0]['error']}"
    # This batch was created above the ceiling deliberately (a stale price the shop typed at
    # receive time — the base engine flags that separately). The guard's job is to refuse the
    # raise, not to rewrite history, so the assertion is "unchanged".
    assert after == SELL, f"the batch price moved to {after}; the guard must leave it untouched"


def test_no_suggestion_asks_the_shop_to_rewrite_a_buy_price(client, auth_headers):
    """What you already paid is a fact, not a lever — no action may offer to change it."""
    from app.database import SessionLocal
    from app.models import Insight
    from app.services import insight_actions
    from sqlalchemy import select

    with SessionLocal() as db:
        rows = db.execute(select(Insight)).scalars().all()
    for row in rows:
        for a in _actions_of(row):
            pr = a.get("params") or {}
            assert "buy_price" not in pr, (
                f"{row.kind}/{a['type']} offers to set buy_price — the shop cannot change what "
                "it already paid; the levers are the sell price, the next supplier, or delisting")
    # the executor set must not grow one either
    assert not any("buy_price" in n for n in insight_actions.ACTIONS), \
        "an executor named after buy_price appeared — that lever does not exist"
