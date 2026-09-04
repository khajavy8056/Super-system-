"""Pricing: price versions + market price aggregation (blueprint §26–28, §55–58).

A price change never mutates history — it closes the previous PriceVersion and
creates a new one.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import MarketPrice, PriceVersion, Product, User
from .audit import write_audit


class PricingError(Exception):
    pass


def _close_active_versions(db: Session, product_id: int, price_type: str, effective_from: datetime) -> None:
    active = db.execute(
        select(PriceVersion).where(
            PriceVersion.product_id == product_id,
            PriceVersion.price_type == price_type,
            PriceVersion.is_active.is_(True),
        )
    ).scalars().all()
    for v in active:
        v.effective_to = effective_from
        v.is_active = False


def set_price(
    db: Session,
    *,
    product: Product,
    price_type: str,
    price: Decimal,
    user: User | None = None,
    source: str | None = None,
    note: str | None = None,
) -> PriceVersion:
    """Create a new price version (closing any previous active one)."""
    if price < 0:
        raise PricingError("Price cannot be negative")
    now = datetime.utcnow()
    _close_active_versions(db, product.id, price_type, now)
    version = PriceVersion(
        product_id=product.id,
        price_type=price_type,
        price=price,
        effective_from=now,
        source=source or "manual",
        note=note,
        is_active=True,
        created_by=user.id if user else None,
    )
    db.add(version)
    db.flush()
    write_audit(
        db, action="PRICE_CHANGED", user_id=user.id if user else None,
        entity_type="PriceVersion", entity_id=version.id,
        after={"product_id": product.id, "type": price_type, "price": str(price)},
    )
    return version


def active_price(db: Session, product_id: int, price_type: str = "SELL") -> Decimal | None:
    row = db.execute(
        select(PriceVersion).where(
            PriceVersion.product_id == product_id,
            PriceVersion.price_type == price_type,
            PriceVersion.is_active.is_(True),
        ).order_by(PriceVersion.effective_from.desc()).limit(1)
    ).scalar_one_or_none()
    return Decimal(row.price) if row else None


def market_aggregate(db: Session, product_id: int | None = None, barcode: str | None = None) -> dict | None:
    q = select(MarketPrice)
    if product_id is not None:
        q = q.where(MarketPrice.product_id == product_id)
    elif barcode is not None:
        q = q.where(MarketPrice.barcode == barcode)
    else:
        return None
    rows = [Decimal(r.price) for r in db.execute(q).scalars().all() if r.price is not None]
    if not rows:
        return None
    rows.sort()
    n = len(rows)
    median = rows[n // 2] if n % 2 else (rows[n // 2 - 1] + rows[n // 2]) / 2
    return {
        "min": min(rows),
        "max": max(rows),
        "median": median,
        "average": sum(rows) / n,
        "count": n,
    }


def suggest_sell_price(db: Session, *, buy_cost: Decimal, target_margin: Decimal,
                       product_id: int | None = None, barcode: str | None = None) -> dict:
    """Buy cost + target margin, informed (not dictated) by market data (§56)."""
    base = buy_cost * (1 + target_margin / 100)
    market = market_aggregate(db, product_id=product_id, barcode=barcode)
    return {
        "suggested": base.quantize(Decimal("1")),
        "based_on_cost": base,
        "market": market,
        "note": "Suggested only — must be confirmed by a user before it becomes the store price.",
    }


def price_freshness(updated_at: datetime | None, now: datetime | None = None, *,
                    fresh_days: int = 7, aging_days: int = 30) -> str:
    """FRESH / AGING / STALE (§57). Tolerates naive and tz-aware datetimes (BUG-022)."""
    from datetime import timezone

    if updated_at is None:
        return "STALE"
    if updated_at.tzinfo is None:
        updated_at = updated_at.replace(tzinfo=timezone.utc)
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    age = (now - updated_at).days
    if age <= fresh_days:
        return "FRESH"
    if age <= aging_days:
        return "AGING"
    return "STALE"
