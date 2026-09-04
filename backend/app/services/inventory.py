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
                     product_ids: list[int] | None = None, batch_ids: list[int] | None = None,
                     include_zero: bool = True) -> Stocktake:
    """Snapshot batches for counting (§19).

    ``include_zero=True`` also snapshots batches the system believes are empty —
    physical stock of a "zero" batch is exactly the kind of discrepancy a
    stocktake must be able to discover (BUG-018).
    """
    st = Stocktake(name=name, status="DRAFT", area=area, started_at=datetime.utcnow(),
                   created_by=user.id if user else None)
    db.add(st)
    db.flush()

    if batch_ids:
        batches = db.execute(select(ProductBatch).where(ProductBatch.id.in_(batch_ids))).scalars().all()
    elif product_ids:
        stmt = select(ProductBatch).where(ProductBatch.product_id.in_(product_ids))
        if not include_zero:
            stmt = stmt.where(ProductBatch.current_qty > 0)
        batches = db.execute(stmt).scalars().all()
    else:
        stmt = select(ProductBatch).where(ProductBatch.status.in_(["ACTIVE", "SOLD_OUT", "EXPIRED"]))
        if not include_zero:
            stmt = stmt.where(ProductBatch.current_qty > 0)
        batches = db.execute(stmt).scalars().all()

    for b in batches:
        db.add(StocktakeItem(stocktake_id=st.id, product_id=b.product_id, batch_id=b.id,
                             system_qty=b.current_qty, status="PENDING"))
    db.flush()
    write_audit(db, action="STOCKTAKE_CREATED", user_id=user.id if user else None,
                entity_type="Stocktake", entity_id=st.id, after={"name": name, "items": len(batches)})
    return st


def start_stocktake(db: Session, *, stocktake_id: int, user: User | None = None) -> Stocktake:
    st = db.get(Stocktake, stocktake_id)
    if not st:
        raise InventoryError("Stocktake not found")
    if st.status != "DRAFT":
        raise InventoryError(f"Cannot start a stocktake in state {st.status}")
    st.status = "IN_PROGRESS"
    db.flush()
    write_audit(db, action="STOCKTAKE_STARTED", user_id=user.id if user else None,
                entity_type="Stocktake", entity_id=st.id)
    return st


def stocktake_progress(db: Session, stocktake_id: int) -> dict:
    """Progress + the next pending item so a closed app can resume exactly
    where it left off (§20)."""
    st = db.get(Stocktake, stocktake_id)
    if not st:
        raise InventoryError("Stocktake not found")
    items = list(st.items)
    counted = [i for i in items if i.status in ("COUNTED", "ADJUSTED")]
    pending = [i for i in items if i.status == "PENDING"]
    return {
        "id": st.id, "name": st.name, "status": st.status,
        "total": len(items), "counted": len(counted), "remaining": len(pending),
        "next_item_id": pending[0].id if pending else None,
        "started_at": st.started_at.isoformat() if st.started_at else None,
        "completed_at": st.completed_at.isoformat() if st.completed_at else None,
    }


def count_stocktake_item(db: Session, *, item_id: int, physical_qty: int,
                         reason: str | None = None, user: User | None = None) -> StocktakeItem:
    """Save one physical count IMMEDIATELY (§25: every operation persists)."""
    item = db.get(StocktakeItem, item_id)
    if not item:
        raise InventoryError("Stocktake item not found")
    st = item.stocktake
    if st.status in ("PENDING_APPROVAL", "ADJUSTED", "CANCELLED"):
        raise InventoryError(f"Stocktake is {st.status}; counting is closed")
    if physical_qty < 0:
        raise InventoryError("Physical quantity cannot be negative")
    if st.status == "DRAFT":
        st.status = "IN_PROGRESS"
    item.physical_qty = physical_qty
    item.difference = physical_qty - item.system_qty
    item.reason = reason
    item.status = "COUNTED"
    write_audit(db, action="STOCKTAKE_COUNTED",
                user_id=user.id if user else None,
                entity_type="StocktakeItem", entity_id=item.id,
                after={"physical_qty": physical_qty, "difference": item.difference},
                reference=f"stocktake:{st.id}")
    db.flush()
    return item


