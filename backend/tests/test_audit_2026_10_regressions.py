# -*- coding: utf-8 -*-
"""رگرسیون ممیزی ۲۰۲۶-۱۰ (نسخهٔ ۱٫۰٫۵۲۶) — یک آزمون برای هر باگ اصلاح‌شده.

هر آزمون دقیقاً همان شکستی را بازتولید می‌کند که در ممیزی دیده شد، پس اگر کسی
اصلاح را برگرداند، همین‌جا قرمز می‌شود. نام‌گذاری: BUG-A … BUG-E مطابق گزارش.

BUG-A  اعتبارسنجی ۴۲۲ با ctx از نوع Decimal خودِ هندلر را می‌شکست → ۵۰۰
BUG-B  دروازهٔ I-18 فقط *وجود* هدر Bearer را می‌دید → نقشهٔ کامل API لو می‌رفت
BUG-C  محدودکنندهٔ نرخ، ورودهای *موفق* را هم می‌شمرد → قفل‌شدن کارکنان واقعی
BUG-D  سود روزانهٔ پیش‌بینی، تخفیف فاکتور را کم نمی‌کرد، فاکتور مرجوعی‌شده را
       کامل حذف می‌کرد و ردیف‌های آینده را وارد گذشته می‌کرد
BUG-E  مرجوعیِ بدون مبلغ، قیمت قفسه (ناخالص) را پس می‌داد → بیشتر از پولِ گرفته‌شده
"""
from __future__ import annotations

import tempfile
from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


# ---------------------------------------------------------------- BUG-A
def test_bug_a_decimal_validation_error_returns_422_with_details(client, auth_headers, milk):
    """تعداد صفر باید ۴۲۲ با پیام میدانی بدهد، نه ۵۰۰ «خطای داخلی»."""
    r = client.post("/api/pos/checkout", headers=auth_headers,
                    json={"items": [{"product_id": milk["id"], "quantity": 0}], "payments": []})
    assert r.status_code == 422, f"expected 422, got {r.status_code}: {r.text[:200]}"
    detail = r.json()["detail"]
    assert isinstance(detail, list) and detail, detail
    first = detail[0]
    assert first["loc"][-1] == "quantity"
    assert "ctx" in first and isinstance(first["ctx"].get("gt"), str), first


def test_bug_a_discount_and_decimal_parsing_are_also_json_safe(client, auth_headers, milk):
    for body, field in (
        ({"items": [{"product_id": milk["id"], "quantity": -2}], "payments": []}, "quantity"),
        ({"items": [{"product_id": milk["id"], "quantity": "abc"}], "payments": []}, "quantity"),
        ({"items": [{"product_id": milk["id"], "quantity": 1, "discount": -5}], "payments": []}, "discount"),
    ):
        r = client.post("/api/pos/checkout", headers=auth_headers, json=body)
        assert r.status_code == 422, (field, r.status_code, r.text[:160])
        assert r.json()["detail"][0]["loc"][-1] == field


# ---------------------------------------------------------------- BUG-B
def test_bug_b_schema_endpoint_needs_a_real_token(client, auth_headers):
    """یک رشتهٔ جعلی بعد از «Bearer» نباید نقشهٔ API را باز کند."""
    assert client.get("/openapi.json").status_code == 404
    assert client.get("/openapi.json", headers={"Authorization": "Bearer x"}).status_code == 404
    assert client.get(
        "/openapi.json", headers={"Authorization": "Bearer not.a.jwt"}).status_code == 404
    # an authenticated developer still gets the schema
    ok = client.get("/openapi.json", headers=auth_headers)
    assert ok.status_code == 200 and ok.json()["info"]["version"]


def test_bug_b_a_cashier_cannot_read_the_schema(client, auth_headers):
    uname = "audit_cashier_schema"
    client.post("/api/users", headers=auth_headers, json={
        "username": uname, "password": "pass1234", "roles": ["Cashier"]})
    tok = client.post("/api/auth/login", data={"username": uname, "password": "pass1234"})
    if tok.status_code != 200:      # user may already exist from another run
        client.post("/api/users", headers=auth_headers, json={
            "username": uname + "2", "password": "pass1234", "roles": ["Cashier"]})
        tok = client.post("/api/auth/login", data={"username": uname + "2", "password": "pass1234"})
    H = {"Authorization": f"Bearer {tok.json()['access_token']}"}
    assert client.get("/openapi.json", headers=H).status_code == 404, \
        "یک صندوق‌دار نباید نقشهٔ کامل API را ببیند"


