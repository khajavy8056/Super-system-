# -*- coding: utf-8 -*-
"""build-488 — لایهٔ سرمایهٔ انسانی و اطلاع‌رسانی (بخش‌های ۱۴–۲۷ و ۳۴–۳۵ دستور).

هیچ‌کدام از این مدل‌ها منطق کسب‌وکار موجود را تغییر نمی‌دهند؛ کاملاً افزودنی‌اند
و به معماری فعلی (TimestampMixin / Base / MONEY) متصل می‌شوند:

- Shift / ShiftAssignment / ShiftAttendance — شیفت‌بندی واقعی (§۱۸–۱۹)
- PayrollEntry — حقوق و دستمزد ساختارمند، متصل به حسابداری (§۲۶–۲۷)
- Announcement / AnnouncementRead — اطلاعیهٔ داخلی با مخاطب‌گیری و وضعیت خواندن (§۱۴–۱۷)
- Achievement / ScoreEvent — دستاوردها/مدال/نشان با Evidence واقعی (§۳۴–۳۵)
- UserWidgetLayout — شخصی‌سازی داشبورد در محدودهٔ دسترسی (§۸)
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (Boolean, DateTime, ForeignKey, Integer, String, Text,
                        UniqueConstraint)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import Base
from .base import TimestampMixin
from .pricing import MONEY


class Shift(TimestampMixin, Base):
    """یک شیفت کاری تعریف‌شده: ساعت شروع/پایان، روزهای کاری، بخش و فروشگاه."""

    __tablename__ = "hr_shifts"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    #: «06:00»
    start_time: Mapped[str] = mapped_column(String(5))
    end_time: Mapped[str] = mapped_column(String(5))
    #: JSON list[int] — Python weekday (0=دوشنبه … 6=یکشنبه)؛ خالی = هر روز
    workdays: Mapped[str] = mapped_column(Text, default="[]")
    store: Mapped[str] = mapped_column(String(128), default="")
    department: Mapped[str] = mapped_column(String(128), default="")
    #: نام Role هدف (اختیاری) — فقط برای پیشنهاد تخصیص، محدودکننده نیست
    role_hint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="ACTIVE")  # ACTIVE / ARCHIVED
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)

    assignments: Mapped[list["ShiftAssignment"]] = relationship(
        back_populates="shift", cascade="all, delete-orphan")


class ShiftAssignment(Base):
    """تخصیص شیفت به کاربر (قابل جابه‌جایی/لغو/تمدید)."""

    __tablename__ = "hr_shift_assignments"
    __table_args__ = (UniqueConstraint("shift_id", "user_id", "day", name="uq_shift_user_day"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    shift_id: Mapped[int] = mapped_column(ForeignKey("hr_shifts.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    #: «YYYY-MM-DD» — روزِ شیفت (برای برنامهٔ هفتگی می‌تواند روز الگو باشد)
    day: Mapped[str] = mapped_column(String(10), default="")  # "" = الگوی دائمی
    status: Mapped[str] = mapped_column(String(16), default="ACTIVE")  # ACTIVE / CANCELLED
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)

    shift: Mapped["Shift"] = relationship(back_populates="assignments")


class ShiftAttendance(Base):
    """حضور واقعی: شروع/پایان ثبت‌شده، تأخیر و خروج زودهنگام از مقایسه با برنامه."""

    __tablename__ = "hr_shift_attendance"
    __table_args__ = (UniqueConstraint("shift_id", "user_id", "day", name="uq_att_shift_user_day"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    shift_id: Mapped[int | None] = mapped_column(ForeignKey("hr_shifts.id", ondelete="SET NULL"), nullable=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    day: Mapped[str] = mapped_column(String(10), index=True)  # «YYYY-MM-DD»
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    #: دقیقه — از مقایسهٔ برنامه با حضور واقعی (null = بدون برنامه)
    late_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    early_leave_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)


class PayrollEntry(TimestampMixin, Base):
    """دورهٔ حقوق یک کارمند (§۲۶) — ساختارمند و گزارش‌پذیر؛ پرداخت آن به
    حسابداری (§۲۷) با سند JournalEntry قابل ردیابی است (payment_ref)."""

    __tablename__ = "hr_payroll"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    #: «1404-07» — دورهٔ پرداخت
    period: Mapped[str] = mapped_column(String(7), index=True)
    base_salary: Mapped[Decimal] = mapped_column(MONEY, default=0)
    hourly_pay: Mapped[Decimal] = mapped_column(MONEY, default=0)
    worked_hours: Mapped[Decimal] = mapped_column(MONEY, default=0)
    overtime_hours: Mapped[Decimal] = mapped_column(MONEY, default=0)
    bonus: Mapped[Decimal] = mapped_column(MONEY, default=0)
    benefits: Mapped[Decimal] = mapped_column(MONEY, default=0)
    deductions: Mapped[Decimal] = mapped_column(MONEY, default=0)
    penalty: Mapped[Decimal] = mapped_column(MONEY, default=0)
    total: Mapped[Decimal] = mapped_column(MONEY, default=0)
    status: Mapped[str] = mapped_column(String(16), default="DRAFT")  # DRAFT / APPROVED / PAID
    #: ارجاع سند/پرداخت حسابداری (§۲۷ — ردیابی مالی)
    payment_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)


class Announcement(TimestampMixin, Base):
    """اطلاعیهٔ داخلی (§۱۴–۱۶) با مخاطب‌گیری دقیق."""

    __tablename__ = "announcements"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(255))
    body: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    #: DRAFT / SCHEDULED / PUBLISHED / CANCELLED / EXPIRED
    status: Mapped[str] = mapped_column(String(16), default="PUBLISHED", index=True)
    priority: Mapped[int] = mapped_column(Integer, default=3)  # 1 فوری … 5 اطلاعی
    publish_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    #: ALL / STORE / ROLES / USERS
    target_kind: Mapped[str] = mapped_column(String(16), default="ALL")
    target_store: Mapped[str | None] = mapped_column(String(128), nullable=True)
    #: JSON list[str] نام Roleها
    target_roles: Mapped[str] = mapped_column(Text, default="[]")
    #: JSON list[int] شناسهٔ کاربران
    target_users: Mapped[str] = mapped_column(Text, default="[]")
    attachment_path: Mapped[str | None] = mapped_column(String(255), nullable=True)

    reads: Mapped[list["AnnouncementRead"]] = relationship(
        back_populates="announcement", cascade="all, delete-orphan")


class AnnouncementRead(Base):
    """وضعیت دریافت/دیده‌شدن/خواندن برای هر کاربر (§۱۷)."""

    __tablename__ = "announcement_reads"
    __table_args__ = (UniqueConstraint("announcement_id", "user_id", name="uq_ann_user"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    announcement_id: Mapped[int] = mapped_column(
        ForeignKey("announcements.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    seen_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    announcement: Mapped["Announcement"] = relationship(back_populates="reads")


class Achievement(TimestampMixin, Base):
    """مدال/نشان/دستاورد واقعی (§۳۵) — فقط با Event معتبر اعطا می‌شود."""

    __tablename__ = "hr_achievements"
    __table_args__ = (UniqueConstraint("user_id", "code", name="uq_ach_user_code"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    #: MEDAL / BADGE / ACHIEVEMENT
    kind: Mapped[str] = mapped_column(String(16), default="BADGE")
    code: Mapped[str] = mapped_column(String(64), index=True)
    title: Mapped[str] = mapped_column(String(128))
    description: Mapped[str] = mapped_column(Text, default="")
    level: Mapped[int] = mapped_column(Integer, default=1)  # 1 برنزی … 3 طلایی
    #: JSON {event, metric, value, at} — «این امتیاز از چه فعالیتی به دست آمده» (§۳۴)
    evidence: Mapped[str] = mapped_column(Text, default="{}")
    awarded_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class ScoreEvent(Base):
    """رویداد امتیاز (§۳۴) — هر امتیاز باید Source و Evidence داشته باشد.
    ثبت امتیاز بدون event/evidence معتبر ممنوع است (سرویس achievements)."""

    __tablename__ = "hr_score_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    points: Mapped[int] = mapped_column(Integer)
    #: SALE / TASK / STOCKTAKE / ACCURACY / ACTION / SHIFT / MANUAL
    source: Mapped[str] = mapped_column(String(32), index=True)
    #: JSON {ref_type, ref_id, metric, value} — ردیابی تا Source
    evidence: Mapped[str] = mapped_column(Text, default="{}")
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)


class UserWidgetLayout(Base):
    """چیدمان شخصی داشبورد هر کاربر (§۸) — فقط در محدودهٔ Widgetهای مجاز."""

    __tablename__ = "user_widget_layouts"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True, index=True)
    #: JSON {order: [widget_id…], pinned: [widget_id…], hidden: [widget_id…], sizes: {id: "sm|md|lg"}}
    layout: Mapped[str] = mapped_column(Text, default="{}")
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
