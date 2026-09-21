"""Double-entry accounting (v1.4): chart of accounts, journal, cheques, expenses.

Design rules
------------
* Every business event that moves money produces ONE balanced journal entry
  (Σ debit == Σ credit). Entries are append-only; a mistake is corrected with
  a reversing entry (``reversal_of_id``) — never by editing history.
* Account codes follow the common Iranian retail chart (کدینگ): 1xxx دارایی،
  2xxx بدهی، 3xxx سرمایه، 4xxx درآمد، 5xxx بهای تمام‌شده، 6xxx هزینه.
* Normal balance is derived from the account class: ASSET/EXPENSE/COGS are
  debit-normal; LIABILITY/EQUITY/REVENUE are credit-normal.
* Automatic postings (POS sale, receiving, returns, waste, customer
  settlement) are tagged with ``source_type``/``source_id`` so they can be
  traced back to the operational document, and never double-posted.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import Base
from .base import TimestampMixin
from .pricing import MONEY

ACCOUNT_CLASSES = ("ASSET", "LIABILITY", "EQUITY", "REVENUE", "COGS", "EXPENSE")
DEBIT_NORMAL = {"ASSET", "COGS", "EXPENSE"}


class Account(TimestampMixin, Base):
    __tablename__ = "acc_accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(16), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(128))
    account_class: Mapped[str] = mapped_column(String(16), index=True)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("acc_accounts.id"), nullable=True)
    #: system accounts are the posting targets of automatic entries and
    #: cannot be deleted/re-coded from the UI
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    #: only leaf (postable) accounts may receive journal lines
    is_postable: Mapped[bool] = mapped_column(Boolean, default=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    @property
    def debit_normal(self) -> bool:
        return self.account_class in DEBIT_NORMAL


class FiscalPeriod(TimestampMixin, Base):
    """Jalali fiscal year (e.g. 1405: 1405/01/01 – 1405/12/29)."""

    __tablename__ = "acc_fiscal_periods"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(32), unique=True)
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    is_closed: Mapped[bool] = mapped_column(Boolean, default=False)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    closed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)


class JournalEntry(TimestampMixin, Base):
    __tablename__ = "acc_journal_entries"
    __table_args__ = (UniqueConstraint("source_type", "source_id", "kind", name="uq_acc_source"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    number: Mapped[int] = mapped_column(Integer, index=True)  # sequential سند شماره
    entry_date: Mapped[date] = mapped_column(Date, index=True)
    description: Mapped[str] = mapped_column(String(512), default="")
    #: SALE | SALE_RETURN | PURCHASE | WASTE | SETTLEMENT | EXPENSE | CHEQUE |
    #: MANUAL | OPENING | CLOSING | REVERSAL | ADJUSTMENT
    kind: Mapped[str] = mapped_column(String(24), index=True, default="MANUAL")
    source_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    source_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    #: DRAFT | POSTED | REVERSED
    status: Mapped[str] = mapped_column(String(12), default="POSTED", index=True)
    reversal_of_id: Mapped[int | None] = mapped_column(ForeignKey("acc_journal_entries.id"), nullable=True)
    fiscal_period_id: Mapped[int | None] = mapped_column(ForeignKey("acc_fiscal_periods.id"), nullable=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)

    lines: Mapped[list["JournalLine"]] = relationship(back_populates="entry", cascade="all, delete-orphan",
                                                      order_by="JournalLine.id")


class JournalLine(Base):
    __tablename__ = "acc_journal_lines"

    id: Mapped[int] = mapped_column(primary_key=True)
    entry_id: Mapped[int] = mapped_column(ForeignKey("acc_journal_entries.id"), index=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("acc_accounts.id"), index=True)
    debit: Mapped[Decimal] = mapped_column(MONEY, default=0)
    credit: Mapped[Decimal] = mapped_column(MONEY, default=0)
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    #: optional sub-ledger reference (تفصیلی): customer / supplier / user
    party_type: Mapped[str | None] = mapped_column(String(24), nullable=True)
    party_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    entry: Mapped["JournalEntry"] = relationship(back_populates="lines")
    account: Mapped["Account"] = relationship()


class Supplier(TimestampMixin, Base):
    __tablename__ = "acc_suppliers"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128), index=True)
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    address: Mapped[str | None] = mapped_column(String(512), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class ExpenseCategory(TimestampMixin, Base):
    __tablename__ = "acc_expense_categories"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128), unique=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("acc_accounts.id"))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Expense(TimestampMixin, Base):
    __tablename__ = "acc_expenses"

    id: Mapped[int] = mapped_column(primary_key=True)
    category_id: Mapped[int] = mapped_column(ForeignKey("acc_expense_categories.id"))
    amount: Mapped[Decimal] = mapped_column(MONEY)
    expense_date: Mapped[date] = mapped_column(Date, index=True)
    #: CASH | BANK | CARD
    paid_from: Mapped[str] = mapped_column(String(12), default="CASH")
    description: Mapped[str | None] = mapped_column(String(512), nullable=True)
    supplier_id: Mapped[int | None] = mapped_column(ForeignKey("acc_suppliers.id"), nullable=True)
    journal_entry_id: Mapped[int | None] = mapped_column(ForeignKey("acc_journal_entries.id"), nullable=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)


class Cheque(TimestampMixin, Base):
    """Received (from customers) and issued (to suppliers) cheques."""

    __tablename__ = "acc_cheques"

    id: Mapped[int] = mapped_column(primary_key=True)
    #: RECEIVED | ISSUED
    direction: Mapped[str] = mapped_column(String(10), index=True)
    number: Mapped[str] = mapped_column(String(32), index=True)
    bank_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    amount: Mapped[Decimal] = mapped_column(MONEY)
    due_date: Mapped[date] = mapped_column(Date, index=True)
    issue_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    #: PENDING | CLEARED | BOUNCED | CANCELLED
    status: Mapped[str] = mapped_column(String(12), default="PENDING", index=True)
    party_type: Mapped[str | None] = mapped_column(String(24), nullable=True)  # CUSTOMER | SUPPLIER
    party_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    party_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    description: Mapped[str | None] = mapped_column(String(512), nullable=True)
    journal_entry_id: Mapped[int | None] = mapped_column(ForeignKey("acc_journal_entries.id"), nullable=True)
    cleared_entry_id: Mapped[int | None] = mapped_column(ForeignKey("acc_journal_entries.id"), nullable=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)


class CashSession(TimestampMixin, Base):
    """Cashier shift: opening float → sales → closing count (Z-report)."""

    __tablename__ = "acc_cash_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    opened_at: Mapped[datetime] = mapped_column(DateTime)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    opening_float: Mapped[Decimal] = mapped_column(MONEY, default=0)
    expected_cash: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    counted_cash: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    difference: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    note: Mapped[str | None] = mapped_column(String(512), nullable=True)
    #: OPEN | CLOSED
    status: Mapped[str] = mapped_column(String(8), default="OPEN", index=True)
    journal_entry_id: Mapped[int | None] = mapped_column(ForeignKey("acc_journal_entries.id"), nullable=True)
