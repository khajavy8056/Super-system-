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
from ..services import catalog, product_images
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
        from ..services import product_bank as _bank
        _bank.remember_product(db, p, source="USER")  # v2.7 — the shop's own products teach the bank
        if not p.image_url:
            product_images.enqueue(db, p.id, user_id=user.id)   # v2.5: picture found in the background
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
    if not p.image_url:
        product_images.enqueue(db, p.id, user_id=user.id)
    from ..services import product_bank as _bank
    _bank.remember_product(db, p, source="USER")  # v2.7
    db.commit()
    return _out(p)


# --- v2.5 automatic product pictures --------------------------------------------

@router.post("/{product_id}/image/find")
def find_image_now(product_id: int, force: bool = False, db: Session = Depends(get_db),
                   user: User = Depends(require_permission("products.manage"))):
    """Look the picture up right now (blocking, ≤ ~30 s) — used by the «یافتن تصویر» button."""
    p = db.get(Product, product_id)
    if not p or p.deleted_at is not None:
        raise HTTPException(status_code=404, detail="PRODUCT_NOT_FOUND")
    rep = product_images.find_and_store(db, p, force=force)
    db.commit()
    rep["image_url"] = p.image_url
    return rep


@router.get("/{product_id}/image/candidates")
def image_candidates(product_id: int, db: Session = Depends(get_db), user: User = Depends(require_permission("products.manage"))):
    """v2.5.1 — picker: top candidate pictures (retail catalogues first) so the operator chooses the right pack photo."""
    p = db.get(Product, product_id)
    if not p or p.deleted_at is not None:
        raise HTTPException(status_code=404, detail="PRODUCT_NOT_FOUND")
    return {"product_id": p.id, "name": p.name, "current": p.image_url, "candidates": product_images.list_candidates(db, p)}


class _PickBody(BaseModel):
    url: str
    source: str = "picked"


@router.post("/{product_id}/image/pick")
def image_pick(product_id: int, body: _PickBody, db: Session = Depends(get_db), user: User = Depends(require_permission("products.manage"))):
    p = db.get(Product, product_id)
    if not p or p.deleted_at is not None:
        raise HTTPException(status_code=404, detail="PRODUCT_NOT_FOUND")
    rep = product_images.set_image_from_url(db, p, body.url, source=body.source)
    if not rep.get("ok"):
        raise HTTPException(status_code=400, detail=rep.get("reason", "INVALID_IMAGE"))
    db.commit()
    return rep


@router.post("/{product_id}/image/upload")
async def image_upload(product_id: int, file: UploadFile = File(...), db: Session = Depends(get_db),
                       user: User = Depends(require_permission("products.manage"))):
    """Own photo (camera/gallery/file) — the final guarantee that the thumbnail is the real product."""
    p = db.get(Product, product_id)
    if not p or p.deleted_at is not None:
        raise HTTPException(status_code=404, detail="PRODUCT_NOT_FOUND")
    buf = await file.read()
    rep = product_images.set_image_from_bytes(db, p, buf, source="upload")
    if not rep.get("ok"):
        raise HTTPException(status_code=400, detail=rep.get("reason", "INVALID_IMAGE"))
    db.commit()
    return rep


@router.post("/images/backfill")
def backfill_images(limit: int = 500, db: Session = Depends(get_db),
                    user: User = Depends(require_permission("products.manage"))):
    """Queue a background picture lookup for every product that has none (starter catalogue etc.)."""
    rep = product_images.backfill(db, limit=limit, user_id=user.id)
    db.commit()
    rep["missing"] = product_images.missing_count(db)
    return rep


