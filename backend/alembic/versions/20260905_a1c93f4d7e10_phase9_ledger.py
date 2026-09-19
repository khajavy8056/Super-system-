"""phase-9: customer credit accounts (ledger), extended customer profile.

Revision ID: a1c93f4d7e10
Revises: e5b21c74a903
Create Date: 2026-09-05

§29 rule: an update must never destroy user data. This migration is additive
only — it creates one new table and adds nullable/defaulted columns to
`customers`. No existing column is dropped, renamed or retyped, so an existing
installation upgrades with every product, invoice and customer intact.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a1c93f4d7e10"
down_revision: Union[str, None] = "e5b21c74a903"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

MONEY = sa.Numeric(14, 2)

_CUSTOMER_COLUMNS = [
    sa.Column("last_name", sa.String(128), nullable=True),
    sa.Column("address", sa.String(512), nullable=True),
    sa.Column("notes", sa.String(1024), nullable=True),
    sa.Column("credit_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
    sa.Column("credit_limit", MONEY, nullable=False, server_default="0"),
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

    if "customers" in tables:
        for column in _CUSTOMER_COLUMNS:
            if not _has_column(bind, "customers", column.name):
                op.add_column("customers", column)

    if "customer_ledger_entries" not in tables:
        op.create_table(
            "customer_ledger_entries",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("customer_id", sa.Integer(),
                      sa.ForeignKey("customers.id"), nullable=False, index=True),
            sa.Column("entry_type", sa.String(24), nullable=False, index=True),
            sa.Column("amount", MONEY, nullable=False, server_default="0"),
            sa.Column("balance_after", MONEY, nullable=False, server_default="0"),
            sa.Column("invoice_id", sa.Integer(),
                      sa.ForeignKey("invoices.id"), nullable=True, index=True),
            sa.Column("method", sa.String(16), nullable=True),
            sa.Column("note", sa.String(512), nullable=True),
            sa.Column("created_by", sa.Integer(),
                      sa.ForeignKey("users.id"), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
        )
        op.create_index(
            "ix_customer_ledger_customer_id_id",
            "customer_ledger_entries", ["customer_id", "id"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = set(insp.get_table_names())

    if "customer_ledger_entries" in tables:
        op.drop_index("ix_customer_ledger_customer_id_id",
                      table_name="customer_ledger_entries")
        op.drop_table("customer_ledger_entries")

    # Customer profile columns are intentionally NOT dropped on downgrade:
    # they may hold real addresses/notes entered by the shop, and losing them
    # would violate the "no update destroys data" rule.
