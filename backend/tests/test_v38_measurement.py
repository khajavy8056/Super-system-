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
    s = SessionLocal()
    try:
        row = _accepted(s, "void_rate")
        res = svc.measure(s, row)
        s.commit()
        assert res["verdict"] in ("POSITIVE_OUTCOME", "NEGATIVE_OUTCOME", "NEUTRAL_OUTCOME")
        assert res["gain"] is None
        assert row.measured_gain is None, "a rate is not a toman figure"
    finally:
        s.close()


def test_negative_outcome_when_post_below_base(client):
    s = SessionLocal()
    try:
        now = datetime.utcnow()
        row = _accepted(s, "product_profit",
                        baseline={"window_days": 28, "profit": 50000.0, "value": 50000.0,
                                  "from": (now - timedelta(days=33)).isoformat()})
        res = svc.measure(s, row)  # post window is empty for product -1 ⇒ 0 < base
        s.commit()
        assert res["verdict"] == "NEGATIVE_OUTCOME", res
        assert float(row.measured_gain) < 0
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
