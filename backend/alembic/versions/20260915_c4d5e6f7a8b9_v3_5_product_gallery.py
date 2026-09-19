"""v3.5: products.gallery — up to three shipped image links per catalogue line.

Revision ID: c4d5e6f7a8b9
Revises: b3c4d5e6f7a8
Create Date: 2026-09-15
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c4d5e6f7a8b9"
down_revision: Union[str, None] = "b3c4d5e6f7a8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    cols = {c["name"] for c in sa.inspect(bind).get_columns("products")}
    if "gallery" not in cols:
        with op.batch_alter_table("products") as b:
            b.add_column(sa.Column("gallery", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("products") as b:
        b.drop_column("gallery")
