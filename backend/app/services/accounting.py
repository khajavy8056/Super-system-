"""Double-entry accounting engine (v1.4).

Public surface
--------------
ensure_chart(db)                       seed the default chart + fiscal year (idempotent)
post(db, kind, lines, ...)             balanced journal entry (raises AccountingError)
reverse(db, entry_id, ...)             append a mirror entry, mark original REVERSED
post_sale / post_sale_return / post_purchase / post_waste / post_settlement
                                        automatic postings from operational documents
record_expense / record_cheque / clear_cheque / bounce_cheque
open_cash_session / close_cash_session
trial_balance / general_ledger / income_statement / balance_sheet / account_balance
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from ..models import (
    Account, CashSession, Cheque, Expense, ExpenseCategory, FiscalPeriod,
    Invoice, InvoiceItem, JournalEntry, JournalLine, Payment, ProductBatch,
    Return, Supplier, User,
)
from ..models.accounting import DEBIT_NORMAL
from .audit import write_audit

ZERO = Decimal("0")
CENT = Decimal("0.01")




def _local_date(dt):
    """Store-local calendar date of a naive-UTC timestamp (Tehran day ≠ UTC day after 20:30 UTC)."""
    from .timeservice import utc_to_local, local_today
    if dt is None:
        return local_today()
    loc = utc_to_local(dt)
    return (loc or dt).date()

def _lt_today():
    from .timeservice import local_today
    return local_today()


def _lt_now():
    from .timeservice import local_now
    return local_now()

class AccountingError(ValueError):
    def __init__(self, code: str, message: str = ""):
        super().__init__(message or code)
        self.code = code


def _m(v) -> Decimal:
    return Decimal(str(v or 0)).quantize(CENT, ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# Chart of accounts (کدینگ پیش‌فرض فروشگاهی)
# ---------------------------------------------------------------------------
# code, name, class, parent_code, postable
DEFAULT_CHART: list[tuple[str, str, str, str | None, bool]] = [
    ("1000", "دارایی‌ها", "ASSET", None, False),
    ("1100", "موجودی نقد و بانک", "ASSET", "1000", False),
    ("1101", "صندوق", "ASSET", "1100", True),
    ("1102", "بانک", "ASSET", "1100", True),
    ("1103", "کارت‌خوان (پوز بانکی)", "ASSET", "1100", True),
    ("1104", "چک‌های دریافتنی", "ASSET", "1100", True),
    ("1200", "حساب‌های دریافتنی", "ASSET", "1000", False),
    ("1201", "بدهکاران تجاری (مشتریان)", "ASSET", "1200", True),
    ("1300", "موجودی کالا", "ASSET", "1000", False),
    ("1301", "موجودی کالای فروشگاه", "ASSET", "1300", True),
    ("1400", "دارایی ثابت", "ASSET", "1000", False),
    ("1401", "تجهیزات و اثاثه", "ASSET", "1400", True),
    ("2000", "بدهی‌ها", "LIABILITY", None, False),
    ("2100", "حساب‌های پرداختنی", "LIABILITY", "2000", False),
    ("2101", "بستانکاران تجاری (تأمین‌کنندگان)", "LIABILITY", "2100", True),
    ("2102", "چک‌های پرداختنی", "LIABILITY", "2100", True),
    ("2200", "مالیات و عوارض", "LIABILITY", "2000", False),
    ("2201", "مالیات بر ارزش افزوده پرداختنی", "LIABILITY", "2200", True),
    ("2300", "سایر بدهی‌ها", "LIABILITY", "2000", False),
    ("2301", "پیش‌دریافت مشتریان", "LIABILITY", "2300", True),
    ("3000", "حقوق صاحبان سهام", "EQUITY", None, False),
    ("3101", "سرمایه", "EQUITY", "3000", True),
    ("3102", "برداشت شخصی", "EQUITY", "3000", True),
    ("3201", "سود (زیان) انباشته", "EQUITY", "3000", True),
    ("3202", "سود (زیان) دورهٔ جاری", "EQUITY", "3000", True),
    ("4000", "درآمدها", "REVENUE", None, False),
    ("4101", "فروش کالا", "REVENUE", "4000", True),
    ("4102", "برگشت از فروش", "REVENUE", "4000", True),
    ("4103", "تخفیفات فروش", "REVENUE", "4000", True),
    ("4201", "سایر درآمدها", "REVENUE", "4000", True),
    ("5000", "بهای تمام‌شدهٔ کالای فروش‌رفته", "COGS", None, False),
    ("5101", "بهای تمام‌شدهٔ فروش", "COGS", "5000", True),
    ("5102", "ضایعات و کسری انبار", "COGS", "5000", True),
    ("5103", "اضافات انبار (اصلاح)", "COGS", "5000", True),
    ("6000", "هزینه‌ها", "EXPENSE", None, False),
    ("6101", "اجاره", "EXPENSE", "6000", True),
    ("6102", "حقوق و دستمزد", "EXPENSE", "6000", True),
    ("6103", "آب، برق، گاز و تلفن", "EXPENSE", "6000", True),
    ("6104", "حمل و نقل", "EXPENSE", "6000", True),
    ("6105", "تبلیغات و بازاریابی", "EXPENSE", "6000", True),
    ("6106", "تعمیر و نگهداری", "EXPENSE", "6000", True),
    ("6107", "ملزومات و بسته‌بندی", "EXPENSE", "6000", True),
    ("6108", "کارمزد بانکی و کارت‌خوان", "EXPENSE", "6000", True),
    ("6109", "پیامک و اینترنت", "EXPENSE", "6000", True),
    ("6110", "چک برگشتی (زیان)", "EXPENSE", "6000", True),
    ("6199", "سایر هزینه‌ها", "EXPENSE", "6000", True),
]

DEFAULT_EXPENSE_CATEGORIES = [
    ("اجاره", "6101"), ("حقوق و دستمزد", "6102"), ("آب، برق، گاز و تلفن", "6103"),
    ("حمل و نقل", "6104"), ("تبلیغات و بازاریابی", "6105"), ("تعمیر و نگهداری", "6106"),
    ("ملزومات و بسته‌بندی", "6107"), ("کارمزد بانکی", "6108"), ("پیامک و اینترنت", "6109"),
    ("سایر", "6199"),
]

# Fixed posting targets
A_CASH, A_BANK, A_CARD, A_CHQ_RECV = "1101", "1102", "1103", "1104"
A_RECEIVABLE, A_INVENTORY = "1201", "1301"
A_PAYABLE, A_CHQ_PAY, A_VAT = "2101", "2102", "2201"
A_SALES, A_SALES_RET, A_SALES_DISC = "4101", "4102", "4103"
A_COGS, A_WASTE, A_SURPLUS = "5101", "5102", "5103"
A_BOUNCE, A_CAPITAL, A_RETAINED = "6110", "3101", "3201"

TENDER_ACCOUNT = {"CASH": A_CASH, "CARD": A_CARD, "POS": A_CARD, "BANK": A_BANK,
                  "TRANSFER": A_BANK, "CHEQUE": A_CHQ_RECV, "ACCOUNT": A_RECEIVABLE}


def ensure_chart(db: Session) -> None:
    """Seed chart, expense categories and the current Jalali fiscal year."""
    have = {a.code: a for a in db.execute(select(Account)).scalars()}
    for code, name, cls, parent, postable in DEFAULT_CHART:
        if code in have:
            continue
        parent_id = have[parent].id if parent and parent in have else None
        acc = Account(code=code, name=name, account_class=cls, parent_id=parent_id,
                      is_system=True, is_postable=postable)
        db.add(acc)
        db.flush()
        have[code] = acc
    cats = {c.name for c in db.execute(select(ExpenseCategory)).scalars()}
    for name, code in DEFAULT_EXPENSE_CATEGORIES:
        if name not in cats:
            db.add(ExpenseCategory(name=name, account_id=have[code].id))
    ensure_fiscal_period(db, _lt_today())
    db.flush()


def ensure_fiscal_period(db: Session, d: date) -> FiscalPeriod:
    from .timeservice import from_jalali, to_jalali

    fp = db.execute(select(FiscalPeriod).where(FiscalPeriod.start_date <= d, FiscalPeriod.end_date >= d)
                    ).scalar_one_or_none()
    if fp:
        return fp
    jy, _, _ = to_jalali(datetime(d.year, d.month, d.day))
    sy, sm, sd = from_jalali(jy, 1, 1)
    ny, nm, nd = from_jalali(jy + 1, 1, 1)
    from datetime import timedelta
    fp = FiscalPeriod(name=str(jy), start_date=date(sy, sm, sd), end_date=date(ny, nm, nd) - timedelta(days=1))
    db.add(fp)
    db.flush()
    return fp


def account_by_code(db: Session, code: str) -> Account:
    acc = db.execute(select(Account).where(Account.code == code)).scalar_one_or_none()
    if acc is None:
        ensure_chart(db)
        acc = db.execute(select(Account).where(Account.code == code)).scalar_one_or_none()
    if acc is None:
        raise AccountingError("ACCOUNT_NOT_FOUND", f"حساب {code} در کدینگ وجود ندارد")
    return acc


# ---------------------------------------------------------------------------
# Posting engine
# ---------------------------------------------------------------------------
@dataclass
class Line:
    account: str            # account code
    debit: Decimal = ZERO
    credit: Decimal = ZERO
    description: str | None = None
    party_type: str | None = None
    party_id: int | None = None


def _next_number(db: Session) -> int:
    return int(db.execute(select(func.coalesce(func.max(JournalEntry.number), 0))).scalar_one()) + 1


def post(db: Session, *, kind: str, lines: list[Line], description: str = "",
         entry_date: date | None = None, source_type: str | None = None, source_id: int | None = None,
         user: User | None = None, status: str = "POSTED") -> JournalEntry:
    """Append one balanced journal entry. Idempotent per (source_type, source_id, kind)."""
    lines = [l for l in lines if _m(l.debit) != ZERO or _m(l.credit) != ZERO]
    if len(lines) < 2:
        raise AccountingError("TOO_FEW_LINES", "سند باید حداقل دو ردیف داشته باشد")
    total_d = sum((_m(l.debit) for l in lines), ZERO)
    total_c = sum((_m(l.credit) for l in lines), ZERO)
    if total_d != total_c:
        raise AccountingError("UNBALANCED", f"سند تراز نیست: بدهکار {total_d} ≠ بستانکار {total_c}")
    for l in lines:
        if _m(l.debit) < ZERO or _m(l.credit) < ZERO:
            raise AccountingError("NEGATIVE_AMOUNT", "مبلغ منفی مجاز نیست")
        if _m(l.debit) and _m(l.credit):
            raise AccountingError("BOTH_SIDES", "یک ردیف نمی‌تواند هم بدهکار و هم بستانکار باشد")

    if source_type and source_id is not None:
        dup = db.execute(select(JournalEntry).where(
            JournalEntry.source_type == source_type, JournalEntry.source_id == source_id,
            JournalEntry.kind == kind)).scalar_one_or_none()
        if dup:
            return dup

    d = entry_date or _lt_today()
    fp = ensure_fiscal_period(db, d)
    if fp.is_closed:
        raise AccountingError("PERIOD_CLOSED", f"دورهٔ مالی {fp.name} بسته شده است")

    accounts = {code: account_by_code(db, code) for code in {l.account for l in lines}}
    for a in accounts.values():
        if not a.is_postable:
            raise AccountingError("NOT_POSTABLE", f"حساب {a.code} {a.name} گروه است و قابل ثبت نیست")
        if not a.is_active:
            raise AccountingError("ACCOUNT_INACTIVE", f"حساب {a.code} غیرفعال است")

    entry = JournalEntry(number=_next_number(db), entry_date=d, description=description[:512],
                         kind=kind, source_type=source_type, source_id=source_id, status=status,
                         fiscal_period_id=fp.id, created_by=user.id if user else None)
    db.add(entry)
    db.flush()
    for l in lines:
        db.add(JournalLine(entry_id=entry.id, account_id=accounts[l.account].id,
                           debit=_m(l.debit), credit=_m(l.credit), description=l.description,
                           party_type=l.party_type, party_id=l.party_id))
    db.flush()
    return entry


def reverse(db: Session, *, entry_id: int, user: User | None = None, reason: str | None = None) -> JournalEntry:
    orig = db.get(JournalEntry, entry_id)
    if orig is None:
        raise AccountingError("ENTRY_NOT_FOUND", "سند یافت نشد")
    if orig.status == "REVERSED":
        raise AccountingError("ALREADY_REVERSED", "این سند قبلاً برگشت خورده است")
    mirror = [Line(account=l.account.code, debit=l.credit, credit=l.debit, description=l.description,
                   party_type=l.party_type, party_id=l.party_id) for l in orig.lines]
    rev = post(db, kind="REVERSAL", lines=mirror, description=f"برگشت سند {orig.number}: {reason or ''}",
               user=user)
    rev.reversal_of_id = orig.id
    orig.status = "REVERSED"
    write_audit(db, action="ACC_ENTRY_REVERSED", user_id=user.id if user else None,
                entity_type="JournalEntry", entity_id=orig.id, after={"reversal": rev.number}, reference=reason)
    db.flush()
    return rev


# ---------------------------------------------------------------------------
# Automatic postings
# ---------------------------------------------------------------------------
def post_sale(db: Session, invoice: Invoice, user: User | None = None) -> JournalEntry | None:
    """Sale: Dr tenders / Dr receivable ; Cr sales, Cr VAT. COGS: Dr COGS / Cr inventory."""
    gross = sum((_m(i.unit_sell_price) * Decimal(str(i.qty)) for i in invoice.items), ZERO)
    discount = _m(invoice.discount)
    tax = _m(invoice.tax)
    total = _m(invoice.total_amount)
    cogs = sum((_m(i.unit_buy_price) * Decimal(str(i.qty)) for i in invoice.items), ZERO)
    lines: list[Line] = []
    tenders: dict[str, Decimal] = {}
    for p in invoice.payments:
        code = TENDER_ACCOUNT.get(str(p.method).upper(), A_CASH)
        tenders[code] = tenders.get(code, ZERO) + _m(p.amount)
    if not tenders:
        tenders[A_CASH] = total
    for code, amt in tenders.items():
        lines.append(Line(code, debit=amt, description=f"دریافت بابت فاکتور {invoice.invoice_number}",
                          party_type="CUSTOMER" if code == A_RECEIVABLE else None,
                          party_id=invoice.customer_id if code == A_RECEIVABLE else None))
    if discount:
        lines.append(Line(A_SALES_DISC, debit=discount, description="تخفیف فروش"))
    lines.append(Line(A_SALES, credit=_m(gross), description=f"فروش فاکتور {invoice.invoice_number}"))
    if tax:
        lines.append(Line(A_VAT, credit=tax, description="مالیات بر ارزش افزوده"))
    # rounding guard: force balance through sales if the tenders != total (should not happen)
    dsum = sum((l.debit for l in lines), ZERO)
    csum = sum((l.credit for l in lines), ZERO)
    if dsum != csum:
        lines.append(Line(A_SALES, debit=max(ZERO, csum - dsum), credit=max(ZERO, dsum - csum),
                          description="تعدیل گرد کردن"))
    if cogs > ZERO:
        lines.append(Line(A_COGS, debit=cogs, description="بهای تمام‌شده"))
        lines.append(Line(A_INVENTORY, credit=cogs, description="خروج کالا از انبار"))
    return post(db, kind="SALE", lines=lines, description=f"فروش — فاکتور {invoice.invoice_number}",
                entry_date=_local_date(invoice.created_at),
                source_type="Invoice", source_id=invoice.id, user=user)


def post_sale_void(db: Session, invoice: Invoice, user: User | None = None, reason: str | None = None):
    sale = db.execute(select(JournalEntry).where(JournalEntry.source_type == "Invoice",
                                                 JournalEntry.source_id == invoice.id,
                                                 JournalEntry.kind == "SALE")).scalar_one_or_none()
    if sale and sale.status != "REVERSED":
        return reverse(db, entry_id=sale.id, user=user, reason=f"ابطال فاکتور {invoice.invoice_number} — {reason or ''}")
    return None


def post_sale_return(db: Session, ret: Return, item: InvoiceItem, invoice: Invoice, user: User | None = None):
    refund = _m(ret.refund_amount)
    cost = _m(item.unit_buy_price) * Decimal(str(ret.qty))
    lines = [Line(A_SALES_RET, debit=refund, description=f"برگشت از فروش فاکتور {invoice.invoice_number}"),
             Line(A_CASH, credit=refund, description="استرداد وجه")]
    if cost > ZERO:
        lines += [Line(A_INVENTORY, debit=cost, description="بازگشت کالا به انبار"),
                  Line(A_COGS, credit=cost, description="برگشت بهای تمام‌شده")]
    return post(db, kind="SALE_RETURN", lines=lines, description=f"برگشت از فروش — {invoice.invoice_number}",
                source_type="Return", source_id=ret.id, user=user)


def post_purchase(db: Session, batch: ProductBatch, user: User | None = None, *,
                  paid_from: str = "PAYABLE", supplier_id: int | None = None):
    """Receiving: Dr inventory / Cr supplier payable (or cash if paid immediately)."""
    value = _m(batch.buy_price) * Decimal(str(batch.quantity_received))
    if value <= ZERO:
        return None
    credit_acc = {"CASH": A_CASH, "BANK": A_BANK, "CARD": A_CARD}.get(paid_from.upper(), A_PAYABLE)
    lines = [Line(A_INVENTORY, debit=value, description=f"ورود کالا بچ {batch.batch_number}"),
             Line(credit_acc, credit=value, description="خرید کالا",
                  party_type="SUPPLIER" if credit_acc == A_PAYABLE else None, party_id=supplier_id)]
    return post(db, kind="PURCHASE", lines=lines, description=f"خرید — بچ {batch.batch_number}",
                entry_date=_local_date(batch.received_at),
                source_type="ProductBatch", source_id=batch.id, user=user)


def post_stock_adjustment(db: Session, *, batch: ProductBatch, delta_qty: Decimal, movement_id: int,
                          movement_type: str, user: User | None = None):
    """WASTE / ADJUSTMENT / STOCKTAKE: shortage → Dr waste, Cr inventory; surplus → reverse."""
    value = _m(batch.buy_price) * abs(Decimal(str(delta_qty)))
    if value <= ZERO:
        return None
    if Decimal(str(delta_qty)) < ZERO:
        lines = [Line(A_WASTE, debit=value, description=f"{movement_type} بچ {batch.batch_number}"),
                 Line(A_INVENTORY, credit=value, description="کاهش موجودی")]
    else:
        lines = [Line(A_INVENTORY, debit=value, description="افزایش موجودی"),
                 Line(A_SURPLUS, credit=value, description=f"{movement_type} بچ {batch.batch_number}")]
    return post(db, kind="WASTE" if movement_type == "WASTE" else "ADJUSTMENT", lines=lines,
                description=f"{'ضایعات' if movement_type == 'WASTE' else 'اصلاح موجودی'} — بچ {batch.batch_number}",
                source_type="StockMovement", source_id=movement_id, user=user)


def post_settlement(db: Session, *, customer_id: int, amount: Decimal, method: str, entry_id: int,
                    user: User | None = None, user_id: int | None = None):
    if user is None and user_id is not None:
        user = db.get(User, user_id)
    acc = TENDER_ACCOUNT.get(method.upper(), A_CASH)
    if acc == A_RECEIVABLE:
        acc = A_CASH
    lines = [Line(acc, debit=amount, description="دریافت از مشتری"),
             Line(A_RECEIVABLE, credit=amount, description="تسویهٔ حساب دفتری",
                  party_type="CUSTOMER", party_id=customer_id)]
    return post(db, kind="SETTLEMENT", lines=lines, description="تسویهٔ بدهی مشتری",
                source_type="CustomerLedgerEntry", source_id=entry_id, user=user)


# ---------------------------------------------------------------------------
# Expenses / cheques / cash sessions
# ---------------------------------------------------------------------------
def record_expense(db: Session, *, category_id: int, amount, expense_date: date | None = None,
                   paid_from: str = "CASH", description: str | None = None, supplier_id: int | None = None,
                   user: User | None = None) -> Expense:
    cat = db.get(ExpenseCategory, category_id)
    if cat is None:
        raise AccountingError("CATEGORY_NOT_FOUND", "دستهٔ هزینه یافت نشد")
    amount = _m(amount)
    if amount <= ZERO:
        raise AccountingError("INVALID_AMOUNT", "مبلغ باید بزرگ‌تر از صفر باشد")
    pay_acc = {"CASH": A_CASH, "BANK": A_BANK, "CARD": A_CARD, "PAYABLE": A_PAYABLE}.get(paid_from.upper(), A_CASH)
    exp = Expense(category_id=category_id, amount=amount, expense_date=expense_date or _lt_today(),
                  paid_from=paid_from.upper(), description=description, supplier_id=supplier_id,
                  created_by=user.id if user else None)
    db.add(exp)
    db.flush()
    acc = db.get(Account, cat.account_id)
    entry = post(db, kind="EXPENSE", entry_date=exp.expense_date,
                 lines=[Line(acc.code, debit=amount, description=description or cat.name),
                        Line(pay_acc, credit=amount, description=f"پرداخت {cat.name}",
                             party_type="SUPPLIER" if pay_acc == A_PAYABLE else None, party_id=supplier_id)],
                 description=f"هزینه — {cat.name}", source_type="Expense", source_id=exp.id, user=user)
    exp.journal_entry_id = entry.id
    write_audit(db, action="EXPENSE_RECORDED", user_id=user.id if user else None, entity_type="Expense",
                entity_id=exp.id, after={"amount": str(amount), "category": cat.name})
    return exp


def record_cheque(db: Session, *, direction: str, number: str, amount, due_date: date, bank_name: str | None,
                  party_type: str | None, party_id: int | None, party_name: str | None,
                  description: str | None = None, issue_date: date | None = None,
                  user: User | None = None) -> Cheque:
    direction = direction.upper()
    if direction not in ("RECEIVED", "ISSUED"):
        raise AccountingError("INVALID_DIRECTION", "نوع چک باید RECEIVED یا ISSUED باشد")
    amount = _m(amount)
    if amount <= ZERO:
        raise AccountingError("INVALID_AMOUNT", "مبلغ باید بزرگ‌تر از صفر باشد")
    chq = Cheque(direction=direction, number=number, bank_name=bank_name, amount=amount, due_date=due_date,
                 issue_date=issue_date, party_type=party_type, party_id=party_id, party_name=party_name,
                 description=description, created_by=user.id if user else None)
    db.add(chq)
    db.flush()
    if direction == "RECEIVED":
        lines = [Line(A_CHQ_RECV, debit=amount, description=f"چک دریافتی {number}"),
                 Line(A_RECEIVABLE if party_type == "CUSTOMER" else A_SALES, credit=amount,
                      description="دریافت چک", party_type=party_type, party_id=party_id)]
    else:
        lines = [Line(A_PAYABLE, debit=amount, description="پرداخت با چک",
                      party_type=party_type, party_id=party_id),
                 Line(A_CHQ_PAY, credit=amount, description=f"چک پرداختی {number}")]
    entry = post(db, kind="CHEQUE", lines=lines, description=f"ثبت چک {number}",
                 source_type="Cheque", source_id=chq.id, user=user)
    chq.journal_entry_id = entry.id
    return chq


def clear_cheque(db: Session, *, cheque_id: int, user: User | None = None) -> Cheque:
    chq = db.get(Cheque, cheque_id)
    if chq is None:
        raise AccountingError("CHEQUE_NOT_FOUND", "چک یافت نشد")
    if chq.status != "PENDING":
        raise AccountingError("INVALID_STATE", f"چک در وضعیت {chq.status} است")
    if chq.direction == "RECEIVED":
        lines = [Line(A_BANK, debit=chq.amount, description=f"وصول چک {chq.number}"),
                 Line(A_CHQ_RECV, credit=chq.amount)]
    else:
        lines = [Line(A_CHQ_PAY, debit=chq.amount, description=f"پاس شدن چک {chq.number}"),
                 Line(A_BANK, credit=chq.amount)]
    entry = post(db, kind="CHEQUE", lines=lines, description=f"وصول چک {chq.number}",
                 source_type="ChequeClear", source_id=chq.id, user=user)
    chq.cleared_entry_id = entry.id
    chq.status = "CLEARED"
    return chq


def bounce_cheque(db: Session, *, cheque_id: int, user: User | None = None) -> Cheque:
    chq = db.get(Cheque, cheque_id)
    if chq is None:
        raise AccountingError("CHEQUE_NOT_FOUND", "چک یافت نشد")
    if chq.status != "PENDING":
        raise AccountingError("INVALID_STATE", f"چک در وضعیت {chq.status} است")
    if chq.direction == "RECEIVED":
        # debt comes back to the customer; cheque asset is gone
        lines = [Line(A_RECEIVABLE if chq.party_type == "CUSTOMER" else A_BOUNCE, debit=chq.amount,
                      description=f"برگشت چک {chq.number}", party_type=chq.party_type, party_id=chq.party_id),
                 Line(A_CHQ_RECV, credit=chq.amount)]
    else:
        lines = [Line(A_CHQ_PAY, debit=chq.amount, description=f"برگشت چک {chq.number}"),
                 Line(A_PAYABLE, credit=chq.amount, party_type=chq.party_type, party_id=chq.party_id)]
    entry = post(db, kind="CHEQUE", lines=lines, description=f"برگشت چک {chq.number}",
                 source_type="ChequeBounce", source_id=chq.id, user=user)
    chq.cleared_entry_id = entry.id
    chq.status = "BOUNCED"
    return chq


def open_cash_session(db: Session, *, user: User, opening_float) -> CashSession:
    cur = db.execute(select(CashSession).where(CashSession.user_id == user.id, CashSession.status == "OPEN")
                     ).scalar_one_or_none()
    if cur:
        raise AccountingError("SESSION_OPEN", "شیفت باز دیگری برای این کاربر وجود دارد")
    s = CashSession(user_id=user.id, opened_at=datetime.utcnow(), opening_float=_m(opening_float))
    db.add(s)
    db.flush()
    return s


def session_summary(db: Session, s: CashSession) -> dict:
    end = s.closed_at or datetime.utcnow()
    rows = db.execute(
        select(Payment.method, func.coalesce(func.sum(Payment.amount), 0), func.count(func.distinct(Invoice.id)))
        .select_from(Payment).join(Invoice, Payment.invoice_id == Invoice.id)
        .where(Invoice.created_by == s.user_id, Invoice.created_at >= s.opened_at, Invoice.created_at <= end,
               Invoice.status.in_(["PAID", "PARTIALLY_REFUNDED", "REFUNDED"]))
        .group_by(Payment.method)).all()
    by_method = {str(m).upper(): float(_m(a)) for m, a, _ in rows}
    invoices = int(db.execute(select(func.count(Invoice.id)).where(
        Invoice.created_by == s.user_id, Invoice.created_at >= s.opened_at, Invoice.created_at <= end,
        Invoice.status != "VOID")).scalar_one())
    refunds = _m(db.execute(select(func.coalesce(func.sum(Return.refund_amount), 0)).where(
        Return.created_by == s.user_id, Return.created_at >= s.opened_at, Return.created_at <= end)).scalar_one())
    cash_sales = _m(by_method.get("CASH", 0))
    expected = _m(s.opening_float) + cash_sales - refunds
    return {"by_method": by_method, "invoice_count": invoices, "refunds": float(refunds),
            "cash_sales": float(cash_sales), "expected_cash": float(expected),
            "total_sales": float(sum((_m(v) for v in by_method.values()), ZERO))}


def close_cash_session(db: Session, *, session_id: int, counted_cash, note: str | None,
                       user: User | None = None) -> CashSession:
    s = db.get(CashSession, session_id)
    if s is None:
        raise AccountingError("SESSION_NOT_FOUND", "شیفت یافت نشد")
    if s.status != "OPEN":
        raise AccountingError("SESSION_CLOSED", "این شیفت قبلاً بسته شده است")
    s.closed_at = datetime.utcnow()
    summ = session_summary(db, s)
    s.expected_cash = _m(summ["expected_cash"])
    s.counted_cash = _m(counted_cash)
    s.difference = s.counted_cash - s.expected_cash
    s.note = note
    s.status = "CLOSED"
    if s.difference != ZERO:
        diff = abs(s.difference)
        if s.difference < ZERO:
            lines = [Line("6199", debit=diff, description="کسری صندوق"), Line(A_CASH, credit=diff)]
        else:
            lines = [Line(A_CASH, debit=diff), Line("4201", credit=diff, description="اضافهٔ صندوق")]
        e = post(db, kind="ADJUSTMENT", lines=lines, description=f"بستن صندوق شیفت #{s.id}",
                 source_type="CashSession", source_id=s.id, user=user)
        s.journal_entry_id = e.id
    write_audit(db, action="CASH_SESSION_CLOSED", user_id=user.id if user else None, entity_type="CashSession",
                entity_id=s.id, after={"expected": str(s.expected_cash), "counted": str(s.counted_cash),
                                       "difference": str(s.difference)})
    return s


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------
def _balances(db: Session, start: date | None, end: date | None, account_ids: list[int] | None = None) -> dict[int, tuple[Decimal, Decimal]]:
    conds = [JournalEntry.status != "REVERSED_HIDDEN"]  # keep reversed pairs — they cancel
    if start:
        conds.append(JournalEntry.entry_date >= start)
    if end:
        conds.append(JournalEntry.entry_date <= end)
    if account_ids:
        conds.append(JournalLine.account_id.in_(account_ids))
    rows = db.execute(
        select(JournalLine.account_id, func.coalesce(func.sum(JournalLine.debit), 0),
               func.coalesce(func.sum(JournalLine.credit), 0))
        .join(JournalEntry, JournalLine.entry_id == JournalEntry.id)
        .where(and_(*conds)).group_by(JournalLine.account_id)).all()
    return {aid: (_m(d), _m(c)) for aid, d, c in rows}


def _signed(acc: Account, debit: Decimal, credit: Decimal) -> Decimal:
    return debit - credit if acc.account_class in DEBIT_NORMAL else credit - debit


def trial_balance(db: Session, start: date | None = None, end: date | None = None) -> dict:
    ensure_chart(db)
    accounts = list(db.execute(select(Account).order_by(Account.code)).scalars())
    bal = _balances(db, start, end)
    by_id = {a.id: a for a in accounts}
    # roll leaf balances up to parents for display
    agg: dict[int, list[Decimal]] = {a.id: [ZERO, ZERO] for a in accounts}
    for aid, (d, c) in bal.items():
        cur = by_id.get(aid)
        while cur is not None:
            agg[cur.id][0] += d
            agg[cur.id][1] += c
            cur = by_id.get(cur.parent_id) if cur.parent_id else None
    rows = []
    td = tc = ZERO
    for a in accounts:
        d, c = agg[a.id]
        if d == ZERO and c == ZERO:
            continue
        if a.is_postable:
            td += d
            tc += c
        rows.append({"account_id": a.id, "code": a.code, "name": a.name, "class": a.account_class,
                     "is_group": not a.is_postable, "debit": float(d), "credit": float(c),
                     "balance": float(_signed(a, d, c)), "level": a.code.rstrip("0").__len__() if a.code else 1})
    return {"rows": rows, "total_debit": float(td), "total_credit": float(tc), "balanced": td == tc,
            "start": str(start) if start else None, "end": str(end) if end else None}


def account_balance(db: Session, code: str, end: date | None = None) -> Decimal:
    acc = account_by_code(db, code)
    d, c = _balances(db, None, end, [acc.id]).get(acc.id, (ZERO, ZERO))
    return _signed(acc, d, c)


def general_ledger(db: Session, account_id: int, start: date | None = None, end: date | None = None,
                   limit: int = 500) -> dict:
    acc = db.get(Account, account_id)
    if acc is None:
        raise AccountingError("ACCOUNT_NOT_FOUND", "حساب یافت نشد")
    opening = ZERO
    if start:
        from datetime import timedelta
        d, c = _balances(db, None, start - timedelta(days=1), [acc.id]).get(acc.id, (ZERO, ZERO))
        opening = _signed(acc, d, c)
    conds = [JournalLine.account_id == acc.id]
    if start:
        conds.append(JournalEntry.entry_date >= start)
    if end:
        conds.append(JournalEntry.entry_date <= end)
    rows = db.execute(select(JournalLine, JournalEntry).join(JournalEntry, JournalLine.entry_id == JournalEntry.id)
                      .where(and_(*conds)).order_by(JournalEntry.entry_date, JournalEntry.number, JournalLine.id)
                      .limit(limit)).all()
    running = opening
    out = []
    for ln, en in rows:
        running += _signed(acc, _m(ln.debit), _m(ln.credit))
        out.append({"entry_id": en.id, "number": en.number, "date": str(en.entry_date), "kind": en.kind,
                    "status": en.status, "description": ln.description or en.description,
                    "debit": float(ln.debit), "credit": float(ln.credit), "balance": float(running)})
    return {"account": {"id": acc.id, "code": acc.code, "name": acc.name, "class": acc.account_class},
            "opening": float(opening), "closing": float(running), "rows": out}


def income_statement(db: Session, start: date, end: date) -> dict:
    ensure_chart(db)
    accounts = {a.id: a for a in db.execute(select(Account)).scalars()}
    bal = _balances(db, start, end)

    def total(cls: str) -> tuple[Decimal, list[dict]]:
        t = ZERO
        items = []
        for aid, (d, c) in bal.items():
            a = accounts[aid]
            if a.account_class != cls:
                continue
            v = _signed(a, d, c)
            t += v
            items.append({"code": a.code, "name": a.name, "amount": float(v)})
        items.sort(key=lambda x: x["code"])
        return t, items

    rev, rev_items = total("REVENUE")
    cogs, cogs_items = total("COGS")
    exp, exp_items = total("EXPENSE")
    gross = rev - cogs
    net = gross - exp
    return {"start": str(start), "end": str(end),
            "revenue": {"total": float(rev), "items": rev_items},
            "cogs": {"total": float(cogs), "items": cogs_items},
            "gross_profit": float(gross),
            "expenses": {"total": float(exp), "items": exp_items},
            "net_profit": float(net),
            "gross_margin_pct": float((gross / rev * 100).quantize(CENT)) if rev else 0.0}


def balance_sheet(db: Session, as_of: date | None = None) -> dict:
    ensure_chart(db)
    as_of = as_of or _lt_today()
    accounts = {a.id: a for a in db.execute(select(Account)).scalars()}
    bal = _balances(db, None, as_of)
    groups: dict[str, list[dict]] = {"ASSET": [], "LIABILITY": [], "EQUITY": []}
    totals = {"ASSET": ZERO, "LIABILITY": ZERO, "EQUITY": ZERO}
    pl = ZERO
    for aid, (d, c) in bal.items():
        a = accounts[aid]
        v = _signed(a, d, c)
        if a.account_class in groups:
            groups[a.account_class].append({"code": a.code, "name": a.name, "amount": float(v)})
            totals[a.account_class] += v
        elif a.account_class == "REVENUE":
            pl += v
        else:  # COGS / EXPENSE
            pl -= v
    for g in groups.values():
        g.sort(key=lambda x: x["code"])
    groups["EQUITY"].append({"code": "3202", "name": "سود (زیان) دورهٔ جاری", "amount": float(pl)})
    totals["EQUITY"] += pl
    return {"as_of": str(as_of),
            "assets": {"total": float(totals["ASSET"]), "items": groups["ASSET"]},
            "liabilities": {"total": float(totals["LIABILITY"]), "items": groups["LIABILITY"]},
            "equity": {"total": float(totals["EQUITY"]), "items": groups["EQUITY"]},
            "balanced": totals["ASSET"] == totals["LIABILITY"] + totals["EQUITY"]}


def close_period(db: Session, *, period_id: int, user: User | None = None) -> FiscalPeriod:
    """Close P&L accounts into retained earnings and lock the period."""
    fp = db.get(FiscalPeriod, period_id)
    if fp is None:
        raise AccountingError("PERIOD_NOT_FOUND", "دورهٔ مالی یافت نشد")
    if fp.is_closed:
        raise AccountingError("PERIOD_CLOSED", "این دوره قبلاً بسته شده است")
    accounts = {a.id: a for a in db.execute(select(Account)).scalars()}
    bal = _balances(db, fp.start_date, fp.end_date)
    lines: list[Line] = []
    net = ZERO
    for aid, (d, c) in bal.items():
        a = accounts[aid]
        if a.account_class not in ("REVENUE", "COGS", "EXPENSE"):
            continue
        v = d - c  # raw debit balance
        if v == ZERO:
            continue
        # zero the account: credit debit-balances, debit credit-balances
        lines.append(Line(a.code, debit=max(ZERO, -v), credit=max(ZERO, v), description="بستن حساب‌های موقت"))
        net += -v  # credit balances (revenue) increase net
    if lines:
        lines.append(Line(A_RETAINED, debit=max(ZERO, -net), credit=max(ZERO, net), description="انتقال سود/زیان"))
        post(db, kind="CLOSING", lines=lines, description=f"بستن دورهٔ مالی {fp.name}", entry_date=fp.end_date,
             source_type="FiscalPeriod", source_id=fp.id, user=user)
    fp.is_closed = True
    fp.closed_at = datetime.utcnow()
    fp.closed_by = user.id if user else None
    write_audit(db, action="FISCAL_PERIOD_CLOSED", user_id=user.id if user else None, entity_type="FiscalPeriod",
                entity_id=fp.id, after={"net": str(net)})
    return fp


def overview(db: Session) -> dict:
    """Numbers for the accounting home + dashboard block."""
    ensure_chart(db)
    today = _lt_today()
    from .timeservice import from_jalali, to_jalali
    jy, jm, _ = to_jalali(datetime(today.year, today.month, today.day))
    sy, sm, sd = from_jalali(jy, jm, 1)
    month_start = date(sy, sm, sd)
    pl = income_statement(db, month_start, today)
    pending_recv = db.execute(select(func.coalesce(func.sum(Cheque.amount), 0), func.count(Cheque.id)).where(
        Cheque.direction == "RECEIVED", Cheque.status == "PENDING")).one()
    pending_pay = db.execute(select(func.coalesce(func.sum(Cheque.amount), 0), func.count(Cheque.id)).where(
        Cheque.direction == "ISSUED", Cheque.status == "PENDING")).one()
    due_soon = list(db.execute(select(Cheque).where(Cheque.status == "PENDING",
                                                    Cheque.due_date <= today.replace(day=today.day))
                               .order_by(Cheque.due_date).limit(5)).scalars())
    return {
        "cash": float(account_balance(db, A_CASH)), "bank": float(account_balance(db, A_BANK)),
        "card": float(account_balance(db, A_CARD)),
        "receivables": float(account_balance(db, A_RECEIVABLE)), "payables": float(account_balance(db, A_PAYABLE)),
        "inventory_value": float(account_balance(db, A_INVENTORY)),
        "month": {"revenue": pl["revenue"]["total"], "cogs": pl["cogs"]["total"],
                  "expenses": pl["expenses"]["total"], "net_profit": pl["net_profit"],
                  "gross_margin_pct": pl["gross_margin_pct"]},
        "cheques": {"received_pending": float(_m(pending_recv[0])), "received_count": int(pending_recv[1]),
                    "issued_pending": float(_m(pending_pay[0])), "issued_count": int(pending_pay[1]),
                    "overdue": [{"id": c.id, "number": c.number, "amount": float(c.amount), "due_date": str(c.due_date),
                                 "direction": c.direction, "party_name": c.party_name} for c in due_soon]},
        "entry_count": int(db.execute(select(func.count(JournalEntry.id))).scalar_one()),
    }
