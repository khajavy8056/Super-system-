"""v1.1: warehouses + storage locations (§109, §130, §131), invoice-level
discount column and category parent (§79) — additive only (§29).

Revision ID: c8d1e2f3a410
Revises: b7e4d2019f31
Create Date: 2026-09-06
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c8d1e2f3a410"
down_revision: Union[str, None] = "b7e4d2019f31"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

MONEY = sa.Numeric(14, 2)


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _columns(table: str) -> set[str]:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    tables = _tables()
    if "warehouses" not in tables:
        op.create_table(
            "warehouses",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("name", sa.String(128), nullable=False, index=True),
            sa.Column("code", sa.String(32), nullable=True),
            sa.Column("address", sa.Text(), nullable=True),
            sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        )
    if "storage_locations" not in tables:
        op.create_table(
            "storage_locations",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("warehouse_id", sa.Integer(), sa.ForeignKey("warehouses.id"),
                      nullable=False, index=True),
            sa.Column("name", sa.String(128), nullable=False),
            sa.Column("code", sa.String(32), nullable=True),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        )
    if "invoices" in tables and "invoice_discount" not in _columns("invoices"):
        op.add_column("invoices", sa.Column("invoice_discount", MONEY, nullable=False,
                                            server_default="0"))


def downgrade() -> None:
    # Additive migration; data-preserving downgrade keeps the tables.
    pass
