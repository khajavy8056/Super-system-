"""counters table for atomic invoice numbering (phase-0, BUG-004)

Revision ID: c2f10a9b3e01
Revises: 3590913a6c4d
Create Date: 2026-09-04

Uses CREATE TABLE IF NOT EXISTS so it is safe on databases that already had
the table created by ``create_all`` (see database._sync_alembic).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "c2f10a9b3e01"
down_revision: Union[str, None] = "3590913a6c4d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS counters (
            name VARCHAR(64) NOT NULL,
            value INTEGER NOT NULL,
            PRIMARY KEY (name)
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS counters")
