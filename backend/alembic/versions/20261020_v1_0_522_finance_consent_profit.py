# -*- coding: utf-8 -*-
"""v1.0.522 — I-09/I-08/I-11 financial + consent fixes (audit 1.0.521).

* customer: sms_consent, sms_consent_at, sms_opt_out_reason (I-11)
* invoices view net already handled in code (no schema change) — this revision
  ensures customer consent columns exist for enforcement.
* also adds daily_sales_summary materialised view prep (F-16) via table if missing.
"""
from typing import Sequence, Union
import sqlalchemy as sa
from alembic import op

revision: str = "v1_0_522"
down_revision: Union[str, None] = "e515a1b2c3d4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column(bind, table: str, column: str) -> bool:
    insp = sa.inspect(bind)
    if table not in insp.get_table_names():
        return False
    return column in {c["name"] for c in insp.get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    # I-11
    new_cols = [
        ("customers", sa.Column("sms_consent", sa.Boolean(), nullable=False, server_default=sa.false())),
        ("customers", sa.Column("sms_consent_at", sa.DateTime(), nullable=True)),
        ("customers", sa.Column("sms_opt_out_reason", sa.String(255), nullable=True)),
    ]
    for table, col in new_cols:
        if not _has_column(bind, table, col.name):
            op.add_column(table, col)
    # F-16 daily summary (optional materialised table)
    if not sa.inspect(bind).has_table("daily_sales_summary"):
        op.create_table(
            "daily_sales_summary",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("day", sa.Date(), nullable=False, unique=True),
            sa.Column("invoice_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("gross_sales", sa.Numeric(18,2), nullable=False, server_default="0"),
            sa.Column("discounts", sa.Numeric(18,2), nullable=False, server_default="0"),
            sa.Column("net_sales", sa.Numeric(18,2), nullable=False, server_default="0"),
            sa.Column("profit", sa.Numeric(18,2), nullable=False, server_default="0"),
            sa.Column("refunds", sa.Numeric(18,2), nullable=False, server_default="0"),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
        )
    # purchase orders (F-07 minimal)
    if not sa.inspect(bind).has_table("purchase_orders"):
        op.create_table(
            "purchase_orders",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("supplier_id", sa.Integer(), sa.ForeignKey("suppliers.id"), nullable=True),
            sa.Column("status", sa.String(16), nullable=False, server_default="DRAFT"),
            sa.Column("total_cost", sa.Numeric(18,2), nullable=False, server_default="0"),
            sa.Column("note", sa.Text(), nullable=True),
            sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
        )
    if not sa.inspect(bind).has_table("purchase_order_lines"):
        op.create_table(
            "purchase_order_lines",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("order_id", sa.Integer(), sa.ForeignKey("purchase_orders.id"), nullable=False),
            sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id"), nullable=False),
            sa.Column("qty", sa.Numeric(12,3), nullable=False),
            sa.Column("unit_cost", sa.Numeric(18,2), nullable=False),
            sa.Column("received_qty", sa.Numeric(12,3), nullable=False, server_default="0"),
        )


def downgrade() -> None:
    bind = op.get_bind()
    for tbl, col in [("customers","sms_opt_out_reason"),("customers","sms_consent_at"),("customers","sms_consent")]:
        if _has_column(bind, tbl, col):
            with op.batch_alter_table(tbl) as b:
                b.drop_column(col)
    if sa.inspect(bind).has_table("purchase_order_lines"):
        op.drop_table("purchase_order_lines")
    if sa.inspect(bind).has_table("purchase_orders"):
        op.drop_table("purchase_orders")
    if sa.inspect(bind).has_table("daily_sales_summary"):
        op.drop_table("daily_sales_summary")
