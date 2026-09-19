"""v1.3: stocktake scheduling (scheduled_for, reminder_note) — additive only.

Revision ID: d9e4f5a6b7c8
Revises: c8d1e2f3a410
Create Date: 2026-09-07
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d9e4f5a6b7c8"
down_revision: Union[str, None] = "c8d1e2f3a410"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _columns(table: str) -> set[str]:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    cols = _columns("stocktakes")
    if "scheduled_for" not in cols:
        op.add_column("stocktakes", sa.Column("scheduled_for", sa.Date(), nullable=True))
    if "reminder_note" not in cols:
        op.add_column("stocktakes", sa.Column("reminder_note", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("stocktakes") as b:
        b.drop_column("reminder_note")
        b.drop_column("scheduled_for")
