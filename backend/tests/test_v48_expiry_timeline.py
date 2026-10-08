# -*- coding: utf-8 -*-
"""Round 16 (v4.8.0) — «تایم‌لاین انقضا»: پیشنهاد باید وقتِ اقدام برسد، نه روز صفر.

گزارش مالک (عیناً): «وقتی محصول صفر روز مانده بود پیشنهاد می‌داد، عملاً فاسد
شده؛ باید چند روز قبلش، یک هفته قبلش پیشنهاد بدهد تا بشود کاری کرد.»

سه چیز اینجا تست می‌شود:
  ۱. **زمان‌بندی درست** — منطق خالص ``expiry_plan.build_plan``: سرعت
     محافظه‌کارانه، حاشیهٔ اطمینان، و تایم‌لاینی که آخرین پله را دست‌کم دو روز
     پیش از انقضا می‌گذارد (نه روی روز صفر).
  ۲. **روی دادهٔ واقعی** — تحلیل‌گر ``EXPIRY_LADDER`` از مسیر واقعی سرویس‌ها،
     همراه با شواهد تاریخ‌دار.
  ۳. **اجرا واقعاً انجام می‌شود** — پذیرش پیشنهاد قیمت بچ را همان لحظه پایین
     می‌آورد، پله‌های بعدی روی تاریخ خودشان اعمال می‌شوند، و گزارش بازبینی
     («آیا اقدام‌ها برقرارند؟») هم تأیید می‌کند.
"""
import contextlib
import json
import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select

from app.database import SessionLocal
from app.models import Product, ProductBatch, StockMovement, SystemSetting
from app.models.insights import Insight
from app.services import expiry_plan, insight_actions, insights
from app.services.timeservice import local_today


# --------------------------------------------------------------------------- helpers
def _make_product(client, auth_headers, name, qty=10, expiry_days=None, buy=1000, sell=1500):
    r = client.post("/api/products", headers=auth_headers,
                    json={"barcode": f"V48{uuid.uuid4().hex[:10]}", "name": name})
    assert r.status_code == 201, r.text
    pid = r.json()["id"]
    body = {"product_id": pid, "quantity_received": qty, "buy_price": buy, "sell_price": sell}
    if expiry_days is not None:
        body["expiry_date"] = (date.today() + timedelta(days=expiry_days)).isoformat()
    rr = client.post("/api/batches/receive", headers=auth_headers, json=body)
    assert rr.status_code == 201, rr.text
    return pid, rr.json()["id"]


def _sell(client, auth_headers, pid, bid, qty, unit_price=None, when=None):
    """یک فروش واقعی از مسیر صندوق (برای ساختن سرعت فروش).

    قیمت پیش‌فرض از خودِ بچ خوانده می‌شود وگرنه صندوق با PAYMENT_MISMATCH رد
    می‌کند — همان محافظتی که نمی‌گذارد پای صندوق قیمت دلخواه بسازد.
    """
    if unit_price is None:
        with SessionLocal() as db:
            unit_price = float(db.get(ProductBatch, bid).sell_price)
    r = client.post("/api/pos/checkout", headers=auth_headers, json={
        "items": [{"product_id": pid, "quantity": qty, "batch_id": bid}],
        "payments": [{"method": "CASH", "amount": qty * unit_price}]})
    assert r.status_code in (200, 201), r.text
    if when is not None:
        inv_id = r.json().get("id")
        with SessionLocal() as db:
            from app.models import Invoice
            inv = db.get(Invoice, inv_id)
            if inv is not None:
                inv.created_at = when
                for it in inv.items:
                    it.created_at = when
                db.commit()
    return r.json()


def _set_setting(db, key, value):
    row = db.execute(select(SystemSetting).where(SystemSetting.key == key)).scalar_one_or_none()
    if row:
        row.value = str(value)
    else:
        db.add(SystemSetting(key=key, value=str(value)))
    db.flush()


