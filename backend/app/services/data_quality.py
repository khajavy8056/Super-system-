# -*- coding: utf-8 -*-
"""v3.7 — Data Quality Engine.

Runs BEFORE the intelligence engine (see ``services.insights.run``). Garbage in
means garbage recommendations: a missing buy price makes every profit estimate
a lie, a duplicated invoice number corrupts every measurement, negative stock
breaks allocation. This module checks the facts the analyzers stand on and
reports them with a severity:

  CRITICAL  the data is wrong in a way that corrupts decisions/measurements
  HIGH      likely wrong; decisions touching these rows are unreliable
  MEDIUM    suspicious; worth a look but not decision-breaking
  LOW       hygiene (missing category/unit, stale prices, …)

``blocks_intelligence`` is True only when a check that corrupts *measurement
itself* fires (duplicate invoice numbers, negative stock). Everything else
degrades confidence but does not silence the engine — a shop with dirty data
still needs advice, just honestly-flagged advice.

Read-only: every check is a SELECT. No writes, no network.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..models import (
    Coupon,
    Customer,
    CustomerLedgerEntry,
    ExternalSource,
    Invoice,
    InvoiceItem,
    PriceVersion,
    Product,
    ProductBatch,
    ProductResolverResult,
    StockMovement,
)

SAMPLE_LIMIT = 20  # ids kept per check; counts are exact

# ---------------------------------------------------------------------------
# check metadata: id -> (severity, blocks_intelligence, fa_message)
# ---------------------------------------------------------------------------
CHECKS: dict[str, tuple[str, bool, str]] = {
    "missing_consumer_price": ("MEDIUM", False, "بچ فعال دارای موجودی بدون قیمت مصرف‌کننده (سقف قانونی نامشخص)"),
    "missing_buy_price": ("HIGH", False, "بچ دارای موجودی بدون قیمت خرید (محاسبه سود ناممکن)"),
    "negative_stock": ("CRITICAL", True, "موجودی منفی بچ (انبار/تخصیص خراب است)"),
    "impossible_expiry": ("LOW", False, "تاریخ انقضای غیرممکن (بیش از ۱۰ سال آینده)"),
    "production_after_expiry": ("HIGH", False, "تاریخ تولید بعد از انقضا"),
    "duplicate_invoice_number": ("CRITICAL", True, "شماره فاکتور تکراری (اندازه‌گیری خراب می‌شود)"),
    "negative_margin": ("MEDIUM", False, "فروش زیر قیمت خرید (حاشیه منفی)"),
    "invalid_customer_phone": ("LOW", False, "شماره تماس نامعتبر مشتری ثبت‌شده"),
    "orphan_stock_movement": ("HIGH", False, "گردش انبار یتیم (کالا/بچ ناموجود)"),
    "orphan_invoice_item": ("HIGH", False, "قلم فاکتور یتیم (کالا/بچ ناموجود)"),
    "unbalanced_ledger": ("CRITICAL", False, "تراز دفتر مشتری با تاریخچه‌اش نمی‌خواند"),
    "broken_price_history": ("MEDIUM", False, "تاریخچه قیمت خراب (چند نسخه فعال همزمان)"),
    "suspicious_discount": ("MEDIUM", False, "تخفیف مشکوک (بیش از ۵۰٪ مبلغ فاکتور)"),
    "discount_exceeds_total": ("HIGH", False, "تخفیف بزرگ‌تر از جمع فاکتور"),
    "stock_inflation": ("HIGH", False, "موجودی فعلی بیش از مقدار دریافتی (تورم انبار از مرجوعی/ابطال؟)"),
    "missing_category": ("LOW", False, "کالا بدون دسته‌بندی"),
    "missing_unit": ("LOW", False, "کالا بدون واحد اندازه‌گیری"),
    "stale_price": ("LOW", False, "قیمت قدیمی (بیش از ۱۸۰ روز بدون بازبینی، موجودی فعال)"),
    "broken_resolver_link": ("MEDIUM", False, "نتیجه تأییدشده resolver به کالای ناموجود اشاره می‌کند"),
    "overused_coupon": ("HIGH", False, "کوپن بیش از سقف مصرف استفاده شده"),
}

_PHONE_RE = re.compile(r"^(\+?98|0)?9\d{9}$")


def _check(check_id: str, count: int, sample: list) -> dict:
    sev, blocks, msg = CHECKS[check_id]
    return {"id": check_id, "severity": sev, "blocks": blocks, "count": int(count),
            "sample_ids": [int(x) for x in sample[:SAMPLE_LIMIT]], "message": msg}


def run_all(db: Session) -> dict:
    """Evaluate every check. Returns the Data Quality Report (JSON-serializable)."""
    out: list[dict] = []
    out.append(_c_missing_consumer_price(db))
    out.append(_c_missing_buy_price(db))
    out.append(_c_negative_stock(db))
    out.append(_c_impossible_expiry(db))
    out.append(_c_production_after_expiry(db))
    out.append(_c_duplicate_invoice_number(db))
    out.append(_c_negative_margin(db))
    out.append(_c_invalid_customer_phone(db))
    out.append(_c_orphan_stock_movement(db))
    out.append(_c_orphan_invoice_item(db))
    out.append(_c_unbalanced_ledger(db))
    out.append(_c_broken_price_history(db))
    out.append(_c_suspicious_discount(db))
    out.append(_c_discount_exceeds_total(db))
    out.append(_c_stock_inflation(db))
    out.append(_c_missing_category(db))
    out.append(_c_missing_unit(db))
    out.append(_c_stale_price(db))
    out.append(_c_broken_resolver_link(db))
    out.append(_c_overused_coupon(db))
    fired = [c for c in out if c["count"] > 0]
    summary = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0}
    for c in fired:
        summary[c["severity"]] += c["count"]
    blocks = any(c["blocks"] and c["count"] for c in out)
    verdict = "BLOCKED" if blocks else ("DEGRADED" if fired else "OK")
    return {"generated_at": datetime.utcnow().isoformat(timespec="seconds"),
            "verdict": verdict, "blocks_intelligence": blocks,
            "summary": summary, "checks": fired}


def blocks_intelligence(report: dict) -> bool:
    return bool(report.get("blocks_intelligence"))


# ---------------------------------------------------------------------------
# individual checks (each returns the check dict, count may be 0)
# ---------------------------------------------------------------------------
def _c_missing_consumer_price(db: Session) -> dict:
    q = (select(ProductBatch.id)
         .where(ProductBatch.status == "ACTIVE", ProductBatch.current_qty > 0,
                or_(ProductBatch.consumer_price.is_(None), ProductBatch.consumer_price <= 0)))
    ids = [r for r in db.execute(q.limit(SAMPLE_LIMIT + 1)).scalars()]
    n = db.execute(select(func.count()).select_from(ProductBatch).where(
        ProductBatch.status == "ACTIVE", ProductBatch.current_qty > 0,
        or_(ProductBatch.consumer_price.is_(None), ProductBatch.consumer_price <= 0))).scalar_one()
    return _check("missing_consumer_price", n, ids)


def _c_missing_buy_price(db: Session) -> dict:
    where = [ProductBatch.current_qty > 0,
             or_(ProductBatch.buy_price.is_(None), ProductBatch.buy_price <= 0)]
    ids = list(db.execute(select(ProductBatch.id).where(*where).limit(SAMPLE_LIMIT + 1)).scalars())
    n = db.execute(select(func.count()).select_from(ProductBatch).where(*where)).scalar_one()
    return _check("missing_buy_price", n, ids)


def _c_negative_stock(db: Session) -> dict:
    where = [ProductBatch.current_qty < 0]
    ids = list(db.execute(select(ProductBatch.id).where(*where).limit(SAMPLE_LIMIT + 1)).scalars())
    n = db.execute(select(func.count()).select_from(ProductBatch).where(*where)).scalar_one()
    return _check("negative_stock", n, ids)


def _c_impossible_expiry(db: Session) -> dict:
    far = date.today() + timedelta(days=365 * 10)
    where = [ProductBatch.expiry_date.isnot(None), ProductBatch.expiry_date > far]
    ids = list(db.execute(select(ProductBatch.id).where(*where).limit(SAMPLE_LIMIT + 1)).scalars())
    n = db.execute(select(func.count()).select_from(ProductBatch).where(*where)).scalar_one()
    return _check("impossible_expiry", n, ids)


def _c_production_after_expiry(db: Session) -> dict:
    where = [ProductBatch.production_date.isnot(None), ProductBatch.expiry_date.isnot(None),
             ProductBatch.production_date > ProductBatch.expiry_date]
    ids = list(db.execute(select(ProductBatch.id).where(*where).limit(SAMPLE_LIMIT + 1)).scalars())
    n = db.execute(select(func.count()).select_from(ProductBatch).where(*where)).scalar_one()
    return _check("production_after_expiry", n, ids)


def _c_duplicate_invoice_number(db: Session) -> dict:
    dupes = (select(Invoice.invoice_number).group_by(Invoice.invoice_number)
             .having(func.count(Invoice.id) > 1)).subquery()
    ids = list(db.execute(select(Invoice.id).where(Invoice.invoice_number.in_(select(dupes)))
                          .limit(SAMPLE_LIMIT + 1)).scalars())
    n = db.execute(select(func.count()).select_from(Invoice)
                   .where(Invoice.invoice_number.in_(select(dupes)))).scalar_one()
    return _check("duplicate_invoice_number", n, ids)


def _c_negative_margin(db: Session) -> dict:
    where = [ProductBatch.status == "ACTIVE", ProductBatch.current_qty > 0,
             ProductBatch.buy_price > 0, ProductBatch.sell_price > 0,
             ProductBatch.sell_price < ProductBatch.buy_price]
    ids = list(db.execute(select(ProductBatch.id).where(*where).limit(SAMPLE_LIMIT + 1)).scalars())
    n = db.execute(select(func.count()).select_from(ProductBatch).where(*where)).scalar_one()
    return _check("negative_margin", n, ids)


def _c_invalid_customer_phone(db: Session) -> dict:
    rows = db.execute(select(Customer.id, Customer.phone)
                      .where(Customer.phone.isnot(None), Customer.phone != "")).all()
    bad = [i for i, p in rows if not _PHONE_RE.match(re.sub(r"[\s\-]", "", p or ""))]
    return _check("invalid_customer_phone", len(bad), bad)


def _c_orphan_stock_movement(db: Session) -> dict:
    prod_ids = select(Product.id)
    batch_ids = select(ProductBatch.id)
    where = [or_(StockMovement.product_id.notin_(prod_ids),
                 StockMovement.batch_id.isnot(None),
                 StockMovement.batch_id.is_(None))]
    # batch orphan: batch_id set but no such batch
    ids_a = set(db.execute(select(StockMovement.id)
                           .where(StockMovement.product_id.notin_(prod_ids))
                           .limit(SAMPLE_LIMIT + 1)).scalars())
    ids_b = set(db.execute(select(StockMovement.id)
                           .where(StockMovement.batch_id.isnot(None),
                                  StockMovement.batch_id.notin_(batch_ids))
                           .limit(SAMPLE_LIMIT + 1)).scalars())
    ids = sorted(ids_a | ids_b)
    n_a = db.execute(select(func.count()).select_from(StockMovement)
                     .where(StockMovement.product_id.notin_(prod_ids))).scalar_one()
    n_b = db.execute(select(func.count()).select_from(StockMovement)
                     .where(StockMovement.batch_id.isnot(None),
                            StockMovement.batch_id.notin_(batch_ids))).scalar_one()
    # rows counted in both are still one broken row each — recount exactly when small
    n = n_a + n_b
    if n <= SAMPLE_LIMIT + 1:
        n = len(ids)
    return _check("orphan_stock_movement", n, ids)


def _c_orphan_invoice_item(db: Session) -> dict:
    prod_ids = select(Product.id)
    batch_ids = select(ProductBatch.id)
    ids_a = set(db.execute(select(InvoiceItem.id)
                           .where(InvoiceItem.product_id.notin_(prod_ids))
                           .limit(SAMPLE_LIMIT + 1)).scalars())
    ids_b = set(db.execute(select(InvoiceItem.id)
                           .where(InvoiceItem.batch_id.isnot(None),
                                  InvoiceItem.batch_id.notin_(batch_ids))
                           .limit(SAMPLE_LIMIT + 1)).scalars())
    ids = sorted(ids_a | ids_b)
    n_a = db.execute(select(func.count()).select_from(InvoiceItem)
                     .where(InvoiceItem.product_id.notin_(prod_ids))).scalar_one()
    n_b = db.execute(select(func.count()).select_from(InvoiceItem)
                     .where(InvoiceItem.batch_id.isnot(None),
                            InvoiceItem.batch_id.notin_(batch_ids))).scalar_one()
    n = len(ids) if (n_a + n_b) <= SAMPLE_LIMIT + 1 else n_a + n_b
    return _check("orphan_invoice_item", n, ids)


def _c_unbalanced_ledger(db: Session) -> dict:
    """balance_after of the latest entry per customer must equal SUM(amount)."""
    # latest entry per customer
    sub = (select(CustomerLedgerEntry.customer_id,
                  func.max(CustomerLedgerEntry.id).label("mid"))
           .group_by(CustomerLedgerEntry.customer_id)).subquery()
    rows = db.execute(
        select(CustomerLedgerEntry.customer_id, CustomerLedgerEntry.balance_after,
               CustomerLedgerEntry.id)
        .join(sub, CustomerLedgerEntry.id == sub.c.mid)).all()
    bad: list[int] = []
    for cid, bal_after, _mid in rows:
        total = db.execute(
            select(func.coalesce(func.sum(CustomerLedgerEntry.amount), 0))
            .where(CustomerLedgerEntry.customer_id == cid)).scalar_one()
        if abs(Decimal(str(total)) - Decimal(str(bal_after or 0))) > Decimal("0.01"):
            bad.append(int(cid))
    return _check("unbalanced_ledger", len(bad), bad)


def _c_broken_price_history(db: Session) -> dict:
    dupes = (select(PriceVersion.product_id, PriceVersion.price_type)
             .where(PriceVersion.is_active.is_(True))
             .group_by(PriceVersion.product_id, PriceVersion.price_type)
             .having(func.count(PriceVersion.id) > 1)).subquery()
    # count distinct (product, type) pairs broken
    n = db.execute(select(func.count()).select_from(dupes)).scalar_one()
    pairs = db.execute(select(dupes).limit(SAMPLE_LIMIT + 1)).all()
    pids = sorted({int(r[0]) for r in pairs})
    return _check("broken_price_history", n, pids)


def _c_suspicious_discount(db: Session) -> dict:
    where = [Invoice.status.in_(["PAID", "PARTIALLY_REFUNDED", "REFUNDED"]),
             Invoice.subtotal > 0, Invoice.discount > Invoice.subtotal * Decimal("0.5")]
    ids = list(db.execute(select(Invoice.id).where(*where).limit(SAMPLE_LIMIT + 1)).scalars())
    n = db.execute(select(func.count()).select_from(Invoice).where(*where)).scalar_one()
    return _check("suspicious_discount", n, ids)


def _c_discount_exceeds_total(db: Session) -> dict:
    where = [Invoice.discount > Invoice.subtotal]
    ids = list(db.execute(select(Invoice.id).where(*where).limit(SAMPLE_LIMIT + 1)).scalars())
    n = db.execute(select(func.count()).select_from(Invoice).where(*where)).scalar_one()
    return _check("discount_exceeds_total", n, ids)


def _c_stock_inflation(db: Session) -> dict:
    """current_qty above quantity_received means returns/voids inflated stock."""
    where = [ProductBatch.quantity_received > 0,
             ProductBatch.current_qty > ProductBatch.quantity_received + Decimal("0.001")]
    ids = list(db.execute(select(ProductBatch.id).where(*where).limit(SAMPLE_LIMIT + 1)).scalars())
    n = db.execute(select(func.count()).select_from(ProductBatch).where(*where)).scalar_one()
    return _check("stock_inflation", n, ids)


def _c_missing_category(db: Session) -> dict:
    where = [Product.deleted_at.is_(None), Product.category_id.is_(None)]
    ids = list(db.execute(select(Product.id).where(*where).limit(SAMPLE_LIMIT + 1)).scalars())
    n = db.execute(select(func.count()).select_from(Product).where(*where)).scalar_one()
    return _check("missing_category", n, ids)


def _c_missing_unit(db: Session) -> dict:
    where = [Product.deleted_at.is_(None), Product.unit_id.is_(None)]
    ids = list(db.execute(select(Product.id).where(*where).limit(SAMPLE_LIMIT + 1)).scalars())
    n = db.execute(select(func.count()).select_from(Product).where(*where)).scalar_one()
    return _check("missing_unit", n, ids)


def _c_stale_price(db: Session) -> dict:
    """ACTIVE stocked batch whose sell price was set >180 days ago (via versions or received_at)."""
    cutoff = datetime.utcnow() - timedelta(days=180)
    # batches with a recent active price version are fresh
    fresh_pids = (select(PriceVersion.product_id)
                  .where(PriceVersion.is_active.is_(True), PriceVersion.effective_from >= cutoff))
    where = [ProductBatch.status == "ACTIVE", ProductBatch.current_qty > 0,
             ProductBatch.received_at < cutoff,
             ProductBatch.product_id.notin_(fresh_pids)]
    ids = list(db.execute(select(ProductBatch.id).where(*where).limit(SAMPLE_LIMIT + 1)).scalars())
    n = db.execute(select(func.count()).select_from(ProductBatch).where(*where)).scalar_one()
    return _check("stale_price", n, ids)


def _c_broken_resolver_link(db: Session) -> dict:
    prod_ids = select(Product.id)
    where = [ProductResolverResult.status == "APPROVED",
             ProductResolverResult.product_id.isnot(None),
             ProductResolverResult.product_id.notin_(prod_ids)]
    ids = list(db.execute(select(ProductResolverResult.id).where(*where).limit(SAMPLE_LIMIT + 1)).scalars())
    n = db.execute(select(func.count()).select_from(ProductResolverResult).where(*where)).scalar_one()
    return _check("broken_resolver_link", n, ids)


def _c_overused_coupon(db: Session) -> dict:
    where = [Coupon.used_count > Coupon.usage_limit]
    ids = list(db.execute(select(Coupon.id).where(*where).limit(SAMPLE_LIMIT + 1)).scalars())
    n = db.execute(select(func.count()).select_from(Coupon).where(*where)).scalar_one()
    return _check("overused_coupon", n, ids)


def external_sources_health(db: Session) -> list[dict]:
    """Configured-source inventory (no network): code, type, active, has endpoint."""
    rows = db.execute(select(ExternalSource)).scalars().all()
    return [{"code": s.code, "type": s.source_type, "active": bool(s.is_active),
             "has_endpoint": bool(s.base_url)} for s in rows]
