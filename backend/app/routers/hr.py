# -*- coding: utf-8 -*-
"""build-488 — APIهای اطلاعیه، شیفت، حقوق، عملکرد و داشبورد Widget (§۱۴–۲۷).

هر endpoint دسترسی سمت-سرور خودش را دارد (§۵۰) و عملیات مهم Audit می‌شود (§۵۱).
"""
from __future__ import annotations

import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import (Announcement, PayrollEntry, Shift, ShiftAssignment,
                      ShiftAttendance, User)
from ..security import get_current_user, has_permission, require_permission
from ..services import announcements as ann_svc
from ..services import payroll as pay_svc
from ..services import shifts as shift_svc
from ..services import widgets as widget_svc
from ..services.audit import write_audit

router = APIRouter(prefix="/hr", tags=["hr"])


def _err(exc: Exception, code: str = "ERROR"):
    if isinstance(exc, (ann_svc.AnnouncementError, shift_svc.ShiftError,
                        pay_svc.PayrollError, widget_svc.WidgetError)):
        return HTTPException(status_code=400, detail={"code": exc.code, "message": str(exc)})
    return HTTPException(status_code=500, detail={"code": code, "message": str(exc)})


# ───────────────────────────── اطلاعیه‌ها (§۱۴–۱۷) ─────────────────────────────

class AnnouncementIn(BaseModel):
    title: str
    body: str = ""
    priority: int = 3
    publish_at: datetime | None = None
    expires_at: datetime | None = None
    target_kind: str = "ALL"
    target_store: str | None = None
    target_roles: list[str] = []
    target_users: list[int] = []
    attachment_path: str | None = None
    status: str = "PUBLISHED"


