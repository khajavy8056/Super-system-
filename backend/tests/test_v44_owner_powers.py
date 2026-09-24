# -*- coding: utf-8 -*-
"""v4.4.0 — the owner's round-12 rules, locked down as tests.

1. «سلام» is a GREETING, not an inventory question — the model is a language
   model FIRST: greetings/thanks/goodbye answered naturally, the four-part
   business format only for real business questions.
2. The brain reaches settings + customer SMS (consult → set/send) through
   audited, whitelisted tools — with the manager's approval.
3. Reminders: due → notification; unanswered → SMS to the manager, again
   every interval until acknowledged; «دوباره یادآوری کن» pushes the popup.
4. The brain is ALWAYS analysing: a 15-minute worker exists and is guarded.
5. Android: the chat answer carries its decision (تأیید/ویرایش/رد buttons)
   and its reminders; the ready-but-not-ready prefs bug stays dead.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

ANDROID = ROOT / "mobile-android" / "app" / "src" / "main" / "java" / "ir" / "khajavy" / "supermarket"


# --------------------------------------------------------------- rule 1: language model first
def test_greeting_gets_a_greeting_not_inventory():
    """«سلام» must NEVER produce an inventory report (the exact complaint)."""
    from app.services.business_brain.planner import _smalltalk_answer

    reply = _smalltalk_answer("سلام")
    assert reply, "a greeting deserves an answer"
    for word in ("موجودی", "فروش", "وضعیت:", "پیشنهاد:", "اقدام"):
        assert word not in reply, f"small-talk must stay small-talk: {reply}"
    assert _smalltalk_answer("سلام") == _smalltalk_answer("سلام")


def test_thanks_and_goodbye_are_conversation():
    from app.services.business_brain.planner import _smalltalk_answer

    for q in ("مرسی", "ممنون", "متشکرم", "خداحافظ"):
        assert _smalltalk_answer(q), f"{q!r} must be answered conversationally"
        assert "موجودی" not in _smalltalk_answer(q)


def test_business_questions_still_reach_the_analyser():
    """A question with a real business word is NOT small-talk."""
    from app.services.business_brain.planner import _smalltalk_answer

    assert _smalltalk_answer("موجودی شیر کاله چقدر مونده؟") is None
    assert _smalltalk_answer("فروش امروز چطور بود؟") is None
    assert _smalltalk_answer("") is None
    assert _smalltalk_answer(None) is None
    assert _smalltalk_answer("x" * 120) is None


def test_chat_greeting_over_api(auth_headers, client):
    """End-to-end: the API answer to «سلام» has no numbers section."""
    r = client.post("/api/brain/chat", headers=auth_headers,
                    json={"question": "سلام", "prefer_llm": False})
    assert r.status_code == 200, r.text
    text = r.json()["text"]
    assert text and "{" not in text[:200]
    assert "موجودی" not in text, "a greeting must not be answered with stock levels"
    assert r.json()["mode"] == "deterministic"


def test_system_prompt_is_language_model_first():
    from app.services.business_brain.prompts import SYSTEM_PROMPT

    assert "مدل زبانی" in SYSTEM_PROMPT
    assert "احوال‌پرسی" in SYSTEM_PROMPT
    # the four-part format is now conditional, not the default shape
    assert "فقط وقتی سؤال واقعاً" in SYSTEM_PROMPT


# --------------------------------------------------------------- rule 2: settings + SMS powers
def test_setting_tools_are_whitelisted():
    """The brain may only touch the keys on the owner-approved list."""
    from app.services.business_brain.tools import SETTING_WHITELIST

    assert "sms.reminder_template" in SETTING_WHITELIST
    assert "brain.manager_phone" in SETTING_WHITELIST
    assert "sms.password" not in SETTING_WHITELIST, "secrets are never brain-writable"
    assert "license" not in " ".join(SETTING_WHITELIST)


def test_registry_has_the_new_powers():
    from app.services.business_brain.registry import REGISTRY

    names = set(REGISTRY.names())
    assert {"get_setting", "set_setting", "sms_draft"} <= names
    # approval-class: set_setting/sms_draft are gated behind the manager's تأیید
    spec = REGISTRY.get("set_setting")
    assert "settings.manage" in spec.permissions
    spec = REGISTRY.get("sms_draft")
    assert "settings.manage" in spec.permissions and spec.side_effects


def test_set_setting_tool_writes_and_reads(auth_headers, client):
    from app.database import SessionLocal
    from app.models import SystemSetting
    from app.services.business_brain.context import ToolContext
    from app.services.business_brain.tools import get_setting_tool, set_setting_tool

    db = SessionLocal()
    try:
        ctx = ToolContext(db=db, system=True)
        out = set_setting_tool(ctx, {"key": "sms.reminder_template",
                                     "value": "مشتری گرامی، سفارش شما آماده است."})
        assert "DENIED_KEY" not in out.get("flags", [])
        db.commit()
        row = db.query(SystemSetting).filter_by(key="sms.reminder_template").one()
        assert row.value == "مشتری گرامی، سفارش شما آماده است."

        got = get_setting_tool(ctx, {"key": "sms.reminder_template"})
        assert "آماده است" in got["summary"]
        denied = get_setting_tool(ctx, {"key": "sms.password"})
        assert "DENIED_KEY" in denied.get("flags", [])
    finally:
        db.close()


def test_sms_draft_needs_the_manager_approval(auth_headers, client):
    """The brain may DRAFT a customer SMS, but the send only happens via the
    decision the manager approves — never directly from the tool."""
    from app.database import SessionLocal
    from app.models import Customer
    from app.services.business_brain.context import ToolContext
    from app.services.business_brain.tools import sms_draft

    db = SessionLocal()
    try:
        cust = db.query(Customer).first()
        if cust is None:
            cust = Customer(name="مشتری آزمون", phone="09120000001")
            db.add(cust)
            db.flush()
        ctx = ToolContext(db=db, system=True)
        out = sms_draft(ctx, {"customer_id": cust.id, "text": "سلام، تخفیف ویژه امروز"})
        assert out["details"]["decision_id"], "a draft must raise a decision"
        db.commit()
        from app.models.brain import BrainDecision
        row = db.query(BrainDecision).get(out["details"]["decision_id"])
        assert row.status == "WAITING_APPROVAL"
        opts = __import__("json").loads(row.options)
        assert opts[0]["actions"][0]["type"] == "personal_sms"
    finally:
        db.close()


# --------------------------------------------------------------- rule 3: the reminder loop
def test_reminder_escalates_to_manager_sms(auth_headers, client):
    """Due → notified; still unanswered after the interval → SMS to manager;
    and AGAIN after another interval — until acknowledged."""
    from app.database import SessionLocal
    from app.models import SmsMessage
    from app.models.brain import BrainFollowup
    from app.services.business_brain import followups as fsvc

    db = SessionLocal()
    try:
        from app.models import SystemSetting
        db.query(SmsMessage).delete()
        db.query(BrainFollowup).delete()
        _set(db, "brain.manager_phone", "09121112233")
        _set(db, "brain.reminder_escalate_hours", "3")
        db.commit()

        row = BrainFollowup(kind="REMIND", title="پیگیری سفارش قفسه",
                            due_at=datetime.utcnow() - timedelta(hours=1))
        db.add(row)
        db.commit()

        # 1st pass: notification only
        n1 = fsvc.notify_due(db)
        assert n1 == 1 and row.notified_at is not None
        assert db.query(SmsMessage).count() == 0, "no SMS before the interval"

        # not yet 3h → still no SMS
        assert fsvc.notify_due(db, now=datetime.utcnow() + timedelta(hours=1)) == 0

        # 3h passed, still open → SMS #1 to the manager
        later = datetime.utcnow() + timedelta(hours=4)
        assert fsvc.notify_due(db, now=later) == 1
        msgs = db.query(SmsMessage).all()
        assert len(msgs) == 1 and msgs[0].phone == "09121112233"
        assert "پیگیری سفارش قفسه" in msgs[0].text

        # re-sent only after ANOTHER interval, never on every tick
        assert fsvc.notify_due(db, now=later + timedelta(minutes=30)) == 0
        assert fsvc.notify_due(db, now=later + timedelta(hours=4)) == 1
        assert db.query(SmsMessage).count() == 2

        # acknowledged → the loop ends
        assert fsvc.acknowledge(db, row.id)["ok"] is True
        after = fsvc.notify_due(db, now=later + timedelta(hours=12))
        assert db.query(SmsMessage).count() == 2, "no SMS after «انجام شد»"
    finally:
        db.query(SmsMessage).delete()
        db.query(BrainFollowup).delete()
        from app.models import SystemSetting as _SS
        db.query(_SS).filter(_SS.key.in_(("brain.manager_phone",
                                          "brain.reminder_escalate_hours"))).delete()
        db.commit()
        db.close()


def test_snooze_brings_the_popup_back():
    from app.database import SessionLocal
    from app.models.brain import BrainFollowup
    from app.services.business_brain import followups as fsvc

    db = SessionLocal()
    try:
        db.query(BrainFollowup).delete()
        db.commit()
        row = BrainFollowup(kind="REMIND", title="تماس با تأمین‌کننده",
                            due_at=datetime.utcnow() - timedelta(minutes=5))
        db.add(row)
        db.commit()
        fsvc.notify_due(db)
        assert row.notified_at is not None

        out = fsvc.snooze(db, row.id, hours=2)
        assert out["ok"] is True
        assert row.notified_at is None, "snooze clears the escalation clock"
        assert row.due_at > datetime.utcnow(), "snooze pushes the due time forward"
        # a snoozed reminder is not due yet → no popup, no SMS
        assert fsvc.due_items(db) == []
    finally:
        db.query(BrainFollowup).delete()
        db.commit()
        db.close()


def test_reminder_api_endpoints(auth_headers, client):
    """The phone's loop: poll due, ack, snooze."""
    from app.database import SessionLocal
    from app.models.brain import BrainFollowup

    db = SessionLocal()
    try:
        db.query(BrainFollowup).delete()
        db.commit()
        row = BrainFollowup(kind="REMIND", title="یادآوری تست",
                            due_at=datetime.utcnow() - timedelta(minutes=1))
        db.add(row)
        db.commit()

        due = client.get("/api/brain/reminders/due", headers=auth_headers)
        assert due.status_code == 200, due.text
        items = due.json()["reminders"]
        assert any(i["id"] == row.id for i in items)

        sn = client.post(f"/api/brain/reminders/{row.id}/snooze", headers=auth_headers,
                         json={"hours": 2})
        assert sn.status_code == 200 and sn.json()["ok"], sn.text
        db.expire_all()                      # the API wrote through its own session
        assert db.query(BrainFollowup).get(row.id).due_at > datetime.utcnow()

        ack = client.post(f"/api/brain/reminders/{row.id}/ack", headers=auth_headers)
        assert ack.status_code == 200 and ack.json()["ok"], ack.text
        db.expire_all()
        assert db.query(BrainFollowup).get(row.id).status == "DONE"
    finally:
        db.query(BrainFollowup).delete()
        db.commit()
        db.close()


