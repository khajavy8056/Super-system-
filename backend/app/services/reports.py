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
