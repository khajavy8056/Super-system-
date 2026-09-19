"""v3.0 — «فروشگاه نمونه»: generate one realistic year of a neighbourhood
supermarket through the REAL service layer, then back-date the timestamps.

Why through the service layer: checkout allocates batches, writes movements,
profit per line, ledger entries, payments, coupons; receiving writes batches,
movements and payables. So every report, the intelligence engine and the
A/B measurer see exactly what a real shop would have produced — nothing is
faked in the reports layer.

Realism knobs (deterministic, seeded):
  * ~120 products in 14 categories with real Iranian buy/sell prices (toman)
  * weekday curve (Thursday/Friday peak), monthly seasonality (Ramadan-ish dip,
    Nowruz spike, summer beverages), hour-of-day curve
  * 140 named customers with habits (regulars, VIP whales, churned ones), ~35 % of
    invoices are registered customers, some on credit
  * 4 cashiers; one has a mildly elevated void rate (so LOSS_PREV fires)
  * 3 suppliers with different price/shelf-life quality (SUPPLIER)
  * intentionally planted situations the engine must find:
      - a perishable batch received too big (EXPIRY_LADDER)
      - two dead-stock SKUs bought 5 months ago (DEAD_STOCK)
      - a fast mover with low stock (VELOCITY)
      - one SKU priced under cost (PRICE_GAP)
      - strong basket pairs (bread↔cheese, tea↔sugar, chips↔soda …) (CROSS_SELL)
      - issued cheques clustering next month (CASHFLOW)
  * ~6 % of registered customers stop coming 40–70 days before "today" (CHURN)

`generate(db, days=365)` returns a summary; `generate_backup_file(path)` builds
a standalone .db you can import from Settings → Backup.
"""
from __future__ import annotations

import json
import logging
import math
import random
from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select, text, update
from sqlalchemy.orm import Session

from ..models import (Brand, Category, Cheque, Customer, CustomerLedgerEntry, Expense, ExpenseCategory, Invoice, InvoiceItem,
                      Payment, Product, ProductBatch, Return, StockMovement, Supplier, Unit, User)
from . import accounting as acc_svc
from . import catalog
from . import pos as pos_svc
from .audit import write_audit

log = logging.getLogger("supermarket.demo")

D = Decimal

# --------------------------------------------------------------------------- catalogue
# (category, [(name, brand, buy, sell, consumer, perishable_days|None, base_daily_demand)])
CATALOG = {
    "لبنیات": [("شیر کم‌چرب ۱ لیتری", "کاله", 32000, 38000, 39000, 12, 9.0), ("ماست ۹۰۰ گرمی", "میهن", 48000, 56000, 58000, 20, 6.5),
             ("پنیر سفید ۴۰۰ گرمی", "کاله", 62000, 72000, 74000, 40, 5.0), ("دوغ ۱.۵ لیتری", "عالیس", 30000, 36000, 37000, 25, 4.0),
             ("خامه ۲۰۰ گرمی", "پگاه", 26000, 31000, 32000, 15, 2.2), ("کره ۱۰۰ گرمی", "میهن", 42000, 49000, 50000, 60, 2.8)],
    "نان و شیرینی": [("نان تست ۵۰۰ گرمی", "سه‌نان", 38000, 45000, 46000, 7, 6.0), ("کیک صبحانه", "شیرین‌عسل", 12000, 15000, 15000, 90, 5.5),
                 ("بیسکویت ساقه طلایی", "مینو", 20000, 25000, 25000, 180, 4.5), ("کلوچه نادری", "نادری", 9000, 12000, 12000, 60, 4.0)],
    "نوشیدنی": [("نوشابه کولا ۱.۵ لیتری", "زمزم", 22000, 28000, 29000, 240, 7.0), ("نوشابه پرتقالی ۳۰۰ سی‌سی", "کوکاکولا", 11000, 15000, 15000, 240, 6.0),
              ("آب معدنی ۱.۵ لیتری", "دماوند", 8000, 12000, 12000, 365, 9.0), ("آبمیوه سان‌استار ۱ لیتری", "سان‌استار", 45000, 55000, 56000, 180, 2.5),
              ("ماءالشعیر لیمو", "ایستک", 18000, 24000, 25000, 240, 3.5), ("چای کیسه‌ای ۱۰۰ عددی", "گلستان", 95000, 115000, 118000, None, 2.0),
              ("قهوه فوری ۵۰ گرمی", "نسکافه", 120000, 145000, 150000, None, 1.2)],
    "تنقلات": [("چیپس سرکه نمکی", "مزمز", 22000, 28000, 28000, 120, 6.5), ("پفک نمکی", "مینو", 14000, 18000, 18000, 120, 6.0),
             ("پاپ‌کرن پنیری", "چی‌توز", 18000, 23000, 23000, 120, 3.0), ("تخمه آفتابگردان ۲۰۰ گرمی", "مزمز", 35000, 42000, 43000, 150, 2.5),
             ("شکلات تلخ ۸۰٪", "فرمند", 28000, 35000, 35000, 240, 2.0), ("آدامس نعنایی", "بایودنت", 8000, 11000, 11000, 365, 3.5)],
    "خواربار": [("برنج ایرانی ۵ کیلویی", "طبیعت", 620000, 690000, 700000, None, 0.9), ("روغن آفتابگردان ۱.۸ لیتری", "لادن", 165000, 185000, 190000, None, 1.6),
              ("قند شکسته ۱ کیلویی", "شاهسوند", 58000, 66000, 67000, None, 2.2), ("شکر ۹۰۰ گرمی", "شاهسوند", 42000, 48000, 49000, None, 3.0),
              ("ماکارونی ۷۰۰ گرمی", "مانا", 28000, 34000, 35000, None, 3.2), ("رب گوجه ۸۰۰ گرمی", "چین‌چین", 58000, 68000, 69000, None, 2.0),
              ("تن ماهی ۱۸۰ گرمی", "طبیعت", 68000, 79000, 80000, None, 2.6), ("عدس ۹۰۰ گرمی", "خشکپاک", 60000, 70000, 72000, None, 1.2),
              ("لوبیا چیتی ۹۰۰ گرمی", "خشکپاک", 95000, 110000, 112000, None, 0.9), ("نمک تصفیه‌شده", "گلها", 9000, 12000, 12000, None, 1.6),
              ("زعفران ۱ گرمی", "سحرخیز", 140000, 165000, 170000, None, 0.5), ("سس مایونز ۴۵۰ گرمی", "دلپذیر", 55000, 64000, 65000, 180, 2.0),
              ("سس کچاپ ۴۰۰ گرمی", "بیژن", 38000, 45000, 46000, 180, 1.8)],
    "پروتئین": [("تخم‌مرغ ۲۰ عددی", "تلاونگ", 130000, 148000, 150000, 25, 3.6), ("سوسیس آلمانی ۵۰۰ گرمی", "کاله", 98000, 115000, 118000, 30, 1.8),
              ("کالباس خشک ۳۰۰ گرمی", "سولیکو", 110000, 128000, 130000, 30, 1.2), ("مرغ منجمد ۱.۸ کیلویی", "پروتئین گستر", 260000, 295000, 300000, 120, 1.0)],
    "میوه و سبزی": [("سیب زرد (کیلو)", "", 38000, 48000, 0, 14, 4.0), ("موز (کیلو)", "", 75000, 90000, 0, 6, 4.5), ("گوجه‌فرنگی (کیلو)", "", 25000, 34000, 0, 5, 4.0),
                ("خیار (کیلو)", "", 22000, 30000, 0, 6, 3.6), ("سیب‌زمینی (کیلو)", "", 18000, 25000, 0, 30, 3.5), ("پیاز (کیلو)", "", 16000, 22000, 0, 30, 3.0),
                ("لیمو ترش (کیلو)", "", 60000, 75000, 0, 12, 1.2)],
    "بهداشتی": [("شامپو ۴۰۰ میلی", "پرژک", 68000, 82000, 84000, None, 1.6), ("صابون ۱۲۵ گرمی", "گلنار", 14000, 18000, 18000, None, 2.8),
              ("خمیردندان ۱۰۰ میلی", "پونه", 38000, 46000, 47000, None, 1.8), ("دستمال کاغذی ۳۰۰ برگ", "تنو", 42000, 50000, 51000, None, 4.0),
              ("پوشک سایز ۴", "مای‌بیبی", 280000, 320000, 325000, None, 0.6), ("نوار بهداشتی", "مای‌لیدی", 45000, 54000, 55000, None, 1.2)],
    "شوینده": [("مایع ظرفشویی ۱ لیتری", "پریل", 52000, 62000, 63000, None, 2.4), ("پودر لباسشویی ۵۰۰ گرمی", "پرسیل", 48000, 57000, 58000, None, 1.8),
             ("مایع دستشویی ۵۰۰ میلی", "اکتیو", 40000, 48000, 49000, None, 1.6), ("سفیدکننده ۱ لیتری", "وایتکس", 22000, 28000, 28000, None, 1.4)],
    "کنسرو و آماده": [("کنسرو لوبیا", "دلپذیر", 38000, 45000, 46000, None, 1.6), ("کنسرو ذرت", "مهرام", 42000, 50000, 51000, None, 1.2),
                  ("نودل فوری", "الیت", 12000, 15000, 15000, 180, 3.8), ("سوپ آماده", "الیت", 18000, 22000, 22000, 240, 1.0)],
    "صبحانه": [("عسل ۵۰۰ گرمی", "خوانسار", 190000, 220000, 225000, None, 0.7), ("مربا آلبالو", "شانا", 48000, 56000, 57000, None, 0.9),
             ("کره بادام‌زمینی", "شیررضا", 85000, 98000, 100000, None, 0.7), ("غلات صبحانه", "نستله", 95000, 110000, 112000, None, 0.8),
             ("حلوا شکری", "عقاب", 32000, 38000, 39000, None, 1.6)],
    "بستنی و یخی": [("بستنی وانیلی ۱ لیتری", "میهن", 65000, 78000, 80000, 180, 1.4), ("بستنی چوبی", "دومینو", 12000, 16000, 16000, 180, 4.2),
                ("یخ در بهشت", "میهن", 9000, 12000, 12000, 180, 2.0)],
    "سیگار و متفرقه": [("کبریت", "توکلی", 2000, 3000, 3000, None, 1.5), ("باتری قلمی ۴ عددی", "سونی", 45000, 55000, 56000, None, 0.6),
                   ("کیسه زباله رول", "پاکنام", 25000, 30000, 30000, None, 1.8), ("فندک", "", 6000, 9000, 9000, None, 1.2)],
    "بچه و حیوانات": [("شیرخشک ۴۰۰ گرمی", "نان", 250000, 285000, 290000, None, 0.4), ("غذای گربه ۱ کیلویی", "رفلکس", 180000, 210000, 215000, None, 0.3)],
}

