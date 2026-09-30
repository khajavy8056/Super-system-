"""Coupon / campaign engine (§31–38).

Two-phase by design:

  ``evaluate()``  – pure, read-only. Used by the cart preview and by checkout
                    right before committing. Never mutates a coupon.
  ``consume()``   – called INSIDE the checkout transaction. Uses a conditional
                    UPDATE (``used_count < usage_limit``) so two terminals can
                    never take the same last use, and writes a redemption row.

A coupon whose checkout later fails is never burned: the whole transaction
rolls back together with the redemption row.
"""
from __future__ import annotations

import secrets
import string
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from ..models import Campaign, CampaignRedemption, Coupon, CouponRedemption, Customer, User
from .audit import write_audit

ZERO = Decimal("0")
CENT = Decimal("0.01")
_ALPHABET = string.ascii_uppercase.replace("O", "").replace("I", "") + "23456789"


class CouponError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def generate_code(prefix: str = "SM", length: int = 8) -> str:
    body = "".join(secrets.choice(_ALPHABET) for _ in range(length))
    return f"{prefix.upper().strip('-')}-{body}" if prefix else body


def get_by_code(db: Session, code: str) -> Coupon | None:
    return db.execute(
        select(Coupon).where(Coupon.code == code.strip().upper())
    ).scalar_one_or_none()


def _expire_if_needed(coupon: Coupon, now: datetime) -> None:
    if coupon.status == "ACTIVE" and coupon.valid_until and coupon.valid_until < now:
        coupon.status = "EXPIRED"


def evaluate(
    db: Session,
    *,
    code: str,
    amount: Decimal,
    customer_id: int | None = None,
    customer_phone: str | None = None,
    now: datetime | None = None,
) -> dict:
    """Return the discount a coupon would give for ``amount`` (no writes).

    Raises ``CouponError`` with a machine-readable code on every rejection so
    the POS can show a precise reason.
    """
    now = now or datetime.utcnow()
    amount = Decimal(amount)
    coupon = get_by_code(db, code)
    if coupon is None:
        raise CouponError("COUPON_NOT_FOUND", "کد تخفیف یافت نشد")

    _expire_if_needed(coupon, now)

    if coupon.status == "BLOCKED":
        raise CouponError("COUPON_BLOCKED", "این کد تخفیف مسدود شده است")
    if coupon.status == "EXPIRED":
        raise CouponError("COUPON_EXPIRED", "اعتبار این کد تخفیف تمام شده است")
    if coupon.status == "USED":
        raise CouponError("COUPON_USED", "این کد تخفیف قبلاً استفاده شده است")
    if coupon.valid_from and coupon.valid_from > now:
        raise CouponError("COUPON_NOT_STARTED", "زمان استفاده از این کد هنوز نرسیده است")
    if coupon.valid_until and coupon.valid_until < now:
        raise CouponError("COUPON_EXPIRED", "اعتبار این کد تخفیف تمام شده است")
    if coupon.used_count >= coupon.usage_limit:
        raise CouponError("COUPON_LIMIT_REACHED", "سقف دفعات استفاده از این کد پر شده است")

    campaign = db.get(Campaign, coupon.campaign_id) if coupon.campaign_id else None
    if campaign is not None and campaign.status != "ACTIVE":
        raise CouponError("CAMPAIGN_INACTIVE", "کمپین این کد فعال نیست")

    # customer-specific coupon (§35)
    if coupon.customer_id or coupon.customer_phone:
        ok = False
        if customer_id and coupon.customer_id == customer_id:
            ok = True
        if coupon.customer_phone and customer_phone and \
                _norm_phone(coupon.customer_phone) == _norm_phone(customer_phone):
            ok = True
        if not ok and customer_id and coupon.customer_phone:
            cust = db.get(Customer, customer_id)
            if cust and cust.phone and _norm_phone(cust.phone) == _norm_phone(coupon.customer_phone):
                ok = True
        if not ok:
            raise CouponError("COUPON_NOT_YOURS", "این کد مخصوص مشتری دیگری است")

    if coupon.min_purchase and amount < coupon.min_purchase:
        raise CouponError(
            "MIN_PURCHASE_NOT_MET",
            f"حداقل مبلغ خرید برای این کد {coupon.min_purchase:,.0f} است",
        )

    discount = compute_discount(coupon, amount)
    if discount <= 0:
        raise CouponError("NO_DISCOUNT", "این کد برای این سبد تخفیفی ایجاد نمی‌کند")

    return {
        "coupon_id": coupon.id,
        "code": coupon.code,
        "discount": discount,
        "discount_type": coupon.discount_type,
        "discount_value": coupon.discount_value,
        "max_discount": coupon.max_discount,
        "min_purchase": coupon.min_purchase,
        "remaining_uses": coupon.usage_limit - coupon.used_count,
        "campaign": campaign.name if campaign else None,
    }