def complete_stocktake(db: Session, *, stocktake_id: int, user: User | None = None) -> Stocktake:
    """Finish counting -> PENDING_APPROVAL with a difference report (§19).

    No stock is changed here — adjustments happen only after a manager
    approves (approve_stocktake)."""
    st = db.get(Stocktake, stocktake_id)
    if not st:
        raise InventoryError("Stocktake not found")
    if st.status not in ("DRAFT", "IN_PROGRESS"):
        raise InventoryError(f"Cannot complete a stocktake in state {st.status}")

    diffs = []
    for item in st.items:
        if item.status != "COUNTED":
            continue
        if item.difference != 0:
            diffs.append({"item_id": item.id, "batch_id": item.batch_id,
                          "system_qty": item.system_qty, "physical_qty": item.physical_qty,
                          "difference": item.difference})

    st.status = "PENDING_APPROVAL"
    st.completed_at = datetime.utcnow()
    write_audit(
        db, action="STOCKTAKE_COMPLETED", user_id=user.id if user else None,
        entity_type="Stocktake", entity_id=st.id,
        after={"name": st.name, "differences": len(diffs)},
    )
    db.flush()
    return st


def stocktake_differences(db: Session, stocktake_id: int) -> list[dict]:
    """System vs physical comparison incl. estimated value difference (§34)."""
    st = db.get(Stocktake, stocktake_id)
    if not st:
        raise InventoryError("Stocktake not found")
    out = []
    for item in st.items:
        if item.status not in ("COUNTED", "ADJUSTED") or item.physical_qty is None:
            continue
        batch = db.get(ProductBatch, item.batch_id) if item.batch_id else None
        cost = Decimal(batch.buy_price) if batch else Decimal("0")
        diff = (item.physical_qty or 0) - item.system_qty
        if diff == 0 and item.status != "ADJUSTED":
            continue
        product = db.get(Product, item.product_id)
        out.append({
            "item_id": item.id, "product_id": item.product_id,
            "product_name": product.name if product else f"#{item.product_id}",
            "batch_id": item.batch_id,
            "system_qty": item.system_qty, "physical_qty": item.physical_qty,
            "difference": diff,
            "value_difference": float(cost * diff),
            "reason": item.reason, "status": item.status,
        })
    return out


def approve_stocktake(db: Session, *, stocktake_id: int, user: User | None = None,
                      reason: str | None = None) -> Stocktake:
    """Manager approval -> apply adjustments + STOCKTAKE movements + audit (§19)."""
    st = db.get(Stocktake, stocktake_id)
    if not st:
        raise InventoryError("Stocktake not found")
    if st.status == "ADJUSTED":
        raise InventoryError("Stocktake already approved & applied")
    if st.status != "PENDING_APPROVAL":
        raise InventoryError(f"Stocktake is {st.status}; complete the counting first")

    applied = 0
    for item in st.items:
        if item.status != "COUNTED" or item.difference == 0:
            if item.status == "COUNTED":
                item.status = "VERIFIED"  # counted, no difference
            continue
        batch = db.get(ProductBatch, item.batch_id) if item.batch_id else None
        if batch:
            adjust_batch(
                db, batch=batch, new_current_qty=max(0, batch.current_qty + item.difference),
                user=user, reason=item.reason or f"Stocktake #{st.id}", movement_type="STOCKTAKE",
            )
            item.status = "ADJUSTED"
            applied += 1

    st.status = "ADJUSTED"
    write_audit(
        db, action="STOCKTAKE_APPROVED", user_id=user.id if user else None,
        entity_type="Stocktake", entity_id=st.id,
        after={"name": st.name, "adjusted_items": applied}, reference=reason,
    )
    db.flush()
    return st


def cancel_stocktake(db: Session, *, stocktake_id: int, user: User | None = None,
                     reason: str | None = None) -> Stocktake:
    st = db.get(Stocktake, stocktake_id)
    if not st:
        raise InventoryError("Stocktake not found")
    if st.status == "ADJUSTED":
        raise InventoryError("Cannot cancel an applied stocktake")
    st.status = "CANCELLED"
    write_audit(db, action="STOCKTAKE_CANCELLED", user_id=user.id if user else None,
                entity_type="Stocktake", entity_id=st.id, reference=reason)
    db.flush()
    return st
