from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import User
from ..security import get_current_user, require_permission
from ..services import resolvers

router = APIRouter(prefix="/barcode", tags=["resolvers"])


@router.get("/resolve/{barcode}")
def resolve_barcode(barcode: str, db: Session = Depends(get_db),
                    _: User = Depends(require_permission("products.view"))):
    return resolvers.resolve_barcode(db, barcode)


@router.get("/images/{barcode}")
def resolve_image(barcode: str, product_id: int | None = None, db: Session = Depends(get_db),
                  _: User = Depends(require_permission("products.view"))):
    return resolvers.resolve_image(db, barcode, product_id=product_id)


@router.get("/prices/{barcode}")
def resolve_market_price(barcode: str, product_id: int | None = None, db: Session = Depends(get_db),
                         _: User = Depends(require_permission("pricing.view_cost"))):
    return resolvers.resolve_market_price(db, barcode, product_id=product_id)