def compute_discount(coupon: Coupon, amount: Decimal) -> Decimal:
    """Percentage or fixed, capped by ``max_discount`` and by the amount (§32–34)."""
    amount = Decimal(amount)
    if coupon.discount_type.upper() == "PERCENT":
        raw = (amount * Decimal(coupon.discount_value) / Decimal("100"))
    else:
        raw = Decimal(coupon.discount_value)
    if coupon.max_discount is not None and coupon.max_discount > 0:
        raw = min(raw, Decimal(coupon.max_discount))
    raw = min(raw, amount)  # never negative totals
    return max(ZERO, raw.quantize(CENT, ROUND_HALF_UP))


# ============================================================================ build-481 — campaign benefits at the till (§21–26)
#
# A campaign is no longer just a label coupons hang off: it is an executable
# benefit the checkout can apply.  The rules below are the ONLY place the
# benefit is computed — the cashier selects among campaigns whose conditions
# already hold and can never bend one (§25).

class CampaignError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _campaign_targets(campaign: Campaign) -> list[int]:
    import json as _json
    try:
        ids = _json.loads(campaign.target_ids or "[]")
    except ValueError:
        ids = []
    return [int(x) for x in ids if x is not None]


def compute_campaign_discount(campaign: Campaign, amount: Decimal) -> Decimal:
    """Same honesty rules as coupon math: percent/fixed, capped, never negative."""
    amount = Decimal(amount)
    if str(campaign.discount_type).upper() == "PERCENT":
        raw = amount * Decimal(campaign.discount_value) / Decimal("100")
    else:
        raw = Decimal(campaign.discount_value)
    if campaign.max_discount is not None and campaign.max_discount > 0:
        raw = min(raw, Decimal(campaign.max_discount))
    raw = min(raw, amount)
    return max(ZERO, raw.quantize(CENT, ROUND_HALF_UP))


def campaign_scope_amount(campaign: Campaign, *, amount: Decimal, product_ids: list[int] | None,
                          line_amounts: dict[int, Decimal] | None) -> Decimal:
    """For product-targeted campaigns only the covered lines count as the base.

    ``line_amounts`` maps product_id → net line total.  Without line detail the
    whole amount is assumed covered (the API validates this before checkout).
    """
    if str(campaign.target_type).upper() != "PRODUCTS":
        return Decimal(amount)
    targets = set(_campaign_targets(campaign))
    if not targets or not line_amounts:
        return ZERO
    return sum((Decimal(v) for pid, v in line_amounts.items() if int(pid) in targets), ZERO)


def _campaign_purchases_count(db: Session, campaign: Campaign, customer_id: int | None) -> int:
    if not customer_id:
        return 0
    return db.execute(
        select(func.count(CampaignRedemption.id)).where(
            CampaignRedemption.campaign_id == campaign.id,
            CampaignRedemption.customer_id == customer_id,
        )
    ).scalar_one()


def _customer_purchase_count(db: Session, customer_id: int | None) -> int:
    if not customer_id:
        return 0
    from ..models import Invoice
    return db.execute(
        select(func.count(Invoice.id)).where(
            Invoice.customer_id == customer_id, Invoice.status == "PAID"
        )
    ).scalar_one()


