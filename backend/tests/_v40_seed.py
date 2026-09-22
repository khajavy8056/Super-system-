# -*- coding: utf-8 -*-
"""Shared seeding for the v4.0 brain tests.

Not a test module itself — it exists so the reasoning tests and the acceptance
scenarios describe the *same* shop. The numbers are the brief's scenario #1:

* 180,000,000 toman of capital in the drawer;
* an issued cheque of 120,000,000 due tomorrow and one of 80,000,000 due in
  three days;
* two debtors: 90,000,000 (a customer with a real payment history) and
  70,000,000 (a slow payer);
* a fast-moving product with two healthy batches and a slow one whose batch
  expires in twelve days;
* two suppliers, one of which carries the urgent cheque.

Everything is relative to ``today``, so the seeding never becomes a time bomb.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

M = Decimal(1_000_000)


def seed_shop(db, *, tag="v40", cash=180, cheques=((120, 1), (80, 3)), receivables=(90, 70),
              expiring_batch=True, sales_days=14):
    """Create the scenario shop. Returns a dict of the objects created."""
    from app.models import Customer, Invoice, InvoiceItem, Product, ProductBatch
    from app.services import accounting as acc
    from app.services import ledger as ledger_svc
    from app.services.business_brain import policies

    acc.ensure_chart(db)
    policies.ensure_defaults(db)
    today = date.today()

    acc.post(db, kind="OPENING",
             lines=[acc.Line(acc.A_CASH, debit=Decimal(cash) * M),
                    acc.Line(acc.A_CAPITAL, credit=Decimal(cash) * M)],
             description=f"{tag} capital")

    supplier_x = acc.Supplier(name=f"{tag} پخش الف", is_active=True)
    supplier_y = acc.Supplier(name=f"{tag} پخش ب", is_active=True)
    db.add_all([supplier_x, supplier_y])
    db.flush()

    fast = Product(name=f"{tag} برنج ایرانی ۵ کیلویی", barcode=f"626000{abs(hash(tag)) % 10 ** 6:06d}0",
                   is_active=True)
    slow = Product(name=f"{tag} روغن آفتابگردان", barcode=f"626000{abs(hash(tag)) % 10 ** 6:06d}1",
                   is_active=True)
    db.add_all([fast, slow])
    db.flush()

    for offset, (buy, sell) in ((10, ("6200000", "7000000")), (5, ("6300000", "7100000"))):
        db.add(ProductBatch(product_id=fast.id, batch_number=f"{tag}-B{offset}",
                            current_qty=40 + offset, quantity_received=60,
                            buy_price=Decimal(buy), sell_price=Decimal(sell),
                            supplier_id=supplier_x.id, status="ACTIVE", received_at=datetime.utcnow(),
                            expiry_date=today + timedelta(days=220)))
    if expiring_batch:
        db.add(ProductBatch(product_id=slow.id, batch_number=f"{tag}-O1", current_qty=12,
                            quantity_received=24, buy_price=Decimal("2500000"),
                            sell_price=Decimal("3200000"), supplier_id=supplier_y.id, status="ACTIVE",
                            received_at=datetime.utcnow(), expiry_date=today + timedelta(days=12)))
    db.flush()

    for day in range(1, sales_days + 1):
        created = datetime.utcnow() - timedelta(days=day)
        invoice = Invoice(invoice_number=f"{tag}-S{day}", status="PAID", payment_status="PAID",
                          payment_method="CASH", subtotal=Decimal(3) * M,
                          total_amount=Decimal(3) * M, created_at=created, paid_at=created)
        db.add(invoice)
        db.flush()
        db.add(InvoiceItem(invoice_id=invoice.id, product_id=fast.id, qty=2,
                           unit_buy_price=Decimal("6250000"), unit_sell_price=Decimal("7000000"),
                           subtotal=Decimal(14) * M, profit=Decimal("1500000"), created_at=created))

    issued = []
    for index, (amount, days) in enumerate(cheques):
        supplier = supplier_x if index == 0 else supplier_y
        issued.append(acc.record_cheque(
            db, direction="ISSUED", number=f"{tag}-{1001 + index}", amount=Decimal(amount) * M,
            due_date=today + timedelta(days=days), bank_name="ملت", party_type="SUPPLIER",
            party_id=supplier.id, party_name=supplier.name))

    good = Customer(name=f"{tag} مشتری خوش‌حساب", phone="09120000001", is_active=True)
    slow_payer = Customer(name=f"{tag} مشتری کند", phone="09120000002", is_active=True)
    db.add_all([good, slow_payer])
    db.flush()

    if receivables:
        for customer, amount in zip((good, slow_payer), receivables):
            if not amount:
                continue
            customer.credit_enabled = True
            amount = Decimal(amount) * M
            created = datetime.utcnow() - timedelta(days=20)
            invoice = Invoice(invoice_number=f"{tag}-C{customer.id}", status="PAID",
                              payment_status="UNPAID", payment_method="ACCOUNT", subtotal=amount,
                              total_amount=amount, customer_id=customer.id, created_at=created)
            db.add(invoice)
            db.flush()
            db.add(InvoiceItem(invoice_id=invoice.id, product_id=fast.id, qty=1,
                               unit_buy_price=amount * Decimal("0.8"), unit_sell_price=amount,
                               subtotal=amount, profit=amount * Decimal("0.2"), created_at=created))
            ledger_svc.charge_invoice_to_account(db, customer_id=customer.id, invoice=invoice)
            acc.post(db, kind="SALE",
                     lines=[acc.Line(acc.A_RECEIVABLE, debit=amount, party_type="CUSTOMER",
                                     party_id=customer.id),
                            acc.Line(acc.A_SALES, credit=amount)],
                     description=f"{tag} credit sale #{customer.id}")

        # the good payer has a real payment history (three settlements)
        for _ in range(3 if (receivables and receivables[0]) else 0):
            ledger_svc.post_entry(db, customer_id=good.id, entry_type="PAYMENT",
                                  amount=Decimal(2) * M, method="CASH")
            acc.post(db, kind="SETTLEMENT",
                     lines=[acc.Line(acc.A_CASH, debit=Decimal(2) * M),
                            acc.Line(acc.A_RECEIVABLE, credit=Decimal(2) * M, party_type="CUSTOMER",
                                     party_id=good.id)],
                     description=f"{tag} settlement")

    # purchases on credit so payables — and the cheques drawn against them — are real
    for supplier, amount in ((supplier_x, Decimal(str(issued[0].amount)) if issued else 0),
                             (supplier_y, Decimal(str(issued[1].amount)) if len(issued) > 1 else 0)):
        if not amount:
            continue
        acc.post(db, kind="PURCHASE",
                 lines=[acc.Line(acc.A_INVENTORY, debit=amount),
                        acc.Line(acc.A_PAYABLE, credit=amount, party_type="SUPPLIER",
                                 party_id=supplier.id)],
                 description=f"{tag} purchase {supplier.name}")

    db.commit()
    return {"db": db, "fast": fast, "slow": slow, "good": good, "slow_payer": slow_payer,
            "supplier_x": supplier_x, "supplier_y": supplier_y, "cheques": issued, "tag": tag}


def fresh_store():
    """A brand-new, completely empty shop database.

    Used by the acceptance tests that need to prove the brain does *not* invent a
    recommendation when there is nothing to recommend — which cannot be shown on
    the shared test database that other tests have already filled.
    """
    import tempfile
    from pathlib import Path

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.database import Base
    import app.models  # noqa: F401  (registers every table on Base)

    path = Path(tempfile.mkdtemp(prefix="v40_empty_")) / "empty.db"
    engine = create_engine(f"sqlite:///{path}", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)()
