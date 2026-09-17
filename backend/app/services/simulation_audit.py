"""Read-only economic checks for generated backups; never repairs failed evidence.

SQL aggregation keeps raw invoices/movements out of Python memory. Reports retain
only counts and at most 10 example IDs per check. Run on an offline snapshot, not
inside the live POS transaction. Currency tolerance is 0.02, quantity is 0.0011.
"""
from __future__ import annotations
import sqlite3


CHECKS = {
    "unbalanced_journals": """
        SELECT e.id FROM acc_journal_entries e
        LEFT JOIN acc_journal_lines l ON l.entry_id=e.id
        WHERE e.status IN ('POSTED','REVERSED') GROUP BY e.id
        HAVING COUNT(l.id)<2 OR ABS(COALESCE(SUM(l.debit-l.credit),0))>0.02
    """,
    "invalid_journal_lines": """
        SELECT id FROM acc_journal_lines
        WHERE debit<0 OR credit<0 OR (debit>0 AND credit>0)
    """,
    "batch_movement_mismatch": """
        SELECT b.id FROM product_batches b LEFT JOIN
        (SELECT batch_id, SUM(quantity) qty FROM stock_movements
         WHERE batch_id IS NOT NULL GROUP BY batch_id) m ON m.batch_id=b.id
        WHERE ABS(b.current_qty-COALESCE(m.qty,0))>0.0011
    """,
    "negative_stock": "SELECT id FROM product_batches WHERE current_qty < -0.0011",
    "invoice_gross_mismatch": """
        SELECT i.id FROM invoices i LEFT JOIN
        (SELECT invoice_id, SUM(qty*unit_sell_price) gross, COUNT(*) n
         FROM invoice_items GROUP BY invoice_id) l ON l.invoice_id=i.id
        WHERE i.status IN ('PAID','VOID','PARTIALLY_REFUNDED','REFUNDED') AND
        (COALESCE(l.n,0)=0 OR ABS(i.subtotal-COALESCE(l.gross,0))>0.02)
    """,
    "invoice_total_mismatch": """
        SELECT id FROM invoices WHERE status IN ('PAID','VOID','PARTIALLY_REFUNDED','REFUNDED')
        AND ABS(total_amount-(subtotal-discount+tax))>0.02
    """,
    "invoice_payment_mismatch": """
        SELECT i.id FROM invoices i LEFT JOIN
        (SELECT invoice_id, SUM(amount) amount FROM payments GROUP BY invoice_id) p ON p.invoice_id=i.id
        WHERE i.status='PAID' AND ABS(i.total_amount-COALESCE(p.amount,0))>0.02
    """,
    "customer_running_balance_mismatch": """
        SELECT id FROM (
            SELECT id, balance_after, SUM(amount) OVER
            (PARTITION BY customer_id ORDER BY id ROWS UNBOUNDED PRECEDING) expected
            FROM customer_ledger_entries
        ) WHERE ABS(balance_after-expected)>0.02
    """,
    "sale_journal_date_mismatch": """
        SELECT e.id FROM acc_journal_entries e JOIN invoices i
        ON e.source_type='Invoice' AND e.source_id=i.id AND e.kind='SALE'
        WHERE e.entry_date != date(i.created_at, '+3 hours', '+30 minutes')
    """,
    "missing_cash_settlement_journal": """
        SELECT l.id FROM customer_ledger_entries l WHERE l.entry_type='PAYMENT'
        AND l.method IN ('CASH','CARD','TRANSFER','BANK') AND NOT EXISTS
        (SELECT 1 FROM acc_journal_entries e WHERE e.source_type='CustomerLedgerEntry'
         AND e.source_id=l.id AND e.kind='SETTLEMENT')
    """,
    "receivables_subledger_mismatch": """
        SELECT customer_id FROM (
            SELECT customer_id, amount AS difference FROM customer_ledger_entries
            UNION ALL
            SELECT l.party_id, -(l.debit-l.credit) FROM acc_journal_lines l
            JOIN acc_accounts a ON a.id=l.account_id
            JOIN acc_journal_entries e ON e.id=l.entry_id
            WHERE a.code='1201' AND l.party_type='CUSTOMER'
              AND l.party_id IS NOT NULL AND e.status IN ('POSTED','REVERSED')
        ) GROUP BY customer_id HAVING ABS(SUM(difference))>0.02
    """,
    "missing_sale_journal": """
        SELECT i.id FROM invoices i WHERE i.status IN ('PAID','VOID','PARTIALLY_REFUNDED','REFUNDED') AND NOT EXISTS
        (SELECT 1 FROM acc_journal_entries e WHERE e.source_type='Invoice'
         AND e.source_id=i.id AND e.kind='SALE')
    """,
}


def audit(connection: sqlite3.Connection) -> dict:
    checks = {}
    for name, query in CHECKS.items():
        try:
            count = connection.execute(f"SELECT COUNT(*) FROM ({query})").fetchone()[0]
            samples = [r[0] for r in connection.execute(f"SELECT * FROM ({query}) LIMIT 10")] if count else []
            checks[name] = {"violations": count, "sample_ids": samples}
        except sqlite3.DatabaseError as exc:
            checks[name] = {"error": str(exc)}
    return {"ok": all(not c.get('error') and c.get('violations') == 0 for c in checks.values()),
            "checks": checks,
            "scope": "accounting_and_inventory_consistency_not_model_accuracy"}