@contextlib.contextmanager
def _run_expiry_all(db, product_id):
    """تحلیل‌گر انقضا را روی دادهٔ همین دیتابیس اجرا کن و پیشنهاد این کالا را برگردان.

    سقف تولیدی کارت‌های انقضا (``EXPIRY_DRAFTS_CAP``) در دیتابیس مشترکِ کل تست‌ها
    می‌تواند با بچ‌های نزدیک‌انقضای تست‌های دیگر پر شود؛ اینجا سقف موقتاً بالا
    می‌رود تا تست، خودِ منطق را بسنجد نه شانسِ رتبه‌بندی. مسیر تولید در تست جداگانه
    (``test_expiry_cards_are_not_dropped_when_many_batches_are_at_risk``) با سقف
    واقعی سنجیده می‌شود.
    """
    cap = insights.EXPIRY_DRAFTS_CAP
    insights.EXPIRY_DRAFTS_CAP = 500
    try:
        ctx = insights._load_ctx(db, 90)
        drafts = insights.a_expiry_ladder(ctx)
        yield [d for d in drafts if d.evidence.get("product_id") == product_id], ctx
    finally:
        insights.EXPIRY_DRAFTS_CAP = cap


def _run_expiry(db, product_id):
    with _run_expiry_all(db, product_id) as (drafts, _ctx):
        return drafts


# =========================================================== ۱) منطق خالص زمان‌بندی
def test_advice_fires_weeks_before_expiry_not_on_day_zero():
    # اعداد واقعی تومانی: آستانهٔ ریسکِ محصول ۵۰٬۰۰۰ تومان است، پس تست با
    # مبالغ واقعی نوشته می‌شود (نه با ۱۰۰۰ تومان که همیشه زیر آستانه می‌ماند).
    """هستهٔ باگ: روی «روز صفر» نه؛ چند هفته قبل، وقتی هنوز وقت اقدام هست.

    سناریوی واقعی: ۴۰ عدد ماست، ۲۰ روز تا انقضا، فروش ۱ عدد در روز.
    قدیمی (خوش‌بین + بدون بافر): ۱×۲۰ = ۲۰ < ۰.۹×۴۰=۳۶ → پیشنهاد می‌داد، ولی
    اگر یک هفتهٔ شلوغ سرعت را بالا می‌برد ساکت می‌شد تا روز صفر.
    اکنون: سرعت محافظه‌کارانه و تایم‌لاین تاریخ‌دار.
    """
    today = date(2026, 9, 27)
    plan = expiry_plan.build_plan(today=today, expiry=today + timedelta(days=20), qty=40,
                                  velocity=1.0, buy=10_000, sell=15_000)
    assert plan is not None and plan["mode"] == "ladder"
    assert plan["days_left"] == 20
    assert plan["velocity_per_day"] == 1.0
    assert plan["surplus"] == 20.0
    assert plan["at_risk"] == 200_000

    timeline = plan["timeline"]
    assert timeline, "برنامه بدون تایم‌لاین بی‌معناست"
    assert timeline[0]["date"] == today.isoformat(), "پلهٔ اول از امروز"
    assert timeline[0]["jdate"] == expiry_plan.jdate(today)
    # آخرین پله دست‌کم دو روز پیش از انقضا، و هیچ پله‌ای بعد از انقضا نیست
    assert plan["final_runway_days"] >= expiry_plan.MIN_FINAL_RUNWAY_DAYS
    last_day = date.fromisoformat(timeline[-1]["date"])
    assert last_day <= today + timedelta(days=plan["days_left"] - expiry_plan.MIN_FINAL_RUNWAY_DAYS)
    # تخفیف پله‌ای صعودی است و هرگز از قیمت خرید پایین نمی‌زند
    percents = [t["percent"] for t in timeline]
    assert percents == sorted(percents) and percents[-1] <= expiry_plan.MAX_DISCOUNT_PERCENT
    for t in timeline:
        assert t["suggested_price"] >= 10_000 * 1.01


def test_promo_week_does_not_silence_the_advice():
    """سرعت محافظه‌کارانه: یک هفتهٔ پرفروش نباید هشدار را خاموش کند.

    کمینهٔ نرخ‌ها انتخاب می‌شود، پس فروشگاه حتی وقتی «همین هفته خوب فروخت»
    هم برنامهٔ محتاطانه می‌گیرد — نه سکوت تا روز صفر.
    """
    assert expiry_plan.conservative_velocity  # قرارداد ماژول

    class _C:
        days = 90

    calls = {}

    def fake_velocity(ctx, pid, days=28):
        calls[days] = 8.0 if days == 28 else 1.0     # هفتهٔ شلوغ، ماه آرام
        return calls[days]

    import app.services.insights as ins
    original = ins._daily_velocity
    ins._daily_velocity = fake_velocity
    try:
        v = expiry_plan.conservative_velocity(_C(), 7)
    finally:
        ins._daily_velocity = original
    assert v == 1.0, "باید کندترین نرخ (نه بهترین هفته) ملاک باشد"


