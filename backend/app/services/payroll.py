# -*- coding: utf-8 -*-
"""build-488 — حقوق و دستمزد (§۲۶–۲۷).

ساختارمند، گزارش‌پذیر و متصل به حسابداری:
**Employee → Payroll → Accounting** — پرداخت هر دوره با سند JournalEntry
(بدهکار: ۶۱۰۲ حقوق و دستمزد / بستانکار: ۱۱۰۱ صندوق) قابل ردیابی است (§۲۷).

حقوق هرگز «بخش جدا» نیست: payment_ref روی ردیف حقوق، شمارهٔ سند مالی را نگه می‌دارد.
"""
from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import PayrollEntry, User
from .accounting import Line, post as post_journal

ZERO = Decimal("0")


class PayrollError(Exception):
    def __init__(self, code: str, message: str = ""):
        self.code = code
        super().__init__(message or code)


def compute_total(row: dict) -> Decimal:
    """مجموع پرداختی = پایه + ساعتی×ساعات + اضافه‌کاری + مزایا + پاداش − کسورات − جریمه."""
    base = Decimal(str(row.get("base_salary") or 0))
    hourly = Decimal(str(row.get("hourly_pay") or 0)) * Decimal(str(row.get("worked_hours") or 0))
    overtime = Decimal(str(row.get("overtime_hours") or 0)) * Decimal(str(row.get("hourly_pay") or 0)) * Decimal("1.4")
    gross = base + hourly + overtime + Decimal(str(row.get("benefits") or 0)) + Decimal(str(row.get("bonus") or 0))
    net = gross - Decimal(str(row.get("deductions") or 0)) - Decimal(str(row.get("penalty") or 0))
    return max(ZERO, net.quantize(Decimal("1")))


def create_entry(db: Session, *, user_id: int, period: str, user: User | None = None,
                 **fields) -> PayrollEntry:
    u = db.get(User, user_id)
    if u is None:
        raise PayrollError("USER_NOT_FOUND", f"کاربر {user_id} یافت نشد")
    if not period or len(period) < 4:
        raise PayrollError("BAD_PERIOD", "دورهٔ پرداخت باید مثل «1404-07» باشد")
    dup = db.execute(select(PayrollEntry).where(
        PayrollEntry.user_id == user_id, PayrollEntry.period == period)).scalar_one_or_none()
    if dup is not None:
        raise PayrollError("DUPLICATE", f"برای این کاربر در دورهٔ {period} قبلاً ثبت شده است")
    total = compute_total(fields)
    row = PayrollEntry(
        user_id=user_id, period=period,
        base_salary=Decimal(str(fields.get("base_salary") or 0)),
        hourly_pay=Decimal(str(fields.get("hourly_pay") or 0)),
        worked_hours=Decimal(str(fields.get("worked_hours") or 0)),
        overtime_hours=Decimal(str(fields.get("overtime_hours") or 0)),
        bonus=Decimal(str(fields.get("bonus") or 0)),
        benefits=Decimal(str(fields.get("benefits") or 0)),
        deductions=Decimal(str(fields.get("deductions") or 0)),
        penalty=Decimal(str(fields.get("penalty") or 0)),
        total=total, status="DRAFT",
        note=fields.get("note"), created_by=user.id if user else None,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def update_entry(db: Session, row: PayrollEntry, **fields) -> PayrollEntry:
    if row.status == "PAID":
        raise PayrollError("LOCKED", "ردیف پرداخت‌شده قابل ویرایش نیست")
    for k in ("base_salary", "hourly_pay", "worked_hours", "overtime_hours",
              "bonus", "benefits", "deductions", "penalty"):
        if fields.get(k) is not None:
            setattr(row, k, Decimal(str(fields[k])))
    if fields.get("note") is not None:
        row.note = fields["note"]
    row.total = compute_total({k: getattr(row, k) for k in
                               ("base_salary", "hourly_pay", "worked_hours", "overtime_hours",
                                "bonus", "benefits", "deductions", "penalty")})
    db.commit()
    return row


def approve(db: Session, row: PayrollEntry) -> PayrollEntry:
    if row.status != "DRAFT":
        raise PayrollError("BAD_STATUS", f"فقط ردیف پیش‌نویس تأیید می‌شود (وضعیت فعلی: {row.status})")
    row.status = "APPROVED"
    db.commit()
    return row


def pay(db: Session, row: PayrollEntry, *, user: User | None = None,
        account_cash: str = "1101", account_salary: str = "6102") -> PayrollEntry:
    """پرداخت + ثبت سند حسابداری (§۲۷) — idempotent با source_type=PAYROLL."""
    if row.status == "PAID":
        return row
    if row.status != "APPROVED":
        raise PayrollError("BAD_STATUS", "قبل از پرداخت باید ردیف تأیید شده باشد")
    total = Decimal(row.total or 0)
    if total <= 0:
        raise PayrollError("ZERO_TOTAL", "مجموع پرداختی صفر است")
    entry = post_journal(
        db, kind="MANUAL",
        lines=[
            Line(account=account_salary, debit=total, description=f"حقوق دورهٔ {row.period}",
                 party_type="user", party_id=row.user_id),
            Line(account=account_cash, credit=total, description=f"پرداخت حقوق دورهٔ {row.period}"),
        ],
        description=f"پرداخت حقوق {row.period} — کاربر {row.user_id}",
        source_type="PAYROLL", source_id=row.id, user=user,
    )
    row.status = "PAID"
    row.payment_ref = f"JE:{entry.number}"
    db.commit()
    return row


def out_dict(row: PayrollEntry, viewer: User | None = None) -> dict:
    return {
        "id": row.id, "user_id": row.user_id, "period": row.period,
        "base_salary": float(row.base_salary or 0), "hourly_pay": float(row.hourly_pay or 0),
        "worked_hours": float(row.worked_hours or 0), "overtime_hours": float(row.overtime_hours or 0),
        "bonus": float(row.bonus or 0), "benefits": float(row.benefits or 0),
        "deductions": float(row.deductions or 0), "penalty": float(row.penalty or 0),
        "total": float(row.total or 0), "status": row.status,
        "payment_ref": row.payment_ref, "note": row.note,
    }
