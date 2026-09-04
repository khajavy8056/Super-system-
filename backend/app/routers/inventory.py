from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Product, ProductBatch, Stocktake, StocktakeItem, User
from ..security import get_current_user, require_permission
from ..services import inventory as inv
from ..services.inventory import InventoryError

router = APIRouter(prefix="/inventory", tags=["inventory"])


class AdjustIn(BaseModel):
    batch_id: int
    new_current_qty: int = Field(ge=0)
    reason: str | None = None


class StocktakeIn(BaseModel):
    name: str
    area: str | None = None
    product_ids: list[int] | None = None
    batch_ids: list[int] | None = None
    include_zero: bool = True  # snapshot believed-empty batches too (BUG-018)


class CountIn(BaseModel):
    item_id: int
    physical_qty: int = Field(ge=0)
    reason: str | None = None


@router.get("/stock")
def stock_summary(db: Session = Depends(get_db), _: User = Depends(require_permission("inventory.view"))):
    products = db.execute(select(Product).where(Product.deleted_at.is_(None))).scalars().all()
    batches = db.execute(select(ProductBatch)).scalars().all()
    out = []
    for p in products:
        total = sum(b.current_qty for b in batches if b.product_id == p.id)
        if total > 0 or True:
            out.append({
                "product_id": p.id, "name": p.name, "barcode": p.barcode,
                "total_stock": total, "min_stock_alert": p.min_stock_alert,
                "batches": [{"batch_id": b.id, "batch_number": b.batch_number,
                             "current_qty": b.current_qty, "status": b.status,
                             "expiry_date": str(b.expiry_date) if b.expiry_date else None}
                            for b in batches if b.product_id == p.id],
            })
    return out


@router.post("/adjust")
def adjust(body: AdjustIn, db: Session = Depends(get_db),
           user: User = Depends(require_permission("inventory.adjust"))):
    batch = db.get(ProductBatch, body.batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="BATCH_NOT_FOUND")
    try:
        inv.adjust_batch(db, batch=batch, new_current_qty=body.new_current_qty,
                         user=user, reason=body.reason)
        db.commit()
        return {"batch_id": batch.id, "current_qty": batch.current_qty, "status": batch.status}
    except InventoryError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/waste")
def waste(body: AdjustIn, db: Session = Depends(get_db),
          user: User = Depends(require_permission("inventory.adjust"))):
    batch = db.get(ProductBatch, body.batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="BATCH_NOT_FOUND")
    try:
        inv.record_waste(db, batch=batch, qty=body.new_current_qty, user=user, reason=body.reason)
        db.commit()
        return {"batch_id": batch.id, "current_qty": batch.current_qty}
    except InventoryError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/movements")
def movements(limit: int = Query(default=200, le=1000), db: Session = Depends(get_db),
              _: User = Depends(require_permission("inventory.view"))):
    from ..services.reports import movements_report
    return movements_report(db, limit=limit)


# --- Stocktaking (§19–20): create -> count (persist immediately) -------------
# -> complete -> PENDING_APPROVAL -> manager approve -> adjustments applied
@router.post("/stocktakes", status_code=201)
def create_stocktake(body: StocktakeIn, db: Session = Depends(get_db),
                     user: User = Depends(require_permission("inventory.stocktake"))):
    st = inv.create_stocktake(db, name=body.name, area=body.area, user=user,
                              product_ids=body.product_ids, batch_ids=body.batch_ids,
                              include_zero=body.include_zero)
    db.commit()
    return {"id": st.id, "name": st.name, "status": st.status,
            "items": [{"id": i.id, "product_id": i.product_id, "batch_id": i.batch_id,
                       "system_qty": i.system_qty} for i in st.items]}


@router.get("/stocktakes")
def list_stocktakes(db: Session = Depends(get_db), _: User = Depends(require_permission("inventory.stocktake"))):
    from ..services.reports import stocktake_report
    return stocktake_report(db)


@router.get("/stocktakes/{stocktake_id}")
def get_stocktake(stocktake_id: int, db: Session = Depends(get_db),
                  _: User = Depends(require_permission("inventory.stocktake"))):
    st = db.get(Stocktake, stocktake_id)
    if not st:
        raise HTTPException(status_code=404, detail="STOCKTAKE_NOT_FOUND")
    pids = [i.product_id for i in st.items]
    products = {p.id: p for p in db.execute(select(Product).where(Product.id.in_(pids))).scalars()} if pids else {}
    return {"id": st.id, "name": st.name, "status": st.status, "area": st.area,
            "items": [{"id": i.id, "product_id": i.product_id, "batch_id": i.batch_id,
                       "product_name": (products.get(i.product_id).name if products.get(i.product_id) else f"#{i.product_id}"),
                       "barcode": (products.get(i.product_id).barcode if products.get(i.product_id) else None),
                       "image_url": (products.get(i.product_id).image_url if products.get(i.product_id) else None),
                       "system_qty": i.system_qty, "physical_qty": i.physical_qty,
                       "difference": i.difference, "status": i.status, "reason": i.reason}
                      for i in st.items]}


