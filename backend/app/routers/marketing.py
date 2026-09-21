"""Campaigns & coupons API (§31–38)."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Campaign, Coupon, CouponRedemption, Customer, User
from ..security import require_permission
from ..services import coupons as svc
from ..services.audit import write_audit

router = APIRouter(prefix="/marketing", tags=["marketing"])


class CampaignIn(BaseModel):
    name: str
    description: str | None = None
    discount_type: str = Field(default="PERCENT", pattern="^(PERCENT|FIXED)$")
    discount_value: Decimal = Field(default=Decimal("0"), ge=0)
    min_purchase: Decimal = Field(default=Decimal("0"), ge=0)
    max_discount: Decimal | None = Field(default=None, ge=0)
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    auto_issue_threshold: Decimal | None = Field(default=None, ge=0)
    auto_issue_validity_days: int = Field(default=30, ge=1, le=3650)
    auto_issue_sms: bool = True
    status: str = Field(default="ACTIVE", pattern="^(ACTIVE|PAUSED|ENDED)$")


class CouponIn(BaseModel):
    code: str | None = None
    campaign_id: int | None = None
    customer_id: int | None = None
    customer_phone: str | None = None
    discount_type: str = Field(default="PERCENT", pattern="^(PERCENT|FIXED)$")
    discount_value: Decimal = Field(default=Decimal("0"), ge=0)
    min_purchase: Decimal = Field(default=Decimal("0"), ge=0)
    max_discount: Decimal | None = Field(default=None, ge=0)
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    usage_limit: int = Field(default=1, ge=1, le=100000)
    note: str | None = None


class ValidateIn(BaseModel):
    code: str
    amount: Decimal = Field(ge=0)
    customer_id: int | None = None
    customer_phone: str | None = None


def _campaign_out(c: Campaign) -> dict:
    return {
        "id": c.id, "name": c.name, "description": c.description,
        "discount_type": c.discount_type, "discount_value": float(c.discount_value),
        "min_purchase": float(c.min_purchase),
        "max_discount": float(c.max_discount) if c.max_discount is not None else None,
        "valid_from": c.valid_from.isoformat() if c.valid_from else None,
        "valid_until": c.valid_until.isoformat() if c.valid_until else None,
        "auto_issue_threshold": float(c.auto_issue_threshold) if c.auto_issue_threshold else None,
        "auto_issue_validity_days": c.auto_issue_validity_days,
        "auto_issue_sms": c.auto_issue_sms,
        "status": c.status,
    }


def _coupon_out(c: Coupon) -> dict:
    return {
        "id": c.id, "code": c.code, "campaign_id": c.campaign_id,
        "customer_id": c.customer_id, "customer_phone": c.customer_phone,
        "discount_type": c.discount_type, "discount_value": float(c.discount_value),
        "min_purchase": float(c.min_purchase),
        "max_discount": float(c.max_discount) if c.max_discount is not None else None,
        "valid_from": c.valid_from.isoformat() if c.valid_from else None,
        "valid_until": c.valid_until.isoformat() if c.valid_until else None,
        "usage_limit": c.usage_limit, "used_count": c.used_count,
        "status": c.status, "note": c.note,
        "created_at": c.created_at.isoformat() if c.created_at else None,
    }


# --- campaigns ----------------------------------------------------------------

@router.get("/campaigns")
def list_campaigns(db: Session = Depends(get_db),
                   _: User = Depends(require_permission("reports.view"))):
    rows = db.execute(select(Campaign).order_by(Campaign.id.desc())).scalars()
    return [_campaign_out(c) for c in rows]


@router.post("/campaigns", status_code=201)
def create_campaign(body: CampaignIn, db: Session = Depends(get_db),
                    user: User = Depends(require_permission("settings.manage"))):
    c = Campaign(**body.model_dump(), created_by=user.id)
    db.add(c)
    db.flush()
    write_audit(db, action="CAMPAIGN_CREATED", user_id=user.id, entity_type="Campaign",
                entity_id=c.id, after={"name": c.name})
    db.commit()
    return _campaign_out(c)


@router.patch("/campaigns/{campaign_id}")
def update_campaign(campaign_id: int, body: CampaignIn, db: Session = Depends(get_db),
                    user: User = Depends(require_permission("settings.manage"))):
    c = db.get(Campaign, campaign_id)
    if not c:
        raise HTTPException(status_code=404, detail="CAMPAIGN_NOT_FOUND")
    for k, v in body.model_dump().items():
        setattr(c, k, v)
    write_audit(db, action="CAMPAIGN_UPDATED", user_id=user.id, entity_type="Campaign",
                entity_id=c.id, after={"name": c.name, "status": c.status})
    db.commit()
    return _campaign_out(c)


# --- coupons ------------------------------------------------------------------

@router.get("/coupons")
def list_coupons(q: str | None = None, status: str | None = None,
                 customer_id: int | None = None, limit: int = Query(100, le=1000),
                 db: Session = Depends(get_db),
                 _: User = Depends(require_permission("reports.view"))):
    stmt = select(Coupon).order_by(Coupon.id.desc())
    if q:
        stmt = stmt.where(Coupon.code.ilike(f"%{q.strip().upper()}%") |
                          Coupon.customer_phone.ilike(f"%{q.strip()}%"))
    if status:
        stmt = stmt.where(Coupon.status == status.upper())
    if customer_id:
        stmt = stmt.where(Coupon.customer_id == customer_id)
    return [_coupon_out(c) for c in db.execute(stmt.limit(limit)).scalars()]


@router.post("/coupons", status_code=201)
def create_coupon(body: CouponIn, db: Session = Depends(get_db),
                  user: User = Depends(require_permission("settings.manage"))):
    code = (body.code or svc.generate_code()).strip().upper()
    if svc.get_by_code(db, code):
        raise HTTPException(status_code=409, detail="COUPON_CODE_EXISTS")
    phone = body.customer_phone
    if body.customer_id and not phone:
        cust = db.get(Customer, body.customer_id)
        phone = cust.phone if cust else None
    c = Coupon(**{**body.model_dump(exclude={"code", "customer_phone"}),
                  "code": code, "customer_phone": phone},
               created_by=user.id)
    db.add(c)
    db.flush()
    write_audit(db, action="COUPON_CREATED", user_id=user.id, entity_type="Coupon",
                entity_id=c.id, after={"code": c.code})
    db.commit()
    return _coupon_out(c)


@router.post("/coupons/{coupon_id}/block")
def block_coupon(coupon_id: int, db: Session = Depends(get_db),
                 user: User = Depends(require_permission("settings.manage"))):
    c = db.get(Coupon, coupon_id)
    if not c:
        raise HTTPException(status_code=404, detail="COUPON_NOT_FOUND")
    c.status = "BLOCKED"
    write_audit(db, action="COUPON_BLOCKED", user_id=user.id, entity_type="Coupon",
                entity_id=c.id)
    db.commit()
    return _coupon_out(c)


@router.post("/coupons/validate")
def validate_coupon(body: ValidateIn, db: Session = Depends(get_db),
                    _: User = Depends(require_permission("pos.sell"))):
    """Read-only evaluation used by the POS before checkout. Never consumes."""
    try:
        res = svc.evaluate(db, code=body.code, amount=body.amount,
                           customer_id=body.customer_id, customer_phone=body.customer_phone)
    except svc.CouponError as exc:
        raise HTTPException(status_code=422, detail={"code": exc.code, "message": exc.message})
    return {**res, "discount": float(res["discount"]),
            "discount_value": float(res["discount_value"]),
            "min_purchase": float(res["min_purchase"]),
            "max_discount": float(res["max_discount"]) if res["max_discount"] is not None else None}


@router.get("/coupons/{coupon_id}/redemptions")
def coupon_redemptions(coupon_id: int, db: Session = Depends(get_db),
                       _: User = Depends(require_permission("reports.view"))):
    rows = db.execute(
        select(CouponRedemption).where(CouponRedemption.coupon_id == coupon_id)
        .order_by(CouponRedemption.id.desc())
    ).scalars()
    return [{"id": r.id, "invoice_id": r.invoice_id, "customer_id": r.customer_id,
             "amount": float(r.amount), "created_at": r.created_at.isoformat()} for r in rows]


@router.get("/stats")
def marketing_stats(db: Session = Depends(get_db),
                    _: User = Depends(require_permission("reports.view"))):
    total = int(db.execute(select(func.count()).select_from(Coupon)).scalar_one())
    by_status = dict(db.execute(
        select(Coupon.status, func.count()).group_by(Coupon.status)
    ).all())
    redeemed_value = float(db.execute(
        select(func.coalesce(func.sum(CouponRedemption.amount), 0))
    ).scalar_one())
    return {"total_coupons": total, "by_status": by_status,
            "redeemed_value": redeemed_value,
            "campaigns": int(db.execute(select(func.count()).select_from(Campaign)).scalar_one())}
