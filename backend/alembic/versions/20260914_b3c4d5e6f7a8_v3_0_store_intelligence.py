"""v3.0: ai_insights table + product_batches.supplier_id — additive only.

Revision ID: b3c4d5e6f7a8
Revises: a1b2c3d4e5f6
Create Date: 2026-09-14
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b3c4d5e6f7a8"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    from app.database import Base
    import app.models  # noqa: F401
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "ai_insights" not in set(insp.get_table_names()):
        Base.metadata.tables["ai_insights"].create(bind)
    cols = {c["name"] for c in insp.get_columns("product_batches")}
    if "supplier_id" not in cols:
        with op.batch_alter_table("product_batches") as b:
            b.add_column(sa.Column("supplier_id", sa.Integer(), nullable=True))
        op.create_index("ix_product_batches_supplier_id", "product_batches", ["supplier_id"])
    backfill_batch_suppliers(bind)


def backfill_batch_suppliers(bind) -> int:
    """Older releases only recorded the supplier on the purchase journal line; copy it onto the batch."""
    res = bind.execute(sa.text(
        "UPDATE product_batches SET supplier_id = ("
        "  SELECT l.party_id FROM acc_journal_lines l JOIN acc_journal_entries e ON e.id = l.entry_id"
        "  WHERE e.source_type = 'ProductBatch' AND e.source_id = product_batches.id AND l.party_id IS NOT NULL LIMIT 1)"
        " WHERE supplier_id IS NULL"))
    return res.rowcount or 0


def downgrade() -> None:
    op.drop_index("ix_product_batches_supplier_id", table_name="product_batches")
    with op.batch_alter_table("product_batches") as b:
        b.drop_column("supplier_id")
    op.drop_table("ai_insights")
