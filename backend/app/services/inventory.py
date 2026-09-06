"""Inventory: movements, adjustments, stocktaking reconciliation.

Rule (§38): a stock change is NEVER just ``current_qty -= X`` — it is always
``batch update + StockMovement + audit`` performed together.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import Product, ProductBatch, StockMovement, Stocktake, StocktakeItem, User
from .audit import write_audit
from .units import to_qty


class InventoryError(Exception):
    pass


def product_total_stock(db: Session, product_id: int) -> Decimal:
    return to_qty(
        db.execute(
            select(func.coalesce(func.sum(ProductBatch.current_qty), 0))
            .where(ProductBatch.product_id == product_id)
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
    new_current_qty,
    user: User | None = None,
    reason: str | None = None,
    movement_type: str = "ADJUSTMENT",
) -> ProductBatch:
    """Manually reconcile a batch's system quantity (adjustment / waste)."""
    new_current_qty = to_qty(new_current_qty)
    if new_current_qty < 0:
        raise InventoryError("Cannot set a negative batch quantity")
    delta = new_current_qty - to_qty(batch.current_qty)
    before = to_qty(batch.current_qty)
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
        before={"current_qty": float(before)},
        after={"current_qty": float(new_current_qty)}, reference=reason,
    )
    return batch


def record_waste(db: Session, *, batch: ProductBatch, qty, user: User | None = None,
                 reason: str | None = None) -> ProductBatch:
    qty = to_qty(qty)
    if qty <= 0:
        raise InventoryError("Waste quantity must be positive")
    if to_qty(batch.current_qty) < qty:
        raise InventoryError("Insufficient stock to waste")
    return adjust_batch(db, batch=batch, new_current_qty=to_qty(batch.current_qty) - qty,
                        user=user, reason=reason or "Waste", movement_type="WASTE")


def create_stocktake(db: Session, *, name: str, area: str | None = None, user: User | None = None,
                     product_ids: list[int] | None = None, batch_ids: list[int] | None = None,
                     include_zero: bool = True, warehouse_id: int | None = None) -> Stocktake:
    """Snapshot batches for counting (§19).

    ``include_zero=True`` also snapshots batches the system believes are empty —
    physical stock of a "zero" batch is exactly the kind of discrepancy a
    stocktake must be able to discover (BUG-018).
    """
    st = Stocktake(name=name, status="DRAFT", area=area, started_at=datetime.utcnow(),
                   warehouse_id=warehouse_id, created_by=user.id if user else None)
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
        if warehouse_id is not None:
            stmt = stmt.where(ProductBatch.warehouse_id == warehouse_id)
        if not include_zero:
            stmt = stmt.where(ProductBatch.current_qty > 0)
        batches = db.execute(stmt).scalars().all()

    for b in batches:
        db.add(StocktakeItem(stocktake_id=st.id, product_id=b.product_id, batch_id=b.id,
                             system_qty=to_qty(b.current_qty), status="PENDING"))
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
    ordered = sorted(items, key=lambda i: i.id)
    position = 0
    if st.cursor_item_id:
        for idx, it in enumerate(ordered, start=1):
            if it.id == st.cursor_item_id:
                position = idx
                break
    if not position:
        position = len(counted)
    total = len(items)
    return {
        "id": st.id, "name": st.name, "status": st.status,
        "warehouse_id": st.warehouse_id, "area": st.area,
        "total": total, "counted": len(counted), "remaining": len(pending),
        "percent": round(100 * len(counted) / total, 1) if total else 0.0,
        "position": position,
        "cursor_item_id": st.cursor_item_id,
        "next_item_id": pending[0].id if pending else None,
        "resumable": st.status in ("DRAFT", "IN_PROGRESS") and bool(pending),
        "started_at": st.started_at.isoformat() if st.started_at else None,
        "completed_at": st.completed_at.isoformat() if st.completed_at else None,
    }


