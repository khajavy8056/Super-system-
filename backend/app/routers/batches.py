from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Product, ProductBatch, User
from ..security import get_current_user, require_permission
from ..services import catalog
from ..services.catalog import CatalogError

router = APIRouter(prefix="/batches", tags=["batches"])


class ReceiveIn(BaseModel):
    product_id: int | None = None
    barcode: str | None = None
    quantity_received: Decimal = Field(gt=0)  # decimal-aware (§25)
    buy_price: Decimal = Field(ge=0)
    consumer_price: Decimal | None = None
    sell_price: Decimal | None = None
    production_date: date | None = None
    expiry_date: date | None = None
    batch_number: str | None = None
    note: str | None = None
    # §6 — money fields belong to the batch, not the product.
    supplier_price: Decimal | None = None
    discount: Decimal | None = None
    tax: Decimal | None = None


def _out(b: ProductBatch) -> dict:
    return {
        "id": b.id, "product_id": b.product_id, "batch_number": b.batch_number,
        "quantity_received": float(b.quantity_received), "current_qty": float(b.current_qty),
        "buy_price": float(b.buy_price), "consumer_price": float(b.consumer_price),
        "sell_price": float(b.sell_price),
        "supplier_price": float(b.supplier_price) if b.supplier_price is not None else None,
        "discount": float(b.discount or 0), "tax": float(b.tax or 0),
        "production_date": str(b.production_date) if b.production_date else None,
        "expiry_date": str(b.expiry_date) if b.expiry_date else None,
        "received_at": b.received_at.isoformat() if b.received_at else None,
        "status": b.status, "note": b.note,
        "warehouse_id": b.warehouse_id, "location_id": b.location_id,
    }


@router.get("")
def list_batches(product_id: int | None = None, db: Session = Depends(get_db),
                 _: User = Depends(require_permission("inventory.view"))):
    stmt = select(ProductBatch).order_by(ProductBatch.received_at.desc())
    if product_id:
        stmt = stmt.where(ProductBatch.product_id == product_id)
    return [_out(b) for b in db.execute(stmt).scalars()]


@router.get("/{batch_id}")
def get_batch(batch_id: int, db: Session = Depends(get_db), _: User = Depends(require_permission("inventory.view"))):
    b = db.get(ProductBatch, batch_id)
    if not b:
        raise HTTPException(status_code=404, detail="BATCH_NOT_FOUND")
    return _out(b)


@router.post("/receive", status_code=201)
def receive(body: ReceiveIn, db: Session = Depends(get_db),
            user: User = Depends(require_permission("batches.manage"))):
    product: Product | None = None
    if body.product_id:
        product = db.get(Product, body.product_id)
    elif body.barcode:
        product = catalog.get_product_by_barcode(db, body.barcode)
    if not product:
        raise HTTPException(status_code=404, detail="PRODUCT_NOT_FOUND")

    try:
        batch = catalog.receive_batch(
            db, product=product, quantity_received=body.quantity_received,
            buy_price=body.buy_price, consumer_price=body.consumer_price,
            sell_price=body.sell_price, production_date=body.production_date,
            expiry_date=body.expiry_date, batch_number=body.batch_number,
            received_at=datetime.utcnow(), user=user, note=body.note,
            supplier_price=body.supplier_price, discount=body.discount,
            tax=body.tax,
        )
        db.commit()
        return _out(batch)
    except CatalogError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/{batch_id}", status_code=204)
def delete_batch(batch_id: int, db: Session = Depends(get_db),
                 user: User = Depends(require_permission("batches.delete"))):
    """Soft-delete an empty batch (never a batch with history — §28/§100)."""
    b = db.get(ProductBatch, batch_id)
    if not b:
        raise HTTPException(status_code=404, detail="BATCH_NOT_FOUND")
    if b.current_qty > 0:
        raise HTTPException(status_code=400, detail="Cannot delete a batch with remaining stock")
    b.status = "BLOCKED"
    from ..services.audit import write_audit
    write_audit(db, action="BATCH_DELETED", user_id=user.id, entity_type="ProductBatch", entity_id=b.id)
    db.commit()