def evaluate_campaign(
    db: Session,
    *,
    campaign_id: int,
    amount: Decimal,
    product_ids: list[int] | None = None,
    line_amounts: dict[int, Decimal] | None = None,
    customer_id: int | None = None,
    now: datetime | None = None,
) -> dict:
    """Validate EVERY condition and return the benefit a campaign would grant.

    Read-only: nothing is written.  Raises :class:`CampaignError` with a
    machine-readable code whenever the campaign must not apply — the POS shows
    the exact reason instead of a silent no-op (§25).
    """
    now = now or datetime.utcnow()
    amount = Decimal(amount)
    campaign = db.get(Campaign, campaign_id)
    if campaign is None:
        raise CampaignError("CAMPAIGN_NOT_FOUND", "جشنواره یافت نشد")
    if campaign.status != "ACTIVE":
        raise CampaignError("CAMPAIGN_INACTIVE", "این جشنواره فعال نیست")
    if campaign.valid_from and campaign.valid_from > now:
        raise CampaignError("CAMPAIGN_NOT_STARTED", "زمان این جشنواره هنوز نرسیده است")
    if campaign.valid_until and campaign.valid_until < now:
        raise CampaignError("CAMPAIGN_EXPIRED", "مهلت این جشنواره تمام شده است")
    if amount <= 0:
        raise CampaignError("EMPTY_CART", "سبد خرید خالی است")

    if campaign.min_purchase and amount < campaign.min_purchase:
        raise CampaignError(
            "MIN_PURCHASE_NOT_MET",
            f"حداقل خرید برای این جشنواره {campaign.min_purchase:,.0f} است",
        )
    if campaign.max_purchase is not None and campaign.max_purchase > 0 and amount > campaign.max_purchase:
        raise CampaignError(
            "MAX_PURCHASE_EXCEEDED",
            f"این جشنواره تا سقف خرید {campaign.max_purchase:,.0f} اعمال می‌شود",
        )

    base = campaign_scope_amount(campaign, amount=amount, product_ids=product_ids,
                                 line_amounts=line_amounts)
    if str(campaign.target_type).upper() == "PRODUCTS":
        targets = _campaign_targets(campaign)
        if not targets:
            raise CampaignError("CAMPAIGN_NO_TARGETS", "کالای مشخص‌شده‌ای برای این جشنواره ثبت نشده است")
        if base <= 0:
            raise CampaignError("PRODUCT_NOT_IN_CAMPAIGN", "هیچ‌کدام از کالاهای این سبد مشمول جشنواره نیستند")

    if campaign.usage_limit is not None and campaign.used_count >= campaign.usage_limit:
        raise CampaignError("CAMPAIGN_LIMIT_REACHED", "سقف استفادهٔ این جشنواره پر شده است")
    if campaign.first_purchase_only and customer_id and _customer_purchase_count(db, customer_id) > 0:
        raise CampaignError("CAMPAIGN_FIRST_PURCHASE_ONLY", "این جشنواره فقط برای نخستین خرید است")
    if campaign.per_customer_limit is not None and customer_id:
        used = _campaign_purchases_count(db, campaign, customer_id)
        if used >= campaign.per_customer_limit:
            raise CampaignError("CAMPAIGN_CUSTOMER_LIMIT", "سقف استفادهٔ شما از این جشنواره پر شده است")

    discount = compute_campaign_discount(campaign, base)
    if discount <= 0:
        raise CampaignError("NO_DISCOUNT", "این جشنواره برای این سبد تخفیفی ایجاد نمی‌کند")

    return {
        "campaign_id": campaign.id,
        "name": campaign.name,
        "discount": discount,
        "discount_type": campaign.discount_type,
        "discount_value": campaign.discount_value,
        "min_purchase": campaign.min_purchase,
        "max_discount": campaign.max_discount,
        "scope_amount": base,
        "target_type": campaign.target_type,
        "stackable": bool(campaign.stackable),
        "auto_apply": bool(campaign.auto_apply),
        "priority": campaign.priority,
    }