# basket affinity pairs (name fragments) with probability that the second joins when the first is in
PAIRS = [("نان تست", "پنیر سفید", 0.55), ("چای کیسه‌ای", "قند شکسته", 0.5), ("چیپس", "نوشابه کولا", 0.45), ("پفک", "نوشابه پرتقالی", 0.4),
         ("ماکارونی", "رب گوجه", 0.6), ("شیر کم‌چرب", "کیک صبحانه", 0.35), ("مرغ منجمد", "روغن آفتابگردان", 0.3), ("تخم‌مرغ", "نان تست", 0.35),
         ("سیب‌زمینی", "پیاز", 0.5), ("خیار", "گوجه‌فرنگی", 0.55), ("پودر لباسشویی", "سفیدکننده", 0.35), ("شامپو", "صابون", 0.3),
         ("بستنی چوبی", "آب معدنی", 0.3), ("نودل فوری", "سس کچاپ", 0.35), ("زعفران", "برنج ایرانی", 0.4)]

FIRST = ["علی", "محمد", "حسین", "رضا", "مهدی", "امیر", "سعید", "مریم", "فاطمه", "زهرا", "نرگس", "سارا", "لیلا", "نسرین", "مینا", "پریسا", "حمید", "مجید", "بهرام", "کامران", "الهام", "شیرین", "سمیرا", "احمد", "ناصر", "فرهاد", "نیما", "آرش", "پویا", "شهاب"]
LAST = ["احمدی", "محمدی", "رضایی", "کریمی", "موسوی", "حسینی", "جعفری", "صادقی", "نوری", "کاظمی", "رحیمی", "قاسمی", "اکبری", "عباسی", "بهرامی", "شریفی", "نظری", "زارعی", "سلطانی", "یوسفی"]

SUPPLIERS = [("پخش سراسری کاله", 0.00, 0.05), ("پخش مهرگان", 0.06, 0.30), ("بنکداری حاج‌قاسم", 0.02, 0.10)]   # (name, price premium, short-life share)

MONTH_FACTOR = {1: 1.02, 2: 0.98, 3: 1.28, 4: 0.92, 5: 0.96, 6: 1.06, 7: 1.10, 8: 1.08, 9: 1.00, 10: 0.97, 11: 0.95, 12: 1.03}   # Gregorian; March = Nowruz shopping
WEEKDAY_FACTOR = {0: 0.92, 1: 0.90, 2: 0.95, 3: 1.22, 4: 1.28, 5: 0.98, 6: 0.90}   # Mon..Sun; Thu/Fri peak (Iranian weekend)
HOURS = [(8, 0.03), (9, 0.05), (10, 0.07), (11, 0.08), (12, 0.08), (13, 0.06), (14, 0.05), (15, 0.05), (16, 0.07), (17, 0.09), (18, 0.11), (19, 0.12), (20, 0.09), (21, 0.05)]


def _rng(seed: int) -> random.Random:
    return random.Random(seed)


def _fix_created(db: Session, table: str, ids: list[int], at: datetime) -> None:
    if not ids:
        return
    db.execute(text(f"UPDATE {table} SET created_at=:at WHERE id IN ({','.join(str(i) for i in ids)})"), {"at": at})


def _stamp_journal(db: Session, source: str, source_id: int, at: datetime) -> None:
    """Backdate the generated source's journal AND its reversal, including fiscal year.

    Simulation-only: amounts and journal lines are never rewritten. This is not a
    live accounting repair operation; callers operate on an isolated demo DB.
    """
    local_day = (at + timedelta(hours=3, minutes=30)).date()
    period = acc_svc.ensure_fiscal_period(db, local_day)
    db.flush()
    db.execute(text("""UPDATE acc_journal_entries SET entry_date=:day,
        created_at=:at, updated_at=:at, fiscal_period_id=:period
        WHERE (source_type=:source AND source_id=:id) OR reversal_of_id IN
        (SELECT id FROM acc_journal_entries WHERE source_type=:source AND source_id=:id)
        """), {"day": local_day, "at": at, "period": period.id, "source": source, "id": source_id})


def _settle_demo_customer(db: Session, *, customer: Customer, amount: D, day: date,
                          admin: User, by_cheque: bool = False, due_date: date | None = None):
    """One atomic customer settlement, with exactly one accounting posting.

    ledger.settle posts cash accounting itself. A received cheque's journal is
    posted by record_cheque, so its companion ledger entry must NOT post it twice.
    The caller owns the transaction/savepoint.
    """
    from . import ledger as ledger_svc
    when = datetime.combine(day, datetime.min.time()) + timedelta(hours=10)
    if by_cheque:
        entry = ledger_svc.post_entry(db, customer_id=customer.id, entry_type="PAYMENT",
                                     amount=amount, method="CHEQUE", note="دریافت چک بابت بدهی",
                                     user_id=admin.id)
        cheque = acc_svc.record_cheque(db, direction="RECEIVED",
            number=f"SIM-R-{day.isoformat()}-{customer.id}", amount=amount,
            due_date=due_date or day + timedelta(days=20), bank_name="ملت",
            party_type="CUSTOMER", party_id=customer.id, party_name=customer.name,
            issue_date=day, description="چک دریافتی بابت تسویهٔ بدهی", user=admin)
        _fix_created(db, "acc_cheques", [cheque.id], when)
        _stamp_journal(db, "Cheque", cheque.id, when)
    else:
        result = ledger_svc.settle(db, customer_id=customer.id, amount=amount, method="CASH",
                                   note="تسویهٔ دوره‌ای", user_id=admin.id)
        entry = db.get(CustomerLedgerEntry, result["entry_id"])
        _stamp_journal(db, "CustomerLedgerEntry", entry.id, when)
    _fix_created(db, "customer_ledger_entries", [entry.id], when)
    return entry


def _supplier_weights(n: int) -> list[float]:
    """v3.5.9 — ``random.choices`` silently ignores a population longer than its weight list,
    so a big-store build with 15 wholesalers would have kept buying from the first three only."""
    if n <= 3:
        return [0.5, 0.25, 0.25][:n]
    return [0.34, 0.17, 0.17] + [0.32 / (n - 3)] * (n - 3)


