# -*- coding: utf-8 -*-
"""v4.0: Business Brain tables (decision memory, policy memory, follow-ups,
conversation memory, business memory facts, model-manager ledger).

Idempotent (project convention): every table is created only when missing, so a
database created from the newer models and then migrated through this revision
does not hit "table already exists". ``downgrade`` drops only what this
revision created — no existing column or table is ever touched, so the
migration cannot lose data on the way up or down.
"""
from __future__ import annotations

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "d4f6a8b1c2e3"
down_revision: Union[str, None] = "c5d9e2f7a4b6"
branch_labels = None
depends_on = None

MONEY = sa.Numeric(18, 2)

TABLES: dict[str, list[sa.Column]] = {
    "brain_messages": [
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("session_key", sa.String(64), nullable=False, server_default="default"),
        sa.Column("role", sa.String(12), nullable=False),
        sa.Column("content", sa.Text(), nullable=False, server_default=""),
        sa.Column("tool_trace", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("meta", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("decision_id", sa.Integer(), nullable=True),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("local_decision", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("pending_sync", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    ],
    "brain_decisions": [
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("type", sa.String(32), nullable=False, server_default="business_decision"),
        sa.Column("title", sa.String(255), nullable=False, server_default=""),
        sa.Column("problem", sa.Text(), nullable=False, server_default=""),
        sa.Column("objective", sa.Text(), nullable=False, server_default=""),
        sa.Column("situation", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("evidence", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("options", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("recommended_option", sa.String(64), nullable=True),
        sa.Column("selected_option", sa.String(64), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False, server_default=""),
        sa.Column("risks", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("confidence", sa.String(16), nullable=False, server_default="medium"),
        sa.Column("policy_verdict", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("requires_approval", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("actions", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("approval", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("execution", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("measurement", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("result", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("measured_gain", MONEY, nullable=True),
        sa.Column("outcome", sa.String(24), nullable=True),
        sa.Column("measured_at", sa.DateTime(), nullable=True),
        sa.Column("decision_kind", sa.String(32), nullable=False, server_default=""),
        sa.Column("status", sa.String(20), nullable=False, server_default="NEEDS_DECISION"),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("history", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("insight_id", sa.Integer(), nullable=True),
        sa.Column("dedupe_key", sa.String(160), nullable=True),
        sa.Column("origin", sa.String(16), nullable=False, server_default="CHAT"),
        sa.Column("tool_trace", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("local_decision", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("pending_sync", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("conflict_with", sa.Integer(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("store_key", sa.String(64), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    ],
    "brain_followups": [
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("decision_id", sa.Integer(), nullable=True),
        sa.Column("kind", sa.String(16), nullable=False, server_default="REMIND"),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("note", sa.Text(), nullable=False, server_default=""),
        sa.Column("due_at", sa.DateTime(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="OPEN"),
        sa.Column("notified_at", sa.DateTime(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.Column("result", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("pending_sync", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    ],
    "brain_policies": [
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("key", sa.String(64), nullable=False),
        sa.Column("value", sa.Text(), nullable=False, server_default="null"),
        sa.Column("value_type", sa.String(16), nullable=False, server_default="text"),
        sa.Column("scope", sa.String(32), nullable=False, server_default="store"),
        sa.Column("source", sa.String(12), nullable=False, server_default="OWNER"),
        sa.Column("label", sa.String(160), nullable=False, server_default=""),
        sa.Column("note", sa.Text(), nullable=False, server_default=""),
        sa.Column("updated_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    ],
    "brain_model_installs": [
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("model_id", sa.String(64), nullable=False),
        sa.Column("path", sa.Text(), nullable=False, server_default=""),
        sa.Column("size_bytes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sha256", sa.String(64), nullable=False, server_default=""),
        sa.Column("status", sa.String(16), nullable=False, server_default="PENDING"),
        sa.Column("device_profile", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("benchmark", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("activated_at", sa.DateTime(), nullable=True),
        sa.Column("previous_install_id", sa.Integer(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    ],
    "brain_memory_facts": [
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("kind", sa.String(24), nullable=False),
        sa.Column("key", sa.String(128), nullable=False),
        sa.Column("value", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("confidence", sa.Numeric(4, 3), nullable=False, server_default="0.5"),
        sa.Column("source", sa.String(16), nullable=False, server_default="ANALYZER"),
        sa.Column("reference_type", sa.String(32), nullable=True),
        sa.Column("reference_id", sa.Integer(), nullable=True),
        sa.Column("observed_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    ],
}

INDEXES: dict[str, list[tuple[str, list[str]]]] = {
    "brain_messages": [("ix_brain_messages_session", ["session_key"]),
                       ("ix_brain_messages_role", ["role"]),
                       ("ix_brain_messages_decision", ["decision_id"])],
    "brain_decisions": [("ix_brain_decisions_status", ["status"]),
                        ("ix_brain_decisions_origin", ["origin"]),
                        ("ix_brain_decisions_dedupe", ["dedupe_key"]),
                        ("ix_brain_decisions_local", ["local_decision"]),
                        ("ix_brain_decisions_store", ["store_key"])],
    "brain_followups": [("ix_brain_followups_due", ["due_at"]),
                        ("ix_brain_followups_status", ["status"]),
                        ("ix_brain_followups_decision", ["decision_id"])],
    "brain_policies": [("ix_brain_policies_key", ["key"], True)],
    "brain_model_installs": [("ix_brain_model_installs_model", ["model_id"]),
                             ("ix_brain_model_installs_status", ["status"])],
    "brain_memory_facts": [("ix_brain_memory_facts_kind", ["kind"]),
                           ("ix_brain_memory_facts_key", ["key"])],
}


def _existing() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    existing = _existing()
    for table, columns in TABLES.items():
        if table in existing:
            continue
        op.create_table(table, *columns)
        for spec in INDEXES.get(table, []):
            name, cols = spec[0], spec[1]
            unique = len(spec) > 2 and bool(spec[2])
            op.create_index(name, table, cols, unique=unique)


def downgrade() -> None:
    existing = _existing()
    for table in ("brain_memory_facts", "brain_model_installs", "brain_policies",
                  "brain_followups", "brain_decisions", "brain_messages"):
        if table in existing:
            op.drop_table(table)
