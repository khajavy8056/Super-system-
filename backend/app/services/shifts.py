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


def _naive(dt):
    """build-491 — نرمال‌سازی برای محاسبات زمانی (SQLite مقدار را naive برمی‌گرداند)."""
    if dt is None:
        return None
    return dt.replace(tzinfo=None) if getattr(dt, "tzinfo", None) is not None else dt


def _lt_now() -> datetime:
    try:
        from ..services.timeservice import local_now
        # build-491 — همیشه naive محلی؛ جلوگیری از TypeError در تفریق/مقایسهٔ زمان‌ها
        return _naive(local_now())
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


def has_attendance(db: Session, user: User, day: str | None = None) -> bool:
    """build-491 — آیا برای این روز حضوری (با ساعت ورود) ثبت شده؟"""
    d = day or _day_of(_lt_now())
    att = db.execute(select(ShiftAttendance).where(
        ShiftAttendance.user_id == user.id, ShiftAttendance.day == d
    ).order_by(ShiftAttendance.id.desc()).limit(1)).scalar_one_or_none()
    return bool(att and att.started_at)


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
        late = int((_naive(att.started_at) - _naive(start)).total_seconds() // 60)
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
            early = int((_naive(end) - _naive(att.ended_at)).total_seconds() // 60)
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
    now_naive = _naive(_lt_now())
    worked_min = 0
    for a in att:
        if a.started_at:
            end_dt = _naive(a.ended_at) if a.ended_at else now_naive
            worked_min += max(0, int((end_dt - _naive(a.started_at)).total_seconds() // 60))
    overtime_min = max(0, worked_min - planned_min) if planned_min > 0 else worked_min
    deficit_min = max(0, planned_min - worked_min) if planned_min > 0 else 0
    return {
        "user_id": user_id, "day": day,
        "sales_total": round(total), "invoices_total": len(rows),
        "sales_in_shift": round(in_shift), "invoices_in_shift": n_in,
        "sales_out_of_shift": round(out_shift), "invoices_out_of_shift": n_out,
        "shift_windows": [[s.isoformat(), e.isoformat()] for s, e in windows],
        "planned_minutes": planned_min,
        "worked_minutes": worked_min,
        "overtime_minutes": overtime_min,
        "deficit_minutes": deficit_min,
        "attendance": [{
            "shift_id": a.shift_id, "started_at": a.started_at.isoformat() if a.started_at else None,
            "ended_at": a.ended_at.isoformat() if a.ended_at else None,
            "late_minutes": a.late_minutes, "early_leave_minutes": a.early_leave_minutes,
        } for a in att],
    }


def attendance_summary(db: Session, start_day: str, end_day: str, user_id: int | None = None) -> list[dict]:
    """build-492 — گزارش مقایسهٔ ساعات شیفت برنامه‌ریزی‌شده و ساعات حضور واقعی برای هر کاربر."""
    s_date = datetime.strptime(start_day, "%Y-%m-%d").date()
    e_date = datetime.strptime(end_day, "%Y-%m-%d").date()
    if e_date < s_date:
        s_date, e_date = e_date, s_date
    users_q = select(User).where(User.is_active == True)  # noqa: E712
    if user_id is not None:
        users_q = users_q.where(User.id == user_id)
    users = db.execute(users_q.order_by(User.id)).scalars().all()
    out = []
    for u in users:
        total_planned = 0
        total_worked = 0
        total_late = 0
        total_early = 0
        days_scheduled = 0
        days_present = 0
        cur = s_date
        while cur <= e_date:
            d_str = cur.isoformat()
            perf = day_performance(db, u.id, d_str)
            p_min = perf["planned_minutes"]
            w_min = perf["worked_minutes"]
            if p_min > 0:
                days_scheduled += 1
            if perf["attendance"]:
                days_present += 1
            total_planned += p_min
            total_worked += w_min
            for a in perf["attendance"]:
                total_late += int(a.get("late_minutes") or 0)
                total_early += int(a.get("early_leave_minutes") or 0)
            cur += timedelta(days=1)
        overtime = max(0, total_worked - total_planned) if total_planned > 0 else total_worked
        deficit = max(0, total_planned - total_worked) if total_planned > 0 else 0
        out.append({
            "user_id": u.id,
            "username": u.username,
            "full_name": u.full_name or u.username,
            "start_day": s_date.isoformat(),
            "end_day": e_date.isoformat(),
            "days_scheduled": days_scheduled,
            "days_present": days_present,
            "planned_minutes": total_planned,
            "worked_minutes": total_worked,
            "overtime_minutes": overtime,
            "deficit_minutes": deficit,
            "late_minutes": total_late,
            "early_leave_minutes": total_early,
        })
    return out


def _matching_shifts_for_user_day(db: Session, user_id: int, day: str) -> list[Shift]:
    """برگرداندن تمام شیفت‌های فعال کاربر برای تاریخ `day` (چه اختصاص روزِ خاص و چه شیفت تکرارشونده با day='')."""
    wd = datetime.strptime(day, "%Y-%m-%d").weekday()
    rows = db.execute(select(ShiftAssignment, Shift).join(
        Shift, ShiftAssignment.shift_id == Shift.id).where(
        ShiftAssignment.user_id == user_id,
        ShiftAssignment.status == "ACTIVE",
        Shift.status == "ACTIVE",
    ).order_by(Shift.start_time.asc(), ShiftAssignment.id.asc())).all()
    exact: list[Shift] = []
    recurring: list[Shift] = []
    seen_ids: set[int] = set()
    for a, sh in rows:
        if sh.id in seen_ids:
            continue
        if a.day == day:
            exact.append(sh)
            seen_ids.add(sh.id)
        elif a.day == "":
            days = json.loads(sh.workdays or "[]")
            if not days or wd in days:
                recurring.append(sh)
                seen_ids.add(sh.id)
    return exact + recurring


def _pick_active_or_next_shift(shifts: list[Shift], day: str, now: datetime) -> tuple[Shift | None, bool]:
    """انتخاب شیفتِ در حال اجرا (یا نزدیک‌ترین شیفت امروز) و تعیین اینکه آیا زمان فعلی داخل بازهٔ شیفت است."""
    if not shifts:
        return None, False
    n = _naive(now)
    grace = timedelta(minutes=15)
    for sh in shifts:
        start, end = shift_window(sh, day)
        if (start - grace) <= n <= end:
            return sh, True
    upcoming = []
    for sh in shifts:
        start, end = shift_window(sh, day)
        if n < start:
            upcoming.append((start, sh))
    if upcoming:
        upcoming.sort(key=lambda x: x[0])
        return upcoming[0][1], False
    return shifts[-1], False


def attendance_status(db: Session, user: User, *, auto_enter: bool = False) -> dict:
    """build-492 — نوار حضور و تشخیص خودکار شیفت فعال کاربر:
    User -> Assigned Shift -> Current Date/Time -> Shift Validation -> Active Shift -> User Attendance / Presence.
    اگر `auto_enter=True` باشد و کاربر در بازهٔ شیفت مجاز خود وارد برنامه شده باشد، حضور او به‌صورت خودکار در شیفت فعال ثبت می‌شود."""
    now = _lt_now()
    d = _day_of(now)
    n_now = _naive(now)
    grace = timedelta(minutes=15)
    shifts = _matching_shifts_for_user_day(db, user.id, d)
    sh, in_window = _pick_active_or_next_shift(shifts, d, now)
    att = db.execute(select(ShiftAttendance).where(
        ShiftAttendance.user_id == user.id, ShiftAttendance.day == d
    ).order_by(ShiftAttendance.id.desc()).limit(1)).scalar_one_or_none()
    auto_clocked_in = False
    if auto_enter and sh is not None and in_window:
        if att is None:
            att = clock_in(db, user, shift_id=sh.id, day=d, at=now)
            auto_clocked_in = True
    if sh is None and att is not None and att.shift_id:
        sh = db.get(Shift, att.shift_id)
        if sh:
            s_win, e_win = shift_window(sh, d)
            in_window = (s_win - grace) <= n_now <= e_win
    started = att.started_at if att else None
    ended = att.ended_at if att else None
    present = bool(started and not ended)
    minutes = int((n_now - _naive(started)).total_seconds() // 60) if present and started else None
    has_shift = sh is not None or att is not None
    if not has_shift:
        shift_state = "NO_SHIFT"
    elif ended is not None:
        shift_state = "COMPLETED"
    elif present or in_window:
        shift_state = "IN_SHIFT"
    else:
        shift_state = "OUT_OF_SHIFT"
    shift_windows = []
    for s in shifts:
        sw, ew = shift_window(s, d)
        shift_windows.append({
            "id": s.id,
            "name": s.name,
            "start_time": s.start_time,
            "end_time": s.end_time,
            "in_window": (sw - grace) <= n_now <= ew,
        })
    active_shift = (
        {"id": sh.id, "name": sh.name, "start_time": sh.start_time, "end_time": sh.end_time}
        if sh is not None else None
    )
    return {
        "day": d,
        "has_shift": has_shift,
        "in_shift_window": in_window,
        "auto_entered": auto_clocked_in,
        "auto_clocked_in": auto_clocked_in,
        "shift_state": shift_state,
        "active_shift": active_shift,
        "shift_windows": shift_windows,
        "shift_id": sh.id if sh else (att.shift_id if att else None),
        "shift_name": sh.name if sh else None,
        "start_time": sh.start_time if sh else None,
        "end_time": sh.end_time if sh else None,
        "present": present,
        "since": started.isoformat() if started else None,
        "ended_at": ended.isoformat() if ended else None,
        "minutes": minutes,
        "late_minutes": att.late_minutes if att else None,
        "shifts_today": [
            {"id": s.id, "name": s.name, "start_time": s.start_time, "end_time": s.end_time}
            for s in shifts
        ],
    }


def my_shifts(db: Session, user: User) -> dict:
    """build-492 — فهرست شیفت‌های اختصاص‌یافته به کاربر جاری + وضعیت لحظه‌ای حضور."""
    st = attendance_status(db, user, auto_enter=True)
    rows = db.execute(select(ShiftAssignment, Shift).join(
        Shift, ShiftAssignment.shift_id == Shift.id).where(
        ShiftAssignment.user_id == user.id,
        ShiftAssignment.status == "ACTIVE",
        Shift.status == "ACTIVE",
    ).order_by(ShiftAssignment.day.desc(), Shift.start_time.asc())).all()
    assignments = [
        {
            "assignment_id": a.id,
            "shift_id": sh.id,
            "shift_name": sh.name,
            "start_time": sh.start_time,
            "end_time": sh.end_time,
            "day": a.day,
            "workdays": json.loads(sh.workdays or "[]"),
            "store": sh.store,
            "department": sh.department,
        }
        for a, sh in rows
    ]
    return {"status": st, "assignments": assignments}


def attendance_today(db: Session) -> list[dict]:
    """build-492 — حضور امروز تیم (سوپروایزر/مدیر): شامل شیفت‌های روز خاص و شیفت‌های تکرارشوندهٔ امروز."""
    now = _lt_now()
    d = _day_of(now)
    wd = datetime.strptime(d, "%Y-%m-%d").weekday()
    seen: dict[int, dict] = {}
    rows = db.execute(select(ShiftAssignment, Shift, User).join(
        Shift, ShiftAssignment.shift_id == Shift.id).join(
        User, ShiftAssignment.user_id == User.id).where(
        ShiftAssignment.status == "ACTIVE", Shift.status == "ACTIVE")).all()
    for a, sh, u in rows:
        if a.day not in (d, ""):
            continue
        if a.day == "":
            days = json.loads(sh.workdays or "[]")
            if days and wd not in days:
                continue
        if u.id in seen and a.day == "":
            continue
        seen[u.id] = {"user_id": u.id, "name": u.full_name or u.username,
                      "shift_id": sh.id, "shift_name": sh.name,
                      "start_time": sh.start_time, "end_time": sh.end_time,
                      "day": d, "assignment_id": a.id}
    for att in db.execute(select(ShiftAttendance).where(ShiftAttendance.day == d)).scalars():
        if att.user_id not in seen:
            u = db.get(User, att.user_id)
            if u:
                seen[att.user_id] = {"user_id": u.id, "name": u.full_name or u.username,
                                     "shift_id": att.shift_id, "shift_name": None,
                                     "start_time": None, "end_time": None,
                                     "day": d, "assignment_id": None}
    out = []
    for rec in seen.values():
        att = db.execute(select(ShiftAttendance).where(
            ShiftAttendance.user_id == rec["user_id"], ShiftAttendance.day == d
        ).order_by(ShiftAttendance.id.desc()).limit(1)).scalar_one_or_none()
        started = att.started_at if att else None
        ended = att.ended_at if att else None
        rec["present"] = bool(started and not ended)
        rec["since"] = started.isoformat() if started else None
        rec["ended_at"] = ended.isoformat() if ended else None
        rec["minutes"] = int((_naive(now) - _naive(started)).total_seconds() // 60) if rec["present"] and started else None
        out.append(rec)
    out.sort(key=lambda r: (not r["present"], r.get("start_time") or "", r["name"]))
    return out


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
