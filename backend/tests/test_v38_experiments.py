# -*- coding: utf-8 -*-
"""v3.8 — Experiment orchestration proof (user order §6).

CREATE → PLAN → ASSIGN → START → EXPOSE → OUTCOME → CLOSE → EVALUATE:
* arms are immutable once frozen,
* assigned ≠ exposed, missing ≠ zero,
* the window closes once, after it elapsed,
* without enough data the system records INSUFFICIENT_DATA — never a result,
* the verdict links back to the originating insight.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta

import pytest

from app.database import SessionLocal
from app.models import Customer, Experiment, Insight
from app.services import experiments as ex


def _customers(db, n, tag):
    ids = []
    for i in range(n):
        c = Customer(name=f"V38X{tag}{i}", phone=f"0912000{tag}{i:04d}"[-11:] if False else None)
        db.add(c)
        db.flush()
        ids.append(c.id)
    db.commit()
    return ids


def _backdate(exp_id, days=30):
    s = SessionLocal()
    try:
        e = s.get(Experiment, exp_id)
        e.started_at = datetime.utcnow() - timedelta(days=days)
        s.commit()
    finally:
        s.close()


def test_full_lifecycle_to_complete(client):
    s = SessionLocal()
    try:
        ids = _customers(s, 220, "a")
        e = ex.create(s, name="V38 coupon test", hypothesis="h", action_type="personal_coupons")
        info = ex.plan(s, e, customer_ids=ids, baseline_rate=0.2, minimum_lift=0.2)
        assert info["planned_per_arm"] >= 100 and e.status == "PLANNED"
        arms = ex.assign(s, e)
        assert arms["treatment"] + arms["control"] == 220 and e.status == "ASSIGNED"
        with pytest.raises(ex.ExperimentError):
            ex.assign(s, e)  # immutable: exactly once
        ex.start(s, e)
        assert e.status == "RUNNING"
        t = json.loads(e.treatment)
        c = json.loads(e.control)
        for i, cid in enumerate(t):
            ex.record_exposure(s, e, cid)
            ex.record_outcome(s, e, cid, profit=1000.0 + (i % 7) * 100.0,
                              purchased=True, variable_cost=50.0)
        for i, cid in enumerate(c):
            ex.record_exposure(s, e, cid)
            ex.record_outcome(s, e, cid, profit=100.0 + (i % 5) * 10.0,
                              purchased=True, variable_cost=0.0)
        s.commit()
        eid = e.id
    finally:
        s.close()
    _backdate(eid)
    s = SessionLocal()
    try:
        e = s.get(Experiment, eid)
        cov = ex.close(s, e)
        assert cov["missing"] == [] and e.status == "OBSERVING"
        with pytest.raises(ex.ExperimentError):
            ex.close(s, e)  # window closes once
        res = ex.evaluate(s, e, seed=7)
        s.commit()
        assert res["status"] == "COMPLETE", res
        assert res["decision"] in ("ACCEPT_FOR_RETEST", "NO_ACTION", "REJECT")
        assert res["coverage"]["outcomes_treatment"] == len(json.loads(e.treatment))
        assert e.status == "COMPLETE"
    finally:
        s.close()


def test_insufficient_data_makes_no_result(client):
    s = SessionLocal()
    try:
        ids = _customers(s, 12, "b")
        e = ex.create(s, name="V38 small test")
        ex.plan(s, e, customer_ids=ids, baseline_rate=0.2, minimum_lift=0.05)
        ex.assign(s, e)
        ex.start(s, e)
        t = json.loads(e.treatment)
        for cid in t:  # outcomes for SOME treatment customers only; control missing
            ex.record_outcome(s, e, cid, profit=500.0, purchased=True, variable_cost=None)
        s.commit()
        eid = e.id
    finally:
        s.close()
    _backdate(eid)
    s = SessionLocal()
    try:
        e = s.get(Experiment, eid)
        ex.close(s, e)
        res = ex.evaluate(s, e)
        s.commit()
        assert res["status"] == "INSUFFICIENT_DATA", res
        assert res["decision"] == "NO_ACTION"
        assert "net_profit_per_customer" not in res, "no data ⇒ no number"
        assert e.status == "OBSERVING", "stays open for late outcomes, never COMPLETE"
        assert len(ex.coverage(e)["missing"]) > 0
    finally:
        s.close()


def test_window_and_membership_guards(client):
    s = SessionLocal()
    try:
        ids = _customers(s, 10, "c")
        e = ex.create(s, name="V38 guards")
        with pytest.raises(ex.ExperimentError):
            ex.assign(s, e)  # PLAN first
        ex.plan(s, e, customer_ids=ids, baseline_rate=0.2, minimum_lift=0.05)
        ex.assign(s, e)
        with pytest.raises(ex.ExperimentError):
            ex.record_exposure(s, e, ids[0])  # START first
        ex.start(s, e)
        with pytest.raises(ex.ExperimentError):
            ex.close(s, e)  # window has not elapsed
        with pytest.raises(ex.ExperimentError):
            ex.record_outcome(s, e, 999999999, profit=1, purchased=True, variable_cost=0)
        with pytest.raises(ex.ExperimentError):
            ex.evaluate(s, e)  # CLOSE first
        ex.cancel(s, e)
        assert e.status == "CANCELLED"
        s.commit()
    finally:
        s.close()


def test_verdict_links_back_to_insight(client):
    s = SessionLocal()
    try:
        ids = _customers(s, 210, "d")
        ins = Insight(kind="V38X", dedupe_key="v38x:link", title="t", body="b", status="ACCEPTED")
        s.add(ins)
        s.flush()
        e = ex.create(s, name="V38 link test", insight_id=ins.id)
        ex.plan(s, e, customer_ids=ids, baseline_rate=0.2, minimum_lift=0.2)
        ex.assign(s, e)
        ex.start(s, e)
        t = json.loads(e.treatment)
        c = json.loads(e.control)
        for i, cid in enumerate(t):
            ex.record_outcome(s, e, cid, profit=200.0 + i, purchased=True, variable_cost=0.0)
        for i, cid in enumerate(c):
            ex.record_outcome(s, e, cid, profit=100.0 + i, purchased=True, variable_cost=0.0)
        s.commit()
        eid, iid = e.id, ins.id
    finally:
        s.close()
    _backdate(eid)
    s = SessionLocal()
    try:
        e = s.get(Experiment, eid)
        ex.close(s, e)
        ex.evaluate(s, e, seed=3)
        s.commit()
        ev = json.loads(s.get(Insight, iid).evidence)
        assert ev["experiment"]["id"] == eid
        assert ev["experiment"]["decision"] in ("ACCEPT_FOR_RETEST", "NO_ACTION", "REJECT")
    finally:
        s.close()