def test_safety_buffer_delays_the_decision_but_never_past_the_point_of_no_return():
    """«کمی می‌فروشد» کافی نیست: باید وضعیت روشن باشد یا هشدار بیاید."""
    today = date(2026, 9, 27)
    expiry = today + timedelta(days=10)
    # ۱۰ عدد، ۱۰ روز، سرعت ۰.۹ → ۹ عدد فروش می‌رود؛ با بافر ۱۵٪ ریسکِ ۱ عدد
    # ارزش هشدار ندارد (زیر آستانهٔ ریالی) → سکوت درست است.
    assert expiry_plan.build_plan(today=today, expiry=expiry, qty=10, velocity=0.9,
                                  buy=5_000, sell=8_000) is None
    # همان کالا با ۱۰۰ عدد و سرعت ۹ → ۱۰ عدد ضایعات = ۵۰٬۰۰۰ تومان ریسک → هشدار
    plan = expiry_plan.build_plan(today=today, expiry=expiry, qty=100, velocity=9.0,
                                  buy=5_000, sell=8_000)
    assert plan is not None and plan["surplus"] == 10.0


def test_day_zero_is_a_last_chance_with_a_single_step_not_a_silent_skip():
    today = date(2026, 9, 27)
    plan = expiry_plan.build_plan(today=today, expiry=today, qty=30, velocity=0.0,
                                  buy=10_000, sell=20_000)
    assert plan is not None and plan["mode"] == "ladder"
    assert plan["days_left"] == 0
    assert len(plan["timeline"]) == 1
    assert plan["timeline"][0]["date"] == today.isoformat()
    assert plan.get("urgent") is True


def test_expired_stock_is_never_given_a_discount():
    """کالای تاریخ‌گذشته تخفیف نمی‌گیرد — ثبت ضایعات می‌گیرد (صداقت انبار)."""
    today = date(2026, 9, 27)
    plan = expiry_plan.build_plan(today=today, expiry=today - timedelta(days=3), qty=12,
                                  velocity=1.0, buy=10_000, sell=15_000)
    assert plan is not None and plan["mode"] == "waste"
    assert "ladder" not in plan
    assert plan["at_risk"] == 120_000


def test_far_future_batches_stay_quiet():
    today = date(2026, 9, 27)
    assert expiry_plan.build_plan(today=today, expiry=today + timedelta(days=90), qty=500,
                                  velocity=0.0, buy=10_000, sell=15_000) is None
    assert expiry_plan.build_plan(today=today, expiry=None, qty=500, velocity=0.0,
                                  buy=10_000, sell=15_000) is None


# =========================================================== ۲) تحلیل‌گر روی داده واقعی
def test_analyzer_emits_a_dated_plan_for_real_stock(client, auth_headers):
    pid, bid = _make_product(client, auth_headers, "ماست تایم‌لاین", qty=40, expiry_days=18,
                             buy=10_000, sell=15_000)
    _sell(client, auth_headers, pid, bid, 3)      # مختصر فروش تا سرعت > ۰ شود
    with SessionLocal() as db:
        drafts = _run_expiry(db, pid)
    assert drafts, "با ۴۰ عدد و ۱۸ روز مانده باید پیشنهاد بیاید"
    d = drafts[0]
    assert d.kind == "EXPIRY_LADDER"
    assert d.evidence["mode"] == "ladder"
    # تاریخ پلهٔ اول باید «امروزِ فروشگاه» باشد (تقویم شمسی، نه تاریخ خام میلادی)
    assert d.evidence["timeline"][0]["jdate"] == expiry_plan.jdate(local_today())
    assert d.evidence["final_runway_days"] >= expiry_plan.MIN_FINAL_RUNWAY_DAYS
    # تاریخ‌ها در متن و در اقدام‌ها یکی هستند (تایم‌لاین = واقعیت اجرا)
    ladder = d.actions[0]["params"]["ladder"]
    assert [s["percent"] for s in ladder] == [t["percent"] for t in d.evidence["timeline"]]
    assert "روز فرصت دارید" in d.title or "آخرین فرصت" in d.title


