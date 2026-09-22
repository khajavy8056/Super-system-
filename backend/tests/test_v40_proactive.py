# -*- coding: utf-8 -*-
"""v4.0 — Proactive engine: it must speak up, but never nag (§24, §25).

A shop assistant that produces cards every time it runs is worse than one that
stays quiet: the owner stops reading. These tests pin the anti-spam rules and the
honesty rules at the same time:

* a real cash crunch *is* raised, with its numbers;
* running again does not raise the same card twice (dedupe);
* a card the owner closed is not re-raised inside its cooldown;
* the ceiling comes from the policy table, and zero is allowed;
* a healthy shop gets **no** cards at all;
* nothing is acted on — proactive runs create decisions, never prices or SMS.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.database import init_db
from app.models import BrainDecision, SystemSetting
from app.services import accounting as acc
from app.services.business_brain import policies, proactive
from _v40_seed import fresh_store, seed_shop


@pytest.fixture(scope="module", autouse=True)
def _schema():
    init_db()
    yield


def _engine(db, **kw):
    return proactive.evaluate(db, persist=True, **kw)


def test_a_real_cash_crunch_is_raised_with_its_numbers():
    db = fresh_store()
    try:
        seed_shop(db, tag="p1")
        out = _engine(db, force=True)
        jobs = {a["job"] for a in out["alerts"]}
        assert {"cash_watch", "cheque_watch"} & jobs, jobs
        cash = next((a for a in out["alerts"] if a["domain"] == "finance"), None)
        assert cash is not None
        assert "تومان" in cash["problem"], cash["problem"]
        assert ("چک" in cash["problem"] or "تعهد" in cash["problem"]), cash["problem"]
        for alert in out["alerts"]:
            assert alert["decision_id"], "every card is backed by a decision row"
            assert alert["reason"] and alert["problem"]
    finally:
        db.close()


def test_the_same_card_is_not_raised_twice():
    db = fresh_store()
    try:
        seed_shop(db, tag="p2")
        first = _engine(db, force=True)
        assert first["alerts"]
        keys = {a["dedupe_key"] for a in first["alerts"]}
        second = _engine(db, force=True)
        assert not ({a["dedupe_key"] for a in second["alerts"]} & keys), \
            "a card that is still open must never be raised again"
        reasons = {s["reason"] for s in second["skipped"]}
        assert "ALREADY_ON_DESK" in reasons
    finally:
        db.close()


def test_a_closed_card_respects_its_cooldown_then_returns():
    db = fresh_store()
    try:
        seed_shop(db, tag="p3")
        out = _engine(db, force=True)
        card = next(a for a in out["alerts"] if a["job"] in ("cash_watch", "cheque_watch"))
        row = db.get(BrainDecision, card["decision_id"])
        row.status = "RESOLVED"
        db.commit()

        # a manual run may look again immediately, but it must respect the cooldown
        again = _engine(db)
        assert all(a["dedupe_key"] != card["dedupe_key"] for a in again["alerts"]), "cooldown must hold"
        assert any(s["reason"] == "COOLDOWN" for s in again["skipped"])

        # …and once the cooldown has passed, the engine is allowed to speak again
        from sqlalchemy import update

        db.execute(update(BrainDecision).where(BrainDecision.id == row.id)
                   .values(updated_at=row.created_at - timedelta(days=5)))
        db.commit()
        later = _engine(db)
        assert any(a["dedupe_key"] == card["dedupe_key"] for a in later["alerts"]), \
            "a problem that is still there must come back after its cooldown"
    finally:
        db.close()


def test_the_alert_ceiling_comes_from_the_policy_table_and_zero_is_allowed():
    db = fresh_store()
    try:
        seed_shop(db, tag="p4")
        policies.set_value(db, "max_active_alerts", 0, source="OWNER")
        db.commit()
        out = _engine(db, force=True)
        assert out["alerts"] == [], "a zero ceiling means the owner asked to be left alone"
        assert any(s["reason"] == "ALERT_LIMIT" for s in out["skipped"])

        policies.set_value(db, "max_active_alerts", 5, source="OWNER")
        db.commit()
        out = _engine(db, force=True)
        assert out["alerts"], "with a ceiling restored the engine speaks again"
        domains = [a["domain"] for a in out["alerts"]]
        assert len(domains) == len(set(domains)), "one card per domain per pass (clustering)"
    finally:
        db.close()


def test_a_healthy_shop_gets_no_cards():
    db = fresh_store()
    try:
        seed_shop(db, tag="p5", cheques=(), receivables=(0, 0), expiring_batch=False)
        # a comfortable buffer and no obligations at all
        acc.post(db, kind="OPENING",
                 lines=[acc.Line(acc.A_CASH, debit=200_000_000),
                        acc.Line(acc.A_CAPITAL, credit=200_000_000)], description="buffer")
        db.commit()
        out = _engine(db, force=True)
        assert out["alerts"] == [], out["alerts"]
        assert all(s["reason"] in ("NOTHING_TO_REPORT", "NO_ACTIONABLE_OPTION") for s in out["skipped"])
        assert proactive.status(db)["open_cards"] == 0
    finally:
        db.close()


def test_an_empty_shop_is_silent():
    db = fresh_store()
    try:
        out = _engine(db, force=True)
        assert out["alerts"] == []
    finally:
        db.close()


def test_proactive_never_touches_the_shop_data():
    """The engine proposes; the Action Engine (after approval) is what acts."""
    db = fresh_store()
    try:
        shop = seed_shop(db, tag="p6")
        from app.models import ProductBatch
        from app.models.system import SmsMessage

        before_batches = [(b.id, float(b.sell_price)) for b in db.query(ProductBatch).all()]
        before_sms = db.query(SmsMessage).count()
        before_campaigns = db.query(SystemSetting).filter(
            SystemSetting.key.like("campaign%")).count()

        out = _engine(db, force=True)
        assert out["alerts"]

        after_batches = [(b.id, float(b.sell_price)) for b in db.query(ProductBatch).all()]
        assert before_batches == after_batches, "no price may change without approval"
        assert db.query(SmsMessage).count() == before_sms, "no SMS may be sent without approval"
        assert db.query(SystemSetting).filter(SystemSetting.key.like("campaign%")).count() == before_campaigns
    finally:
        db.close()


def test_status_is_json_serialisable_and_reports_the_last_run():
    import json

    db = fresh_store()
    try:
        seed_shop(db, tag="p7")
        assert proactive.last_run(db) is None
        _engine(db, force=True)
        status = proactive.status(db)
        json.dumps(status, default=str)
        assert status["last_run"] is not None
        assert "cash_watch" in status["jobs"] and len(status["jobs"]) == 8
    finally:
        db.close()


def test_a_broken_job_does_not_stop_the_others(monkeypatch):
    db = fresh_store()
    try:
        seed_shop(db, tag="p8")

        def broken(*args, **kwargs):
            raise RuntimeError("boom")

        monkeypatch.setattr(proactive, "JOBS", (("broken_watch", broken),) + proactive.JOBS[1:])
        out = _engine(db, force=True)
        assert any(s["reason"] == "ERROR" for s in out["skipped"])
        assert out["alerts"], "the remaining watchers must still run"
    finally:
        db.close()


def test_the_proactive_cards_are_the_ones_the_api_shows():
    db = fresh_store()
    try:
        seed_shop(db, tag="p9")
        out = _engine(db, force=True)
        shown = proactive.recommendations(db)
        assert [c["id"] for c in shown] == [a["decision_id"] for a in out["alerts"]]
        for card in shown:
            assert set(card) >= {"id", "title", "status", "priority"}, card.keys()
    finally:
        db.close()
