"""Inventory: ProductBatch, StockMovement, Stocktake (blueprint §23–46)."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import Base
from .base import TimestampMixin
from .pricing import MONEY, QTY


class ProductBatch(TimestampMixin, Base):
    """A receiving entry of a product. Carries its own purchase cost and
    selling prices (blueprint §23–25). Purchase cost is immutable after the
    batch is consumed (protected by service-layer rules, §28/§100).
    """

    __tablename__ = "product_batches"

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    batch_number: Mapped[str] = mapped_column(String(64), index=True)
    quantity_received: Mapped[Decimal] = mapped_column(QTY, default=0)
    current_qty: Mapped[Decimal] = mapped_column(QTY, default=0)

    buy_price: Mapped[Decimal] = mapped_column(MONEY, default=0)
    consumer_price: Mapped[Decimal] = mapped_column(MONEY, default=0)
    sell_price: Mapped[Decimal] = mapped_column(MONEY, default=0)

    production_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    expiry_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    received_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="ACTIVE")

    # Future multi-branch/warehouse support (§145–147), optional in v1.
    warehouse_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    location_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    product: Mapped["Product"] = relationship(back_populates="batches")


class StockMovement(TimestampMixin, Base):
    """Immutable append-only ledger of every stock change (blueprint §37–38)."""

    __tablename__ = "stock_movements"

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    batch_id: Mapped[int | None] = mapped_column(ForeignKey("product_batches.id"), nullable=True)
    movement_type: Mapped[str] = mapped_column(String(24), index=True)
    quantity: Mapped[Decimal] = mapped_column(QTY, nullable=False)  # signed
    reference_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    reference_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    unit_cost: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)

    product: Mapped["Product"] = relationship()
    batch: Mapped["ProductBatch | None"] = relationship()


class Stocktake(TimestampMixin, Base):
    __tablename__ = "stocktakes"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(16), default="DRAFT")
    area: Mapped[str | None] = mapped_column(String(128), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    completed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    warehouse_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    #: last item the operator was on — lets a phone resume mid-session (§14)
    cursor_item_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    items: Mapped[list["StocktakeItem"]] = relationship(back_populates="stocktake")


class StocktakeItem(Base):
    __tablename__ = "stocktake_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    stocktake_id: Mapped[int] = mapped_column(ForeignKey("stocktakes.id"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    batch_id: Mapped[int | None] = mapped_column(ForeignKey("product_batches.id"), nullable=True)
    system_qty: Mapped[Decimal] = mapped_column(QTY, default=0)
    physical_qty: Mapped[Decimal | None] = mapped_column(QTY, nullable=True)
    difference: Mapped[Decimal] = mapped_column(QTY, default=0)
    reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="PENDING")
    counted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    counted_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)

    stocktake: Mapped["Stocktake"] = relationship(back_populates="items")
    product: Mapped["Product"] = relationship()
    batch: Mapped["ProductBatch | None"] = relationship()
