# -*- coding: utf-8 -*-
"""build-488 — گزارش عملکرد کارکنان (§۲۱–۲۴) با نمودار و PDF.

همهٔ اعداد از فعالیت واقعی سیستم می‌آیند (§۵۲): فاکتورهای PAID ثبت‌شده توسط هر
کاربر، حضور/شیفت ثبت‌شده، رویدادهای امتیاز با Evidence و دستاوردها.

- گزارش فردی: روزانه/هفتگی/ماهانه/سالانه + تفکیک شیفت + اهداف + روند
- گزارش تیمی: جدول عملکرد همهٔ کارکنان (برای مدیر/سوپروایزر)
- سری‌های نمودار: فروش روزانه/هفتگی/ماهانه، تعداد تراکنش، میانگین فاکتور،
  مقایسهٔ هدف و عملکرد، ساعات کاری، روند امتیاز — ورودی PDF همین داده‌هاست.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import (Achievement, Customer, Invoice, ScoreEvent, ShiftAttendance,
                      ShiftAssignment, Shift, User)
from .shifts import day_performance

PAID = "PAID"


def _parse_day(s: str | date | None) -> date:
    if isinstance(s, date):
        return s
    return datetime.strptime(str(s), "%Y-%m-%d").date()


def _window(start: str | date | None, end: str | date | None) -> tuple[date, date]:
    e = _parse_day(end) if end else date.today()
    s = _parse_day(start) if start else e - timedelta(days=29)
    return s, e


def _user_sales(db: Session, user_id: int, start: datetime, end: datetime) -> list[tuple[datetime, float]]:
    rows = db.execute(select(Invoice.created_at, Invoice.total_amount).where(
        Invoice.created_by == user_id, Invoice.status == PAID,
        Invoice.created_at >= start, Invoice.created_at < end)
        .order_by(Invoice.created_at)).all()
    return [(at, float(amount or 0)) for at, amount in rows]


def employee_report(db: Session, user_id: int,
                    start: str | date | None = None, end: str | date | None = None,
                    *, goal: float | None = None) -> dict:
    s_day, e_day = _window(start, end)
    start_dt, end_dt = datetime.combine(s_day, time.min), datetime.combine(e_day + timedelta(days=1), time.min)
    rows = _user_sales(db, user_id, start_dt, end_dt)
    total = sum(v for _, v in rows)
    by_day: dict[str, float] = defaultdict(float)
    for at, v in rows:
        by_day[at.strftime("%Y-%m-%d")] += v
    # تفکیک داخل/خارج شیفت (§۲۰) — مجموع کل بازه
    in_shift = out_shift = 0
    days = [s_day + timedelta(days=k) for k in range((e_day - s_day).days + 1)]
    for d in days:
        perf = day_performance(db, user_id, d.strftime("%Y-%m-%d"))
        in_shift += perf["sales_in_shift"]
        out_shift += perf["sales_out_of_shift"]
    customers = db.execute(select(Customer.id).join(Invoice, Invoice.customer_id == Customer.id).where(
        Invoice.created_by == user_id, Invoice.status == PAID,
        Invoice.created_at >= start_dt, Invoice.created_at < end_dt).distinct()).all()
    att = db.execute(select(ShiftAttendance).where(
        ShiftAttendance.user_id == user_id,
        ShiftAttendance.day >= s_day.strftime("%Y-%m-%d"),
        ShiftAttendance.day <= e_day.strftime("%Y-%m-%d"))).scalars().all()
    late = sum(a.late_minutes or 0 for a in att)
    early = sum(a.early_leave_minutes or 0 for a in att)
    scores = db.execute(select(ScoreEvent).where(
        ScoreEvent.user_id == user_id,
        ScoreEvent.created_at >= start_dt, ScoreEvent.created_at < end_dt)).scalars().all()
    achs = db.execute(select(Achievement).where(Achievement.user_id == user_id)).scalars().all()
    u = db.get(User, user_id)
    goal = float(goal or 0)
    return {
        "user_id": user_id,
        "full_name": (u.full_name or u.username) if u else "",
        "job_title": (u.job_title or "") if u else "",
        "from": s_day.isoformat(), "to": e_day.isoformat(),
        "sales_total": round(total),
        "invoice_count": len(rows),
        "avg_invoice": round(total / len(rows)) if rows else 0,
        "customer_count": len(customers),
        "sales_in_shift": in_shift, "sales_out_of_shift": out_shift,
        "worked_days": len({a.day for a in att}),
        "late_minutes_total": late, "early_leave_minutes_total": early,
        "score_total": sum(s.points for s in scores),
        "score_events": len(scores),
        "achievements": [{"code": a.code, "title": a.title, "kind": a.kind,
                          "level": a.level, "evidence": a.evidence,
                          "awarded_at": a.awarded_at.isoformat()} for a in achs],
        "goal": goal,
        "goal_progress": round(total / goal * 100, 1) if goal else None,
        "daily_series": [{"day": d, "sales": round(by_day.get(d, 0))} for d in
                         [(s_day + timedelta(days=k)).isoformat() for k in range((e_day - s_day).days + 1)]],
    }


def team_report(db: Session, start: str | date | None = None, end: str | date | None = None) -> list[dict]:
    """عملکرد همهٔ کارکنان فعال — برای مدیر/سوپروایزر (§۲۱)."""
    out = []
    for u in db.execute(select(User).where(User.is_active.is_(True)).order_by(User.id)).scalars():
        rep = employee_report(db, u.id, start, end)
        rep["roles"] = [r.name for r in u.roles]
        out.append(rep)
    out.sort(key=lambda r: -r["sales_total"])
    return out


def chart_series(db: Session, user_id: int | None = None,
                 start: str | date | None = None, end: str | date | None = None,
                 goal: float | None = None) -> list[dict]:
    """سری‌های نمودار (§۲۲) — همه از دادهٔ واقعی؛ مناسب رسم در UI و PDF."""
    s_day, e_day = _window(start, end)
    start_dt, end_dt = datetime.combine(s_day, time.min), datetime.combine(e_day + timedelta(days=1), time.min)
    q = select(Invoice.created_at, Invoice.total_amount).where(
        Invoice.status == PAID, Invoice.created_at >= start_dt, Invoice.created_at < end_dt)
    if user_id is not None:
        q = q.where(Invoice.created_by == user_id)
    rows = db.execute(q.order_by(Invoice.created_at)).all()
    daily: dict[str, float] = defaultdict(float)
    daily_n: dict[str, int] = defaultdict(int)
    weekly: dict[str, float] = defaultdict(float)
    monthly: dict[str, float] = defaultdict(float)
    for at, amount in rows:
        v = float(amount or 0)
        d = at.strftime("%Y-%m-%d")
        daily[d] += v
        daily_n[d] += 1
        weekly[at.strftime("%G-W%V")] += v
        monthly[at.strftime("%Y-%m")] += v
    days = [(s_day + timedelta(days=k)).isoformat() for k in range((e_day - s_day).days + 1)]
    goal = float(goal or 0)
    series = [
        {"id": "sales_daily", "title": "فروش روزانه", "type": "line",
         "points": [{"x": d, "y": round(daily.get(d, 0))} for d in days]},
        {"id": "invoices_daily", "title": "تعداد تراکنش", "type": "bar",
         "points": [{"x": d, "y": daily_n.get(d, 0)} for d in days]},
        {"id": "avg_invoice", "title": "میانگین فاکتور", "type": "line",
         "points": [{"x": d, "y": round(daily.get(d, 0) / daily_n[d]) if daily_n.get(d) else 0} for d in days]},
        {"id": "sales_weekly", "title": "فروش هفتگی", "type": "bar",
         "points": [{"x": k, "y": round(v)} for k, v in sorted(weekly.items())]},
        {"id": "sales_monthly", "title": "فروش ماهانه", "type": "bar",
         "points": [{"x": k, "y": round(v)} for k, v in sorted(monthly.items())]},
    ]
    if goal > 0:
        total = sum(daily.values())
        series.append({"id": "goal_progress", "title": "مقایسهٔ هدف و عملکرد", "type": "gauge",
                       "points": [{"x": "هدف", "y": goal}, {"x": "عملکرد", "y": round(total)}],
                       "progress_pct": round(total / goal * 100, 1)})
    return series


def chart_series_summary(series: list[dict]) -> dict:
    out = {}
    for s in series:
        pts = s.get("points") or []
        if pts and s.get("type") in ("line", "bar") and all(isinstance(p.get("y"), (int, float)) for p in pts):
            out[s["id"]] = {"min": min(p["y"] for p in pts), "max": max(p["y"] for p in pts),
                            "sum": sum(p["y"] for p in pts), "n": len(pts)}
    return out
