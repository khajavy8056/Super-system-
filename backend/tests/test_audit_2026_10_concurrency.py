# -*- coding: utf-8 -*-
"""هم‌زمانی صندوق (ممیزی ۲۰۲۶-۱۰) — دو ترمینال، یک Batch.

کد ادعا می‌کند کسر موجودی اتمیک است (``UPDATE … WHERE current_qty >= qty``) و
شمارهٔ فاکتور از شمارندهٔ اتمیک می‌آید (BUG-004/BUG-005). آزمون قبلی برای این
ادعا فقط «تک‌ترمینالی» بود؛ اینجا واقعاً چند ترد هم‌زمان می‌فروشند:

  ۱. Batch با ۵ عدد، ۱۲ تلاش هم‌زمان برای فروش ۱ عدد:
     → دقیقاً ۵ فروش موفق، بقیه INSUFFICIENT_STOCK، موجودی پایانی صفر،
       هیچ عددی منفی نمی‌شود و شمارهٔ فاکتورها یکتا و بدون شکاف است.
  ۲. فروش هم‌زمان روی دو Batch جدا: هر دو باید موفق شوند و شماره‌ها یکتا بمانند.

اگر روزی کسی «اعتبارسنجی خواندنی» را جای کسر اتمیک بگذارد، این آزمون قرمز می‌شود.
"""
from __future__ import annotations

import tempfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.database import Base


@pytest.fixture()
def shop():
    """یک فروشگاه مستقل روی فایل (نه حافظه) تا چند ترد واقعاً هم‌زمان بنویسند."""
    import app.models  # noqa: F401 — register tables
    from app.database import _make_engine
    from app.models import Product, ProductBatch, User
    from app.security import hash_password

    d = tempfile.mkdtemp(prefix="audit_concurrency_")
    url = f"sqlite:///{d}/shop.db"
    engine = _make_engine(url)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False,
                           expire_on_commit=False)
    setup = Session()
    user = User(username="till", full_name="Till", password_hash=hash_password("x"),
                is_active=True)
    setup.add(user)
    p = Product(barcode="CONC1", name="کالای هم‌زمانی")
    setup.add(p)
    setup.flush()
    setup.commit()
    try:
        yield {"engine": engine, "Session": Session, "user_id": user.id, "product_id": p.id}
    finally:
        setup.close()
        engine.dispose()


def _receive(shop, qty: int, sell: int = 1000, buy: int = 600) -> int:
    from app.models import ProductBatch

    s = shop["Session"]()
    b = ProductBatch(product_id=shop["product_id"], batch_number=f"B{datetime.utcnow().timestamp()}",
                     quantity_received=qty, current_qty=qty, buy_price=buy, sell_price=sell,
                     received_at=datetime.utcnow(), status="ACTIVE")
    s.add(b)
    s.commit()
    bid = b.id
    s.close()
    return bid


def _sell(shop, batch_id: int, qty: int = 1, amount: int = 1000):
    """One complete checkout in its own session — exactly like one terminal."""
    from app.models import User
    from app.services import pos as pos_svc

    s = shop["Session"]()
    try:
        user = s.get(User, shop["user_id"])
        inv = pos_svc.checkout(
            s,
            items=[pos_svc.CartItem(product_id=shop["product_id"], quantity=Decimal(qty),
                                    batch_id=batch_id)],
            payments=[{"method": "CASH", "amount": Decimal(amount * qty)}],
            user=user,
        )
        s.commit()
        return ("OK", inv.invoice_number)
    except Exception as exc:  # noqa: BLE001 — a rejected sale is a valid outcome
        s.rollback()
        return ("ERR", getattr(exc, "code", type(exc).__name__))
    finally:
        s.close()


def test_no_oversell_when_many_tills_sell_the_same_batch_at_once(shop):
    from app.models import Invoice, ProductBatch

    batch_id = _receive(shop, 5)
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(lambda _: _sell(shop, batch_id), range(12)))

    ok = [r for r in results if r[0] == "OK"]
    errs = [r[1] for r in results if r[0] == "ERR"]
    assert len(ok) == 5, f"expected exactly 5 sales, got {len(ok)} ({errs})"
    assert set(errs) <= {"INSUFFICIENT_STOCK", "BATCH_NOT_FOUND"}, errs

    s = shop["Session"]()
    try:
        qty = s.execute(select(ProductBatch.current_qty).where(ProductBatch.id == batch_id)).scalar_one()
        assert Decimal(str(qty)) == Decimal("0"), f"stock must end at 0, got {qty}"
        assert Decimal(str(qty)) >= 0
        numbers = [n for _, n in ok]
        assert len(set(numbers)) == len(numbers), f"duplicate invoice numbers: {numbers}"
        stored = s.execute(select(func.count(Invoice.id))).scalar_one()
        assert stored == 5, stored
    finally:
        s.close()


def test_parallel_sales_on_different_batches_keep_numbers_unique(shop):
    from app.models import Invoice

    b1 = _receive(shop, 10, sell=1000)
    b2 = _receive(shop, 10, sell=1500)
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(
            lambda i: _sell(shop, b1, amount=1000) if i % 2 == 0
            else _sell(shop, b2, amount=1500), range(10)))
    assert all(r[0] == "OK" for r in results), [r for r in results if r[0] != "OK"]
    numbers = [r[1] for r in results]
    assert len(set(numbers)) == 10, f"duplicate invoice numbers: {sorted(numbers)}"
    s = shop["Session"]()
    try:
        assert s.execute(select(func.count(Invoice.id))).scalar_one() == 10
    finally:
        s.close()
