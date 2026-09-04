"""Customer phone book + credit accounts (§30–35, §42)."""
from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Customer, Invoice, User
from ..security import get_current_user, require_permission
from ..services import ledger as ledger_svc
from ..services.audit import write_audit

router = APIRouter(prefix="/customers", tags=["customers"])


_ERROR_STATUS = {
    "CUSTOMER_NOT_FOUND": 404,
    "CREDIT_DISABLED": 409,
    "CREDIT_LIMIT_EXCEEDED": 409,
    "OVERPAYMENT": 422,
    "NO_DEBT": 409,
    "INVALID_AMOUNT": 422,
    "INVALID_ENTRY_TYPE": 422,
}


def _raise(err: ledger_svc.LedgerError):
    raise HTTPException(
        status_code=_ERROR_STATUS.get(err.code, 400),
        detail={"code": err.code, "message": str(err)},
    )


class CustomerIn(BaseModel):
    name: str
    last_name: str | None = None
    phone: str | None = None
    email: str | None = None
    address: str | None = None
    notes: str | None = None
    credit_enabled: bool = True
    credit_limit: Decimal = Decimal("0")


class CustomerPatch(BaseModel):
    name: str | None = None
    last_name: str | None = None
    phone: str | None = None
    email: str | None = None
    address: str | None = None
    notes: str | None = None
    credit_enabled: bool | None = None
    credit_limit: Decimal | None = None
    is_active: bool | None = None


class SettleIn(BaseModel):
    amount: Decimal | None = Field(
        None, description="Omit or null to settle the full outstanding balance"
    )
    method: str = "CASH"
    note: str | None = None


class AdjustIn(BaseModel):
    entry_type: str = Field(..., description="ADJUSTMENT_DEBIT | ADJUSTMENT_CREDIT")
    amount: Decimal
    note: str


def _out(c: Customer) -> dict:
    return {
        "id": c.id,
        "name": c.name,
        "last_name": c.last_name,
        "phone": c.phone,
        "email": c.email,
        "address": c.address,
        "notes": c.notes,
        "credit_enabled": c.credit_enabled,
        "credit_limit": c.credit_limit,
        "is_active": c.is_active,
    }


# --------------------------------------------------------------------------
# phone book
# --------------------------------------------------------------------------
@router.get("")
def list_customers(q: str | None = None, with_debt: bool = False,
                   db: Session = Depends(get_db),
                   _: User = Depends(require_permission("pos.sell"))):
    """List customers. `with_debt=true` attaches each account balance."""
    stmt = select(Customer).where(Customer.is_active.is_(True)).order_by(Customer.name)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(
            Customer.name.ilike(like)
            | Customer.last_name.ilike(like)
            | Customer.phone.ilike(like)
        )
    rows = [_out(c) for c in db.execute(stmt.limit(100)).scalars()]
    if with_debt:
        for row in rows:
            row["balance"] = ledger_svc.balance_of(db, row["id"])
    return rows


@router.post("", status_code=201)
def create_customer(body: CustomerIn, db: Session = Depends(get_db),
                    _: User = Depends(require_permission("pos.sell"))):
    """Create a customer. Idempotent by phone (§42: a phone with no name is fine)."""
    phone = (body.phone or "").strip() or None
    if phone:
        existing = db.execute(
            select(Customer).where(Customer.phone == phone)
        ).scalar_one_or_none()
        if existing:
            return _out(existing)
    c = Customer(
        name=(body.name or "").strip() or (phone or "بدون نام"),
        last_name=(body.last_name or "").strip() or None,
        phone=phone,
        email=(body.email or "").strip() or None,
        address=(body.address or "").strip() or None,
        notes=(body.notes or "").strip() or None,
        credit_enabled=body.credit_enabled,
        credit_limit=body.credit_limit or Decimal("0"),
    )
    db.add(c)
    db.commit()
    return _out(c)


@router.get("/debtors")
def list_debtors(min_amount: Decimal = Decimal("0"), db: Session = Depends(get_db),
                 _: User = Depends(require_permission("customers.ledger"))):
    """Customers who owe money — the source list for §35 SMS reminders."""
    return ledger_svc.debtors(db, min_amount)


@router.get("/phone/{phone}")
def by_phone(phone: str, db: Session = Depends(get_db),
             _: User = Depends(require_permission("pos.sell"))):
    c = db.execute(select(Customer).where(Customer.phone == phone)).scalar_one_or_none()
    if not c:
        raise HTTPException(status_code=404, detail="CUSTOMER_NOT_FOUND")
    out = _out(c)
    out["balance"] = ledger_svc.balance_of(db, c.id)
    return out


