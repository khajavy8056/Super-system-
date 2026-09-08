"""Accounting API (v1.4): chart, journal, ledgers, statements, expenses, cheques, cash sessions."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import (Account, CashSession, Cheque, Customer, Expense, ExpenseCategory,
                      FiscalPeriod, JournalEntry, JournalLine, Supplier, User)
from ..security import get_current_user, require_permission
from ..services import accounting as acc
from ..services.audit import write_audit


def _lt_today():
    from ..services.timeservice import local_today
    return local_today()


def _lt_now():
    from ..services.timeservice import local_now
    return local_now()

router = APIRouter(prefix="/accounting", tags=["accounting"])

_STATUS = {"ACCOUNT_NOT_FOUND": 404, "ENTRY_NOT_FOUND": 404, "CHEQUE_NOT_FOUND": 404,
           "SESSION_NOT_FOUND": 404, "PERIOD_NOT_FOUND": 404, "CATEGORY_NOT_FOUND": 404,
           "UNBALANCED": 422, "TOO_FEW_LINES": 422, "NEGATIVE_AMOUNT": 422, "INVALID_AMOUNT": 422,
           "BOTH_SIDES": 422, "PERIOD_CLOSED": 409, "ALREADY_REVERSED": 409, "SESSION_OPEN": 409,
           "SESSION_CLOSED": 409, "INVALID_STATE": 409, "NOT_POSTABLE": 422}


def _raise(e: acc.AccountingError):
    raise HTTPException(status_code=_STATUS.get(e.code, 400), detail={"code": e.code, "message": str(e)})


def _entry_out(e: JournalEntry) -> dict:
    return {"id": e.id, "number": e.number, "date": str(e.entry_date), "kind": e.kind, "status": e.status,
            "description": e.description, "source_type": e.source_type, "source_id": e.source_id,
            "reversal_of_id": e.reversal_of_id, "created_by": e.created_by,
            "total": float(sum((Decimal(str(l.debit)) for l in e.lines), Decimal(0))),
            "lines": [{"id": l.id, "account_id": l.account_id, "code": l.account.code, "name": l.account.name,
                       "debit": float(l.debit), "credit": float(l.credit), "description": l.description,
                       "party_type": l.party_type, "party_id": l.party_id} for l in e.lines]}


# ---- overview / chart -------------------------------------------------------
@router.get("/overview")
def overview(db: Session = Depends(get_db), _: User = Depends(require_permission("accounting.view"))):
    return acc.overview(db)


@router.get("/accounts")
def list_accounts(db: Session = Depends(get_db), _: User = Depends(require_permission("accounting.view"))):
    acc.ensure_chart(db)
    db.commit()
    rows = list(db.execute(select(Account).order_by(Account.code)).scalars())
    bal = acc._balances(db, None, None)
    return [{"id": a.id, "code": a.code, "name": a.name, "class": a.account_class, "parent_id": a.parent_id,
             "is_system": a.is_system, "is_active": a.is_active, "is_postable": a.is_postable,
             "balance": float(acc._signed(a, *bal.get(a.id, (Decimal(0), Decimal(0)))))} for a in rows]


class AccountIn(BaseModel):
    code: str = Field(min_length=3, max_length=16)
    name: str = Field(min_length=1, max_length=128)
    account_class: str
    parent_id: int | None = None
    description: str | None = None


@router.post("/accounts", status_code=201)
def create_account(body: AccountIn, db: Session = Depends(get_db),
                   user: User = Depends(require_permission("accounting.post"))):
    from ..models.accounting import ACCOUNT_CLASSES
    if body.account_class not in ACCOUNT_CLASSES:
        raise HTTPException(422, {"code": "INVALID_CLASS", "message": "طبقهٔ حساب نامعتبر است"})
    if db.execute(select(Account).where(Account.code == body.code)).scalar_one_or_none():
        raise HTTPException(409, {"code": "DUPLICATE_CODE", "message": "این کد حساب قبلاً ثبت شده است"})
    a = Account(code=body.code, name=body.name, account_class=body.account_class, parent_id=body.parent_id,
                description=body.description, is_system=False, is_postable=True)
    db.add(a)
    if body.parent_id:
        parent = db.get(Account, body.parent_id)
        if parent:
            parent.is_postable = False
    write_audit(db, action="ACC_ACCOUNT_CREATED", user_id=user.id, entity_type="Account", after={"code": body.code})
    db.commit()
    return {"id": a.id, "code": a.code, "name": a.name}


class AccountPatch(BaseModel):
    name: str | None = None
    is_active: bool | None = None
    description: str | None = None


@router.patch("/accounts/{account_id}")
def patch_account(account_id: int, body: AccountPatch, db: Session = Depends(get_db),
                  user: User = Depends(require_permission("accounting.post"))):
    a = db.get(Account, account_id)
    if not a:
        raise HTTPException(404, "ACCOUNT_NOT_FOUND")
    if body.name is not None:
        a.name = body.name
    if body.description is not None:
        a.description = body.description
    if body.is_active is not None:
        if a.is_system and not body.is_active:
            raise HTTPException(409, {"code": "SYSTEM_ACCOUNT", "message": "حساب سیستمی را نمی‌توان غیرفعال کرد"})
        a.is_active = body.is_active
    db.commit()
    return {"ok": True}


# ---- journal -----------------------------------------------------------------
@router.get("/journal")
def list_journal(start: date | None = None, end: date | None = None, kind: str | None = None,
                 q: str | None = None, limit: int = Query(100, le=1000), offset: int = 0,
                 db: Session = Depends(get_db), _: User = Depends(require_permission("accounting.view"))):
    conds = []
    if start:
        conds.append(JournalEntry.entry_date >= start)
    if end:
        conds.append(JournalEntry.entry_date <= end)
    if kind:
        conds.append(JournalEntry.kind == kind.upper())
    if q:
        conds.append(JournalEntry.description.ilike(f"%{q}%"))
    stmt = select(JournalEntry)
    if conds:
        stmt = stmt.where(and_(*conds))
    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    rows = db.execute(stmt.order_by(JournalEntry.entry_date.desc(), JournalEntry.number.desc())
                      .limit(limit).offset(offset)).scalars().all()
    return {"total": int(total), "items": [_entry_out(e) for e in rows]}


@router.get("/journal/{entry_id}")
def get_entry(entry_id: int, db: Session = Depends(get_db), _: User = Depends(require_permission("accounting.view"))):
    e = db.get(JournalEntry, entry_id)
    if not e:
        raise HTTPException(404, "ENTRY_NOT_FOUND")
    return _entry_out(e)


class LineIn(BaseModel):
    account_code: str
    debit: Decimal = Field(default=Decimal(0), ge=0)
    credit: Decimal = Field(default=Decimal(0), ge=0)
    description: str | None = None


class ManualEntryIn(BaseModel):
    entry_date: date | None = None
    description: str = ""
    lines: list[LineIn]


@router.post("/journal", status_code=201)
def post_manual(body: ManualEntryIn, db: Session = Depends(get_db),
                user: User = Depends(require_permission("accounting.post"))):
    try:
        e = acc.post(db, kind="MANUAL", entry_date=body.entry_date, description=body.description, user=user,
                     lines=[acc.Line(l.account_code, l.debit, l.credit, l.description) for l in body.lines])
    except acc.AccountingError as ex:
        db.rollback()
        _raise(ex)
    write_audit(db, action="ACC_MANUAL_ENTRY", user_id=user.id, entity_type="JournalEntry", entity_id=e.id,
                after={"number": e.number, "lines": len(body.lines)})
    db.commit()
    return _entry_out(e)


class ReverseIn(BaseModel):
    reason: str | None = None


@router.post("/journal/{entry_id}/reverse")
def reverse_entry(entry_id: int, body: ReverseIn, db: Session = Depends(get_db),
                  user: User = Depends(require_permission("accounting.post"))):
    try:
        e = acc.reverse(db, entry_id=entry_id, user=user, reason=body.reason)
    except acc.AccountingError as ex:
        db.rollback()
        _raise(ex)
    db.commit()
    return _entry_out(e)


# ---- statements --------------------------------------------------------------
@router.get("/trial-balance")
def trial_balance(start: date | None = None, end: date | None = None, db: Session = Depends(get_db),
                  _: User = Depends(require_permission("accounting.view"))):
    return acc.trial_balance(db, start, end)


@router.get("/ledger/{account_id}")
def ledger(account_id: int, start: date | None = None, end: date | None = None,
           db: Session = Depends(get_db), _: User = Depends(require_permission("accounting.view"))):
    try:
        return acc.general_ledger(db, account_id, start, end)
    except acc.AccountingError as ex:
        _raise(ex)


@router.get("/income-statement")
def income_statement(start: date, end: date, db: Session = Depends(get_db),
                     _: User = Depends(require_permission("accounting.view"))):
    return acc.income_statement(db, start, end)


@router.get("/balance-sheet")
def balance_sheet(as_of: date | None = None, db: Session = Depends(get_db),
                  _: User = Depends(require_permission("accounting.view"))):
    return acc.balance_sheet(db, as_of)


# ---- fiscal periods ----------------------------------------------------------
@router.get("/periods")
def periods(db: Session = Depends(get_db), _: User = Depends(require_permission("accounting.view"))):
    acc.ensure_chart(db)
    db.commit()
    return [{"id": p.id, "name": p.name, "start_date": str(p.start_date), "end_date": str(p.end_date),
             "is_closed": p.is_closed, "closed_at": p.closed_at.isoformat() if p.closed_at else None}
            for p in db.execute(select(FiscalPeriod).order_by(FiscalPeriod.start_date)).scalars()]


@router.post("/periods/{period_id}/close")
def close_period(period_id: int, db: Session = Depends(get_db),
                 user: User = Depends(require_permission("accounting.close"))):
    try:
        p = acc.close_period(db, period_id=period_id, user=user)
    except acc.AccountingError as ex:
        db.rollback()
        _raise(ex)
    db.commit()
    return {"id": p.id, "name": p.name, "is_closed": p.is_closed}


# ---- expenses ----------------------------------------------------------------
@router.get("/expense-categories")
def expense_categories(db: Session = Depends(get_db), _: User = Depends(require_permission("accounting.view"))):
    acc.ensure_chart(db)
    db.commit()
    rows = db.execute(select(ExpenseCategory, Account).join(Account, ExpenseCategory.account_id == Account.id)
                      .where(ExpenseCategory.is_active.is_(True)).order_by(Account.code)).all()
    return [{"id": c.id, "name": c.name, "account_id": c.account_id, "account_code": a.code} for c, a in rows]


class ExpenseCategoryIn(BaseModel):
    name: str
    account_code: str = "6199"


@router.post("/expense-categories", status_code=201)
def create_expense_category(body: ExpenseCategoryIn, db: Session = Depends(get_db),
                            user: User = Depends(require_permission("accounting.post"))):
    try:
        a = acc.account_by_code(db, body.account_code)
    except acc.AccountingError as ex:
        _raise(ex)
    c = ExpenseCategory(name=body.name, account_id=a.id)
    db.add(c)
    db.commit()
    return {"id": c.id, "name": c.name, "account_code": a.code}


class ExpenseIn(BaseModel):
    category_id: int
    amount: Decimal = Field(gt=0)
    expense_date: date | None = None
    paid_from: str = "CASH"
    description: str | None = None
    supplier_id: int | None = None


@router.get("/expenses")
def list_expenses(start: date | None = None, end: date | None = None, limit: int = Query(200, le=1000),
                  db: Session = Depends(get_db), _: User = Depends(require_permission("accounting.view"))):
    conds = []
    if start:
        conds.append(Expense.expense_date >= start)
    if end:
        conds.append(Expense.expense_date <= end)
    stmt = select(Expense, ExpenseCategory).join(ExpenseCategory, Expense.category_id == ExpenseCategory.id)
    if conds:
        stmt = stmt.where(and_(*conds))
    rows = db.execute(stmt.order_by(Expense.expense_date.desc(), Expense.id.desc()).limit(limit)).all()
    total = sum((Decimal(str(e.amount)) for e, _ in rows), Decimal(0))
    return {"total": float(total), "items": [
        {"id": e.id, "category": c.name, "category_id": c.id, "amount": float(e.amount),
         "expense_date": str(e.expense_date), "paid_from": e.paid_from, "description": e.description,
         "journal_entry_id": e.journal_entry_id} for e, c in rows]}


@router.post("/expenses", status_code=201)
def create_expense(body: ExpenseIn, db: Session = Depends(get_db),
                   user: User = Depends(require_permission("accounting.post"))):
    try:
        e = acc.record_expense(db, category_id=body.category_id, amount=body.amount, expense_date=body.expense_date,
                               paid_from=body.paid_from, description=body.description,
                               supplier_id=body.supplier_id, user=user)
    except acc.AccountingError as ex:
        db.rollback()
        _raise(ex)
    db.commit()
    return {"id": e.id, "amount": float(e.amount), "journal_entry_id": e.journal_entry_id}


# ---- suppliers ---------------------------------------------------------------
class SupplierIn(BaseModel):
    name: str
    phone: str | None = None
    address: str | None = None
    notes: str | None = None


@router.get("/suppliers")
def suppliers(db: Session = Depends(get_db), _: User = Depends(require_permission("accounting.view"))):
    rows = db.execute(select(Supplier).where(Supplier.is_active.is_(True)).order_by(Supplier.name)).scalars().all()
    # payable balance per supplier from journal party lines
    payable = acc.account_by_code(db, acc.A_PAYABLE)
    bal = {pid: float(Decimal(str(c)) - Decimal(str(d))) for pid, d, c in db.execute(
        select(JournalLine.party_id, func.coalesce(func.sum(JournalLine.debit), 0),
               func.coalesce(func.sum(JournalLine.credit), 0))
        .where(JournalLine.account_id == payable.id, JournalLine.party_type == "SUPPLIER")
        .group_by(JournalLine.party_id)).all()}
    return [{"id": s.id, "name": s.name, "phone": s.phone, "address": s.address, "notes": s.notes,
             "balance": bal.get(s.id, 0.0)} for s in rows]


@router.post("/suppliers", status_code=201)
def create_supplier(body: SupplierIn, db: Session = Depends(get_db),
                    user: User = Depends(require_permission("accounting.post"))):
    s = Supplier(**body.model_dump())
    db.add(s)
    db.commit()
    return {"id": s.id, "name": s.name}


class SupplierPayIn(BaseModel):
    amount: Decimal = Field(gt=0)
    method: str = "CASH"
    note: str | None = None


@router.post("/suppliers/{supplier_id}/pay")
def pay_supplier(supplier_id: int, body: SupplierPayIn, db: Session = Depends(get_db),
                 user: User = Depends(require_permission("accounting.post"))):
    s = db.get(Supplier, supplier_id)
    if not s:
        raise HTTPException(404, "SUPPLIER_NOT_FOUND")
    pay_acc = {"CASH": acc.A_CASH, "BANK": acc.A_BANK, "CARD": acc.A_CARD}.get(body.method.upper(), acc.A_CASH)
    try:
        e = acc.post(db, kind="SETTLEMENT", description=f"پرداخت به تأمین‌کننده {s.name} — {body.note or ''}",
                     lines=[acc.Line(acc.A_PAYABLE, debit=body.amount, party_type="SUPPLIER", party_id=s.id,
                                     description=f"پرداخت به {s.name}"),
                            acc.Line(pay_acc, credit=body.amount)], user=user)
    except acc.AccountingError as ex:
        db.rollback()
        _raise(ex)
    write_audit(db, action="SUPPLIER_PAID", user_id=user.id, entity_type="Supplier", entity_id=s.id,
                after={"amount": str(body.amount), "method": body.method})
    db.commit()
    return _entry_out(e)


# ---- cheques -----------------------------------------------------------------
class ChequeIn(BaseModel):
    direction: str
    number: str
    amount: Decimal = Field(gt=0)
    due_date: date
    issue_date: date | None = None
    bank_name: str | None = None
    party_type: str | None = None
    party_id: int | None = None
    party_name: str | None = None
    description: str | None = None


def _cheque_out(c: Cheque) -> dict:
    return {"id": c.id, "direction": c.direction, "number": c.number, "bank_name": c.bank_name,
            "amount": float(c.amount), "due_date": str(c.due_date), "issue_date": str(c.issue_date) if c.issue_date else None,
            "status": c.status, "party_type": c.party_type, "party_id": c.party_id, "party_name": c.party_name,
            "description": c.description, "days_left": (c.due_date - _lt_today()).days}


@router.get("/cheques")
def cheques(status: str | None = None, direction: str | None = None, db: Session = Depends(get_db),
            _: User = Depends(require_permission("accounting.view"))):
    stmt = select(Cheque)
    if status:
        stmt = stmt.where(Cheque.status == status.upper())
    if direction:
        stmt = stmt.where(Cheque.direction == direction.upper())
    return [_cheque_out(c) for c in db.execute(stmt.order_by(Cheque.due_date)).scalars()]


@router.post("/cheques", status_code=201)
def create_cheque(body: ChequeIn, db: Session = Depends(get_db),
                  user: User = Depends(require_permission("accounting.post"))):
    name = body.party_name
    if not name and body.party_type == "CUSTOMER" and body.party_id:
        c = db.get(Customer, body.party_id)
        name = f"{c.name} {c.last_name or ''}".strip() if c else None
    if not name and body.party_type == "SUPPLIER" and body.party_id:
        s = db.get(Supplier, body.party_id)
        name = s.name if s else None
    try:
        chq = acc.record_cheque(db, direction=body.direction, number=body.number, amount=body.amount,
                                due_date=body.due_date, bank_name=body.bank_name, party_type=body.party_type,
                                party_id=body.party_id, party_name=name, description=body.description,
                                issue_date=body.issue_date, user=user)
    except acc.AccountingError as ex:
        db.rollback()
        _raise(ex)
    db.commit()
    return _cheque_out(chq)


@router.post("/cheques/{cheque_id}/clear")
def cheque_clear(cheque_id: int, db: Session = Depends(get_db), user: User = Depends(require_permission("accounting.post"))):
    try:
        c = acc.clear_cheque(db, cheque_id=cheque_id, user=user)
    except acc.AccountingError as ex:
        db.rollback()
        _raise(ex)
    db.commit()
    return _cheque_out(c)


@router.post("/cheques/{cheque_id}/bounce")
def cheque_bounce(cheque_id: int, db: Session = Depends(get_db), user: User = Depends(require_permission("accounting.post"))):
    try:
        c = acc.bounce_cheque(db, cheque_id=cheque_id, user=user)
    except acc.AccountingError as ex:
        db.rollback()
        _raise(ex)
    db.commit()
    return _cheque_out(c)


# ---- cash sessions (shift / Z-report) ----------------------------------------
def _session_out(db: Session, s: CashSession) -> dict:
    summ = acc.session_summary(db, s)
    return {"id": s.id, "user_id": s.user_id, "status": s.status, "opened_at": s.opened_at.isoformat(),
            "closed_at": s.closed_at.isoformat() if s.closed_at else None,
            "opening_float": float(s.opening_float),
            "expected_cash": float(s.expected_cash) if s.expected_cash is not None else summ["expected_cash"],
            "counted_cash": float(s.counted_cash) if s.counted_cash is not None else None,
            "difference": float(s.difference) if s.difference is not None else None,
            "note": s.note, **summ}


@router.get("/cash-sessions/current")
def current_session(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    s = db.execute(select(CashSession).where(CashSession.user_id == user.id, CashSession.status == "OPEN")
                   ).scalar_one_or_none()
    return _session_out(db, s) if s else None


class OpenIn(BaseModel):
    opening_float: Decimal = Field(default=Decimal(0), ge=0)


@router.post("/cash-sessions/open", status_code=201)
def open_session(body: OpenIn, db: Session = Depends(get_db), user: User = Depends(require_permission("pos.sell"))):
    try:
        s = acc.open_cash_session(db, user=user, opening_float=body.opening_float)
    except acc.AccountingError as ex:
        db.rollback()
        _raise(ex)
    db.commit()
    return _session_out(db, s)


class CloseIn(BaseModel):
    counted_cash: Decimal = Field(ge=0)
    note: str | None = None


@router.post("/cash-sessions/{session_id}/close")
def close_session(session_id: int, body: CloseIn, db: Session = Depends(get_db),
                  user: User = Depends(require_permission("pos.sell"))):
    s = db.get(CashSession, session_id)
    if s and s.user_id != user.id and "accounting.close" not in {p.code for r in user.roles for p in r.permissions}:
        raise HTTPException(403, "فقط صاحب شیفت یا حسابدار می‌تواند شیفت را ببندد")
    try:
        s = acc.close_cash_session(db, session_id=session_id, counted_cash=body.counted_cash, note=body.note, user=user)
    except acc.AccountingError as ex:
        db.rollback()
        _raise(ex)
    db.commit()
    return _session_out(db, s)


@router.get("/cash-sessions")
def list_sessions(limit: int = Query(50, le=500), db: Session = Depends(get_db),
                  _: User = Depends(require_permission("accounting.view"))):
    rows = db.execute(select(CashSession).order_by(CashSession.id.desc()).limit(limit)).scalars().all()
    users = {u.id: u.full_name or u.username for u in db.execute(select(User)).scalars()}
    return [{**_session_out(db, s), "user": users.get(s.user_id)} for s in rows]
