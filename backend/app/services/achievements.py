# -*- coding: utf-8 -*-
"""build-488 — امتیاز، دستاورد، مدال و نشان واقعی (§۳۴–۳۵).

قانون سخت‌گیرانه (§۳۴–۳۵): **هیچ امتیازی بدون Event یا Evidence معتبر افزایش
نمی‌یابد.** هر ScoreEvent باید source + evidence (ارجاع به فاکتور/وظیفه/عملیات)
داشته باشد؛ `award()` بدون evidence رد می‌شود.

دستاوردها از فعالیت واقعی استخراج می‌شوند (فروش برتر، دقت، انجام وظایف، انبار …)
و هر کدام شواهدشان را نگه می‌دارند: «این نشان از چه فعالیتی به دست آمده».
"""
from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Achievement, Invoice, ScoreEvent, User

PAID = "PAID"


class AchievementError(Exception):
    def __init__(self, code: str, message: str = ""):
        self.code = code
        super().__init__(message or code)


#: کاتالوگ دستاوردها — code پایدار؛ level با پیشرفت بالا می‌رود (۱ برنز … ۳ طلا)
CATALOG: dict[str, dict] = {
    "TOP_SELLER": {"kind": "MEDAL", "title": "فروش برتر",
                   "description": "بیشترین فروش دوره با شواهد فاکتورهای واقعی"},
    "ACCURATE": {"kind": "BADGE", "title": "دقت بالا",
                 "description": "کمترین خطا/ابطال در فروش"},
    "TASK_MASTER": {"kind": "ACHIEVEMENT", "title": "انجام موفق وظایف",
                    "description": "تکمیل مؤثر وظایف و Actionهای محول‌شده"},
    "STOCK_GUARDIAN": {"kind": "BADGE", "title": "نگهبان انبار",
                       "description": "انبارگردانی دقیق و اختلاف موجودی کم"},
    "RELIABLE": {"kind": "MEDAL", "title": "حضور منظم",
                 "description": "حضور به‌موقع در شیفت‌ها"},
}


def _now() -> datetime:
    return datetime.utcnow()


def award(db: Session, *, user_id: int, code: str, evidence: dict,
          level: int = 1, created_by: int | None = None) -> Achievement | None:
    """اعطای نشان — فقط با evidence معتبر (§۳۵). اگر قبلاً اعطا شده، سطح بالا می‌رود."""
    meta = CATALOG.get(code)
    if meta is None:
        raise AchievementError("UNKNOWN_CODE", f"نشان ناشناخته: {code}")
    if not evidence or not isinstance(evidence, dict) or not evidence.get("event"):
        raise AchievementError("NO_EVIDENCE", "ثبت نشان بدون Evidence معتبر ممنوع است (§۳۵)")
    row = db.execute(select(Achievement).where(
        Achievement.user_id == user_id, Achievement.code == code)).scalar_one_or_none()
    if row is None:
        row = Achievement(user_id=user_id, code=code, kind=meta["kind"],
                          title=meta["title"], description=meta["description"],
                          level=max(1, min(3, int(level))),
                          evidence=json.dumps(evidence, ensure_ascii=False),
                          awarded_at=_now())
        db.add(row)
    else:
        row.level = max(row.level, max(1, min(3, int(level))))
        row.evidence = json.dumps(evidence, ensure_ascii=False)
    db.commit()
    return row


def add_score(db: Session, *, user_id: int, points: int, source: str,
              evidence: dict, note: str | None = None,
              created_by: int | None = None) -> ScoreEvent:
    """ثبت امتیاز — الزاماً با source و evidence (§۳۴)."""
    if not evidence or not evidence.get("ref_type"):
        raise AchievementError("NO_EVIDENCE", "امتیاز بدون ارجاع فعالیت معتبر ممنوع است (§۳۴)")
    if source not in ("SALE", "TASK", "STOCKTAKE", "ACCURACY", "ACTION", "SHIFT", "MANUAL"):
        raise AchievementError("BAD_SOURCE", f"منبع نامعتبر: {source}")
    ev = ScoreEvent(user_id=user_id, points=int(points), source=source,
                    evidence=json.dumps(evidence, ensure_ascii=False),
                    note=note, created_at=_now(), created_by=created_by)
    db.add(ev)
    db.commit()
    db.refresh(ev)
    return ev


def evaluate(db: Session, user_id: int) -> list[Achievement]:
    """بررسی خودکار شرایط دستاوردها از دادهٔ واقعی (idempotent)."""
    gained: list[Achievement] = []
    # فروش برتر: دست‌کم ۱۰ فاکتور PAID
    n = db.execute(select(Invoice.id).where(
        Invoice.created_by == user_id, Invoice.status == PAID).limit(50)).all()
    if len(n) >= 10:
        gained.append(award(db, user_id=user_id, code="TOP_SELLER", level=1,
                            evidence={"event": "sales_threshold", "metric": "paid_invoices",
                                      "value": len(n)}) or None)
    # حضور منظم: بدون تأخیر ثبت‌شده در ۵ شیفت
    from ..models import ShiftAttendance
    atts = db.execute(select(ShiftAttendance).where(
        ShiftAttendance.user_id == user_id).order_by(ShiftAttendance.id.desc()).limit(5)).scalars().all()
    if len(atts) >= 5 and all((a.late_minutes or 0) == 0 for a in atts):
        gained.append(award(db, user_id=user_id, code="RELIABLE", level=1,
                            evidence={"event": "on_time_shifts", "metric": "late_minutes",
                                      "value": 0}) or None)
    return [g for g in gained if g]


def summary(db: Session, user_id: int) -> dict:
    achs = db.execute(select(Achievement).where(Achievement.user_id == user_id)).scalars().all()
    events = db.execute(select(ScoreEvent).where(ScoreEvent.user_id == user_id)
                        .order_by(ScoreEvent.created_at.desc()).limit(50)).scalars().all()
    return {
        "score_total": sum(e.points for e in db.execute(select(ScoreEvent).where(
            ScoreEvent.user_id == user_id)).scalars().all()),
        "achievements": [{"code": a.code, "kind": a.kind, "title": a.title,
                          "level": a.level, "description": a.description,
                          "evidence": json.loads(a.evidence or "{}"),
                          "awarded_at": a.awarded_at.isoformat()} for a in achs],
        "recent_events": [{"points": e.points, "source": e.source, "note": e.note,
                           "evidence": json.loads(e.evidence or "{}"),
                           "created_at": e.created_at.isoformat()} for e in events],
    }