def generate(db: Session, *, days: int = 365, seed: int = 1404, invoices_per_day: float = 95.0, progress=None,
             full_catalog: bool = False, resumable: bool = False, pause_after_days: int | None = None, event_callback=None) -> dict:
    """Build the demo store. Idempotent guard: refuses if the DB already has > 50 invoices."""
    import math
    if not 1 <= days <= 3660 or not math.isfinite(invoices_per_day) or not 1 <= invoices_per_day <= 10000:
        raise ValueError("DEMO_INVALID_SCALE: days 1..3660, invoices/day 1..10000")
    rnd = _rng(seed)
    from contextlib import nullcontext
    from . import simulation_checkpoint as checkpoint
    if resumable and not isinstance(db, checkpoint.ReplaySession):
        raise ValueError("RESUMABLE_REQUIRES_REPLAY_SESSION")
    if pause_after_days is not None and (not resumable or pause_after_days < 1):
        raise ValueError("PAUSE_REQUIRES_RESUMABLE_AND_POSITIVE_DAYS")
    config = checkpoint.signature(days, seed, invoices_per_day, full_catalog) if resumable else None
    saved = checkpoint.load(db, config) if resumable else None
    if saved and saved["phase"] == "complete":
        return saved["summary"]
    if saved is None:
        n_inv = db.execute(select(Invoice.id).limit(51)).all()
        if len(n_inv) > 50:
            raise RuntimeError("DEMO_ON_NONEMPTY_DB")
        today = datetime.utcnow().date()
        # Stress history consists of exactly N completed days, not N+1 dates or a
        # fabricated full current day whose evening has not happened yet.
        if full_catalog:
            from .timeservice import local_today
            today = local_today() - timedelta(days=1)
        start = today - timedelta(days=days - 1 if full_catalog else days)

        admin = db.execute(select(User).order_by(User.id)).scalars().first()
        from ..security import hash_password
        cashiers = []
        for uname, full in (("cashier1", "سمیه رستگار"), ("cashier2", "امیرحسین کیانی"), ("cashier3", "مهسا توکلی")):
            u = db.execute(select(User).where(User.username == uname)).scalar_one_or_none()
            if not u:
                u = User(username=uname, full_name=full, password_hash=hash_password("1234"), is_active=True)
                db.add(u)
                db.flush()
                try:
                    from ..models import Role
                    cashier_role = db.execute(select(Role).where(Role.name.in_(["cashier", "CASHIER", "صندوقدار"]))).scalars().first()
                    if cashier_role:
                        u.roles.append(cashier_role)
                except Exception:
                    pass
            cashiers.append(u)
        users = [admin] + cashiers
        user_weights = [0.15, 0.35, 0.30, 0.20]

        # ---- master data
        unit_piece = db.execute(select(Unit).where(Unit.name.in_(["عدد", "piece"]))).scalars().first()
        unit_kg = db.execute(select(Unit).where(Unit.name.in_(["کیلوگرم", "kg"]))).scalars().first()
        if not unit_piece:
            unit_piece = Unit(name="عدد", symbol="عدد", allow_decimal=False, decimals=0); db.add(unit_piece); db.flush()
        if not unit_kg:
            unit_kg = Unit(name="کیلوگرم", symbol="kg", allow_decimal=True, decimals=3); db.add(unit_kg); db.flush()
        sups = []
        for name, prem, short in SUPPLIERS:
            s = db.execute(select(Supplier).where(Supplier.name == name)).scalar_one_or_none() or Supplier(name=name, phone="021-" + str(rnd.randint(44000000, 88999999)), is_active=True)
            db.add(s); db.flush(); sups.append((s, prem, short))
        if full_catalog:
            # A big store buys from more than three wholesalers. This also gives the SUPPLIER
            # insight a score table long enough to matter — long enough, in fact, to need the
            # v3.5.9 evidence cap, so the stress file reproduces that screen honestly.
            for _nm, _prem, _short in (("پخش آریا", 0.04, 0.10), ("پخش بهار", 0.09, 0.18), ("پخش سپید", 0.02, 0.08),
                                       ("پخش نگین", 0.12, 0.25), ("پخش پارس", 0.06, 0.12), ("پخش زاگرس", 0.15, 0.30),
                                       ("پخش البرز", 0.03, 0.09), ("پخش سهند", 0.08, 0.16), ("پخش رویش", 0.11, 0.22),
                                       ("پخش مهر", 0.05, 0.11), ("پخش کیان", 0.13, 0.27), ("پخش آبان", 0.07, 0.14)):
                s = db.execute(select(Supplier).where(Supplier.name == _nm)).scalar_one_or_none() or Supplier(name=_nm, phone="021-" + str(rnd.randint(44000000, 88999999)), is_active=True)
                db.add(s); db.flush(); sups.append((s, _prem, _short))
        products: list[dict] = []
        bc = 6260000000000 + seed * 100
        for cat_name, items in CATALOG.items():
            cat = db.execute(select(Category).where(Category.name == cat_name)).scalar_one_or_none() or Category(name=cat_name, is_active=True)
            db.add(cat); db.flush()
            for name, brand, buy, sell, cons, shelf, demand in items:
                b = None
                if brand:
                    b = db.execute(select(Brand).where(Brand.name == brand)).scalar_one_or_none() or Brand(name=brand, is_active=True)
                    db.add(b); db.flush()
                bc += 7
                code = str(bc)
                code += str((10 - sum((3 if i % 2 else 1) * int(d) for i, d in enumerate(code[::-1]))) % 10)  # not a real GTIN check but scannable
                loose = "(کیلو)" in name
                p = db.execute(select(Product).where(Product.name == name)).scalar_one_or_none()
                if not p:
                    p = catalog.create_product(db, barcode=None if loose else code[:13], name=name, user=admin, brand_id=b.id if b else None,
                                               category_id=cat.id, unit_id=(unit_kg if loose else unit_piece).id, has_own_barcode=not loose,
                                               min_stock_alert=0)
                products.append({"p": p, "buy": buy, "sell": sell, "cons": cons, "shelf": shelf, "demand": demand, "loose": loose, "stock": 0.0, "cat": cat_name})
        by_name = {d["p"].name: d for d in products}

        # ---- v3.5.9: the FULL default catalogue as a slow-moving long tail -----------------
        # With full_catalog the store carries every SKU in the shipped bank (13,570), each with
        # real receiving history, so a stress backup exercises the whole product range and not
        # just the ~120 curated ones. These are deliberately kept OUT of the daily restock loop:
        # calling sellable() for 13k products x 365 days would never finish. They receive stock
        # on staggered days and join baskets as slow movers.
        long_tail: list[dict] = []
        if full_catalog:
            import zlib
            from . import default_catalog
            default_catalog.import_csv(db, user=admin)
            db.commit()
            known = set(by_name)
            for p in db.execute(select(Product)).scalars():
                if p.name in known:
                    continue
                # deterministic per name (hash() is salted per process, so it would not reproduce)
                h = zlib.crc32(p.name.encode("utf-8"))
                h1 = (h & 0xFFFF) / 0xFFFF
                h2 = ((h >> 16) & 0xFFFF) / 0xFFFF
                sell = int(round((18_000 + h1 * 640_000) / 1000) * 1000)
                buy = int(round(sell * (0.70 + 0.16 * h2) / 100) * 100)
                long_tail.append({"p": p, "buy": buy, "sell": sell, "cons": 0, "shelf": 0,
                                  "demand": round(0.03 + 0.30 * h2, 4), "loose": False,
                                  "stock": 0.0, "cat": "سایر"})
            rnd.shuffle(long_tail)
            log.info("demo: full catalogue loaded — %d long-tail SKUs", len(long_tail))
            if progress:
                progress(0.05)

        # Scale replenishment with traffic; increasing checkouts alone just creates
        # empty shelves instead of exercising a genuinely busy store.
        if full_catalog:
            supply_scale = max(1.0, invoices_per_day / 95.0)
            for product in products + long_tail:
                product["demand"] *= supply_scale

        # ---- customers (140): habits
        customers = []
        customer_count = max(140, min(20000, int(invoices_per_day * 8)))
        for i in range(customer_count):
            nm, ln = rnd.choice(FIRST), rnd.choice(LAST)
            phone = "0912" + str(rnd.randint(1000000, 9999999)) if i % 7 else None
            c = Customer(name=nm, last_name=ln, phone=phone, credit_enabled=(i % 5 == 0), credit_limit=D(2_000_000 if i % 5 == 0 else 0), is_active=True)
            db.add(c); db.flush()
            kind = "vip" if i < customer_count * .086 else "regular" if i < customer_count * .643 else "occasional"
            gap = {"vip": rnd.uniform(1.5, 3.5), "regular": rnd.uniform(4, 9), "occasional": rnd.uniform(14, 40)}[kind]
            churn_day = None
            if kind == "regular" and rnd.random() < 0.10:
                churn_day = today - timedelta(days=rnd.randint(40, 75))
            customers.append({"c": c, "kind": kind, "gap": gap, "next": start + timedelta(days=rnd.uniform(0, gap)), "churn": churn_day, "credit": i % 5 == 0,
                              "fav": rnd.sample(products, 6)})

        # ---- expense categories
        exp_cats = {}
        all_cats = db.execute(select(ExpenseCategory)).scalars().all()
        for nm, alts in (("اجاره", ["اجاره"]), ("برق و گاز", ["آب، برق، گاز و تلفن", "برق"]), ("حقوق", ["حقوق و دستمزد", "حقوق"]),
                         ("حمل", ["حمل و نقل", "حمل"]), ("متفرقه", ["سایر", "متفرقه"])):
            exp_cats[nm] = next((c for a in alts for c in all_cats if a in c.name), all_cats[0])

        # Utility bills are distinct events even where they share the chart-of-accounts category.
        for utility in ("آب", "برق", "گاز"):
            exp_cats[utility] = exp_cats["برق و گاز"]

        pending_expiry = []
    else:
        admin = saved["data"]["admin"]
        cashiers = saved["data"]["cashiers"]
        users = saved["data"]["users"]
        user_weights = saved["data"]["user_weights"]
        sups = saved["data"]["sups"]
        products = saved["data"]["products"]
        by_name = saved["data"]["by_name"]
        long_tail = saved["data"]["long_tail"]
        customers = saved["data"]["customers"]
        exp_cats = saved["data"]["exp_cats"]
        pending_expiry = saved["data"]["pending_expiry"]
        dead = saved["data"]["dead"]
        stats = saved["data"]["stats"]
        fx = saved["data"]["fx"]
        start = saved["data"]["start"]
        today = saved["data"]["today"]
        day = saved["data"]["day"]
        rnd.setstate(saved["rng"])

    # ---- helpers

    def receive(d: dict, when: datetime, qty: float, *, sup=None, shelf_override=None, price_mult=1.0):
        sup = sup or rnd.choices(sups, weights=_supplier_weights(len(sups)))[0]
        s, prem, short = sup
        buy = round(d["buy"] * (1 + prem) * price_mult / 100) * 100
        exp = None
        if d["shelf"]:
            life = shelf_override or (int(d["shelf"] * rnd.uniform(0.45, 0.7)) if rnd.random() < short else int(d["shelf"] * rnd.uniform(0.8, 1.2)))
            exp = (when + timedelta(days=max(2, life))).date()
        # The POS filters expired batches against the REAL clock, so historical batches are received
        # without an expiry and get their (back-dated) expiry stamped at the end of the simulation.
        b = catalog.receive_batch(db, product=d["p"], quantity_received=D(str(round(qty, 3 if d["loose"] else 0))), buy_price=D(buy),
                                  consumer_price=D(d["cons"]) if d["cons"] else None, sell_price=D(d["sell"]), expiry_date=None,
                                  received_at=when, user=admin, paid_from="PAYABLE" if rnd.random() < 0.6 else "CASH", supplier_id=s.id)
        d["stock"] += float(b.quantity_received)
        db.flush()
        _fix_created(db, "product_batches", [b.id], when)
        if exp:
            pending_expiry.append((b.id, exp))
        db.execute(text("UPDATE stock_movements SET created_at=:at WHERE reference_type='ProductBatch' AND reference_id=:bid"), {"at": when, "bid": b.id})
        _stamp_journal(db, "ProductBatch", b.id, when)
        return b

    def sellable(d: dict, on: date) -> float:
        """Stock the POS would actually allocate: ACTIVE batches not expired on that day."""
        rows = db.execute(select(ProductBatch.current_qty, ProductBatch.expiry_date).where(
            ProductBatch.product_id == d["p"].id, ProductBatch.status == "ACTIVE", ProductBatch.current_qty > 0)).all()
        return float(sum(q for q, _ in rows))

    def order(d: dict, day: date):
        """Place a purchase order. Suppliers deliver the next morning (50 %), in two days (35 %)
        or three (15 %) — until it arrives the shelf can run empty (real lost sales)."""
        if d.get("arrives"):
            return
        d["arrives"] = day + timedelta(days=rnd.choices([1, 2, 3], weights=[0.5, 0.35, 0.15])[0])

    def morning_restock(d: dict, day: date):
        """Receive pending deliveries, then decide whether to reorder. The shop reorders when the
        low-stock alert fires (min_stock_alert) — so an accepted «smart minimum» really changes
        purchasing (orders go out days earlier); without one the order is placed only when the
        shelf is (nearly) empty, which is how most small shops actually operate."""
        d["stock"] = sellable(d, day)
        target = d["demand"] * (8 if d["shelf"] and d["shelf"] < 15 else 21)
        if d.get("arrives") and d["arrives"] <= day:
            d["arrives"] = None
            receive(d, datetime.combine(day, datetime.min.time()) + timedelta(hours=7, minutes=rnd.randint(0, 50)), max(target - d["stock"], d["demand"] * 5, 6))
            d["stock"] = sellable(d, day)
        min_alert = float(getattr(d["p"], "min_stock_alert", 0) or 0)
        if min_alert and d["stock"] <= min_alert:
            order(d, day)
        elif d["stock"] < d["demand"] * 0.6 or d["stock"] < 2:
            order(d, day)

    if saved is None:
        # ---- opening stock
        t0 = datetime.combine(start, datetime.min.time()) + timedelta(hours=7)
        for d in products:
            receive(d, t0, d["demand"] * (7 if d["shelf"] and d["shelf"] < 15 else 20))

        # planted dead stock: two SKUs over-bought 5 months ago
        dead = [by_name["غذای گربه ۱ کیلویی"], by_name["شیرخشک ۴۰۰ گرمی"]]
        for d in dead:
            d["demand"] = 0.006   # a salesman talked the owner into 60 units; they barely move
            d["planted_dead"] = True
        for cu in customers:   # nobody's "usual basket" contains the dead SKUs
            cu["fav"] = [x for x in cu["fav"] if not x.get("planted_dead")] or rnd.sample([x for x in products if not x.get("planted_dead")], 6)

        stats = {"invoices": 0, "lines": 0, "sales": 0.0, "voids": 0, "returns": 0, "credit": 0, "accepted_insights": 0, "lost_sales": 0}
        # effects of manager-accepted suggestions (filled by _manager_reviews); the simulation honours them
        fx = {"pair_boost": {}, "vip_ids": set(), "winback_ids": set(), "visit_ids": set(), "price_fixed": set(), "nudge_pairs": {}, "boosted_products": {}}
        # Do not retain every historical invoice id in Python; the database is the ledger.
        day = start
    total_days = days
    def checkpoint_state():
        return {"phase": "running", "rng": rnd.getstate(), "data": dict(
            admin=admin,
            cashiers=cashiers,
            users=users,
            user_weights=user_weights,
            sups=sups,
            products=products,
            by_name=by_name,
            long_tail=long_tail,
            customers=customers,
            exp_cats=exp_cats,
            pending_expiry=pending_expiry,
            dead=dead,
            stats=stats,
            fx=fx,
            start=start,
            today=today,
            day=day)}
    if resumable and saved is None:
        checkpoint.save(db, config, checkpoint_state())
        db.commit()
    if event_callback:
        event_callback({"phase": "days", "done": (day - start).days,
                        "total": (today - start).days + 1, "invoices": stats["invoices"]})
    completed_here = 0
    while day <= today:
        with db.atomic_day() if resumable else nullcontext():
            di = (day - start).days
            if progress:
                progress(0.05 + 0.87 * (di / total_days))   # v3.5.9: daily, mapped into the build's 5..92 %
            if di in (total_days - 45, total_days - 20):
                db.commit()
                _manager_reviews(db, day, admin, products, customers, fx, stats, by_name)
            month_f = MONTH_FACTOR[day.month]
            wd_f = WEEKDAY_FACTOR[day.weekday()]
            growth = 1 + 0.18 * (di / total_days)   # the store grows ~18 % over the year
            n_today = max(20, int(rnd.gauss(invoices_per_day * month_f * wd_f * growth, 8)))
            if day == today and not full_catalog:
                n_today = int(n_today * 0.55)
            if di == total_days - 150:
                for d in dead:
                    receive(d, datetime.combine(day, datetime.min.time()) + timedelta(hours=9), 60, sup=sups[1])
            # daily restock in the morning
            for d in products:
                if d.get("planted_dead"):
                    d["stock"] = sellable(d, day)
                    continue
                morning_restock(d, day)
            # v3.5.9 — long-tail SKUs receive stock on staggered days, so every barcode in the
            # shipped bank ends up with a batch, a supplier and a stock movement somewhere in
            # the year instead of only the curated ~120 SKUs having history.
            if long_tail:
                per = max(1, -(-len(long_tail) // total_days))
                for x in long_tail[di * per:(di + 1) * per]:
                    if x["stock"] <= 0:
                        receive(x, datetime.combine(day, datetime.min.time()) + timedelta(hours=8, minutes=rnd.randint(0, 59)),
                                max(6.0, round(x["demand"] * rnd.randint(60, 160), 1)), sup=rnd.choice(sups))
                        x["stock"] = sellable(x, day)
            # customers due today
            due = [c for c in customers if c["next"] <= day and (not c["churn"] or day < c["churn"] or c["c"].id in fx["winback_ids"])]
            rnd.shuffle(due)
            for k in range(n_today):
                hour = rnd.choices([h for h, _ in HOURS], weights=[w for _, w in HOURS])[0]
                when = datetime.combine(day, datetime.min.time()) + timedelta(hours=hour, minutes=rnd.randint(0, 59), seconds=rnd.randint(0, 59)) - timedelta(hours=3, minutes=30)
                cust = None
                if due and rnd.random() < 0.55:
                    cust = due.pop()
                    cust["next"] = day + timedelta(days=max(1, rnd.gauss(cust["gap"], cust["gap"] * 0.3)))
                # basket
                n_items = max(1, int(rnd.lognormvariate(1.1, 0.55)))
                if cust and cust["kind"] == "vip":
                    n_items += 4
                if cust and cust["c"].id in fx["vip_ids"]:
                    n_items += 1   # the VIP coupon pulls an extra line into the basket
                if cust and cust.get("nudged_until") and day <= cust["nudged_until"] and rnd.random() < 0.7:
                    n_items += 1   # came for «the usual item» after the personal SMS — and picked one more thing
                pool = products if not cust else (cust["fav"] * 2 + products)
                weights = [max(0.05, x["demand"]) * (1.6 if (x["cat"] in ("نوشیدنی", "بستنی و یخی") and day.month in (6, 7, 8)) else 1.0) for x in pool]
                chosen: dict[int, dict] = {}
                for _ in range(n_items):
                    x = rnd.choices(pool, weights=weights)[0]
                    chosen[x["p"].id] = x
                for a, b, prob in PAIRS:
                    if any(a in x["p"].name for x in chosen.values()) and rnd.random() < prob:
                        y = by_name.get(next((n for n in by_name if b in n), ""), None)
                        if y:
                            chosen[y["p"].id] = y
                # accepted CROSS_SELL / nudges: shelf move + cashier whisper lift the attach rate
                for (pa, pb), lift in fx["pair_boost"].items():
                    if pa in chosen and pb not in chosen and rnd.random() < lift:
                        yb = next((x for x in products if x["p"].id == pb), None)
                        if yb:
                            chosen[pb] = yb
                for pid, lift in fx["boosted_products"].items():
                    if pid not in chosen and rnd.random() < lift:
                        yb = next((x for x in products if x["p"].id == pid), None)
                        if yb:
                            chosen[pid] = yb
                # v3.5.9 — slow movers join baskets, so most of the long tail accrues real
                # sales history over the year (and the reports have something to aggregate).
                if long_tail and rnd.random() < 0.10:
                    for _ in range(rnd.choices([1, 2, 3], weights=[0.7, 0.22, 0.08])[0]):
                        _x = long_tail[rnd.randrange(len(long_tail))]
                        if _x["stock"] > 0:
                            chosen[_x["p"].id] = _x
                items = []
                for x in chosen.values():
                    q = round(rnd.uniform(0.3, 2.2), 3) if x["loose"] else (rnd.choices([1, 2, 3, 6], weights=[0.7, 0.2, 0.07, 0.03])[0])
                    if x["stock"] < q:
                        # empty shelf: the customer leaves without it (lost sale) and the order goes out today
                        if not x.get("planted_dead"):
                            order(x, day)
                            stats["lost_sales"] += 1
                        continue
                    items.append((x, q))
                if not items:
                    continue
                cart = [pos_svc.CartItem(product_id=x["p"].id, quantity=D(str(q))) for x, q in items]
                # price the cart exactly like the POS does (batch prices change when the manager accepts a
                # markdown / price fix — paying the catalogue price would make the checkout fail silently)
                try:
                    total_est = float(sum(l.subtotal for l in pos_svc.validate_cart(db, [pos_svc.CartItem(product_id=x["p"].id, quantity=D(str(q))) for x, q in items])))
                except Exception:
                    total_est = sum(x["sell"] * q for x, q in items)
                on_credit = bool(cust and cust["credit"] and rnd.random() < 0.35)
                # v3.5.7 — the account tender is called ACCOUNT everywhere else
                # (pos.checkout sums on_account over method == "ACCOUNT", and the till's
                # own dropdown offers value="ACCOUNT"). This said "CREDIT", a name nothing
                # recognises, so on_account stayed 0: every "نسیه" sale was written up as
                # fully PAID, no customer debt was ever posted, and the fortnightly
                # settlement loop below then found balance_after == 0 and posted nothing
                # either. The demo store shipped with zero receivables.
                method = "ACCOUNT" if on_credit else rnd.choices(["CARD", "CASH"], weights=[0.72, 0.28])[0]
                user = rnd.choices(users, weights=user_weights)[0]
                coupon_obj = None
                if cust and cust["c"].id in (fx["vip_ids"] | fx["winback_ids"]) and rnd.random() < 0.6:
                    from ..models import Coupon
                    coupon_obj = db.execute(select(Coupon).where(Coupon.customer_id == cust["c"].id, Coupon.status == "ACTIVE",
                                                                 Coupon.used_count < Coupon.usage_limit)).scalars().first()
                    if coupon_obj and coupon_obj.valid_until and coupon_obj.valid_until < when:
                        coupon_obj = None
                inv_disc = None
                if coupon_obj:
                    # coupon validity is judged against the simulated day (the service uses the wall clock),
                    # so the discount is applied as an invoice discount and the coupon is consumed for real.
                    inv_disc = D(str(round(total_est * float(coupon_obj.discount_value) / 100))) if coupon_obj.discount_type == "PERCENT" else D(str(coupon_obj.discount_value))
                pay_amt = round(total_est - float(inv_disc or 0))
                sp = db.begin_nested()
                try:
                    inv = pos_svc.checkout(db, items=cart, payments=[{"method": method, "amount": str(pay_amt)}],
                                           user=user, customer_id=cust["c"].id if cust else None, tax_rate=D(0), invoice_discount=inv_disc)
                    if coupon_obj:
                        from ..models import CouponRedemption
                        coupon_obj.used_count += 1
                        if coupon_obj.used_count >= coupon_obj.usage_limit:
                            coupon_obj.status = "USED"
                        db.add(CouponRedemption(coupon_id=coupon_obj.id, invoice_id=inv.id, customer_id=cust["c"].id, amount=inv_disc, created_at=when))
                    sp.commit()
                except Exception as exc:  # stock race etc.
                    sp.rollback()
                    log.warning("demo checkout skipped: %s", exc)
                    continue
                for x, q in items:
                    x["stock"] -= float(q)
                db.flush()
                # back-date everything the checkout wrote
                db.execute(text("UPDATE invoices SET created_at=:at, paid_at=:at, updated_at=:at WHERE id=:id"), {"at": when, "id": inv.id})
                db.execute(text("UPDATE invoice_items SET created_at=:at WHERE invoice_id=:id"), {"at": when, "id": inv.id})
                db.execute(text("UPDATE payments SET created_at=:at WHERE invoice_id=:id"), {"at": when, "id": inv.id})
                db.execute(text("UPDATE coupon_redemptions SET created_at=:at WHERE invoice_id=:id"), {"at": when, "id": inv.id})
                db.execute(text("UPDATE stock_movements SET created_at=:at WHERE reference_type='Invoice' AND reference_id=:id"), {"at": when, "id": inv.id})
                db.execute(text("UPDATE customer_ledger_entries SET created_at=:at WHERE invoice_id=:id"), {"at": when, "id": inv.id})
                db.execute(text("UPDATE audit_logs SET created_at=:at WHERE entity_type='Invoice' AND entity_id=:id"), {"at": when, "id": inv.id})
                _stamp_journal(db, "Invoice", inv.id, when)
                stats["invoices"] += 1; stats["lines"] += len(items); stats["sales"] += float(inv.total_amount)
                if on_credit:
                    stats["credit"] += 1
                # voids: cashier2 has an elevated rate (planted LOSS_PREV)
                vr = 0.045 if user.username == "cashier2" else 0.008
                if rnd.random() < vr:
                    sp = db.begin_nested()
                    try:
                        pos_svc.void_invoice(db, invoice=inv, user=user, reason="اشتباه صندوق‌دار")
                        db.flush()
                        for x, q in items:
                            x["stock"] += float(q)
                        db.execute(text("UPDATE audit_logs SET created_at=:at WHERE action='SALE_VOIDED' AND entity_id=:id"), {"at": when + timedelta(minutes=3), "id": inv.id})
                        db.execute(text("UPDATE stock_movements SET created_at=:at WHERE reference_type='Invoice' AND reference_id=:id AND movement_type='VOID_REVERSAL'"), {"at": when + timedelta(minutes=3), "id": inv.id})
                        _stamp_journal(db, "Invoice", inv.id, when)
                        db.execute(text("UPDATE customer_ledger_entries SET created_at=:at WHERE invoice_id=:id AND entry_type='RETURN_REFUND'"), {"at": when + timedelta(minutes=3), "id": inv.id})
                        stats["voids"] += 1
                        sp.commit()
                    except Exception as exc:
                        sp.rollback(); log.warning("void skipped: %s", exc)
                elif rnd.random() < 0.012:
                    sp = db.begin_nested()
                    try:
                        it = db.execute(select(InvoiceItem).where(InvoiceItem.invoice_id == inv.id)).scalars().first()
                        if it:
                            ret = pos_svc.process_return(db, invoice=inv, invoice_item=it, qty=D(1) if not it.qty < 1 else it.qty, user=user, reason="معیوب")
                            db.flush()
                            returned_at = when + timedelta(minutes=rnd.randint(10, 50))
                            db.execute(text("UPDATE returns SET created_at=:at, updated_at=:at WHERE id=:id"), {"at": returned_at, "id": ret.id})
                            db.execute(text("UPDATE stock_movements SET created_at=:at WHERE reference_type='Return' AND reference_id=:id"), {"at": returned_at, "id": it.id})
                            _stamp_journal(db, "Return", ret.id, returned_at)
                            stats["returns"] += 1
                        sp.commit()
                    except Exception as exc:
                        sp.rollback(); log.warning("return skipped: %s", exc)
            # credit settlements: customers pay their tab every ~2 weeks
            if day.day in (1, 15):
                from . import ledger as ledger_svc
                for cu in customers:
                    if not cu["credit"]:
                        continue
                    last = db.execute(select(CustomerLedgerEntry).where(CustomerLedgerEntry.customer_id == cu["c"].id).order_by(CustomerLedgerEntry.id.desc())).scalars().first()
                    if last and float(last.balance_after) > 0 and rnd.random() < 0.8:
                        amt = float(last.balance_after) * rnd.choice([1.0, 1.0, 0.6])
                        sp = db.begin_nested()
                        try:
                            e = _settle_demo_customer(db, customer=cu["c"], amount=D(str(round(amt))),
                                day=day, admin=admin, by_cheque=rnd.random() < 0.3,
                                due_date=day + timedelta(days=rnd.randint(10, 30)))
                            db.flush()
                            _fix_created(db, "customer_ledger_entries", [e.id], datetime.combine(day, datetime.min.time()) + timedelta(hours=10))
                            _stamp_journal(db, "CustomerLedgerEntry", e.id, datetime.combine(day, datetime.min.time()) + timedelta(hours=10))
                            sp.commit()
                        except Exception as exc:
                            sp.rollback(); log.warning("settlement skipped: %s", exc)
            # monthly expenses + cheques
            if day.day == 1:
                when = datetime.combine(day, datetime.min.time()) + timedelta(hours=9)
                monthly = [("اجاره", 45_000_000, "اجارهٔ ماهانه"),
                           ("آب", rnd.randint(500_000, 1_500_000), "قبض آب"),
                           ("برق", rnd.randint(3_000_000, 6_000_000), "قبض برق"),
                           ("گاز", rnd.randint(500_000, 2_000_000), "قبض گاز"),
                           ("حمل", rnd.randint(1_500_000, 3_500_000), "هزینهٔ حمل ماهانه"),
                           ("متفرقه", rnd.randint(800_000, 2_500_000), "هزینهٔ تعمیرات و مصرفی")]
                monthly.extend(("حقوق", 14_000_000 if idx == 0 else 12_000_000,
                                "حقوق ماهانهٔ " + employee.full_name) for idx, employee in enumerate(cashiers))
                for nm, amt, description in monthly:
                    sp = db.begin_nested()
                    try:
                        e = acc_svc.record_expense(db, category_id=exp_cats[nm].id, amount=D(amt), expense_date=day, paid_from="BANK" if nm in ("اجاره", "حقوق") else "CASH", description=description, user=admin)
                        db.flush(); _fix_created(db, "acc_expenses", [e.id], when); _stamp_journal(db, "Expense", e.id, when); sp.commit()
                    except Exception as exc:
                        sp.rollback(); log.warning("expense skipped: %s", exc)
                # issued cheques to suppliers (planted: next month has a cluster)
                n_ch = 2 if day.month != today.month else 4
                for j in range(n_ch):
                    s, _, _ = rnd.choice(sups)
                    due_d = day + timedelta(days=rnd.randint(25, 55)) if day.month != today.month else today + timedelta(days=rnd.randint(6, 26))
                    sp = db.begin_nested()
                    try:
                        ch = acc_svc.record_cheque(db, direction="ISSUED", number=str(rnd.randint(100000, 999999)), amount=D(rnd.randint(35, 120) * 1_000_000),
                                                   due_date=due_d, bank_name=rnd.choice(["ملت", "ملی", "صادرات", "پاسارگاد"]), party_type="SUPPLIER", party_id=s.id,
                                                   party_name=s.name, description="بابت خرید کالا", issue_date=day, user=admin)
                        db.flush(); _fix_created(db, "acc_cheques", [ch.id], when); _stamp_journal(db, "Cheque", ch.id, when); sp.commit()
                    except Exception as exc:
                        sp.rollback(); log.warning("cheque skipped: %s", exc)
            # v3.5.7 — settle the cheques that have come due. accounting.clear_cheque()
            # and bounce_cheque() both exist, but nothing ever called them, so every
            # cheque this generator wrote stayed PENDING and the cheques report had one
            # column with anything in it: no وصول شده, no برگشت خورده, no ageing.
            due = db.execute(select(Cheque).where(Cheque.status == "PENDING",
                                                  Cheque.due_date <= day)).scalars().all()
            for ch in due:
                if rnd.random() < 0.12:
                    continue                       # genuinely still outstanding
                sp = db.begin_nested()
                try:
                    if rnd.random() < 0.07:
                        acc_svc.bounce_cheque(db, cheque_id=ch.id, user=admin)
                        if ch.direction == "RECEIVED" and ch.party_type == "CUSTOMER":
                            from . import ledger as ledger_svc
                            restored = ledger_svc.post_entry(db, customer_id=ch.party_id,
                                entry_type="ADJUSTMENT_DEBIT", amount=ch.amount,
                                method="CHEQUE", note=f"برگشت چک {ch.number}", user_id=admin.id)
                            _fix_created(db, "customer_ledger_entries", [restored.id],
                                         datetime.combine(day, datetime.min.time()) + timedelta(hours=9))
                    else:
                        acc_svc.clear_cheque(db, cheque_id=ch.id, user=admin)
                    cleared_at = datetime.combine(day, datetime.min.time()) + timedelta(hours=9)
                    _stamp_journal(db, "ChequeClear" if ch.status == "CLEARED" else "ChequeBounce", ch.id, cleared_at)
                    sp.commit()
                    # the service stamps updated_at with the wall clock; pull it back onto
                    # the simulated calendar. created_at is deliberately left alone — that
                    # is the issue date and _fix_created() would overwrite it.
                    db.execute(text("UPDATE acc_cheques SET updated_at=:at WHERE id=:id"),
                               {"at": datetime.combine(day, datetime.min.time()) + timedelta(hours=9),
                                "id": ch.id})
                except Exception as exc:
                    sp.rollback(); log.warning("cheque settle skipped: %s", exc)
            db.commit()  # bounded daily transactions; avoid month-sized WAL growth
            day += timedelta(days=1)

            if resumable:
                checkpoint.save(db, config, checkpoint_state())
        if event_callback:
            event_callback({"phase": "days", "done": (day - start).days,
                            "total": (today - start).days + 1, "invoices": stats["invoices"]})
        completed_here += 1
        if pause_after_days is not None and completed_here >= pause_after_days and day <= today:
            raise checkpoint.SimulationPaused(f"PAUSED: completed through {day - timedelta(days=1)}; next day {day}")

    with db.atomic_day() if resumable else nullcontext():
        def stamp_expiries():
            # historical expiry dates; whatever is still on the shelf and past its date becomes EXPIRED (the waste the engine will talk about)
            for bid, exp in pending_expiry:
                db.execute(text("UPDATE product_batches SET expiry_date=:e WHERE id=:id"), {"e": exp, "id": bid})
            pending_expiry.clear()
            db.execute(text("UPDATE product_batches SET status='EXPIRED' WHERE expiry_date IS NOT NULL AND expiry_date < :t AND current_qty > 0 AND status='ACTIVE'"), {"t": today})
            db.flush()

        stamp_expiries()

        if not full_catalog:
            # ---- planted end-state situations
            now = datetime.utcnow()
            # 1) perishable over-receipt → EXPIRY_LADDER
            yog = by_name["ماست ۹۰۰ گرمی"]
            receive(yog, now - timedelta(days=2), 140, shelf_override=9)
            # 2) fast mover nearly out → VELOCITY
            water = by_name["آب معدنی ۱.۵ لیتری"]
            db.execute(update(ProductBatch).where(ProductBatch.product_id == water["p"].id, ProductBatch.status == "ACTIVE").values(current_qty=D(0)))
            receive(water, now - timedelta(hours=5), 14)
            # 3) priced under cost → PRICE_GAP
            tuna = by_name["تن ماهی ۱۸۰ گرمی"]
            db.execute(update(ProductBatch).where(ProductBatch.product_id == tuna["p"].id, ProductBatch.status == "ACTIVE").values(sell_price=D(69000)))
            # 4) consumer-price violation
            tea = by_name["چای کیسه‌ای ۱۰۰ عددی"]
            db.execute(update(ProductBatch).where(ProductBatch.product_id == tea["p"].id, ProductBatch.status == "ACTIVE").values(sell_price=D(124000)))
            stamp_expiries()
            db.commit()

        # ---- v3.5.9: run the model on the FINAL data and actually act on it -----------------
        # A stress file that only *contains* sales proves nothing about the intelligence engine.
        # So: run every generator over the finished year, accept the strongest suggestions through
        # the real accept() path (baseline frozen, actions executed), then measure them — exactly
        # what a manager clicking «اجرا و سنجش اثر» would do.
        ins: dict = {}
        try:
            from ..models import Insight
            from . import insights as ins_svc
            if progress:
                progress(0.93)
            run_res = ins_svc.run(db, days=180)
            db.commit()
            if progress:
                progress(0.96)
            accepted = 0
            for r in db.execute(select(Insight).where(Insight.status == "NEW")
                                .order_by(Insight.priority.asc(), Insight.expected_gain.desc()).limit(0 if full_catalog else 14)).scalars().all():
                try:
                    ins_svc.accept(db, r, user=admin)
                    accepted += 1
                except Exception as exc:
                    db.rollback()
                    log.warning("demo: accept skipped for insight %s: %s", r.id, exc)
            db.commit()
            if progress:
                progress(0.98)
            ins = {"errors": run_res.get("errors", []), "generated": int(run_res.get("created", 0)) + int(run_res.get("refreshed", 0)),
                   "accepted": accepted, "measured": ins_svc.measure_all(db),
                   "open": len(db.execute(select(Insight.id).where(Insight.status == "NEW")).scalars().all())}
            db.commit()
        except Exception:
            db.rollback()
            ins["errors"] = ["FINAL_INSIGHT_PASS_FAILED"]
            log.exception("demo: final insight pass failed (the store is still valid without it)")
        if progress:
            progress(1.0)

        try:
            write_audit(db, action="DEMO_STORE_GENERATED", entity_type="System", entity_id=None, after={"days": days, **{k: (round(v) if isinstance(v, float) else v) for k, v in stats.items()}})
            db.commit()
        except Exception:
            db.rollback()
        summary = {"days": days, "start_date": str(start), "end_date": str(today), "products": len(products), "long_tail_products": len(long_tail),
                "suppliers": len(sups), "customers": len(customers), "insights": ins,
                **{k: (round(v) if isinstance(v, float) else v) for k, v in stats.items()}}

        if resumable:
            checkpoint.save(db, config, {"phase": "complete", "summary": summary})
        return summary


def _manager_reviews(db: Session, day: date, admin, products, customers, fx: dict, stats: dict, by_name: dict) -> None:
    """Replay what a real manager did on `day`: run the engine with the clock set to that day,
    accept the sensible suggestions through the real accept() (baseline frozen, actions executed),
    and register the behavioural consequences the rest of the simulation must honour."""
    from . import insights as ins
    from ..models import Insight
    clock = datetime.combine(day, datetime.min.time()) + timedelta(hours=6, minutes=30)   # 10:00 Tehran
    ins.set_clock(clock)
    try:
        ins.run(db)
        db.commit()
        rows = db.execute(select(Insight).where(Insight.status == "NEW")).scalars().all()
        accepted = 0
        for r in rows:
            ev = json.loads(r.evidence or "{}")
            take, only = False, None
            if r.kind == "CROSS_SELL" and accepted < 12:
                take = True
                prods = ev.get("products") or []
                a, b = (prods[0]["id"], prods[1]["id"]) if len(prods) == 2 else (None, None)
                if a and b:
                    fx["pair_boost"][(a, b)] = 0.22
                    fx["pair_boost"][(b, a)] = 0.12
            elif r.kind == "BASKET_NUDGE":
                take = True
                for rule in ev.get("rules", [])[:12]:
                    fx["pair_boost"][(rule["if"], rule["then"])] = max(fx["pair_boost"].get((rule["if"], rule["then"]), 0), 0.10)
            elif r.kind == "VIP":
                take = True
                fx["vip_ids"] |= {x["customer_id"] for x in ev.get("rows", [])}
            elif r.kind == "CHURN":
                take = True
                ids = {x["customer_id"] for x in ev.get("rows", [])}
                fx["winback_ids"] |= ids
                for c in customers:
                    if c["c"].id in ids:
                        c["churn"] = None
                        c["next"] = day + timedelta(days=random.Random(c["c"].id).randint(2, 9))
                        c["gap"] *= 1.3   # they come back, a bit less often than before
            elif r.kind == "PRICE_GAP" and ev.get("margin") is not None:
                take = True   # under-cost tuna → priced properly; unit demand dips slightly
                fx["boosted_products"][ev["product_id"]] = 0.0
                d = next((x for x in products if x["p"].id == ev["product_id"]), None)
                if d:
                    d["demand"] *= 0.93
            elif r.kind == "DEAD_STOCK":
                take = True   # bundle + shelf move: the dead stock starts to move slowly
                fx["boosted_products"][ev["product_id"]] = 0.035
            elif r.kind == "VELOCITY" and accepted < 20:
                take, only = True, ["set_min_stock"]
            elif r.kind == "VISIT_PATTERN":
                take = True   # personal «your usual item is in» SMS: the due customers come on time and add a line
                for x in ev.get("rows", []):
                    fx["visit_ids"].add(x["customer_id"])
                for c in customers:
                    if c["c"].id in fx["visit_ids"]:
                        c["next"] = min(c["next"], day + timedelta(days=1))
                        c["nudged_until"] = day + timedelta(days=14)
            if take:
                try:
                    ins.accept(db, r, user=admin, action_types=only)
                    accepted += 1
                except Exception as exc:
                    db.rollback()
                    log.warning("demo accept skipped %s: %s", r.kind, exc)
        # demo-store prices after PRICE_GAP acceptance are already changed by the real action.
        db.execute(text("UPDATE ai_insights SET created_at=:t, updated_at=:t, last_seen_at=:t WHERE created_at > :t"), {"t": clock})
        db.execute(text("UPDATE campaigns SET created_at=:t WHERE created_at > :t"), {"t": clock})
        db.execute(text("UPDATE coupons SET created_at=:t WHERE created_at > :t"), {"t": clock})
        db.execute(text("UPDATE notifications SET created_at=:t WHERE created_at > :t"), {"t": clock})
        db.execute(text("UPDATE audit_logs SET created_at=:t WHERE created_at > :t"), {"t": clock})
        db.commit()
        stats["accepted_insights"] += accepted
        log.warning("demo manager review on %s: %d suggestions accepted", day, accepted)
    finally:
        ins.set_clock(None)


def is_demo(db: Session) -> bool:
    from ..models import AuditLog
    return db.execute(select(AuditLog.id).where(AuditLog.action == "DEMO_STORE_GENERATED").limit(1)).first() is not None


#: what POST /api/system/restore refuses to accept — kept in step with
#: ``_REQUIRED_TABLES`` in routers/system.py so a generated file is validated
#: here rather than discovered to be broken at restore time.
_REQUIRED_TABLES = {"users", "products", "product_batches", "invoices", "audit_logs"}

#: runs in the child process, with DATABASE_URL already pointed at the new file
_CHILD = """
import json, sys
from app.database import init_db, SessionLocal, engine
from app.services import demo_store
from app.services.simulation_checkpoint import ReplaySession, SimulationPaused, file_lock
from contextlib import nullcontext

_cfg = json.loads(sys.argv[1])


def _event(event):
    print("__EVENT__" + json.dumps(event), flush=True)


def _p(frac):
    # Streamed so the parent can draw a live progress bar; flush matters more than format.
    sys.stdout.write("__PROG__%.6f\\n" % max(0.0, min(1.0, float(frac))))
    sys.stdout.flush()


with file_lock(_cfg["worker_lock"]) if _cfg.get("worker_lock") else nullcontext():
    init_db()
    session = ReplaySession(bind=engine, expire_on_commit=False) if _cfg.get("resumable") else SessionLocal()
    try:
        with session as db:
            s = demo_store.generate(db, days=_cfg["days"], seed=_cfg["seed"],
                invoices_per_day=_cfg["invoices_per_day"], full_catalog=_cfg["full_catalog"],
                progress=_p, event_callback=_event, resumable=_cfg.get("resumable", False), pause_after_days=_cfg.get("pause_after_days"))
    except SimulationPaused as exc:
        print(str(exc), flush=True)
        sys.exit(75)
print("__DEMO__" + json.dumps(s))
"""


def generate_backup_file(path, *, days: int = 365, seed: int = 1404,
                         invoices_per_day: float = 95.0, compress: bool = True,
                         full_catalog: bool = False, progress=None, work_dir=None, resume: bool = False,
                         pause_after_days: int | None = None, event_callback=None) -> dict:
    """v3.5.6 — build the standalone one-year demo store.

    This module's docstring has promised ``generate_backup_file(path)`` since v3.0,
    but the function was never written: nothing could produce ``demo_store.db.gz``,
    so ``GET /api/system/demo`` always reported ``available: false`` and the
    "restore the bundled demo store" path had nothing to restore.

    It builds in a throwaway directory through a SUBPROCESS whose DATABASE_URL
    points at the new file, so the real ``init_db()`` runs unmodified — same
    ``create_all``, same alembic stamp, same ``_reconcile_schema``, same indexes,
    same ``bootstrap``. Building it any other way would drift from what an
    installed app produces, and the whole point is that restore accepts the file
    unchanged.

    The result is validated with exactly the checks ``restore`` applies
    (``PRAGMA integrity_check`` plus the required tables) before it is written
    out, so a broken file fails here instead of at the shop's counter.
    """
    import gzip
    import os
    import shutil
    import sqlite3
    import subprocess
    import sys
    import tempfile
    from pathlib import Path

    dest = Path(path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    backend_dir = Path(__file__).resolve().parents[2]

    from . import simulation_checkpoint as checkpoint
    if (resume or pause_after_days is not None) and work_dir is None:
        raise ValueError("RESUME_REQUIRES_WORK_DIRECTORY")
    if work_dir and dest.resolve().is_relative_to(Path(work_dir).resolve()):
        raise ValueError("OUTPUT_MUST_BE_OUTSIDE_WORK_DIRECTORY")
    manager = checkpoint.workspace(work_dir, resume) if work_dir else tempfile.TemporaryDirectory(prefix="demostore_")
    with manager as td:
        raw = Path(td) / "demo.db"
        env = dict(os.environ)
        env["DATABASE_URL"] = f"sqlite+pysqlite:///{raw}"
        env["SUPERMARKET_LICENSE_GATE"] = "0"
        env["ADMIN_USERNAME"] = "admin"
        env["ADMIN_PASSWORD"] = "admin123"
        env["PYTHONPATH"] = os.pathsep.join([str(backend_dir), env.get("PYTHONPATH", "")])

        # v3.5.9 — streamed, not capture_output: the build can run for an hour on a big store
        # and the caller owes the user a progress bar. stderr is merged into stdout so the
        # child can never deadlock on a full pipe. Parameters travel as JSON in argv rather
        # than by %-formatting the template — a stray % in the child used to break the build.
        cfg = json.dumps({"days": int(days), "seed": int(seed),
                          "invoices_per_day": float(invoices_per_day),
                          "full_catalog": bool(full_catalog), "resumable": work_dir is not None,
                          "pause_after_days": pause_after_days,
                          "worker_lock": str(Path(td) / "worker.lock") if work_dir else None})
        proc = subprocess.Popen([sys.executable, "-u", "-c", _CHILD, cfg],
                                cwd=str(backend_dir), env=env, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True, bufsize=1)
        from collections import deque
        summary, tail_lines = None, deque(maxlen=100)
        try:
            for line in proc.stdout or []:
                line = line.rstrip("\n")
                if line.startswith("__PROG__"):
                    if progress:
                        try:
                            progress(float(line[len("__PROG__"):]))
                        except Exception:   # a broken progress callback must not kill the build
                            log.debug("progress callback failed", exc_info=True)
                elif line.startswith("__EVENT__"):
                    if event_callback:
                        event_callback(json.loads(line[len("__EVENT__"):]))
                elif line.startswith("__DEMO__"):
                    summary = json.loads(line[len("__DEMO__"):])
                else:
                    tail_lines.append(line)
            rc = proc.wait()
        except BaseException:
            proc.terminate()
            try:
                proc.wait(timeout=30)
            except subprocess.TimeoutExpired:
                proc.kill(); proc.wait()
            raise
        if rc == 75:
            raise checkpoint.SimulationPaused("\n".join(tail_lines))
        if rc != 0 or summary is None:
            raise RuntimeError("DEMO_BUILD_FAILED rc=%s\n%s" % (rc, "\n".join(list(tail_lines)[-25:])))

        snapshot = Path(td) / "export.db"
        if snapshot.exists():
            snapshot.unlink()
        source, target = sqlite3.connect(str(raw)), sqlite3.connect(str(snapshot))
        try:
            source.backup(target, pages=256, progress=(
                lambda status, remaining, total: event_callback({"phase": "snapshot", "done": total - remaining, "total": total})
                if event_callback else None))
            target.execute("DROP TABLE IF EXISTS _simulation_checkpoint")
            target.commit()
            # sqlite's connection context manager commits but does NOT close.
            # Flush any inherited WAL before copying/compressing the main file.
            target.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            target.execute("PRAGMA journal_mode=DELETE")
        finally:
            target.close()
            source.close()
        raw = snapshot
        # --- validate exactly what restore will check -----------------------
        con = sqlite3.connect(str(raw))
        try:
            integrity = con.execute("PRAGMA integrity_check").fetchone()[0]
            tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        finally:
            con.close()
        if integrity != "ok":
            raise RuntimeError(f"DEMO_INTEGRITY_FAILED: {integrity}")
        missing = _REQUIRED_TABLES - tables
        if missing:
            raise RuntimeError(f"DEMO_MISSING_TABLES: {sorted(missing)}")

        if compress:
            tmp = dest.with_suffix(dest.suffix + ".tmp")
            with open(raw, "rb") as src, gzip.open(tmp, "wb", compresslevel=6) as out:
                processed, total = 0, raw.stat().st_size
                while chunk := src.read(1 << 20):
                    out.write(chunk)
                    processed += len(chunk)
                    if event_callback:
                        event_callback({"phase": "compress", "done": processed, "total": total})
            tmp.replace(dest)
        else:
            tmp = dest.with_suffix(dest.suffix + ".tmp")
            shutil.copyfile(raw, tmp)
            tmp.replace(dest)

    summary = dict(summary or {})
    summary.update({"path": str(dest), "bytes": dest.stat().st_size,
                    "compressed": bool(compress), "tables": len(tables)})
    return summary
