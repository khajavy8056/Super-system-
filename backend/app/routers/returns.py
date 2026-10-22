from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Invoice, InvoiceItem, User
from ..security import has_permission, require_permission
from ..services import pos as pos_svc
from ..services.pos import PosError

router = APIRouter(prefix="/returns", tags=["returns"])


class ReturnIn(BaseModel):
    invoice_id: int
    invoice_item_id: int
    # I-01: qty must support fractional for weight-based products (Decimal, not int)
    qty: Decimal = Field(gt=0)
    reason: str | None = None
    refund_amount: Decimal | None = None


@router.post("", status_code=201)
def create_return(body: ReturnIn, db: Session = Depends(get_db),
                  user: User = Depends(require_permission("pos.return"))):
    inv = db.get(Invoice, body.invoice_id)
    item = db.get(InvoiceItem, body.invoice_item_id)
    if not inv or not item or item.invoice_id != inv.id:
        raise HTTPException(status_code=404, detail="INVOICE_NOT_FOUND")
    if not has_permission(user, "reports.view_all") and inv.created_by != user.id:
        raise HTTPException(status_code=404, detail="INVOICE_NOT_FOUND")
    # I-01 guard: if product's unit disallows decimal, qty must be integral
    try:
        from ..models.inventory import ProductBatch
        from ..models.catalog import Product
        batch = db.get(ProductBatch, item.batch_id) if item.batch_id else None
        prod = db.get(Product, item.product_id) if not batch else db.get(Product, batch.product_id)
        if prod and prod.unit:
            # unit.allow_decimal is the source of truth
            if not getattr(prod.unit, "allow_decimal", True):
                # qty must be integer value (e.g., 2.0 is ok, 2.5 is not)
                if body.qty != body.qty.to_integral_value():
                    raise HTTPException(status_code=422, detail={"code": "FRACTIONAL_NOT_ALLOWED", "message": "این کالا فقط به تعداد صحیح قابل برگشت است"})
        elif prod and hasattr(prod, "unit_id"):
            # fallback: check Unit via product's unit_id if relation not loaded
            from ..models.catalog import Unit
            unit = db.get(Unit, prod.unit_id) if getattr(prod, "unit_id", None) else None
            if unit and not getattr(unit, "allow_decimal", True):
                if body.qty != body.qty.to_integral_value():
                    raise HTTPException(status_code=422, detail={"code": "FRACTIONAL_NOT_ALLOWED", "message": "این کالا فقط به تعداد صحیح قابل برگشت است"})
    except HTTPException:
        raise
    except Exception:
        pass  # defensive: unit check failure should not block return for legacy data
    try:
        ret = pos_svc.process_return(db, invoice=inv, invoice_item=item, qty=body.qty,
                                     user=user, reason=body.reason, refund_amount=body.refund_amount)
        db.commit()
        return {"return_id": ret.id, "qty": float(ret.qty), "refund_amount": float(ret.refund_amount),
                "status": ret.status}
    except PosError as e:
        db.rollback()
        raise HTTPException(status_code=422, detail={"code": e.code, "message": e.message})