# --------------------------------------------------------------- rule 4: always analysing
def test_brain_worker_exists_and_is_guarded():
    """The 15-minute pass: registered in main, env-gated, never raises."""
    import app.main as main_mod

    src = Path(main_mod.__file__).read_text(encoding="utf-8")
    assert "_start_brain_worker()" in src
    assert "SUPERMARKET_BRAIN_WORKER" in src, "must have a kill-switch"
    assert "proactive_svc.evaluate" in src
    # the reminder escalation runs INSIDE the periodic pass
    from app.services.business_brain import proactive as proactive_svc
    body = Path(proactive_svc.__file__).read_text(encoding="utf-8")
    assert "notify_due" in body


# --------------------------------------------------------------- rule 5: Android side
def test_android_chat_has_approval_buttons():
    src = (ANDROID / "BrainScreens.java").read_text(encoding="utf-8")
    assert "approvalButtons" in src, "تأیید/ویرایش/رد under the answer"
    for label in ("تأیید", "ویرایش", "رد"):
        assert f'"{label}"' in src
    assert "/brain/decisions/\" + id + \"/approve" in src
    assert "reminderChip" in src, "a registered reminder shows as a chip"


def test_android_reminder_receiver_exists():
    rx = (ANDROID / "ReminderRx.java").read_text(encoding="utf-8")
    assert "REMINDER_ACK" in rx and "REMINDER_SNOOZE" in rx
    assert "دوباره یادآوری" in rx and "انجام شد" in rx
    manifest = (ANDROID.parents[3] / "AndroidManifest.xml").read_text(encoding="utf-8")
    assert ".ReminderRx" in manifest
    notify = (ANDROID / "Notify.java").read_text(encoding="utf-8")
    assert "ReminderRx.poll" in notify, "the periodic Checker polls reminders"


def test_ready_bug_stays_dead():
    """Regression: stateOf must read through the per-id JSONObject."""
    src = (ANDROID / "BrainModel.java").read_text(encoding="utf-8")
    assert 'one.optString("state", "")' in src
    assert "all.optString(id" not in src, "the org.json trap must not come back"
    # single installed card, no download cards, when a model is ready
    screens = (ANDROID / "BrainScreens.java").read_text(encoding="utf-8")
    assert "BrainModel.readySpec(c);" in screens and "if (rs != null)" in screens
    assert "نصب و تأیید شده" in screens


# ----------------------------------------------------------------- helper
def _set(db, key: str, value: str) -> None:
    """Upsert a system setting the way the app itself does."""
    from app.models import SystemSetting
    row = db.query(SystemSetting).filter_by(key=key).one_or_none()
    if row is None:
        db.add(SystemSetting(key=key, value=value))
    else:
        row.value = value
