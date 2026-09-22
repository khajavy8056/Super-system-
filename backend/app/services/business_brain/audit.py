"""v4.0 — Brain audit trail.

The Action Engine already audits every *execution* (``INSIGHT_ACTION`` /
``INSIGHT_ACCEPTED``). What it cannot audit is the reasoning *before* an action
exists: which tools ran, which model answered, which policy blocked something,
that the model tried to quote a number nobody computed. Those events land here.

Every entry is a row in the existing ``audit_logs`` table, so the Audit screen,
backup/restore and the retention rules keep working unchanged.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from ..audit import write_audit

EVENTS = {
    "BRAIN_CHAT": "گفت‌وگوی مدیر با مغز کسب‌وکار",
    "BRAIN_SITUATION": "ساخت وضعیت کسب‌وکار",
    "BRAIN_TOOL_DENIED": "تلاش برای فراخوانی ابزار بدون مجوز",
    "BRAIN_NUMBER_REJECTED": "عدد بدون منبع در پاسخ مدل رد شد",
    "BRAIN_DECISION_CREATED": "تصمیم جدید ثبت شد",
    "BRAIN_DECISION_APPROVED": "تصمیم تأیید شد",
    "BRAIN_DECISION_REJECTED": "تصمیم رد شد",
    "BRAIN_DECISION_EXECUTED": "تصمیم اجرا شد",
    "BRAIN_DECISION_FAILED": "اجرای تصمیم شکست خورد",
    "BRAIN_DECISION_MEASURED": "نتیجهٔ تصمیم اندازه‌گیری شد",
    "BRAIN_CONFLICT": "تضاد تصمیم بین دو دستگاه",
    "BRAIN_POLICY_BLOCK": "سیاست فروشگاه مانع اجرا شد",
    "BRAIN_ALERT": "هشدار proactive ساخته شد",
    "BRAIN_MODEL_EVENT": "رویداد مدیریت مدل محلی",
    "BRAIN_DEGRADED": "اجرای حالت سبک/محدود",
    "BRAIN_MEASURE_FAILED": "اندازه‌گیری تصمیم ناموفق بود",
    "BRAIN_OFFLINE_DECISION": "تصمیم آفلاین ثبت شد (در انتظار همگام‌سازی)",
}


def log(db: Session, *, event: str, user_id: int | None = None, decision_id: int | None = None,
        before: dict | None = None, after: dict | None = None, reference: str | None = None) -> None:
    """Write one brain event. Never raises: auditing must not break the answer."""
    try:
        write_audit(db, action=event if event in EVENTS else "BRAIN_EVENT", user_id=user_id,
                    entity_type="BrainDecision" if decision_id else "Brain",
                    entity_id=decision_id, before=before, after=after, reference=reference)
    except Exception:  # pragma: no cover - defensive
        import logging
        logging.getLogger("supermarket.brain.audit").exception("brain audit write failed for %s", event)


def label(event: str) -> str:
    return EVENTS.get(event, event)
