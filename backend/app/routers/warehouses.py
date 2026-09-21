"""Warehouses, storage locations and inter-warehouse transfers (§109, §130, §131)."""
from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import ProductBatch, StorageLocation, User, Warehouse
from ..security import require_permission
from ..services import inventory as inv
from ..services.audit import write_audit
from ..services.inventory import InventoryError

router = APIRouter(prefix="/warehouses", tags=["warehouses"])


class WarehouseIn(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    code: str | None = None
    address: str | None = None
    is_default: bool = False


class WarehousePatch(BaseModel):
    name: str | None = None
    code: str | None = None
    address: str | None = None
    is_default: bool | None = None
    is_active: bool | None = None


class LocationIn(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    code: str | None = None


class TransferIn(BaseModel):
    batch_id: int
    quantity: Decimal = Field(gt=0)
    to_warehouse_id: int
    to_location_id: int | None = None
    reason: str | None = None


def _w_out(w: Warehouse, db: Session) -> dict:
    stock = db.execute(
        select(func.coalesce(func.sum(ProductBatch.current_qty), 0),
               func.coalesce(func.sum(ProductBatch.current_qty * ProductBatch.buy_price), 0))
        .where(ProductBatch.warehouse_id == w.id)
    ).one()
    return {"id": w.id, "name": w.name, "code": w.code, "address": w.address,
            "is_default": w.is_default, "is_active": w.is_active,
            "total_qty": float(stock[0]), "stock_value": float(stock[1]),
            "locations": [{"id": l.id, "name": l.name, "code": l.code, "is_active": l.is_active}
                          for l in db.execute(select(StorageLocation)
                                              .where(StorageLocation.warehouse_id == w.id)
                                              .order_by(StorageLocation.name)).scalars()]}


@router.get("")
def list_warehouses(db: Session = Depends(get_db), _: User = Depends(require_permission("inventory.view"))):
    inv.ensure_default_warehouse(db)
    db.commit()
    rows = db.execute(select(Warehouse).order_by(Warehouse.is_default.desc(), Warehouse.name)).scalars()
    return [_w_out(w, db) for w in rows]


@router.post("", status_code=201)
def create_warehouse(body: WarehouseIn, db: Session = Depends(get_db),
                     user: User = Depends(require_permission("inventory.adjust"))):
    if body.is_default:
        for w in db.execute(select(Warehouse)).scalars():
            w.is_default = False
    w = Warehouse(name=body.name.strip(), code=body.code, address=body.address, is_default=body.is_default)
    db.add(w)
    db.flush()
    write_audit(db, action="WAREHOUSE_CREATED", user_id=user.id, entity_type="Warehouse", entity_id=w.id,
                after={"name": w.name})
    db.commit()
    return _w_out(w, db)


@router.patch("/{warehouse_id}")
def update_warehouse(warehouse_id: int, body: WarehousePatch, db: Session = Depends(get_db),
                     user: User = Depends(require_permission("inventory.adjust"))):
    w = db.get(Warehouse, warehouse_id)
    if not w:
        raise HTTPException(status_code=404, detail="WAREHOUSE_NOT_FOUND")
    data = body.model_dump(exclude_none=True)
    if data.get("is_default"):
        for o in db.execute(select(Warehouse)).scalars():
            o.is_default = False
    for k, v in data.items():
        setattr(w, k, v)
    write_audit(db, action="WAREHOUSE_UPDATED", user_id=user.id, entity_type="Warehouse", entity_id=w.id,
                after=data)
    db.commit()
    return _w_out(w, db)


@router.post("/{warehouse_id}/locations", status_code=201)
def create_location(warehouse_id: int, body: LocationIn, db: Session = Depends(get_db),
                    user: User = Depends(require_permission("inventory.adjust"))):
    if not db.get(Warehouse, warehouse_id):
        raise HTTPException(status_code=404, detail="WAREHOUSE_NOT_FOUND")
    loc = StorageLocation(warehouse_id=warehouse_id, name=body.name.strip(), code=body.code)
    db.add(loc)
    db.flush()
    write_audit(db, action="LOCATION_CREATED", user_id=user.id, entity_type="StorageLocation",
                entity_id=loc.id, after={"name": loc.name, "warehouse_id": warehouse_id})
    db.commit()
    return {"id": loc.id, "warehouse_id": warehouse_id, "name": loc.name, "code": loc.code}


@router.post("/transfer")
def transfer(body: TransferIn, db: Session = Depends(get_db),
             user: User = Depends(require_permission("inventory.adjust"))):
    batch = db.get(ProductBatch, body.batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="BATCH_NOT_FOUND")
    try:
        nb = inv.transfer_batch(db, batch=batch, qty=body.quantity, to_warehouse_id=body.to_warehouse_id,
                                to_location_id=body.to_location_id, user=user, reason=body.reason)
        db.commit()
        return {"source_batch_id": batch.id, "source_current_qty": float(batch.current_qty),
                "dest_batch_id": nb.id, "dest_current_qty": float(nb.current_qty),
                "dest_warehouse_id": nb.warehouse_id, "dest_location_id": nb.location_id}
    except InventoryError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))
