"""Product catalog + receiving (batch creation) services.

Implements blueprint §22–25, §90–94: products are separate from batches, a new
receiving always creates a NEW batch (never overwrites the old one), and the
system flags buy-price changes at receiving time.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import Brand, Category, Product, ProductBatch, StockMovement, Unit, User
from .audit import write_audit
from .notifications import notify


class CatalogError(Exception):
    pass


def _next_batch_number(db: Session) -> str:
    """Generate an internal batch number: B-YYYYMMDD-000123 (§92)."""
    today = datetime.utcnow().strftime("%Y%m%d")
    prefix = f"B-{today}-"
    row = db.execute(
        select(func.count()).select_from(ProductBatch).where(ProductBatch.batch_number.like(f"{prefix}%"))
    ).scalar_one()
    return f"{prefix}{int(row) + 1:06d}"


def get_product_by_barcode(db: Session, barcode: str) -> Product | None:
    return db.execute(select(Product).where(Product.barcode == barcode, Product.deleted_at.is_(None))).scalar_one_or_none()


def create_product(
    db: Session,
    *,
    barcode: str,
    name: str,
    user: User | None = None,
    sku: str | None = None,
    brand_id: int | None = None,
    category_id: int | None = None,
    unit_id: int | None = None,
    model: str | None = None,
    description: str | None = None,
    image_url: str | None = None,
    min_stock_alert: int = 0,
) -> Product:
    if get_product_by_barcode(db, barcode):
        raise CatalogError(f"Product with barcode {barcode} already exists")
    product = Product(
        barcode=barcode,
        name=name,
        sku=sku,
        brand_id=brand_id,
        category_id=category_id,
        unit_id=unit_id,
        model=model,
        description=description,
        image_url=image_url,
        min_stock_alert=min_stock_alert,
        is_active=True,
    )
    db.add(product)
    db.flush()
    write_audit(
        db, action="PRODUCT_CREATED", user_id=user.id if user else None,
        entity_type="Product", entity_id=product.id, after={"barcode": barcode, "name": name},
    )
    return product


def update_product(db: Session, product: Product, *, user: User | None = None, **fields) -> Product:
    before = {"name": product.name, "min_stock_alert": product.min_stock_alert, "is_active": product.is_active}
    for key, value in fields.items():
        if value is not None and hasattr(product, key):
            setattr(product, key, value)
    db.flush()
    write_audit(
        db, action="PRODUCT_UPDATED", user_id=user.id if user else None,
        entity_type="Product", entity_id=product.id, before=before,
        after={k: getattr(product, k) for k in before},
    )
    return product


def receive_batch(
    db: Session,
    *,
    product: Product,
    quantity_received,
    buy_price: Decimal,
    consumer_price: Decimal | None = None,
    sell_price: Decimal | None = None,
    production_date: date | None = None,
    expiry_date: date | None = None,
    batch_number: str | None = None,
    received_at: datetime | None = None,
    user: User | None = None,
    note: str | None = None,
) -> ProductBatch:
    """Register receiving: always creates a NEW batch + PURCHASE_IN movement.

    ADR-001: the batch inherits its sell price from the active SELL
    PriceVersion when not provided, and snapshots it — so old-price batches
    stay sellable at their own price (§16) while new batches follow the
    current version. The first batch also seeds the price history."""
    from .units import QuantityError, to_qty, validate_for_unit

    try:
        quantity_received = validate_for_unit(db, product, to_qty(quantity_received))
    except QuantityError as exc:
        raise CatalogError(str(exc))
    if quantity_received <= 0:
        raise CatalogError("quantity_received must be positive")

    from .pricing import active_price, set_price as set_price_version

    current_active_sell = active_price(db, product.id, "SELL")
    effective_sell = sell_price
    if effective_sell is None:
        effective_sell = current_active_sell  # inherit the current versioned price

    # Detect buy-price change vs. the most recent batch (§93).
    price_change_warning: str | None = None
    existing_batches = db.execute(
        select(ProductBatch)
        .where(ProductBatch.product_id == product.id, ProductBatch.batch_number != "")
        .order_by(ProductBatch.received_at.desc())
        .limit(1)
    ).scalars().all()
    if existing_batches:
        old_buy = existing_batches[0].buy_price
        if old_buy and buy_price != old_buy:
            pct = (Decimal(buy_price) - Decimal(old_buy)) / Decimal(old_buy) * 100
            direction = "increased" if buy_price > old_buy else "decreased"
            price_change_warning = f"Buy price {direction}: {old_buy} -> {buy_price} ({pct:+.1f}%)"

    batch = ProductBatch(
        product_id=product.id,
        batch_number=batch_number or _next_batch_number(db),
        quantity_received=quantity_received,
        current_qty=quantity_received,
        buy_price=buy_price,
        consumer_price=consumer_price if consumer_price is not None else (effective_sell or buy_price),
        sell_price=effective_sell if effective_sell is not None else (consumer_price or buy_price),
        production_date=production_date,
        expiry_date=expiry_date,
        received_at=received_at or datetime.utcnow(),
        status="ACTIVE",
        note=note,
    )
    db.add(batch)
    db.flush()

    # Seed the price history if this is the product's first price (ADR-001).
    if current_active_sell is None and batch.sell_price not in (None, 0):
        set_price_version(
            db, product=product, price_type="SELL", price=Decimal(batch.sell_price),
            user=user, source="batch_initial", note=f"Seeded from first batch {batch.batch_number}",
        )


    movement = StockMovement(
        product_id=product.id,
        batch_id=batch.id,
        movement_type="PURCHASE_IN",
        quantity=quantity_received,
        reference_type="ProductBatch",
        reference_id=batch.id,
        unit_cost=buy_price,
        created_by=user.id if user else None,
    )
    db.add(movement)
    write_audit(
        db, action="BATCH_CREATED", user_id=user.id if user else None,
        entity_type="ProductBatch", entity_id=batch.id,
        after={"batch_number": batch.batch_number, "qty": float(quantity_received),
               "buy": str(buy_price)},
    )
    if price_change_warning:
        notify(db, type="PRICE_CHANGE", title="Buy price changed", body=price_change_warning,
               severity="WARNING", reference_type="ProductBatch", reference_id=batch.id)
    return batch


def list_batches(db: Session, product_id: int) -> list[ProductBatch]:
    return list(
        db.execute(
            select(ProductBatch).where(ProductBatch.product_id == product_id).order_by(ProductBatch.received_at.asc())
        ).scalars()
    )


def active_batches(db: Session, product_id: int) -> list[ProductBatch]:
    return [
        b for b in list_batches(db, product_id)
        if b.status == "ACTIVE" and b.current_qty > 0
    ]
