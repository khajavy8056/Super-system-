from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Product, ProductBatch, PriceVersion, User
from ..security import get_current_user, require_permission
from ..services import pricing
from ..services.pricing import PricingError

router = APIRouter(prefix="/prices", tags=["pricing"])


class SetPriceIn(BaseModel):
    product_id: int
    price_type: str = "SELL"
    price: Decimal = Field(ge=0)
    source: str | None = None
    note: str | None = None


class SuggestIn(BaseModel):
    product_id: int
    target_margin: Decimal = Field(default=Decimal("20"), ge=0)


@router.post("", status_code=201)
def set_price(body: SetPriceIn, db: Session = Depends(get_db),
              user: User = Depends(require_permission("pricing.manage"))):
    product = db.get(Product, body.product_id)
    if not product:
        raise HTTPException(status_code=404, detail="PRODUCT_NOT_FOUND")
    try:
        v = pricing.set_price(db, product=product, price_type=body.price_type,
                              price=body.price, user=user, source=body.source, note=body.note)
        db.commit()
        return {"id": v.id, "price": float(v.price), "price_type": v.price_type,
                "effective_from": v.effective_from.isoformat(), "is_active": v.is_active}
    except PricingError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/history/{product_id}")
def history(product_id: int, db: Session = Depends(get_db), _: User = Depends(require_permission("products.view"))):
    from ..services.reports import price_history
    return price_history(db, product_id)


@router.get("/active/{product_id}")
def active(product_id: int, db: Session = Depends(get_db), _: User = Depends(require_permission("products.view"))):
    return {"SELL": float(pricing.active_price(db, product_id, "SELL") or 0),
            "CONSUMER": float(pricing.active_price(db, product_id, "CONSUMER") or 0)}


@router.post("/suggest")
def suggest(body: SuggestIn, db: Session = Depends(get_db),
            user: User = Depends(require_permission("pricing.view_cost"))):
    batch = db.execute(
        select(ProductBatch).where(ProductBatch.product_id == body.product_id, ProductBatch.current_qty > 0)
        .order_by(ProductBatch.received_at.desc()).limit(1)
    ).scalars().all()
    if not batch:
        raise HTTPException(status_code=404, detail="No active batch for this product")
    return pricing.suggest_sell_price(db, buy_cost=batch[0].buy_price,
                                      target_margin=body.target_margin, product_id=body.product_id)


@router.get("/market/{product_id}")
def market(product_id: int, db: Session = Depends(get_db), _: User = Depends(require_permission("pricing.view_cost"))):
    return pricing.market_aggregate(db, product_id=product_id) or {}
