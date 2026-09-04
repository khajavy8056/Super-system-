"""Marketing: campaigns, coupons and coupon redemptions (§31–38).

Design rules:
- A coupon is *evaluated* (never mutated) during cart pricing; it is only
  consumed inside the checkout transaction, so a failed checkout can never
  burn a coupon.
- ``used_count`` is incremented with a conditional UPDATE guarded by
  ``used_count < usage_limit`` → two concurrent terminals can never exceed the
  limit (same technique as batch stock deduction).
- Every redemption is recorded in ``coupon_redemptions`` for audit (§38).
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import Base
from .base import TimestampMixin
from .pricing import MONEY


class Campaign(TimestampMixin, Base):
    """A marketing campaign (festival) that coupons can belong to."""

    __tablename__ = "campaigns"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128), index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    discount_type: Mapped[str] = mapped_column(String(16), default="PERCENT")  # PERCENT | FIXED
    discount_value: Mapped[Decimal] = mapped_column(MONEY, default=0)
    min_purchase: Mapped[Decimal] = mapped_column(MONEY, default=0)
    max_discount: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)

    valid_from: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    valid_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    #: auto-issue a next-purchase coupon when an invoice total reaches this (§36)
    auto_issue_threshold: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    auto_issue_validity_days: Mapped[int] = mapped_column(Integer, default=30)
    auto_issue_sms: Mapped[bool] = mapped_column(Boolean, default=True)

    status: Mapped[str] = mapped_column(String(16), default="ACTIVE")  # ACTIVE | PAUSED | ENDED
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)

    coupons: Mapped[list["Coupon"]] = relationship(back_populates="campaign")


class Coupon(TimestampMixin, Base):
    __tablename__ = "coupons"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(48), unique=True, index=True)
    campaign_id: Mapped[int | None] = mapped_column(ForeignKey("campaigns.id"), nullable=True)

    #: customer-specific coupon (§35). NULL = usable by anyone.
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("customers.id"), nullable=True)
    customer_phone: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)

    discount_type: Mapped[str] = mapped_column(String(16), default="PERCENT")  # PERCENT | FIXED
    discount_value: Mapped[Decimal] = mapped_column(MONEY, default=0)
    min_purchase: Mapped[Decimal] = mapped_column(MONEY, default=0)
    max_discount: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)

    valid_from: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    valid_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    usage_limit: Mapped[int] = mapped_column(Integer, default=1)
    used_count: Mapped[int] = mapped_column(Integer, default=0)

    status: Mapped[str] = mapped_column(String(16), default="ACTIVE")  # ACTIVE|USED|EXPIRED|BLOCKED
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)

    campaign: Mapped["Campaign | None"] = relationship(back_populates="coupons")
    redemptions: Mapped[list["CouponRedemption"]] = relationship(back_populates="coupon")


class CouponRedemption(Base):
    __tablename__ = "coupon_redemptions"

    id: Mapped[int] = mapped_column(primary_key=True)
    coupon_id: Mapped[int] = mapped_column(ForeignKey("coupons.id"), index=True)
    invoice_id: Mapped[int | None] = mapped_column(ForeignKey("invoices.id"), nullable=True)
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("customers.id"), nullable=True)
    amount: Mapped[Decimal] = mapped_column(MONEY, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)

    coupon: Mapped["Coupon"] = relationship(back_populates="redemptions")
