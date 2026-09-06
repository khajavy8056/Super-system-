from __future__ import annotations

from typing import Annotated

from decimal import Decimal

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Category, Product, User
from ..security import get_current_user, require_permission
from ..services import catalog
from ..services.audit import write_audit
from ..services.catalog import CatalogError

router = APIRouter(prefix="/products", tags=["products"])


class ProductIn(BaseModel):
    # §16: optional — a loose/bulk item gets an internal INT- code minted.
    barcode: str | None = None
    name: str
    sku: str | None = None
    brand_id: int | None = None
    category_id: int | None = None
    unit_id: int | None = None
    model: str | None = None
    description: str | None = None
    image_url: str | None = None
    min_stock_alert: int = 0
    has_own_barcode: bool = True


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
        "has_own_barcode": bool(getattr(p, "has_own_barcode", True)),
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


# --- Brands & Categories -----------------------------------------------------
# Products carry brand_id/category_id, but until now there was no way to create
# one, so those columns could only ever be null. §18 needs brand search to have
# something to search. Routes are declared before "/{product_id}" would be
# reached for these literals — FastAPI matches in declaration order, and both
# live under distinct prefixes, so no shadowing occurs.

class TaxonomyIn(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    #: §79 — sub-category: id of the parent category (categories only)
    parent_id: int | None = None


@router.get("/brands")
def list_brands(q: str | None = Query(default=None), db: Session = Depends(get_db),
                _: User = Depends(require_permission("products.view"))):
    from ..models import Brand
    stmt = select(Brand)
    if q:
        stmt = stmt.where(Brand.name.ilike(f"%{q}%"))
    rows = db.execute(stmt.order_by(Brand.name.asc())).scalars().all()
    return [{"id": b.id, "name": b.name} for b in rows]


@router.post("/brands", status_code=201)
def create_brand(body: TaxonomyIn, db: Session = Depends(get_db),
                 user: User = Depends(require_permission("products.manage"))):
    from ..models import Brand
    name = body.name.strip()
    existing = db.execute(
        select(Brand).where(func.lower(Brand.name) == name.lower())
    ).scalar_one_or_none()
    if existing:
        # Idempotent: re-sending the same brand returns it rather than
        # littering the catalogue with near-identical rows.
        return {"id": existing.id, "name": existing.name}
    b = Brand(name=name)
    db.add(b)
    db.commit()
    db.refresh(b)
    return {"id": b.id, "name": b.name}


@router.get("/categories")
def list_categories(q: str | None = Query(default=None), db: Session = Depends(get_db),
                    _: User = Depends(require_permission("products.view"))):
    from ..models import Category
    stmt = select(Category)
    if q:
        stmt = stmt.where(Category.name.ilike(f"%{q}%"))
    rows = db.execute(stmt.order_by(Category.name.asc())).scalars().all()
    names = {c.id: c.name for c in rows}
    return [{"id": c.id, "name": c.name, "parent_id": c.parent_id,
             "parent_name": names.get(c.parent_id) if c.parent_id else None,
             "path": (f"{names.get(c.parent_id)} / {c.name}" if c.parent_id and names.get(c.parent_id) else c.name)}
            for c in rows]


@router.post("/categories", status_code=201)
def create_category(body: TaxonomyIn, db: Session = Depends(get_db),
                    user: User = Depends(require_permission("products.manage"))):
    from ..models import Category
    name = body.name.strip()
    if body.parent_id is not None and db.get(Category, body.parent_id) is None:
        raise HTTPException(status_code=404, detail="PARENT_CATEGORY_NOT_FOUND")
    existing = db.execute(
        select(Category).where(func.lower(Category.name) == name.lower(),
                               Category.parent_id.is_(body.parent_id) if body.parent_id is None
                               else Category.parent_id == body.parent_id)
    ).scalar_one_or_none()
    if existing:
        return {"id": existing.id, "name": existing.name, "parent_id": existing.parent_id}
    c = Category(name=name, parent_id=body.parent_id)
    db.add(c)
    db.commit()
    db.refresh(c)
    return {"id": c.id, "name": c.name, "parent_id": c.parent_id}


# NOTE: declared AFTER the static /brands and /categories routes; FastAPI matches
# in declaration order and '/{product_id}' used to swallow them (BUG: 422 on GET
# /products/categories).
# --- §80–82 starter catalog / CSV import (declared before /{product_id}) ---------
@router.get("/import/starter")
def starter_catalog_info(_: User = Depends(require_permission("products.manage"))):
    """Describe the bundled zero-stock starter catalog and the CSV columns."""
    from ..services import starter_catalog
    return starter_catalog.bundled_summary()


@router.post("/import/starter")
def import_starter_catalog(dry_run: bool = False, db: Session = Depends(get_db),
                           user: User = Depends(require_permission("products.manage"))):
    """Import the bundled starter catalog (idempotent, zero stock)."""
    from ..services import starter_catalog
    from ..services.audit import write_audit
    res = starter_catalog.import_csv(db, None, user=user, dry_run=dry_run)
    if not dry_run and res.get("ok"):
        write_audit(db, action="CATALOG_IMPORT", user_id=user.id, entity_type="Product",
                    after={"source": "bundled", "created": res["created"], "skipped": res["skipped"]})
    db.commit()
    return res


@router.post("/import/csv")
async def import_products_csv(file: UploadFile = File(...), dry_run: bool = False,
                              db: Session = Depends(get_db),
                              user: User = Depends(require_permission("products.manage"))):
    """Import the shop's own product list (UTF-8 CSV, columns: category, subcategory,
    name, brand, unit, min_stock_alert, barcode). Stock stays zero."""
    from ..services import starter_catalog
    from ..services.audit import write_audit
    raw = await file.read()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail={"code": "BAD_ENCODING",
                                                     "message": "فایل باید UTF-8 باشد."})
    res = starter_catalog.import_csv(db, text, user=user, dry_run=dry_run)
    if not res.get("ok"):
        raise HTTPException(status_code=400, detail=res)
    if not dry_run:
        write_audit(db, action="CATALOG_IMPORT", user_id=user.id, entity_type="Product",
                    after={"source": file.filename, "created": res["created"], "skipped": res["skipped"]})
    db.commit()
    return res


