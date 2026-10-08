# -*- coding: utf-8 -*-
"""v3.8 — calibration honesty proof (user order §3).

The v3.1 engine clamped every measured/expected ratio into [0.15, 2.5], which
silently rewrote real losses as +15 % wins and fed the lie back into future
predictions. These tests prove the clamp is gone:

* negative / zero / positive outcomes are all recorded as measured,
* per-kind stats carry sample_count, MAE, mean_error, direction_accuracy,
  a 95 % CI and positive/negative rates,
* confidence comes from real performance (sample size + stability + pos_rate),
* money / evidence / uncertainty are returned as three separate blocks.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from decimal import Decimal

from app.database import SessionLocal
from app.models import Insight
from app.services import forecast

_n = 0


def _measured(db, kind, raw, measured, idx):
    db.add(Insight(
        kind=kind, dedupe_key=f"v38cal:{kind}:{idx}", title="t", body="b",
        evidence=json.dumps({"expected_gain_raw": raw}),
        expected_gain=Decimal(str(raw)), status="MEASURED",
        measured_gain=Decimal(str(measured)),
        measured_at=datetime.utcnow() + timedelta(seconds=idx)))
    db.flush()


def test_negative_outcomes_are_recorded_not_clamped(client):
    """A kind that lost money must show a negative ratio and n_negative > 0."""
    s = SessionLocal()
    try:
        kind = "V38_LOSS"
        _measured(s, kind, 10000, -5000, 1)
        _measured(s, kind, 10000, -2000, 2)
        _measured(s, kind, 10000, 1000, 3)
        s.commit()
        cal = forecast.learn(s)
        c = cal[kind]
        assert c["n"] == 3
        assert c["n_negative"] == 2 and c["n_positive"] == 1 and c["n_zero"] == 0
        assert c["ratio"] < 0, f"losing kind must keep a negative ratio, got {c['ratio']}"
        assert abs(c["neg_rate"] - 2 / 3) < 0.001
        assert c["mean_error"] < 0
        assert c["mae"] > 0
        assert len(c["ratio_ci95"]) == 2
    finally:
        s.close()


def test_zero_outcome_counts_as_neutral(client):
    s = SessionLocal()
    try:
        kind = "V38_ZERO"
        _measured(s, kind, 5000, 0, 11)
        s.commit()
        c = forecast.learn(s)[kind]
        assert c["n"] == 1 and c["n_zero"] == 1
        assert c["ratio"] == 0
    finally:
        s.close()


def test_confidence_comes_from_real_performance(client):
    """Few samples or mostly-losses ⇒ low; consistent wins ⇒ high."""
    s = SessionLocal()
    try:
        kind = "V38_WIN"
        for i in range(6):
            _measured(s, kind, 10000, 9500 + i * 100, 20 + i)  # stable ~0.95-1.0
        s.commit()
        cal = forecast.learn(s)
        out = forecast.calibrate(s, kind, 10000, cal)
        assert out["confidence"] == "high", out
        assert out["evidence_strength"]["n"] == 6
        assert out["evidence_strength"]["pos_rate"] == 1.0

        out2 = forecast.calibrate(s, "V38_LOSS", 10000, cal)
        assert out2["confidence"] == "low", out2
        assert out2["gain"] < 0, "predicted loss must stay a predicted loss"
        assert out2["low"] < 0, "the band must reach into the red honestly"
    finally:
        s.close()


def test_money_evidence_uncertainty_are_separate(client):
    s = SessionLocal()
    try:
        cal = forecast.learn(s)
        out = forecast.calibrate(s, "V38_WIN", 10000, cal)
        assert set(out["economic_impact"]) == {"gain", "low", "high", "unit"}
        assert out["evidence_strength"]["mae"] is not None
        assert out["evidence_strength"]["direction_accuracy"] is not None
        assert out["prediction_uncertainty"]["ratio_ci95"] is not None
        # flat keys stay for the UI that already reads them
        assert out["gain"] == out["economic_impact"]["gain"]
    finally:
        s.close()
