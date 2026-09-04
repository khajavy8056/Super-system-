from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Customer, User
from ..security import get_current_user, require_permission

router = APIRouter(prefix="/customers", tags=["customers"])


class CustomerIn(BaseModel):
    name: str
    phone: str | None = None


def _out(c: Customer) -> dict:
    return {"id": c.id, "name": c.name, "phone": c.phone, "is_active": c.is_active}


@router.get("")
def list_customers(q: str | None = None, db: Session = Depends(get_db),
                   _: User = Depends(require_permission("pos.sell"))):
    stmt = select(Customer).where(Customer.is_active.is_(True)).order_by(Customer.name)
    if q:
        stmt = stmt.where(Customer.name.ilike(f"%{q}%") | Customer.phone.ilike(f"%{q}%"))
    return [_out(c) for c in db.execute(stmt.limit(50)).scalars()]


@router.post("", status_code=201)
def create_customer(body: CustomerIn, db: Session = Depends(get_db),
                    _: User = Depends(require_permission("pos.sell"))):
    if body.phone:
        existing = db.execute(
            select(Customer).where(Customer.phone == body.phone)
        ).scalar_one_or_none()
        if existing:
            return _out(existing)  # idempotent by phone
    c = Customer(name=body.name.strip(), phone=(body.phone or "").strip() or None)
    db.add(c)
    db.commit()
    return _out(c)


@router.get("/phone/{phone}")
def by_phone(phone: str, db: Session = Depends(get_db),
             _: User = Depends(require_permission("pos.sell"))):
    c = db.execute(select(Customer).where(Customer.phone == phone)).scalar_one_or_none()
    if not c:
        raise HTTPException(status_code=404, detail="CUSTOMER_NOT_FOUND")
    return _out(c)
