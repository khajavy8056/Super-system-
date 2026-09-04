"""POS engine: cart, batch recommendation, transactional checkout, void, return.

Design rules implemented here:
- Product ≠ Batch (§1). A cart line is (product, batch, qty, prices).
- FIFO/FEFO are *allocation policies*, never physical truth (§4, §33–35).
- InvoiceItems snapshot prices at sale time (§29).
- The whole sale commits atomically: invoice + items + payments + batch
  deduction + movements + profit (§19). Printer/SMS happen AFTER commit (§20).
- Profit uses the actual selected batch cost (§61, §158).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import (
    Customer,
    Invoice,
    InvoiceItem,
    Payment,
    Product,
    ProductBatch,
    StockMovement,
    SystemSetting,
    User,
)
from . import expiry as expiry_svc
from .audit import write_audit
from .notifications import notify

ZERO = Decimal("0")


class PosError(Exception):
    """Business-level POS error with a machine-readable code (blueprint §102)."""
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class CartItem:
    product_id: int
    quantity: int = 1
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


def get_batch_options(db: Session, product: Product) -> list[BatchOption]:
    """Active (sellable) batches with expiry info + a recommendation."""
    today = date.today()
    batches = [
        b for b in db.execute(
            select(ProductBatch).where(
                ProductBatch.product_id == product.id,
                ProductBatch.current_qty > 0,
                ProductBatch.status.in_(["ACTIVE"]),
            )
        ).scalars()
    ]
    if expiry_svc.block_expired_policy(db):
        batches = [b for b in batches if not (b.expiry_date and b.expiry_date < today)]

    policy = allocation_policy(db)
    # Sort: FEFO -> nearest expiry first; FIFO -> oldest received first.
    def sort_key(b: ProductBatch):
        if policy == "FEFO":
            return (b.expiry_date is None, b.expiry_date or date.max, b.production_date or date.max, b.received_at)
        if policy == "FIFO":
            return (b.production_date or b.received_at, b.received_at, b.expiry_date or date.max)
        # HYBRID: expiry risk first, then oldest purchase (cheaper) first.
        return (b.expiry_date is None, b.expiry_date or date.max, b.received_at)

    ordered = sorted(batches, key=sort_key)
    options: list[BatchOption] = []
    for i, b in enumerate(ordered):
        opt = BatchOption(batch=b, days_left=expiry_svc.days_until(b, today))
        if i == 0:
            opt.is_recommended = True
            opt.reason = f"Recommended by {policy} policy"
        options.append(opt)
    return options


def recommend_batch(db: Session, product: Product) -> ProductBatch | None:
    options = get_batch_options(db, product)
    return options[0].batch if options else None


def _resolve_cart_line(db: Session, item: CartItem) -> CartItem:
    product = db.get(Product, item.product_id)
    if not product or product.deleted_at is not None:
        raise PosError("PRODUCT_NOT_FOUND", f"Product {item.product_id} not found")
    if item.quantity <= 0:
        raise PosError("INVALID_QUANTITY", "Quantity must be positive")

    item.product_name = product.name

    if item.batch_id is None:
        # AUTO / HYBRID: pick the recommendation, then let the caller confirm.
        batch = recommend_batch(db, product)
        if not batch:
            raise PosError("INSUFFICIENT_STOCK", f"No available batch for {product.name}")
        item.batch_id = batch.id
        item.suggested = True
    else:
        batch = db.get(ProductBatch, item.batch_id)
        if not batch or batch.product_id != product.id:
            raise PosError("BATCH_NOT_FOUND", "Selected batch does not belong to this product")

    if batch.current_qty <= 0 or batch.status != "ACTIVE":
        raise PosError("INSUFFICIENT_STOCK", f"Batch {batch.batch_number} has no stock")

    if expiry_svc.block_expired_policy(db) and batch.expiry_date and batch.expiry_date < date.today():
        raise PosError("BATCH_EXPIRED", f"Batch {batch.batch_number} is expired and blocked for sale")

    if item.quantity > batch.current_qty:
        raise PosError(
            "INSUFFICIENT_STOCK",
            f"Only {batch.current_qty} available from batch {batch.batch_number}",
        )

    item.unit_buy_price = item.unit_buy_price or batch.buy_price
    item.unit_consumer_price = item.unit_consumer_price or batch.consumer_price
    item.unit_sell_price = item.unit_sell_price or batch.sell_price

    if item.unit_sell_price is None:
        raise PosError("PRICE_NOT_AVAILABLE", f"No sell price for {product.name}")
    if item.unit_buy_price is None:
        item.unit_buy_price = ZERO

    item.batch_number = batch.batch_number
    item.expiry_date = batch.expiry_date

    gross = item.unit_sell_price * item.quantity
    item.subtotal = gross - item.discount
    item.profit = (item.unit_sell_price - item.unit_buy_price) * item.quantity - item.discount
    return item


def validate_cart(db: Session, items: list[CartItem]) -> list[CartItem]:
    """Resolve batches + validate stock for every cart line (no writes)."""
    resolved = [_resolve_cart_line(db, i) for i in items]

    # Merge identical (product, batch) lines so repeated scans stay on one row (§16).
    merged: dict[tuple[int, int], CartItem] = {}
    for it in resolved:
        key = (it.product_id, it.batch_id)
        if key in merged:
            existing = merged[key]
            existing.quantity += it.quantity
            existing.discount += it.discount
        else:
            merged[key] = it
    final = list(merged.values())
    for it in final:
        it = _resolve_cart_line(db, it)
    return final


def _next_invoice_number(db: Session) -> str:
    today = datetime.utcnow().strftime("%Y%m%d")
    prefix = f"INV-{today}-"
    from sqlalchemy import func
    count = db.execute(
        select(func.count()).select_from(Invoice).where(Invoice.invoice_number.like(f"{prefix}%"))
    ).scalar_one()
    return f"{prefix}{int(count) + 1:06d}"


def checkout(
    db: Session,
    *,
    items: list[CartItem],
    payments: list[dict],
    user: User | None = None,
    customer_id: int | None = None,
    tax_rate: Decimal | None = None,
) -> Invoice:
    """Atomic checkout (blueprint §18–21). Caller wraps in try/except + commit/rollback."""
    if not items:
        raise PosError("EMPTY_CART", "Cart is empty")

    resolved = validate_cart(db, items)

    # Re-validate against DB stock right before commit.
    for it in resolved:
        batch = db.get(ProductBatch, it.batch_id)
        if batch.current_qty < it.quantity or batch.status != "ACTIVE":
            raise PosError("INSUFFICIENT_STOCK", f"Stock changed for batch {batch.batch_number}")

    subtotal = sum((i.subtotal for i in resolved), ZERO)
    discount = sum((i.discount for i in resolved), ZERO)
    rate = tax_rate if tax_rate is not None else Decimal(get_setting(db, "pos.tax_rate", "0"))
    tax = ((subtotal - discount) * rate / 100).quantize(Decimal("0.01"))
    total = subtotal - discount + tax

    paid_total = sum((Decimal(p["amount"]) for p in payments), ZERO)
    if abs(paid_total - total) > Decimal("0.01"):
        raise PosError("PAYMENT_MISMATCH", f"Paid {paid_total} but total is {total}")

    invoice = Invoice(
        invoice_number=_next_invoice_number(db),
        customer_id=customer_id,
        subtotal=subtotal,
        discount=discount,
        tax=tax,
        total_amount=total,
        payment_method=_payment_method(payments),
        payment_status="PAID",
        status="PAID",
        print_status="PENDING",
        paid_at=datetime.utcnow(),
        created_by=user.id if user else None,
    )
    db.add(invoice)
    db.flush()

    for it in resolved:
        batch = db.get(ProductBatch, it.batch_id)
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
        batch.current_qty -= it.quantity
        if batch.current_qty == 0:
            batch.status = "SOLD_OUT"
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

    for p in payments:
        db.add(Payment(invoice_id=invoice.id, method=p.get("method", "CASH"), amount=Decimal(p["amount"])))

    write_audit(
        db, action="SALE_CREATED", user_id=user.id if user else None,
        entity_type="Invoice", entity_id=invoice.id,
        after={"invoice_number": invoice.invoice_number, "total": str(total)},
    )
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
                batch.current_qty += item.qty
                if batch.status == "SOLD_OUT":
                    batch.status = "ACTIVE"
                db.add(StockMovement(
                    product_id=item.product_id, batch_id=item.batch_id,
                    movement_type="RETURN_IN", quantity=item.qty,
                    reference_type="Invoice", reference_id=invoice.id,
                    unit_cost=item.unit_buy_price, note=f"Void {reason or ''}",
                    created_by=user.id if user else None,
                ))
    invoice.status = "VOID"
    invoice.payment_status = "VOID"
    write_audit(
        db, action="SALE_VOIDED", user_id=user.id if user else None,
        entity_type="Invoice", entity_id=invoice.id, reference=reason,
    )
    return invoice


def process_return(
    db: Session,
    *,
    invoice: Invoice,
    invoice_item: InvoiceItem,
    qty: int,
    user: User | None = None,
    reason: str | None = None,
    refund_amount: Decimal | None = None,
) -> "Return":
    """Batch-aware return: restock the exact original batch (§60)."""
    from ..models import Return

    if invoice.status not in ("PAID", "PARTIALLY_REFUNDED"):
        raise PosError("INVALID_STATE", "Can only return from a paid invoice")
    if qty <= 0 or qty > invoice_item.qty:
        raise PosError("INVALID_QUANTITY", "Return quantity out of range")

    if invoice_item.batch_id:
        batch = db.get(ProductBatch, invoice_item.batch_id)
        if batch:
            batch.current_qty += qty
            if batch.status == "SOLD_OUT":
                batch.status = "ACTIVE"
            db.add(StockMovement(
                product_id=invoice_item.product_id, batch_id=batch.id,
                movement_type="RETURN_IN", quantity=qty,
                reference_type="Return", reference_id=0,
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
    invoice.status = "PARTIALLY_REFUNDED"
    write_audit(
        db, action="SALE_REFUNDED", user_id=user.id if user else None,
        entity_type="Invoice", entity_id=invoice.id, reference=reason,
    )
    return ret