def eligible_campaigns(
    db: Session,
    *,
    amount: Decimal,
    product_ids: list[int] | None = None,
    line_amounts: dict[int, Decimal] | None = None,
    customer_id: int | None = None,
    now: datetime | None = None,
    include_auto_apply: bool = True,
    limit: int = 20,
) -> list[dict]:
    """The structured list a cashier chooses from (§24).

    Only campaigns whose conditions ALREADY hold for this basket are returned —
    the till never receives a campaign the server would reject at checkout.
    """
    now = now or datetime.utcnow()
    rows = db.execute(
        select(Campaign).where(Campaign.status == "ACTIVE").order_by(Campaign.priority.asc(), Campaign.id.desc())
    ).scalars().all()
    out: list[dict] = []
    for c in rows:
        if not include_auto_apply and c.auto_apply:
            continue
        if c.valid_from and c.valid_from > now:
            continue
        if c.valid_until and c.valid_until < now:
            continue
        if c.auto_issue_threshold is not None and c.discount_value == 0:
            continue   # issue-only festival: its benefit is the future coupon, not a till discount
        try:
            ev = evaluate_campaign(
                db, campaign_id=c.id, amount=amount, product_ids=product_ids,
                line_amounts=line_amounts, customer_id=customer_id, now=now,
            )
        except CampaignError:
            continue
        out.append(ev)
        if len(out) >= limit:
            break
    return out


def consume_campaign(
    db: Session,
    *,
    campaign_id: int,
    amount: Decimal,
    invoice_id: int | None,
    customer_id: int | None = None,
    user: User | None = None,
    source: str = "CAMPAIGN",
) -> CampaignRedemption:
    """Burn one usage of the campaign inside the checkout transaction.

    Same concurrency guard as coupons: a conditional UPDATE on
    ``used_count < usage_limit`` so two terminals can never exceed the limit.
    A failed checkout rolls the whole row back with the sale.
    """
    campaign = db.get(Campaign, campaign_id)
    if campaign is None:
        raise CampaignError("CAMPAIGN_NOT_FOUND", "جشنواره یافت نشد")
    if campaign.usage_limit is not None:
        res = db.execute(
            update(Campaign)
            .where(
                Campaign.id == campaign_id,
                Campaign.status == "ACTIVE",
                func.coalesce(Campaign.used_count, 0) < campaign.usage_limit,
            )
            .values(used_count=Campaign.used_count + 1)
        )
        if res.rowcount != 1:
            raise CampaignError("CAMPAIGN_LIMIT_REACHED", "این جشنواره هم‌زمان توسط صندوق دیگری استفاده شد")
    else:
        campaign.used_count = (campaign.used_count or 0) + 1

    red = CampaignRedemption(
        campaign_id=campaign_id, invoice_id=invoice_id, customer_id=customer_id,
        amount=Decimal(amount), source=source, created_at=datetime.utcnow(),
        created_by=user.id if user else None,
    )
    db.add(red)
    write_audit(
        db, action="CAMPAIGN_APPLIED", user_id=user.id if user else None,
        entity_type="Campaign", entity_id=campaign_id,
        after={"campaign": campaign.name, "amount": float(amount), "invoice_id": invoice_id,
               "customer_id": customer_id, "used_count": (campaign.used_count or 0) + (1 if campaign.usage_limit is None else 0),
               "source": source},
    )
    db.flush()
    return red


