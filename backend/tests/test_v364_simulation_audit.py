import sqlite3
from datetime import datetime

import pytest
from sqlalchemy import select

from app.database import SessionLocal
from app.models import Invoice, JournalEntry, FiscalPeriod
from app.services.demo_store import _stamp_journal
from app.services.simulation_audit import audit


@pytest.fixture
def snapshot():
    db = sqlite3.connect(':memory:')
    db.executescript('''
        CREATE TABLE acc_journal_entries(id INTEGER, status TEXT, source_type TEXT,
            source_id INTEGER, kind TEXT, entry_date TEXT);
        CREATE TABLE acc_accounts(id INTEGER, code TEXT);
        CREATE TABLE acc_journal_lines(id INTEGER, entry_id INTEGER, debit REAL, credit REAL,
            account_id INTEGER, party_type TEXT, party_id INTEGER);
        CREATE TABLE product_batches(id INTEGER, current_qty REAL);
        CREATE TABLE stock_movements(batch_id INTEGER, quantity REAL);
        CREATE TABLE invoices(id INTEGER, status TEXT, subtotal REAL, discount REAL,
            tax REAL, total_amount REAL, created_at TEXT);
        CREATE TABLE invoice_items(invoice_id INTEGER, qty REAL, unit_sell_price REAL);
        CREATE TABLE payments(invoice_id INTEGER, amount REAL);
        CREATE TABLE customer_ledger_entries(id INTEGER, customer_id INTEGER, amount REAL, balance_after REAL, entry_type TEXT DEFAULT "ADJUSTMENT", method TEXT);
        INSERT INTO acc_journal_entries VALUES(1,'POSTED','Invoice',1,'SALE','2020-01-02');
        INSERT INTO acc_accounts VALUES(1,'1201'),(2,'4101'),(3,'1101');
        INSERT INTO acc_journal_lines VALUES(1,1,80,0,1,'CUSTOMER',1),(2,1,0,100,2,NULL,NULL),(3,1,20,0,3,NULL,NULL);
        INSERT INTO product_batches VALUES(1,9);
        INSERT INTO stock_movements VALUES(1,10),(1,-1);
        INSERT INTO invoices VALUES(1,'PAID',100,0,0,100,'2020-01-01 22:00:00');
        INSERT INTO invoice_items VALUES(1,1,100);
        INSERT INTO payments VALUES(1,100);
        INSERT INTO customer_ledger_entries(id,customer_id,amount,balance_after) VALUES(1,1,100,100),(2,1,-20,80);
    ''')
    yield db
    db.close()


def test_valid_snapshot_and_local_journal_date(snapshot):
    assert audit(snapshot)['ok']


@pytest.mark.parametrize('sql,check', [
    ('UPDATE acc_journal_lines SET debit=99 WHERE id=1', 'unbalanced_journals'),
    ('UPDATE product_batches SET current_qty=8', 'batch_movement_mismatch'),
    ('UPDATE product_batches SET current_qty=-1', 'negative_stock'),
    ('UPDATE invoices SET subtotal=101', 'invoice_gross_mismatch'),
    ('UPDATE invoices SET total_amount=90', 'invoice_total_mismatch'),
    ('UPDATE payments SET amount=99', 'invoice_payment_mismatch'),
    ('UPDATE customer_ledger_entries SET balance_after=5 WHERE id=2', 'customer_running_balance_mismatch'),
    ("UPDATE acc_journal_entries SET entry_date='2020-02-01'", 'sale_journal_date_mismatch'),
    ('DELETE FROM acc_journal_entries', 'missing_sale_journal'),
    ("UPDATE acc_journal_lines SET party_id=2 WHERE id=1", 'receivables_subledger_mismatch'),
    ("UPDATE customer_ledger_entries SET entry_type='PAYMENT',method='CASH' WHERE id=2", 'missing_cash_settlement_journal'),
])
def test_economic_corruption_fails_even_when_sqlite_is_healthy(snapshot, sql, check):
    snapshot.execute(sql)
    assert snapshot.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
    result = audit(snapshot)
    assert not result['ok']
    assert result['checks'][check]['violations'] == (2 if check == 'receivables_subledger_mismatch' else 1)


def test_missing_schema_is_failure_not_silent_skip(snapshot):
    snapshot.execute('DROP TABLE payments')
    result = audit(snapshot)
    assert not result['ok']
    assert 'error' in result['checks']['invoice_payment_mismatch']


