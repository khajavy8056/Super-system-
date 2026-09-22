# -*- coding: utf-8 -*-
"""v3.8 — Action Engine proof (user order §4).

VALIDATE → SAVEPOINT → EXECUTE → VERIFY → COMMIT, per action:
* bad params fail validation before any write,
* a crashing action rolls back only itself (partial failure survives),
* every outcome is verifiable and traceable in evidence["executions"],
* actions with consequences outside the DB are flagged before they run.
"""
from __future__ import annotations

import json

from app.database import SessionLocal
from app.models import Insight, SystemSetting
from app.services import insights as svc
from sqlalchemy import select


def _insight(db, actions, kind="V38A"):
    row = Insight(kind=kind, dedupe_key=f"v38a:{id(actions)}:{len(actions)}",
                  title="t", body="b", status="NEW",
                  actions=json.dumps(actions),
                  metric=json.dumps({"metric": "avg_basket_size", "window_days": 28}))
    db.add(row)
    db.commit()
    return row


def test_validate_execute_verify_and_trace(client):
    s = SessionLocal()
    try:
        row = _insight(s, [
            {"type": "set_setting", "params": {"key": "v38.probe", "value": "1"}},
            {"type": "note", "params": {}},
        ])
        res = svc.accept(s, row, user=None)
        kinds = {o["type"]: o["status"] for o in res["executed"]}
        assert kinds == {"set_setting": "EXECUTED_VERIFIED", "note": "EXECUTED_VERIFIED"}, res
        assert s.execute(select(SystemSetting).where(SystemSetting.key == "v38.probe")).scalar_one().value == "1"
        ev = json.loads(s.get(Insight, row.id).evidence)
        assert [e["status"] for e in ev["executions"]] == ["EXECUTED_VERIFIED", "EXECUTED_VERIFIED"]
        assert all("verify" in e for e in ev["executions"])
    finally:
        s.close()


def test_validation_fails_before_any_write_and_partial_survives(client):
    s = SessionLocal()
    try:
        row = _insight(s, [
            {"type": "set_setting", "params": {"key": "v38.partial", "value": "yes"}},
            {"type": "set_price", "params": {"batch_id": 1}},  # missing sell_price
            {"type": "no_such_action", "params": {}},
        ])
        res = svc.accept(s, row, user=None)
        kinds = {o["type"]: o["status"] for o in res["executed"]}
        assert kinds["set_setting"] == "EXECUTED_VERIFIED"
        assert kinds["set_price"] == "VALIDATION_FAILED"
        assert kinds["no_such_action"] == "VALIDATION_FAILED"
        assert "missing param" in [o for o in res["executed"] if o["type"] == "set_price"][0]["error"]
        assert s.execute(select(SystemSetting).where(SystemSetting.key == "v38.partial")).scalar_one().value == "yes"
    finally:
        s.close()


def test_crash_rolls_back_only_itself(client, monkeypatch):
    from app.services import insight_actions as acts

    def boom(db, insight, params, user):
        db.add(SystemSetting(key="v38.boom", value="1"))
        db.flush()
        raise RuntimeError("mid-write crash")

    monkeypatch.setitem(acts.ACTIONS, "v38boom", boom)
    monkeypatch.setitem(acts.ACTION_SPECS, "v38boom",
                        {"required": {}, "reversible": True, "external_side_effect": False, "verify": None})
    s = SessionLocal()
    try:
        row = _insight(s, [
            {"type": "set_setting", "params": {"key": "v38.survivor", "value": "1"}},
            {"type": "v38boom", "params": {}},
        ])
        res = svc.accept(s, row, user=None)
        kinds = {o["type"]: o["status"] for o in res["executed"]}
        assert kinds["v38boom"] == "FAILED_ROLLED_BACK"
        assert kinds["set_setting"] == "EXECUTED_VERIFIED"
        assert s.execute(select(SystemSetting).where(SystemSetting.key == "v38.boom")).scalar_one_or_none() is None
        assert s.execute(select(SystemSetting).where(SystemSetting.key == "v38.survivor")).scalar_one() is not None
    finally:
        s.close()


def test_external_side_effects_are_flagged(client):
    s = SessionLocal()
    try:
        row = _insight(s, [{"type": "visit_sms", "params": {"customers": []}}])
        res = svc.accept(s, row, user=None)
        o = res["executed"][0]
        assert o["external_side_effect"] is True
        assert o["status"] in ("EXECUTED_VERIFIED", "SKIPPED")
    finally:
        s.close()
