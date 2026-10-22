# -*- coding: utf-8 -*-
"""v3.8 — experiment orchestration columns: frozen eligible list + exposure log.

``eligible`` freezes the population at PLAN so ASSIGN can only split the
pre-registered set; ``exposed`` records who actually saw the treatment, so
assigned-but-never-exposed customers are reported — never silently zeroed.
"""
from __future__ import annotations

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "a8c2e4f6b1d3"
down_revision: Union[str, None] = "f7a1c2d3e4b5"


def _columns(table: str) -> set[str]:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    return {c["name"] for c in insp.get_columns(table)} if table in insp.get_table_names() else set()


def upgrade() -> None:
    if "experiments" not in sa.inspect(op.get_bind()).get_table_names():
        return  # v3.7 catch-up creates the table with these columns on fresh installs
    cols = _columns("experiments")
    with op.batch_alter_table("experiments", schema=None) as batch_op:
        if "eligible" not in cols:
            batch_op.add_column(sa.Column("eligible", sa.Text(), nullable=False, server_default="[]"))
        if "exposed" not in cols:
            batch_op.add_column(sa.Column("exposed", sa.Text(), nullable=False, server_default="{}"))


def downgrade() -> None:
    if "experiments" not in sa.inspect(op.get_bind()).get_table_names():
        return
    cols = _columns("experiments")
    with op.batch_alter_table("experiments", schema=None) as batch_op:
        if "exposed" in cols:
            batch_op.drop_column("exposed")
        if "eligible" in cols:
            batch_op.drop_column("eligible")
