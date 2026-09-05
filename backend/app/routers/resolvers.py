from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import ExternalSource, ProductResolverResult, User
from ..security import get_current_user, require_permission
from ..services import catalog, resolvers
from ..services.barcode import validate as validate_barcode
from ..services.catalog import CatalogError

router = APIRouter(prefix="/barcode", tags=["resolvers"])

# --- Lookup (POST: it persists candidates — a GET must stay side-effect free) --


@router.post("/resolve/{barcode}")
def resolve_barcode(barcode: str, db: Session = Depends(get_db),
                    _: User = Depends(require_permission("products.view"))):
    """Full §9 pipeline. Persists PENDING candidates + commits (BUG-006 fix)."""
    result = resolvers.resolve_barcode(db, barcode)
    db.commit()
    return result


@router.get("/resolve/{barcode}")
def resolve_barcode_readonly(barcode: str, db: Session = Depends(get_db),
                             _: User = Depends(require_permission("products.view"))):
    """Read-only: local/cache hit or the PENDING candidates awaiting review."""
    result = resolvers.resolve_barcode(db, barcode)
    if result["origin"] in ("local", "cache", "invalid"):
        db.rollback()
        return result
    rows = db.execute(
        select(ProductResolverResult).where(ProductResolverResult.barcode == barcode)
    ).scalars().all()
    db.rollback()
    return {
        "origin": "pending_review" if rows else "none",
        "barcode": barcode,
        "need_manual": True,
        "candidates": [
            {"id": r.id, "field": r.field, "value": r.value, "source": r.source_code,
             "confidence": r.confidence, "status": r.status}
            for r in rows
        ],
    }


@router.post("/images/{barcode}")
def resolve_image(barcode: str, product_id: int | None = None, db: Session = Depends(get_db),
                  _: User = Depends(require_permission("products.view"))):
    out = resolvers.resolve_image(db, barcode, product_id=product_id)
    db.commit()
    return out


@router.post("/prices/{barcode}")
def resolve_market_price(barcode: str, product_id: int | None = None, db: Session = Depends(get_db),
                         _: User = Depends(require_permission("pricing.view_cost"))):
    out = resolvers.resolve_market_price(db, barcode, product_id=product_id)
    db.commit()
    return out


# --- External source management (BUG-008: configurable providers) --------------

PROVIDERS = [
    {"code": "openfoodfacts", "name": "OpenFoodFacts (public, keyless)", "returns": ["product", "image"],
     "base_url": "https://world.openfoodfacts.org/api/v2/product/{barcode}.json"},
    {"code": "custom_http", "name": "Generic HTTP JSON (configurable template)", "returns": ["product", "image", "price"]},
]


class SourceIn(BaseModel):
    code: str = Field(description="provider code, e.g. openfoodfacts or custom_http")
    name: str
    source_type: str = Field(description="PRODUCT | IMAGE | PRICE")
    base_url: str | None = None
    api_key: str | None = None
    connection: str | None = Field(default=None, description='JSON field mapping, e.g. {"name":"data.title"}')
    priority: int = 100
    is_active: bool = True


class SourcePatch(BaseModel):
    name: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    connection: str | None = None
    priority: int | None = None
    is_active: bool | None = None


def _source_out(s: ExternalSource) -> dict:
    return {"id": s.id, "code": s.code, "name": s.name, "source_type": s.source_type,
            "base_url": s.base_url, "has_api_key": bool(s.api_key),
            "connection": s.connection, "priority": s.priority, "is_active": s.is_active}


@router.get("/sources/providers")
def list_providers(_: User = Depends(require_permission("products.view"))):
    """Available provider implementations registered in the core."""
    return PROVIDERS


@router.get("/sources")
def list_sources(db: Session = Depends(get_db), _: User = Depends(require_permission("products.view"))):
    return [_source_out(s) for s in db.execute(select(ExternalSource).order_by(ExternalSource.priority)).scalars()]


