"""Customer credit accounts / دفتر حساب مشتری (§30–35).

Accounting model
----------------
The ledger is **append-only and signed**:

    amount > 0  → customer owes more   (debit: credit sale, adjustment)
    amount < 0  → customer owes less   (credit: payment, refund)

    balance = SUM(amount)   -- positive means the customer is in debt

There is deliberately **no cached balance column on `customers`**. A cached
total is the classic source of "the report says 400,000 but the statement adds
up to 350,000" bugs: any code path that forgets to update it corrupts the
account silently. Here the balance is always derived, and `balance_after` on
each row is a *witness* of the balance at that instant — `verify_integrity()`
re-adds the history and reports any row where the witness disagrees.

Corrections are made by posting a reversing entry, never by editing or
deleting a row (§33 soft-delete/audit rule applied to money).

Concurrency
-----------
Posting an entry re-reads the balance inside the caller's transaction and the
row is inserted in the same transaction as the invoice it belongs to, so a
failed checkout can never leave a dangling debt (mirrors the coupon rule
proven by `test_failed_checkout_does_not_burn_the_coupon`).
"""
from __future__ import annotations

from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import Customer, CustomerLedgerEntry, Invoice

ZERO = Decimal("0")

#: entry types that increase debt
DEBIT_TYPES = {"CREDIT_SALE", "ADJUSTMENT_DEBIT", "OPENING_BALANCE"}
#: entry types that decrease debt
CREDIT_TYPES = {"PAYMENT", "RETURN_REFUND", "ADJUSTMENT_CREDIT"}
ENTRY_TYPES = DEBIT_TYPES | CREDIT_TYPES


class LedgerError(ValueError):
    """Business-rule violation; the router maps `.code` to an HTTP status."""

    def __init__(self, code: str, message: str = ""):
        self.code = code
        super().__init__(message or code)


def _money(value) -> Decimal:
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def balance_of(db: Session, customer_id: int) -> Decimal:
    """Current outstanding debt. Positive = customer owes the store."""
    total = db.execute(
        select(func.coalesce(func.sum(CustomerLedgerEntry.amount), 0)).where(
            CustomerLedgerEntry.customer_id == customer_id
        )
    ).scalar_one()
    return _money(total)


def post_entry(
    db: Session,
    *,
    customer_id: int,
    entry_type: str,
    amount: Decimal | float | str,
    invoice_id: int | None = None,
    method: str | None = None,
    note: str | None = None,
    user_id: int | None = None,
    enforce_credit_limit: bool = True,
) -> CustomerLedgerEntry:
    """Append one ledger entry and return it.

    `amount` is given as a POSITIVE magnitude; the sign is derived from
    `entry_type`. That way a caller can never accidentally post a payment that
    increases the debt by passing the wrong sign.
    """
    if entry_type not in ENTRY_TYPES:
        raise LedgerError("INVALID_ENTRY_TYPE", f"نوع تراکنش نامعتبر: {entry_type}")

    magnitude = _money(amount)
    if magnitude <= ZERO:
        raise LedgerError("INVALID_AMOUNT", "مبلغ باید بزرگ‌تر از صفر باشد")

    customer = db.get(Customer, customer_id)
    if customer is None:
        raise LedgerError("CUSTOMER_NOT_FOUND", "مشتری یافت نشد")

    signed = magnitude if entry_type in DEBIT_TYPES else -magnitude
    current = balance_of(db, customer_id)
    new_balance = current + signed

    # A payment must not overshoot the debt into a negative balance unless it
    # is an explicit adjustment: that is almost always a data-entry mistake.
    if entry_type == "PAYMENT" and new_balance < ZERO:
        raise LedgerError(
            "OVERPAYMENT",
            f"مبلغ پرداخت ({magnitude}) از بدهی فعلی ({current}) بیشتر است",
        )

    if (
        enforce_credit_limit
        and entry_type == "CREDIT_SALE"
        and customer.credit_limit
        and customer.credit_limit > ZERO
        and new_balance > customer.credit_limit
    ):
        raise LedgerError(
            "CREDIT_LIMIT_EXCEEDED",
            f"سقف اعتبار مشتری ({customer.credit_limit}) رعایت نشده است؛ "
            f"بدهی جدید: {new_balance}",
        )

    entry = CustomerLedgerEntry(
        customer_id=customer_id,
        entry_type=entry_type,
        amount=signed,
        balance_after=new_balance,
        invoice_id=invoice_id,
        method=method,
        note=note,
        created_by=user_id,
    )
    db.add(entry)
    db.flush()
    return entry


