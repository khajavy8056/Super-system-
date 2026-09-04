"""Dashboard + reporting (blueprint §8, §88–89, §140–143)."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import (
    Category,
    Invoice,
    InvoiceItem,
    Product,
    ProductBatch,
    PriceVersion,
    StockMovement,
)
from . import expiry as expiry_svc

ZERO = Decimal("0")


def _day_range(d: date) -> tuple[datetime, datetime]:
    start = datetime(d.year, d.month, d.day)
    return start, start + timedelta(days=1)


def _sales_between(db: Session, start: datetime, end: datetime, *, paid_only: bool = True) -> list[Invoice]:
    q = select(Invoice).where(Invoice.created_at >= start, Invoice.created_at < end)
    if paid_only:
        q = q.where(Invoice.status == "PAID")
    return list(db.execute(q).scalars())


def dashboard(db: Session) -> dict:
    today = date.today()
    t0, t1 = _day_range(today)
    y0, y1 = _day_range(today - timedelta(days=1))
    m0 = datetime(today.year, today.month, 1)

    today_inv = _sales_between(db, t0, t1)
    yest_inv = _sales_between(db, y0, y1)
    month_inv = _sales_between(db, m0, datetime.utcnow())

    today_sales = sum((i.total_amount for i in today_inv), ZERO)
    yest_sales = sum((i.total_amount for i in yest_inv), ZERO)
    month_sales = sum((i.total_amount for i in month_inv), ZERO)

    def profit_of(invoices: list[Invoice]) -> Decimal:
        if not invoices:
            return ZERO
        ids = [i.id for i in invoices]
        items = db.execute(select(InvoiceItem).where(InvoiceItem.invoice_id.in_(ids))).scalars().all()
        return sum((it.profit for it in items), ZERO)

    today_profit = profit_of(today_inv)
    month_profit = profit_of(month_inv)

    batches = list(db.execute(select(ProductBatch)).scalars())
    active_batches = [b for b in batches if b.current_qty > 0 and b.status == "ACTIVE"]
    inventory_value = sum((Decimal(b.current_qty) * b.buy_price for b in active_batches), ZERO)

    products = list(db.execute(select(Product).where(Product.deleted_at.is_(None))).scalars())
    low_stock, no_stock = [], []
    for p in products:
        total = sum(b.current_qty for b in batches if b.product_id == p.id)
        if total <= 0:
            no_stock.append({"product_id": p.id, "name": p.name, "barcode": p.barcode})
        elif p.min_stock_alert and total <= p.min_stock_alert:
            low_stock.append({"product_id": p.id, "name": p.name, "barcode": p.barcode, "qty": total})

    expiry_buckets = {"EXPIRED": [], "EXPIRING_TODAY": [], "EXPIRING_3_DAYS": [], "EXPIRING_7_DAYS": [], "EXPIRING_30_DAYS": []}
    for b in active_batches:
        if b.expiry_date:
            status = expiry_svc.classify(b)
            if status != "NORMAL":
                expiry_buckets[status].append({
                    "batch_id": b.id, "batch_number": b.batch_number,
                    "product_id": b.product_id, "product_name": b.product.name if b.product else "",
                    "qty": b.current_qty, "expiry": str(b.expiry_date),
                    "days_left": expiry_svc.days_until(b),
                    "value": float(Decimal(b.current_qty) * b.buy_price),
                })

    # Price issues (§8 price widget).
    price_conflicts = []
    for p in products:
        prices = {b.sell_price for b in active_batches if b.product_id == p.id and b.sell_price}
        if len(prices) > 1:
            price_conflicts.append({"product_id": p.id, "name": p.name,
                                    "prices": sorted(float(x) for x in prices)})

    return {
        "sales": {
            "today": float(today_sales), "yesterday": float(yest_sales),
            "month": float(month_sales),
            "invoice_count_today": len(today_inv),
            "avg_invoice_today": float(today_sales / len(today_inv)) if today_inv else 0.0,
        },
        "profit": {"today": float(today_profit), "month": float(month_profit)},
        "inventory": {
            "value": float(inventory_value), "product_count": len(products),
            "low_stock": low_stock[:50], "no_stock": no_stock[:50],
            "low_stock_count": len(low_stock), "no_stock_count": len(no_stock),
        },
        "expiry": {k: v for k, v in expiry_buckets.items()},
        "pricing": {"price_conflicts": price_conflicts[:50], "price_conflict_count": len(price_conflicts)},
    }


def sales_report(db: Session, start: date, end: date, group: str = "daily") -> dict:
    s0, s1 = _day_range(start)
    e0, e1 = _day_range(end)
    invoices = _sales_between(db, s0, e1)
    return {
        "total_sales": float(sum((i.total_amount for i in invoices), ZERO)),
        "invoice_count": len(invoices),
        "invoices": [
            {"invoice_number": i.invoice_number, "total": float(i.total_amount),
             "created_at": i.created_at.isoformat(), "status": i.status,
             "payment_method": i.payment_method}
            for i in invoices
        ],
    }


def profit_by_batch(db: Session, start: date | None = None, end: date | None = None) -> list[dict]:
    q = select(InvoiceItem)
    if start and end:
        s0, _ = _day_range(start)
        _, e1 = _day_range(end)
        sub = select(Invoice.id).where(Invoice.created_at >= s0, Invoice.created_at < e1)
        q = q.where(InvoiceItem.invoice_id.in_(sub))
    items = list(db.execute(q).scalars())
    agg: dict[int, dict] = {}
    for it in items:
        key = it.batch_id or 0
        if key not in agg:
            agg[key] = {"batch_id": it.batch_id, "product_id": it.product_id,
                        "qty": 0, "revenue": ZERO, "profit": ZERO}
        agg[key]["qty"] += it.qty
        agg[key]["revenue"] += it.subtotal
        agg[key]["profit"] += it.profit
    return [
        {**v, "revenue": float(v["revenue"]), "profit": float(v["profit"])}
        for v in agg.values()
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


def stocktake_report(db: Session) -> dict:
    from ..models import Stocktake
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
    batches = list(db.execute(select(ProductBatch)).scalars())
    return {
        "active": [b.batch_number for b in batches if b.status == "ACTIVE" and b.current_qty > 0],
        "sold_out": [b.batch_number for b in batches if b.status == "SOLD_OUT" or b.current_qty <= 0],
        "expired": [b.batch_number for b in batches if b.status == "EXPIRED"],
        "blocked": [b.batch_number for b in batches if b.status == "BLOCKED"],
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
