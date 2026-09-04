from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Category, Product, User
from ..security import get_current_user, require_permission
from ..services import catalog
from ..services.catalog import CatalogError

router = APIRouter(prefix="/products", tags=["products"])


class ProductIn(BaseModel):
    barcode: str
    name: str
    sku: str | None = None
    brand_id: int | None = None
    category_id: int | None = None
    unit_id: int | None = None
    model: str | None = None
    description: str | None = None
    image_url: str | None = None
    min_stock_alert: int = 0


class ProductPatch(BaseModel):
    name: str | None = None
    sku: str | None = None
    brand_id: int | None = None
    category_id: int | None = None
    unit_id: int | None = None
    model: str | None = None
    description: str | None = None
    image_url: str | None = None
    min_stock_alert: int | None = None
    is_active: bool | None = None


def _out(p: Product) -> dict:
    return {
        "id": p.id, "barcode": p.barcode, "name": p.name, "sku": p.sku,
        "brand_id": p.brand_id, "category_id": p.category_id, "unit_id": p.unit_id,
        "model": p.model, "description": p.description, "image_url": p.image_url,
        "min_stock_alert": p.min_stock_alert, "is_active": p.is_active,
        "created_at": p.created_at.isoformat() if p.created_at else None,
    }


@router.get("")
def list_products(
    q: str | None = Query(default=None),
    limit: int = Query(default=100, le=1000),
    offset: int = 0,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("products.view")),
):
    stmt = select(Product).where(Product.deleted_at.is_(None))
    if q:
        stmt = stmt.where(Product.name.ilike(f"%{q}%") | Product.barcode.ilike(f"%{q}%"))
    total = int(db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one())
    rows = db.execute(stmt.order_by(Product.name.asc()).limit(limit).offset(offset)).scalars().all()
    return {"total": total, "items": [_out(p) for p in rows]}


@router.get("/barcode/{barcode}")
def by_barcode(barcode: str, db: Session = Depends(get_db), _: User = Depends(require_permission("products.view"))):
    p = catalog.get_product_by_barcode(db, barcode)
    if not p:
        raise HTTPException(status_code=404, detail="PRODUCT_NOT_FOUND")
    return _out(p)


@router.get("/{product_id}")
def get_product(product_id: int, db: Session = Depends(get_db), _: User = Depends(require_permission("products.view"))):
    p = db.get(Product, product_id)
    if not p or p.deleted_at is not None:
        raise HTTPException(status_code=404, detail="PRODUCT_NOT_FOUND")
    return _out(p)


@router.post("", status_code=201)
def create_product(body: ProductIn, db: Session = Depends(get_db),
                   user: User = Depends(require_permission("products.manage"))):
    try:
        p = catalog.create_product(db, barcode=body.barcode, name=body.name, user=user, **body.model_dump(exclude={"barcode", "name"}))
        db.commit()
        return _out(p)
    except CatalogError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.patch("/{product_id}")
def update_product(product_id: int, body: ProductPatch, db: Session = Depends(get_db),
                   user: User = Depends(require_permission("products.manage"))):
    p = db.get(Product, product_id)
    if not p or p.deleted_at is not None:
        raise HTTPException(status_code=404, detail="PRODUCT_NOT_FOUND")
    catalog.update_product(db, p, user=user, **body.model_dump(exclude_none=True))
    db.commit()
    return _out(p)


@router.delete("/{product_id}", status_code=204)
def delete_product(product_id: int, db: Session = Depends(get_db),
                   user: User = Depends(require_permission("products.manage"))):
    """Soft delete only (data lifecycle rule §144)."""
    p = db.get(Product, product_id)
    if not p or p.deleted_at is not None:
        raise HTTPException(status_code=404, detail="PRODUCT_NOT_FOUND")
    from datetime import datetime
    p.deleted_at = datetime.utcnow()
    p.is_active = False
    db.commit()