@router.get("/announcements")
def my_announcements(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    ann_svc.sweep(db)
    out = []
    for ann, read in ann_svc.visible_states(db, user):
        d = ann_svc.out_dict(db, ann, read=read)
        out.append(d)
    return out


@router.get("/announcements/all")
def all_announcements(db: Session = Depends(get_db),
                      _: User = Depends(require_permission("announcements.manage"))):
    ann_svc.sweep(db)
    return [ann_svc.out_dict(db, a) for a in
            db.execute(select(Announcement).order_by(Announcement.created_at.desc()).limit(200)).scalars()]


@router.post("/announcements", status_code=201)
def create_announcement(body: AnnouncementIn, db: Session = Depends(get_db),
                        user: User = Depends(require_permission("announcements.publish"))):
    try:
        ann = ann_svc.create(db, title=body.title, body=body.body, user=user,
                             priority=body.priority, publish_at=body.publish_at,
                             expires_at=body.expires_at, target_kind=body.target_kind,
                             target_store=body.target_store, target_roles=body.target_roles,
                             target_users=body.target_users,
                             attachment_path=body.attachment_path, status=body.status)
    except ann_svc.AnnouncementError as exc:
        raise _err(exc)
    write_audit(db, action="ANNOUNCEMENT_CREATED", user_id=user.id,
                entity_type="Announcement", entity_id=ann.id,
                after={"title": ann.title, "target_kind": ann.target_kind})
    db.commit()
    return ann_svc.out_dict(db, ann)


@router.post("/announcements/{ann_id}/read")
def read_announcement(ann_id: int, db: Session = Depends(get_db),
                      user: User = Depends(get_current_user)):
    ann = db.get(Announcement, ann_id)
    if ann is None:
        raise HTTPException(status_code=404, detail="ANNOUNCEMENT_NOT_FOUND")
    ann_svc.mark_read(db, ann, user)
    return {"ok": True}


@router.post("/announcements/{ann_id}/seen")
def seen_announcement(ann_id: int, db: Session = Depends(get_db),
                      user: User = Depends(get_current_user)):
    ann = db.get(Announcement, ann_id)
    if ann is None:
        raise HTTPException(status_code=404, detail="ANNOUNCEMENT_NOT_FOUND")
    ann_svc.mark_seen(db, ann, user)
    return {"ok": True}


@router.delete("/announcements/{ann_id}")
def cancel_announcement(ann_id: int, db: Session = Depends(get_db),
                        user: User = Depends(get_current_user)):
    ann = db.get(Announcement, ann_id)
    if ann is None:
        raise HTTPException(status_code=404, detail="ANNOUNCEMENT_NOT_FOUND")
    if not (has_permission(user, "announcements.manage") or ann.created_by == user.id):
        raise HTTPException(status_code=403, detail={"code": "MISSING_PERMISSION",
                                                     "message": "حذف اطلاعیه نیازمند announcements.manage است"})
    ann_svc.cancel(db, ann)
    write_audit(db, action="ANNOUNCEMENT_CANCELLED", user_id=user.id,
                entity_type="Announcement", entity_id=ann.id)
    db.commit()
    return {"ok": True}


# ───────────────────────────── شیفت‌ها (§۱۸–۲۰) ─────────────────────────────

class ShiftIn(BaseModel):
    name: str
    start_time: str
    end_time: str
    workdays: list[int] = []
    store: str = ""
    department: str = ""
    role_hint: str | None = None


class ShiftPatch(BaseModel):
    name: str | None = None
    start_time: str | None = None
    end_time: str | None = None
    workdays: list[int] | None = None
    store: str | None = None
    department: str | None = None
    role_hint: str | None = None
    status: str | None = None


class AssignIn(BaseModel):
    user_id: int
    day: str = ""


class MoveIn(BaseModel):
    shift_id: int
    day: str | None = None


@router.get("/shifts")
def list_shifts(db: Session = Depends(get_db), _: User = Depends(require_permission("shifts.view"))):
    return [shift_svc.out_dict(db, s) for s in
            db.execute(select(Shift).order_by(Shift.id.desc())).scalars()]


@router.post("/shifts", status_code=201)
def create_shift(body: ShiftIn, db: Session = Depends(get_db),
                 user: User = Depends(require_permission("shifts.manage"))):
    try:
        sh = shift_svc.create_shift(db, name=body.name, start_time=body.start_time,
                                    end_time=body.end_time, workdays=body.workdays,
                                    store=body.store, department=body.department,
                                    role_hint=body.role_hint, user=user)
    except shift_svc.ShiftError as exc:
        raise _err(exc)
    write_audit(db, action="SHIFT_CREATED", user_id=user.id, entity_type="Shift",
                entity_id=sh.id, after={"name": sh.name, "start": sh.start_time, "end": sh.end_time})
    db.commit()
    return shift_svc.out_dict(db, sh)


@router.patch("/shifts/{shift_id}")
def update_shift(shift_id: int, body: ShiftPatch, db: Session = Depends(get_db),
                 user: User = Depends(require_permission("shifts.manage"))):
    sh = db.get(Shift, shift_id)
    if sh is None:
        raise HTTPException(status_code=404, detail="SHIFT_NOT_FOUND")
    before = {"name": sh.name, "start": sh.start_time, "end": sh.end_time, "status": sh.status}
    try:
        shift_svc.update_shift(db, sh, **body.model_dump(exclude_none=True))
    except shift_svc.ShiftError as exc:
        raise _err(exc)
    write_audit(db, action="SHIFT_UPDATED", user_id=user.id, entity_type="Shift",
                entity_id=sh.id, before=before,
                after={"name": sh.name, "start": sh.start_time, "end": sh.end_time, "status": sh.status})
    db.commit()
    return shift_svc.out_dict(db, sh)


@router.post("/shifts/{shift_id}/assign", status_code=201)
def assign_shift(shift_id: int, body: AssignIn, db: Session = Depends(get_db),
                 user: User = Depends(require_permission("shifts.manage"))):
    sh = db.get(Shift, shift_id)
    if sh is None:
        raise HTTPException(status_code=404, detail="SHIFT_NOT_FOUND")
    try:
        a = shift_svc.assign(db, sh, body.user_id, body.day, actor=user)
    except shift_svc.ShiftError as exc:
        raise _err(exc)
    write_audit(db, action="SHIFT_ASSIGNED", user_id=user.id, entity_type="Shift",
                entity_id=sh.id, after={"user_id": body.user_id, "day": body.day})
    db.commit()
    return {"assignment_id": a.id, "user_id": a.user_id, "day": a.day, "status": a.status}


@router.delete("/shifts/assignments/{assignment_id}")
def unassign_shift(assignment_id: int, db: Session = Depends(get_db),
                   user: User = Depends(require_permission("shifts.manage"))):
    a = db.get(ShiftAssignment, assignment_id)
    if a is None:
        raise HTTPException(status_code=404, detail="ASSIGNMENT_NOT_FOUND")
    shift_svc.unassign(db, a)
    write_audit(db, action="SHIFT_UNASSIGNED", user_id=user.id, entity_type="Shift",
                entity_id=a.shift_id, after={"user_id": a.user_id})
    db.commit()
    return {"ok": True}


@router.post("/shifts/assignments/{assignment_id}/move")
def move_shift(assignment_id: int, body: MoveIn, db: Session = Depends(get_db),
               user: User = Depends(require_permission("shifts.manage"))):
    a = db.get(ShiftAssignment, assignment_id)
    if a is None:
        raise HTTPException(status_code=404, detail="ASSIGNMENT_NOT_FOUND")
    target = db.get(Shift, body.shift_id)
    if target is None:
        raise HTTPException(status_code=404, detail="SHIFT_NOT_FOUND")
    try:
        new_a = shift_svc.move_assignment(db, a, target, day=body.day)
    except shift_svc.ShiftError as exc:
        raise _err(exc)
    write_audit(db, action="SHIFT_MOVED", user_id=user.id, entity_type="Shift",
                entity_id=body.shift_id, after={"user_id": new_a.user_id})
    db.commit()
    return {"assignment_id": new_a.id, "shift_id": new_a.shift_id}


@router.get("/shifts/day/{day}")
def shift_day(day: str, db: Session = Depends(get_db),
              _: User = Depends(require_permission("shifts.view"))):
    """شیفت‌های یک روز + عملکرد هر نفر با تفکیک داخل/خارج شیفت (§۱۹–۲۰)."""
    rows = []
    seen = set()
    for a in db.execute(select(ShiftAssignment).where(ShiftAssignment.status == "ACTIVE")).scalars():
        if a.day and a.day != day:
            continue
        if a.user_id in seen:
            continue
        seen.add(a.user_id)
        rows.append(shift_svc.day_performance(db, a.user_id, day))
    return {"day": day, "staff": rows}


@router.get("/shifts/performance/{user_id}/{day}")
def user_day_performance(user_id: int, day: str, db: Session = Depends(get_db),
                         viewer: User = Depends(get_current_user)):
    if viewer.id != user_id and not (has_permission(viewer, "performance.view")
                                     or has_permission(viewer, "performance.view_all")):
        raise HTTPException(status_code=403, detail={"code": "MISSING_PERMISSION",
                                                     "message": "دیدن عملکرد دیگران نیازمند performance.view است"})
    return shift_svc.day_performance(db, user_id, day)


@router.post("/attendance/clock-in")
def clock_in(db: Session = Depends(get_db), user: User = Depends(get_current_user),
             shift_id: int | None = None, day: str | None = None):
    att = shift_svc.clock_in(db, user, shift_id=shift_id, day=day)
    return {"id": att.id, "day": att.day, "started_at": att.started_at.isoformat(),
            "late_minutes": att.late_minutes}


@router.post("/attendance/clock-out")
def clock_out(db: Session = Depends(get_db), user: User = Depends(get_current_user),
              day: str | None = None):
    att = shift_svc.clock_out(db, user, day=day)
    return {"id": att.id, "day": att.day, "ended_at": att.ended_at.isoformat(),
            "early_leave_minutes": att.early_leave_minutes}


# ───────────────────────────── حقوق (§۲۶–۲۷) ─────────────────────────────

class PayrollIn(BaseModel):
    user_id: int
    period: str
    base_salary: float = 0
    hourly_pay: float = 0
    worked_hours: float = 0
    overtime_hours: float = 0
    bonus: float = 0
    benefits: float = 0
    deductions: float = 0
    penalty: float = 0
    note: str | None = None


class PayrollPatch(BaseModel):
    base_salary: float | None = None
    hourly_pay: float | None = None
    worked_hours: float | None = None
    overtime_hours: float | None = None
    bonus: float | None = None
    benefits: float | None = None
    deductions: float | None = None
    penalty: float | None = None
    note: str | None = None


@router.get("/payroll")
def list_payroll(period: str | None = None, db: Session = Depends(get_db),
                 _: User = Depends(require_permission("payroll.view"))):
    q = select(PayrollEntry).order_by(PayrollEntry.period.desc(), PayrollEntry.id)
    if period:
        q = q.where(PayrollEntry.period == period)
    return [pay_svc.out_dict(r) for r in db.execute(q).scalars()]


@router.post("/payroll", status_code=201)
def create_payroll(body: PayrollIn, db: Session = Depends(get_db),
                   user: User = Depends(require_permission("payroll.manage"))):
    try:
        row = pay_svc.create_entry(db, user_id=body.user_id, period=body.period, user=user,
                                   **{k: getattr(body, k) for k in
                                      ("base_salary", "hourly_pay", "worked_hours",
                                       "overtime_hours", "bonus", "benefits",
                                       "deductions", "penalty", "note")})
    except pay_svc.PayrollError as exc:
        raise _err(exc)
    write_audit(db, action="PAYROLL_CREATED", user_id=user.id, entity_type="Payroll",
                entity_id=row.id, after={"user_id": row.user_id, "period": row.period,
                                         "total": float(row.total)})
    db.commit()
    return pay_svc.out_dict(row)


@router.patch("/payroll/{row_id}")
def update_payroll(row_id: int, body: PayrollPatch, db: Session = Depends(get_db),
                   user: User = Depends(require_permission("payroll.manage"))):
    row = db.get(PayrollEntry, row_id)
    if row is None:
        raise HTTPException(status_code=404, detail="PAYROLL_NOT_FOUND")
    before = {"total": float(row.total)}
    try:
        row = pay_svc.update_entry(db, row, **body.model_dump(exclude_none=True))
    except pay_svc.PayrollError as exc:
        raise _err(exc)
    write_audit(db, action="PAYROLL_UPDATED", user_id=user.id, entity_type="Payroll",
                entity_id=row.id, before=before, after={"total": float(row.total)})
    db.commit()
    return pay_svc.out_dict(row)


@router.post("/payroll/{row_id}/approve")
def approve_payroll(row_id: int, db: Session = Depends(get_db),
                    user: User = Depends(require_permission("payroll.manage"))):
    row = db.get(PayrollEntry, row_id)
    if row is None:
        raise HTTPException(status_code=404, detail="PAYROLL_NOT_FOUND")
    try:
        row = pay_svc.approve(db, row)
    except pay_svc.PayrollError as exc:
        raise _err(exc)
    write_audit(db, action="PAYROLL_APPROVED", user_id=user.id, entity_type="Payroll", entity_id=row.id)
    db.commit()
    return pay_svc.out_dict(row)


@router.post("/payroll/{row_id}/pay")
def pay_payroll(row_id: int, db: Session = Depends(get_db),
                user: User = Depends(require_permission("payroll.manage"))):
    row = db.get(PayrollEntry, row_id)
    if row is None:
        raise HTTPException(status_code=404, detail="PAYROLL_NOT_FOUND")
    try:
        row = pay_svc.pay(db, row, user=user)
    except pay_svc.PayrollError as exc:
        raise _err(exc)
    write_audit(db, action="PAYROLL_PAID", user_id=user.id, entity_type="Payroll",
                entity_id=row.id, after={"payment_ref": row.payment_ref})
    db.commit()
    return pay_svc.out_dict(row)


# ───────────────────────────── عملکرد + PDF (§۲۱–۲۴) ─────────────────────────────

@router.get("/performance/me")
def my_performance(start: str | None = None, end: str | None = None,
                   goal: float | None = None, db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)):
    from ..services import performance as perf
    return perf.employee_report(db, user.id, start, end, goal=goal)


