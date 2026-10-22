# -*- coding: utf-8 -*-
"""build-488 — ارزیابی صادقانهٔ مدل هوش مصنوعی (§۳۶–۳۷).

قاعدهٔ مالک: «سودی که می‌توانست اتفاق بیفتد ولی نیفتاد» ضرر نیست (مثلاً نیامدن
مشتریِ پیش‌بینی‌شده). فقط ضرر واقعی، قابل اندازه‌گیری و قابل انتساب با Evidence
منفی حساب می‌شود؛ «عملکرد مدل» نباید به‌خاطر Missed Opportunity منفی شود.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta

from app.models import Insight
from app.services import forecast, insights as svc
from tests.test_v38_measurement import _accepted, SessionLocal


def test_missed_opportunity_has_no_negative_score(client):
    """فرصت ازدست‌رفته: measured_gain=NULL + missed_gain ثبت + بدون امتیاز منفی."""
    s = SessionLocal()
    try:
        now = datetime.utcnow()
        row = _accepted(s, "product_profit",
                        baseline={"window_days": 28, "profit": 50000.0, "value": 50000.0,
                                  "from": (now - timedelta(days=33)).isoformat()})
        res = svc.measure(s, row)
        s.commit()
        assert res["verdict"] == "MISSED_OPPORTUNITY"
        assert row.measured_gain is None
        # یادگیری کالیبراسیون هم نباید آن را ضرر ببیند
        cal = forecast.learn(s)
        entry = cal.get(row.kind, {})
        assert entry.get("n_negative", 0) == 0
        assert entry.get("n_missed", 0) >= 1
    finally:
        s.close()


def test_neutral_outcome_is_not_negative(client):
    """NO_IMPACT (بدون تغییر) نیز امتیاز منفی ندارد (§۳۷ Neutral)."""
    s = SessionLocal()
    try:
        now = datetime.utcnow()
        row = _accepted(s, "product_profit",
                        baseline={"window_days": 28, "profit": 0.0, "value": 0.0,
                                  "from": (now - timedelta(days=33)).isoformat()})
        res = svc.measure(s, row)  # post هم خالی ⇒ 0-0
        s.commit()
        assert res["verdict"] in ("NO_IMPACT", "MISSED_OPPORTUNITY")
        assert row.measured_gain in (None, 0.0)
    finally:
        s.close()


def test_measurement_verdict_unit():
    """قاعدهٔ طبقه‌بندی مستقیم — بدون دیتابیس."""
    spec = {"metric": "product_profit"}
    assert svc.measurement_verdict(5.0, enough=True, spec=spec) == "POSITIVE_OUTCOME"
    assert svc.measurement_verdict(0.0, enough=True, spec=spec) == "NO_IMPACT"
    # منفی بدون هزینهٔ واقعی = فرصت ازدست‌رفته، نه ضرر
    assert svc.measurement_verdict(-5.0, enough=True, spec=spec, realized_cost=0) == "MISSED_OPPORTUNITY"
    # منفی با هزینه/تخفیف واقعی = ضرر واقعی
    assert svc.measurement_verdict(-5.0, enough=True, spec=spec, realized_cost=12) == "NEGATIVE_OUTCOME"
    assert svc.measurement_verdict(None, enough=True, spec=spec) == "NOT_MEASURABLE"
    assert svc.measurement_verdict(-5.0, enough=False, spec=spec) == "INSUFFICIENT_DATA"


def test_plan_reports_outcome_counters(client, auth_headers):
    """خروجی forecast.plan باید سود واقعی/بی‌اثر/فرصت ازدست‌رفته/ضرر را جدا بدهد."""
    s = SessionLocal()
    try:
        now = datetime.utcnow()
        row = _accepted(s, "product_profit",
                        baseline={"window_days": 28, "profit": 50000.0, "value": 50000.0,
                                  "from": (now - timedelta(days=33)).isoformat()})
        svc.measure(s, row)
        s.commit()
        plan = forecast.plan(s)
        outcomes = plan["model"]["outcomes"]
        # «فرصت ازدست‌رفته» جدا گزارش می‌شود و هرگز در «ضرر» نمی‌نشیند
        # (دادهٔ سراسری session-scoped است؛ فقط جداسازی خودِ ردیف مهم است)
        assert outcomes["missed"] >= 1, outcomes
        assert set(outcomes) == {"positive", "neutral", "missed", "negative"}
    finally:
        s.close()
