from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Product, User
from ..security import get_current_user, require_permission
from ..services import pos as pos_svc
from ..services.pos import CartItem, PosError

router = APIRouter(prefix="/pos", tags=["pos"])


class CartLineIn(BaseModel):
    product_id: int
    #: decimal quantities are first-class (12.500 Kg) — §25
    quantity: Decimal = Field(default=Decimal("1"), gt=0)
    batch_id: int | None = None
    discount: Decimal = Field(default=Decimal("0"), ge=0)


class CartIn(BaseModel):
    items: list[CartLineIn]
    tax_rate: Decimal | None = None
    coupon_code: str | None = None
    customer_id: int | None = None
    invoice_discount: Decimal | None = Field(default=None, ge=0)


class PaymentIn(BaseModel):
    method: str = "CASH"
    amount: Decimal = Field(ge=0)


class CheckoutIn(BaseModel):
    items: list[CartLineIn]
    payments: list[PaymentIn]
    customer_id: int | None = None
    customer_phone: str | None = None
    customer_name: str | None = None
    tax_rate: Decimal | None = None
    coupon_code: str | None = None
    #: §12 whole-invoice discount (absolute amount in base currency)
    invoice_discount: Decimal | None = Field(default=None, ge=0)
    #: §19 pulse the cash drawer after a successful cash sale
    open_drawer: bool = False


# --- Kiosk / lock mode (§7) ---------------------------------------------------

@router.get("/kiosk/config")
def kiosk_config(db: Session = Depends(get_db),
                 _: User = Depends(get_current_user)):
    """Config the POS terminal needs to enter kiosk mode (any logged-in user)."""
    shortcut = pos_svc.get_setting(db, "pos.kiosk_shortcut", "Ctrl+Shift+L")
    store = pos_svc.get_setting(db, "printer.header", "") or "فروشگاه"
    return {"shortcut": shortcut, "store_name": store.split("\n")[0]}


class KioskUnlockIn(BaseModel):
    username: str
    password: str


@router.post("/kiosk/unlock")
def kiosk_unlock(body: KioskUnlockIn, db: Session = Depends(get_db)):
    """Leaving kiosk requires admin credentials (§7 security note).

    Returns ok=True ONLY for a valid, active user holding ``settings.manage``.
    No token is issued — the cashier session stays as-is; this only unlocks
    the terminal UI. Failed attempts are audited and rate-limited by the same
    login throttling machinery.
    """
    from ..models import User as UserModel
    from ..security import _user_permission_codes, verify_password
    from ..services.audit import write_audit
    from sqlalchemy import select as _select

    user = db.execute(_select(UserModel).where(UserModel.username == body.username)).scalar_one_or_none()
    if not user or not user.is_active or not verify_password(body.password, user.password_hash):
        write_audit(db, action="KIOSK_UNLOCK_FAILED", reference=body.username)
        db.commit()
        raise HTTPException(status_code=401, detail="ادمین معتبر نیست")
    if "settings.manage" not in _user_permission_codes(user):
        write_audit(db, action="KIOSK_UNLOCK_DENIED", user_id=user.id, reference=body.username)
        db.commit()
        raise HTTPException(status_code=403, detail="این کاربر اجازه خروج از حالت کیوسک ندارد")
    write_audit(db, action="KIOSK_UNLOCKED", user_id=user.id, entity_type="User", entity_id=user.id)
    db.commit()
    return {"ok": True}


@router.get("/batch-options/{product_id}")
def batch_options(product_id: int, db: Session = Depends(get_db), _: User = Depends(require_permission("pos.sell"))):
    product = db.get(Product, product_id)
    if not product:
        raise HTTPException(status_code=404, detail="PRODUCT_NOT_FOUND")
    options = pos_svc.get_batch_options(db, product)
    return {"product_id": product_id, "product_name": product.name,
            "mode": pos_svc.get_setting(db, "pos.batch_selection_mode", "HYBRID"),
            "options": [o.as_dict() for o in options]}


