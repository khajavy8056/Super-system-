# -*- coding: utf-8 -*-
"""build-488 — شیفت‌بندی و عملکرد شیفت (§۱۸–۲۰).

- تعریف/ویرایش/بایگانی شیفت، تخصیص/لغو/جابه‌جایی کارکنان (shifts.manage)
- حضور واقعی (شروع/پایان) با محاسبهٔ تأخیر و خروج زودهنگام در برابر برنامه
- گزارش عملکرد هر نفر: فروشِ داخل شیفت / خارج از شیفت (§۲۰ — سیستم فرض نمی‌کند
  همهٔ فعالیت‌ها داخل شیفت اتفاق افتاده؛ تفکیک برای گزارش مدیریتی حیاتی است)

همهٔ اعداد از دادهٔ واقعی فاکتورها می‌آیند (§۵۲) — هیچ عددی ساختگی نیست.
"""
from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Invoice, Shift, ShiftAssignment, ShiftAttendance, User

PAID = "PAID"


def _now() -> datetime:
    return datetime.utcnow()


def _lt_now() -> datetime:
    try:
        from ..services.timeservice import local_now
        return local_now()
    except Exception:
        return datetime.utcnow()


class ShiftError(Exception):
    def __init__(self, code: str, message: str = ""):
        self.code = code
        super().__init__(message or code)


def _parse_hhmm(value: str) -> time:
    try:
        hh, mm = (value or "").split(":")
        return time(int(hh) % 24, int(mm) % 60)
    except Exception:
        raise ShiftError("BAD_TIME", f"ساعت نامعتبر: {value!r} (قالب HH:MM)")


def create_shift(db: Session, *, name: str, start_time: str, end_time: str,
                 workdays: list[int] | None = None, store: str = "",
                 department: str = "", role_hint: str | None = None,
                 user: User | None = None) -> Shift:
    if not (name or "").strip():
        raise ShiftError("EMPTY_NAME", "نام شیفت خالی است")
    s = _parse_hhmm(start_time)
    e = _parse_hhmm(end_time)
    if s == e:
        raise ShiftError("BAD_RANGE", "ساعت شروع و پایان نمی‌توانند یکی باشند")
    days = sorted({int(d) for d in (workdays or []) if 0 <= int(d) <= 6})
    sh = Shift(name=name.strip(), start_time=f"{s.hour:02d}:{s.minute:02d}",
               end_time=f"{e.hour:02d}:{e.minute:02d}",
               workdays=json.dumps(days), store=store or "", department=department or "",
               role_hint=role_hint, status="ACTIVE",
               created_by=user.id if user else None)
    db.add(sh)
    db.commit()
    db.refresh(sh)
    return sh


def update_shift(db: Session, sh: Shift, **fields) -> Shift:
    if fields.get("name") is not None:
        if not fields["name"].strip():
            raise ShiftError("EMPTY_NAME", "نام شیفت خالی است")
        sh.name = fields["name"].strip()
    for k in ("start_time", "end_time"):
        if fields.get(k) is not None:
            t = _parse_hhmm(fields[k])
            setattr(sh, k, f"{t.hour:02d}:{t.minute:02d}")
    if fields.get("workdays") is not None:
        sh.workdays = json.dumps(sorted({int(d) for d in fields["workdays"] if 0 <= int(d) <= 6}))
    for k in ("store", "department", "role_hint", "status"):
        if fields.get(k) is not None:
            setattr(sh, k, fields[k])
    if sh.start_time == sh.end_time:
        raise ShiftError("BAD_RANGE", "ساعت شروع و پایان نمی‌توانند یکی باشند")
    db.commit()
    return sh


def assign(db: Session, sh: Shift, user_id: int, day: str = "", *,
           actor: User | None = None) -> ShiftAssignment:
    u = db.get(User, user_id)
    if u is None:
        raise ShiftError("USER_NOT_FOUND", f"کاربر {user_id} یافت نشد")
    existing = db.execute(select(ShiftAssignment).where(
        ShiftAssignment.shift_id == sh.id, ShiftAssignment.user_id == user_id,
        ShiftAssignment.day == (day or ""))).scalar_one_or_none()
    if existing and existing.status == "ACTIVE":
        return existing
    if existing:
        existing.status = "ACTIVE"
        db.commit()
        return existing
    a = ShiftAssignment(shift_id=sh.id, user_id=user_id, day=day or "",
                        status="ACTIVE", created_at=_now(),
                        created_by=actor.id if actor else None)
    db.add(a)
    db.commit()
    db.refresh(a)
    return a


def unassign(db: Session, assignment: ShiftAssignment) -> ShiftAssignment:
    assignment.status = "CANCELLED"
    db.commit()
    return assignment


def move_assignment(db: Session, assignment: ShiftAssignment, new_shift: Shift,
                    day: str | None = None) -> ShiftAssignment:
    """جابه‌جایی شیفت یک کاربر (§۱۸) — لغوِ تخصیص قبلی + تخصیص جدید."""
    assignment.status = "CANCELLED"
    db.flush()
    return assign(db, new_shift, assignment.user_id,
                  assignment.day if day is None else day)


def shift_window(sh: Shift, day: str) -> tuple[datetime, datetime]:
    """بازهٔ واقعی شیفت برای یک روز (با عبور از نیمه‌شب)."""
    d = datetime.strptime(day, "%Y-%m-%d").date()
    s = _parse_hhmm(sh.start_time)
    e = _parse_hhmm(sh.end_time)
    start = datetime.combine(d, s)
    end = datetime.combine(d, e)
    if end <= start:
        end += timedelta(days=1)
    return start, end


