"""Inventory: movements, adjustments, stocktaking reconciliation.

Rule (§38): a stock change is NEVER just ``current_qty -= X`` — it is always
``batch update + StockMovement + audit`` performed together.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Product, ProductBatch, StockMovement, Stocktake, StocktakeItem, User
from .audit import write_audit


class InventoryError(Exception):
    pass


def product_total_stock(db: Session, product_id: int) -> int:
    from ..models import ProductBatch
    return int(
        db.execute(
            select(__import__("sqlalchemy").func.coalesce(
                __import__("sqlalchemy").func.sum(ProductBatch.current_qty), 0)
            ).where(ProductBatch.product_id == product_id)
        ).scalar_one()
    )


def add_movement(
    db: Session,
    *,
    product_id: int,
    batch_id: int | None,
    movement_type: str,
    quantity: int,
    reference_type: str | None = None,
    reference_id: int | None = None,
    unit_cost: Decimal | None = None,
    note: str | None = None,
    user: User | None = None,
) -> StockMovement:
    mv = StockMovement(
        product_id=product_id,
        batch_id=batch_id,
        movement_type=movement_type,
        quantity=quantity,
        reference_type=reference_type,
        reference_id=reference_id,
        unit_cost=unit_cost,
        note=note,
        created_by=user.id if user else None,
    )
    db.add(mv)
    db.flush()
    return mv


def adjust_batch(
    db: Session,
    *,
    batch: ProductBatch,
    new_current_qty: int,
    user: User | None = None,
    reason: str | None = None,
    movement_type: str = "ADJUSTMENT",
) -> ProductBatch:
    """Manually reconcile a batch's system quantity (adjustment / waste)."""
    if new_current_qty < 0:
        raise InventoryError("Cannot set a negative batch quantity")
    delta = new_current_qty - batch.current_qty
    before = batch.current_qty
    batch.current_qty = new_current_qty
    if batch.status in ("SOLD_OUT",) and new_current_qty > 0:
        batch.status = "ACTIVE"
    elif new_current_qty == 0 and batch.status == "ACTIVE":
        batch.status = "SOLD_OUT"
    add_movement(
        db, product_id=batch.product_id, batch_id=batch.id,
        movement_type=movement_type, quantity=delta,
        reference_type="ProductBatch", reference_id=batch.id,
        unit_cost=batch.buy_price, note=reason, user=user,
    )
    write_audit(
        db, action="STOCK_ADJUSTED", user_id=user.id if user else None,
        entity_type="ProductBatch", entity_id=batch.id,
        before={"current_qty": before}, after={"current_qty": new_current_qty}, reference=reason,
    )
    return batch


def record_waste(db: Session, *, batch: ProductBatch, qty: int, user: User | None = None, reason: str | None = None) -> ProductBatch:
    if qty <= 0:
        raise InventoryError("Waste quantity must be positive")
    if batch.current_qty < qty:
        raise InventoryError("Insufficient stock to waste")
    return adjust_batch(db, batch=batch, new_current_qty=batch.current_qty - qty,
                        user=user, reason=reason or "Waste", movement_type="WASTE")


def create_stocktake(db: Session, *, name: str, area: str | None = None, user: User | None = None,
                     product_ids: list[int] | None = None, batch_ids: list[int] | None = None) -> Stocktake:
    st = Stocktake(name=name, status="DRAFT", area=area, started_at=datetime.utcnow(),
                   created_by=user.id if user else None)
    db.add(st)
    db.flush()

    if batch_ids:
        batches = db.execute(select(ProductBatch).where(ProductBatch.id.in_(batch_ids))).scalars().all()
    elif product_ids:
        batches = db.execute(
            select(ProductBatch).where(ProductBatch.product_id.in_(product_ids), ProductBatch.current_qty > 0)
        ).scalars().all()
    else:
        batches = db.execute(select(ProductBatch).where(ProductBatch.current_qty > 0)).scalars().all()

    for b in batches:
        db.add(StocktakeItem(stocktake_id=st.id, product_id=b.product_id, batch_id=b.id,
                             system_qty=b.current_qty, status="PENDING"))
    db.flush()
    return st


def count_stocktake_item(db: Session, *, item_id: int, physical_qty: int,
                         reason: str | None = None, user: User | None = None) -> StocktakeItem:
    item = db.get(StocktakeItem, item_id)
    if not item:
        raise InventoryError("Stocktake item not found")
    if physical_qty < 0:
        raise InventoryError("Physical quantity cannot be negative")
    item.physical_qty = physical_qty
    item.difference = physical_qty - item.system_qty
    item.reason = reason
    item.status = "COUNTED"
    db.flush()
    return item


def complete_stocktake(db: Session, *, stocktake_id: int, user: User | None = None) -> Stocktake:
    """Apply counted differences as STOCKTAKE movements + audit (§41, §109)."""
    st = db.get(Stocktake, stocktake_id)
    if not st:
        raise InventoryError("Stocktake not found")
    if st.status == "COMPLETED":
        raise InventoryError("Stocktake already completed")

    for item in st.items:
        if item.status != "COUNTED" or item.difference == 0:
            continue
        batch = db.get(ProductBatch, item.batch_id) if item.batch_id else None
        if batch:
            adjust_batch(
                db, batch=batch, new_current_qty=batch.current_qty + item.difference,
                user=user, reason=item.reason or "Stocktake", movement_type="STOCKTAKE",
            )
        item.status = "ADJUSTED"

    st.status = "COMPLETED"
    st.completed_at = datetime.utcnow()
    write_audit(
        db, action="STOCKTAKE_COMPLETED", user_id=user.id if user else None,
        entity_type="Stocktake", entity_id=st.id, after={"name": st.name},
    )
    return st
