# -*- coding: utf-8 -*-
"""v4.0 — the brain API over real HTTP: does what the owner pressed actually stick?

This file exists because of a bug the unit tests could not see. `get_db` yields a
session and closes it **without committing** — every router in this product
commits its own writes — so the first version of `/api/brain` returned a
perfectly happy ``{"ok": true, "executed": [...]}`` for an approval and then threw
the whole thing away: the card was back on the desk, the SMS queue was empty and
no measurement appointment existed.

The three tests below walk the two journeys that matter and check the database
**from a brand-new session**, so a missing commit cannot hide behind the session
the request just used:

1. the owner asks something → the conversation and its decision are on disk;
2. the owner approves a card → the decision, its execution record and the
   follow-up that will measure it are all on disk;
3. the owner rejects/snoozes → that state is on disk too, and nothing executed.
"""
from __future__ import annotations

import json

from app.database import SessionLocal
from app.models import BrainDecision, BrainFollowup, BrainMessage
from app.services.business_brain import decisions as decision_svc
from app.services.business_brain import policies


def _fresh() -> "SessionLocal":
    return SessionLocal()


def _card(db, *, title: str, actions=None, requires_approval: bool = True) -> BrainDecision:
    """A decision card with one harmless, internal action."""
    policies.ensure_defaults(db)
    row = decision_svc.create(
        db, title=title, problem="فشار نقدی هفتهٔ آینده", reason="برای تست مسیر تأیید",
        options=[{"id": "note_only", "label": "ثبت یادداشت و پیگیری", "description": "بی‌خطر",
                  "requires_approval": requires_approval, "action_class": "APPROVAL", "risk": "low",
                  "reversible": True, "economics": {"gain_toman": 0},
                  "actions": actions if actions is not None else [
                      {"type": "note", "params": {"text": "برای پیگیری: وصول مطالبات"}, "label": "یادداشت"}]}],
        evidence=[], situation={}, requires_approval=requires_approval)
    db.commit()
    return row


# --------------------------------------------------------------------------- chat
def test_a_chat_turn_is_written_to_memory(client, auth_headers):
    before = _fresh()
    try:
        seen = before.query(BrainMessage).count()
    finally:
        before.close()

    response = client.post("/api/brain/chat", headers=auth_headers,
                           json={"question": "وضعیت فروشگاه چطوره؟", "prefer_llm": False})
    assert response.status_code == 200, response.text
    answer = response.json()
    assert answer["text"] and "{" not in answer["text"][:200], "raw JSON must never reach the owner"

    after = _fresh()
    try:
        assert after.query(BrainMessage).count() > seen, \
            "a chat turn that is never committed is a brain with amnesia"
        history = client.get("/api/brain/chat/history", headers=auth_headers).json()["messages"]
        assert any("وضعیت فروشگاه" in json.dumps(m, ensure_ascii=False) for m in history)
    finally:
        after.close()


# --------------------------------------------------------------------------- approval
def test_approving_a_card_persists_the_execution_and_the_measurement(client, auth_headers):
    db = _fresh()
    try:
        row = _card(db, title=f"تأیید API — {__name__}")
        decision_id = row.id
    finally:
        db.close()

    response = client.post(f"/api/brain/decisions/{decision_id}/approve",
                           headers=auth_headers, json={})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["ok"] is True, body
    assert body["status"] == "COMPLETED", body
    assert body["followup_id"], "an executed decision owes the owner a measurement appointment"

    # a NEW session: the only way to see what really reached the database
    check = _fresh()
    try:
        row = check.get(BrainDecision, decision_id)
        assert row.status == "COMPLETED", f"approval was rolled back ({row.status})"
        assert row.selected_option == "note_only"
        assert json.loads(row.approval or "{}").get("approved_by"), "who approved must be recorded"
        executed = json.loads(row.execution or "{}").get("executions") or []
        assert executed and all(e.get("ok") for e in executed), executed
        followup = check.get(BrainFollowup, body["followup_id"])
        assert followup is not None and followup.due_at is not None, \
            "the measurement contract must survive the request"
        assert followup.decision_id == decision_id
    finally:
        check.close()


# --------------------------------------------------------------------------- reject / snooze
def test_rejecting_a_card_is_recorded_and_executes_nothing(client, auth_headers):
    db = _fresh()
    try:
        row = _card(db, title=f"رد API — {__name__}")
        decision_id = row.id
    finally:
        db.close()

    response = client.post(f"/api/brain/decisions/{decision_id}/reject",
                           headers=auth_headers, json={"reason": "الان صلاح نیست"})
    assert response.status_code == 200, response.text

    check = _fresh()
    try:
        row = check.get(BrainDecision, decision_id)
        assert row.status in ("RESOLVED", "NO_ACTION", "FAILED"), row.status
        assert json.loads(row.execution or "{}").get("executions") in (None, []), \
            "a rejected card must not have run anything"
        assert row.status != "COMPLETED"
    finally:
        check.close()

    from app.models import BrainFollowup

    before = _fresh()
    try:
        reminders = before.query(BrainFollowup).filter(BrainFollowup.decision_id == decision_id).count()
    finally:
        before.close()

    snooze = client.post(f"/api/brain/decisions/{decision_id}/snooze",
                         headers=auth_headers, json={"days": 5})
    assert snooze.status_code == 200, snooze.text
    check = _fresh()
    try:
        row = check.get(BrainDecision, decision_id)
        assert row.status != "COMPLETED", "a snoozed card has not run"
        reminders_after = check.query(BrainFollowup).filter(BrainFollowup.decision_id == decision_id).count()
        assert reminders_after > reminders, "«بعداً» must leave a reminder on disk, not just a toast"
    finally:
        check.close()