@router.get("/performance/team")
def team_performance(start: str | None = None, end: str | None = None,
                     db: Session = Depends(get_db),
                     _: User = Depends(require_permission("performance.view"))):
    from ..services import performance as perf
    return perf.team_report(db, start, end)


@router.get("/performance/{user_id}")
def employee_performance(user_id: int, start: str | None = None, end: str | None = None,
                         goal: float | None = None, db: Session = Depends(get_db),
                         viewer: User = Depends(get_current_user)):
    from ..services import performance as perf
    if viewer.id != user_id and not (has_permission(viewer, "performance.view_all")
                                     or has_permission(viewer, "performance.view")):
        raise HTTPException(status_code=403, detail={"code": "MISSING_PERMISSION",
                                                     "message": "دیدن عملکرد دیگران نیازمند performance.view است"})
    return perf.employee_report(db, user_id, start, end, goal=goal)


@router.get("/performance/charts/{user_id}")
def performance_charts(user_id: int, start: str | None = None, end: str | None = None,
                       goal: float | None = None, db: Session = Depends(get_db),
                       viewer: User = Depends(get_current_user)):
    from ..services import performance as perf
    if viewer.id != user_id and not has_permission(viewer, "performance.view"):
        raise HTTPException(status_code=403, detail={"code": "MISSING_PERMISSION",
                                                     "message": "نیازمند performance.view"})
    return perf.chart_series(db, user_id, start, end, goal=goal)


