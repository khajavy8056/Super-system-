"""v1.4: double-entry accounting tables — additive only.

Revision ID: e1f2a3b4c5d6
Revises: d9e4f5a6b7c8
Create Date: 2026-09-08
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e1f2a3b4c5d6"
down_revision: Union[str, None] = "d9e4f5a6b7c8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLES = ["acc_cash_sessions", "acc_cheques", "acc_expenses", "acc_expense_categories", "acc_suppliers",
          "acc_journal_lines", "acc_journal_entries", "acc_fiscal_periods", "acc_accounts"]


def upgrade() -> None:
    # Tables are created from the ORM metadata (create_all runs before alembic
    # in database.init_db); this keeps a real revision so downgrade works and
    # an old DB upgraded via `alembic upgrade head` gets them too.
    from app.database import Base
    import app.models  # noqa: F401
    bind = op.get_bind()
    existing = set(sa.inspect(bind).get_table_names())
    for name in reversed(TABLES):
        if name not in existing:
            Base.metadata.tables[name].create(bind)


def downgrade() -> None:
    for name in TABLES:
        op.drop_table(name)
