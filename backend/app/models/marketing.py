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
    """A marketing campaign (festival) that coupons can belong to.

    v1.0.0 build 481 — a campaign is no longer just a *label* for coupons: it is
    an executable benefit the POS can apply at checkout (steps 21–26 of the
    campaign audit).  Every rule below is enforced server-side inside the
    checkout transaction — the cashier may only *select* among campaigns whose
    conditions already hold, never bend them.
    """

    __tablename__ = "campaigns"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128), index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    discount_type: Mapped[str] = mapped_column(String(16), default="PERCENT")  # PERCENT | FIXED
    discount_value: Mapped[Decimal] = mapped_column(MONEY, default=0)
    min_purchase: Mapped[Decimal] = mapped_column(MONEY, default=0)
    #: upper bound of the purchase amount the campaign applies to (سقف خرید)
    max_purchase: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    max_discount: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)

    valid_from: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    valid_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    #: auto-issue a next-purchase coupon when an invoice total reaches this (§36)
    auto_issue_threshold: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    auto_issue_validity_days: Mapped[int] = mapped_column(Integer, default=30)
    auto_issue_sms: Mapped[bool] = mapped_column(Boolean, default=True)

    #: build-481 benefit targeting & limits
    #: ALL = whole basket · PRODUCTS = only the listed product ids (JSON list)
    target_type: Mapped[str] = mapped_column(String(16), default="ALL")
    target_ids: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON list of product ids
    #: the benefit applies only to a customer's very first invoice (اولین خرید)
    first_purchase_only: Mapped[bool] = mapped_column(Boolean, default=False)
    #: total number of redemptions allowed (NULL = unlimited)
    usage_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    #: redemptions allowed per customer (NULL = unlimited)
    per_customer_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    #: may this campaign's benefit stack with a coupon on the same invoice?
    stackable: Mapped[bool] = mapped_column(Boolean, default=False)
    #: auto-apply at checkout whenever its conditions hold (threshold festivals)
    auto_apply: Mapped[bool] = mapped_column(Boolean, default=False)
    #: lower number = applied first when several campaigns hold (اولویت)
    priority: Mapped[int] = mapped_column(Integer, default=3)
    #: total benefit money granted so far / redemption count (audited per row below)
    used_count: Mapped[int] = mapped_column(Integer, default=0)

    #: provenance: which store-intelligence suggestion created this campaign (audit)
    source_insight_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    status: Mapped[str] = mapped_column(String(16), default="ACTIVE")  # ACTIVE | PAUSED | ENDED
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)

    coupons: Mapped[list["Coupon"]] = relationship(back_populates="campaign")
    redemptions: Mapped[list["CampaignRedemption"]] = relationship(back_populates="campaign")


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


class CampaignRedemption(Base):
    """build-481 — every campaign benefit applied to an invoice (§26 audit trail).

    One row per (campaign, invoice): who applied it, how much benefit money it
    granted, and which customer consumed a per-customer slot.  The invoice keeps
    an immutable *snapshot* of the campaign name/benefit (see ``Invoice``), so
    later edits to the campaign can never rewrite history.
    """

    __tablename__ = "campaign_redemptions"

    id: Mapped[int] = mapped_column(primary_key=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("campaigns.id"), index=True)
    invoice_id: Mapped[int | None] = mapped_column(ForeignKey("invoices.id"), nullable=True)
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("customers.id"), nullable=True)
    amount: Mapped[Decimal] = mapped_column(MONEY, default=0)
    #: CAMPAIGN = cashier/auto applied a festival · AUTO_ISSUE = future-benefit issuance marker
    source: Mapped[str] = mapped_column(String(16), default="CAMPAIGN")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)

    campaign: Mapped["Campaign"] = relationship(back_populates="redemptions")
