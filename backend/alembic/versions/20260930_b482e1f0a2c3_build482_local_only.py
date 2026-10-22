# -*- coding: utf-8 -*-
"""build-482 — «دسترسی فقط به صورت بومی» (local-only sign-in policy).

The phone may sign a user in ONLY while it is on the shop's own network when
``users.local_only`` is set (checked by default for non-admin users). Unchecked
→ the user may work outside the network too (phone standalone / relay) and the
data syncs back when the phone rejoins the LAN. The main admin (role
«Administrator») is exempt by role. Fully additive — no data is touched.

Revision ID: b482e1f0a2c3
Revises: a481c2e0b7d5
Create Date: 2026-09-30
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b482e1f0a2c3"
down_revision: Union[str, None] = "a481c2e0b7d5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column(bind, table: str, column: str) -> bool:
    insp = sa.inspect(bind)
    if table not in insp.get_table_names():
        return False
    return column in {c["name"] for c in insp.get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    if not _has_column(bind, "users", "local_only"):
        op.add_column("users", sa.Column("local_only", sa.Boolean(), nullable=False, server_default=sa.true()))


def downgrade() -> None:
    bind = op.get_bind()
    if _has_column(bind, "users", "local_only"):
        with op.batch_alter_table("users") as batch:
            batch.drop_column("local_only")
