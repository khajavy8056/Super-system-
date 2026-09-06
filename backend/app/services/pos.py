"""POS engine: cart, batch allocation, transactional checkout, void, return.

Design rules implemented here (blueprint §1, §4, §16–21, §29, §61):
- Product ≠ Batch. A cart line is (product, batch, qty, prices).
- FIFO/FEFO are *allocation policies* — an accounting allocation, never a claim
  about which physical unit the customer picked up (§17).
- InvoiceItems snapshot prices at sale time (§29).
- The whole sale commits atomically; printer/SMS happen AFTER commit (§20).
- Profit uses the actual selected batch cost (§61).
- Stock deduction and invoice numbering are ATOMIC (no double-sale / duplicate
  invoice numbers under concurrent terminals).
- Discounts are counted exactly once: total = gross − Σdiscount + tax(gross−Σdiscount).

Phase-0 fixes (2026-09-04 audit): BUG-001 (discount double count), BUG-002
(returns exceeding purchases), BUG-003 (no cross-batch allocation), BUG-004
(invoice numbering race), BUG-005 (non-atomic deduction), BUG-019 (refund states).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..models import (
    Counter,
    Invoice,
    InvoiceItem,
    Payment,
    Product,
    ProductBatch,
    Return,
    StockMovement,
    SystemSetting,
    User,
)
from . import expiry as expiry_svc
from .audit import write_audit
from .units import QuantityError, to_qty, validate_for_unit

ZERO = Decimal("0")
CENT = Decimal("0.01")


class PosError(Exception):
    """Business-level POS error with a machine-readable code (blueprint §102)."""
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class CartItem:
    product_id: int
    quantity: Decimal = Decimal("1")
    batch_id: int | None = None
    unit_sell_price: Decimal | None = None
    unit_buy_price: Decimal | None = None
    unit_consumer_price: Decimal | None = None
    discount: Decimal = ZERO
    tax: Decimal = ZERO
    subtotal: Decimal = ZERO
    profit: Decimal = ZERO
    # filled during validation:
    product_name: str = ""
    batch_number: str | None = None
    expiry_date: date | None = None
    suggested: bool = False


@dataclass
class BatchOption:
    batch: ProductBatch
    days_left: int | None
    is_recommended: bool = False
    reason: str = ""

    def as_dict(self) -> dict:
        return {
            "batch_id": self.batch.id,
            "batch_number": self.batch.batch_number,
            "buy_price": float(self.batch.buy_price),
            "consumer_price": float(self.batch.consumer_price),
            "sell_price": float(self.batch.sell_price),
            "current_qty": self.batch.current_qty,
            "expiry_date": str(self.batch.expiry_date) if self.batch.expiry_date else None,
            "days_left": self.days_left,
            "is_recommended": self.is_recommended,
            "reason": self.reason,
        }


def get_setting(db: Session, key: str, default: str) -> str:
    row = db.execute(select(SystemSetting).where(SystemSetting.key == key)).scalar_one_or_none()
    return row.value if row else default


def allocation_policy(db: Session) -> str:
    return get_setting(db, "pos.allocation_policy", "HYBRID").upper()


def sellable_batches(db: Session, product: Product) -> list[ProductBatch]:
    """Active batches with stock, ordered by the configured allocation policy.

    FEFO → nearest expiry first; FIFO → oldest received first;
    HYBRID → expiry risk first, then oldest purchase. Expired batches are
    excluded when the block-sale policy is on.
    """
    today = date.today()
    batches = list(
        db.execute(
            select(ProductBatch).where(
                ProductBatch.product_id == product.id,
                ProductBatch.current_qty > 0,
                ProductBatch.status.in_(["ACTIVE"]),
            )
        ).scalars()
    )
    if expiry_svc.block_expired_policy(db):
        batches = [b for b in batches if not (b.expiry_date and b.expiry_date < today)]

    policy = allocation_policy(db)

    def sort_key(b: ProductBatch):
        if policy == "FIFO":
            return (b.production_date or b.received_at, b.received_at, b.expiry_date or date.max)
        # FEFO and HYBRID both prioritise expiry risk, HYBRID breaks ties by oldest received.
        return (b.expiry_date is None, b.expiry_date or date.max, b.received_at)

    return sorted(batches, key=sort_key)


def get_batch_options(db: Session, product: Product) -> list[BatchOption]:
    """Active (sellable) batches with expiry info + a recommendation."""
    today = date.today()
    policy = allocation_policy(db)
    options: list[BatchOption] = []
    for i, b in enumerate(sellable_batches(db, product)):
        opt = BatchOption(batch=b, days_left=expiry_svc.days_until(b, today))
        if i == 0:
            opt.is_recommended = True
            opt.reason = f"Recommended by {policy} policy"
        options.append(opt)
    return options


def recommend_batch(db: Session, product: Product) -> ProductBatch | None:
    batches = sellable_batches(db, product)
    return batches[0] if batches else None


def available_qty(db: Session, product: Product) -> Decimal:
    """Total sellable quantity across batches (decimal-aware, §25)."""
    return sum((to_qty(b.current_qty) for b in sellable_batches(db, product)), ZERO)


def allocate(db: Session, product: Product, qty: Decimal) -> list[tuple[ProductBatch, Decimal]]:
    """Accounting allocation of ``qty`` across sellable batches per policy.

    This is an inventory-accounting allocation (which batch's cost/stock is
    consumed) — NOT a claim about which physical unit the customer took (§17).
    The cashier may always override with an explicit batch selection.
    """
    qty = to_qty(qty)
    if qty <= 0:
        raise PosError("INVALID_QUANTITY", "Quantity must be positive")
    remaining = qty
    allocation: list[tuple[ProductBatch, Decimal]] = []
    for b in sellable_batches(db, product):
        take = min(remaining, to_qty(b.current_qty))
        if take > 0:
            allocation.append((b, take))
            remaining -= take
        if remaining == 0:
            break
    if remaining > 0:
        raise PosError(
            "INSUFFICIENT_STOCK",
            f"Only {qty - remaining} available for {product.name} across its batches",
        )
    return allocation


def _apportion(total: Decimal, parts: list[Decimal]) -> list[Decimal]:
    """Split ``total`` proportionally over ``parts`` (ints) without losing cents.
    The last part absorbs the rounding remainder so Σparts == total."""
    if not parts:
        return []
    whole = sum((Decimal(p) for p in parts), ZERO)
    if whole == 0:
        return [ZERO] * len(parts)
    out = [((total * Decimal(p)) / whole).quantize(CENT, ROUND_HALF_UP) for p in parts[:-1]]
    out.append((total - sum(out, ZERO)).quantize(CENT, ROUND_HALF_UP))
    return out


def _default_sell_price(db: Session, product: Product) -> Decimal | None:
    """ADR-001: batch price first, active PriceVersion as fallback."""
    from .pricing import active_price

    return active_price(db, product.id, "SELL")


def _resolve_cart_line(db: Session, item: CartItem) -> CartItem:
    """Resolve and price a cart line that is bound to a specific batch."""
    product = db.get(Product, item.product_id)
    if not product or product.deleted_at is not None:
        raise PosError("PRODUCT_NOT_FOUND", f"Product {item.product_id} not found")
    try:
        item.quantity = validate_for_unit(db, product, item.quantity)
    except QuantityError as exc:
        raise PosError("INVALID_QUANTITY", str(exc))
    if item.quantity <= 0:
        raise PosError("INVALID_QUANTITY", "Quantity must be positive")
    if item.discount is None or item.discount < 0:
        raise PosError("INVALID_DISCOUNT", "Discount cannot be negative")
    if item.discount > 0 and item.unit_sell_price is not None and \
            item.discount > item.unit_sell_price * item.quantity:
        raise PosError("INVALID_DISCOUNT", "Discount exceeds the line amount")

    item.product_name = product.name

    if item.batch_id is None:  # auto: single recommended batch if it fits
        batch = recommend_batch(db, product)
        if not batch:
            raise PosError("INSUFFICIENT_STOCK", f"No available batch for {product.name}")
        item.batch_id = batch.id
        item.suggested = True

    batch = db.get(ProductBatch, item.batch_id)
    if not batch or batch.product_id != product.id:
        raise PosError("BATCH_NOT_FOUND", "Selected batch does not belong to this product")

    if batch.current_qty <= 0 or batch.status != "ACTIVE":
        raise PosError("INSUFFICIENT_STOCK", f"Batch {batch.batch_number} has no stock")

    if expiry_svc.block_expired_policy(db) and batch.expiry_date and batch.expiry_date < date.today():
        raise PosError("BATCH_EXPIRED", f"Batch {batch.batch_number} is expired and blocked for sale")

    if item.quantity > to_qty(batch.current_qty):
        others = available_qty(db, product) - to_qty(batch.current_qty)
        hint = f" ({others} more available in other batches)" if others > 0 else ""
        raise PosError(
            "INSUFFICIENT_STOCK",
            f"Only {batch.current_qty} available from batch {batch.batch_number}{hint}",
        )

    item.unit_buy_price = item.unit_buy_price if item.unit_buy_price is not None else batch.buy_price
    item.unit_consumer_price = (
        item.unit_consumer_price if item.unit_consumer_price is not None else batch.consumer_price
    )
    if item.unit_sell_price is None:
        item.unit_sell_price = batch.sell_price
        if item.unit_sell_price is None or item.unit_sell_price == 0:
            item.unit_sell_price = _default_sell_price(db, product)  # ADR-001 fallback

    if item.unit_sell_price is None:
        raise PosError("PRICE_NOT_AVAILABLE", f"No sell price for {product.name}")
    if item.unit_buy_price is None:
        item.unit_buy_price = ZERO

    item.batch_number = batch.batch_number
    item.expiry_date = batch.expiry_date

    gross = (item.unit_sell_price * item.quantity).quantize(CENT, ROUND_HALF_UP)
    item.subtotal = (gross - item.discount).quantize(CENT, ROUND_HALF_UP)  # line net
    item.profit = (
        (item.unit_sell_price - item.unit_buy_price) * item.quantity - item.discount
    ).quantize(CENT, ROUND_HALF_UP)
    return item


def validate_cart(db: Session, items: list[CartItem]) -> list[CartItem]:
    """Expand auto lines across batches (allocation policy), merge duplicates,
    then price every line (no writes)."""
    expanded: list[CartItem] = []
    for it in items:
        if it.batch_id is not None:
            expanded.append(it)
            continue
        product = db.get(Product, it.product_id)
        if not product or product.deleted_at is not None:
            raise PosError("PRODUCT_NOT_FOUND", f"Product {it.product_id} not found")
        allocation = allocate(db, product, it.quantity)
        shares = _apportion(it.discount, [q for _, q in allocation])
        for (batch, take), share in zip(allocation, shares):
            expanded.append(
                CartItem(
                    product_id=it.product_id, quantity=take, batch_id=batch.id,
                    unit_sell_price=it.unit_sell_price, discount=share, suggested=True,
                )
            )

    # Merge identical (product, batch) lines so repeated scans stay on one row (§16).
    merged: dict[tuple[int, int], CartItem] = {}
    for it in expanded:
        key = (it.product_id, it.batch_id or 0)
        if key in merged:
            merged[key].quantity += it.quantity
            merged[key].discount += it.discount
        else:
            merged[key] = it

    return [_resolve_cart_line(db, line) for line in merged.values()]


# --- Atomic invoice numbering (BUG-004) --------------------------------------

def _next_invoice_number(db: Session) -> str:
    """Gap-free-per-day invoice numbers via an atomic counter row.

    ``UPDATE counters SET value = value + 1`` is atomic under concurrency (the
    DB serialises the write), so two concurrent checkouts can never collide —
    unlike the previous COUNT-based approach which raced and re-used numbers.
    """
    today = datetime.utcnow().strftime("%Y%m%d")
    key = f"invoice:{today}"
    for attempt in range(3):
        row = db.execute(select(Counter).where(Counter.name == key)).scalar_one_or_none()
        if row is None:
            try:
                db.add(Counter(name=key, value=1))
                db.flush()
                return f"INV-{today}-{1:06d}"
            except IntegrityError:
                db.rollback()  # another terminal created it first; retry the update path
                continue
        new_val = db.execute(
            update(Counter).where(Counter.name == key).values(value=Counter.value + 1)
        )
        if new_val.rowcount != 1:
            continue
        val = db.execute(select(Counter.value).where(Counter.name == key)).scalar_one()
        return f"INV-{today}-{val:06d}"
    raise PosError("NUMBERING_FAILED", "Could not allocate an invoice number; please retry")


def _atomic_deduct(db: Session, batch_id: int, qty: Decimal) -> None:
    """Atomically deduct stock: UPDATE ... WHERE current_qty >= qty.

    Under two concurrent terminals selling the same batch, exactly one UPDATE
    succeeds per available unit — overselling is impossible regardless of the
    pre-validation reads (BUG-005)."""
    from sqlalchemy import case

    qty = to_qty(qty)
    res = db.execute(
        update(ProductBatch)
        .where(
            ProductBatch.id == batch_id,
            ProductBatch.current_qty >= qty,
            ProductBatch.status == "ACTIVE",
        )
        .values(
            current_qty=ProductBatch.current_qty - qty,
            status=case(
                (ProductBatch.current_qty - qty == 0, "SOLD_OUT"),
                else_="ACTIVE",
            ),
        )
    )
    if res.rowcount != 1:
        raise PosError(
            "INSUFFICIENT_STOCK",
            f"Stock changed for batch #{batch_id} during checkout; please retry",
        )


def checkout(
    db: Session,
    *,
    items: list[CartItem],
    payments: list[dict],
    user: User | None = None,
    customer_id: int | None = None,
    tax_rate: Decimal | None = None,
    coupon_code: str | None = None,
    invoice_discount: Decimal | None = None,
) -> Invoice:
    """Atomic checkout (blueprint §18–21). Caller wraps in try/except + commit/rollback.

    Money math (BUG-001): gross = Σ(price×qty); discount = Σ(line discounts);
    taxable = gross − discount; tax = taxable × rate; total = taxable + tax.
    Each discount is counted exactly once."""
    if not items:
        raise PosError("EMPTY_CART", "Cart is empty")

    resolved = validate_cart(db, items)

    gross = sum(((i.unit_sell_price or ZERO) * i.quantity for i in resolved), ZERO)
    discount = sum((i.discount for i in resolved), ZERO)
    if discount > gross:
        raise PosError("INVALID_DISCOUNT", "Total discount exceeds cart amount")

    # §12 — invoice-level discount, applied after line discounts, before coupon.
    inv_disc = Decimal(str(invoice_discount)) if invoice_discount else ZERO
    if inv_disc < 0:
        raise PosError("INVALID_DISCOUNT", "Invoice discount cannot be negative")
    if inv_disc > gross - discount:
        raise PosError("INVALID_DISCOUNT", "Invoice discount exceeds cart amount")
    discount += inv_disc

    # Coupon is evaluated against the post-line-discount amount, then consumed
    # inside this same transaction (§37–38) so a failed sale never burns it.
    coupon_info = None
    if coupon_code:
        from . import coupons as coupon_svc

        phone = None
        if customer_id:
            from ..models import Customer as _Customer
            cust = db.get(_Customer, customer_id)
            phone = cust.phone if cust else None
        try:
            coupon_info = coupon_svc.evaluate(
                db, code=coupon_code, amount=gross - discount,
                customer_id=customer_id, customer_phone=phone,
            )
        except coupon_svc.CouponError as exc:
            raise PosError(exc.code, exc.message)
        discount += coupon_info["discount"]
        if discount > gross:
            discount = gross

    taxable = gross - discount
    rate = tax_rate if tax_rate is not None else Decimal(get_setting(db, "pos.tax_rate", "0"))
    tax = (taxable * rate / 100).quantize(CENT, ROUND_HALF_UP)
    total = (taxable + tax).quantize(CENT, ROUND_HALF_UP)

    paid_total = sum((Decimal(p["amount"]) for p in payments), ZERO)
    if abs(paid_total - total) > CENT:
        raise PosError("PAYMENT_MISMATCH", f"Paid {paid_total} but total is {total}")

    # "افزودن به حساب دفتری" (§34): an ACCOUNT tender is not cash received —
    # it is credit extended, so it requires a registered customer. A walk-in
    # (customer_id IS NULL) has no account to charge, and silently treating
    # that as paid would invent revenue that never arrives.
    on_account = sum(
        (Decimal(p["amount"]) for p in payments
         if str(p.get("method", "CASH")).upper() == "ACCOUNT"), ZERO)
    if on_account > ZERO and not customer_id:
        raise PosError(
            "ACCOUNT_REQUIRES_CUSTOMER",
            "فروش نسیه فقط برای مشتری ثبت‌شده ممکن است؛ مشتری آزاد حساب دفتری ندارد",
        )

    invoice = Invoice(
        invoice_number=_next_invoice_number(db),
        customer_id=customer_id,
        subtotal=gross,  # gross of lines (pre-discount)
        discount=discount,
        invoice_discount=inv_disc,
        tax=tax,
        total_amount=total,
        payment_method=_payment_method(payments),
        payment_status=("ON_ACCOUNT" if on_account >= total
                        else ("PARTIAL" if on_account > ZERO else "PAID")),
        status="PAID",
        print_status="PENDING",
        paid_at=None if on_account >= total else datetime.utcnow(),
        created_by=user.id if user else None,
    )
    db.add(invoice)
    db.flush()

    for it in resolved:
        # Authoritative atomic deduction (not the ORM read above).
        _atomic_deduct(db, it.batch_id, it.quantity)
        db.add(InvoiceItem(
            invoice_id=invoice.id,
            product_id=it.product_id,
            batch_id=it.batch_id,
            qty=it.quantity,
            unit_buy_price=it.unit_buy_price or ZERO,
            unit_consumer_price=it.unit_consumer_price or ZERO,
            unit_sell_price=it.unit_sell_price or ZERO,
            discount=it.discount,
            tax=ZERO,
            subtotal=it.subtotal,
            profit=it.profit,
            created_at=datetime.utcnow(),
        ))
        db.add(StockMovement(
            product_id=it.product_id,
            batch_id=it.batch_id,
            movement_type="SALE_OUT",
            quantity=-it.quantity,
            reference_type="Invoice",
            reference_id=invoice.id,
            unit_cost=it.unit_buy_price,
            created_by=user.id if user else None,
        ))

    if coupon_info is not None:
        from . import coupons as coupon_svc

        try:
            coupon_svc.consume(
                db, coupon_id=coupon_info["coupon_id"], amount=coupon_info["discount"],
                invoice_id=invoice.id, customer_id=customer_id, user=user,
            )
        except coupon_svc.CouponError as exc:
            raise PosError(exc.code, exc.message)

    for p in payments:
        db.add(Payment(invoice_id=invoice.id, method=p.get("method", "CASH"), amount=Decimal(p["amount"])))

    # Charge the credit portion to the customer account in THIS transaction, so
    # a later failure rolls the debt back with the sale (§32).
    if on_account > ZERO:
        from . import ledger as ledger_svc

        try:
            ledger_svc.post_entry(
                db, customer_id=customer_id, entry_type="CREDIT_SALE",
                amount=on_account, invoice_id=invoice.id,
                note=f"فاکتور {invoice.invoice_number}",
                user_id=user.id if user else None,
            )
        except ledger_svc.LedgerError as exc:
            raise PosError(exc.code, str(exc))

    write_audit(
        db, action="SALE_CREATED", user_id=user.id if user else None,
        entity_type="Invoice", entity_id=invoice.id,
        after={"invoice_number": invoice.invoice_number, "total": str(total),
               "coupon": coupon_info["code"] if coupon_info else None},
    )
    invoice.applied_coupon_code = coupon_info["code"] if coupon_info else None  # transient
    return invoice


def _payment_method(payments: list[dict]) -> str:
    methods = {p.get("method", "CASH") for p in payments}
    return "MIXED" if len(methods) > 1 else (methods.pop() if methods else "CASH")


def void_invoice(db: Session, *, invoice: Invoice, user: User | None = None, reason: str | None = None) -> Invoice:
    """Void a PAID invoice: restock batches + reverse movements + audit (§84)."""
    if invoice.status == "VOID":
        raise PosError("ALREADY_VOID", "Invoice is already void")
    if invoice.status not in ("PAID", "PENDING"):
        raise PosError("INVALID_STATE", f"Cannot void invoice in state {invoice.status}")

    for item in invoice.items:
        if item.batch_id:
            batch = db.get(ProductBatch, item.batch_id)
            if batch:
                batch.current_qty = to_qty(batch.current_qty) + to_qty(item.qty)
                if batch.status == "SOLD_OUT":
                    batch.status = "ACTIVE"
                db.add(StockMovement(
                    product_id=item.product_id, batch_id=item.batch_id,
                    movement_type="VOID_REVERSAL", quantity=item.qty,
                    reference_type="Invoice", reference_id=invoice.id,
                    unit_cost=item.unit_buy_price, note=f"Void: {reason or ''}",
                    created_by=user.id if user else None,
                ))
    invoice.status = "VOID"
    invoice.payment_status = "VOID"
    write_audit(
        db, action="SALE_VOIDED", user_id=user.id if user else None,
        entity_type="Invoice", entity_id=invoice.id, reference=reason,
    )
    return invoice


def returned_qty_for_item(db: Session, invoice_item_id: int) -> Decimal:
    """Total already-returned quantity for an invoice line (completed returns)."""
    return to_qty(
        db.execute(
            select(func.coalesce(func.sum(Return.qty), 0)).where(
                Return.invoice_item_id == invoice_item_id,
                Return.status == "COMPLETED",
            )
        ).scalar_one()
    )


def process_return(
    db: Session,
    *,
    invoice: Invoice,
    invoice_item: InvoiceItem,
    qty: Decimal,
    user: User | None = None,
    reason: str | None = None,
    refund_amount: Decimal | None = None,
) -> Return:
    """Batch-aware return with a cumulative cap (BUG-002) and honest states (BUG-019)."""
    if invoice.status not in ("PAID", "PARTIALLY_REFUNDED", "REFUNDED"):
        raise PosError("INVALID_STATE", "Can only return from a paid invoice")
    qty = to_qty(qty)
    if qty <= 0:
        raise PosError("INVALID_QUANTITY", "Return quantity must be positive")

    already = returned_qty_for_item(db, invoice_item.id)
    if already + qty > to_qty(invoice_item.qty):
        raise PosError(
            "RETURN_EXCEEDS_PURCHASE",
            f"Only {to_qty(invoice_item.qty) - already} of this line can still be returned "
            f"({already} already returned of {invoice_item.qty})",
        )

    if invoice_item.batch_id:
        batch = db.get(ProductBatch, invoice_item.batch_id)
        if batch:
            batch.current_qty = to_qty(batch.current_qty) + qty
            if batch.status == "SOLD_OUT":
                batch.status = "ACTIVE"
            db.add(StockMovement(
                product_id=invoice_item.product_id, batch_id=batch.id,
                movement_type="RETURN_IN", quantity=qty,
                reference_type="Return", reference_id=invoice_item.id,
                unit_cost=invoice_item.unit_buy_price, note=reason,
                created_by=user.id if user else None,
            ))

    ret = Return(
        invoice_id=invoice.id,
        invoice_item_id=invoice_item.id,
        batch_id=invoice_item.batch_id,
        qty=qty,
        reason=reason,
        refund_amount=refund_amount or (invoice_item.unit_sell_price * qty),
        status="COMPLETED",
        created_by=user.id if user else None,
    )
    db.add(ret)
    db.flush()

    # Invoice state reflects the aggregated returns of ALL its lines (BUG-019).
    all_items = list(invoice.items)
    fully_returned = all(
        returned_qty_for_item(db, i.id) >= to_qty(i.qty) for i in all_items
    )
    invoice.status = "REFUNDED" if fully_returned else "PARTIALLY_REFUNDED"

    write_audit(
        db, action="SALE_REFUNDED", user_id=user.id if user else None,
        entity_type="Invoice", entity_id=invoice.id,
        after={"return_id": ret.id, "qty": qty}, reference=reason,
    )
    return ret
