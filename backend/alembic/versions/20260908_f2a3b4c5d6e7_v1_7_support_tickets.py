"""v1.7: support_tickets table — additive only.

Revision ID: f2a3b4c5d6e7
Revises: e1f2a3b4c5d6
Create Date: 2026-09-08
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f2a3b4c5d6e7"
down_revision: Union[str, None] = "e1f2a3b4c5d6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    from app.database import Base
    import app.models  # noqa: F401
    bind = op.get_bind()
    if "support_tickets" not in set(sa.inspect(bind).get_table_names()):
        Base.metadata.tables["support_tickets"].create(bind)


def downgrade() -> None:
    op.drop_table("support_tickets")