@router.get("/performance/pdf/{user_id}")
def performance_pdf(user_id: int, start: str | None = None, end: str | None = None,
                    goal: float | None = None, db: Session = Depends(get_db),
                    viewer: User = Depends(get_current_user)):
    """PDF گزارش عملکرد کارمند (§۲۳) — نیازمند reports.export یا خودِ کاربر."""
    from ..services import performance as perf
    from ..services.pdf import report_pdf
    if viewer.id != user_id and not (has_permission(viewer, "reports.export")
                                     or has_permission(viewer, "performance.view_all")):
        raise HTTPException(status_code=403, detail={"code": "MISSING_PERMISSION",
                                                     "message": "ساخت PDF نیازمند reports.export است"})
    rep = perf.employee_report(db, user_id, start, end, goal=goal)
    series = perf.chart_series(db, user_id, start, end, goal=goal)
    summary = [
        ["نام", rep["full_name"]], ["عنوان شغلی", rep["job_title"] or "—"],
        ["فروش کل", f'{rep["sales_total"]:,}'], ["تعداد فاکتور", str(rep["invoice_count"])],
        ["میانگین فاکتور", f'{rep["avg_invoice"]:,}'], ["تعداد مشتری", str(rep["customer_count"])],
        ["فروش داخل شیفت", f'{rep["sales_in_shift"]:,}'], ["فروش خارج از شیفت", f'{rep["sales_out_of_shift"]:,}'],
        ["روزهای حضور", str(rep["worked_days"])], ["مجموع تأخیر (دقیقه)", str(rep["late_minutes_total"])],
        ["امتیاز", str(rep["score_total"])],
    ]
    if rep.get("goal"):
        summary.append(["هدف فروش", f'{int(rep["goal"]):,}'])
        summary.append(["پیشرفت نسبت به هدف", f'{rep["goal_progress"]}%'])
    tables = [{
        "title": "فروش روزانه", "columns": ["روز", "فروش (تومان)"],
        "rows": [[d["day"], f'{d["sales"]:,}'] for d in rep["daily_series"]],
    }]
    charts = [{"title": s["title"], "type": s["type"], "points": s["points"]}
              for s in series if s.get("type") in ("line", "bar")]
    data, font_status = report_pdf(
        title="گزارش عملکرد کارمند", subtitle=rep["full_name"],
        period=f'{rep["from"]} تا {rep["to"]}',
        tables=tables, charts=charts, summary=summary,
        generated_by=viewer.full_name or viewer.username)
    return Response(content=data, media_type="application/pdf", headers={
        "Content-Disposition": f'attachment; filename="performance-{user_id}.pdf"',
        "X-Font-Status": font_status,
    })


# ───────────────────────────── داشبورد Widget (§۴–۱۳) ─────────────────────────────

@router.get("/widgets")
def get_widgets(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return widget_svc.compose(db, user)


class LayoutIn(BaseModel):
    order: list[str] = []
    pinned: list[str] = []
    hidden: list[str] = []
    sizes: dict = {}


@router.put("/widgets/layout")
def save_widget_layout(body: LayoutIn, db: Session = Depends(get_db),
                       user: User = Depends(get_current_user)):
    try:
        return widget_svc.save_layout(db, user, order=body.order, pinned=body.pinned,
                                      hidden=body.hidden, sizes=body.sizes)
    except widget_svc.WidgetError as exc:
        raise _err(exc)
