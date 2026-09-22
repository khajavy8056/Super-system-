"""v4.0 — Follow-up Engine (§14, §50).

«فردا یادم بنداز ببینیم این جشنواره جواب داده یا نه» has to become a *record*,
not a sentence in a chat log. A follow-up is created by the brain (or by the
owner), carries a due date, and when it comes due the operational scanner (§26)
turns it into a notification — once, not once per tick.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...models import BrainDecision, BrainFollowup
from ..notifications import notify
from . import persian as fa

KINDS = ("REMIND", "MEASURE", "SUPPLIER", "CUSTOMER", "DATA", "CUSTOM")
DEFAULT_DAYS = {"MEASURE": 7, "REMIND": 1, "SUPPLIER": 3, "CUSTOMER": 14, "DATA": 3, "CUSTOM": 3}


def create(db: Session, *, title: str, due_at=None, days: int | None = None, kind: str = "REMIND",
           note: str = "", decision_id: int | None = None, user_id: int | None = None,
           pending_sync: bool = False) -> BrainFollowup:
    if due_at is None:
        due_at = datetime.utcnow() + timedelta(days=days if days is not None else DEFAULT_DAYS.get(kind, 3))
    elif isinstance(due_at, str):
        due_at = datetime.fromisoformat(due_at.replace("Z", ""))
    row = BrainFollowup(kind=kind if kind in KINDS else "REMIND", title=title[:255], note=note,
                        due_at=due_at, decision_id=decision_id, created_by=user_id,
                        pending_sync=pending_sync, status="OPEN")
    db.add(row)
    db.flush()
    return row


def for_decision(db: Session) -> list[dict]:
    rows = db.execute(select(BrainFollowup).where(BrainFollowup.decision_id.isnot(None))
                      .order_by(BrainFollowup.due_at.desc()).limit(50)).scalars().all()
    return [to_dict(r) for r in rows]


def open_items(db: Session, *, limit: int = 50) -> list[dict]:
    rows = db.execute(select(BrainFollowup).where(BrainFollowup.status == "OPEN")
                      .order_by(BrainFollowup.due_at).limit(limit)).scalars().all()
    return [to_dict(r) for r in rows]


def due_items(db: Session, *, now: datetime | None = None, limit: int = 20) -> list[BrainFollowup]:
    now = now or datetime.utcnow()
    return list(db.execute(select(BrainFollowup).where(BrainFollowup.status == "OPEN",
                                                       BrainFollowup.due_at <= now)
                           .order_by(BrainFollowup.due_at).limit(limit)).scalars())


def resolve(db: Session, followup_id: int, *, result: str = "", user_id: int | None = None) -> dict:
    row = db.get(BrainFollowup, followup_id)
    if row is None:
        return {"ok": False, "error": "FOLLOWUP_NOT_FOUND"}
    row.status = "DONE"
    row.result = result
    row.resolved_at = datetime.utcnow()
    db.flush()
    # resolving a measurement follow-up triggers the measurement itself (§55)
    if row.decision_id and row.kind == "MEASURE":
        from .decisions import measure
        decision = db.get(BrainDecision, row.decision_id)
        if decision is not None:
            try:
                measure(db, decision, user_id=user_id)
            except Exception:  # noqa: BLE001 — a failed measurement must not lose the follow-up
                from .audit import log
                log(db, event="BRAIN_MEASURE_FAILED", decision_id=row.decision_id)
    return {"ok": True, "followup": to_dict(row)}


def cancel(db: Session, followup_id: int, *, reason: str = "") -> dict:
    row = db.get(BrainFollowup, followup_id)
    if row is None:
        return {"ok": False, "error": "FOLLOWUP_NOT_FOUND"}
    row.status = "CANCELLED"
    row.result = reason
    row.resolved_at = datetime.utcnow()
    db.flush()
    return {"ok": True, "followup": to_dict(row)}


def notify_due(db: Session, *, now: datetime | None = None) -> int:
    """Worker hook: one notification per follow-up, never repeated."""
    now = now or datetime.utcnow()
    sent = 0
    for row in due_items(db, now=now):
        if row.notified_at is not None:
            continue
        notify(db, type="BRAIN_FOLLOWUP", title="پیگیری سررسید شد: " + row.title,
               body=(row.note or "")[:400], severity="WARN", reference_type="BrainFollowup",
               reference_id=row.id)
        row.notified_at = now
        sent += 1
    if sent:
        db.flush()
    return sent


def auto_for_decision(db: Session, decision: BrainDecision, *, user_id: int | None = None) -> BrainFollowup | None:
    """Every executed decision gets a measurement appointment — automatically.

    Without this, a decision is executed and then nobody ever checks whether it
    worked; with it, the measurement window has an owner and a date.
    """
    if decision.status not in ("COMPLETED", "MONITORING", "RUNNING"):
        return None
    exists = db.execute(select(BrainFollowup).where(BrainFollowup.decision_id == decision.id,
                                                    BrainFollowup.kind == "MEASURE")).scalar_one_or_none()
    if exists:
        return exists
    window = 7
    try:
        import json
        window = int(json.loads(decision.measurement or "{}").get("window_days") or 7)
    except (TypeError, ValueError):
        pass
    return create(db, title=f"سنجش نتیجه: {decision.title[:120]}", kind="MEASURE",
                  days=max(2, window), note="بررسی کن که این تصمیم اثر داشت یا نه",
                  decision_id=decision.id, user_id=user_id)


def to_dict(row: BrainFollowup) -> dict:
    return {"id": row.id, "title": row.title, "kind": row.kind, "note": row.note, "status": row.status,
            "decision_id": row.decision_id, "due_at": row.due_at.isoformat() if row.due_at else None,
            "due_at_fa": fa.fa_date(row.due_at, with_time=False) if row.due_at else None,
            "overdue": bool(row.due_at and row.due_at <= datetime.utcnow() and row.status == "OPEN"),
            "notified_at": row.notified_at.isoformat() if row.notified_at else None,
            "resolved_at": row.resolved_at.isoformat() if row.resolved_at else None,
            "result": row.result, "pending_sync": bool(row.pending_sync)}