def _day_of(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d")


def clock_in(db: Session, user: User, *, shift_id: int | None = None,
             day: str | None = None, at: datetime | None = None) -> ShiftAttendance:
    now = at or _lt_now()
    d = day or _day_of(now)
    sh = db.get(Shift, shift_id) if shift_id else None
    att = db.execute(select(ShiftAttendance).where(
        ShiftAttendance.user_id == user.id, ShiftAttendance.day == d,
        ShiftAttendance.shift_id == (sh.id if sh else None))).scalar_one_or_none()
    if att is None:
        att = ShiftAttendance(user_id=user.id, day=d, shift_id=sh.id if sh else None)
        db.add(att)
    att.started_at = att.started_at or now
    if sh:
        start, _ = shift_window(sh, d)
        # تأخیر فقط وقتی معنا دارد که ورود بعد از ساعت برنامه باشد
        late = int((att.started_at - start).total_seconds() // 60)
        att.late_minutes = max(0, late) if late > 0 else 0
    db.commit()
    db.refresh(att)
    return att


def clock_out(db: Session, user: User, *, day: str | None = None,
              at: datetime | None = None) -> ShiftAttendance:
    now = at or _lt_now()
    d = day or _day_of(now)
    att = db.execute(select(ShiftAttendance).where(
        ShiftAttendance.user_id == user.id, ShiftAttendance.day == d).order_by(
        ShiftAttendance.id.desc()).limit(1)).scalar_one_or_none()
    if att is None:
        att = ShiftAttendance(user_id=user.id, day=d)
        db.add(att)
    att.ended_at = now
    if att.shift_id:
        sh = db.get(Shift, att.shift_id)
        if sh:
            _, end = shift_window(sh, d)
            early = int((end - att.ended_at).total_seconds() // 60)
            att.early_leave_minutes = max(0, early) if early > 0 else 0
    db.commit()
    db.refresh(att)
    return att


# ── عملکرد: فروش داخل/خارج شیفت (§۱۹–۲۰) ─────────────────────────────────


def _user_shift_windows(db: Session, user_id: int, day: str) -> list[tuple[datetime, datetime]]:
    out = []
    for a in db.execute(select(ShiftAssignment).where(
            ShiftAssignment.user_id == user_id, ShiftAssignment.status == "ACTIVE")).scalars():
        if a.day and a.day != day:
            continue
        sh = db.get(Shift, a.shift_id)
        if sh is None or sh.status != "ACTIVE":
            continue
        if a.day == "":
            days = json.loads(sh.workdays or "[]")
            wd = datetime.strptime(day, "%Y-%m-%d").weekday()
            if days and wd not in days:
                continue
        out.append(shift_window(sh, day))
    return sorted(out)


def day_performance(db: Session, user_id: int, day: str) -> dict:
    """فروش روز + تفکیک داخل/خارج شیفت — همه از فاکتورهای واقعی (§۵۲)."""
    d = datetime.strptime(day, "%Y-%m-%d").date()
    day_start = datetime.combine(d, time.min)
    day_end = day_start + timedelta(days=1)
    rows = db.execute(select(Invoice.created_at, Invoice.total_amount).where(
        Invoice.created_by == user_id, Invoice.status == PAID,
        Invoice.created_at >= day_start, Invoice.created_at < day_end)).all()
    windows = _user_shift_windows(db, user_id, day)
    total = in_shift = out_shift = 0.0
    n_in = n_out = 0
    for at, amount in rows:
        total += float(amount or 0)
        if any(start <= at < end for start, end in windows):
            in_shift += float(amount or 0)
            n_in += 1
        else:
            out_shift += float(amount or 0)
            n_out += 1
    att = db.execute(select(ShiftAttendance).where(
        ShiftAttendance.user_id == user_id, ShiftAttendance.day == day)).scalars().all()
    planned_min = sum(int((e - s).total_seconds() // 60) for s, e in windows)
    return {
        "user_id": user_id, "day": day,
        "sales_total": round(total), "invoices_total": len(rows),
        "sales_in_shift": round(in_shift), "invoices_in_shift": n_in,
        "sales_out_of_shift": round(out_shift), "invoices_out_of_shift": n_out,
        "shift_windows": [[s.isoformat(), e.isoformat()] for s, e in windows],
        "planned_minutes": planned_min,
        "attendance": [{
            "shift_id": a.shift_id, "started_at": a.started_at.isoformat() if a.started_at else None,
            "ended_at": a.ended_at.isoformat() if a.ended_at else None,
            "late_minutes": a.late_minutes, "early_leave_minutes": a.early_leave_minutes,
        } for a in att],
    }


def shift_roster(db: Session, sh: Shift) -> list[dict]:
    out = []
    for a in db.execute(select(ShiftAssignment).where(
            ShiftAssignment.shift_id == sh.id, ShiftAssignment.status == "ACTIVE")).scalars():
        u = db.get(User, a.user_id)
        out.append({"assignment_id": a.id, "user_id": a.user_id, "day": a.day,
                    "full_name": (u.full_name or u.username) if u else "",
                    "job_title": (u.job_title or "") if u else ""})
    return out


def out_dict(db: Session, sh: Shift) -> dict:
    return {
        "id": sh.id, "name": sh.name, "start_time": sh.start_time, "end_time": sh.end_time,
        "workdays": json.loads(sh.workdays or "[]"), "store": sh.store,
        "department": sh.department, "role_hint": sh.role_hint, "status": sh.status,
        "roster": shift_roster(db, sh),
    }