@router.get("/{product_id}")
def get_product(product_id: int, db: Session = Depends(get_db), _: User = Depends(require_permission("products.view"))):
    p = db.get(Product, product_id)
    if not p or p.deleted_at is not None:
        raise HTTPException(status_code=404, detail="PRODUCT_NOT_FOUND")
    return _out(p)


class DuplicateCheckIn(BaseModel):
    name: str
    barcode: str | None = None
    brand_id: int | None = None
    model: str | None = None
    unit_id: int | None = None


@router.post("/check-duplicate")
def check_duplicate(body: DuplicateCheckIn, db: Session = Depends(get_db),
                    _: User = Depends(require_permission("products.view"))):
    """§33 — warn before creating what may be an existing product.

    Advisory only: barcode equality is the sole hard identity rule (§32), so
    this never blocks or auto-merges. An exact barcode hit is reported
    separately from fuzzy name matches because the two mean different things.
    """
    exact = None
    if body.barcode and body.barcode.strip():
        hit = catalog.get_product_by_barcode(db, body.barcode.strip())
        if hit:
            exact = _out(hit)

    candidates = catalog.find_possible_duplicates(
        db, name=body.name, brand_id=body.brand_id, model=body.model,
        unit_id=body.unit_id)
    return {"exact_barcode_match": exact, "possible_duplicates": candidates,
            "has_warning": bool(exact or candidates)}


@router.get("/{product_id}/detail")
def product_detail(product_id: int, db: Session = Depends(get_db),
                   _: User = Depends(require_permission("products.view"))):
    """§5 — the product header plus every batch that ever belonged to it.

    Depleted batches are returned too (``current_qty == 0``): they are the
    product's purchase-price history and deleting them would erase the margin
    record. The caller decides how to present active vs historical.
    """
    from ..models import ProductBatch

    p = db.get(Product, product_id)
    if not p or p.deleted_at is not None:
        raise HTTPException(status_code=404, detail="PRODUCT_NOT_FOUND")

    rows = db.execute(
        select(ProductBatch).where(ProductBatch.product_id == product_id)
        .order_by(ProductBatch.received_at.desc(), ProductBatch.id.desc())
    ).scalars().all()

    def _b(b) -> dict:
        return {
            "id": b.id, "batch_number": b.batch_number,
            "quantity_received": float(b.quantity_received),
            "current_qty": float(b.current_qty),
            "buy_price": float(b.buy_price),
            "supplier_price": float(b.supplier_price) if b.supplier_price is not None else None,
            "consumer_price": float(b.consumer_price),
            "sell_price": float(b.sell_price),
            "discount": float(b.discount or 0), "tax": float(b.tax or 0),
            "production_date": str(b.production_date) if b.production_date else None,
            "expiry_date": str(b.expiry_date) if b.expiry_date else None,
            "received_at": b.received_at.isoformat() if b.received_at else None,
            "status": b.status, "note": b.note,
            "is_depleted": float(b.current_qty) <= 0,
        }

    batches = [_b(b) for b in rows]
    active = [b for b in batches if not b["is_depleted"]]
    return {
        "product": _out(p),
        "total_stock": sum(b["current_qty"] for b in active),
        "active_batches": active,
        "depleted_batches": [b for b in batches if b["is_depleted"]],
        "batch_count": len(batches),
    }


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
    """Soft delete only (data lifecycle rule §144).

    §43 requires PRODUCT_DELETED in the audit trail. It was silently absent:
    a product could vanish from the catalogue with no record of who removed
    it, while every other destructive action in the system was logged.
    """
    p = db.get(Product, product_id)
    if not p or p.deleted_at is not None:
        raise HTTPException(status_code=404, detail="PRODUCT_NOT_FOUND")
    from datetime import datetime
    snapshot = {"barcode": p.barcode, "name": p.name, "is_active": p.is_active}
    p.deleted_at = datetime.utcnow()
    p.is_active = False
    write_audit(db, action="PRODUCT_DELETED", user_id=user.id, entity_type="Product",
                entity_id=p.id, before=snapshot,
                after={"deleted_at": p.deleted_at.isoformat()})
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
