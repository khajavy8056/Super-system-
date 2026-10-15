# -*- coding: utf-8 -*-
"""build-515 — جادوگر تعریف جشنواره: شرط تعداد خرید.

Changes (additive — no data is touched):

* ``campaigns.min_purchase_count`` — شرط «بعد از N خرید»: پاداش/صدور کوپن
  پس از رسیدن تعداد خریدهای مشتری به N فعال می‌شود (صفر = غیرفعال). مکمل
  ``min_purchase`` (مبلغی) برای جادوگر ۸ گامی تعریف جشنواره.
* ``campaigns.reward_next_only`` — پاداش فقط کوپن خرید بعدی است (نوع «هدیهٔ
  خرید بعدی» جادوگر)، نه تخفیف همین فاکتور.

Revision ID: e515a1b2c3d4
Revises: d4930f0f4930
Create Date: 2026-10-14
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e515a1b2c3d4"
down_revision: Union[str, None] = "d4930f0f4930"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in sa.inspect(bind).get_columns("campaigns")}
    # build-493 convention: idempotent guards — a pre-3.7 DB that was created by
    # create_all already carries the newer model columns; never double-add.
    if "min_purchase_count" not in columns:
        op.add_column("campaigns", sa.Column("min_purchase_count", sa.Integer(),
                                             nullable=False, server_default="0"))
    if "reward_next_only" not in columns:
        op.add_column("campaigns", sa.Column("reward_next_only", sa.Boolean(),
                                             nullable=False, server_default=sa.false()))


def downgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("campaigns")}
    if "reward_next_only" in columns:
        op.drop_column("campaigns", "reward_next_only")
    if "min_purchase_count" in columns:
        op.drop_column("campaigns", "min_purchase_count")
