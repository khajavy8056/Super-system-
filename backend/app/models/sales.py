"""Sales: Invoice / InvoiceItem / Payment / Return (blueprint §63–66, §60).

InvoiceItem snapshots the exact prices at the moment of sale (§29, §108).
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import Base
from .base import TimestampMixin
from .pricing import MONEY, QTY


class Invoice(TimestampMixin, Base):
    __tablename__ = "invoices"

    id: Mapped[int] = mapped_column(primary_key=True)
    invoice_number: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("customers.id"), nullable=True)

    subtotal: Mapped[Decimal] = mapped_column(MONEY, default=0)
    discount: Mapped[Decimal] = mapped_column(MONEY, default=0)
    tax: Mapped[Decimal] = mapped_column(MONEY, default=0)
    total_amount: Mapped[Decimal] = mapped_column(MONEY, default=0)

    payment_method: Mapped[str] = mapped_column(String(16), default="CASH")
    payment_status: Mapped[str] = mapped_column(String(24), default="PENDING")
    status: Mapped[str] = mapped_column(String(24), default="PENDING")
    print_status: Mapped[str] = mapped_column(String(16), default="NONE")

    paid_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)

    items: Mapped[list["InvoiceItem"]] = relationship(back_populates="invoice")
    payments: Mapped[list["Payment"]] = relationship(back_populates="invoice")
    customer: Mapped["Customer | None"] = relationship(back_populates="invoices")


class InvoiceItem(Base):
    __tablename__ = "invoice_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    invoice_id: Mapped[int] = mapped_column(ForeignKey("invoices.id"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    batch_id: Mapped[int | None] = mapped_column(ForeignKey("product_batches.id"), nullable=True)

    qty: Mapped[Decimal] = mapped_column(QTY, default=1)

    unit_buy_price: Mapped[Decimal] = mapped_column(MONEY, default=0)
    unit_consumer_price: Mapped[Decimal] = mapped_column(MONEY, default=0)
    unit_sell_price: Mapped[Decimal] = mapped_column(MONEY, default=0)

    discount: Mapped[Decimal] = mapped_column(MONEY, default=0)
    tax: Mapped[Decimal] = mapped_column(MONEY, default=0)
    subtotal: Mapped[Decimal] = mapped_column(MONEY, default=0)
    profit: Mapped[Decimal] = mapped_column(MONEY, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    invoice: Mapped["Invoice"] = relationship(back_populates="items")
    product: Mapped["Product"] = relationship()
    batch: Mapped["ProductBatch | None"] = relationship()


class Payment(TimestampMixin, Base):
    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(primary_key=True)
    invoice_id: Mapped[int] = mapped_column(ForeignKey("invoices.id"), index=True)
    method: Mapped[str] = mapped_column(String(16), default="CASH")
    amount: Mapped[Decimal] = mapped_column(MONEY, default=0)

    invoice: Mapped["Invoice"] = relationship(back_populates="payments")


class Customer(TimestampMixin, Base):
    __tablename__ = "customers"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(default=True)

    invoices: Mapped[list["Invoice"]] = relationship(back_populates="customer")


class Return(TimestampMixin, Base):
    __tablename__ = "returns"

    id: Mapped[int] = mapped_column(primary_key=True)
    invoice_id: Mapped[int] = mapped_column(ForeignKey("invoices.id"), index=True)
    invoice_item_id: Mapped[int] = mapped_column(ForeignKey("invoice_items.id"), index=True)
    batch_id: Mapped[int | None] = mapped_column(ForeignKey("product_batches.id"), nullable=True)
    qty: Mapped[Decimal] = mapped_column(QTY, default=1)
    reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="COMPLETED")
    refund_amount: Mapped[Decimal] = mapped_column(MONEY, default=0)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
