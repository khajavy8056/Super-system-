# -*- coding: utf-8 -*-
"""v4.4.0: reminder escalation — one nullable column on brain_followups.

``next_sms_at`` is the earliest time the manager may be SMS-ed again about an
unanswered reminder. Idempotent (project convention): the column is added only
when missing; ``downgrade`` drops only this column.
"""
from __future__ import annotations

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "b7e9f1a3c5d8"
down_revision: Union[str, None] = "d4f6a8b1c2e3"
branch_labels = None
depends_on = None


def _cols() -> list[str]:
    """Column names of brain_followups (PRAGMA row = cid, name, type, …)."""
    conn = op.get_bind()
    return [r[1] for r in conn.execute(sa.text(
        "PRAGMA table_info(brain_followups)")).fetchall()]


def upgrade() -> None:
    cols = _cols()
    if cols and "next_sms_at" not in cols:
        op.add_column("brain_followups",
                      sa.Column("next_sms_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    cols = _cols()
    if cols and "next_sms_at" in cols:
        op.drop_column("brain_followups", "next_sms_at")