@router.post("/cart/validate")
def validate_cart(body: CartIn, db: Session = Depends(get_db), _: User = Depends(require_permission("pos.sell"))):
    try:
        items = pos_svc.validate_cart(db, [CartItem(product_id=i.product_id, quantity=i.quantity,
                                                   batch_id=i.batch_id, discount=i.discount)
                                           for i in body.items])
        totals = _totals(items)
        if body.invoice_discount:
            inv_disc = Decimal(str(body.invoice_discount))
            if inv_disc > Decimal(str(totals["subtotal"])):
                raise HTTPException(status_code=422, detail={"code": "INVALID_DISCOUNT",
                                    "message": "تخفیف فاکتور از مبلغ سبد بیشتر است"})
            totals["invoice_discount"] = float(inv_disc)
            totals["discount"] = float(Decimal(str(totals["discount"])) + inv_disc)
            totals["subtotal"] = float(Decimal(str(totals["subtotal"])) - inv_disc)
        coupon = None
        if body.coupon_code:
            from ..services import coupons as coupon_svc

            phone = None
            if body.customer_id:
                from ..models import Customer
                cust = db.get(Customer, body.customer_id)
                phone = cust.phone if cust else None
            try:
                ev = coupon_svc.evaluate(db, code=body.coupon_code,
                                         amount=Decimal(str(totals["subtotal"])),
                                         customer_id=body.customer_id, customer_phone=phone)
                coupon = {"code": ev["code"], "discount": float(ev["discount"]),
                          "campaign": ev["campaign"], "ok": True}
                totals["coupon_discount"] = float(ev["discount"])
                totals["subtotal"] = float(Decimal(str(totals["subtotal"])) - ev["discount"])
            except coupon_svc.CouponError as exc:
                coupon = {"code": body.coupon_code, "ok": False,
                          "error_code": exc.code, "message": exc.message}
        return {"items": [_line_out(i) for i in items], "totals": totals, "coupon": coupon}
    except PosError as e:
        raise HTTPException(status_code=422, detail={"code": e.code, "message": e.message})


@router.post("/checkout", status_code=201)
def checkout(body: CheckoutIn, db: Session = Depends(get_db),
             user: User = Depends(require_permission("pos.sell"))):
    try:
        customer_id = body.customer_id
        if customer_id is None and body.customer_phone:
            # Phone book: a phone number alone is enough to create a customer (§30)
            from ..models import Customer

            phone = body.customer_phone.strip()
            cust = db.execute(select(Customer).where(Customer.phone == phone)).scalar_one_or_none()
            if cust is None:
                cust = Customer(name=(body.customer_name or phone).strip(), phone=phone)
                db.add(cust)
                db.flush()
            customer_id = cust.id
        invoice = pos_svc.checkout(
            db,
            items=[CartItem(product_id=i.product_id, quantity=i.quantity, batch_id=i.batch_id,
                           discount=i.discount)
                   for i in body.items],
            payments=[p.model_dump() for p in body.payments],
            user=user,
            customer_id=customer_id,
            tax_rate=body.tax_rate,
            coupon_code=body.coupon_code,
            invoice_discount=body.invoice_discount,
        )

        # Next-purchase coupon (§36) + invoice SMS are issued after the sale is
        # built but INSIDE the same transaction, so nothing is half-committed.
        from ..models import Customer as _C
        from ..services import coupons as coupon_svc

        customer = db.get(_C, customer_id) if customer_id else None
        issued = coupon_svc.issue_next_purchase_coupon(
            db, invoice=invoice, customer=customer, user=user)

        if customer and customer.phone:
            from ..services import sms as sms_svc
            from ..services import sync as sync_svc

            # §172/§162 — invoice SMS from the shop-editable pattern (§166);
            # the next-purchase coupon rides along in the same message.
            coupon_line = ""
            if issued:
                coupon_line = f"\nکد تخفیف خرید بعدی: {issued.code}"
                if issued.valid_until:
                    coupon_line += f" (تا {issued.valid_until.date()})"
            text = sms_svc.render_template(
                db, "invoice", invoice=invoice.invoice_number,
                amount=f"{invoice.total_amount:,.0f}", coupon_line=coupon_line,
                **sms_svc._store_ctx(db))
            msg = sms_svc.queue_sms(db, phone=customer.phone, text=text,
                                    reference_type="Invoice", reference_id=invoice.id)
            # queued for retry-safe delivery; never blocks the sale (§48)
            sync_svc.enqueue(db, job_type="SMS", payload={"sms_id": msg.id},
                             reference_type="Invoice", reference_id=invoice.id,
                             idempotency_key=f"sms:invoice:{invoice.id}", user_id=user.id)

        out = _invoice_out(invoice)
        # §19 — cash drawer opens on cash tenders (never blocks the sale)
        out["drawer"] = None
        if body.open_drawer or any(str(p.method).upper() == "CASH" for p in body.payments):
            from ..services import hardware as hw_svc
            ok, msg = hw_svc.open_cash_drawer(db)
            out["drawer"] = {"ok": ok, "message": msg}
        out["coupon_code"] = body.coupon_code
        out["issued_coupon"] = ({"code": issued.code,
                                 "valid_until": issued.valid_until.isoformat()
                                 if issued.valid_until else None} if issued else None)
        db.commit()
        return out
    except PosError as e:
        db.rollback()
        raise HTTPException(status_code=422, detail={"code": e.code, "message": e.message})