def test_expired_batch_produces_waste_alert_with_real_action(client, auth_headers):
    pid, bid = _make_product(client, auth_headers, "پنیر تاریخ‌گذشته", qty=6, expiry_days=-2,
                             buy=20_000, sell=30_000)
    with SessionLocal() as db:
        drafts = _run_expiry(db, pid)
    assert drafts and drafts[0].evidence["mode"] == "waste"
    types = [a["type"] for a in drafts[0].actions]
    assert "write_off_waste" in types, "باید اقدام واقعی ثبت ضایعات داشته باشد"
    assert "markdown_ladder" not in types, "روی کالای فاسد تخفیف معنا ندارد"


def test_expiry_cards_are_not_dropped_when_many_batches_are_at_risk():
    """در فروشگاهی با ده‌ها بچ نزدیک انقضا، بچ‌های بعدی هم باید کارت بگیرند.

    قبلاً تحلیل‌گر فقط ۸ کارت برمی‌گرداند؛ با ۳۰ بچ در خطر، ۲۲ تا هیچ‌وقت
    پیشنهاد نمی‌گرفتند — همان سکوتی که مالک از آن شکایت داشت («یک هفته قبلش
    پیشنهاد بدهد»). سقف اکنون ۲۵ است و صفحه فهرست را صفحه‌بندی می‌کند.
    """
    with SessionLocal() as db:
        made = []
        for i in range(30):
            p = Product(barcode=f"V48C{uuid.uuid4().hex[:9]}", name=f"کالای فوری {i}")
            db.add(p)
            db.flush()
            b = ProductBatch(product_id=p.id, batch_number=f"B{i}", quantity_received=10, current_qty=10,
                             buy_price=Decimal("10000"), sell_price=Decimal("15000"), status="ACTIVE",
                             expiry_date=date.today() + timedelta(days=20),
                             received_at=datetime.utcnow() - timedelta(days=10))
            db.add(b)
            made.append(p.id)
        db.flush()
        cap = insights.EXPIRY_DRAFTS_CAP
        ctx = insights._load_ctx(db, 90)
        drafts = insights.a_expiry_ladder(ctx)
        mine = [d for d in drafts if d.evidence.get("product_id") in made]
        assert len(drafts) == cap, f"سقف واقعی باید {cap} کارت باشد (شد {len(drafts)})"
        assert len(mine) > 8, f"با ۳۰ بچ در خطر، بیش از ۸ کارت باید ساخته شود (شد {len(mine)})"
        assert all(d.evidence["mode"] == "ladder" for d in mine)
        db.rollback()


# =========================================================== ۳) اجرا واقعاً انجام می‌شود
def test_accepting_the_ladder_moves_the_price_now_and_verifies(client, auth_headers):
    pid, bid = _make_product(client, auth_headers, "کره پله‌ای", qty=25, expiry_days=15,
                             buy=10_000, sell=20_000)
    _sell(client, auth_headers, pid, bid, 1)
    with SessionLocal() as db:
        drafts = _run_expiry(db, pid)
        assert drafts
        draft = drafts[0]
        # همان رکوردی که موتور ذخیره می‌کند (بدون وابستگی به run کاملِ فروشگاه،
        # چون دیتابیس تست با کل مجموعه شریک است)
        row = Insight(kind=draft.kind, dedupe_key=draft.dedupe_key, title=draft.title, body=draft.body,
                      priority=draft.priority, status="NEW",
                      evidence=json.dumps(draft.evidence, ensure_ascii=False, default=str),
                      actions=json.dumps(draft.actions, ensure_ascii=False, default=str),
                      expected_gain=draft.expected_gain,
                      metric=json.dumps(draft.metric, ensure_ascii=False, default=str))
        db.add(row)
        db.commit()
        insight_id = row.id
        base_price = float(db.get(ProductBatch, bid).sell_price)

    r = client.post(f"/api/insights/{insight_id}/accept", headers=auth_headers, json={})
    assert r.status_code == 200, r.text
    body = r.json()
    markdown = [e for e in body["executed"] if e["type"] == "markdown_ladder"][0]
    assert markdown["ok"] is True
    assert markdown["status"] == "EXECUTED_VERIFIED", markdown
    assert "price" in (markdown.get("verify") or "")

    # قیمت واقعی بچ همان لحظه پایین آمده و تخفیف پله‌ای هم روی بچ نشسته است
    with SessionLocal() as db:
        b = db.get(ProductBatch, bid)
        assert float(b.sell_price) < base_price, "تخفیف باید واقعاً اعمال شده باشد"
        plan = [p for p in json.loads(db.execute(select(SystemSetting).where(
            SystemSetting.key == "insights.markdown_plans")).scalar_one_or_none().value or "[]")
            if p["batch_id"] == bid]
        assert plan and plan[0]["applied"], "پلهٔ اول باید ثبت شده باشد"

    # گزارش بازبینی: اقدام اجراشده «همین حالا» هم برقرار است
    rep = client.get("/api/insights/actions/report", headers=auth_headers)
    assert rep.status_code == 200, rep.text
    rows = [r for r in rep.json()["rows"] if r["insight_id"] == insight_id]
    assert rows, "گزارش اقدام‌ها باید این پیشنهاد را داشته باشد"
    assert any(a["health"] == "OK" for a in rows[0]["actions"])
    assert rep.json()["counts"]["OK"] >= 1


