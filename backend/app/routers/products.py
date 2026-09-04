from __future__ import annotations

from typing import Annotated

from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
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


# --- Units (§25) ---------------------------------------------------------------

from ..models import Unit  # noqa: E402
from ..services import units as units_svc  # noqa: E402

unit_router = APIRouter(prefix="/units", tags=["units"])


class UnitIn(BaseModel):
    name: str
    symbol: str | None = None
    allow_decimal: bool = False
    decimals: int = 0


def _unit_out(u: Unit) -> dict:
    return {"id": u.id, "name": u.name, "symbol": u.symbol,
            "allow_decimal": u.allow_decimal, "decimals": u.decimals,
            "is_active": u.is_active}


@unit_router.get("")
def list_units(db: Session = Depends(get_db), _: User = Depends(require_permission("products.view"))):
    units_svc.ensure_units(db)
    db.commit()
    rows = db.execute(select(Unit).where(Unit.is_active.is_(True)).order_by(Unit.id)).scalars()
    return [_unit_out(u) for u in rows]


@unit_router.post("", status_code=201)
def create_unit(body: UnitIn, db: Session = Depends(get_db),
                _: User = Depends(require_permission("products.manage"))):
    existing = db.execute(select(Unit).where(Unit.name == body.name)).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=409, detail="UNIT_EXISTS")
    u = Unit(**body.model_dump())
    db.add(u)
    db.commit()
    return _unit_out(u)


# --- Quick price edit (§23) ----------------------------------------------------

class QuickPriceIn(BaseModel):
    sell_price: Decimal | None = Field(default=None, ge=0)
    consumer_price: Decimal | None = Field(default=None, ge=0)
    buy_price: Decimal | None = Field(default=None, ge=0)
    batch_id: int | None = None
    apply_to_all_batches: bool = False


@router.post("/{product_id}/quick-price")
def quick_price(product_id: int, body: QuickPriceIn, db: Session = Depends(get_db),
                user: User = Depends(require_permission("pricing.manage"))):
    """One-call price edit from the inventory list — no multi-page workflow.

    Buy price is only editable on a batch that has not yet been consumed
    (costing integrity, §24): once units of a batch are sold, its purchase cost
    is historical evidence and must not change.
    """
    from ..models import ProductBatch
    from ..services.audit import write_audit

    p = db.get(Product, product_id)
    if not p or p.deleted_at is not None:
        raise HTTPException(status_code=404, detail="PRODUCT_NOT_FOUND")

    stmt = select(ProductBatch).where(ProductBatch.product_id == product_id)
    if body.batch_id:
        stmt = stmt.where(ProductBatch.id == body.batch_id)
    elif not body.apply_to_all_batches:
        stmt = stmt.where(ProductBatch.current_qty > 0).order_by(ProductBatch.id.desc()).limit(1)
    batches = list(db.execute(stmt).scalars())
    if not batches:
        raise HTTPException(status_code=404, detail="NO_BATCH_TO_PRICE")

    changed = []
    for b in batches:
        before = {"sell": float(b.sell_price), "consumer": float(b.consumer_price),
                  "buy": float(b.buy_price)}
        if body.sell_price is not None:
            b.sell_price = body.sell_price
        if body.consumer_price is not None:
            b.consumer_price = body.consumer_price
        if body.buy_price is not None:
            consumed = (b.quantity_received or 0) - (b.current_qty or 0)
            if consumed > 0:
                raise HTTPException(status_code=409, detail={
                    "code": "BUY_PRICE_LOCKED",
                    "message": f"بچ {b.batch_number} مصرف شده است؛ قیمت خرید قابل تغییر نیست"})
            b.buy_price = body.buy_price
        changed.append({"batch_id": b.id, "before": before,
                        "after": {"sell": float(b.sell_price),
                                  "consumer": float(b.consumer_price),
                                  "buy": float(b.buy_price)}})

    write_audit(db, action="QUICK_PRICE_EDIT", user_id=user.id, entity_type="Product",
                entity_id=product_id, after={"batches": changed})
    db.commit()
    return {"product_id": product_id, "updated": changed}