@router.post("/sources", status_code=201)
def create_source(body: SourceIn, db: Session = Depends(get_db),
                  _: User = Depends(require_permission("settings.manage"))):
    prefix = body.code.split(":", 1)[0]
    if prefix not in {p["code"] for p in PROVIDERS}:
        raise HTTPException(status_code=400, detail=f"Unknown provider code: {body.code}")
    if body.source_type not in ("PRODUCT", "IMAGE", "PRICE"):
        raise HTTPException(status_code=400, detail="source_type must be PRODUCT | IMAGE | PRICE")
    if db.execute(select(ExternalSource).where(ExternalSource.code == body.code)).scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Source code already exists")
    s = ExternalSource(code=body.code, name=body.name, source_type=body.source_type,
                       base_url=body.base_url, api_key=body.api_key, connection=body.connection,
                       priority=body.priority, is_active=body.is_active)
    db.add(s)
    db.commit()
    return _source_out(s)


@router.patch("/sources/{source_id}")
def update_source(source_id: int, body: SourcePatch, db: Session = Depends(get_db),
                  _: User = Depends(require_permission("settings.manage"))):
    s = db.get(ExternalSource, source_id)
    if not s:
        raise HTTPException(status_code=404, detail="SOURCE_NOT_FOUND")
    for f, v in body.model_dump(exclude_none=True).items():
        setattr(s, f, v)
    db.commit()
    return _source_out(s)


@router.delete("/sources/{source_id}", status_code=204)
def delete_source(source_id: int, db: Session = Depends(get_db),
                  _: User = Depends(require_permission("settings.manage"))):
    s = db.get(ExternalSource, source_id)
    if not s:
        raise HTTPException(status_code=404, detail="SOURCE_NOT_FOUND")
    db.delete(s)
    db.commit()


# --- Human review workflow (§9: candidates -> review -> apply) ------------------

class ReviewDecision(BaseModel):
    approved: bool
    reason: str | None = None


@router.post("/results/{result_id}/review")
def review_result(result_id: int, body: ReviewDecision, db: Session = Depends(get_db),
                  user: User = Depends(require_permission("products.manage"))):
    row = db.get(ProductResolverResult, result_id)
    if not row:
        raise HTTPException(status_code=404, detail="RESULT_NOT_FOUND")
    if row.status != "PENDING":
        raise HTTPException(status_code=409, detail=f"Result already {row.status}")
    row.status = "APPROVED" if body.approved else "REJECTED"
    from ..services.audit import write_audit
    write_audit(db, action="RESOLVER_REVIEWED", user_id=user.id,
                entity_type="ProductResolverResult", entity_id=row.id,
                after={"decision": row.status, "field": row.field}, reference=body.reason)
    db.commit()
    return {"id": row.id, "status": row.status}


class ApplyIn(BaseModel):
    """Human-approved product creation from resolver candidates (§12 Auto-Fill)."""

    barcode: str
    name: str
    sku: str | None = None
    brand: str | None = None
    category: str | None = None
    unit: str | None = None
    model: str | None = None
    description: str | None = None
    image_url: str | None = None
    min_stock_alert: int = 0
    review_ids: list[int] = Field(default_factory=list)


@router.post("/apply", status_code=201)
def apply_resolved(body: ApplyIn, db: Session = Depends(get_db),
                   user: User = Depends(require_permission("products.manage"))):
    """Create the product from (edited) resolver data after human review."""
    ok, _ = validate_barcode(body.barcode)
    if not ok:
        raise HTTPException(status_code=422, detail={"code": "INVALID_BARCODE",
                                                     "message": "بارکد checksum نامعتبر است"})
    brand_id = _resolve_simple(db, "Brand", body.brand)
    category_id = _resolve_simple(db, "Category", body.category)
    unit_id = _resolve_simple(db, "Unit", body.unit)
    try:
        product = catalog.create_product(
            db, barcode=body.barcode, name=body.name, user=user,
            sku=body.sku, brand_id=brand_id, category_id=category_id, unit_id=unit_id,
            model=body.model, description=body.description, image_url=body.image_url,
            min_stock_alert=body.min_stock_alert,
        )
    except CatalogError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    for rid in body.review_ids:
        row = db.get(ProductResolverResult, rid)
        if row and row.barcode == body.barcode:
            row.status = "APPROVED"
            row.product_id = product.id
    db.commit()
    return {"product": resolvers._product_dict(product)}


def _resolve_simple(db: Session, model_name: str, value: str | None) -> int | None:
    if not value or not value.strip():
        return None
    from .. import models as m
    model = getattr(m, model_name)
    row = db.execute(select(model).where(model.name == value.strip())).scalar_one_or_none()
    if row is None:
        row = model(name=value.strip())
        db.add(row)
        db.flush()
    return row.id
