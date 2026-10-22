# -*- coding: utf-8 -*-
"""build-481 — campaign benefits that actually reach the till + insight auto-resolution.

Changes (all additive — no data is touched):

* ``campaigns`` — executable benefit rules: purchase ceiling, product targeting,
  first-purchase-only, total/per-customer usage limits, stacking, auto-apply,
  priority, used_count and source-insight provenance.
* ``campaign_redemptions`` — one audit row per (campaign, invoice): who granted
  which benefit to whom (§26).
* ``invoices`` — immutable campaign/benefit snapshot: campaign_id + the *name*
  frozen at sale time, benefit_source/amount and the consumed coupon code, so
  editing a festival later can never rewrite past receipts (§22).
* ``ai_insights`` — ``resolved_at`` / ``resolution``: a suggestion whose
  underlying condition cleared (stock was received elsewhere, the customer
  became eligible again …) is closed by the engine instead of staying active.

Revision ID: a481c2e0b7d5
Revises: c9e1f2a4b6d8
Create Date: 2026-09-29
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a481c2e0b7d5"
down_revision: Union[str, None] = "c9e1f2a4b6d8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

MONEY = sa.Numeric(18, 2)

#: (table, column, type, nullable, server_default)
_NEW_COLUMNS = [
    ("campaigns", sa.Column("max_purchase", MONEY, nullable=True)),
    ("campaigns", sa.Column("target_type", sa.String(16), nullable=False, server_default="ALL")),
    ("campaigns", sa.Column("target_ids", sa.Text(), nullable=True)),
    ("campaigns", sa.Column("first_purchase_only", sa.Boolean(), nullable=False, server_default=sa.false())),
    ("campaigns", sa.Column("usage_limit", sa.Integer(), nullable=True)),
    ("campaigns", sa.Column("per_customer_limit", sa.Integer(), nullable=True)),
    ("campaigns", sa.Column("stackable", sa.Boolean(), nullable=False, server_default=sa.false())),
    ("campaigns", sa.Column("auto_apply", sa.Boolean(), nullable=False, server_default=sa.false())),
    ("campaigns", sa.Column("priority", sa.Integer(), nullable=False, server_default="3")),
    ("campaigns", sa.Column("used_count", sa.Integer(), nullable=False, server_default="0")),
    ("campaigns", sa.Column("source_insight_id", sa.Integer(), nullable=True)),
    ("invoices", sa.Column("campaign_id", sa.Integer(), nullable=True)),
    ("invoices", sa.Column("campaign_name", sa.String(128), nullable=True)),
    ("invoices", sa.Column("benefit_source", sa.String(16), nullable=False, server_default="NONE")),
    ("invoices", sa.Column("benefit_amount", MONEY, nullable=False, server_default="0")),
    ("invoices", sa.Column("applied_coupon_code", sa.String(48), nullable=True)),
    ("ai_insights", sa.Column("resolved_at", sa.DateTime(), nullable=True)),
    ("ai_insights", sa.Column("resolution", sa.Text(), nullable=True)),
]

_REDEMPTION_TABLE = sa.Table(
    "campaign_redemptions",
    sa.MetaData(),
    sa.Column("id", sa.Integer(), primary_key=True),
    sa.Column("campaign_id", sa.Integer(), nullable=False),
    sa.Column("invoice_id", sa.Integer(), nullable=True),
    sa.Column("customer_id", sa.Integer(), nullable=True),
    sa.Column("amount", MONEY, nullable=False, server_default="0"),
    sa.Column("source", sa.String(16), nullable=False, server_default="CAMPAIGN"),
    sa.Column("created_at", sa.DateTime(), nullable=False),
    sa.Column("created_by", sa.Integer(), nullable=True),
)


def _has_column(bind, table: str, column: str) -> bool:
    insp = sa.inspect(bind)
    if table not in insp.get_table_names():
        return False
    return column in {c["name"] for c in insp.get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    for table, column in _NEW_COLUMNS:
        if not _has_column(bind, table, column.name):
            op.add_column(table, column)
    if not sa.inspect(bind).has_table("campaign_redemptions"):
        op.create_table(
            "campaign_redemptions",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("campaign_id", sa.Integer(), sa.ForeignKey("campaigns.id"), nullable=False, index=True),
            sa.Column("invoice_id", sa.Integer(), sa.ForeignKey("invoices.id"), nullable=True),
            sa.Column("customer_id", sa.Integer(), sa.ForeignKey("customers.id"), nullable=True),
            sa.Column("amount", MONEY, nullable=False, server_default="0"),
            sa.Column("source", sa.String(16), nullable=False, server_default="CAMPAIGN"),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        )


def downgrade() -> None:
    bind = op.get_bind()
    if sa.inspect(bind).has_table("campaign_redemptions"):
        op.drop_table("campaign_redemptions")
    for table, column in reversed(_NEW_COLUMNS):
        if _has_column(bind, table, column.name):
            with op.batch_alter_table(table) as batch:
                batch.drop_column(column.name)
