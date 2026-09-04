from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Product, User
from ..security import get_current_user, require_permission
from ..services import pos as pos_svc
from ..services.pos import CartItem, PosError

router = APIRouter(prefix="/pos", tags=["pos"])


class CartLineIn(BaseModel):
    product_id: int
    quantity: int = Field(default=1, ge=1)
    batch_id: int | None = None


class CartIn(BaseModel):
    items: list[CartLineIn]
    tax_rate: Decimal | None = None


class PaymentIn(BaseModel):
    method: str = "CASH"
    amount: Decimal = Field(ge=0)


class CheckoutIn(BaseModel):
    items: list[CartLineIn]
    payments: list[PaymentIn]
    customer_id: int | None = None
    tax_rate: Decimal | None = None


@router.get("/batch-options/{product_id}")
def batch_options(product_id: int, db: Session = Depends(get_db), _: User = Depends(require_permission("pos.sell"))):
    product = db.get(Product, product_id)
    if not product:
        raise HTTPException(status_code=404, detail="PRODUCT_NOT_FOUND")
    options = pos_svc.get_batch_options(db, product)
    return {"product_id": product_id, "product_name": product.name,
            "mode": pos_svc.get_setting(db, "pos.batch_selection_mode", "HYBRID"),
            "options": [o.as_dict() for o in options]}


@router.post("/cart/validate")
def validate_cart(body: CartIn, db: Session = Depends(get_db), _: User = Depends(require_permission("pos.sell"))):
    try:
        items = pos_svc.validate_cart(db, [CartItem(product_id=i.product_id, quantity=i.quantity, batch_id=i.batch_id)
                                           for i in body.items])
        return {"items": [_line_out(i) for i in items], "totals": _totals(items)}
    except PosError as e:
        raise HTTPException(status_code=422, detail={"code": e.code, "message": e.message})


@router.post("/checkout", status_code=201)
def checkout(body: CheckoutIn, db: Session = Depends(get_db),
             user: User = Depends(require_permission("pos.sell"))):
    try:
        invoice = pos_svc.checkout(
            db,
            items=[CartItem(product_id=i.product_id, quantity=i.quantity, batch_id=i.batch_id)
                   for i in body.items],
            payments=[p.model_dump() for p in body.payments],
            user=user,
            customer_id=body.customer_id,
            tax_rate=body.tax_rate,
        )
        db.commit()
        return _invoice_out(invoice)
    except PosError as e:
        db.rollback()
        raise HTTPException(status_code=422, detail={"code": e.code, "message": e.message})


def _line_out(i: CartItem) -> dict:
    return {
        "product_id": i.product_id, "product_name": i.product_name,
        "batch_id": i.batch_id, "batch_number": i.batch_number,
        "quantity": i.quantity,
        "unit_buy_price": float(i.unit_buy_price or 0),
        "unit_consumer_price": float(i.unit_consumer_price or 0),
        "unit_sell_price": float(i.unit_sell_price or 0),
        "discount": float(i.discount), "subtotal": float(i.subtotal), "profit": float(i.profit),
        "expiry_date": str(i.expiry_date) if i.expiry_date else None,
        "suggested": i.suggested,
    }


def _totals(items: list[CartItem]) -> dict:
    return {
        "subtotal": float(sum((i.subtotal for i in items), Decimal("0"))),
        "profit": float(sum((i.profit for i in items), Decimal("0"))),
        "count": len(items),
    }


def _invoice_out(inv) -> dict:
    return {
        "invoice_id": inv.id,
        "invoice_number": inv.invoice_number,
        "subtotal": float(inv.subtotal),
        "discount": float(inv.discount),
        "tax": float(inv.tax),
        "total_amount": float(inv.total_amount),
        "payment_method": inv.payment_method,
        "status": inv.status,
        "print_status": inv.print_status,
        "items": [
            {"product_id": it.product_id, "batch_id": it.batch_id, "qty": it.qty,
             "unit_buy_price": float(it.unit_buy_price), "unit_sell_price": float(it.unit_sell_price),
             "subtotal": float(it.subtotal), "profit": float(it.profit)}
            for it in inv.items
        ],
    }
