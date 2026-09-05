from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Invoice, User
from ..security import get_current_user, require_permission
from ..services import pos as pos_svc
from ..services.pos import PosError

router = APIRouter(prefix="/invoices", tags=["invoices"])


class VoidIn(BaseModel):
    reason: str | None = None


def _out(inv: Invoice) -> dict:
    return {
        "id": inv.id, "invoice_number": inv.invoice_number,
        "subtotal": float(inv.subtotal), "discount": float(inv.discount), "tax": float(inv.tax),
        "total_amount": float(inv.total_amount), "payment_method": inv.payment_method,
        "payment_status": inv.payment_status, "status": inv.status, "print_status": inv.print_status,
        "created_at": inv.created_at.isoformat() if inv.created_at else None,
        "items": [
            {"product_id": it.product_id, "batch_id": it.batch_id, "qty": it.qty,
             "unit_buy_price": float(it.unit_buy_price), "unit_consumer_price": float(it.unit_consumer_price),
             "unit_sell_price": float(it.unit_sell_price), "discount": float(it.discount),
             "subtotal": float(it.subtotal), "id": it.id,
             "profit": float(it.profit)}
            for it in inv.items
        ],
    }


@router.get("")
def list_invoices(limit: int = Query(default=100, le=1000), offset: int = 0,
                  db: Session = Depends(get_db), _: User = Depends(require_permission("reports.view"))):
    rows = db.execute(select(Invoice).order_by(Invoice.created_at.desc()).limit(limit).offset(offset)).scalars().all()
    return {"items": [_out(i) for i in rows]}


@router.get("/{invoice_id}")
def get_invoice(invoice_id: int, db: Session = Depends(get_db), _: User = Depends(require_permission("reports.view"))):
    inv = db.get(Invoice, invoice_id)
    if not inv:
        raise HTTPException(status_code=404, detail="INVOICE_NOT_FOUND")
    return _out(inv)


@router.post("/{invoice_id}/void")
def void_invoice(invoice_id: int, body: VoidIn, db: Session = Depends(get_db),
                 user: User = Depends(require_permission("pos.void_unpaid"))):
    inv = db.get(Invoice, invoice_id)
    if not inv:
        raise HTTPException(status_code=404, detail="INVOICE_NOT_FOUND")
    if inv.status == "PAID":
        # Voiding a paid invoice needs a stronger permission (§84).
        from ..security import has_permission
        if not has_permission(user, "pos.void_paid"):
            raise HTTPException(status_code=403, detail="Missing permission: pos.void_paid")
    try:
        pos_svc.void_invoice(db, invoice=inv, user=user, reason=body.reason)
        db.commit()
        return _out(inv)
    except PosError as e:
        db.rollback()
        raise HTTPException(status_code=422, detail={"code": e.code, "message": e.message})


@router.post("/{invoice_id}/print")
def print_invoice(invoice_id: int, db: Session = Depends(get_db), _: User = Depends(require_permission("pos.sell"))):
    """Attempt to (re)print via the hardware layer. Printer failure NEVER voids
    the sale (§20) — it only marks print_status=FAILED for a retry."""
    from ..services.hardware import print_receipt
    inv = db.get(Invoice, invoice_id)
    if not inv:
        raise HTTPException(status_code=404, detail="INVOICE_NOT_FOUND")
    ok, message = print_receipt(db, invoice=inv)
    db.commit()
    return {"invoice_id": inv.id, "print_status": inv.print_status, "ok": ok, "message": message}
