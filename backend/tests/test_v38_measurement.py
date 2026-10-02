# -*- coding: utf-8 -*-
"""v3.8 — Measurement Contract proof (user order §5).

Every measurement ends in an explicit verdict instead of a bare number:
NOT_MEASURABLE (no contract for the metric), INSUFFICIENT_DATA (window too
short), NEGATIVE_OUTCOME / POSITIVE_OUTCOME / NEUTRAL_OUTCOME (sign of the
adjusted gain). Direction-only metrics (void_rate) never produce a toman
figure — measured_gain stays NULL so calibration never learns a fake zero.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from decimal import Decimal

from app.database import SessionLocal
from app.models import Insight
from app.services import insights as svc


def _accepted(db, metric, *, days_ago=5, baseline=None, window_days=28):
    now = datetime.utcnow()
    row = Insight(
        kind="V38M", dedupe_key=f"v38m:{metric}:{days_ago}:{now.microsecond}",
        title="t", body="b", status="ACCEPTED",
        accepted_at=now - timedelta(days=days_ago),
        metric=json.dumps({"metric": metric, "window_days": window_days,
                           "product_id": -1, "user_id": -1}),
        baseline=json.dumps(baseline or {"window_days": window_days,
                                         "from": (now - timedelta(days=days_ago + window_days)).isoformat()}))
    db.add(row)
    db.commit()
    return row


def test_unknown_metric_is_not_measurable(client):
    s = SessionLocal()
    try:
        row = _accepted(s, "no_such_metric")
        res = svc.measure(s, row)
        s.commit()
        assert res["verdict"] == "NOT_MEASURABLE"
        assert res["gain"] is None
        assert row.status == "MEASURED"  # terminal: re-measuring changes nothing
        assert row.measured_gain is None
    finally:
        s.close()


def test_short_window_is_insufficient_data(client):
    s = SessionLocal()
    try:
        row = _accepted(s, "product_profit", days_ago=0)
        row.accepted_at = datetime.utcnow() - timedelta(hours=1)
        s.commit()
        res = svc.measure(s, row)
        s.commit()
        assert res["verdict"] == "INSUFFICIENT_DATA"
        assert row.measured_gain is None
        assert row.status == "ACCEPTED"  # not terminal: data may arrive
    finally:
        s.close()


def test_rate_metric_has_direction_but_no_money(client):
    """build-488 (§۳۶–۳۷): نرخِ بدتر‌شده ضرر مالی نیست — MISSED_OPPORTUNITY، نه منفی.

    spec-change note (owner directive, build-488): a rate metric (void_rate …)
    carries no toman figure, so it can NEVER produce NEGATIVE_OUTCOME — «ضرر
    فقط وقتی واقعی است که قابل اندازه‌گیری و قابل انتساب باشد». The previous
    NEGATIVE/NEUTRAL expectation predates that ruling and is updated, not
    weakened: the gain-is-None and measured_gain-is-None guards stay.
    """
    s = SessionLocal()
    try:
        row = _accepted(s, "void_rate")
        res = svc.measure(s, row)
        s.commit()
        assert res["verdict"] in ("POSITIVE_OUTCOME", "NO_IMPACT", "MISSED_OPPORTUNITY")
        assert res["verdict"] != "NEGATIVE_OUTCOME", "rate metrics never report money loss (§۳۷)"
        assert res["gain"] is None
        assert row.measured_gain is None, "a rate is not a toman figure"
    finally:
        s.close()


def test_missed_opportunity_when_expected_gain_did_not_happen(client):
    """§۳۷ — سودی که می‌توانست اتفاق بیفتد ولی نیفتاد ≠ ضرر (مثال مالک).

    Previously the empty post window below baseline was scored NEGATIVE_OUTCOME
    with a negative measured_gain, which dragged «عملکرد مدل» down even though
    the model was fine. Now: MISSED_OPPORTUNITY, measured_gain stays NULL and
    the shortfall is recorded as missed_gain (no negative score).
    """
    s = SessionLocal()
    try:
        now = datetime.utcnow()
        row = _accepted(s, "product_profit",
                        baseline={"window_days": 28, "profit": 50000.0, "value": 50000.0,
                                  "from": (now - timedelta(days=33)).isoformat()})
        res = svc.measure(s, row)  # post window is empty for product -1 ⇒ 0 < base
        s.commit()
        assert res["verdict"] == "MISSED_OPPORTUNITY", res
        assert row.measured_gain is None, "missed opportunity must never be stored as a loss"
        detail = json.loads(row.result or "{}")
        assert detail.get("missed_gain", 0) > 0, detail
        assert detail.get("outcome_class") == "MISSED_OPPORTUNITY"
    finally:
        s.close()


def test_real_loss_needs_realized_cost_evidence(client):
    """§۳۷ Negative = فقط ضرر واقعیِ قابل اندازه‌گیری و قابل انتساب، با Evidence.

    Same shortfall as above, BUT the action actually gave a discount in the
    window (realized_cost > 0) and the net result is negative ⇒ real loss ⇒
    NEGATIVE_OUTCOME with loss_evidence (the cost breakdown).
    """
    from decimal import Decimal
    from app.models import Invoice, InvoiceItem, Product
    s = SessionLocal()
    try:
        now = datetime.utcnow()
        prod = Product(barcode="7712345000024", name="V38 Loss prod")
        s.add(prod)
        s.flush()
        inv = Invoice(invoice_number=f"V38LOSS-{now.microsecond}", subtotal=Decimal(900),
                      discount=Decimal(100), total_amount=Decimal(800),
                      status="PAID", created_at=now - timedelta(days=3))
        s.add(inv)
        s.flush()
        s.add(InvoiceItem(invoice_id=inv.id, product_id=prod.id, qty=Decimal(1),
                          unit_buy_price=Decimal(1000), unit_consumer_price=Decimal(1000),
                          unit_sell_price=Decimal(900), discount=Decimal(100),
                          subtotal=Decimal(900), profit=Decimal(-100),
                          created_at=now - timedelta(days=3)))
        s.commit()
        row = _accepted(s, "product_profit",
                        baseline={"window_days": 28, "profit": 50000.0, "value": 50000.0,
                                  "from": (now - timedelta(days=33)).isoformat()})
        row.metric = json.dumps({"metric": "product_profit", "window_days": 28,
                                 "product_id": prod.id})
        s.commit()
        res = svc.measure(s, row)
        s.commit()
        assert res["verdict"] == "NEGATIVE_OUTCOME", res
        assert float(row.measured_gain) < 0
        detail = json.loads(row.result or "{}")
        assert detail["realized_action_cost"]["total"] > 0, detail
        assert detail.get("loss_evidence"), "real loss must carry evidence (§۳۷)"
    finally:
        s.close()


def test_positive_outcome_when_post_above_base(client, auth_headers):
    """End-to-end: a real sale after acceptance ⇒ POSITIVE_OUTCOME."""
    p = client.post("/api/products", headers=auth_headers,
                    json={"barcode": "7700000999011", "name": "V38 M prod"}).json()
    b = client.post("/api/batches/receive", headers=auth_headers,
                    json={"product_id": p["id"], "quantity_received": 10,
                          "buy_price": 1000, "sell_price": 2000}).json()
    s = SessionLocal()
    try:
        now = datetime.utcnow()
        row = Insight(
            kind="V38M", dedupe_key=f"v38m:pos:{now.microsecond}", title="t", body="b",
            status="ACCEPTED", accepted_at=now - timedelta(days=2),
            metric=json.dumps({"metric": "product_profit", "window_days": 28,
                               "product_id": p["id"]}),
            baseline=json.dumps({"window_days": 28, "profit": 0.0, "value": 0.0,
                                 "from": (now - timedelta(days=30)).isoformat()}))
        s.add(row)
        s.commit()
    finally:
        s.close()
    r = client.post("/api/pos/checkout", headers=auth_headers, json={
        "items": [{"product_id": p["id"], "batch_id": b["id"], "quantity": 2}],
        "tax_rate": 0, "payments": [{"method": "CASH", "amount": 4000}]})
    assert r.status_code == 201, r.text
    s = SessionLocal()
    try:
        row = s.get(Insight, row.id)
        res = svc.measure(s, row)
        s.commit()
        assert res["verdict"] == "POSITIVE_OUTCOME", res
        assert float(row.measured_gain) > 0
    finally:
        s.close()