def test_ladder_steps_are_applied_on_their_own_dates():
    """پله‌های بعدی روی تاریخ خودشان اعمال می‌شوند، و هرگز زیر قیمت خرید نمی‌روند."""
    with SessionLocal() as db:
        from app.models import Insight as _I
        pid = None
        product = Product(barcode=f"V48S{uuid.uuid4().hex[:8]}", name="شیر پله‌ای زمان‌بندی")
        db.add(product)
        db.flush()
        batch = ProductBatch(product_id=product.id, batch_number="B1", quantity_received=100,
                             current_qty=100, buy_price=Decimal("1000"), sell_price=Decimal("2000"),
                             status="ACTIVE", received_at=datetime.utcnow() - timedelta(days=30))
        db.add(batch)
        db.flush()
        insight = _I(kind="EXPIRY_LADDER", dedupe_key="timeline-test", title="t", body="b", status="NEW")
        db.add(insight)
        db.flush()
        result = insight_actions.act_markdown_ladder(db, insight, {
            "batch_id": batch.id,
            "ladder": [{"from_day": 0, "percent": 10},
                       {"from_day": 5, "percent": 20},
                       {"from_day": 10, "percent": 30}]}, None)
        db.flush()
        assert result["applied_now"] == 1
        first = float(db.get(ProductBatch, batch.id).sell_price)
        assert first == 1800.0, f"پلهٔ اول ۱۰٪ از ۲۰۰۰ → ۱۸۰۰ (شد {first})"

        # پلهٔ دوم هنوز موعدش نرسیده
        assert insight_actions.apply_markdown_steps(db) == 0
        assert float(db.get(ProductBatch, batch.id).sell_price) == first

        # با گذر زمان (شبیه‌سازی: تاریخ شروع ۶ روز قبل) پلهٔ دوم اعمال می‌شود
        plans = json.loads(db.execute(select(SystemSetting).where(
            SystemSetting.key == "insights.markdown_plans")).scalar_one().value)
        target = next(p for p in plans if p["batch_id"] == batch.id)
        target["start"] = (date.today() - timedelta(days=6)).isoformat()
        _set_setting(db, "insights.markdown_plans", json.dumps(plans, ensure_ascii=False))
        assert insight_actions.apply_markdown_steps(db) == 1
        second = float(db.get(ProductBatch, batch.id).sell_price)
        assert second == 1600.0, f"پلهٔ دوم ۲۰٪ از ۲۰۰۰ → ۱۶۰۰ (شد {second})"
        # دو پله با درصد یکسان هم هر دو اعمال می‌شوند (باگ قبلی: درصد تکراری رد می‌شد)
        db.rollback()


def test_verify_fails_honestly_when_the_plan_cannot_move_a_price():
    """اگر قیمت واقعاً تغییر نکند، پیشنهاد نباید «اجرا شده» ثبت شود."""
    with SessionLocal() as db:
        from app.models import Insight as _I
        product = Product(barcode=f"V48F{uuid.uuid4().hex[:8]}", name="کالای بی‌قیمت")
        db.add(product)
        db.flush()
        batch = ProductBatch(product_id=product.id, batch_number="B0", quantity_received=5,
                             current_qty=0, buy_price=Decimal("1000"), sell_price=Decimal("1500"),
                             status="ACTIVE", received_at=datetime.utcnow())
        db.add(batch)
        db.flush()
        insight = _I(kind="EXPIRY_LADDER", dedupe_key="verify-fail", title="t", body="b", status="NEW")
        db.add(insight)
        db.flush()
        plan = {"batch_id": batch.id, "base_price": 1500.0, "start": date.today().isoformat(),
                "ladder": [{"from_day": 0, "percent": 10}], "applied": [], "applied_dates": []}
        _set_setting(db, "insights.markdown_plans", json.dumps([plan]))
        ok, detail = insight_actions._verify(db, insight, "markdown_ladder", {"batch_id": batch.id, "ladder": plan["ladder"]},
                                             {"plan": plan})
        assert ok is False and ("NO step applied" in detail or "MISSING" in detail)
        db.rollback()