def consume(
    db: Session,
    *,
    coupon_id: int,
    amount: Decimal,
    invoice_id: int | None,
    customer_id: int | None = None,
    user: User | None = None,
) -> CouponRedemption:
    """Atomically burn one use of the coupon. Must run inside the checkout txn."""
    res = db.execute(
        update(Coupon)
        .where(
            Coupon.id == coupon_id,
            Coupon.status == "ACTIVE",
            Coupon.used_count < Coupon.usage_limit,
        )
        .values(used_count=Coupon.used_count + 1)
    )
    if res.rowcount != 1:
        raise CouponError("COUPON_LIMIT_REACHED", "کد تخفیف هم‌زمان توسط صندوق دیگری استفاده شد")

    coupon = db.get(Coupon, coupon_id)
    db.refresh(coupon)
    if coupon.used_count >= coupon.usage_limit:
        coupon.status = "USED"

    red = CouponRedemption(
        coupon_id=coupon_id, invoice_id=invoice_id, customer_id=customer_id,
        amount=Decimal(amount), created_at=datetime.utcnow(),
        created_by=user.id if user else None,
    )
    db.add(red)
    write_audit(
        db, action="COUPON_REDEEMED", user_id=user.id if user else None,
        entity_type="Coupon", entity_id=coupon_id,
        after={"code": coupon.code, "amount": float(amount), "invoice_id": invoice_id,
               "used_count": coupon.used_count, "status": coupon.status},
    )
    db.flush()
    return red


def issue_next_purchase_coupon(
    db: Session,
    *,
    invoice,
    customer: Customer | None,
    user: User | None = None,
) -> Coupon | None:
    """Auto-issue a coupon for the NEXT purchase when a campaign threshold is
    reached (§36). Returns the coupon, or None when no campaign applies."""
    now = datetime.utcnow()
    campaigns = db.execute(
        select(Campaign).where(
            Campaign.status == "ACTIVE",
            Campaign.auto_issue_threshold.is_not(None),
        ).order_by(Campaign.auto_issue_threshold.desc())
    ).scalars().all()

    for c in campaigns:
        if c.valid_from and c.valid_from > now:
            continue
        if c.valid_until and c.valid_until < now:
            continue
        if Decimal(invoice.total_amount) < Decimal(c.auto_issue_threshold):
            continue
        # build-481 idempotency: the same invoice must never issue the same
        # future benefit twice (double-click on checkout, a retried request, …).
        already = db.execute(
            select(Coupon).where(Coupon.campaign_id == c.id, Coupon.note == f"صادر شده پس از فاکتور {invoice.invoice_number}")
        ).scalars().first()
        if already is not None:
            return already
        coupon = Coupon(
            code=generate_code("NEXT"),
            campaign_id=c.id,
            customer_id=customer.id if customer else None,
            customer_phone=customer.phone if customer else None,
            discount_type=c.discount_type,
            discount_value=c.discount_value,
            min_purchase=c.min_purchase,
            max_discount=c.max_discount,
            valid_from=now,
            valid_until=now + timedelta(days=max(1, c.auto_issue_validity_days)),
            usage_limit=1,
            used_count=0,
            status="ACTIVE",
            note=f"صادر شده پس از فاکتور {invoice.invoice_number}",
            created_by=user.id if user else None,
        )
        db.add(coupon)
        db.flush()
        write_audit(
            db, action="COUPON_ISSUED", user_id=user.id if user else None,
            entity_type="Coupon", entity_id=coupon.id,
            after={"code": coupon.code, "campaign": c.name,
                   "invoice": invoice.invoice_number},
        )
        return coupon
    return None


def _norm_phone(p: str | None) -> str:
    if not p:
        return ""
    digits = "".join(ch for ch in p if ch.isdigit())
    if digits.startswith("0098"):
        digits = "0" + digits[4:]
    elif digits.startswith("98") and len(digits) == 12:
        digits = "0" + digits[2:]
    return digits


def expire_due(db: Session, now: datetime | None = None) -> int:
    """Background sweep: mark past-validity coupons EXPIRED. Returns count."""
    now = now or datetime.utcnow()
    rows = db.execute(
        select(Coupon).where(
            Coupon.status == "ACTIVE",
            Coupon.valid_until.is_not(None),
            Coupon.valid_until < now,
        )
    ).scalars().all()
    for c in rows:
        c.status = "EXPIRED"
    if rows:
        db.flush()
    return len(rows)
