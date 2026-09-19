"""v1.7.1: support_messages table (two-way support conversation) — additive only.

Revision ID: a1b2c3d4e5f6
Revises: f2a3b4c5d6e7
Create Date: 2026-09-09
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "f2a3b4c5d6e7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    from app.database import Base
    import app.models  # noqa: F401
    bind = op.get_bind()
    if "support_messages" not in set(sa.inspect(bind).get_table_names()):
        Base.metadata.tables["support_messages"].create(bind)


def downgrade() -> None:
    op.drop_table("support_messages")
