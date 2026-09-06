"""phase-7: decimal quantities, units metadata, coupons/campaigns, sync queue,
diagnostics, stocktaking resume fields.

Revision ID: e5b21c74a903
Revises: d7a41c0f5b02
Create Date: 2026-09-04

SQLite cannot ALTER a column type in place, but it is dynamically typed: the
existing INTEGER columns already accept NUMERIC values, and SQLAlchemy applies
the Numeric(14,3) type on read/write. For PostgreSQL the ALTERs below are
executed. New columns/tables are created on both.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e5b21c74a903"
down_revision: Union[str, None] = "d7a41c0f5b02"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

QTY = sa.Numeric(14, 3)
MONEY = sa.Numeric(14, 2)

_NEW_COLUMNS = [
    ("units", sa.Column("allow_decimal", sa.Boolean(), nullable=False, server_default=sa.false())),
    ("units", sa.Column("decimals", sa.Integer(), nullable=False, server_default="0")),
    ("stocktakes", sa.Column("completed_by", sa.Integer(), nullable=True)),
    ("stocktakes", sa.Column("warehouse_id", sa.Integer(), nullable=True)),
    ("stocktakes", sa.Column("cursor_item_id", sa.Integer(), nullable=True)),
    ("stocktake_items", sa.Column("counted_at", sa.DateTime(), nullable=True)),
    ("stocktake_items", sa.Column("counted_by", sa.Integer(), nullable=True)),
]

_DECIMAL_COLUMNS = [
    ("product_batches", "quantity_received"),
    ("product_batches", "current_qty"),
    ("stock_movements", "quantity"),
    ("stocktake_items", "system_qty"),
    ("stocktake_items", "physical_qty"),
    ("stocktake_items", "difference"),
    ("invoice_items", "qty"),
    ("returns", "qty"),
]


def _has_column(bind, table: str, column: str) -> bool:
    insp = sa.inspect(bind)
    if table not in insp.get_table_names():
        return False
    return column in {c["name"] for c in insp.get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = set(insp.get_table_names())

    for table, column in _NEW_COLUMNS:
        if table in tables and not _has_column(bind, table, column.name):
            op.add_column(table, column)

    if bind.dialect.name != "sqlite":
        for table, column in _DECIMAL_COLUMNS:
            if table in tables and _has_column(bind, table, column):
                op.alter_column(table, column, type_=QTY, existing_nullable=True,
                                postgresql_using=f"{column}::numeric(14,3)")

    if "campaigns" not in tables:
        op.create_table(
            "campaigns",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("name", sa.String(128), nullable=False, index=True),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("discount_type", sa.String(16), nullable=False, server_default="PERCENT"),
            sa.Column("discount_value", MONEY, nullable=False, server_default="0"),
            sa.Column("min_purchase", MONEY, nullable=False, server_default="0"),
            sa.Column("max_discount", MONEY, nullable=True),
            sa.Column("valid_from", sa.DateTime(), nullable=True),
            sa.Column("valid_until", sa.DateTime(), nullable=True),
            sa.Column("auto_issue_threshold", MONEY, nullable=True),
            sa.Column("auto_issue_validity_days", sa.Integer(), nullable=False, server_default="30"),
            sa.Column("auto_issue_sms", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("status", sa.String(16), nullable=False, server_default="ACTIVE"),
            sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
        )

    if "coupons" not in tables:
        op.create_table(
            "coupons",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("code", sa.String(48), nullable=False, unique=True, index=True),
            sa.Column("campaign_id", sa.Integer(), sa.ForeignKey("campaigns.id"), nullable=True),
            sa.Column("customer_id", sa.Integer(), sa.ForeignKey("customers.id"), nullable=True),
            sa.Column("customer_phone", sa.String(32), nullable=True, index=True),
            sa.Column("discount_type", sa.String(16), nullable=False, server_default="PERCENT"),
            sa.Column("discount_value", MONEY, nullable=False, server_default="0"),
            sa.Column("min_purchase", MONEY, nullable=False, server_default="0"),
            sa.Column("max_discount", MONEY, nullable=True),
            sa.Column("valid_from", sa.DateTime(), nullable=True),
            sa.Column("valid_until", sa.DateTime(), nullable=True),
            sa.Column("usage_limit", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("used_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("status", sa.String(16), nullable=False, server_default="ACTIVE"),
            sa.Column("note", sa.Text(), nullable=True),
            sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
        )

    if "coupon_redemptions" not in tables:
        op.create_table(
            "coupon_redemptions",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("coupon_id", sa.Integer(), sa.ForeignKey("coupons.id"), nullable=False, index=True),
            sa.Column("invoice_id", sa.Integer(), sa.ForeignKey("invoices.id"), nullable=True),
            sa.Column("customer_id", sa.Integer(), sa.ForeignKey("customers.id"), nullable=True),
            sa.Column("amount", MONEY, nullable=False, server_default="0"),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        )

    if "sync_jobs" not in tables:
        op.create_table(
            "sync_jobs",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("job_type", sa.String(32), nullable=False, index=True),
            sa.Column("payload", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("status", sa.String(16), nullable=False, server_default="PENDING", index=True),
            sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="5"),
            sa.Column("last_error", sa.Text(), nullable=True),
            sa.Column("next_attempt_at", sa.DateTime(), nullable=True),
            sa.Column("completed_at", sa.DateTime(), nullable=True),
            sa.Column("reference_type", sa.String(32), nullable=True),
            sa.Column("reference_id", sa.Integer(), nullable=True),
            sa.Column("idempotency_key", sa.String(96), nullable=True, unique=True),
            sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
        )

    if "diagnostic_runs" not in tables:
        op.create_table(
            "diagnostic_runs",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("started_at", sa.DateTime(), nullable=False),
            sa.Column("finished_at", sa.DateTime(), nullable=True),
            sa.Column("total", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("passed", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("failed", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("skipped", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("report", sa.Text(), nullable=False, server_default="[]"),
            sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        )


def downgrade() -> None:
    for table in ("diagnostic_runs", "sync_jobs", "coupon_redemptions", "coupons", "campaigns"):
        op.execute(f"DROP TABLE IF EXISTS {table}")
