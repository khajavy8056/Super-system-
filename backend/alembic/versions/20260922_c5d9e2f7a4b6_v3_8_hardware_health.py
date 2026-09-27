# -*- coding: utf-8 -*-
"""v3.8: hardware registry discovery ids + health tracking + reconnect backoff.

Idempotent (project convention): every column is added only when missing, so
databases created from newer models and then migrated through this revision
do not hit "duplicate column" errors.
"""
from __future__ import annotations

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "c5d9e2f7a4b6"
down_revision: Union[str, None] = "a8c2e4f6b1d3"

COLUMNS: tuple[tuple[str, sa.types.TypeEngine], ...] = (
    ("vendor_id", sa.String(8)),
    ("product_id", sa.String(8)),
    ("serial_number", sa.String(64)),
    ("health", sa.String(24)),
    ("last_error", sa.Text()),
    ("consecutive_failures", sa.Integer()),
    ("last_seen_at", sa.DateTime()),
    ("capabilities", sa.Text()),
)


def _columns(table: str) -> set[str]:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    return {c["name"] for c in insp.get_columns(table)} if table in insp.get_table_names() else set()


def upgrade() -> None:
    if "hardware_devices" not in sa.inspect(op.get_bind()).get_table_names():
        return
    cols = _columns("hardware_devices")
    with op.batch_alter_table("hardware_devices", schema=None) as batch_op:
        for name, type_ in COLUMNS:
            if name not in cols:
                kw: dict = {"nullable": True}
                if name == "consecutive_failures":
                    kw = {"nullable": False, "server_default": "0"}
                batch_op.add_column(sa.Column(name, type_, **kw))


def downgrade() -> None:
    if "hardware_devices" not in sa.inspect(op.get_bind()).get_table_names():
        return
    cols = _columns("hardware_devices")
    with op.batch_alter_table("hardware_devices", schema=None) as batch_op:
        for name, _type_ in reversed(COLUMNS):
            if name in cols:
                batch_op.drop_column(name)