@router.get("/stocktakes/{stocktake_id}/progress")
def stocktake_progress(stocktake_id: int, db: Session = Depends(get_db),
                       _: User = Depends(require_permission("inventory.stocktake"))):
    try:
        return inv.stocktake_progress(db, stocktake_id)
    except InventoryError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/stocktakes/{stocktake_id}/start")
def start_stocktake(stocktake_id: int, db: Session = Depends(get_db),
                    user: User = Depends(require_permission("inventory.stocktake"))):
    try:
        st = inv.start_stocktake(db, stocktake_id=stocktake_id, user=user)
        db.commit()
        return {"id": st.id, "status": st.status}
    except InventoryError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/stocktakes/{stocktake_id}/item-by-barcode/{barcode}")
def item_by_barcode(stocktake_id: int, barcode: str, db: Session = Depends(get_db),
                    _: User = Depends(require_permission("inventory.stocktake"))):
    """Camera scan support (§23): find this session's item(s) for a scanned barcode."""
    from ..services.catalog import get_product_by_barcode
    st = db.get(Stocktake, stocktake_id)
    if not st:
        raise HTTPException(status_code=404, detail="STOCKTAKE_NOT_FOUND")
    product = get_product_by_barcode(db, barcode)
    if not product:
        raise HTTPException(status_code=404, detail={"code": "PRODUCT_NOT_FOUND",
                                                     "message": "این بارکد در سیستم ثبت نشده است"})
    items = [i for i in st.items if i.product_id == product.id]
    if not items:
        raise HTTPException(status_code=404, detail={"code": "ITEM_NOT_IN_SESSION",
                                                     "message": "این کالا در فهرست این انبارگردانی نیست"})
    return {"product": {"id": product.id, "name": product.name, "barcode": product.barcode,
                        "image_url": product.image_url},
            "items": [{"id": i.id, "batch_id": i.batch_id, "system_qty": i.system_qty,
                       "physical_qty": i.physical_qty, "status": i.status,
                       "difference": i.difference} for i in items]}


@router.post("/stocktakes/count")
def count_item(body: CountIn, db: Session = Depends(get_db),
               user: User = Depends(require_permission("inventory.stocktake"))):
    try:
        item = inv.count_stocktake_item(db, item_id=body.item_id, physical_qty=body.physical_qty,
                                        reason=body.reason, user=user)
        db.commit()
        return {"item_id": item.id, "system_qty": item.system_qty, "physical_qty": item.physical_qty,
                "difference": item.difference, "status": item.status}
    except InventoryError as e:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(e))


@router.post("/stocktakes/{stocktake_id}/complete")
def complete_stocktake(stocktake_id: int, db: Session = Depends(get_db),
                       user: User = Depends(require_permission("inventory.stocktake"))):
    """Finish counting -> PENDING_APPROVAL. Stock is NOT changed yet."""
    try:
        st = inv.complete_stocktake(db, stocktake_id=stocktake_id, user=user)
        db.commit()
        return {"id": st.id, "status": st.status,
                "differences": inv.stocktake_differences(db, stocktake_id)}
    except InventoryError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/stocktakes/{stocktake_id}/differences")
def stocktake_differences(stocktake_id: int, db: Session = Depends(get_db),
                          _: User = Depends(require_permission("inventory.stocktake"))):
    """System vs physical incl. value difference (§34)."""
    try:
        return inv.stocktake_differences(db, stocktake_id)
    except InventoryError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/stocktakes/{stocktake_id}/approve")
def approve_stocktake(stocktake_id: int, db: Session = Depends(get_db),
                      user: User = Depends(require_permission("inventory.approve_stocktake"))):
    """Manager approval applies the adjustments (audited per batch)."""
    try:
        st = inv.approve_stocktake(db, stocktake_id=stocktake_id, user=user)
        db.commit()
        return {"id": st.id, "status": st.status}
    except InventoryError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/stocktakes/{stocktake_id}/cancel")
def cancel_stocktake(stocktake_id: int, db: Session = Depends(get_db),
                     user: User = Depends(require_permission("inventory.stocktake"))):
    try:
        st = inv.cancel_stocktake(db, stocktake_id=stocktake_id, user=user)
        db.commit()
        return {"id": st.id, "status": st.status}
    except InventoryError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))
