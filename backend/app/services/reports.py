"""Dashboard + reporting (§8, §49) — SQL-aggregate implementations.

Phase-5 rewrite: every metric below is computed with grouped queries instead of
loading whole tables into memory (dashboard used to materialise every product
and batch row; that dies at ~10k products).
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from ..models import (
    Invoice,
    InvoiceItem,
    Product,
    ProductBatch,
    PriceVersion,
    StockMovement,
    Stocktake,
    User,
)
from . import expiry as expiry_svc

ZERO = Decimal("0")
PAID = "PAID"


def _day_range(d: date) -> tuple[datetime, datetime]:
    start = datetime(d.year, d.month, d.day)
    return start, start + timedelta(days=1)


def _paid_filter(start: datetime, end: datetime):
    return and_(Invoice.status == PAID, Invoice.created_at >= start, Invoice.created_at < end)


def _sales_agg(db: Session, start: datetime, end: datetime) -> tuple[int, Decimal]:
    row = db.execute(
        select(func.count(Invoice.id), func.coalesce(func.sum(Invoice.total_amount), 0))
        .where(_paid_filter(start, end))
    ).one()
    return int(row[0]), Decimal(row[1])


def _profit_agg(db: Session, start: datetime, end: datetime) -> Decimal:
    val = db.execute(
        select(func.coalesce(func.sum(InvoiceItem.profit), 0))
        .join(Invoice, InvoiceItem.invoice_id == Invoice.id)
        .where(_paid_filter(start, end))
    ).scalar_one()
    return Decimal(val)


def dashboard(db: Session) -> dict:
    today = date.today()
    t0, t1 = _day_range(today)
    y0, y1 = _day_range(today - timedelta(days=1))
    m0 = datetime(today.year, today.month, 1)

    cnt_t, sum_t = _sales_agg(db, t0, t1)
    cnt_y, sum_y = _sales_agg(db, y0, y1)
    _, sum_m = _sales_agg(db, m0, datetime.utcnow())
    profit_t = _profit_agg(db, t0, t1)
    profit_m = _profit_agg(db, m0, datetime.utcnow())

    # inventory value + expiry buckets (only batches that can expire)
    inv_val = Decimal(db.execute(
        select(func.coalesce(func.sum(ProductBatch.current_qty * ProductBatch.buy_price), 0))
        .where(ProductBatch.current_qty > 0, ProductBatch.status == "ACTIVE")
    ).scalar_one())
    thresholds = expiry_svc.get_thresholds(db)
    expiry_buckets: dict[str, list] = {k: [] for k in
                                       ("EXPIRED", "EXPIRING_TODAY", "EXPIRING_3_DAYS",
                                        "EXPIRING_7_DAYS", "EXPIRING_30_DAYS")}
    expiring_rows = db.execute(
        select(ProductBatch, Product.name)
        .join(Product, ProductBatch.product_id == Product.id)
        .where(ProductBatch.current_qty > 0, ProductBatch.status == "ACTIVE",
               ProductBatch.expiry_date.is_not(None))
    ).all()
    for b, pname in expiring_rows:
        status = expiry_svc.classify(b, today, thresholds)
        if status != "NORMAL":
            expiry_buckets[status].append({
                "batch_id": b.id, "batch_number": b.batch_number,
                "product_id": b.product_id, "product_name": pname,
                "qty": b.current_qty, "expiry": str(b.expiry_date),
                "days_left": expiry_svc.days_until(b, today),
                "value": float(Decimal(b.current_qty) * Decimal(b.buy_price)),
            })
    for v in expiry_buckets.values():
        v.sort(key=lambda x: x["days_left"] if x["days_left"] is not None else 9999)

    # low / no stock from one grouped query
    product_count = int(db.execute(
        select(func.count(Product.id)).where(Product.deleted_at.is_(None))
    ).scalar_one())
    stock_rows = db.execute(
        select(Product.id, Product.name, Product.barcode, Product.min_stock_alert,
               func.coalesce(func.sum(ProductBatch.current_qty), 0))
        .outerjoin(ProductBatch, ProductBatch.product_id == Product.id)
        .where(Product.deleted_at.is_(None))
        .group_by(Product.id, Product.name, Product.barcode, Product.min_stock_alert)
    ).all()
    low_stock, no_stock = [], []
    for pid, name, barcode, min_alert, total in stock_rows:
        total = int(total)
        if total <= 0:
            no_stock.append({"product_id": pid, "name": name, "barcode": barcode})
        elif min_alert and total <= min_alert:
            low_stock.append({"product_id": pid, "name": name, "barcode": barcode, "qty": total})

    # price conflicts (§8): active sellable batches with >1 distinct sell price
    conflict_rows = db.execute(
        select(Product.id, Product.name)
        .join(ProductBatch, ProductBatch.product_id == Product.id)
        .where(ProductBatch.current_qty > 0, ProductBatch.status == "ACTIVE")
        .group_by(Product.id, Product.name)
        .having(func.count(func.distinct(ProductBatch.sell_price)) > 1)
    ).all()
    price_conflicts = []
    for pid, name in conflict_rows:
        prices = sorted({float(p) for (p,) in db.execute(
            select(ProductBatch.sell_price).where(
                ProductBatch.product_id == pid, ProductBatch.current_qty > 0,
                ProductBatch.status == "ACTIVE", ProductBatch.sell_price.is_not(None))
        ).all()})
        if len(prices) > 1:
            price_conflicts.append({"product_id": pid, "name": name, "prices": prices})

    return {
        "sales": {
            "today": float(sum_t), "yesterday": float(sum_y), "month": float(sum_m),
            "invoice_count_today": cnt_t,
            "avg_invoice_today": float(sum_t / cnt_t) if cnt_t else 0.0,
        },
        "profit": {"today": float(profit_t), "month": float(profit_m)},
        "inventory": {
            "value": float(inv_val), "product_count": product_count,
            "low_stock": low_stock[:50], "no_stock": no_stock[:50],
            "low_stock_count": len(low_stock), "no_stock_count": len(no_stock),
        },
        "expiry": expiry_buckets,
        "pricing": {"price_conflicts": price_conflicts[:50],
                    "price_conflict_count": len(price_conflicts)},
        # §23 — the four blocks the operator actually watches all day were
        # missing from the dashboard payload: what customers owe, what is still
        # waiting to be settled, whether SMS is flowing, and whether the system
        # itself is healthy.
        "receivables": _receivables(db),
        "sms": _sms_status(db),
        "system": _system_status(db),
    }


# --- §23 dashboard blocks ----------------------------------------------------

def _receivables(db: Session) -> dict:
    """Customer debt + unsettled invoices.

    Two different numbers, deliberately kept apart:

    * ``customer_debt`` — the running balance of every customer ledger. This is
      the money the shop is owed on account (§30–35).
    * ``pending_amount`` — invoices that left the counter neither PAID nor VOID.
      A credit sale that was never posted to an account, or an interrupted
      payment, lands here; it must be visible or it simply disappears.
    """
    from . import ledger as ledger_svc

    debt_rows = ledger_svc.debtors(db, 0)
    total_debt = sum((Decimal(str(d["balance"])) for d in debt_rows), ZERO)

    pending_rows = db.execute(
        select(Invoice).where(
            Invoice.status.not_in(["PAID", "VOID", "REFUNDED", "PARTIALLY_REFUNDED"])
        ).order_by(Invoice.created_at.desc()).limit(500)
    ).scalars().all()
    pending_amount = sum((Decimal(i.total_amount) for i in pending_rows), ZERO)

    return {
        "customer_debt": float(total_debt),
        "debtor_count": len(debt_rows),
        "top_debtors": [
            {"customer_id": d["customer_id"], "name": d["name"],
             "phone": d.get("phone"), "balance": float(Decimal(str(d["balance"])))}
            for d in debt_rows[:5]
        ],
        "pending_amount": float(pending_amount),
        "pending_count": len(pending_rows),
        "pending_invoices": [
            {"invoice_id": i.id, "invoice_number": i.invoice_number,
             "total": float(Decimal(i.total_amount)), "status": i.status,
             "payment_method": i.payment_method,
             "created_at": i.created_at.isoformat() if i.created_at else None}
            for i in pending_rows[:10]
        ],
    }


def _sms_status(db: Session) -> dict:
    from ..models import SmsMessage
    from . import sms as sms_svc

    rows = db.execute(
        select(SmsMessage.status, func.count(SmsMessage.id))
        .group_by(SmsMessage.status)
    ).all()
    by_status = {s: int(n) for s, n in rows}
    last = db.execute(
        select(SmsMessage).order_by(SmsMessage.id.desc()).limit(1)
    ).scalar_one_or_none()
    provider = sms_svc.get_setting(db, "sms.provider", "").strip()
    return {
        "provider": provider or None,
        "configured": bool(provider),
        "by_status": by_status,
        "pending": by_status.get("PENDING", 0) + by_status.get("RETRYING", 0),
        "sent": by_status.get("SENT", 0),
        "failed": by_status.get("FAILED", 0),
        "total": sum(by_status.values()),
        "last_at": last.created_at.isoformat() if last and last.created_at else None,
        "last_status": last.status if last else None,
        "last_error": (last.error_message or None) if last else None,
    }


def _system_status(db: Session) -> dict:
    """Health snapshot for the dashboard's status strip.

    Everything here is cheap and local — the dashboard is polled, so it must
    never be the thing that makes a network call or blocks on hardware.
    """
    import shutil
    from pathlib import Path

    from .. import __version__
    from ..config import settings
    from ..models import DiagnosticRun, HardwareDevice, SyncJob

    hw_rows = db.execute(select(HardwareDevice)).scalars().all()
    hardware = {h.device_type: h.status for h in hw_rows}

    last_diag = db.execute(
        select(DiagnosticRun).order_by(DiagnosticRun.id.desc()).limit(1)
    ).scalar_one_or_none()

    queued = int(db.execute(
        select(func.count(SyncJob.id)).where(SyncJob.status.in_(["PENDING", "RUNNING"]))
    ).scalar_one())
    failed_jobs = int(db.execute(
        select(func.count(SyncJob.id)).where(SyncJob.status == "FAILED")
    ).scalar_one())

    free_gb = None
    try:
        free_gb = round(shutil.disk_usage(str(Path(settings.MEDIA_DIR))).free / 1e9, 1)
    except OSError:
        pass

    engine_name = db.get_bind().dialect.name
    issues = []
    if hardware.get("PRINTER") == "DISCONNECTED":
        issues.append("پرینتر متصل نیست")
    if failed_jobs:
        issues.append(f"{failed_jobs} کار همگام‌سازی ناموفق")
    if last_diag and last_diag.failed:
        issues.append(f"{last_diag.failed} خطا در آخرین تست اتصالات")
    if free_gb is not None and free_gb < 1:
        issues.append("فضای دیسک کمتر از ۱ گیگابایت")

    return {
        "version": __version__,
        "environment": settings.ENVIRONMENT,
        "database": engine_name,
        "hardware": hardware,
        "sync_queued": queued,
        "sync_failed": failed_jobs,
        "disk_free_gb": free_gb,
        "last_diagnostics": {
            "run_id": last_diag.id,
            "started_at": last_diag.started_at.isoformat() if last_diag.started_at else None,
            "total": last_diag.total, "passed": last_diag.passed,
            "failed": last_diag.failed, "skipped": last_diag.skipped,
        } if last_diag else None,
        "status": "WARNING" if issues else "OK",
        "issues": issues,
    }


# --- Sales ------------------------------------------------------------------

def sales_report(db: Session, start: date, end: date, group: str = "daily") -> dict:
    s0, _ = _day_range(start)
    _, e1 = _day_range(end)
    cnt, total = _sales_agg(db, s0, e1)

    invoices = list(db.execute(
        select(Invoice).where(_paid_filter(s0, e1)).order_by(Invoice.created_at.desc()).limit(500)
    ).scalars())

    out: dict = {
        "total_sales": float(total), "invoice_count": cnt, "group": group,
        "invoices": [
            {"invoice_number": i.invoice_number, "total": float(i.total_amount),
             "created_at": i.created_at.isoformat(), "status": i.status,
             "payment_method": i.payment_method}
            for i in invoices
        ],
    }

    if group == "daily":
        rows = db.execute(
            select(func.date(Invoice.created_at), func.count(Invoice.id),
                   func.coalesce(func.sum(Invoice.total_amount), 0))
            .where(_paid_filter(s0, e1))
            .group_by(func.date(Invoice.created_at))
            .order_by(func.date(Invoice.created_at))
        ).all()
        out["groups"] = [{"date": str(r[0]), "invoice_count": int(r[1]),
                          "total": float(Decimal(r[2]))} for r in rows]
    elif group in ("monthly", "weekly"):
        # Jalali month / week buckets (§137, §138). SQLite cannot group by the
        # Persian calendar, so bucket in Python on the (bounded) day rows.
        from .timeservice import to_jalali
        rows = db.execute(
            select(func.date(Invoice.created_at), func.count(Invoice.id),
                   func.coalesce(func.sum(Invoice.total_amount), 0))
            .where(_paid_filter(s0, e1))
            .group_by(func.date(Invoice.created_at))
            .order_by(func.date(Invoice.created_at))
        ).all()
        buckets: dict[str, dict] = {}
        for r in rows:
            d = date.fromisoformat(str(r[0]))
            jy, jm, jd = to_jalali(d)
            if group == "monthly":
                key = f"{jy:04d}/{jm:02d}"
            else:
                # Jalali week: 7-day blocks counted from Farvardin 1 of that year
                doy = (jm - 1) * 31 - max(0, jm - 7) + jd if jm <= 6 else 186 + (jm - 7) * 30 + jd
                key = f"{jy:04d}-هفته {((doy - 1) // 7) + 1:02d}"
            b = buckets.setdefault(key, {"period": key, "invoice_count": 0, "total": 0.0,
                                         "first_day": str(r[0]), "last_day": str(r[0])})
            b["invoice_count"] += int(r[1])
            b["total"] += float(Decimal(r[2]))
            b["last_day"] = str(r[0])
        out["groups"] = list(buckets.values())
    elif group == "product":
        rows = db.execute(
            select(Product.name, func.coalesce(func.sum(InvoiceItem.qty), 0),
                   func.coalesce(func.sum(InvoiceItem.subtotal), 0),
                   func.coalesce(func.sum(InvoiceItem.profit), 0))
            .select_from(InvoiceItem)
            .join(Invoice, InvoiceItem.invoice_id == Invoice.id)
            .join(Product, InvoiceItem.product_id == Product.id)
            .where(_paid_filter(s0, e1))
            .group_by(Product.id, Product.name)
            .order_by(func.sum(InvoiceItem.subtotal).desc())
        ).all()
        out["groups"] = [{"product": r[0], "qty": int(r[1]),
                          "revenue": float(Decimal(r[2])), "profit": float(Decimal(r[3]))}
                         for r in rows]
    return out


def cashier_report(db: Session, start: date | None = None, end: date | None = None) -> list[dict]:
    """Sales & profit per cashier (§49) — invoices are attributed to created_by."""
    filt = [Invoice.status == PAID]
    if start and end:
        s0, _ = _day_range(start)
        _, e1 = _day_range(end)
        filt += [Invoice.created_at >= s0, Invoice.created_at < e1]
    rows = db.execute(
        select(Invoice.created_by, func.count(Invoice.id),
               func.coalesce(func.sum(Invoice.total_amount), 0),
               func.coalesce(func.sum(Invoice.discount), 0))
        .select_from(Invoice).where(and_(*filt))
        .group_by(Invoice.created_by)
    ).all()
    users = {u.id: u.username for u in db.execute(select(User)).scalars()}

    profits: dict[int | None, Decimal] = {}
    profit_rows = db.execute(
        select(Invoice.created_by, func.coalesce(func.sum(InvoiceItem.profit), 0))
        .select_from(InvoiceItem)
        .join(Invoice, InvoiceItem.invoice_id == Invoice.id)
        .where(and_(*filt))
        .group_by(Invoice.created_by)
    ).all()
    for uid, prof in profit_rows:
        profits[uid] = Decimal(prof)

    return [
        {"user_id": uid, "username": users.get(uid, "—" if uid is None else f"#{uid}"),
         "invoice_count": int(cnt), "total_sales": float(Decimal(total)),
         "total_discount": float(Decimal(disc)), "profit": float(profits.get(uid, ZERO))}
        for uid, cnt, total, disc in rows
    ]


# --- Inventory / batches ------------------------------------------------------

def inventory_report(db: Session) -> list[dict]:
    """Per-product stock, value at cost and batch count (§49)."""
    rows = db.execute(
        select(Product.id, Product.name, Product.barcode, Product.min_stock_alert,
               func.coalesce(func.sum(ProductBatch.current_qty), 0),
               func.coalesce(func.sum(ProductBatch.current_qty * ProductBatch.buy_price), 0),
               func.count(ProductBatch.id))
        .outerjoin(ProductBatch, and_(ProductBatch.product_id == Product.id,
                                      ProductBatch.current_qty > 0))
        .where(Product.deleted_at.is_(None))
        .group_by(Product.id, Product.name, Product.barcode, Product.min_stock_alert)
        .order_by(Product.name)
    ).all()
    return [
        {"product_id": pid, "name": name, "barcode": barcode,
         "total_qty": int(qty), "value_at_cost": float(Decimal(value)),
         "batches": int(bc), "min_stock_alert": int(min_alert)}
        for pid, name, barcode, min_alert, qty, value, bc in rows
    ]


def purchase_cost_history(db: Session, product_id: int | None = None, limit: int = 100) -> list[dict]:
    """Buy price over time from receiving history (§49)."""
    stmt = (
        select(ProductBatch, Product.name)
        .join(Product, ProductBatch.product_id == Product.id)
        .order_by(ProductBatch.received_at.desc())
        .limit(limit)
    )
    if product_id:
        stmt = stmt.where(ProductBatch.product_id == product_id)
    return [
        {"product_id": b.product_id, "product_name": name, "batch_number": b.batch_number,
         "buy_price": float(b.buy_price), "sell_price": float(b.sell_price),
         "qty_received": b.quantity_received, "current_qty": b.current_qty,
         "received_at": b.received_at.isoformat()}
        for b, name in db.execute(stmt).all()
    ]


def expiry_report(db: Session) -> dict:
    """Full (untruncated) expiry buckets with values (§33)."""
    thresholds = expiry_svc.get_thresholds(db)
    today = date.today()
    buckets: dict[str, list] = {}
    rows = db.execute(
        select(ProductBatch, Product.name)
        .join(Product, ProductBatch.product_id == Product.id)
        .where(ProductBatch.current_qty > 0, ProductBatch.status == "ACTIVE",
               ProductBatch.expiry_date.is_not(None))
    ).all()
    for b, name in rows:
        status = expiry_svc.classify(b, today, thresholds)
        buckets.setdefault(status, []).append({
            "batch_id": b.id, "batch_number": b.batch_number, "product_name": name,
            "qty": b.current_qty, "expiry": str(b.expiry_date),
            "days_left": expiry_svc.days_until(b, today),
            "value": float(Decimal(b.current_qty) * Decimal(b.buy_price)),
        })
    return buckets


def adjustments_report(db: Session, limit: int = 200) -> list[dict]:
    """Audit-trail view of ADJUSTMENT / WASTE / STOCKTAKE movements (§32/§49)."""
    rows = db.execute(
        select(StockMovement, Product.name, User.username)
        .join(Product, StockMovement.product_id == Product.id)
        .outerjoin(User, StockMovement.created_by == User.id)
        .where(StockMovement.movement_type.in_(["ADJUSTMENT", "WASTE", "STOCKTAKE"]))
        .order_by(StockMovement.created_at.desc())
        .limit(limit)
    ).all()
    return [
        {"movement_type": m.movement_type, "product_name": name, "batch_id": m.batch_id,
         "quantity": m.quantity, "by": username or "—" if m.created_by else "system",
         "note": m.note, "created_at": m.created_at.isoformat()}
        for m, name, username in rows
    ]


# --- Existing reports (kept, some optimised) ----------------------------------

def profit_by_batch(db: Session, start: date | None = None, end: date | None = None) -> list[dict]:
    stmt = (
        select(InvoiceItem.batch_id, InvoiceItem.product_id,
               func.coalesce(func.sum(InvoiceItem.qty), 0),
               func.coalesce(func.sum(InvoiceItem.subtotal), 0),
               func.coalesce(func.sum(InvoiceItem.profit), 0))
        .join(Invoice, InvoiceItem.invoice_id == Invoice.id)
        .where(Invoice.status == PAID)
        .group_by(InvoiceItem.batch_id, InvoiceItem.product_id)
    )
    if start and end:
        s0, _ = _day_range(start)
        _, e1 = _day_range(end)
        stmt = stmt.where(Invoice.created_at >= s0, Invoice.created_at < e1)
    rows = db.execute(stmt.order_by(func.sum(InvoiceItem.profit).desc())).all()
    return [
        {"batch_id": bid, "product_id": pid, "qty": int(qty),
         "revenue": float(Decimal(rev)), "profit": float(Decimal(prof))}
        for bid, pid, qty, rev, prof in rows
    ]


def price_history(db: Session, product_id: int) -> list[dict]:
    rows = db.execute(
        select(PriceVersion).where(PriceVersion.product_id == product_id)
        .order_by(PriceVersion.effective_from.desc())
    ).scalars().all()
    return [
        {"price_type": v.price_type, "price": float(v.price), "effective_from": v.effective_from.isoformat(),
         "effective_to": v.effective_to.isoformat() if v.effective_to else None, "source": v.source,
         "is_active": v.is_active}
        for v in rows
    ]


def stocktake_report(db: Session) -> list[dict]:
    sts = db.execute(select(Stocktake).order_by(Stocktake.created_at.desc())).scalars().all()
    return [
        {"id": st.id, "name": st.name, "status": st.status,
         "started_at": st.started_at.isoformat() if st.started_at else None,
         "completed_at": st.completed_at.isoformat() if st.completed_at else None,
         "items": len(st.items)}
        for st in sts
    ]


def low_stock_report(db: Session) -> list[dict]:
    d = dashboard(db)
    return d["inventory"]["low_stock"] + d["inventory"]["no_stock"]


def batch_status_report(db: Session) -> dict:
    rows = db.execute(
        select(ProductBatch.status, func.count(ProductBatch.id))
        .group_by(ProductBatch.status)
    ).all()
    counts = {status: int(cnt) for status, cnt in rows}
    active = int(db.execute(
        select(func.count(ProductBatch.id)).where(
            ProductBatch.status == "ACTIVE", ProductBatch.current_qty > 0)
    ).scalar_one())
    return {
        "active_count": active,
        "status_counts": counts,
        # kept for backward compatibility with the old UI
        "active": [b.batch_number for b in db.execute(
            select(ProductBatch).where(ProductBatch.status == "ACTIVE",
                                       ProductBatch.current_qty > 0).limit(200)).scalars()],
        "sold_out": [b.batch_number for b in db.execute(
            select(ProductBatch).where((ProductBatch.status == "SOLD_OUT") |
                                       (ProductBatch.current_qty <= 0)).limit(200)).scalars()],
        "expired": [b.batch_number for b in db.execute(
            select(ProductBatch).where(ProductBatch.status == "EXPIRED")).scalars()],
        "blocked": [b.batch_number for b in db.execute(
            select(ProductBatch).where(ProductBatch.status == "BLOCKED")).scalars()],
    }


def movements_report(db: Session, limit: int = 200) -> list[dict]:
    rows = db.execute(
        select(StockMovement).order_by(StockMovement.created_at.desc()).limit(limit)
    ).scalars().all()
    return [
        {"movement_type": m.movement_type, "quantity": m.quantity, "batch_id": m.batch_id,
         "product_id": m.product_id, "reference_type": m.reference_type, "reference_id": m.reference_id,
         "created_at": m.created_at.isoformat()}
        for m in rows
    ]
