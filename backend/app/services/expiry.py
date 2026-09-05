"""Expiry engine (blueprint §44–46).

Classifies batches by days-to-expiry using configurable thresholds, blocks
expired batches from sale by default, and raises notifications.
"""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import ProductBatch, SystemSetting
from .notifications import notify

DEFAULT_THRESHOLDS = {"today": 0, "three": 3, "seven": 7, "thirty": 30}


def get_thresholds(db: Session) -> dict[str, int]:
    out = dict(DEFAULT_THRESHOLDS)
    for key in out:
        row = db.execute(
            select(SystemSetting).where(SystemSetting.key == f"expiry.days.{key}")
        ).scalar_one_or_none()
        if row:
            try:
                out[key] = int(row.value)
            except ValueError:
                pass
    return out


def days_until(batch: ProductBatch, today: date | None = None) -> int | None:
    if batch.expiry_date is None:
        return None
    return (batch.expiry_date - (today or date.today())).days


def classify(batch: ProductBatch, today: date | None = None, thresholds: dict[str, int] | None = None) -> str:
    today = today or date.today()
    d = days_until(batch, today)
    if d is None:
        return "NORMAL"
    t = thresholds or DEFAULT_THRESHOLDS
    if d < 0:
        return "EXPIRED"
    if d == 0 or d <= t["today"]:
        return "EXPIRING_TODAY"
    if d <= t["three"]:
        return "EXPIRING_3_DAYS"
    if d <= t["seven"]:
        return "EXPIRING_7_DAYS"
    if d <= t["thirty"]:
        return "EXPIRING_30_DAYS"
    return "NORMAL"


def block_expired_policy(db: Session) -> bool:
    from ..models import SystemSetting
    row = db.execute(select(SystemSetting).where(SystemSetting.key == "expiry.block_sale")).scalar_one_or_none()
    return row.value.lower() not in ("false", "0", "no", "off") if row else True


def expiry_scan(db: Session) -> dict:
    """Periodic job: mark expired batches and notify about near-expiry ones."""
    thresholds = get_thresholds(db)
    today = date.today()
    batches = db.execute(select(ProductBatch).where(ProductBatch.status == "ACTIVE")).scalars().all()
    result = {"expired": 0, "expiring_today": 0, "expiring_3": 0, "expiring_7": 0, "expiring_30": 0}

    for b in batches:
        status = classify(b, today, thresholds)
        if status == "EXPIRED":
            if b.status != "EXPIRED":
                b.status = "EXPIRED"
                notify(db, type="EXPIRY", title="Batch expired",
                       body=f"{b.product.name if b.product else 'Product'}: {b.batch_number} expired {b.expiry_date}",
                       severity="CRITICAL", reference_type="ProductBatch", reference_id=b.id)
            result["expired"] += 1
        elif status != "NORMAL":
            bucket = {"EXPIRING_TODAY": "expiring_today", "EXPIRING_3_DAYS": "expiring_3",
                      "EXPIRING_7_DAYS": "expiring_7", "EXPIRING_30_DAYS": "expiring_30"}[status]
            result[bucket] += 1
    db.flush()
    return result