# ---------------------------------------------------------------- BUG-C
def test_bug_c_successful_logins_are_never_rate_limited(client):
    """۳۰ ورودِ *درست* در یک دقیقه طبیعی است؛ حملۀ واقعی ۳۰ رمزِ غلط است."""
    from app import main as app_main

    app_main.reset_rate_limits()
    limit, _window = app_main._RATE_LIMITS["/api/auth/login"]
    for i in range(limit + 10):
        r = client.post("/api/auth/login", data={"username": "admin", "password": "admin123"})
        assert r.status_code == 200, f"login #{i + 1} blocked: {r.status_code}"


def test_bug_c_failed_logins_still_trip_the_limiter(client):
    from app import main as app_main

    app_main.reset_rate_limits()
    limit, _window = app_main._RATE_LIMITS["/api/auth/login"]
    codes = [client.post("/api/auth/login",
                         data={"username": "nobody", "password": "wrong"}).status_code
             for _ in range(limit + 2)]
    assert 429 in codes, f"brute force was not stopped: {set(codes)}"
    app_main.reset_rate_limits()


# ---------------------------------------------------------------- BUG-D
@pytest.fixture()
def isolated_db():
    """یک پایگاه‌دادهٔ مستقل تا محاسبات مالی به دادهٔ سایر آزمون‌ها وابسته نباشد."""
    from app.database import Base
    import app.models  # noqa: F401 — register every table

    d = tempfile.mkdtemp(prefix="audit_fin_")
    eng = create_engine(f"sqlite:///{d}/fin.db")
    Base.metadata.create_all(eng)
    Session = sessionmaker(bind=eng)
    db = Session()
    try:
        yield db
    finally:
        db.close()
        eng.dispose()


def _mk_invoice(db, *, created_at: datetime, status: str, line_profit, line_disc,
                invoice_disc, refund=None, qty=1, buy=300):
    """Sell one unit of a product; ``refund`` adds a full return of that unit."""
    from app.models import Invoice, InvoiceItem, Product, ProductBatch, Return

    p = db.query(Product).filter_by(barcode="F1").one_or_none()
    if p is None:
        p = Product(barcode="F1", name="کالای مالی")
        db.add(p)
        db.flush()
        db.add(ProductBatch(product_id=p.id, batch_number="B1", quantity_received=1000,
                            current_qty=1000, buy_price=buy, sell_price=2000,
                            received_at=datetime.utcnow(), status="ACTIVE"))
        db.flush()
    batch = db.query(ProductBatch).filter_by(product_id=p.id).first()
    inv = Invoice(invoice_number=f"INV-{created_at.timestamp()}-{status}-{invoice_disc}",
                  subtotal=Decimal("0"), discount=Decimal(str(invoice_disc)),
                  invoice_discount=Decimal(str(invoice_disc)), tax=Decimal("0"),
                  total_amount=Decimal("0"), status=status, payment_status="PAID",
                  created_at=created_at)
    db.add(inv)
    db.flush()
    item = InvoiceItem(invoice_id=inv.id, product_id=p.id, batch_id=batch.id,
                       qty=Decimal(str(qty)), unit_buy_price=Decimal(str(buy)),
                       unit_sell_price=Decimal("2000"), discount=Decimal(str(line_disc)),
                       subtotal=Decimal("2000") - Decimal(str(line_disc)),
                       profit=Decimal(str(line_profit)), created_at=created_at)
    db.add(item)
    db.flush()
    if refund is not None:
        db.add(Return(invoice_id=inv.id, invoice_item_id=item.id, batch_id=batch.id,
                      qty=Decimal("1"), refund_amount=Decimal(str(refund)),
                      status="COMPLETED", created_at=created_at))
    db.commit()
    return inv, item


def test_bug_d_daily_profit_is_net_of_invoice_discount_and_returns(isolated_db):
    from app.services import forecast

    db = isolated_db
    now = datetime.utcnow() - timedelta(minutes=5)
    # A: line profit 2000, invoice-level discount 500 → net 1500
    _mk_invoice(db, created_at=now, status="PAID", line_profit=2000,
                line_disc=0, invoice_disc=500)
    # B: line profit 1000, line discount 200 (already inside profit), invoice.discount=200
    #    → no extra invoice-level discount; a return of that unit refunds 500 and
    #    recovers 300 of cost → return profit 200 → net 800
    _mk_invoice(db, created_at=now, status="PARTIALLY_REFUNDED", line_profit=1000,
                line_disc=200, invoice_disc=200, refund=500)

    series = forecast._daily_profit(db, 3)
    today_value = series[-1][1]
    assert today_value == pytest.approx(1500 + 800, abs=0.01), series


