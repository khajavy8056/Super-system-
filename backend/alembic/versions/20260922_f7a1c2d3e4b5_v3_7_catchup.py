"""v3.7 — schema catch-up: make ``alembic upgrade head`` equal the models.

Revision ID: f7a1c2d3e4b5
Revises: c4d5e6f7a8b9
Create Date: 2026-09-22

Starting with v3.7, Alembic is the ONLY schema manager (``init_db`` no longer
runs ``create_all``). For that to be safe, ``upgrade head`` on an empty
database must produce exactly the schema the models describe. Audit (Sept 2026)
found these gaps — tables/columns that only ``create_all``/reconcile provided:

1. ``product_bank`` (v2.7 BankItem) was never migrated — CREATE TABLE.
2. ``ix_customers_phone`` (Customer.phone index) was never migrated — CREATE INDEX.
3. ``ix_customer_ledger_customer_id_id`` exists in migrated DBs but not in the
   models (leftover of an old revision) — DROP INDEX (redundant; the
   per-column indexes remain).
4. ``sms_messages.next_retry_at`` (v3.7 SMS backoff) — ADD COLUMN.
5. ``experiments`` (v3.7 experiment registry) — CREATE TABLE.

Defensive guards (``IF NOT EXISTS`` / inspector checks): databases created by
pre-3.7 releases via ``create_all`` + stamp ALREADY have (1), (2) and (4)'s
predecessors — a plain CREATE would fail the upgrade on exactly the shops we
must not break. Every step is therefore applied only when missing. Downgrade
removes what upgrade would have created (also guarded).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f7a1c2d3e4b5"
down_revision: Union[str, None] = "c4d5e6f7a8b9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _columns(table: str) -> set[str]:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def _indexes(table: str) -> set[str]:
    try:
        return {i["name"] for i in sa.inspect(op.get_bind()).get_indexes(table)}
    except Exception:
        return set()


def upgrade() -> None:
    tables = _tables()

    # 1) product_bank — mirror of models.external.BankItem
    if "product_bank" not in tables:
        op.create_table(
            "product_bank",
            sa.Column("barcode", sa.String(length=64), nullable=False),
            sa.Column("name", sa.String(length=255), nullable=False),
            sa.Column("brand", sa.String(length=128), nullable=True),
            sa.Column("unit", sa.String(length=64), nullable=True),
            sa.Column("category", sa.String(length=128), nullable=True),
            sa.Column("image_url", sa.Text(), nullable=True),
            sa.Column("source", sa.String(length=16), nullable=False,
                      server_default="ONLINE"),
            sa.Column("confidence", sa.String(length=16), nullable=False,
                      server_default="MEDIUM"),
            sa.Column("updated_at", sa.DateTime(), nullable=False,
                      server_default=sa.text("(CURRENT_TIMESTAMP)")),
            sa.PrimaryKeyConstraint("barcode"),
        )
    if "ix_product_bank_name" not in _indexes("product_bank"):
        op.create_index("ix_product_bank_name", "product_bank", ["name"], unique=False)
    if "ix_product_bank_updated_at" not in _indexes("product_bank"):
        op.create_index("ix_product_bank_updated_at", "product_bank", ["updated_at"], unique=False)

    # 2) customers.phone index (Customer.phone index=True)
    if "customers" in _tables() and "ix_customers_phone" not in _indexes("customers"):
        op.create_index("ix_customers_phone", "customers", ["phone"], unique=False)

    # 3) drop the redundant leftover index (models never declared it)
    if "ix_customer_ledger_customer_id_id" in _indexes("customer_ledger_entries"):
        with op.batch_alter_table("customer_ledger_entries", schema=None) as batch_op:
            batch_op.drop_index("ix_customer_ledger_customer_id_id")

    # 4) SMS backoff gate
    if "sms_messages" in _tables() and "next_retry_at" not in _columns("sms_messages"):
        with op.batch_alter_table("sms_messages", schema=None) as batch_op:
            batch_op.add_column(sa.Column("next_retry_at", sa.DateTime(), nullable=True))

    # 5) experiments — mirror of models.insights.Experiment
    if "experiments" not in _tables():
        op.create_table(
            "experiments",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("name", sa.String(length=128), nullable=False),
            sa.Column("hypothesis", sa.Text(), nullable=True),
            sa.Column("action_type", sa.String(length=32), nullable=False,
                      server_default=""),
            sa.Column("insight_id", sa.Integer(), nullable=True),
            sa.Column("campaign_id", sa.Integer(), nullable=True),
            sa.Column("status", sa.String(length=16), nullable=False,
                      server_default="DRAFT"),
            sa.Column("seed", sa.String(length=64), nullable=False, server_default=""),
            sa.Column("planned_per_arm", sa.Integer(), nullable=False,
                      server_default="100"),
            sa.Column("window_days", sa.Integer(), nullable=False, server_default="28"),
            sa.Column("minimum_net_profit", sa.String(length=32), nullable=False,
                      server_default="0"),
            sa.Column("treatment", sa.Text(), nullable=False, server_default="[]"),
            sa.Column("control", sa.Text(), nullable=False, server_default="[]"),
            sa.Column("outcomes", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("result", sa.Text(), nullable=True),
            sa.Column("started_at", sa.DateTime(), nullable=True),
            sa.Column("closed_at", sa.DateTime(), nullable=True),
            sa.Column("created_by", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False,
                      server_default=sa.text("(CURRENT_TIMESTAMP)")),
            sa.Column("updated_at", sa.DateTime(), nullable=False,
                      server_default=sa.text("(CURRENT_TIMESTAMP)")),
            sa.ForeignKeyConstraint(["insight_id"], ["ai_insights.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
    if "ix_experiments_status" not in _indexes("experiments"):
        op.create_index("ix_experiments_status", "experiments", ["status"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = set(insp.get_table_names())

    def has_index(table: str, name: str) -> bool:
        try:
            return name in {i["name"] for i in insp.get_indexes(table)}
        except Exception:
            return False

    if has_index("experiments", "ix_experiments_status"):
        with op.batch_alter_table("experiments", schema=None) as batch_op:
            batch_op.drop_index("ix_experiments_status")
    if "experiments" in tables:
        op.drop_table("experiments")

    if "sms_messages" in tables and "next_retry_at" in {c["name"] for c in insp.get_columns("sms_messages")}:
        with op.batch_alter_table("sms_messages", schema=None) as batch_op:
            batch_op.drop_column("next_retry_at")

    # restore the dropped leftover index (harmless either way)
    if "customer_ledger_entries" in tables and not has_index(
            "customer_ledger_entries", "ix_customer_ledger_customer_id_id"):
        op.create_index("ix_customer_ledger_customer_id_id",
                        "customer_ledger_entries", ["customer_id", "id"], unique=False)

    if has_index("customers", "ix_customers_phone"):
        with op.batch_alter_table("customers", schema=None) as batch_op:
            batch_op.drop_index("ix_customers_phone")

    if has_index("product_bank", "ix_product_bank_updated_at"):
        with op.batch_alter_table("product_bank", schema=None) as batch_op:
            batch_op.drop_index("ix_product_bank_updated_at")
    if has_index("product_bank", "ix_product_bank_name"):
        with op.batch_alter_table("product_bank", schema=None) as batch_op:
            batch_op.drop_index("ix_product_bank_name")
    if "product_bank" in tables:
        op.drop_table("product_bank")
