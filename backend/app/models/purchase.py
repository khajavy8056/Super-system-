"""Purchase orders + daily sales summary (F-07, F-16)."""
from __future__ import annotations
from datetime import datetime, date
from decimal import Decimal
from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, Date, Numeric
from sqlalchemy.orm import Mapped, mapped_column, relationship
from ..database import Base
from .base import TimestampMixin

class PurchaseOrder(TimestampMixin, Base):
    __tablename__ = "purchase_orders"
    id: Mapped[int] = mapped_column(primary_key=True)
    # FK corrected: acc_suppliers (not suppliers) — see accounting.Supplier
    supplier_id: Mapped[int | None] = mapped_column(ForeignKey("acc_suppliers.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="DRAFT")  # DRAFT|ORDERED|RECEIVED|CANCELLED
    total_cost: Mapped[Decimal] = mapped_column(Numeric(18,2), default=Decimal("0"))
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    lines: Mapped[list["PurchaseOrderLine"]] = relationship(back_populates="order", cascade="all, delete-orphan")

class PurchaseOrderLine(Base):
    __tablename__ = "purchase_order_lines"
    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("purchase_orders.id", ondelete="CASCADE"))
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    qty: Mapped[Decimal] = mapped_column(Numeric(12,3), default=Decimal("1"))
    unit_cost: Mapped[Decimal] = mapped_column(Numeric(18,2), default=Decimal("0"))
    received_qty: Mapped[Decimal] = mapped_column(Numeric(12,3), default=Decimal("0"))
    order: Mapped[PurchaseOrder] = relationship(back_populates="lines")

class DailySalesSummary(Base):
    __tablename__ = "daily_sales_summary"
    id: Mapped[int] = mapped_column(primary_key=True)
    day: Mapped[date] = mapped_column(Date, unique=True, index=True)
    invoice_count: Mapped[int] = mapped_column(Integer, default=0)
    gross_sales: Mapped[Decimal] = mapped_column(Numeric(18,2), default=Decimal("0"))
    discounts: Mapped[Decimal] = mapped_column(Numeric(18,2), default=Decimal("0"))
    net_sales: Mapped[Decimal] = mapped_column(Numeric(18,2), default=Decimal("0"))
    profit: Mapped[Decimal] = mapped_column(Numeric(18,2), default=Decimal("0"))
    refunds: Mapped[Decimal] = mapped_column(Numeric(18,2), default=Decimal("0"))
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