def test_bug_d_fully_refunded_invoice_collapses_to_zero(isolated_db):
    """نگهبان: فاکتور کاملاً مرجوع‌شده سود صفر می‌دهد (قبل و بعد از اصلاح)."""
    from app.services import forecast

    db = isolated_db
    now = datetime.utcnow() - timedelta(minutes=5)
    # sell at 2000 with cost 300 → profit 1700; full refund 2000 → return profit 1700
    _mk_invoice(db, created_at=now, status="REFUNDED", line_profit=1700,
                line_disc=0, invoice_disc=0, refund=2000)
    series = forecast._daily_profit(db, 3)
    assert series[-1][1] == pytest.approx(0.0, abs=0.01), series


def test_bug_d_future_rows_never_leak_into_the_past_trend(isolated_db):
    """نگهبان: ردیفِ آینده نباید در روند گذشته بیاید.

    این مورد در کد قبلی هم عملاً بی‌اثر بود (سری فقط تا امروز ساخته می‌شود)؛
    کرانِ بالای بازه به‌عنوان سخت‌گیریِ تدافعی اضافه شد، نه به‌خاطر یک خطای
    مشاهده‌شده. آزمون می‌ماند تا اگر روزی کسی پنجره را به آینده扩展 داد، قرمز شود.
    """
    from app.services import forecast

    db = isolated_db
    now = datetime.utcnow() - timedelta(minutes=5)
    _mk_invoice(db, created_at=now, status="PAID", line_profit=1000,
                line_disc=0, invoice_disc=0)
    _mk_invoice(db, created_at=now + timedelta(days=2), status="PAID",
                line_profit=99999, line_disc=0, invoice_disc=0)
    series = forecast._daily_profit(db, 3)
    assert series[-1][1] == pytest.approx(1000.0, abs=0.01), series


# ---------------------------------------------------------------- BUG-E
def test_bug_e_return_default_refund_never_exceeds_what_was_paid(client, auth_headers, milk, two_batches):
    """مرجوعیِ خطِ تخفیف‌دار نباید قیمت قفسه را پس بدهد."""
    batch_a = two_batches["a"]["id"]
    r = client.post("/api/pos/checkout", headers=auth_headers, json={
        "items": [{"product_id": milk["id"], "quantity": 2, "batch_id": batch_a,
                   "discount": 20000}],
        "payments": [{"method": "CASH", "amount": 100000}]})
    assert r.status_code == 201, r.text
    inv = r.json()
    assert inv["total_amount"] == 100000.0, inv["total_amount"]

    item_id = client.get(f"/api/invoices/{inv['invoice_id']}", headers=auth_headers).json()["items"][0]["id"]
    rr = client.post("/api/returns", headers=auth_headers, json={
        "invoice_id": inv["invoice_id"], "invoice_item_id": item_id, "qty": 1})
    assert rr.status_code == 201, rr.text
    # paid 50,000 per unit — a default refund must be exactly that, not 60,000
    assert rr.json()["refund_amount"] == 50000.0, rr.json()


def test_bug_e_explicit_refund_amount_is_still_honoured(client, auth_headers, milk, two_batches):
    """مبلغ صریح (مثلاً مرجوعیِ حسن‌نیت) باید دست‌نخورده بماند."""
    batch_b = two_batches["b"]["id"]
    r = client.post("/api/pos/checkout", headers=auth_headers, json={
        "items": [{"product_id": milk["id"], "quantity": 2, "batch_id": batch_b}],
        "payments": [{"method": "CASH", "amount": 130000}]})
    assert r.status_code == 201, r.text
    inv = r.json()
    item_id = client.get(f"/api/invoices/{inv['invoice_id']}", headers=auth_headers).json()["items"][0]["id"]
    rr = client.post("/api/returns", headers=auth_headers, json={
        "invoice_id": inv["invoice_id"], "invoice_item_id": item_id,
        "qty": 1, "refund_amount": 70000})
    assert rr.status_code == 201, rr.text
    assert rr.json()["refund_amount"] == 70000.0, rr.json()
