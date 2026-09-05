"""External data: sources, resolver results, images, market prices.

Every piece of external data keeps value + source + timestamp + confidence
(blueprint §51, §154). Nothing is written into the master tables until a human
confirms it (§52).
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import Base
from .base import TimestampMixin
from .pricing import MONEY


class ExternalSource(TimestampMixin, Base):
    __tablename__ = "external_sources"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(128))
    source_type: Mapped[str] = mapped_column(String(16))  # PRODUCT | IMAGE | PRICE
    priority: Mapped[int] = mapped_column(Integer, default=100)
    base_url: Mapped[str | None] = mapped_column(String(255), nullable=True)
    api_key: Mapped[str | None] = mapped_column(Text, nullable=True)  # encrypted in prod
    # JSON config for the provider implementation (e.g. field mapping for custom_http)
    connection: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(default=True)


class ProductResolverResult(TimestampMixin, Base):
    __tablename__ = "product_resolver_results"

    id: Mapped[int] = mapped_column(primary_key=True)
    barcode: Mapped[str] = mapped_column(String(64), index=True)
    source_id: Mapped[int | None] = mapped_column(ForeignKey("external_sources.id"), nullable=True)
    # Denormalized provider code so results survive source deletion/reconfiguration.
    source_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    field: Mapped[str] = mapped_column(String(32))
    value: Mapped[str] = mapped_column(Text)
    confidence: Mapped[str] = mapped_column(String(16), default="MEDIUM")
    status: Mapped[str] = mapped_column(String(16), default="PENDING")  # PENDING | APPROVED | REJECTED
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id"), nullable=True)


class ImageAsset(TimestampMixin, Base):
    __tablename__ = "image_assets"

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id"), nullable=True)
    barcode: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    source_id: Mapped[int | None] = mapped_column(ForeignKey("external_sources.id"), nullable=True)
    url: Mapped[str] = mapped_column(Text)
    local_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    format: Mapped[str | None] = mapped_column(String(16), nullable=True)
    confidence: Mapped[str] = mapped_column(String(16), default="MEDIUM")
    is_primary: Mapped[bool] = mapped_column(default=False)
    status: Mapped[str] = mapped_column(String(16), default="PENDING")


class MarketPrice(TimestampMixin, Base):
    __tablename__ = "market_prices"

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id"), nullable=True)
    barcode: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    source_id: Mapped[int | None] = mapped_column(ForeignKey("external_sources.id"), nullable=True)
    price: Mapped[Decimal] = mapped_column(MONEY)
    currency: Mapped[str] = mapped_column(String(8), default="IRR")
    confidence: Mapped[str] = mapped_column(String(16), default="MEDIUM")
    observed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