@router.get("/{customer_id}")
def get_customer(customer_id: int, db: Session = Depends(get_db),
                 _: User = Depends(require_permission("pos.sell"))):
    c = db.get(Customer, customer_id)
    if not c:
        raise HTTPException(status_code=404, detail="CUSTOMER_NOT_FOUND")
    out = _out(c)
    out["balance"] = ledger_svc.balance_of(db, c.id)
    return out


@router.patch("/{customer_id}")
def update_customer(customer_id: int, body: CustomerPatch,
                    db: Session = Depends(get_db),
                    user: User = Depends(require_permission("customers.manage"))):
    c = db.get(Customer, customer_id)
    if not c:
        raise HTTPException(status_code=404, detail="CUSTOMER_NOT_FOUND")
    changes = body.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(c, field, value)
    write_audit(db, action="CUSTOMER_UPDATE", user_id=user.id,
                entity_type="Customer", entity_id=c.id, after=changes)
    db.commit()
    return _out(c)


# --------------------------------------------------------------------------
# purchase history + ledger (§32)
# --------------------------------------------------------------------------
@router.get("/{customer_id}/invoices")
def customer_invoices(customer_id: int, limit: int = 50,
                      db: Session = Depends(get_db),
                      _: User = Depends(require_permission("pos.sell"))):
    rows = db.execute(
        select(Invoice)
        .where(Invoice.customer_id == customer_id)
        .order_by(Invoice.id.desc())
        .limit(limit)
    ).scalars()
    return [
        {
            "id": i.id,
            "invoice_number": i.invoice_number,
            "total_amount": i.total_amount,
            "payment_method": i.payment_method,
            "payment_status": i.payment_status,
            "status": i.status,
            "created_at": i.created_at,
        }
        for i in rows
    ]


@router.get("/{customer_id}/ledger")
def customer_ledger(customer_id: int, limit: int = 200,
                    db: Session = Depends(get_db),
                    _: User = Depends(require_permission("customers.ledger"))):
    """Full account statement: balance, totals and every entry."""
    try:
        return ledger_svc.statement(db, customer_id, limit=limit)
    except ledger_svc.LedgerError as e:
        _raise(e)


@router.get("/{customer_id}/ledger/verify")
def verify_ledger(customer_id: int, db: Session = Depends(get_db),
                  _: User = Depends(require_permission("customers.ledger"))):
    """Recompute the balance from history and check the stored witnesses."""
    return ledger_svc.verify_integrity(db, customer_id)


@router.post("/{customer_id}/settle")
def settle_debt(customer_id: int, body: SettleIn, db: Session = Depends(get_db),
                user: User = Depends(require_permission("customers.settle"))):
    """Record a payment (partial or full) against the customer account."""
    try:
        if body.amount is None:
            result = ledger_svc.settle_full(
                db, customer_id=customer_id, method=body.method,
                note=body.note, user_id=user.id)
        else:
            result = ledger_svc.settle(
                db, customer_id=customer_id, amount=body.amount,
                method=body.method, note=body.note, user_id=user.id)
    except ledger_svc.LedgerError as e:
        db.rollback()
        _raise(e)
    write_audit(db, action="CUSTOMER_SETTLE", user_id=user.id,
                entity_type="Customer", entity_id=customer_id,
                after={"paid": str(result["paid"]),
                       "balance": str(result["balance"]),
                       "method": body.method})
    db.commit()
    return result


@router.post("/{customer_id}/ledger/adjust")
def adjust_ledger(customer_id: int, body: AdjustIn, db: Session = Depends(get_db),
                  user: User = Depends(require_permission("customers.settle"))):
    """Post a manual correction.

    The ledger is append-only: a mistake is fixed by a reversing entry, so the
    original record and the correction both remain visible in the statement.
    """
    if body.entry_type not in ("ADJUSTMENT_DEBIT", "ADJUSTMENT_CREDIT"):
        raise HTTPException(status_code=422, detail={
            "code": "INVALID_ENTRY_TYPE",
            "message": "فقط ADJUSTMENT_DEBIT یا ADJUSTMENT_CREDIT مجاز است"})
    try:
        entry = ledger_svc.post_entry(
            db, customer_id=customer_id, entry_type=body.entry_type,
            amount=body.amount, note=body.note, user_id=user.id)
    except ledger_svc.LedgerError as e:
        db.rollback()
        _raise(e)
    write_audit(db, action="CUSTOMER_LEDGER_ADJUST", user_id=user.id,
                entity_type="Customer", entity_id=customer_id,
                after={"entry_type": body.entry_type,
                       "amount": str(body.amount), "note": body.note})
    db.commit()
    return {
        "entry_id": entry.id,
        "amount": entry.amount,
        "balance": entry.balance_after,
    }