def _line_out(i: CartItem) -> dict:
    return {
        "product_id": i.product_id, "product_name": i.product_name,
        "batch_id": i.batch_id, "batch_number": i.batch_number,
        "quantity": float(i.quantity),
        "unit_buy_price": float(i.unit_buy_price or 0),
        "unit_consumer_price": float(i.unit_consumer_price or 0),
        "unit_sell_price": float(i.unit_sell_price or 0),
        "discount": float(i.discount), "subtotal": float(i.subtotal), "profit": float(i.profit),
        "expiry_date": str(i.expiry_date) if i.expiry_date else None,
        "suggested": i.suggested,
    }


def _totals(items: list[CartItem]) -> dict:
    gross = sum(((i.unit_sell_price or Decimal("0")) * i.quantity for i in items), Decimal("0"))
    discount = sum((i.discount for i in items), Decimal("0"))
    return {
        "gross": float(gross),
        "discount": float(discount),
        "subtotal": float(gross - discount),
        "profit": float(sum((i.profit for i in items), Decimal("0"))),
        "count": len(items),
    }


def _invoice_out(inv) -> dict:
    return {
        "invoice_id": inv.id,
        "invoice_number": inv.invoice_number,
        "subtotal": float(inv.subtotal),
        "discount": float(inv.discount),
        "invoice_discount": float(getattr(inv, "invoice_discount", 0) or 0),
        "tax": float(inv.tax),
        "total_amount": float(inv.total_amount),
        "payment_method": inv.payment_method,
        # exposed so the POS can show "نسیه / روی حساب" instead of implying the
        # money was collected — an ACCOUNT sale is credit, not cash received
        "payment_status": inv.payment_status,
        "status": inv.status,
        "print_status": inv.print_status,
        "customer_id": inv.customer_id,
        "items": [
            {"product_id": it.product_id, "batch_id": it.batch_id, "qty": float(it.qty),
             "qty_display": float(it.qty),
             "unit_buy_price": float(it.unit_buy_price), "unit_sell_price": float(it.unit_sell_price),
             "discount": float(it.discount), "subtotal": float(it.subtotal), "profit": float(it.profit)}
            for it in inv.items
        ],
    }


# --- POS search (§26) ------------------------------------------------------------

@router.get("/search")
def pos_search(q: str, limit: int = 20, db: Session = Depends(get_db),
               _: User = Depends(require_permission("pos.sell"))):
    """Cashier search by barcode, product name, SKU or product code.

    An exact barcode/SKU hit is always returned first so scanning stays instant,
    then partial name matches for typed searches (e.g. «شیر»).
    """
    from ..models import Brand, ProductBatch, Unit
    from sqlalchemy import func as _f

    term = (q or "").strip()
    if not term:
        return {"query": q, "items": []}

    exact = db.execute(
        select(Product).where(
            Product.deleted_at.is_(None),
            (Product.barcode == term) | (_f.lower(Product.sku) == term.lower()),
        )
    ).scalars().all()

    like = f"%{term}%"
    # §18 — brand is searchable too: a cashier types «دماوند» (the brand)
    # far more often than the full product name.
    brand_ids = db.execute(
        select(Brand.id).where(Brand.name.ilike(like))
    ).scalars().all()
    conditions = ((Product.name.ilike(like)) | (Product.barcode.ilike(like))
                  | (Product.sku.ilike(like)) | (Product.model.ilike(like)))
    if brand_ids:
        conditions = conditions | (Product.brand_id.in_(brand_ids))
    partial = db.execute(
        select(Product).where(
            Product.deleted_at.is_(None),
            Product.is_active.is_(True),
            conditions,
        ).order_by(Product.name.asc()).limit(limit)
    ).scalars().all()

    seen: set[int] = set()
    ordered: list[Product] = []
    for p in exact + partial:
        if p.id not in seen:
            seen.add(p.id)
            ordered.append(p)

    items = []
    for p in ordered[:limit]:
        options = pos_svc.get_batch_options(db, p)
        unit = db.get(Unit, p.unit_id) if p.unit_id else None
        total = float(sum((o.batch.current_qty for o in options), 0))
        items.append({
            "product_id": p.id, "name": p.name, "barcode": p.barcode, "sku": p.sku,
            "image_url": p.image_url,
            "unit": {"name": unit.name, "symbol": unit.symbol,
                     "allow_decimal": unit.allow_decimal,
                     "decimals": unit.decimals} if unit else None,
            "available_qty": total,
            "price_count": len({float(o.batch.sell_price) for o in options}),
            "exact": p in exact,
            "batches": [o.as_dict() for o in options],
        })
    return {"query": term, "count": len(items), "items": items}
