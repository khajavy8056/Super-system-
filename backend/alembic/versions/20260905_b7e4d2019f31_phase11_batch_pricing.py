"""phase-11: per-batch pricing fields (§6) and internal-barcode flag (§16).

Revision ID: b7e4d2019f31
Revises: a1c93f4d7e10
Create Date: 2026-09-05

§29 rule: an update must never destroy user data. This migration is additive
only — it appends nullable/defaulted columns. Nothing is dropped, renamed or
retyped, so an existing shop upgrades with every product, batch, invoice and
customer intact.

Why these columns:
  - supplier_price / discount / tax live on the BATCH, because the same
    product bought twice can carry different terms and both must stay
    auditable. Writing them onto Product would silently destroy price history.
  - has_own_barcode records whether the barcode is a real manufacturer GTIN
    or one the system minted for a loose/bulk item. External catalogues can
    only be consulted for the former.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b7e4d2019f31"
down_revision: Union[str, None] = "a1c93f4d7e10"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

MONEY = sa.Numeric(14, 2)


def _columns(table: str) -> set[str]:
    bind = op.get_bind()
    return {c["name"] for c in sa.inspect(bind).get_columns(table)}


def upgrade() -> None:
    existing = _columns("product_batches")
    # Idempotent: a shop may already have been stamped by create_all().
    if "supplier_price" not in existing:
        op.add_column("product_batches",
                      sa.Column("supplier_price", MONEY, nullable=True))
    if "discount" not in existing:
        op.add_column("product_batches",
                      sa.Column("discount", MONEY, nullable=False,
                                server_default="0"))
    if "tax" not in existing:
        op.add_column("product_batches",
                      sa.Column("tax", MONEY, nullable=False,
                                server_default="0"))

    if "has_own_barcode" not in _columns("products"):
        # Existing rows were all created from real barcodes, so True is the
        # correct backfill — it preserves current behaviour exactly.
        op.add_column("products",
                      sa.Column("has_own_barcode", sa.Boolean(), nullable=False,
                                server_default=sa.true()))


def downgrade() -> None:
    for col in ("tax", "discount", "supplier_price"):
        if col in _columns("product_batches"):
            op.drop_column("product_batches", col)
    if "has_own_barcode" in _columns("products"):
        op.drop_column("products", "has_own_barcode")