def charge_invoice_to_account(
    db: Session, *, customer_id: int, invoice: Invoice, user_id: int | None = None
) -> CustomerLedgerEntry:
    """Put an invoice on the customer's account (§34 'افزودن به حساب دفتری')."""
    customer = db.get(Customer, customer_id)
    if customer is None:
        raise LedgerError("CUSTOMER_NOT_FOUND", "مشتری یافت نشد")
    if not customer.credit_enabled:
        raise LedgerError(
            "CREDIT_DISABLED", "حساب دفتری برای این مشتری غیرفعال است"
        )

    existing = db.execute(
        select(CustomerLedgerEntry).where(
            CustomerLedgerEntry.invoice_id == invoice.id,
            CustomerLedgerEntry.entry_type == "CREDIT_SALE",
        )
    ).scalar_one_or_none()
    if existing is not None:
        # idempotent: retrying a checkout must not double-charge the customer
        return existing

    return post_entry(
        db,
        customer_id=customer_id,
        entry_type="CREDIT_SALE",
        amount=invoice.total_amount,
        invoice_id=invoice.id,
        note=f"فاکتور {invoice.invoice_number}",
        user_id=user_id,
    )


def settle(
    db: Session,
    *,
    customer_id: int,
    amount: Decimal | float | str,
    method: str = "CASH",
    note: str | None = None,
    user_id: int | None = None,
) -> dict:
    """Record a payment against the account — partial or full (§32)."""
    entry = post_entry(
        db,
        customer_id=customer_id,
        entry_type="PAYMENT",
        amount=amount,
        method=method,
        note=note,
        user_id=user_id,
    )
    return {
        "entry_id": entry.id,
        "paid": abs(entry.amount),
        "balance": entry.balance_after,
        "settled_in_full": entry.balance_after == ZERO,
    }


def settle_full(
    db: Session, *, customer_id: int, method: str = "CASH",
    note: str | None = None, user_id: int | None = None,
) -> dict:
    """Pay off the entire outstanding balance."""
    outstanding = balance_of(db, customer_id)
    if outstanding <= ZERO:
        raise LedgerError("NO_DEBT", "این مشتری بدهی ندارد")
    return settle(
        db, customer_id=customer_id, amount=outstanding, method=method,
        note=note or "تسویه کامل", user_id=user_id,
    )


def statement(db: Session, customer_id: int, limit: int = 200) -> dict:
    """Full account statement: entries newest-first plus totals."""
    customer = db.get(Customer, customer_id)
    if customer is None:
        raise LedgerError("CUSTOMER_NOT_FOUND", "مشتری یافت نشد")

    rows = list(
        db.execute(
            select(CustomerLedgerEntry)
            .where(CustomerLedgerEntry.customer_id == customer_id)
            .order_by(CustomerLedgerEntry.id.desc())
            .limit(limit)
        ).scalars()
    )

    charged = sum((e.amount for e in rows if e.amount > ZERO), ZERO)
    paid = sum((-e.amount for e in rows if e.amount < ZERO), ZERO)

    return {
        "customer": {
            "id": customer.id,
            "name": customer.name,
            "last_name": customer.last_name,
            "phone": customer.phone,
            "credit_enabled": customer.credit_enabled,
            "credit_limit": customer.credit_limit,
        },
        "balance": balance_of(db, customer_id),
        "total_charged": charged,
        "total_paid": paid,
        "entries": [
            {
                "id": e.id,
                "entry_type": e.entry_type,
                "amount": e.amount,
                "balance_after": e.balance_after,
                "invoice_id": e.invoice_id,
                "method": e.method,
                "note": e.note,
                "created_at": e.created_at,
            }
            for e in rows
        ],
    }


def debtors(db: Session, min_amount: Decimal | float = 0) -> list[dict]:
    """Every customer with outstanding debt — drives the §35 SMS reminder."""
    balance = func.coalesce(func.sum(CustomerLedgerEntry.amount), 0).label("balance")
    rows = db.execute(
        select(Customer, balance)
        .join(CustomerLedgerEntry, CustomerLedgerEntry.customer_id == Customer.id)
        .group_by(Customer.id)
        .having(balance > _money(min_amount))
        .order_by(balance.desc())
    ).all()
    return [
        {
            "customer_id": c.id,
            "name": c.name,
            "last_name": c.last_name,
            "phone": c.phone,
            "balance": _money(b),
        }
        for c, b in rows
    ]


def verify_integrity(db: Session, customer_id: int) -> dict:
    """Re-add the history and check each stored `balance_after` witness.

    Used by the diagnostics centre: it proves the ledger has not been tampered
    with or corrupted by a partial write, rather than assuming it.
    """
    rows = list(
        db.execute(
            select(CustomerLedgerEntry)
            .where(CustomerLedgerEntry.customer_id == customer_id)
            .order_by(CustomerLedgerEntry.id.asc())
        ).scalars()
    )
    running = ZERO
    mismatches = []
    for e in rows:
        running += e.amount
        if running != e.balance_after:
            mismatches.append(
                {"entry_id": e.id, "expected": running, "stored": e.balance_after}
            )
    return {
        "customer_id": customer_id,
        "entries": len(rows),
        "computed_balance": running,
        "ok": not mismatches,
        "mismatches": mismatches,
    }