def test_backdated_sale_journal_moves_to_correct_fiscal_period(client, auth_headers, milk, two_batches):
    response = client.post('/api/pos/checkout', headers=auth_headers, json={
        'items': [{'product_id': milk['id'], 'batch_id': two_batches['a']['id'], 'quantity': 1}],
        'payments': [{'method': 'CASH', 'amount': 60000}]})
    assert response.status_code == 201, response.text
    iid = response.json()['invoice_id']
    at = datetime(2018, 2, 3, 23, 0)
    with SessionLocal() as db:
        try:
            original = db.execute(select(JournalEntry).where(JournalEntry.source_type=='Invoice', JournalEntry.source_id==iid)).scalar_one()
            line_amounts = [(line.debit, line.credit) for line in original.lines]
            _stamp_journal(db, 'Invoice', iid, at)
            db.refresh(original)
            period = db.get(FiscalPeriod, original.fiscal_period_id)
            assert str(original.entry_date) == '2018-02-04'
            assert period.start_date <= original.entry_date <= period.end_date
            assert [(line.debit, line.credit) for line in original.lines] == line_amounts
        finally:
            db.rollback()  # do not leave a deliberately backdated journal in the shared suite


@pytest.mark.parametrize("by_cheque", [False, True])
def test_demo_settlement_posts_once_and_updates_customer_ledger(client, by_cheque):
    from decimal import Decimal
    from datetime import date
    from app.models import Customer, User, Cheque, CustomerLedgerEntry
    from app.services import ledger
    from app.services.demo_store import _settle_demo_customer
    with SessionLocal() as db:
        try:
            user = db.execute(select(User).order_by(User.id)).scalars().first()
            customer = Customer(name="Settlement audit", credit_enabled=True, credit_limit=0)
            db.add(customer); db.flush()
            ledger.post_entry(db, customer_id=customer.id, entry_type="OPENING_BALANCE", amount=100)
            e = _settle_demo_customer(db, customer=customer, amount=Decimal(20),
                                      day=date(2020, 1, 2), admin=user, by_cheque=by_cheque)
            assert ledger.balance_of(db, customer.id) == 80
            db.refresh(e)
            assert e.created_at.date() == date(2020, 1, 2)
            cash = list(db.execute(select(JournalEntry).where(JournalEntry.source_type=="CustomerLedgerEntry", JournalEntry.source_id==e.id)).scalars())
            if by_cheque:
                assert not cash
                cheque = db.execute(select(Cheque).where(Cheque.party_id==customer.id, Cheque.direction=="RECEIVED")).scalar_one()
                entry = db.get(JournalEntry, cheque.journal_entry_id)
                assert cheque.amount == 20 and cheque.status == "PENDING"
            else:
                assert len(cash) == 1
                entry = cash[0]
            assert sum(l.debit for l in entry.lines) == sum(l.credit for l in entry.lines) == 20
            assert entry.entry_date == date(2020, 1, 2)
        finally:
            db.rollback()


def test_void_mixed_credit_sale_reverses_only_credit_portion_once(client, milk, two_batches):
    from decimal import Decimal as D
    from app.models import Customer, User, CustomerLedgerEntry
    from app.services import ledger, pos
    with SessionLocal() as db:
        try:
            user = db.execute(select(User).order_by(User.id)).scalars().first()
            customer = Customer(name='Void credit regression', credit_enabled=True, credit_limit=0)
            db.add(customer); db.flush()
            ledger.post_entry(db, customer_id=customer.id, entry_type='OPENING_BALANCE', amount=1000)
            inv = pos.checkout(db, items=[pos.CartItem(product_id=milk['id'], quantity=D(1))],
                payments=[{'method':'CASH','amount':'20000'}, {'method':'ACCOUNT','amount':'40000'}],
                user=user, customer_id=customer.id, tax_rate=D(0))
            assert ledger.balance_of(db, customer.id) == 41000
            pos.void_invoice(db, invoice=inv, user=user)
            db.flush()
            assert ledger.balance_of(db, customer.id) == 1000
            credits = list(db.execute(select(CustomerLedgerEntry).where(
                CustomerLedgerEntry.invoice_id==inv.id, CustomerLedgerEntry.entry_type=='RETURN_REFUND')).scalars())
            assert len(credits) == 1 and credits[0].amount == -40000
            with pytest.raises(pos.PosError):
                pos.void_invoice(db, invoice=inv, user=user)
            assert ledger.balance_of(db, customer.id) == 1000
        finally:
            db.rollback()
