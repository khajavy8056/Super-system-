# -*- coding: utf-8 -*-
"""build-488 — لایهٔ سرمایهٔ انسانی، اطلاعیه‌ها و داشبورد پویا (دستور جامع مالک).

کاملاً افزودنی: جدول‌های شیفت/حضور/حقوق/اطلاعیه/دستاورد/امتیاز/چیدمان داشبورد +
جدول دسترسی مستقیم کاربر (§۲) + ستون‌های پروفایل (§۱) + اعلان شخصی (§۱۷).
دادهٔ موجود هرگز دست نمی‌خورد؛ downgrade فقط همین افزودنی‌ها را برمی‌دارد.

Revision ID: c488e1a0b7d5
Revises: b482e1f0a2c3
Create Date: 2026-10-02
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c488e1a0b7d5"
down_revision: Union[str, None] = "b482e1f0a2c3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(bind, table: str) -> bool:
    return table in sa.inspect(bind).get_table_names()


def _has_column(bind, table: str, column: str) -> bool:
    insp = sa.inspect(bind)
    if table not in insp.get_table_names():
        return False
    return column in {c["name"] for c in insp.get_columns(table)}


def _ts() -> list:
    """created_at/updated_at دقیقاً مثل TimestampMixin."""
    return [
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    ]


def upgrade() -> None:
    bind = op.get_bind()

    # ── users: پروفایل (§۱) + فروشگاه (§۱۶) ──
    for col, typ, nullable in [
        ("phone", sa.String(32), True),
        ("job_title", sa.String(128), True),
        ("avatar_path", sa.String(255), True),
        ("hire_date", sa.DateTime(), True),
        ("store", sa.String(128), True),
    ]:
        if not _has_column(bind, "users", col):
            op.add_column("users", sa.Column(col, typ, nullable=nullable))

    # ── user_permissions: دسترسی مستقیم مستقل از Role (§۲) ──
    if not _has_table(bind, "user_permissions"):
        op.create_table(
            "user_permissions",
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
            sa.Column("permission_id", sa.Integer(), sa.ForeignKey("permissions.id", ondelete="CASCADE"), primary_key=True),
        )

    # ── notifications: اعلان شخصی (§۱۷) ──
    for col, typ in [("user_id", sa.Integer()), ("seen_at", sa.DateTime()), ("read_at", sa.DateTime())]:
        if not _has_column(bind, "notifications", col):
            op.add_column("notifications", sa.Column(col, typ, nullable=True))

    # ── hr_shifts (§۱۸) ──
    if not _has_table(bind, "hr_shifts"):
        op.create_table(
            "hr_shifts",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("name", sa.String(128), nullable=False),
            sa.Column("start_time", sa.String(5), nullable=False),
            sa.Column("end_time", sa.String(5), nullable=False),
            sa.Column("workdays", sa.Text(), nullable=False, server_default="[]"),
            sa.Column("store", sa.String(128), nullable=False, server_default=""),
            sa.Column("department", sa.String(128), nullable=False, server_default=""),
            sa.Column("role_hint", sa.String(64), nullable=True),
            sa.Column("status", sa.String(16), nullable=False, server_default="ACTIVE"),
            sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
            *_ts(),
        )
        op.create_index("ix_hr_shifts_status", "hr_shifts", ["status"])

    # ── hr_shift_assignments (§۱۸) ──
    if not _has_table(bind, "hr_shift_assignments"):
        op.create_table(
            "hr_shift_assignments",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("shift_id", sa.Integer(), sa.ForeignKey("hr_shifts.id", ondelete="CASCADE"), nullable=False),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("day", sa.String(10), nullable=False, server_default=""),
            sa.Column("status", sa.String(16), nullable=False, server_default="ACTIVE"),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
            sa.UniqueConstraint("shift_id", "user_id", "day", name="uq_shift_user_day"),
        )
        op.create_index("ix_hr_shift_assignments_shift_id", "hr_shift_assignments", ["shift_id"])
        op.create_index("ix_hr_shift_assignments_user_id", "hr_shift_assignments", ["user_id"])

    # ── hr_shift_attendance (§۱۹) ──
    if not _has_table(bind, "hr_shift_attendance"):
        op.create_table(
            "hr_shift_attendance",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("shift_id", sa.Integer(), sa.ForeignKey("hr_shifts.id", ondelete="SET NULL"), nullable=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("day", sa.String(10), nullable=False),
            sa.Column("started_at", sa.DateTime(), nullable=True),
            sa.Column("ended_at", sa.DateTime(), nullable=True),
            sa.Column("late_minutes", sa.Integer(), nullable=True),
            sa.Column("early_leave_minutes", sa.Integer(), nullable=True),
            sa.Column("note", sa.Text(), nullable=True),
            sa.UniqueConstraint("shift_id", "user_id", "day", name="uq_att_shift_user_day"),
        )
        op.create_index("ix_hr_shift_attendance_user_id", "hr_shift_attendance", ["user_id"])
        op.create_index("ix_hr_shift_attendance_day", "hr_shift_attendance", ["day"])

    # ── hr_payroll (§۲۶–۲۷) ──
    if not _has_table(bind, "hr_payroll"):
        op.create_table(
            "hr_payroll",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("period", sa.String(7), nullable=False),
            sa.Column("base_salary", sa.Numeric(18, 2), nullable=False, server_default="0"),
            sa.Column("hourly_pay", sa.Numeric(18, 2), nullable=False, server_default="0"),
            sa.Column("worked_hours", sa.Numeric(18, 2), nullable=False, server_default="0"),
            sa.Column("overtime_hours", sa.Numeric(18, 2), nullable=False, server_default="0"),
            sa.Column("bonus", sa.Numeric(18, 2), nullable=False, server_default="0"),
            sa.Column("benefits", sa.Numeric(18, 2), nullable=False, server_default="0"),
            sa.Column("deductions", sa.Numeric(18, 2), nullable=False, server_default="0"),
            sa.Column("penalty", sa.Numeric(18, 2), nullable=False, server_default="0"),
            sa.Column("total", sa.Numeric(18, 2), nullable=False, server_default="0"),
            sa.Column("status", sa.String(16), nullable=False, server_default="DRAFT"),
            sa.Column("payment_ref", sa.String(128), nullable=True),
            sa.Column("note", sa.Text(), nullable=True),
            sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
            *_ts(),
        )
        op.create_index("ix_hr_payroll_user_id", "hr_payroll", ["user_id"])
        op.create_index("ix_hr_payroll_period", "hr_payroll", ["period"])

    # ── announcements (§۱۴–۱۶) ──
    if not _has_table(bind, "announcements"):
        op.create_table(
            "announcements",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("title", sa.String(255), nullable=False),
            sa.Column("body", sa.Text(), nullable=False, server_default=""),
            sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("status", sa.String(16), nullable=False, server_default="PUBLISHED"),
            sa.Column("priority", sa.Integer(), nullable=False, server_default="3"),
            sa.Column("publish_at", sa.DateTime(), nullable=True),
            sa.Column("expires_at", sa.DateTime(), nullable=True),
            sa.Column("target_kind", sa.String(16), nullable=False, server_default="ALL"),
            sa.Column("target_store", sa.String(128), nullable=True),
            sa.Column("target_roles", sa.Text(), nullable=False, server_default="[]"),
            sa.Column("target_users", sa.Text(), nullable=False, server_default="[]"),
            sa.Column("attachment_path", sa.String(255), nullable=True),
            *_ts(),
        )
        op.create_index("ix_announcements_status", "announcements", ["status"])

    # ── announcement_reads (§۱۷) ──
    if not _has_table(bind, "announcement_reads"):
        op.create_table(
            "announcement_reads",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("announcement_id", sa.Integer(), sa.ForeignKey("announcements.id", ondelete="CASCADE"), nullable=False),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("delivered_at", sa.DateTime(), nullable=True),
            sa.Column("seen_at", sa.DateTime(), nullable=True),
            sa.Column("read_at", sa.DateTime(), nullable=True),
            sa.UniqueConstraint("announcement_id", "user_id", name="uq_ann_user"),
        )
        op.create_index("ix_announcement_reads_announcement_id", "announcement_reads", ["announcement_id"])
        op.create_index("ix_announcement_reads_user_id", "announcement_reads", ["user_id"])

    # ── hr_achievements (§۳۵) ──
    if not _has_table(bind, "hr_achievements"):
        op.create_table(
            "hr_achievements",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("kind", sa.String(16), nullable=False, server_default="BADGE"),
            sa.Column("code", sa.String(64), nullable=False),
            sa.Column("title", sa.String(128), nullable=False),
            sa.Column("description", sa.Text(), nullable=False, server_default=""),
            sa.Column("level", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("evidence", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("awarded_at", sa.DateTime(), nullable=False),
            *_ts(),
            sa.UniqueConstraint("user_id", "code", name="uq_ach_user_code"),
        )
        op.create_index("ix_hr_achievements_user_id", "hr_achievements", ["user_id"])
        op.create_index("ix_hr_achievements_code", "hr_achievements", ["code"])

    # ── hr_score_events (§۳۴) ──
    if not _has_table(bind, "hr_score_events"):
        op.create_table(
            "hr_score_events",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("points", sa.Integer(), nullable=False),
            sa.Column("source", sa.String(32), nullable=False),
            sa.Column("evidence", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("note", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        )
        op.create_index("ix_hr_score_events_user_id", "hr_score_events", ["user_id"])
        op.create_index("ix_hr_score_events_source", "hr_score_events", ["source"])
        op.create_index("ix_hr_score_events_created_at", "hr_score_events", ["created_at"])

    # ── user_widget_layouts (§۸) ──
    if not _has_table(bind, "user_widget_layouts"):
        op.create_table(
            "user_widget_layouts",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("layout", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("user_id", name="uq_widget_layout_user"),
        )
        op.create_index("ix_user_widget_layouts_user_id", "user_widget_layouts", ["user_id"])


def downgrade() -> None:
    bind = op.get_bind()
    for table in ("user_widget_layouts", "hr_score_events", "hr_achievements",
                  "announcement_reads", "announcements", "hr_payroll",
                  "hr_shift_attendance", "hr_shift_assignments", "hr_shifts"):
        if _has_table(bind, table):
            op.drop_table(table)
    if _has_table(bind, "user_permissions"):
        op.drop_table("user_permissions")
    for col in ("user_id", "seen_at", "read_at"):
        if _has_column(bind, "notifications", col):
            op.drop_column("notifications", col)
    for col in ("store", "hire_date", "avatar_path", "job_title", "phone"):
        if _has_column(bind, "users", col):
            op.drop_column("users", col)
