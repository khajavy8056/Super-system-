"""phase-1 resolvers: resolver source_code + external_sources.connection

Revision ID: d7a41c0f5b02
Revises: c2f10a9b3e01
Create Date: 2026-09-04
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "d7a41c0f5b02"
down_revision: Union[str, None] = "c2f10a9b3e01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("product_resolver_results") as batch_op:
        batch_op.add_column(sa.Column("source_code", sa.String(length=64), nullable=True))
    with op.batch_alter_table("external_sources") as batch_op:
        batch_op.add_column(sa.Column("connection", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("product_resolver_results") as batch_op:
        batch_op.drop_column("source_code")
    with op.batch_alter_table("external_sources") as batch_op:
        batch_op.drop_column("connection")
