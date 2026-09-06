"""Pricing: PriceVersion keeps the full, immutable history of price changes
(blueprint §26–28). The batch itself carries the purchase (buy) price.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import Base
from .base import TimestampMixin

MONEY = Numeric(14, 2)
QTY = Numeric(14, 3)  # decimal quantities (Kg / gram / liter support)


class PriceVersion(TimestampMixin, Base):
    __tablename__ = "price_versions"

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    price_type: Mapped[str] = mapped_column(String(16), default="SELL")
    price: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    effective_from: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    effective_to: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    source: Mapped[str | None] = mapped_column(String(64), nullable=True)
    note: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)

    product: Mapped["Product"] = relationship()
