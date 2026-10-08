# -*- coding: utf-8 -*-
"""build-493 — explicit permission for cached/offline mobile sign-in.

Revision ID: d4930f0f4930
Revises: c488e1a0b7d5
Create Date: 2026-10-05
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d4930f0f4930"
down_revision: Union[str, None] = "c488e1a0b7d5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in sa.inspect(bind).get_columns("users")}
    if "offline_allowed" not in columns:
        # Preserve the old decision: local_only=False previously allowed cached login;
        # local_only=True remains online/LAN-only until an administrator opts in.
        op.add_column("users", sa.Column("offline_allowed", sa.Boolean(), nullable=False, server_default=sa.false()))
        op.execute(sa.text("UPDATE users SET offline_allowed = NOT COALESCE(local_only, TRUE)"))


def downgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("users")}
    if "offline_allowed" in columns:
        op.drop_column("users", "offline_allowed")