def count_stocktake_item(db: Session, *, item_id: int, physical_qty, 
                         reason: str | None = None, user: User | None = None) -> StocktakeItem:
    """Save one physical count IMMEDIATELY (§25: every operation persists)."""
    item = db.get(StocktakeItem, item_id)
    if not item:
        raise InventoryError("Stocktake item not found")
    st = item.stocktake
    if st.status in ("PENDING_APPROVAL", "ADJUSTED", "CANCELLED"):
        raise InventoryError(f"Stocktake is {st.status}; counting is closed")
    physical_qty = to_qty(physical_qty)
    if physical_qty < 0:
        raise InventoryError("Physical quantity cannot be negative")
    product = db.get(Product, item.product_id)
    if product is not None:
        from .units import QuantityError, validate_for_unit
        try:
            physical_qty = validate_for_unit(db, product, physical_qty)
        except QuantityError as exc:
            raise InventoryError(str(exc))
    if st.status == "DRAFT":
        st.status = "IN_PROGRESS"
    item.physical_qty = physical_qty
    item.difference = physical_qty - to_qty(item.system_qty)
    item.reason = reason
    item.status = "COUNTED"
    item.counted_at = datetime.utcnow()
    item.counted_by = user.id if user else None
    # Persist the cursor so a closed/crashed app resumes at the right row (§14)
    st.cursor_item_id = item.id
    write_audit(db, action="STOCKTAKE_COUNTED",
                user_id=user.id if user else None,
                entity_type="StocktakeItem", entity_id=item.id,
                after={"physical_qty": float(physical_qty),
                       "difference": float(item.difference)},
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
                          "system_qty": float(item.system_qty),
                          "physical_qty": float(item.physical_qty),
                          "difference": float(item.difference)})

    st.status = "PENDING_APPROVAL"
    st.completed_at = datetime.utcnow()
    st.completed_by = user.id if user else None
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
        diff = to_qty(item.physical_qty or 0) - to_qty(item.system_qty)
        if diff == 0 and item.status != "ADJUSTED":
            continue
        product = db.get(Product, item.product_id)
        out.append({
            "item_id": item.id, "product_id": item.product_id,
            "product_name": product.name if product else f"#{item.product_id}",
            "batch_id": item.batch_id,
            "system_qty": float(item.system_qty),
            "physical_qty": float(item.physical_qty),
            "difference": float(diff),
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
                db, batch=batch,
                new_current_qty=max(Decimal("0"), to_qty(batch.current_qty) + to_qty(item.difference)),
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


# --- §109 / §130 / §131: warehouses, locations, transfers ---------------------

def transfer_batch(db: Session, *, batch: ProductBatch, qty, to_warehouse_id: int,
                   to_location_id: int | None = None, user: User | None = None,
                   reason: str | None = None) -> ProductBatch:
    """Move ``qty`` of a batch to another warehouse.

    Stock never teleports: the source batch is reduced with TRANSFER_OUT and a
    NEW batch (same cost/prices/expiry — costing basis is preserved) is created
    in the destination with TRANSFER_IN. Both movements share ``reference_id``
    so the pair is auditable.
    """
    from ..models import Warehouse

    qty = to_qty(qty)
    if qty <= 0:
        raise InventoryError("Transfer quantity must be positive")
    if to_qty(batch.current_qty) < qty:
        raise InventoryError("Insufficient stock to transfer")
    if (batch.warehouse_id or 0) == to_warehouse_id and (batch.location_id or None) == to_location_id:
        raise InventoryError("Source and destination are the same")
    dest = db.get(Warehouse, to_warehouse_id)
    if dest is None or not dest.is_active:
        raise InventoryError("Destination warehouse not found")

    # Full move keeps the same batch row (identity preserved); partial splits.
    if to_qty(batch.current_qty) == qty:
        add_movement(db, product_id=batch.product_id, batch_id=batch.id,
                     movement_type="TRANSFER_OUT", quantity=-qty,
                     reference_type="Warehouse", reference_id=batch.warehouse_id,
                     unit_cost=batch.buy_price, note=reason, user=user)
        batch.warehouse_id = to_warehouse_id
        batch.location_id = to_location_id
        add_movement(db, product_id=batch.product_id, batch_id=batch.id,
                     movement_type="TRANSFER_IN", quantity=qty,
                     reference_type="Warehouse", reference_id=to_warehouse_id,
                     unit_cost=batch.buy_price, note=reason, user=user)
        new_batch = batch
    else:
        batch.current_qty = to_qty(batch.current_qty) - qty
        add_movement(db, product_id=batch.product_id, batch_id=batch.id,
                     movement_type="TRANSFER_OUT", quantity=-qty,
                     reference_type="Warehouse", reference_id=to_warehouse_id,
                     unit_cost=batch.buy_price, note=reason, user=user)
        new_batch = ProductBatch(
            product_id=batch.product_id, batch_number=f"{batch.batch_number}-T{to_warehouse_id}",
            quantity_received=qty, current_qty=qty,
            buy_price=batch.buy_price, supplier_price=batch.supplier_price,
            consumer_price=batch.consumer_price, sell_price=batch.sell_price,
            discount=batch.discount, tax=batch.tax,
            production_date=batch.production_date, expiry_date=batch.expiry_date,
            received_at=batch.received_at, status="ACTIVE",
            warehouse_id=to_warehouse_id, location_id=to_location_id,
            note=f"transfer from batch {batch.id}",
        )
        db.add(new_batch)
        db.flush()
        add_movement(db, product_id=batch.product_id, batch_id=new_batch.id,
                     movement_type="TRANSFER_IN", quantity=qty,
                     reference_type="ProductBatch", reference_id=batch.id,
                     unit_cost=batch.buy_price, note=reason, user=user)
    write_audit(db, action="STOCK_TRANSFERRED", user_id=user.id if user else None,
                entity_type="ProductBatch", entity_id=batch.id,
                after={"qty": float(qty), "to_warehouse_id": to_warehouse_id,
                       "to_location_id": to_location_id, "new_batch_id": new_batch.id},
                reference=reason)
    return new_batch


def ensure_default_warehouse(db: Session):
    from ..models import Warehouse
    w = db.execute(select(Warehouse).where(Warehouse.is_default.is_(True))).scalar_one_or_none()
    if w is None:
        w = db.execute(select(Warehouse).order_by(Warehouse.id)).scalars().first()
        if w is None:
            w = Warehouse(name="انبار اصلی", code="MAIN", is_default=True, is_active=True)
            db.add(w)
        else:
            w.is_default = True
        db.flush()
    return w
