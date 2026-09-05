from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Invoice, InvoiceItem, User
from ..security import get_current_user, require_permission
from ..services import pos as pos_svc
from ..services.pos import PosError

router = APIRouter(prefix="/returns", tags=["returns"])


class ReturnIn(BaseModel):
    invoice_id: int
    invoice_item_id: int
    qty: int = Field(ge=1)
    reason: str | None = None
    refund_amount: Decimal | None = None


@router.post("", status_code=201)
def create_return(body: ReturnIn, db: Session = Depends(get_db),
                  user: User = Depends(require_permission("pos.return"))):
    inv = db.get(Invoice, body.invoice_id)
    item = db.get(InvoiceItem, body.invoice_item_id)
    if not inv or not item or item.invoice_id != inv.id:
        raise HTTPException(status_code=404, detail="INVOICE_NOT_FOUND")
    try:
        ret = pos_svc.process_return(db, invoice=inv, invoice_item=item, qty=body.qty,
                                     user=user, reason=body.reason, refund_amount=body.refund_amount)
        db.commit()
        return {"return_id": ret.id, "qty": ret.qty, "refund_amount": float(ret.refund_amount),
                "status": ret.status}
    except PosError as e:
        db.rollback()
        raise HTTPException(status_code=422, detail={"code": e.code, "message": e.message})
