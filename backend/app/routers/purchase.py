"""F-07 — purchase orders (minimal)."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from decimal import Decimal
from sqlalchemy import select
from sqlalchemy.orm import Session
from ..database import get_db
from ..models import User
from ..security import require_permission
from ..models.purchase import PurchaseOrder, PurchaseOrderLine

router = APIRouter(prefix="/purchase-orders", tags=["purchase-orders"])

class LineIn(BaseModel):
    product_id: int
    qty: Decimal = Field(gt=0)
    unit_cost: Decimal = Field(ge=0)

class CreateIn(BaseModel):
    supplier_id: int | None = None
    note: str | None = None
    lines: list[LineIn]

@router.get("")
def list_orders(db: Session = Depends(get_db), _: User = Depends(require_permission("inventory.view"))):
    rows = db.execute(select(PurchaseOrder).order_by(PurchaseOrder.id.desc()).limit(100)).scalars().all()
    return [{"id": r.id, "supplier_id": r.supplier_id, "status": r.status, "total_cost": float(r.total_cost), "lines": len(r.lines), "created_at": r.created_at.isoformat()} for r in rows]

@router.post("", status_code=201)
def create_order(body: CreateIn, db: Session = Depends(get_db), user: User = Depends(require_permission("inventory.adjust"))):
    if not body.lines:
        raise HTTPException(400, "حداقل یک ردیف لازم است")
    po = PurchaseOrder(supplier_id=body.supplier_id, status="DRAFT", note=body.note, created_by=user.id)
    db.add(po); db.flush()
    total=Decimal(0)
    for ln in body.lines:
        db.add(PurchaseOrderLine(order_id=po.id, product_id=ln.product_id, qty=ln.qty, unit_cost=ln.unit_cost))
        total+= ln.qty * ln.unit_cost
    po.total_cost=total
    db.commit()
    return {"id": po.id, "total_cost": float(total)}

@router.post("/{order_id}/receive")
def receive_order(order_id: int, db: Session = Depends(get_db), _: User = Depends(require_permission("inventory.adjust"))):
    from ..services import accounting as acc_svc
    po = db.get(PurchaseOrder, order_id)
    if not po: raise HTTPException(404, "پیدا نشد")
    if po.status != "DRAFT": raise HTTPException(409, "قبلاً دریافت شده")
    # create batches for each line
    from ..models.inventory import ProductBatch
    from datetime import datetime
    from ..services.inventory import _next_batch_number  # type: ignore
    for ln in po.lines:
        # generate minimal batch
        b = ProductBatch(product_id=ln.product_id, batch_number=f"PO-{po.id}-{ln.product_id}", quantity_received=ln.qty, current_qty=ln.qty, buy_price=ln.unit_cost, sell_price=ln.unit_cost*Decimal("1.2"), status="ACTIVE", received_at=datetime.utcnow())
        db.add(b); db.flush()
        acc_svc.post_purchase(db, b, supplier_id=po.supplier_id)
    po.status="RECEIVED"
    db.commit()
    return {"ok": True, "order_id": po.id}
