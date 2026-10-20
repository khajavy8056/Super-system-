# -*- coding: utf-8 -*-
"""I-20 — missing indexes for hot reporting queries."""
from typing import Sequence, Union
import sqlalchemy as sa
from alembic import op

revision: str = "v1_0_523"
down_revision: Union[str, None] = "v1_0_522"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_INDEXES = [
    ("ix_invoices_created_at", "invoices", ["created_at"]),
    ("ix_invoices_status", "invoices", ["status"]),
    ("ix_invoices_customer_id", "invoices", ["customer_id"]),
    ("ix_invoice_items_invoice_id", "invoice_items", ["invoice_id"]),
    ("ix_invoice_items_product_id", "invoice_items", ["product_id"]),
    ("ix_returns_invoice_id", "returns", ["invoice_id"]),
    ("ix_returns_invoice_item_id", "returns", ["invoice_item_id"]),
    ("ix_product_batches_product_id", "product_batches", ["product_id"]),
    ("ix_product_batches_expiry", "product_batches", ["expiry_date"]),
    ("ix_product_batches_status", "product_batches", ["status"]),
    ("ix_stock_movements_product_id", "stock_movements", ["product_id"]),
    ("ix_payments_invoice_id", "payments", ["invoice_id"]),
    ("ix_customer_ledger_customer_id", "customer_ledger_entries", ["customer_id"]),
    ("ix_customer_ledger_invoice_id", "customer_ledger_entries", ["invoice_id"]),
]


def _has_index(bind, table: str, index: str) -> bool:
    insp = sa.inspect(bind)
    try:
        return index in {x["name"] for x in insp.get_indexes(table)}
    except Exception:
        return False


def upgrade() -> None:
    bind = op.get_bind()
    for name, table, cols in _INDEXES:
        if not _has_index(bind, table, name):
            try:
                op.create_index(name, table, cols)
            except Exception:
                pass


def downgrade() -> None:
    bind = op.get_bind()
    for name, table, cols in _INDEXES:
        if _has_index(bind, table, name):
            try:
                op.drop_index(name, table)
            except Exception:
                pass