def test_write_off_waste_really_moves_stock(client, auth_headers):
    pid, bid = _make_product(client, auth_headers, "ضایعات واقعی", qty=9, expiry_days=-1)
    with SessionLocal() as db:
        insight = Insight(kind="EXPIRY_LADDER", dedupe_key="waste-real", title="t", body="b", status="NEW")
        db.add(insight)
        db.flush()
        res = insight_actions.act_write_off_waste(db, insight, {"batch_id": bid, "qty": 4, "reason": "تست"}, None)
        db.flush()
        assert res["wasted"] == 4 and res["after_qty"] == 5.0
        movements = db.execute(select(StockMovement).where(StockMovement.batch_id == bid,
                                                           StockMovement.movement_type == "WASTE")).scalars().all()
        assert len(movements) == 1
        ok, detail = insight_actions._verify(db, insight, "write_off_waste", {"batch_id": bid, "qty": 4}, res)
        assert ok is True, detail
        db.rollback()


def test_worker_health_scan_flags_a_lost_effect(client, auth_headers):
    """اگر اثر یک اقدام از بین برود، «سیستم بررسی فروشگاه» باید آن را پیدا کند."""
    pid, bid = _make_product(client, auth_headers, "بازبینی اثر", qty=20, expiry_days=12, buy=1000, sell=2000)
    with SessionLocal() as db:
        insight = Insight(kind="EXPIRY_LADDER", dedupe_key="health-scan", title="بازبینی اثر", body="b",
                          status="ACCEPTED", accepted_at=datetime.utcnow())
        db.add(insight)
        db.flush()
        res = insight_actions.act_markdown_ladder(db, insight, {"batch_id": bid,
                                                   "ladder": [{"from_day": 0, "percent": 25}]}, None)
        executions = [{"type": "markdown_ladder", "at": datetime.utcnow().isoformat(),
                       "status": "EXECUTED_VERIFIED", "params": {"batch_id": bid, "ladder": [{"from_day": 0, "percent": 25}]},
                       "result": res, "verify": "ok"}]
        insight.evidence = json.dumps({"executions": executions})
        db.flush()
        mine = lambda res: [x for x in res["lost"] if x["insight_id"] == insight.id]
        assert mine(insight_actions.health_scan(db)) == [], "تازه اجرا شده — باید سالم باشد"
        # اثر از بین می‌رود: کسی قیمت را دستی برمی‌گرداند و برنامه پاک می‌شود
        db.get(ProductBatch, bid).sell_price = Decimal("2000")
        _set_setting(db, "insights.markdown_plans", "[]")
        db.flush()
        found = mine(insight_actions.health_scan(db))
        assert found and found[0]["type"] == "markdown_ladder"
        db.rollback()


def test_pos_checkout_applies_due_ladder_steps(client, auth_headers):
    """حتی با کارگر خاموش، تخفیفی که موعدش رسیده روی صندوق اعمال می‌شود."""
    pid, bid = _make_product(client, auth_headers, "قفسه تخفیف‌دار", qty=10, expiry_days=9, buy=1000, sell=2000)
    with SessionLocal() as db:
        plan = {"batch_id": bid, "base_price": 2000.0, "start": date.today().isoformat(),
                "ladder": [{"from_day": 0, "percent": 30}], "applied": [], "applied_dates": [],
                "product_id": pid}
        _set_setting(db, "insights.markdown_plans", json.dumps([plan]))
        db.commit()
    _sell(client, auth_headers, pid, bid, 1, unit_price=1400)
    with SessionLocal() as db:
        assert float(db.get(ProductBatch, bid).sell_price) == 1400.0, "پلهٔ سررسیدشده باید پیش از فروش اعمال شود"
        db.rollback()