@router.get("/images/status")
def images_status(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    from sqlalchemy import func as _f
    from ..models import SyncJob
    q = db.execute(select(SyncJob.status, _f.count(SyncJob.id)).where(SyncJob.job_type == "PRODUCT_IMAGE").group_by(SyncJob.status)).all()
    total = db.execute(select(_f.count(Product.id)).where(Product.deleted_at.is_(None), Product.is_active.is_(True))).scalar() or 0
    missing = product_images.missing_count(db)
    return {"total": total, "with_image": total - missing, "missing": missing, "jobs": {s: n for s, n in q},
            "auto_find": product_images.setting(db, "images.auto_find", "true") == "true",
            "web_fallback": product_images.setting(db, "images.web_fallback", "true") == "true"}


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


# ---------------------------------------------------------------------------
# v2.7 — بانک کالا (offline barcode → name/brand bank)
# ---------------------------------------------------------------------------
from fastapi.responses import Response  # noqa: E402
from ..services import product_bank as bank_svc  # noqa: E402

bank_router = APIRouter(prefix="/bank", tags=["bank"])


@bank_router.get("/stats")
def bank_stats(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    return bank_svc.stats(db)


@bank_router.get("/lookup/{barcode}")
def bank_lookup(barcode: str, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    row = bank_svc.lookup(db, barcode)
    if row is None:
        raise HTTPException(status_code=404, detail="BANK_MISS")
    return row


class BankRememberIn(BaseModel):
    barcode: str
    name: str
    brand: str | None = None
    unit: str | None = None
    category: str | None = None
    image_url: str | None = None


@bank_router.post("/remember")
def bank_remember(body: BankRememberIn, db: Session = Depends(get_db), user: User = Depends(require_permission("products.manage"))):
    res = bank_svc.remember(db, body.barcode, body.name, brand=body.brand, unit=body.unit, category=body.category,
                            image_url=body.image_url, source="USER")
    if res is None:
        raise HTTPException(status_code=400, detail="بارکد یا نام معتبر نیست")
    db.commit()
    return res


@bank_router.post("/import")
async def bank_import(file: UploadFile = File(...), db: Session = Depends(get_db), user: User = Depends(require_permission("products.manage"))):
    """Import a barcode→name list (CSV/TSV/TXT or Excel .xlsx). Columns may be Persian or English;
    only «بارکد» and «نام» are required. Rows never overwrite what the shop itself confirmed."""
    data = await file.read()
    name = (file.filename or "").lower()
    if name.endswith((".xlsx", ".xlsm")) or data[:2] == b"PK":
        res = bank_svc.import_xlsx_bytes(db, data, source="IMPORT")
    else:
        text = None
        for enc in ("utf-8-sig", "utf-16", "cp1256"):
            try:
                text = data.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        if text is None:
            raise HTTPException(status_code=400, detail="فایل قابل خواندن نیست")
        res = bank_svc.import_csv_text(db, text, source="IMPORT")
    if res.get("error"):
        raise HTTPException(status_code=400, detail=res)
    db.commit()
    write_audit(db, action="BANK_IMPORT", user_id=user.id, entity_type="ProductBank", after=res)
    db.commit()
    return res


@bank_router.get("/export.csv")
def bank_export(db: Session = Depends(get_db), _: User = Depends(require_permission("products.manage"))):
    return Response(content="\ufeff" + bank_svc.export_csv(db), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": "attachment; filename=product-bank.csv"})


@bank_router.post("/seed-from-products")
def bank_seed(db: Session = Depends(get_db), _: User = Depends(require_permission("products.manage"))):
    n = bank_svc.seed_from_products(db)
    db.commit()
    return {"added": n, **bank_svc.stats(db)}


# ---------------------------------------------------------------------------
# v3.4 — «بانک محصولات» از پوشه (the shop's own Excel + pictures) and catalog.pack for phones
# ---------------------------------------------------------------------------
import threading as _th  # noqa: E402
from pathlib import Path as _P  # noqa: E402

from fastapi.responses import FileResponse  # noqa: E402

from ..services import catalog_folder  # noqa: E402

catalog_router = APIRouter(prefix="/catalog", tags=["catalog"])
_JOB: dict = {"running": False, "done": 0, "total": 0, "current": "", "result": None, "error": None, "started": None}
_LOCK = _th.Lock()


class FolderIn(BaseModel):
    root: str | None = None
    replace_images: bool = False


@catalog_router.get("/folder")
def catalog_folder_status(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    root = catalog_folder.default_root()
    root.mkdir(parents=True, exist_ok=True)
    pk = catalog_folder.pack_path()
    return {"root": str(root), "exists": root.is_dir(), "last": catalog_folder.last_state(db), "job": {k: v for k, v in _JOB.items() if k != "result"},
            "result": _JOB.get("result"), "pack": {"exists": pk.is_file(), "bytes": pk.stat().st_size if pk.is_file() else 0,
                                                    "at": __import__("datetime").datetime.fromtimestamp(pk.stat().st_mtime).isoformat(timespec="seconds") if pk.is_file() else None}}


@catalog_router.post("/folder/scan")
def catalog_folder_scan(body: FolderIn | None = None, _: User = Depends(require_permission("products.manage"))):
    """Dry run: what would be imported (sheets, rows, pictures found / missing)."""
    root = _P(body.root) if body and body.root else catalog_folder.default_root()
    res = catalog_folder.scan(root)
    res.pop("_rows", None)
    if res.get("error"):
        raise HTTPException(status_code=400, detail=res["error"])
    return res


@catalog_router.post("/folder/import")
def catalog_folder_import(body: FolderIn | None = None, user: User = Depends(require_permission("products.manage"))):
    """Start the import in the background (thousands of rows + pictures); poll GET /catalog/folder."""
    with _LOCK:
        if _JOB["running"]:
            return {"started": False, "reason": "RUNNING", **{k: v for k, v in _JOB.items() if k != "result"}}
        _JOB.update({"running": True, "done": 0, "total": 0, "current": "", "result": None, "error": None, "started": __import__("time").time()})
    root = _P(body.root) if body and body.root else catalog_folder.default_root()
    replace = bool(body and body.replace_images)
    uid = user.id

    def _run():
        from ..database import SessionLocal
        try:
            with SessionLocal() as s:
                def prog(done, total, cur):
                    _JOB.update({"done": done, "total": total, "current": cur})
                res = catalog_folder.import_folder(s, root, replace_images=replace, progress=prog, user_id=uid)
                if res.get("error"):
                    _JOB["error"] = res["error"]
                else:
                    try:
                        pk = catalog_folder.export_pack(s, catalog_folder.pack_path())
                        res["pack"] = pk
                    except Exception as exc:  # pragma: no cover
                        res["pack_error"] = str(exc)
                    write_audit(s, action="CATALOG_FOLDER_IMPORT", user_id=uid, entity_type="Catalog", after={k: v for k, v in res.items() if k != "missing"})
                    s.commit()
                _JOB["result"] = res
        except Exception as exc:  # never leave the job stuck
            _JOB["error"] = str(exc)
        finally:
            _JOB["running"] = False

    _th.Thread(target=_run, name="catalog-import", daemon=True).start()
    return {"started": True, "root": str(root)}


@catalog_router.post("/pack/build")
def catalog_pack_build(db: Session = Depends(get_db), _: User = Depends(require_permission("products.manage"))):
    """(Re)build catalog.pack from the current products + stored pictures."""
    return catalog_folder.export_pack(db, catalog_folder.pack_path())


@catalog_router.get("/pack")
def catalog_pack_download(_: User = Depends(get_current_user)):
    """The phone (or the operator, to copy it onto a phone) downloads the pack. Paired phones use this on the LAN."""
    pk = catalog_folder.pack_path()
    if not pk.is_file():
        raise HTTPException(status_code=404, detail="بستهٔ کاتالوگ هنوز ساخته نشده — ابتدا «وارد کردن از پوشه» را اجرا کنید")
    return FileResponse(str(pk), media_type="application/octet-stream", filename="catalog.pack")


@catalog_router.get("/pack/info")
def catalog_pack_info(_: User = Depends(get_current_user)):
    pk = catalog_folder.pack_path()
    if not pk.is_file():
        return {"exists": False}
    idx = catalog_folder.read_pack_index(pk)
    import sqlite3 as _s, tempfile as _t
    with _t.NamedTemporaryFile(suffix=".db", delete=False) as f:
        f.write(idx["db"]); tmp = f.name
    try:
        con = _s.connect(tmp)
        meta = dict(con.execute("SELECT k, v FROM meta").fetchall())
        con.close()
    finally:
        _P(tmp).unlink(missing_ok=True)
    return {"exists": True, **meta, "bytes": pk.stat().st_size, "images": len(idx["index"]), "items": int(meta.get("items", 0) or 0)}


@catalog_router.post("/folder/open")
def catalog_folder_open(_: User = Depends(require_permission("products.manage"))):
    """Open the catalogue folder in the OS file manager (desktop install only)."""
    import subprocess, sys
    root = catalog_folder.default_root()
    root.mkdir(parents=True, exist_ok=True)
    try:
        if sys.platform.startswith("win"):
            subprocess.Popen(["explorer", str(root)])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(root)])
        else:
            subprocess.Popen(["xdg-open", str(root)])
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"ok": True, "root": str(root)}
