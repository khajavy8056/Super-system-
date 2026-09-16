# -*- coding: utf-8 -*-
"""v3.5.13 — the customer-behaviour analyzers must fire, and stay executable.

Two things are pinned here, because both are easy to break silently:

1.  **The new analyzers actually produce insights on real data.** A detector that never fires is
    indistinguishable from one that was never written, so this drives the REAL demo-store
    generator (a year of real invoices through the real POS service) and then the REAL
    ``insights.run``.

2.  **Every suggestion is executable and measurable.** ``accept()`` replays
    ``insight_actions.ACTIONS[type]`` and ``measure()`` computes ``insights._metric_value(spec)``.
    A draft whose action type is not in that dict, or whose metric kind is not one
    ``_metric_value`` understands, produces a button that fails and a gain that can never be
    measured — i.e. decoration. The supported sets are read out of the real code rather than
    restated, so this cannot drift out of date.
"""
import datetime as _dt
import inspect
import re

import pytest

from app.services import customer_intel, insight_actions, insights


def _supported_metrics() -> set[str]:
    """Every metric kind ``_metric_value`` can compute, read from its own source."""
    src = inspect.getsource(insights._metric_value)
    return set(re.findall(r'm == "([a-z_]+)"', src))


@pytest.fixture(scope="module")
def analyzed(client, auth_headers):
    """Seed real customers through the real POS, backdate the invoices, analyse.

    ``demo_store.generate`` is not usable here: it refuses a database that already holds more
    than 50 invoices, and the shared session-scoped test DB always does by the time this module
    runs. Seeding additively keeps this test meaningful inside a full suite run instead of
    silently skipping.
    """
    from datetime import timedelta

    from app.database import SessionLocal
    from app.models import Insight, Invoice
    from sqlalchemy import select, update

    pids = []
    for i in range(3):
        r = client.post("/api/products", json={"barcode": f"626550100{i:04d}", "name": f"IntelGoods {i}"},
                        headers=auth_headers)
        assert r.status_code == 201, r.text
        pid = r.json()["id"]
        pids.append(pid)
        rr = client.post("/api/batches/receive", headers=auth_headers, json={
            "product_id": pid, "quantity_received": 5000, "buy_price": 8000, "sell_price": 12000})
        assert rr.status_code == 201, rr.text

    # Ten customers with enough history for the RFM/churn/basket families. All sales are cash:
    # a CREDIT tender is rejected unless the customer has credit_enabled, which is not what this
    # test is about.
    stamps = []          # (invoice_id, days_ago)
    for c in range(10):
        r = client.post("/api/customers", json={"name": f"IntelCust {c}", "phone": f"09121000{c:03d}"},
                        headers=auth_headers)
        assert r.status_code == 201, r.text
        cid = r.json()["id"]
        tapering = c < 3          # these three fade away → basket shrink / churn
        for k in range(6):
            if tapering and k >= 4:
                break
            rr = client.post("/api/pos/checkout", headers=auth_headers, json={
                "items": [{"product_id": pids[k % 3], "quantity": 2},
                          {"product_id": pids[(k + 1) % 3], "quantity": 1}],
                "payments": [{"method": "CASH", "amount": 36000}],
                "customer_id": cid})
            assert rr.status_code == 201, rr.text
            iid = rr.json()["invoice_id"]
            if tapering:
                days_ago = 88 - k * 6      # everything in the distant past
            else:
                days_ago = 5 + k * 13 + c  # spread across the window, varies by day of month
            stamps.append((iid, days_ago, (c * 3 + k) % 12))

    with SessionLocal() as db:
        now = _dt.datetime.now(_dt.timezone.utc)
        for iid, days_ago, hour in stamps:
            db.execute(update(Invoice).where(Invoice.id == iid)
                       .values(created_at=now - timedelta(days=days_ago, hours=hour)))
        db.commit()

        res = insights.run(db, days=90)
        assert not res["errors"], f"analyzers raised: {res['errors']}"
        kinds = {r[0] for r in db.execute(select(Insight.kind)).all()}
    return {"result": res, "kinds": kinds}


def test_new_analyzers_are_registered_and_labelled():
    for kind in customer_intel.ANALYZERS:
        assert kind in insights.ANALYZERS, f"{kind} is defined but never registered"
        assert kind in insights.KIND_LABELS, f"{kind} has no Persian label — the feed shows a blank chip"


def test_customer_analyzers_fire_on_real_data(analyzed):
    fired = analyzed["kinds"] & set(customer_intel.ANALYZERS)
    # The demo store has registered customers with real gaps, credit and repeat baskets, so at
    # least the customer-facing family must produce something. Requiring all 24 would couple this
    # test to one RNG seed; requiring none would let the whole module rot.
    assert len(fired) >= 4, (
        f"only {sorted(fired)} fired out of {len(customer_intel.ANALYZERS)} new analyzers — "
        f"store kinds seen: {sorted(analyzed['kinds'])}")
    assert analyzed["kinds"] & {"CUST_PAYDAY", "CUST_CHURN_RISK", "CUST_RFM"}, (
        "the headline customer analyses did not fire")


def _required_params(fn) -> set[str]:
    """Keys an executor *must* have in its payload, read from its own source.

    A key read as ``p["k"]`` is required; one that also appears as ``p.get("k")`` is optional,
    because the executor already handles its absence. Getting this wrong in either direction
    makes the check useless — too strict and it fails on perfectly safe actions (that is exactly
    what happened to ``reorder_note``, whose ``p["product_id"]`` sits inside a
    ``p.get("product_id")`` guard), too loose and it catches nothing.
    """
    src = inspect.getsource(fn)
    hard = set(re.findall(r'p\["(\w+)"\]', src)) | set(re.findall(r"p\['(\w+)'\]", src))
    soft = set(re.findall(r'p\.get\("(\w+)"', src)) | set(re.findall(r"p\.get\('(\w+)'", src))
    return hard - soft


def test_every_suggestion_is_executable_and_measurable(analyzed):
    """No decoration: every action runs, every metric measures.

    This checks the PAYLOAD, not just the action name. ``execute()`` calls
    ``fn(db, insight, a["params"], user)`` and the executors index that dict directly, so an
    action whose payload sits at the top level instead of under "params" passes a name-only
    check and then raises KeyError the moment the shop presses the button. That exact mistake
    was made while writing this module and only an execution-level test caught it.
    """
    from app.database import SessionLocal
    from app.models import Insight, User
    from sqlalchemy import select
    import json

    actions = insight_actions.ACTIONS
    metrics = _supported_metrics()
    assert metrics, "could not read the supported metric kinds — the guard would be vacuous"

    with SessionLocal() as db:
        rows = db.execute(select(Insight)).scalars().all()
    assert rows, "no insights at all — nothing was checked"
    checked_actions = checked_metrics = 0
    for row in rows:
        for a in json.loads(row.actions or "[]"):
            assert a["type"] in actions, (
                f"{row.kind}: action {a['type']!r} has no executor in insight_actions.ACTIONS, "
                f"so «اجرا و سنجش اثر» would fail")
            need = _required_params(actions[a["type"]])
            have = a.get("params") or {}
            missing = need - set(have)
            assert not missing, (
                f"{row.kind}/{a['type']}: payload is missing {sorted(missing)} — the executor "
                f"would raise KeyError when the shop runs this suggestion")
            checked_actions += 1
        spec = json.loads(row.metric or "{}")
        if spec.get("metric"):
            assert spec["metric"] in metrics, (
                f"{row.kind}: metric {spec['metric']!r} is not computable by _metric_value, "
                f"so the A/B gain can never be reported")
            checked_metrics += 1
    assert checked_actions and checked_metrics, "the contract check ran over no actions or metrics"


def test_accepting_the_new_suggestions_actually_executes(analyzed):
    """The strongest form of the same check: really run the actions and require none to fail."""
    from app.database import SessionLocal
    from app.models import Insight, User
    from sqlalchemy import select

    with SessionLocal() as db:
        admin = db.execute(select(User).order_by(User.id)).scalars().first()
        tried = failed = 0
        for kind in sorted(analyzed["kinds"] & set(customer_intel.ANALYZERS)):
            row = db.execute(select(Insight).where(Insight.kind == kind, Insight.status == "NEW")).scalars().first()
            if row is None:
                continue
            res = insights.accept(db, row, user=admin)
            for e in res["executed"]:
                tried += 1
                if not e.get("ok"):
                    failed += 1
                    print(f"ACTION FAILED {kind}/{e.get('type')}: {e.get('error')}")
        assert tried, "no new-kind suggestion could be accepted — nothing was executed"
        assert failed == 0, f"{failed} of {tried} actions failed to execute (see captured output)"

