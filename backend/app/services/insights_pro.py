"""v3.5 — Store Intelligence **PRO**: 46 additional analyzers on top of the 13 in ``insights``.

Same contract as ``insights``: every analyzer is ``(Ctx) -> list[Draft]``, reads only real
rows, returns evidence the owner can check, and its actions run through
``insight_actions.ACTIONS`` when accepted. The extra frames (ledger, cheques, returns,
coupons, stocktakes, movements, price history, …) are loaded lazily and cached on the
context, so a full run stays a handful of queries.

Groups
------
Customer behaviour (12) — PAY_CYCLE, CUST_FAVORITE, CUST_ITEM_DUE, TICKET_DROP, FREQ_DROP,
    NEW_CUST_2ND, OFFER_SENSITIVE, CATEGORY_GAP, CREDIT_RISK, ANNIVERSARY, BULK_BUYER, THRESHOLD_UPSELL
Stock & forecast (12) — REORDER_POINT, OVERSTOCK, STOCKOUT_HISTORY, TREND_UP, TREND_DOWN,
    EXPIRY_RISK_BUY, WASTE_PATTERN, SHRINKAGE, CATEGORY_TURNS, FIFO_BREAK, SUPPLIER_LEAD, SEASONAL_YOY
Pricing & margin (6) — PROFIT_PARETO, NEGATIVE_MARGIN, DISCOUNT_LEAK, PRICE_ROUNDING, ELASTICITY, CATEGORY_MARGIN
Operations (8) — PEAK_HOURS, QUEUE_STRESS, CASHIER_PERF, CASH_DIFF, RETURNS_PRODUCT,
    RECEIVABLES_AGING, EXPENSE_SPIKE, SMS_ROI
Growth (7) — CAMPAIGN_FATIGUE, UNREGISTERED_SALES, HERO_PRODUCT, SLOW_DAY, BASKET_TREND,
    NEW_PRODUCT_WATCH, CATEGORY_DEPTH
Daily (1) — SURPRISE («امروز می‌دانستید؟»: one fresh, checkable fact a day)
"""
from __future__ import annotations

import math
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta

from sqlalchemy import func, select

from ..models import (AuditLog, Campaign, CashSession, Category, Cheque, Coupon, CouponRedemption, Customer,
                      CustomerLedgerEntry, Expense, ExpenseCategory, Invoice, InvoiceItem, PriceVersion, Product,
                      ProductBatch, Return, SmsMessage, StockMovement, StocktakeItem, Supplier, User)
from .insights import PAID, WEEKDAY_FA, Ctx, Draft, _avg_margin, _f, _fa, _money, _pname, _stock
from .timeservice import to_jalali

JMONTH = ["فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور", "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند"]


# ----------------------------------------------------------------------------- lazy frames
class Ext:
    """Extra frames for the PRO analyzers, loaded once per run and cached on the ctx."""

    def __init__(self, ctx: Ctx):
        self.ctx = ctx
        self.db = ctx.db
        self._c: dict = {}

    def _m(self, key, fn):
        if key not in self._c:
            self._c[key] = fn()
        return self._c[key]

    # --- customers -------------------------------------------------------
    @property
    def customers(self) -> dict[int, Customer]:
        return self._m("customers", lambda: {c.id: c for c in self.db.execute(select(Customer)).scalars()})

    def cname(self, cid: int) -> str:
        c = self.customers.get(cid)
        return f"{c.name} {c.last_name or ''}".strip() if c else f"#{cid}"

    def phone(self, cid: int):
        c = self.customers.get(cid)
        return c.phone if c else None

    @property
    def by_cust(self) -> dict[int, list[dict]]:
        """customer → invoices (with id) sorted by time, paid, in window."""
        def build():
            d: dict[int, list[dict]] = defaultdict(list)
            for iid, inv in self.ctx.invoices.items():
                if inv["cust"]:
                    d[inv["cust"]].append({"id": iid, **inv})
            for v in d.values():
                v.sort(key=lambda x: x["at"])
            return d
        return self._m("by_cust", build)

    @property
    def cust_lines(self) -> dict[int, list[dict]]:
        def build():
            d: dict[int, list[dict]] = defaultdict(list)
            for l in self.ctx.lines:
                if l["cust"]:
                    d[l["cust"]].append(l)
            return d
        return self._m("cust_lines", build)

    @property
    def first_visit(self) -> dict[int, datetime]:
        return self._m("first_visit", lambda: {r[0]: r[1] for r in self.db.execute(
            select(Invoice.customer_id, func.min(Invoice.created_at)).where(Invoice.status == PAID, Invoice.customer_id.is_not(None))
            .group_by(Invoice.customer_id)).all()})

    @property
    def ledger(self) -> list[CustomerLedgerEntry]:
        since = self.ctx.since(365)
        return self._m("ledger", lambda: self.db.execute(select(CustomerLedgerEntry).where(CustomerLedgerEntry.created_at >= since)
                                                         .order_by(CustomerLedgerEntry.created_at)).scalars().all())

    @property
    def balances(self) -> dict[int, tuple[float, datetime]]:
        """customer → (current balance, time of last entry) from the latest ledger row."""
        def build():
            sub = select(CustomerLedgerEntry.customer_id, func.max(CustomerLedgerEntry.id).label("mid")).group_by(CustomerLedgerEntry.customer_id).subquery()
            rows = self.db.execute(select(CustomerLedgerEntry).join(sub, CustomerLedgerEntry.id == sub.c.mid)).scalars().all()
            return {e.customer_id: (_f(e.balance_after), e.created_at) for e in rows}
        return self._m("balances", build)

    # --- products / stock ---------------------------------------------------
    @property
    def categories(self) -> dict[int, str]:
        return self._m("categories", lambda: {c.id: c.name for c in self.db.execute(select(Category)).scalars()})

    def cat_of(self, pid: int):
        p = self.ctx.products.get(pid)
        return p.category_id if p else None

    def cat_name(self, cid) -> str:
        return self.categories.get(cid, "بدون دسته") if cid else "بدون دسته"

    @property
    def active_batches(self) -> list[ProductBatch]:
        return self._m("active_batches", lambda: self.db.execute(select(ProductBatch).where(ProductBatch.status == "ACTIVE", ProductBatch.current_qty > 0)).scalars().all())

    @property
    def stock_by_pid(self) -> dict[int, float]:
        def build():
            d: dict[int, float] = defaultdict(float)
            for b in self.active_batches:
                d[b.product_id] += _f(b.current_qty)
            return d
        return self._m("stock_by_pid", build)

    @property
    def capital_by_pid(self) -> dict[int, float]:
        def build():
            d: dict[int, float] = defaultdict(float)
            for b in self.active_batches:
                d[b.product_id] += _f(b.current_qty) * _f(b.buy_price)
            return d
        return self._m("capital_by_pid", build)

    @property
    def recent_batches(self) -> list[ProductBatch]:
        since = self.ctx.since(180)
        return self._m("recent_batches", lambda: self.db.execute(select(ProductBatch).where(ProductBatch.received_at >= since)
                                                                 .order_by(ProductBatch.received_at)).scalars().all())

    @property
    def movements(self) -> list[tuple]:
        """(created_at, product_id, movement_type, qty) for the window."""
        since = self.ctx.since(self.ctx.days)
        return self._m("movements", lambda: self.db.execute(
            select(StockMovement.created_at, ProductBatch.product_id, StockMovement.movement_type, StockMovement.quantity)
            .join(ProductBatch, ProductBatch.id == StockMovement.batch_id).where(StockMovement.created_at >= since)).all())

    @property
    def velocity28(self) -> dict[int, float]:
        def build():
            since = self.ctx.since(28)
            q: Counter = Counter()
            for l in self.ctx.lines:
                if l["at"] >= since:
                    q[l["pid"]] += l["qty"]
            return {p: v / 28 for p, v in q.items()}
        return self._m("velocity28", build)

    def weekly_units(self, pid: int, weeks: int = 6) -> list[float]:
        wk = self._m("weekly", lambda: self._weekly())
        return wk.get(pid, [0.0] * weeks)[-weeks:]

    def _weekly(self) -> dict[int, list[float]]:
        n = 8
        out: dict[int, list[float]] = defaultdict(lambda: [0.0] * n)
        now = self.ctx.now_utc
        for l in self.ctx.lines:
            k = int((now - l["at"]).total_seconds() // (7 * 86400))
            if 0 <= k < n:
                out[l["pid"]][n - 1 - k] += l["qty"]
        return out

    @property
    def first_sold(self) -> dict[int, datetime]:
        return self._m("first_sold", lambda: {r[0]: r[1] for r in self.db.execute(
            select(InvoiceItem.product_id, func.min(Invoice.created_at)).join(Invoice, Invoice.id == InvoiceItem.invoice_id)
            .where(Invoice.status == PAID).group_by(InvoiceItem.product_id)).all()})

    @property
    def stocktake_diffs(self) -> list[StocktakeItem]:
        since = self.ctx.since(180)
        return self._m("stocktake_diffs", lambda: self.db.execute(select(StocktakeItem).where(StocktakeItem.counted_at >= since, StocktakeItem.difference != 0)).scalars().all())

    @property
    def price_versions(self) -> list[PriceVersion]:
        since = self.ctx.since(180)
        return self._m("price_versions", lambda: self.db.execute(select(PriceVersion).where(PriceVersion.price_type == "SELL", PriceVersion.effective_from >= since)
                                                                 .order_by(PriceVersion.effective_from)).scalars().all())

    @property
    def suppliers(self) -> dict[int, str]:
        return self._m("suppliers", lambda: {s.id: s.name for s in self.db.execute(select(Supplier)).scalars()})

    # --- money / ops --------------------------------------------------------
    @property
    def returns(self) -> list[tuple]:
        since = self.ctx.since(self.ctx.days)
        return self._m("returns", lambda: self.db.execute(
            select(Return.created_at, InvoiceItem.product_id, Return.qty, Return.reason, Return.refund_amount)
            .join(InvoiceItem, InvoiceItem.id == Return.invoice_item_id).where(Return.created_at >= since)).all())

    @property
    def expenses(self) -> list[tuple]:
        since = (self.ctx.now_utc - timedelta(days=120)).date()
        return self._m("expenses", lambda: self.db.execute(
            select(Expense.expense_date, Expense.amount, ExpenseCategory.name).join(ExpenseCategory, ExpenseCategory.id == Expense.category_id)
            .where(Expense.expense_date >= since)).all())

    @property
    def coupons(self) -> list[Coupon]:
        since = self.ctx.since(120)
        return self._m("coupons", lambda: self.db.execute(select(Coupon).where(Coupon.created_at >= since)).scalars().all())

    @property
    def redemptions(self) -> list[CouponRedemption]:
        since = self.ctx.since(180)
        return self._m("redemptions", lambda: self.db.execute(select(CouponRedemption).where(CouponRedemption.created_at >= since)).scalars().all())

    @property
    def campaigns(self) -> dict[int, Campaign]:
        return self._m("campaigns", lambda: {c.id: c for c in self.db.execute(select(Campaign)).scalars()})

    @property
    def sms(self) -> list[SmsMessage]:
        since = self.ctx.since(120)
        return self._m("sms", lambda: self.db.execute(select(SmsMessage).where(SmsMessage.created_at >= since)).scalars().all())

    @property
    def cash_sessions(self) -> list[CashSession]:
        since = self.ctx.since(90)
        return self._m("cash_sessions", lambda: self.db.execute(select(CashSession).where(CashSession.opened_at >= since, CashSession.status != "OPEN")).scalars().all())

    @property
    def voids(self) -> list[AuditLog]:
        since = self.ctx.since(self.ctx.days)
        return self._m("voids", lambda: self.db.execute(select(AuditLog).where(AuditLog.action == "SALE_VOIDED", AuditLog.created_at >= since)).scalars().all())

    @property
    def users(self) -> dict[int, str]:
        return self._m("users", lambda: {u.id: (getattr(u, "full_name", None) or getattr(u, "username", None) or str(u.id)) for u in self.db.execute(select(User)).scalars()})

    @property
    def cheques(self) -> list[Cheque]:
        return self._m("cheques", lambda: self.db.execute(select(Cheque).where(Cheque.status == "PENDING")).scalars().all())


def ext(ctx: Ctx) -> Ext:
    e = getattr(ctx, "_ext", None)
    if e is None:
        e = Ext(ctx)
        setattr(ctx, "_ext", e)
    return e


def _median(xs):
    xs = sorted(xs)
    return xs[len(xs) // 2] if xs else 0


def _slope(ys: list[float]) -> float:
    """least-squares slope per step, normalised by the mean (→ relative change per step)."""
    n = len(ys)
    if n < 3:
        return 0.0
    xm, ym = (n - 1) / 2, sum(ys) / n
    den = sum((i - xm) ** 2 for i in range(n)) or 1
    s = sum((i - xm) * (y - ym) for i, y in enumerate(ys)) / den
    return s / ym if ym > 0 else 0.0


def _local_hour(dt: datetime) -> int:
    return (dt + timedelta(hours=3, minutes=30)).hour


def _cust_rows(e: Ext, cids, extra=None):
    out = []
    for cid in cids:
        r = {"customer_id": cid, "name": e.cname(cid), "phone": e.phone(cid)}
        if extra:
            r.update(extra(cid) or {})
        out.append(r)
    return out


def _sms_action(label: str, texts: list[dict]) -> dict:
    return {"type": "personal_sms", "label": label, "params": {"customers": texts}}


# =============================================================================
# CUSTOMER BEHAVIOUR
# =============================================================================
def a_pay_cycle(ctx: Ctx) -> list[Draft]:
    """When does each credit customer usually settle? → remind them the day before their own pay-day."""
    e = ext(ctx)
    pays: dict[int, list[datetime]] = defaultdict(list)
    for en in e.ledger:
        if en.entry_type == "PAYMENT":
            pays[en.customer_id].append(en.created_at)
    rows = []
    today = ctx.today
    for cid, ds in pays.items():
        if len(ds) < 3:
            continue
        bal, _ = e.balances.get(cid, (0.0, None))
        if bal <= 0:
            continue
        doms = [to_jalali(d + timedelta(hours=3, minutes=30))[2] for d in ds]
        dom = _median(doms)
        spread = _median([abs(x - dom) for x in doms])
        if spread > 5:
            continue
        jd = to_jalali(datetime.combine(today, datetime.min.time()))[2]
        due_in = (dom - jd) % 30
        if due_in > 3:
            continue
        rows.append({"customer_id": cid, "name": e.cname(cid), "phone": e.phone(cid), "balance": round(bal), "pay_day": dom,
                     "spread_days": spread, "payments": len(ds), "due_in": due_in})
    if not rows:
        return []
    rows.sort(key=lambda r: -r["balance"])
    rows = rows[:30]
    total = sum(r["balance"] for r in rows)
    ex = rows[0]
    texts = [{"customer_id": r["customer_id"], "text": f"{r['name']} عزیز، مانده حساب شما {_money(r['balance'])} است؛ طبق روال همیشگی منتظر تسویهٔ {_fa(r['pay_day'])}ام هستیم. سپاس از همراهی‌تان."} for r in rows if r["phone"]]
    return [Draft(kind="PAY_CYCLE", dedupe_key=f"day:{today.isoformat()}", priority=2,
                  title=f"{_fa(len(rows))} مشتری نسیه‌ای طی ۳ روز آینده روز تسویه‌شان است",
                  body=(f"از تاریخ پرداخت‌های قبلی، هر مشتری یک «روز حقوق» دارد؛ مثلاً «{ex['name']}» معمولاً {_fa(ex['pay_day'])}ام هر ماه تسویه می‌کند "
                        f"(انحراف ±{_fa(ex['spread_days'])} روز). یادآوری یک روز قبل از همان روز، بدون این‌که مزاحم باشد، وصول را چند روز جلو می‌اندازد. "
                        f"مجموع مانده: {_money(total)}."),
                  evidence={"rows": rows, "total_balance": round(total)},
                  actions=[_sms_action("پیامک یادآوری در روز تسویهٔ خودِ مشتری", texts)],
                  expected_gain=total * 0.02, metric={"metric": "receivables_collected", "window_days": 14})]


def a_cust_favorite(ctx: Ctx) -> list[Draft]:
    """What excites each top customer: the product/category with an unusually high share of *their* basket."""
    e = ext(ctx)
    store_share: Counter = Counter()
    tot = 0.0
    for l in ctx.lines:
        store_share[l["pid"]] += l["sub"]
        tot += l["sub"]
    if tot <= 0 or len(e.by_cust) < 10:
        return []
    rows = []
    for cid, ls in e.cust_lines.items():
        if len(e.by_cust.get(cid, [])) < 4:
            continue
        mine: Counter = Counter()
        s = 0.0
        for l in ls:
            mine[l["pid"]] += l["sub"]
            s += l["sub"]
        if s <= 0:
            continue
        pid, v = mine.most_common(1)[0]
        my = v / s
        base = store_share[pid] / tot
        lift = my / base if base > 0 else 0
        if my >= 0.15 and lift >= 3:
            rows.append({"customer_id": cid, "name": e.cname(cid), "phone": e.phone(cid), "product_id": pid, "product": _pname(ctx, pid),
                         "share": round(my * 100), "lift": round(lift, 1), "spent": round(s), "category": e.cat_name(e.cat_of(pid))})
    if len(rows) < 3:
        return []
    rows.sort(key=lambda r: -r["spent"])
    rows = rows[:40]
    texts = [{"customer_id": r["customer_id"], "text": f"{r['name']} عزیز، «{r['product']}» که همیشه می‌برید این هفته با هدیهٔ ویژه برای شماست. منتظرتان هستیم."} for r in rows if r["phone"]]
    gain = sum(r["spent"] for r in rows) * (30 / ctx.days) * 0.08
    return [Draft(kind="CUST_FAVORITE", dedupe_key=f"week:{ctx.today.isocalendar()[1]}", priority=3,
                  title=f"چیزی که هر مشتری را جذب می‌کند: {_fa(len(rows))} مشتری با «کالای عشق»",
                  body=(f"هر یک از این مشتریان یک کالا دارد که سهمش در سبد او {_fa(rows[0]['lift'],1)}× بیشتر از میانگین فروشگاه است "
                        f"(مثلاً «{rows[0]['name']}» ← «{rows[0]['product']}»، {_fa(rows[0]['share'])}٪ خریدش). پیام شخصی دربارهٔ همان کالا "
                        f"— نه تخفیف عمومی — چیزی است که او را برمی‌گرداند."),
                  evidence={"rows": rows}, actions=[_sms_action("پیامک شخصی دربارهٔ کالای موردعلاقهٔ هر مشتری", texts),
                                                    {"type": "personal_coupons", "label": "کوپن ۵٪ شخصی (۱۰ روز) برای همان کالا", "params": {"customers": [{"customer_id": r["customer_id"], "percent": 5, "days": 10} for r in rows if r["phone"]]}}],
                  expected_gain=gain, metric={"metric": "customer_sales", "customer_ids": [r["customer_id"] for r in rows], "window_days": 21})]


def a_cust_item_due(ctx: Ctx) -> list[Draft]:
    """Per-customer replenishment cycle of a consumable («هر ۲۰ روز یک بسته برنج») — the item is due, not just the visit."""
    e = ext(ctx)
    per: dict[tuple[int, int], list[date]] = defaultdict(list)
    for l in ctx.lines:
        if l["cust"]:
            per[(l["cust"], l["pid"])].append(l["at"].date())
    rows = []
    for (cid, pid), ds in per.items():
        ds = sorted(set(ds))
        if len(ds) < 4:
            continue
        gaps = [(b - a).days for a, b in zip(ds, ds[1:]) if (b - a).days > 0]
        if len(gaps) < 3:
            continue
        med = _median(gaps)
        mad = _median([abs(g - med) for g in gaps])
        if med < 3 or mad > med * 0.4:
            continue
        due = ds[-1] + timedelta(days=med)
        d = (due - ctx.today).days
        if -1 <= d <= 3:
            rows.append({"customer_id": cid, "name": e.cname(cid), "phone": e.phone(cid), "product_id": pid, "product": _pname(ctx, pid),
                         "cycle_days": med, "buys": len(ds), "due": due.isoformat(), "due_in": d, "margin": round(_avg_margin(ctx, pid))})
    if len(rows) < 2:
        return []
    rows.sort(key=lambda r: (-r["buys"], r["due_in"]))
    rows = rows[:40]
    texts = [{"customer_id": r["customer_id"], "text": f"{r['name']} عزیز، «{r['product']}» شما احتمالاً رو به اتمام است؛ تازه‌اش رسیده و برایتان کنار گذاشته‌ایم."} for r in rows if r["phone"]]
    return [Draft(kind="CUST_ITEM_DUE", dedupe_key=f"day:{ctx.today.isoformat()}", priority=2,
                  title=f"{_fa(len(rows))} کالای همیشگی مشتریان همین روزها تمام می‌شود",
                  body=(f"چرخهٔ خرید هر مشتری برای هر کالا محاسبه شد؛ مثلاً «{rows[0]['name']}» هر {_fa(rows[0]['cycle_days'])} روز «{rows[0]['product']}» می‌برد و نوبت بعدی {_fa(abs(rows[0]['due_in']))} روز {'دیگر' if rows[0]['due_in'] >= 0 else 'پیش'} است. "
                        f"پیام «کالای شما دارد تمام می‌شود» دقیقاً همان لحظه‌ای می‌رسد که به فکرش می‌افتد — و جلوی خرید از رقیب را می‌گیرد."),
                  evidence={"rows": rows}, actions=[_sms_action("پیامک «کالای همیشگی‌تان رو به اتمام است»", texts)],
                  expected_gain=sum(r["margin"] for r in rows) * 2.0,
                  metric={"metric": "customer_sales", "customer_ids": sorted({r["customer_id"] for r in rows}), "window_days": 14})]


def a_ticket_drop(ctx: Ctx) -> list[Draft]:
    """Regulars whose basket shrank ≥30 % in the last 4 weeks vs. their own history — they are splitting the shop."""
    e = ext(ctx)
    cut = ctx.since(28)
    rows = []
    for cid, invs in e.by_cust.items():
        old = [i["total"] for i in invs if i["at"] < cut]
        new = [i["total"] for i in invs if i["at"] >= cut]
        if len(old) < 5 or len(new) < 2:
            continue
        ao, an = sum(old) / len(old), sum(new) / len(new)
        if ao > 0 and an < ao * 0.7:
            rows.append({"customer_id": cid, "name": e.cname(cid), "phone": e.phone(cid), "avg_before": round(ao), "avg_now": round(an),
                         "drop_pct": round((1 - an / ao) * 100), "visits_now": len(new), "monthly_loss": round((ao - an) * len(new) * (30 / 28))})
    if len(rows) < 3:
        return []
    rows.sort(key=lambda r: -r["monthly_loss"])
    rows = rows[:30]
    loss = sum(r["monthly_loss"] for r in rows)
    texts = [{"customer_id": r["customer_id"], "text": f"{r['name']} عزیز، نظرتان برای ما مهم است؛ اگر چیزی کم داریم یا قیمتی مناسب نبود همین‌جا پاسخ دهید. با کد VIP۵ این هفته ۵٪ تخفیف دارید."} for r in rows if r["phone"]]
    return [Draft(kind="TICKET_DROP", dedupe_key=f"week:{ctx.today.isocalendar()[1]}", priority=2,
                  title=f"سبد {_fa(len(rows))} مشتری ثابت کوچک شده — بخشی از خریدشان جای دیگر می‌رود",
                  body=(f"این مشتریان هنوز می‌آیند اما میانگین فاکتورشان {_fa(rows[0]['drop_pct'])}٪ (و بیشتر) افت کرده؛ نشانهٔ کلاسیک «تقسیم سبد» با رقیب، قبل از ریزش کامل. "
                        f"فروش ماهانهٔ ازدست‌رفته: {_money(loss)}. یک پیام نظرخواهی + کوپن کوچک معمولاً دلیل را رو می‌کند (قیمت، موجودی، یا برخورد)."),
                  evidence={"rows": rows, "monthly_loss": round(loss)},
                  actions=[_sms_action("پیامک نظرخواهی + ۵٪ تخفیف", texts),
                           {"type": "personal_coupons", "label": "کوپن ۵٪ شخصی (۷ روز)", "params": {"customers": [{"customer_id": r["customer_id"], "percent": 5, "days": 7} for r in rows if r["phone"]]}}],
                  expected_gain=loss * 0.3, metric={"metric": "customer_sales", "customer_ids": [r["customer_id"] for r in rows], "window_days": 28})]


def a_freq_drop(ctx: Ctx) -> list[Draft]:
    """Visit gaps getting longer (last 3 gaps vs. earlier median) — early churn signal, weeks before CHURN fires."""
    e = ext(ctx)
    rows = []
    for cid, invs in e.by_cust.items():
        ds = sorted({i["at"].date() for i in invs})
        gaps = [(b - a).days for a, b in zip(ds, ds[1:]) if (b - a).days > 0]
        if len(gaps) < 6:
            continue
        base, recent = _median(gaps[:-3]), sum(gaps[-3:]) / 3
        silent = (ctx.today - ds[-1]).days
        if base >= 1 and recent >= base * 1.8 and silent <= base * 2.5:
            spent = sum(i["total"] for i in invs)
            rows.append({"customer_id": cid, "name": e.cname(cid), "phone": e.phone(cid), "gap_before": base, "gap_now": round(recent, 1),
                         "silent_days": silent, "monthly_sales": round(spent * (30 / ctx.days))})
    if len(rows) < 3:
        return []
    rows.sort(key=lambda r: -r["monthly_sales"])
    rows = rows[:30]
    at_risk = sum(r["monthly_sales"] for r in rows)
    texts = [{"customer_id": r["customer_id"], "text": f"{r['name']} عزیز، مدتی است کمتر می‌بینیمتان؛ کالاهای تازه رسیده و با کد BACK۱۰ این هفته ۱۰٪ تخفیف دارید."} for r in rows if r["phone"]]
    return [Draft(kind="FREQ_DROP", dedupe_key=f"week:{ctx.today.isocalendar()[1]}", priority=3,
                  title=f"{_fa(len(rows))} مشتری دارند کم‌کم فاصله می‌گیرند (قبل از ریزش)",
                  body=(f"فاصلهٔ خریدهای اخیر این مشتریان تقریباً دو برابر روال خودشان شده (مثلاً «{rows[0]['name']}»: هر {_fa(rows[0]['gap_before'])} روز → هر {_fa(rows[0]['gap_now'],1)} روز). "
                        f"در این مرحله برگرداندنشان بسیار ارزان‌تر از بعد از قطع کامل است. فروش ماهانهٔ در خطر: {_money(at_risk)}."),
                  evidence={"rows": rows, "monthly_sales_at_risk": round(at_risk)},
                  actions=[_sms_action("پیامک «دلتنگ شدیم» + ۱۰٪", texts),
                           {"type": "personal_coupons", "label": "کوپن ۱۰٪ شخصی (۷ روز)", "params": {"customers": [{"customer_id": r["customer_id"], "percent": 10, "days": 7} for r in rows if r["phone"]]}}],
                  expected_gain=at_risk * 0.15, metric={"metric": "customer_sales", "customer_ids": [r["customer_id"] for r in rows], "window_days": 28})]


def a_new_cust_2nd(ctx: Ctx) -> list[Draft]:
    """First-time customers of the last 30 days who have not come back: the second visit decides everything."""
    e = ext(ctx)
    rows = []
    for cid, first in e.first_visit.items():
        age = (ctx.now_utc - first).days
        if not (5 <= age <= 30):
            continue
        invs = e.by_cust.get(cid, [])
        if len(invs) != 1 or not e.phone(cid):
            continue
        pids = list(invs[0]["pids"])[:3]
        rows.append({"customer_id": cid, "name": e.cname(cid), "phone": e.phone(cid), "first_visit": first.date().isoformat(), "days_ago": age,
                     "ticket": round(invs[0]["total"]), "bought": [_pname(ctx, p) for p in pids]})
    if len(rows) < 3:
        return []
    rows.sort(key=lambda r: -r["ticket"])
    rows = rows[:40]
    texts = [{"customer_id": r["customer_id"], "text": f"{r['name']} عزیز، از اولین خریدتان سپاسگزاریم! برای دومین خرید ۱۰٪ تخفیف با کد WELCOME۱۰ تا ۷ روز آینده مهمان ما باشید."} for r in rows]
    avg = sum(r["ticket"] for r in rows) / len(rows)
    return [Draft(kind="NEW_CUST_2ND", dedupe_key=f"week:{ctx.today.isocalendar()[1]}", priority=2,
                  title=f"{_fa(len(rows))} مشتری جدید فقط یک بار آمده‌اند — خرید دوم را بسازید",
                  body=(f"مشتری‌ای که بار دوم برگردد، با احتمال چند برابر مشتری ثابت می‌شود. این {_fa(len(rows))} نفر در ۳۰ روز اخیر اولین خریدشان را کرده‌اند "
                        f"(میانگین فاکتور {_money(avg)}) و هنوز برنگشته‌اند؛ همه شماره داده‌اند. یک خوش‌آمد + کوپن یک‌هفته‌ای ارزان‌ترین جذب مشتری ثابت است."),
                  evidence={"rows": rows},
                  actions=[{"type": "personal_coupons", "label": "کوپن خوش‌آمد ۱۰٪ (۷ روز) + پیامک", "params": {"customers": [{"customer_id": r["customer_id"], "percent": 10, "days": 7, "text": t["text"]} for r, t in zip(rows, texts)]}}],
                  expected_gain=avg * len(rows) * 0.3 * 0.2, metric={"metric": "customer_sales", "customer_ids": [r["customer_id"] for r in rows], "window_days": 14})]


def a_offer_sensitive(ctx: Ctx) -> list[Draft]:
    """Who actually responds to coupons (and who buys anyway)? Stop discounting the second group."""
    e = ext(ctx)
    if len(e.coupons) < 10:
        return []
    issued: Counter = Counter()
    used: Counter = Counter()
    for c in e.coupons:
        if c.customer_id:
            issued[c.customer_id] += 1
            if c.status == "USED" or (c.used_count or 0) > 0:
                used[c.customer_id] += 1
    resp = [cid for cid, n in issued.items() if n >= 2 and used[cid] / n >= 0.5]
    deaf = [cid for cid, n in issued.items() if n >= 3 and used[cid] == 0 and len(e.by_cust.get(cid, [])) >= 4]
    if len(resp) + len(deaf) < 5:
        return []
    rows_r = _cust_rows(e, resp[:40], lambda c: {"issued": issued[c], "used": used[c]})
    rows_d = _cust_rows(e, deaf[:40], lambda c: {"issued": issued[c], "used": 0, "visits": len(e.by_cust.get(c, []))})
    return [Draft(kind="OFFER_SENSITIVE", dedupe_key=f"month:{ctx.today.strftime('%Y-%m')}", priority=3,
                  title=f"{_fa(len(resp))} مشتری به تخفیف واکنش نشان می‌دهند، {_fa(len(deaf))} نفر بدون تخفیف هم می‌خرند",
                  body=(f"از روی کوپن‌های صادرشده و استفاده‌شده: گروه اول ≥۵۰٪ کوپن‌ها را استفاده کرده‌اند (پیام تخفیف برایشان کار می‌کند)؛ گروه دوم با وجود ≥۳ کوپن هیچ‌کدام را استفاده نکرده و همچنان خرید می‌کنند "
                        f"— برای این‌ها تخفیف یعنی سود دورریخته؛ به‌جایش خبر کالای تازه یا تشکر شخصی بفرستید."),
                  evidence={"responders": rows_r, "non_responders": rows_d},
                  actions=[{"type": "tag_customers", "label": "علامت‌گذاری گروه‌ها در پروندهٔ مشتری", "params": {"tags": {"offer_responder": resp[:200], "offer_deaf": deaf[:200]}}}],
                  expected_gain=len(deaf) * 15000, metric={"metric": "customer_sales", "customer_ids": resp[:40], "window_days": 28})]


def a_category_gap(ctx: Ctx) -> list[Draft]:
    """Loyal customers who never buy a category that most similar customers do — they buy it next door."""
    e = ext(ctx)
    if not e.categories or len(e.by_cust) < 15:
        return []
    cust_cats: dict[int, Counter] = defaultdict(Counter)
    for cid, ls in e.cust_lines.items():
        for l in ls:
            c = e.cat_of(l["pid"])
            if c:
                cust_cats[cid][c] += l["sub"]
    loyal = [cid for cid, invs in e.by_cust.items() if len(invs) >= 8]
    if len(loyal) < 8:
        return []
    pen: Counter = Counter()
    for cid in loyal:
        for c in cust_cats[cid]:
            pen[c] += 1
    rows = []
    for c, n in pen.items():
        share = n / len(loyal)
        if share < 0.6:
            continue
        missing = [cid for cid in loyal if c not in cust_cats[cid]]
        if not missing:
            continue
        avg_cat = sum(cust_cats[cid][c] for cid in loyal if c in cust_cats[cid]) / n
        rows.append({"category_id": c, "category": e.cat_name(c), "penetration_pct": round(share * 100), "missing": _cust_rows(e, missing[:25]),
                     "missing_count": len(missing), "avg_spend": round(avg_cat), "monthly_opportunity": round(avg_cat * len(missing) * (30 / ctx.days))})
    if not rows:
        return []
    rows.sort(key=lambda r: -r["monthly_opportunity"])
    top = rows[0]
    texts = [{"customer_id": m["customer_id"], "text": f"{m['name']} عزیز، می‌دانستید {top['category']} ما هم تازه و با قیمت مناسب است؟ این هفته برای شما ۱۰٪ تخفیف روی همین بخش."} for m in top["missing"] if m["phone"]]
    return [Draft(kind="CATEGORY_GAP", dedupe_key=f"cat:{top['category_id']}:{ctx.today.strftime('%Y-%m')}", priority=3,
                  title=f"{_fa(top['missing_count'])} مشتری ثابت هرگز «{top['category']}» را از شما نمی‌خرند",
                  body=(f"{_fa(top['penetration_pct'])}٪ مشتریان ثابت از این دسته می‌خرند (به‌طور میانگین {_money(top['avg_spend'])} در دوره)، اما این {_fa(top['missing_count'])} نفر هرگز. "
                        f"یعنی این بخش سبدشان را از جای دیگری تأمین می‌کنند. یک معرفی هدفمند با تخفیف روی همان دسته، سبد کاملشان را به شما می‌آورد. فرصت ماهانه: {_money(top['monthly_opportunity'])}."),
                  evidence={"rows": rows[:5]}, actions=[_sms_action(f"معرفی «{top['category']}» به مشتریانی که آن را از شما نمی‌خرند", texts)],
                  expected_gain=top["monthly_opportunity"] * 0.1, metric={"metric": "customer_sales", "customer_ids": [m["customer_id"] for m in top["missing"]], "window_days": 28})]


def a_credit_risk(ctx: Ctx) -> list[Draft]:
    """Credit balances growing while payments lag — cap before it becomes a bad debt."""
    e = ext(ctx)
    now = ctx.now_utc
    last_pay: dict[int, datetime] = {}
    sales90: Counter = Counter()
    for en in e.ledger:
        if en.entry_type == "PAYMENT":
            last_pay[en.customer_id] = en.created_at
        elif en.entry_type == "CREDIT_SALE" and en.created_at >= ctx.since(90):
            sales90[en.customer_id] += _f(en.amount)
    rows = []
    for cid, (bal, at) in e.balances.items():
        if bal < 500_000:
            continue
        lp = last_pay.get(cid)
        silent = (now - lp).days if lp else 999
        c = e.customers.get(cid)
        limit = _f(c.credit_limit) if c else 0
        if silent >= 45 or (limit and bal > limit * 1.1):
            rows.append({"customer_id": cid, "name": e.cname(cid), "phone": e.phone(cid), "balance": round(bal), "days_since_payment": min(silent, 999),
                         "credit_sales_90d": round(sales90[cid]), "credit_limit": round(limit), "suggested_limit": round(max(bal * 0.8, 200_000) / 100_000) * 100_000})
    if not rows:
        return []
    rows.sort(key=lambda r: -r["balance"])
    rows = rows[:25]
    total = sum(r["balance"] for r in rows)
    return [Draft(kind="CREDIT_RISK", dedupe_key=f"week:{ctx.today.isocalendar()[1]}", priority=1 if total > 20_000_000 else 2,
                  title=f"{_money(total)} نسیه در معرض سوخت‌شدن ({_fa(len(rows))} حساب)",
                  body=(f"این حساب‌ها یا بیش از ۴۵ روز است پرداختی نداشته‌اند یا از سقف اعتبارشان گذشته‌اند و همچنان نسیه می‌برند. «{rows[0]['name']}»: {_money(rows[0]['balance'])}، آخرین پرداخت {_fa(rows[0]['days_since_payment'])} روز پیش. "
                        f"پیشنهاد: سقف اعتبار را روی ۸۰٪ ماندهٔ فعلی ببندید تا بدهی رشد نکند، و پیامک محترمانهٔ تسویه بفرستید."),
                  evidence={"rows": rows, "total": round(total)},
                  actions=[{"type": "set_credit_limit", "label": "بستن سقف اعتبار روی ۸۰٪ ماندهٔ فعلی", "params": {"customers": [{"customer_id": r["customer_id"], "limit": r["suggested_limit"]} for r in rows]}},
                           {"type": "debt_reminders", "label": "پیامک یادآوری بدهی", "params": {}}],
                  expected_gain=total * 0.05, metric={"metric": "receivables_collected", "window_days": 21})]


def a_anniversary(ctx: Ctx) -> list[Draft]:
    """First-purchase anniversary in the coming week — a free, memorable thank-you."""
    e = ext(ctx)
    rows = []
    for cid, first in e.first_visit.items():
        yrs = ctx.today.year - first.year
        if yrs < 1 or len(e.by_cust.get(cid, [])) < 3 or not e.phone(cid):
            continue
        try:
            ann = first.date().replace(year=ctx.today.year)
        except ValueError:
            continue
        d = (ann - ctx.today).days
        if 0 <= d <= 6:
            rows.append({"customer_id": cid, "name": e.cname(cid), "phone": e.phone(cid), "years": yrs, "date": ann.isoformat(), "in_days": d,
                         "visits_window": len(e.by_cust.get(cid, []))})
    if len(rows) < 2:
        return []
    texts = [{"customer_id": r["customer_id"], "text": f"{r['name']} عزیز، {_fa(r['years'])} سال از اولین خریدتان از ما می‌گذرد. سپاس که هستید؛ این هفته یک هدیهٔ کوچک پای صندوق منتظرتان است."} for r in rows]
    return [Draft(kind="ANNIVERSARY", dedupe_key=f"week:{ctx.today.isocalendar()[1]}", priority=4,
                  title=f"سالگرد اولین خرید {_fa(len(rows))} مشتری در این هفته است",
                  body=(f"کاری که هیچ رقیبی نمی‌کند: «{rows[0]['name']}» {_fa(rows[0]['years'])} سال پیش در همین هفته اولین بار از شما خرید کرد. یک پیام تشکر و یک هدیهٔ کوچک، "
                        f"وفاداری می‌سازد و هزینه‌اش تقریباً صفر است."),
                  evidence={"rows": rows}, actions=[_sms_action("پیامک تبریک سالگرد + هدیهٔ کوچک", texts)],
                  expected_gain=len(rows) * 40_000, metric={"metric": "customer_sales", "customer_ids": [r["customer_id"] for r in rows], "window_days": 21})]


def a_bulk_buyer(ctx: Ctx) -> list[Draft]:
    """Customers who repeatedly buy a product in wholesale quantities (small shops / large families) → a standing deal."""
    e = ext(ctx)
    typ: dict[int, list[float]] = defaultdict(list)
    for l in ctx.lines:
        typ[l["pid"]].append(l["qty"])
    med = {p: _median(q) for p, q in typ.items() if len(q) >= 10}
    hits: dict[int, dict[int, list[float]]] = defaultdict(lambda: defaultdict(list))
    for l in ctx.lines:
        m = med.get(l["pid"])
        if l["cust"] and m and l["qty"] >= max(6, m * 5):
            hits[l["cust"]][l["pid"]].append(l["qty"])
    rows = []
    for cid, d in hits.items():
        for pid, qs in d.items():
            if len(qs) >= 3:
                rows.append({"customer_id": cid, "name": e.cname(cid), "phone": e.phone(cid), "product_id": pid, "product": _pname(ctx, pid),
                             "times": len(qs), "avg_qty": round(sum(qs) / len(qs), 1), "typical_qty": med[pid], "margin": round(_avg_margin(ctx, pid))})
    if len(rows) < 2:
        return []
    rows.sort(key=lambda r: -(r["times"] * r["avg_qty"] * r["margin"]))
    rows = rows[:25]
    texts = [{"customer_id": r["customer_id"], "text": f"{r['name']} عزیز، برای خرید عمدهٔ «{r['product']}» قیمت ویژه برایتان در نظر گرفته‌ایم؛ قبل از خرید بعدی به ما خبر دهید تا آماده باشد."} for r in rows if r["phone"]]
    gain = sum(r["avg_qty"] * r["margin"] * r["times"] for r in rows) * (30 / ctx.days) * 0.3
    return [Draft(kind="BULK_BUYER", dedupe_key=f"month:{ctx.today.strftime('%Y-%m')}", priority=3,
                  title=f"{_fa(len(rows))} خریدار عمده در میان مشتریان شما پنهان است",
                  body=(f"«{rows[0]['name']}» {_fa(rows[0]['times'])} بار «{rows[0]['product']}» را به‌طور میانگین {_fa(rows[0]['avg_qty'],1)} عدد برده (معمول: {_fa(rows[0]['typical_qty'])}). "
                        f"این‌ها احتمالاً مغازه‌دار یا خانوادهٔ پرجمعیت‌اند؛ یک قرار «قیمت عمده + رزرو» آن‌ها را از بنکدار جدا می‌کند و حجم را چند برابر."),
                  evidence={"rows": rows}, actions=[_sms_action("پیشنهاد قیمت عمده + رزرو کالا", texts)],
                  expected_gain=gain, metric={"metric": "customer_sales", "customer_ids": sorted({r["customer_id"] for r in rows}), "window_days": 28})]


def a_threshold_upsell(ctx: Ctx) -> list[Draft]:
    """A large share of baskets sits just below a round amount → «بالای X تومان، Y هدیه» lifts them over."""
    totals = [inv["total"] for inv in ctx.invoices.values() if inv["total"] > 0]
    if len(totals) < 80:
        return []
    med = _median(totals)
    step = 50_000 if med < 300_000 else 100_000 if med < 1_000_000 else 500_000
    thr = math.ceil(med / step) * step
    near = [t for t in totals if thr * 0.8 <= t < thr]
    share = len(near) / len(totals)
    if share < 0.15:
        return []
    uplift = sum(thr - t for t in near)
    rate = _profit_rate(ctx)
    gain = uplift * rate * 0.35 * (30 / ctx.days)
    return [Draft(kind="THRESHOLD_UPSELL", dedupe_key=f"thr:{thr}", priority=3,
                  title=f"{_fa(share*100)}٪ فاکتورها کمی زیر {_money(thr)} می‌مانند",
                  body=(f"میانهٔ فاکتور {_money(med)} است و {_fa(len(near))} فاکتور بین {_fa(80)}٪ تا ۱۰۰٪ آستانهٔ {_money(thr)} بسته شده‌اند. یک پیشنهاد سادهٔ «خرید بالای {_money(thr)} = ۳٪ تخفیف یا یک کالای هدیه» "
                        f"معمولاً یک‌سوم این فاکتورها را از خط رد می‌کند؛ جمع فاصله تا آستانه {_money(uplift)} است."),
                  evidence={"threshold": thr, "median_ticket": round(med), "near_count": len(near), "invoices": len(totals), "gap_sum": round(uplift)},
                  actions=[{"type": "threshold_campaign", "label": f"کمپین «بالای {_money(thr)} = ۳٪ تخفیف» (۳۰ روز)", "params": {"percent": 3, "min_purchase": thr, "days": 30}}],
                  expected_gain=gain, metric={"metric": "avg_basket_size", "window_days": 28})]


# =============================================================================
# STOCK & FORECAST
# =============================================================================
def _profit_rate(ctx: Ctx) -> float:
    s = sum(l["sub"] for l in ctx.lines)
    return (sum(l["profit"] for l in ctx.lines) / s) if s > 0 else 0.15


def a_reorder_point(ctx: Ctx) -> list[Draft]:
    """min_stock_alert far from the velocity-based optimum (lead-time 3 d + safety) — both directions cost money."""
    e = ext(ctx)
    rows = []
    for pid, v in e.velocity28.items():
        p = ctx.products.get(pid)
        if not p or v * 28 < 8:
            continue
        opt = math.ceil(v * 5)   # 3-day lead + 2-day safety
        cur = int(p.min_stock_alert or 0)
        if cur == 0 or cur < opt * 0.5 or cur > opt * 3:
            rows.append({"product_id": pid, "name": p.name, "velocity_per_day": round(v, 2), "current_min": cur, "suggested_min": opt,
                         "direction": "up" if cur < opt else "down", "margin": round(_avg_margin(ctx, pid))})
    if len(rows) < 3:
        return []
    rows.sort(key=lambda r: -r["velocity_per_day"] * r["margin"])
    rows = rows[:40]
    ups = [r for r in rows if r["direction"] == "up"]
    gain = sum(r["velocity_per_day"] * r["margin"] for r in ups) * 3   # ≈3 avoided empty days / month each
    return [Draft(kind="REORDER_POINT", dedupe_key=f"month:{ctx.today.strftime('%Y-%m')}", priority=2,
                  title=f"نقطهٔ سفارش {_fa(len(rows))} کالا با سرعت فروش واقعی‌شان نمی‌خواند",
                  body=(f"حداقل موجودی باید ≈ ۵ روز فروش باشد (۳ روز تا رسیدن جنس + ۲ روز ایمنی). {_fa(len(ups))} کالا هشدارشان خیلی دیر می‌آید (یا اصلاً تنظیم نشده) و {_fa(len(rows)-len(ups))} کالا سرمایه را بی‌دلیل قفل کرده‌اند. "
                        f"مثلاً «{rows[0]['name']}» روزی {_fa(rows[0]['velocity_per_day'],1)} عدد می‌فروشد؛ حداقل فعلی {_fa(rows[0]['current_min'])} ← پیشنهادی {_fa(rows[0]['suggested_min'])}."),
                  evidence={"rows": rows},
                  actions=[{"type": "set_min_stock_bulk", "label": "به‌روزرسانی هوشمند حداقل موجودی همهٔ این کالاها", "params": {"items": [{"product_id": r["product_id"], "min_stock": r["suggested_min"]} for r in rows]}}],
                  expected_gain=gain, metric={"metric": "availability", "product_id": rows[0]["product_id"], "window_days": 28, "margin_per_day": round(rows[0]["velocity_per_day"] * rows[0]["margin"])})]


def a_overstock(ctx: Ctx) -> list[Draft]:
    """Cover > 90 days on items that still sell — stop ordering, free the cash."""
    e = ext(ctx)
    rows = []
    for pid, st in e.stock_by_pid.items():
        v = e.velocity28.get(pid, 0)
        if v <= 0:
            continue
        cover = st / v
        cap = e.capital_by_pid[pid]
        if cover > 90 and cap > 300_000:
            rows.append({"product_id": pid, "name": _pname(ctx, pid), "stock": st, "velocity_per_day": round(v, 2), "days_cover": round(cover),
                         "capital": round(cap), "excess_capital": round(cap * (1 - 45 / cover))})
    if not rows:
        return []
    rows.sort(key=lambda r: -r["excess_capital"])
    rows = rows[:30]
    excess = sum(r["excess_capital"] for r in rows)
    return [Draft(kind="OVERSTOCK", dedupe_key=f"month:{ctx.today.strftime('%Y-%m')}", priority=3,
                  title=f"{_money(excess)} سرمایهٔ اضافی در {_fa(len(rows))} کالای پرموجودی",
                  body=(f"این کالاها می‌فروشند، اما موجودی‌شان بیش از ۹۰ روز فروش است (مثلاً «{rows[0]['name']}»: {_fa(rows[0]['days_cover'])} روز). "
                        f"نیازی به حراج نیست؛ فقط سفارش بعدی را نگیرید. با پوشش ۴۵ روزه، {_money(excess)} نقد آزاد می‌شود."),
                  evidence={"rows": rows, "excess_capital": round(excess)},
                  actions=[{"type": "note", "label": "ثبت در فهرست «سفارش نگیر» برای خرید بعدی", "params": {}}],
                  expected_gain=excess * 0.03, metric={"metric": "product_profit", "product_id": rows[0]["product_id"], "window_days": 28})]


def a_stockout_history(ctx: Ctx) -> list[Draft]:
    """Products that went to zero ≥ 3 times in the window: the order quantity is structurally too small."""
    e = ext(ctx)
    bal: dict[int, float] = defaultdict(float)
    episodes: Counter = Counter()
    for at, pid, typ, q in sorted(e.movements, key=lambda m: m[0]):
        before = bal[pid]
        bal[pid] += _f(q)
        if before > 0 and bal[pid] <= 0:
            episodes[pid] += 1
    rows = []
    for pid, n in episodes.items():
        v = e.velocity28.get(pid, 0)
        if n >= 3 and v * 28 >= 10:
            m = _avg_margin(ctx, pid)
            rows.append({"product_id": pid, "name": _pname(ctx, pid), "stockouts": n, "velocity_per_day": round(v, 2), "margin": round(m),
                         "suggested_order": math.ceil(v * 21), "lost_per_episode": round(v * 2 * m)})
    if not rows:
        return []
    rows.sort(key=lambda r: -r["stockouts"] * r["lost_per_episode"])
    rows = rows[:20]
    lost = sum(r["stockouts"] * r["lost_per_episode"] for r in rows) * (30 / ctx.days)
    return [Draft(kind="STOCKOUT_HISTORY", dedupe_key=f"month:{ctx.today.strftime('%Y-%m')}", priority=2,
                  title=f"{_fa(len(rows))} کالا مرتب تمام می‌شوند — مقدار سفارش کم است",
                  body=(f"«{rows[0]['name']}» در این دوره {_fa(rows[0]['stockouts'])} بار به صفر رسیده؛ هر بار ≈ ۲ روز قفسهٔ خالی یعنی {_money(rows[0]['lost_per_episode'])} سود ازدست‌رفته. "
                        f"مسئله سرعت هشدار نیست، اندازهٔ سفارش است: پیشنهاد ۳ هفته پوشش در هر سفارش. زیان ماهانهٔ فعلی: {_money(lost)}."),
                  evidence={"rows": rows},
                  actions=[{"type": "reorder_note", "label": "افزودن به لیست سفارش با مقدار پیشنهادی", "params": {"products": [r["product_id"] for r in rows], "qty": rows[0]["suggested_order"]}}],
                  expected_gain=lost * 0.6, metric={"metric": "availability", "product_id": rows[0]["product_id"], "window_days": 28, "margin_per_day": round(rows[0]["velocity_per_day"] * rows[0]["margin"])})]


def _trend_rows(ctx: Ctx, up: bool):
    e = ext(ctx)
    rows = []
    for pid in e.velocity28:
        w = e.weekly_units(pid, 6)
        if sum(w) < 12:
            continue
        s = _slope(w)
        if (up and s >= 0.12) or (not up and s <= -0.12):
            rows.append({"product_id": pid, "name": _pname(ctx, pid), "weekly": [round(x, 1) for x in w], "trend_pct_per_week": round(s * 100),
                         "stock": e.stock_by_pid.get(pid, 0), "margin": round(_avg_margin(ctx, pid)), "next_week": round(max(0.0, w[-1] * (1 + s)), 1)})
    rows.sort(key=lambda r: -abs(r["trend_pct_per_week"]) * r["margin"] * sum(r["weekly"]))
    return rows[:20]


def a_trend_up(ctx: Ctx) -> list[Draft]:
    rows = _trend_rows(ctx, True)
    if len(rows) < 2:
        return []
    short = [r for r in rows if r["stock"] < r["next_week"] * 1.5]
    gain = sum(r["next_week"] * r["margin"] for r in short) * 2
    return [Draft(kind="TREND_UP", dedupe_key=f"week:{ctx.today.isocalendar()[1]}", priority=2 if short else 3,
                  title=f"{_fa(len(rows))} کالا در حال اوج‌گرفتن‌اند — {_fa(len(short))} تا موجودی کافی ندارند",
                  body=(f"فروش هفتگی «{rows[0]['name']}» شش هفته است هر هفته ≈{_fa(rows[0]['trend_pct_per_week'])}٪ رشد می‌کند ({'، '.join(_fa(x) for x in rows[0]['weekly'])}). "
                        f"پیش‌بینی هفتهٔ بعد: {_fa(rows[0]['next_week'],1)} عدد؛ موجودی {_fa(rows[0]['stock'])}. سفارش را بر اساس روند بگیرید، نه میانگین."),
                  evidence={"rows": rows},
                  actions=[{"type": "reorder_note", "label": "سفارش کالاهای رو به رشد (۲ هفته با احتساب روند)", "params": {"products": [r["product_id"] for r in short or rows]}}],
                  expected_gain=gain, metric={"metric": "product_units", "product_id": rows[0]["product_id"], "window_days": 14})]


def a_trend_down(ctx: Ctx) -> list[Draft]:
    rows = _trend_rows(ctx, False)
    if len(rows) < 2:
        return []
    e = ext(ctx)
    heavy = [r for r in rows if r["stock"] > max(1.0, r["next_week"]) * 6]
    cap = sum(e.capital_by_pid.get(r["product_id"], 0) for r in heavy)
    return [Draft(kind="TREND_DOWN", dedupe_key=f"week:{ctx.today.isocalendar()[1]}", priority=3,
                  title=f"{_fa(len(rows))} کالا دارند افت می‌کنند — سفارش بعدی را کوچک کنید",
                  body=(f"فروش «{rows[0]['name']}» هر هفته ≈{_fa(abs(rows[0]['trend_pct_per_week']))}٪ کم می‌شود ({'، '.join(_fa(x) for x in rows[0]['weekly'])}). "
                        f"{_fa(len(heavy))} کالا با این روند بیش از ۶ هفته موجودی دارند ({_money(cap)} سرمایه). قبل از راکدشدن، سفارش را نصف کنید یا با کالای پرفروش باندل کنید."),
                  evidence={"rows": rows, "heavy_capital": round(cap)},
                  actions=[{"type": "note", "label": "یادداشت «سفارش نصف» برای خرید بعدی", "params": {}}],
                  expected_gain=cap * 0.05, metric={"metric": "product_profit", "product_id": rows[0]["product_id"], "window_days": 28})]


def a_expiry_risk_buy(ctx: Ctx) -> list[Draft]:
    """Batches that will expire before they can sell at the current pace — the waste is already decided unless you act now."""
    e = ext(ctx)
    rows = []
    for b in e.active_batches:
        if not b.expiry_date:
            continue
        v = e.velocity28.get(b.product_id, 0)
        left = (b.expiry_date - ctx.today).days
        if left <= 14 or left > 120:
            continue   # ≤14 d is EXPIRY_LADDER's job
        qty = _f(b.current_qty)
        sellable = v * left
        if v <= 0 or qty > sellable * 1.3:
            waste = qty - sellable
            rows.append({"batch_id": b.id, "product_id": b.product_id, "name": _pname(ctx, b.product_id), "qty": qty, "days_left": left,
                         "velocity_per_day": round(v, 2), "will_sell": round(sellable), "will_expire": round(max(0.0, waste)), "loss": round(max(0.0, waste) * _f(b.buy_price))})
    rows = [r for r in rows if r["loss"] > 50_000]
    if not rows:
        return []
    rows.sort(key=lambda r: -r["loss"])
    rows = rows[:25]
    loss = sum(r["loss"] for r in rows)
    return [Draft(kind="EXPIRY_RISK_BUY", dedupe_key=f"week:{ctx.today.isocalendar()[1]}", priority=2,
                  title=f"{_money(loss)} کالا با این سرعت فروش قبل از فروش منقضی می‌شود",
                  body=(f"«{rows[0]['name']}»: {_fa(rows[0]['qty'])} عدد، {_fa(rows[0]['days_left'])} روز تا انقضا، روزی {_fa(rows[0]['velocity_per_day'],1)} عدد فروش → فقط {_fa(rows[0]['will_sell'])} عدد می‌فروشد و {_fa(rows[0]['will_expire'])} عدد دور می‌رود. "
                        f"هنوز زود است و می‌شود با تخفیف ملایم، جابه‌جایی به قفسهٔ چشم‌گیر یا برگرداندن به تأمین‌کننده جلویش را گرفت."),
                  evidence={"rows": rows, "loss": round(loss)},
                  actions=[{"type": "markdown_ladder", "label": "تخفیف ملایم ۱۰٪ اکنون، ۲۰٪ در دو هفته", "params": {"batch_id": rows[0]["batch_id"], "ladder": [{"from_day": 0, "percent": 10}, {"from_day": 14, "percent": 20}]}},
                           {"type": "note", "label": "یادداشت «برگشت به تأمین‌کننده» برای انباردار", "params": {}}],
                  expected_gain=loss * 0.5, metric={"metric": "product_units", "product_id": rows[0]["product_id"], "window_days": 21})]


def a_waste_pattern(ctx: Ctx) -> list[Draft]:
    """Recurring WASTE movements on the same products — order less, more often."""
    e = ext(ctx)
    w: Counter = Counter()
    n: Counter = Counter()
    for at, pid, typ, q in e.movements:
        if typ == "WASTE":
            w[pid] += abs(_f(q))
            n[pid] += 1
    rows = []
    for pid, q in w.items():
        sold = sum(l["qty"] for l in ctx.lines if l["pid"] == pid)
        if n[pid] >= 2 and q >= max(3, sold * 0.05):
            cost = q * (sum(l["cost"] * l["qty"] for l in ctx.lines if l["pid"] == pid) / max(1, sold) if sold else 0)
            rows.append({"product_id": pid, "name": _pname(ctx, pid), "waste_qty": q, "waste_events": n[pid], "sold": sold, "waste_pct": round(q / max(1, sold + q) * 100), "cost": round(cost)})
    if not rows:
        return []
    rows.sort(key=lambda r: -r["cost"])
    rows = rows[:20]
    cost = sum(r["cost"] for r in rows) * (30 / ctx.days)
    return [Draft(kind="WASTE_PATTERN", dedupe_key=f"month:{ctx.today.strftime('%Y-%m')}", priority=2,
                  title=f"{_money(cost)} ضایعات ماهانهٔ تکراری در {_fa(len(rows))} کالا",
                  body=(f"«{rows[0]['name']}» {_fa(rows[0]['waste_events'])} بار ضایعات ثبت شده ({_fa(rows[0]['waste_pct'])}٪ از کل ورودی). ضایعات تکراری یعنی اندازهٔ سفارش با فروش نمی‌خواند؛ "
                        f"سفارش کوچک‌تر و مکررتر، یا حداقل موجودی پایین‌تر، بیشتر این هزینه را حذف می‌کند."),
                  evidence={"rows": rows, "monthly_cost": round(cost)},
                  actions=[{"type": "set_min_stock_bulk", "label": "کاهش حداقل موجودی این کالاها به ۳ روز فروش", "params": {"items": [{"product_id": r["product_id"], "min_stock": max(1, math.ceil(e.velocity28.get(r["product_id"], 0) * 3))} for r in rows]}}],
                  expected_gain=cost * 0.5, metric={"metric": "product_profit", "product_id": rows[0]["product_id"], "window_days": 28})]


def a_shrinkage(ctx: Ctx) -> list[Draft]:
    """Stocktake shortages concentrated on specific products → theft / mis-scan / unrecorded waste."""
    e = ext(ctx)
    short: Counter = Counter()
    cnt: Counter = Counter()
    for it in e.stocktake_diffs:
        if _f(it.difference) < 0:
            short[it.product_id] += -_f(it.difference)
            cnt[it.product_id] += 1
    if not short:
        return []
    rows = []
    for pid, q in short.items():
        cost = q * (next((l["cost"] for l in ctx.lines if l["pid"] == pid), 0) or 0)
        rows.append({"product_id": pid, "name": _pname(ctx, pid), "missing_qty": q, "counts": cnt[pid], "cost": round(cost), "category": e.cat_name(e.cat_of(pid))})
    rows.sort(key=lambda r: -r["cost"])
    rows = rows[:20]
    total = sum(r["cost"] for r in rows)
    if total < 200_000:
        return []
    cats = Counter(r["category"] for r in rows).most_common(1)[0]
    return [Draft(kind="SHRINKAGE", dedupe_key=f"month:{ctx.today.strftime('%Y-%m')}", priority=2,
                  title=f"{_money(total)} کسری انبارگردانی، متمرکز روی {_fa(len(rows))} کالا",
                  body=(f"در انبارگردانی‌های ۶ ماه اخیر «{rows[0]['name']}» {_fa(rows[0]['missing_qty'])} عدد کم آمده ({_fa(rows[0]['counts'])} بار). بیشترین کسری در دستهٔ «{cats[0]}» است. "
                        f"کسری تکراری روی همان کالا معمولاً یا سرقت قفسه است، یا اسکن نکردن پای صندوق، یا ضایعات ثبت‌نشده — هر سه با شمارش هفتگی همین چند قلم پیدا می‌شود."),
                  evidence={"rows": rows, "total_cost": round(total)},
                  actions=[{"type": "note", "label": "برنامهٔ شمارش هفتگی این کالاها (یادداشت انباردار)", "params": {}}],
                  expected_gain=total / 6 * 0.5, metric={"metric": "product_profit", "product_id": rows[0]["product_id"], "window_days": 28})]


def a_category_turns(ctx: Ctx) -> list[Draft]:
    """Inventory turns per category vs. the store — the slow categories eat the shelf."""
    e = ext(ctx)
    if not e.categories:
        return []
    cogs: Counter = Counter()
    cap: Counter = Counter()
    for l in ctx.lines:
        cogs[e.cat_of(l["pid"])] += l["cost"] * l["qty"]
    for pid, c in e.capital_by_pid.items():
        cap[e.cat_of(pid)] += c
    tot_c, tot_k = sum(cogs.values()), sum(cap.values())
    if tot_k <= 0 or tot_c <= 0:
        return []
    store_turns = tot_c / tot_k * (365 / ctx.days)
    rows = []
    for c, k in cap.items():
        if k < 1_000_000:
            continue
        t = cogs[c] / k * (365 / ctx.days)
        rows.append({"category_id": c, "category": e.cat_name(c), "capital": round(k), "turns_per_year": round(t, 1), "store_turns": round(store_turns, 1), "vs_store_pct": round((t / store_turns - 1) * 100) if store_turns else 0})
    slow = [r for r in rows if r["turns_per_year"] < store_turns * 0.5]
    if not slow:
        return []
    slow.sort(key=lambda r: -r["capital"])
    excess = sum(r["capital"] * 0.4 for r in slow)
    return [Draft(kind="CATEGORY_TURNS", dedupe_key=f"month:{ctx.today.strftime('%Y-%m')}", priority=3,
                  title=f"دستهٔ «{slow[0]['category']}» {_fa(abs(slow[0]['vs_store_pct']))}٪ کندتر از کل فروشگاه می‌چرخد",
                  body=(f"گردش سالانهٔ موجودی فروشگاه ≈{_fa(store_turns,1)} بار است؛ «{slow[0]['category']}» فقط {_fa(slow[0]['turns_per_year'],1)} بار با {_money(slow[0]['capital'])} سرمایه. "
                        f"با کم‌کردن عمق این دسته‌ها (کمتر بخرید، تنوع کمتر) حدود {_money(excess)} آزاد می‌شود که در دسته‌های تندگردش سود بیشتری می‌سازد."),
                  evidence={"rows": sorted(rows, key=lambda r: r["turns_per_year"]), "slow": slow},
                  actions=[{"type": "note", "label": "بازنگری عمق خرید این دسته‌ها", "params": {}}],
                  expected_gain=excess * 0.02, metric={"metric": "avg_basket_size", "window_days": 28})]


def a_fifo_break(ctx: Ctx) -> list[Draft]:
    """Older batch still on hand while a newer batch of the same product is being sold → rotation is broken."""
    e = ext(ctx)
    by_pid: dict[int, list[ProductBatch]] = defaultdict(list)
    for b in e.active_batches:
        if b.expiry_date:
            by_pid[b.product_id].append(b)
    sold_batches = Counter(l["batch"] for l in ctx.lines if l["at"] >= ctx.since(14) and l["batch"])
    rows = []
    for pid, bs in by_pid.items():
        if len(bs) < 2:
            continue
        bs.sort(key=lambda b: b.expiry_date)
        oldest, newer = bs[0], bs[1:]
        if sold_batches.get(oldest.id, 0) == 0 and any(sold_batches.get(b.id, 0) > 0 for b in newer):
            rows.append({"product_id": pid, "name": _pname(ctx, pid), "old_batch": oldest.batch_number, "old_qty": _f(oldest.current_qty), "old_expiry": oldest.expiry_date.isoformat(),
                         "days_left": (oldest.expiry_date - ctx.today).days, "value": round(_f(oldest.current_qty) * _f(oldest.buy_price))})
    if not rows:
        return []
    rows.sort(key=lambda r: r["days_left"])
    rows = rows[:25]
    val = sum(r["value"] for r in rows)
    return [Draft(kind="FIFO_BREAK", dedupe_key=f"week:{ctx.today.isocalendar()[1]}", priority=2 if rows[0]["days_left"] < 30 else 3,
                  title=f"{_fa(len(rows))} کالا از بچ جدید فروخته می‌شوند و بچ قدیمی‌ترشان دست‌نخورده مانده",
                  body=(f"«{rows[0]['name']}»: بچ {rows[0]['old_batch']} با {_fa(rows[0]['old_qty'])} عدد و {_fa(rows[0]['days_left'])} روز تا انقضا هیچ فروشی در ۱۴ روز اخیر نداشته، در حالی که بچ تازه‌تر فروش می‌رود. "
                        f"یعنی جنس تازه جلوی قفسه است. یک چیدمان دوباره (قدیمی جلو) {_money(val)} کالا را از انقضا نجات می‌دهد."),
                  evidence={"rows": rows, "value": round(val)},
                  actions=[{"type": "shelf_note", "label": "یادداشت چیدمان FIFO برای انباردار", "params": {"products": [r["product_id"] for r in rows]}}],
                  expected_gain=val * 0.4, metric={"metric": "product_units", "product_id": rows[0]["product_id"], "window_days": 14})]


def a_supplier_lead(ctx: Ctx) -> list[Draft]:
    """Each supplier has a delivery rhythm; products that will run out before the supplier's next visit need an early call."""
    e = ext(ctx)
    visits: dict[int, list[date]] = defaultdict(list)
    prods: dict[int, set] = defaultdict(set)
    for b in e.recent_batches:
        if b.supplier_id and b.received_at:
            visits[b.supplier_id].append(b.received_at.date())
            prods[b.supplier_id].add(b.product_id)
    rows = []
    for sid, ds in visits.items():
        ds = sorted(set(ds))
        gaps = [(b - a).days for a, b in zip(ds, ds[1:]) if (b - a).days > 0]
        if len(gaps) < 3:
            continue
        cyc = _median(gaps)
        nxt = ds[-1] + timedelta(days=cyc)
        wait = max(0, (nxt - ctx.today).days)
        risky = []
        for pid in prods[sid]:
            v = e.velocity28.get(pid, 0)
            st = e.stock_by_pid.get(pid, 0)
            if v > 0 and st / v < wait + 2:
                risky.append({"product_id": pid, "name": _pname(ctx, pid), "days_cover": round(st / v, 1), "need": math.ceil(v * (wait + cyc) - st)})
        if risky:
            rows.append({"supplier_id": sid, "supplier": e.suppliers.get(sid, str(sid)), "cycle_days": cyc, "last_visit": ds[-1].isoformat(), "next_visit": nxt.isoformat(), "wait_days": wait, "risky": sorted(risky, key=lambda r: r["days_cover"])[:15]})
    if not rows:
        return []
    rows.sort(key=lambda r: -len(r["risky"]))
    top = rows[0]
    gain = sum(_avg_margin(ctx, r["product_id"]) * e.velocity28.get(r["product_id"], 0) for r in top["risky"]) * 4
    return [Draft(kind="SUPPLIER_LEAD", dedupe_key=f"sup:{top['supplier_id']}:{ctx.today.isocalendar()[1]}", priority=2,
                  title=f"{_fa(len(top['risky']))} کالای «{top['supplier']}» قبل از نوبت بعدی‌اش تمام می‌شود",
                  body=(f"این تأمین‌کننده معمولاً هر {_fa(top['cycle_days'])} روز جنس می‌آورد؛ نوبت بعدی ≈ {_fa(top['wait_days'])} روز دیگر. اما «{top['risky'][0]['name']}» فقط {_fa(top['risky'][0]['days_cover'],1)} روز موجودی دارد. "
                        f"یک تماس زودتر از موعد (یا سفارش تلفنی) ارزان‌تر از {_fa(top['wait_days'])} روز قفسهٔ خالی است."),
                  evidence={"rows": rows[:5]},
                  actions=[{"type": "reorder_note", "label": f"افزودن به لیست سفارش «{top['supplier']}»", "params": {"products": [r["product_id"] for r in top["risky"]]}}],
                  expected_gain=gain, metric={"metric": "availability", "product_id": top["risky"][0]["product_id"], "window_days": 14, "margin_per_day": round(_avg_margin(ctx, top["risky"][0]["product_id"]) * e.velocity28.get(top["risky"][0]["product_id"], 0))})]


def a_seasonal_yoy(ctx: Ctx) -> list[Draft]:
    """Same Jalali month last year: products that spiked then (≥ 1.8× their yearly average) → stock up before it repeats."""
    db = ctx.db
    since = ctx.now_utc - timedelta(days=400)
    rows_db = db.execute(select(InvoiceItem.product_id, Invoice.created_at, InvoiceItem.qty).join(Invoice, Invoice.id == InvoiceItem.invoice_id)
                         .where(Invoice.status == PAID, Invoice.created_at >= since, Invoice.created_at < ctx.since(300))).all()
    if len(rows_db) < 200:
        return []
    jy, jm, _ = to_jalali(datetime.combine(ctx.today, datetime.min.time()) + timedelta(days=20))   # the month we are about to enter / in
    per: dict[int, Counter] = defaultdict(Counter)
    for pid, at, q in rows_db:
        y, m, _ = to_jalali(at + timedelta(hours=3, minutes=30))
        per[pid][m] += _f(q)
    e = ext(ctx)
    rows = []
    for pid, months in per.items():
        if len(months) < 4:
            continue
        avg = sum(months.values()) / len(months)
        peak = months.get(jm, 0)
        if avg >= 3 and peak >= avg * 1.8:
            v = e.velocity28.get(pid, 0)
            rows.append({"product_id": pid, "name": _pname(ctx, pid), "month": JMONTH[jm - 1], "last_year_units": round(peak), "avg_month_units": round(avg, 1), "lift": round(peak / avg, 1),
                         "current_velocity_per_day": round(v, 2), "stock": e.stock_by_pid.get(pid, 0), "margin": round(_avg_margin(ctx, pid))})
    if len(rows) < 2:
        return []
    rows.sort(key=lambda r: -r["last_year_units"] * r["margin"])
    rows = rows[:25]
    gain = sum((r["last_year_units"] - r["avg_month_units"]) * r["margin"] for r in rows) * 0.4
    return [Draft(kind="SEASONAL_YOY", dedupe_key=f"jm:{jy}-{jm}", priority=2,
                  title=f"پارسال در {rows[0]['month']} فروش {_fa(len(rows))} کالا جهش داشت — آماده شوید",
                  body=(f"«{rows[0]['name']}» در {rows[0]['month']} پارسال {_fa(rows[0]['last_year_units'])} عدد فروخت، {_fa(rows[0]['lift'],1)}× میانگین ماهانه‌اش. موجودی فعلی {_fa(rows[0]['stock'])} عدد است. "
                        f"الگوی فصلی تکرار می‌شود؛ سفارش پیش از موج، فروش را می‌گیرد و بعد از موج فقط جنس مانده می‌آورد."),
                  evidence={"rows": rows},
                  actions=[{"type": "reorder_note", "label": "افزودن کالاهای فصلی به لیست سفارش", "params": {"products": [r["product_id"] for r in rows]}}],
                  expected_gain=gain, metric={"metric": "product_units", "product_id": rows[0]["product_id"], "window_days": 28})]


# =============================================================================
# PRICING & MARGIN
# =============================================================================
def a_profit_pareto(ctx: Ctx) -> list[Draft]:
    """The few products that make most of the profit — they must never be out, never mis-priced."""
    e = ext(ctx)
    pr: Counter = Counter()
    for l in ctx.lines:
        pr[l["pid"]] += l["profit"]
    tot = sum(v for v in pr.values() if v > 0)
    if tot <= 0 or len(pr) < 30:
        return []
    acc, core = 0.0, []
    for pid, v in pr.most_common():
        if v <= 0 or acc >= tot * 0.8:
            break
        acc += v
        core.append(pid)
    share_items = len(core) / len(pr)
    if share_items > 0.5:
        return []
    weak = [pid for pid in core if (e.stock_by_pid.get(pid, 0) / max(1e-9, e.velocity28.get(pid, 0))) < 5]
    rows = [{"product_id": p, "name": _pname(ctx, p), "profit": round(pr[p]), "share_pct": round(pr[p] / tot * 100, 1), "stock": e.stock_by_pid.get(p, 0),
             "days_cover": round(e.stock_by_pid.get(p, 0) / max(1e-9, e.velocity28.get(p, 0)), 1), "min_stock": int((ctx.products.get(p).min_stock_alert or 0) if ctx.products.get(p) else 0)} for p in core[:40]]
    return [Draft(kind="PROFIT_PARETO", dedupe_key=f"month:{ctx.today.strftime('%Y-%m')}", priority=2 if weak else 3,
                  title=f"{_fa(len(core))} کالا ({_fa(share_items*100)}٪ اقلام) ۸۰٪ سود شما را می‌سازند — {_fa(len(weak))} تا کم‌موجودی‌اند",
                  body=(f"این فهرست «قلب فروشگاه» است: «{rows[0]['name']}» به‌تنهایی {_fa(rows[0]['share_pct'],1)}٪ سود دوره را آورده. برای این‌ها قاعده فرق می‌کند: هرگز خالی نمانند (حداقل ۷ روز پوشش)، "
                        f"همیشه در دید باشند و قیمتشان هر هفته بازبینی شود. {_fa(len(weak))} قلم هم‌اکنون زیر ۵ روز موجودی دارند."),
                  evidence={"rows": rows, "core_count": len(core), "all_products_sold": len(pr)},
                  actions=[{"type": "set_min_stock_bulk", "label": "حداقل موجودی ۷ روزه برای کالاهای قلب فروشگاه", "params": {"items": [{"product_id": p, "min_stock": max(1, math.ceil(e.velocity28.get(p, 0) * 7))} for p in core if e.velocity28.get(p, 0) > 0]}}],
                  expected_gain=sum(pr[p] for p in weak) * (30 / ctx.days) * 0.1, metric={"metric": "avg_basket_size", "window_days": 28})]


def a_negative_margin(ctx: Ctx) -> list[Draft]:
    """Lines actually sold below cost (after discounts) — realised losses, not just a batch price gap."""
    loss: Counter = Counter()
    n: Counter = Counter()
    for l in ctx.lines:
        if l["profit"] < 0 and l["qty"] > 0:
            loss[l["pid"]] += -l["profit"]
            n[l["pid"]] += 1
    rows = [{"product_id": p, "name": _pname(ctx, p), "lines": n[p], "loss": round(v)} for p, v in loss.items() if n[p] >= 3 and v > 30_000]
    if not rows:
        return []
    rows.sort(key=lambda r: -r["loss"])
    rows = rows[:25]
    tot = sum(r["loss"] for r in rows) * (30 / ctx.days)
    e = ext(ctx)
    b = next((b for b in e.active_batches if b.product_id == rows[0]["product_id"]), None)
    acts = [{"type": "note", "label": "بررسی قیمت و تخفیف این کالاها", "params": {}}]
    if b:
        acts.insert(0, {"type": "set_price", "label": f"اصلاح قیمت «{rows[0]['name']}» به قیمت خرید + ۱۲٪", "params": {"batch_id": b.id, "sell_price": round(_f(b.buy_price) * 1.12 / 100) * 100}})
    return [Draft(kind="NEGATIVE_MARGIN", dedupe_key=f"month:{ctx.today.strftime('%Y-%m')}", priority=1,
                  title=f"{_fa(len(rows))} کالا عملاً زیر قیمت خرید فروخته شده‌اند — {_money(tot)} زیان ماهانه",
                  body=(f"بعد از احتساب تخفیف‌های پای صندوق، «{rows[0]['name']}» در {_fa(rows[0]['lines'])} فاکتور با زیان فروخته شده ({_money(rows[0]['loss'])}). "
                        f"یا قیمت خرید جدید ثبت نشده، یا قیمت فروش قدیمی است، یا تخفیف دستی زیاد است — در هر سه حالت هر فروش این کالا پول از جیب شماست."),
                  evidence={"rows": rows, "monthly_loss": round(tot)}, actions=acts,
                  expected_gain=tot * 0.8, metric={"metric": "product_profit", "product_id": rows[0]["product_id"], "window_days": 28})]


def a_discount_leak(ctx: Ctx) -> list[Draft]:
    """Manual discounts as a share of sales, by cashier — a rate 2× the rest is policy (or worse), not generosity."""
    e = ext(ctx)
    disc: Counter = Counter()
    sales: Counter = Counter()
    for l in ctx.lines:
        d = max(0.0, l["price"] * l["qty"] - l["sub"])
        disc[l["user"]] += d
        sales[l["user"]] += l["sub"]
    tot_s = sum(sales.values())
    if tot_s <= 0 or sum(disc.values()) / tot_s < 0.01:
        return []
    avg = sum(disc.values()) / tot_s
    rows = [{"user_id": u, "user": e.users.get(u, str(u)), "discount": round(disc[u]), "sales": round(s), "rate_pct": round(disc[u] / s * 100, 1)} for u, s in sales.items() if s > 0]
    rows.sort(key=lambda r: -r["rate_pct"])
    hot = [r for r in rows if r["rate_pct"] >= max(2.0, avg * 100 * 2) and r["sales"] > tot_s * 0.05]
    if not hot:
        return []
    leak = sum((r["rate_pct"] / 100 - avg) * r["sales"] for r in hot) * (30 / ctx.days)
    return [Draft(kind="DISCOUNT_LEAK", dedupe_key=f"month:{ctx.today.strftime('%Y-%m')}", priority=2,
                  title=f"تخفیف دستی «{hot[0]['user']}» {_fa(hot[0]['rate_pct'],1)}٪ فروش است — {_fa(avg*100,1)}٪ میانگین",
                  body=(f"در این دوره {_money(sum(disc.values()))} تخفیف پای صندوق داده شده. {_fa(len(hot))} کاربر نرخی بیش از دو برابر میانگین دارند؛ نشت ماهانه نسبت به میانگین: {_money(leak)}. "
                        f"سقف تخفیف دستی برای صندوق‌دار (مثلاً ۳٪) و الزام دلیل، معمولاً بدون هیچ اثری بر فروش این عدد را نصف می‌کند."),
                  evidence={"rows": rows, "avg_rate_pct": round(avg * 100, 2), "monthly_leak": round(leak)},
                  actions=[{"type": "set_setting", "label": "سقف تخفیف دستی صندوق ۳٪", "params": {"key": "pos.max_manual_discount_pct", "value": "3"}}],
                  expected_gain=leak * 0.5, metric={"metric": "avg_basket_size", "window_days": 28})]


def a_price_rounding(ctx: Ctx) -> list[Draft]:
    """Odd sell prices (…۱۷۵۰) create change friction; rounding up to the next ۵۰۰/۱۰۰۰ is invisible to the customer and pure margin."""
    e = ext(ctx)
    rows = []
    for b in e.active_batches:
        p = _f(b.sell_price)
        if p < 5_000:
            continue
        step = 500 if p < 50_000 else 1000
        r = p % step
        if 0 < r and (step - r) <= step * 0.3:
            v = e.velocity28.get(b.product_id, 0)
            if v * 28 >= 4:
                rows.append({"batch_id": b.id, "product_id": b.product_id, "name": _pname(ctx, b.product_id), "price": p, "new_price": p + (step - r), "delta": step - r, "monthly_units": round(v * 30), "gain": round((step - r) * v * 30)})
    if len(rows) < 3:
        return []
    rows.sort(key=lambda r: -r["gain"])
    rows = rows[:40]
    gain = sum(r["gain"] for r in rows)
    return [Draft(kind="PRICE_ROUNDING", dedupe_key=f"month:{ctx.today.strftime('%Y-%m')}", priority=4,
                  title=f"گردکردن قیمت {_fa(len(rows))} کالا: {_money(gain)} سود ماهانهٔ بی‌دردسر",
                  body=(f"«{rows[0]['name']}» {_money(rows[0]['price'])} است؛ {_money(rows[0]['new_price'])} برای مشتری فرقی ندارد ولی با {_fa(rows[0]['monthly_units'])} عدد فروش ماهانه {_money(rows[0]['gain'])} اضافه می‌آورد و خرده‌پول صندوق را هم کم می‌کند. "
                        f"همهٔ موارد زیر ۳۰٪ یک پله‌اند (کمتر از ۱۵۰/۳۰۰ تومان)."),
                  evidence={"rows": rows, "monthly_gain": round(gain)},
                  actions=[{"type": "set_prices_bulk", "label": "گردکردن قیمت همهٔ این کالاها", "params": {"items": [{"batch_id": r["batch_id"], "sell_price": r["new_price"]} for r in rows]}}],
                  expected_gain=gain * 0.9, metric={"metric": "product_profit", "product_id": rows[0]["product_id"], "window_days": 28})]


def a_elasticity(ctx: Ctx) -> list[Draft]:
    """Where a price change happened, what did volume do? Learned per product → the direction that made more profit."""
    e = ext(ctx)
    pv_by: dict[int, list[PriceVersion]] = defaultdict(list)
    for pv in e.price_versions:
        pv_by[pv.product_id].append(pv)
    rows = []
    for pid, pvs in pv_by.items():
        for pv in pvs:
            t = pv.effective_from
            if t < ctx.since(ctx.days - 14) or t > ctx.since(14):
                continue
            before = [l for l in ctx.lines if l["pid"] == pid and t - timedelta(days=14) <= l["at"] < t]
            after = [l for l in ctx.lines if l["pid"] == pid and t <= l["at"] < t + timedelta(days=14)]
            if len(before) < 4 or len(after) < 2:
                continue
            ub, ua = sum(l["qty"] for l in before), sum(l["qty"] for l in after)
            pb, pa = sum(l["profit"] for l in before), sum(l["profit"] for l in after)
            prb = before[-1]["price"]
            pra = _f(pv.price)
            if prb <= 0 or abs(pra / prb - 1) < 0.03:
                continue
            dp, dq = pra / prb - 1, ua / ub - 1 if ub else 0
            el = dq / dp if dp else 0
            rows.append({"product_id": pid, "name": _pname(ctx, pid), "date": t.date().isoformat(), "price_before": prb, "price_after": pra, "price_change_pct": round(dp * 100),
                         "units_before": ub, "units_after": ua, "units_change_pct": round(dq * 100), "profit_before": round(pb), "profit_after": round(pa), "elasticity": round(el, 2),
                         "verdict": "good" if pa > pb else "bad"})
    if not rows:
        return []
    rows.sort(key=lambda r: -abs(r["profit_after"] - r["profit_before"]))
    rows = rows[:20]
    bad = [r for r in rows if r["verdict"] == "bad"]
    r0 = (bad or rows)[0]
    acts = []
    b = next((b for b in e.active_batches if b.product_id == r0["product_id"]), None)
    if bad and b:
        acts.append({"type": "set_price", "label": f"بازگرداندن قیمت «{r0['name']}» به {_money(r0['price_before'])}", "params": {"batch_id": b.id, "sell_price": r0["price_before"]}})
    acts.append({"type": "note", "label": "ثبت درس‌آموخته‌های قیمت‌گذاری", "params": {}})
    return [Draft(kind="ELASTICITY", dedupe_key=f"month:{ctx.today.strftime('%Y-%m')}", priority=2 if bad else 3,
                  title=(f"تغییر قیمت «{r0['name']}» سود را کم کرد" if bad else f"تغییر قیمت «{r0['name']}» جواب داد — الگو را تکرار کنید"),
                  body=(f"در {r0['date']} قیمت از {_money(r0['price_before'])} به {_money(r0['price_after'])} ({_fa(r0['price_change_pct'])}٪) رفت؛ فروش ۱۴ روزه {_fa(r0['units_before'])} → {_fa(r0['units_after'])} عدد "
                        f"({_fa(r0['units_change_pct'])}٪) و سود {_money(r0['profit_before'])} → {_money(r0['profit_after'])}. کشش قیمتی ≈ {_fa(r0['elasticity'],1)}. "
                        + ("این کالا حساس به قیمت است؛ برگردید." if bad else "این کالا کم‌کشش است؛ افزایش‌های کوچک دیگر هم احتمالاً بی‌خطرند.")),
                  evidence={"rows": rows}, actions=acts,
                  expected_gain=abs(r0["profit_after"] - r0["profit_before"]) * 2, metric={"metric": "product_profit", "product_id": r0["product_id"], "window_days": 14})]


def a_category_margin(ctx: Ctx) -> list[Draft]:
    """Categories priced well below the store's margin rate — usually inherited prices, not strategy."""
    e = ext(ctx)
    if not e.categories:
        return []
    s: Counter = Counter()
    p: Counter = Counter()
    for l in ctx.lines:
        c = e.cat_of(l["pid"])
        s[c] += l["sub"]
        p[c] += l["profit"]
    tot_s, tot_p = sum(s.values()), sum(p.values())
    if tot_s <= 0:
        return []
    store = tot_p / tot_s
    rows = [{"category_id": c, "category": e.cat_name(c), "sales": round(v), "margin_pct": round(p[c] / v * 100, 1), "store_pct": round(store * 100, 1)} for c, v in s.items() if v > tot_s * 0.03]
    low = [r for r in rows if r["margin_pct"] < store * 100 * 0.6]
    if not low:
        return []
    low.sort(key=lambda r: -r["sales"])
    gap = sum((store - r["margin_pct"] / 100) * r["sales"] for r in low) * (30 / ctx.days)
    return [Draft(kind="CATEGORY_MARGIN", dedupe_key=f"month:{ctx.today.strftime('%Y-%m')}", priority=3,
                  title=f"حاشیهٔ سود «{low[0]['category']}» {_fa(low[0]['margin_pct'],1)}٪ است، فروشگاه {_fa(store*100,1)}٪",
                  body=(f"{_fa(len(low))} دستهٔ پرفروش با حاشیه‌ای کمتر از ۶۰٪ میانگین فروشگاه. اگر فقط نصف فاصله جبران شود، ماهانه {_money(gap/2)} سود اضافه می‌شود. "
                        f"معمولاً چند قلم پرفروش این دسته‌ها قیمت قدیمی دارند؛ از همان‌ها شروع کنید."),
                  evidence={"rows": sorted(rows, key=lambda r: r["margin_pct"]), "monthly_gap": round(gap)},
                  actions=[{"type": "note", "label": "بازبینی قیمت اقلام پرفروش این دسته‌ها", "params": {}}],
                  expected_gain=gap * 0.25, metric={"metric": "avg_basket_size", "window_days": 28})]


# =============================================================================
# OPERATIONS
# =============================================================================
def a_peak_hours(ctx: Ctx) -> list[Draft]:
    """Hour-of-day sales heat-map → where the second cashier / the promo table / the fresh delivery should be."""
    hrs: Counter = Counter()
    cnt: Counter = Counter()
    for inv in ctx.invoices.values():
        h = _local_hour(inv["at"])
        hrs[h] += inv["total"]
        cnt[h] += 1
    if sum(cnt.values()) < 200:
        return []
    days = max(1, ctx.days)
    rows = [{"hour": h, "invoices_per_day": round(cnt[h] / days, 1), "sales_per_day": round(hrs[h] / days)} for h in sorted(cnt)]
    tot = sum(hrs.values())
    top = sorted(rows, key=lambda r: -r["sales_per_day"])[:3]
    share = sum(r["sales_per_day"] for r in top) * days / tot
    open_h = [r for r in rows if r["invoices_per_day"] >= 0.5]
    first, last = open_h[0], open_h[-1]
    dead = [r for r in open_h if r["sales_per_day"] < (tot / days / len(open_h)) * 0.25]
    return [Draft(kind="PEAK_HOURS", dedupe_key=f"month:{ctx.today.strftime('%Y-%m')}", priority=3,
                  title=f"ساعت‌های {'، '.join(_fa(r['hour']) for r in sorted(top, key=lambda r: r['hour']))} → {_fa(share*100)}٪ فروش روزانه",
                  body=(f"در این سه ساعت روزانه {_fa(sum(r['invoices_per_day'] for r in top),1)} فاکتور بسته می‌شود؛ صف و کمبود کالای تازه بیشترین ضرر را همین‌جا می‌زند. "
                        f"{_fa(len(dead))} ساعت باز (مثلاً {_fa(dead[0]['hour']) if dead else '—'}) کمتر از یک‌چهارم میانگین می‌فروشد — زمان مناسب برای چیدمان، شمارش و تماس با تأمین‌کننده. "
                        f"اولین/آخرین ساعت فعال: {_fa(first['hour'])} تا {_fa(last['hour'])}."),
                  evidence={"rows": rows, "peak": top, "dead": dead},
                  actions=[{"type": "note", "label": "برنامهٔ نیرو و تحویل کالا بر اساس ساعات اوج", "params": {}}],
                  expected_gain=tot / days * 30 * 0.005, metric={"metric": "avg_basket_size", "window_days": 28})]


def a_queue_stress(ctx: Ctx) -> list[Draft]:
    """Bursts of > N invoices per 15 minutes on one register → lost baskets (people leave the queue)."""
    slots: Counter = Counter()
    for inv in ctx.invoices.values():
        t = inv["at"] + timedelta(hours=3, minutes=30)
        slots[(t.weekday(), t.hour, t.minute // 15)] += 1
    if not slots:
        return []
    weeks = max(1, ctx.days / 7)
    per = {k: v / weeks for k, v in slots.items()}
    cap = 10   # ≈ one register, 90 s per invoice
    hot = sorted(((k, v) for k, v in per.items() if v >= cap), key=lambda kv: -kv[1])
    if len(hot) < 3:
        return []
    rows = [{"weekday": WEEKDAY_FA[k[0]], "time": f"{k[1]:02d}:{k[2]*15:02d}", "invoices_per_15min": round(v, 1)} for k, v in hot[:20]]
    avg_ticket = sum(i["total"] for i in ctx.invoices.values()) / max(1, len(ctx.invoices))
    lost = sum(max(0.0, v - cap) for _, v in hot) * 4 * avg_ticket * _profit_rate(ctx) * 0.3
    return [Draft(kind="QUEUE_STRESS", dedupe_key=f"month:{ctx.today.strftime('%Y-%m')}", priority=3,
                  title=f"{_fa(len(hot))} بازهٔ ۱۵ دقیقه‌ای در هفته بیش از ظرفیت یک صندوق است",
                  body=(f"{rows[0]['weekday']} ساعت {rows[0]['time']} به‌طور میانگین {_fa(rows[0]['invoices_per_15min'],1)} فاکتور در ۱۵ دقیقه بسته می‌شود؛ یک صندوق حدود {_fa(cap)} تا می‌کشد. "
                        f"در صف طولانی بخشی از مشتری‌ها سبد را می‌گذارند و می‌روند. صندوق دوم (حتی با گوشی) فقط در همین بازه‌ها، سود ماهانهٔ ≈{_money(lost)} را برمی‌گرداند."),
                  evidence={"rows": rows, "capacity_per_15min": cap},
                  actions=[{"type": "note", "label": "برنامهٔ صندوق دوم برای بازه‌های شلوغ", "params": {}}],
                  expected_gain=lost, metric={"metric": "avg_basket_size", "window_days": 28})]


def a_cashier_perf(ctx: Ctx) -> list[Draft]:
    """Per cashier: basket size, items per basket, discount rate, void rate → a coaching sheet, not a witch-hunt."""
    e = ext(ctx)
    by_u: dict[int, dict] = defaultdict(lambda: {"inv": 0, "sales": 0.0, "items": 0.0, "disc": 0.0})
    for iid, inv in ctx.invoices.items():
        u = inv["user"]
        by_u[u]["inv"] += 1
        by_u[u]["sales"] += inv["total"]
    for l in ctx.lines:
        by_u[l["user"]]["items"] += l["qty"]
        by_u[l["user"]]["disc"] += max(0.0, l["price"] * l["qty"] - l["sub"])
    voids = Counter(v.user_id for v in e.voids)
    rows = [{"user_id": u, "user": e.users.get(u, str(u)), "invoices": d["inv"], "avg_ticket": round(d["sales"] / d["inv"]), "items_per_basket": round(d["items"] / d["inv"], 1),
             "discount_pct": round(d["disc"] / d["sales"] * 100, 2) if d["sales"] else 0, "void_pct": round(voids[u] / d["inv"] * 100, 1)} for u, d in by_u.items() if d["inv"] >= 50]
    if len(rows) < 2:
        return []
    rows.sort(key=lambda r: -r["avg_ticket"])
    best, worst = rows[0], rows[-1]
    if best["avg_ticket"] < worst["avg_ticket"] * 1.15:
        return []
    gain = (best["avg_ticket"] - worst["avg_ticket"]) * worst["invoices"] * (30 / ctx.days) * _profit_rate(ctx) * 0.3
    return [Draft(kind="CASHIER_PERF", dedupe_key=f"month:{ctx.today.strftime('%Y-%m')}", priority=3,
                  title=f"میانگین فاکتور «{best['user']}» {_fa((best['avg_ticket']/worst['avg_ticket']-1)*100)}٪ بیشتر از «{worst['user']}» است",
                  body=(f"با مشتریان مشابه، {best['user']} سبد {_fa(best['items_per_basket'],1)} قلمی و {worst['user']} سبد {_fa(worst['items_per_basket'],1)} قلمی می‌بندد "
                        f"(تخفیف {_fa(best['discount_pct'],1)}٪ در برابر {_fa(worst['discount_pct'],1)}٪، ابطال {_fa(best['void_pct'],1)}٪ در برابر {_fa(worst['void_pct'],1)}٪). "
                        f"تفاوت معمولاً در یک جمله است: «چیز دیگری لازم ندارید؟» + پیشنهاد پای صندوق. آموزش ۱۰ دقیقه‌ای و فعال‌کردن پیشنهاد خودکار."),
                  evidence={"rows": rows},
                  actions=[{"type": "enable_nudges", "label": "فعال‌کردن پیشنهاد پای صندوق برای همه", "params": {}}],
                  expected_gain=gain, metric={"metric": "avg_basket_size", "window_days": 28})]


def a_cash_diff(ctx: Ctx) -> list[Draft]:
    """Cash-drawer differences recurring for one user/shift."""
    e = ext(ctx)
    by_u: dict[int, list[float]] = defaultdict(list)
    for s in e.cash_sessions:
        if s.difference is not None:
            by_u[s.user_id].append(_f(s.difference))
    rows = []
    for u, ds in by_u.items():
        short = [d for d in ds if d < -10_000]
        if len(ds) >= 5 and len(short) >= max(3, len(ds) * 0.3):
            rows.append({"user_id": u, "user": e.users.get(u, str(u)), "sessions": len(ds), "short_sessions": len(short), "total_short": round(-sum(short)), "avg_short": round(-sum(short) / len(short))})
    if not rows:
        return []
    rows.sort(key=lambda r: -r["total_short"])
    tot = sum(r["total_short"] for r in rows)
    return [Draft(kind="CASH_DIFF", dedupe_key=f"month:{ctx.today.strftime('%Y-%m')}", priority=2,
                  title=f"کسری صندوق تکراری: {_money(tot)} در ۹۰ روز",
                  body=(f"«{rows[0]['user']}» در {_fa(rows[0]['short_sessions'])} شیفت از {_fa(rows[0]['sessions'])} شیفت کسری داشته (میانگین {_money(rows[0]['avg_short'])}). کسری تصادفی دو طرفه است؛ کسری یک‌طرفهٔ تکراری یعنی خطای رویه (پول‌خرد، کارت‌خوان) یا مشکل جدی‌تر. "
                        f"شمارش میان‌شیفت و ثبت دلیل برای هر اختلاف بالای ۲۰ هزار تومان."),
                  evidence={"rows": rows, "total_short": round(tot)},
                  actions=[{"type": "note", "label": "الزام شمارش میان‌شیفت", "params": {}}],
                  expected_gain=tot / 3 * 0.7, metric={"metric": "void_rate", "user_id": rows[0]["user_id"], "window_days": 28})]


def a_returns_product(ctx: Ctx) -> list[Draft]:
    """Return rate per product ≥ 4 % (and ≥ 3 returns) → quality/supplier/expiry problem."""
    e = ext(ctx)
    ret: Counter = Counter()
    n: Counter = Counter()
    reasons: dict[int, Counter] = defaultdict(Counter)
    for at, pid, q, reason, amt in e.returns:
        ret[pid] += _f(q)
        n[pid] += 1
        reasons[pid][(reason or "—")[:30]] += 1
    rows = []
    for pid, q in ret.items():
        sold = sum(l["qty"] for l in ctx.lines if l["pid"] == pid)
        if n[pid] >= 3 and sold > 0 and q / sold >= 0.04:
            rows.append({"product_id": pid, "name": _pname(ctx, pid), "returns": n[pid], "returned_qty": q, "sold": sold, "rate_pct": round(q / sold * 100, 1), "top_reason": reasons[pid].most_common(1)[0][0]})
    if not rows:
        return []
    rows.sort(key=lambda r: -r["rate_pct"] * r["sold"])
    rows = rows[:20]
    return [Draft(kind="RETURNS_PRODUCT", dedupe_key=f"month:{ctx.today.strftime('%Y-%m')}", priority=2,
                  title=f"«{rows[0]['name']}» {_fa(rows[0]['rate_pct'],1)}٪ مرجوعی دارد ({_fa(len(rows))} کالای مشکل‌دار)",
                  body=(f"دلیل غالب: «{rows[0]['top_reason']}». مرجوعی بالای ۴٪ در سوپرمارکت یعنی مشکل کیفیت یا بچ خراب؛ هر مرجوعی علاوه بر پول، اعتماد مشتری را هم می‌برد. "
                        f"با تأمین‌کننده تسویه یا تعویض کنید و تا رفع مشکل، این اقلام را از قفسهٔ اصلی بردارید."),
                  evidence={"rows": rows},
                  actions=[{"type": "note", "label": "پیگیری با تأمین‌کننده", "params": {}}],
                  expected_gain=sum(r["returned_qty"] * _avg_margin(ctx, r["product_id"]) for r in rows) * (30 / ctx.days) * 2, metric={"metric": "product_profit", "product_id": rows[0]["product_id"], "window_days": 28})]


def a_receivables_aging(ctx: Ctx) -> list[Draft]:
    """Aging buckets of customer debt (0–30 / 31–60 / 61–90 / 90+) → focused collection instead of blanket reminders."""
    e = ext(ctx)
    now = ctx.now_utc
    last_pay: dict[int, datetime] = {}
    for en in e.ledger:
        if en.entry_type == "PAYMENT":
            last_pay[en.customer_id] = en.created_at
    buckets = {"0-30": [], "31-60": [], "61-90": [], "90+": []}
    for cid, (bal, at) in e.balances.items():
        if bal <= 0:
            continue
        ref = last_pay.get(cid) or e.first_visit.get(cid) or at
        age = (now - ref).days
        k = "0-30" if age <= 30 else "31-60" if age <= 60 else "61-90" if age <= 90 else "90+"
        buckets[k].append({"customer_id": cid, "name": e.cname(cid), "phone": e.phone(cid), "balance": round(bal), "age_days": age})
    tot = sum(r["balance"] for b in buckets.values() for r in b)
    old = buckets["61-90"] + buckets["90+"]
    old_sum = sum(r["balance"] for r in old)
    if tot < 1_000_000 or old_sum < tot * 0.2:
        return []
    for b in buckets.values():
        b.sort(key=lambda r: -r["balance"])
    texts = [{"customer_id": r["customer_id"], "text": f"{r['name']} عزیز، ماندهٔ حساب شما {_money(r['balance'])} است و مدتی از آخرین تسویه گذشته. لطفاً برای تسویه یا هماهنگی اقساط تماس بگیرید. سپاس."} for r in old[:40] if r["phone"]]
    return [Draft(kind="RECEIVABLES_AGING", dedupe_key=f"week:{ctx.today.isocalendar()[1]}", priority=2,
                  title=f"{_money(old_sum)} از طلب‌ها بیش از ۶۰ روز قدیمی است ({_fa(old_sum/tot*100)}٪ کل)",
                  body=(f"کل طلب: {_money(tot)} — ۰ تا ۳۰ روز: {_money(sum(r['balance'] for r in buckets['0-30']))}، ۳۱ تا ۶۰: {_money(sum(r['balance'] for r in buckets['31-60']))}، "
                        f"۶۱ تا ۹۰: {_money(sum(r['balance'] for r in buckets['61-90']))}، بالای ۹۰: {_money(sum(r['balance'] for r in buckets['90+']))}. "
                        f"احتمال وصول بعد از ۹۰ روز به‌شدت افت می‌کند؛ روی {_fa(len(old))} حساب قدیمی تمرکز کنید (پیامک + تماس + پیشنهاد قسط)."),
                  evidence={"buckets": {k: v[:25] for k, v in buckets.items()}, "totals": {k: round(sum(r["balance"] for r in v)) for k, v in buckets.items()}},
                  actions=[_sms_action("پیامک تسویه به حساب‌های بالای ۶۰ روز", texts)],
                  expected_gain=old_sum * 0.1, metric={"metric": "receivables_collected", "window_days": 21})]


def a_expense_spike(ctx: Ctx) -> list[Draft]:
    """An expense category this month ≥ 1.4× its 3-month average."""
    e = ext(ctx)
    by: dict[str, Counter] = defaultdict(Counter)
    for d, amt, cat in e.expenses:
        m = to_jalali(datetime.combine(d, datetime.min.time()))[:2]
        by[cat][m] += _f(amt)
    jy, jm, _ = to_jalali(datetime.combine(ctx.today, datetime.min.time()))
    rows = []
    for cat, ms in by.items():
        cur = ms.get((jy, jm), 0)
        prev = [v for k, v in ms.items() if k != (jy, jm)]
        if len(prev) >= 2 and cur >= 500_000:
            avg = sum(prev) / len(prev)
            if avg > 0 and cur >= avg * 1.4:
                rows.append({"category": cat, "this_month": round(cur), "avg_prev": round(avg), "spike_pct": round((cur / avg - 1) * 100)})
    if not rows:
        return []
    rows.sort(key=lambda r: -(r["this_month"] - r["avg_prev"]))
    extra = sum(r["this_month"] - r["avg_prev"] for r in rows)
    return [Draft(kind="EXPENSE_SPIKE", dedupe_key=f"month:{jy}-{jm}", priority=3,
                  title=f"هزینهٔ «{rows[0]['category']}» این ماه {_fa(rows[0]['spike_pct'])}٪ بالاتر از معمول است",
                  body=(f"{JMONTH[jm-1]}: {_money(rows[0]['this_month'])} در برابر میانگین {_money(rows[0]['avg_prev'])} ماه‌های قبل. {_fa(len(rows))} سرفصل جهش دارند، مجموعاً {_money(extra)} بیش از روال. "
                        f"جهش هزینه بی‌صدا سود ماه را می‌خورد؛ یک نگاه پنج‌دقیقه‌ای به ریز اسناد این سرفصل کافی است."),
                  evidence={"rows": rows, "extra": round(extra)},
                  actions=[{"type": "note", "label": "بررسی اسناد این سرفصل", "params": {}}],
                  expected_gain=extra * 0.3, metric={"metric": "avg_basket_size", "window_days": 28})]


def a_sms_roi(ctx: Ctx) -> list[Draft]:
    """Per campaign: coupons issued → used → sales they carried; keep what pays, stop what doesn't."""
    e = ext(ctx)
    if not e.redemptions and not e.coupons:
        return []
    per: dict[int, dict] = defaultdict(lambda: {"issued": 0, "used": 0, "sales": 0.0, "discount": 0.0})
    for c in e.coupons:
        if c.campaign_id:
            per[c.campaign_id]["issued"] += 1
    inv_total = {iid: inv["total"] for iid, inv in ctx.invoices.items()}
    cid_by_coupon = {c.id: c.campaign_id for c in e.coupons}
    for r in e.redemptions:
        camp = cid_by_coupon.get(r.coupon_id)
        if camp:
            per[camp]["used"] += 1
            per[camp]["sales"] += inv_total.get(r.invoice_id, 0.0)
            per[camp]["discount"] += _f(r.amount)
    rows = []
    for camp, d in per.items():
        if d["issued"] < 10:
            continue
        c = e.campaigns.get(camp)
        rate = d["used"] / d["issued"]
        profit = d["sales"] * _profit_rate(ctx) - d["discount"]
        rows.append({"campaign_id": camp, "campaign": c.name if c else str(camp), "issued": d["issued"], "used": d["used"], "rate_pct": round(rate * 100, 1),
                     "sales": round(d["sales"]), "discount": round(d["discount"]), "net_profit": round(profit), "verdict": "keep" if rate >= 0.12 and profit > 0 else "stop"})
    if not rows:
        return []
    rows.sort(key=lambda r: -r["net_profit"])
    keep, stop = [r for r in rows if r["verdict"] == "keep"], [r for r in rows if r["verdict"] == "stop"]
    return [Draft(kind="SMS_ROI", dedupe_key=f"month:{ctx.today.strftime('%Y-%m')}", priority=3,
                  title=f"بازده کمپین‌ها: {_fa(len(keep))} کمپین سودده، {_fa(len(stop))} کمپین بی‌اثر",
                  body=((f"«{keep[0]['campaign']}» با {_fa(keep[0]['rate_pct'],1)}٪ استفاده {_money(keep[0]['net_profit'])} سود خالص آورده. " if keep else "")
                        + (f"«{stop[0]['campaign']}» با {_fa(stop[0]['issued'])} کوپن فقط {_fa(stop[0]['used'])} بار استفاده شده — متن یا مخاطبش را عوض کنید. " if stop else "")
                        + "قاعدهٔ سرانگشتی: زیر ۱۲٪ استفاده یعنی پیشنهاد جذاب نیست یا به آدم اشتباهی رفته."),
                  evidence={"rows": rows},
                  actions=[{"type": "note", "label": "بازنگری کمپین‌های بی‌اثر", "params": {}}],
                  expected_gain=sum(r["net_profit"] for r in keep) * 0.2, metric={"metric": "avg_basket_size", "window_days": 28})]


# =============================================================================
# GROWTH
# =============================================================================
def a_campaign_fatigue(ctx: Ctx) -> list[Draft]:
    """Same customers messaged ≥ 4× in 30 days with < 1 redemption → they are tuning you out."""
    e = ext(ctx)
    since = ctx.since(30)
    per_phone: Counter = Counter()
    for m in e.sms:
        if m.created_at >= since and m.phone:
            per_phone[m.phone] += 1
    heavy = {p for p, n in per_phone.items() if n >= 4}
    if len(heavy) < 5:
        return []
    used_phones = set()
    for r in e.redemptions:
        if r.created_at >= since and r.customer_id:
            used_phones.add(e.phone(r.customer_id))
    fatigued = [p for p in heavy if p not in used_phones]
    if len(fatigued) < 5:
        return []
    cust_by_phone = {c.phone: c.id for c in e.customers.values() if c.phone}
    rows = [{"phone": p, "customer_id": cust_by_phone.get(p), "name": e.cname(cust_by_phone[p]) if p in cust_by_phone else "—", "sms_30d": per_phone[p]} for p in fatigued]
    rows.sort(key=lambda r: -r["sms_30d"])
    return [Draft(kind="CAMPAIGN_FATIGUE", dedupe_key=f"month:{ctx.today.strftime('%Y-%m')}", priority=3,
                  title=f"{_fa(len(fatigued))} مشتری در ۳۰ روز ≥۴ پیامک گرفته‌اند و هیچ واکنشی نداشته‌اند",
                  body=(f"پیامک زیاد بدون پاسخ، اثر پیامک‌های بعدی (حتی مهم‌ها) را می‌کشد و هزینهٔ پیامک هم هست. برای این گروه یک ماه سکوت، بعد فقط پیام‌های شخصی (کالای همیشگی، سالگرد). "
                        f"سقف پیشنهادی: ۲ پیامک تبلیغاتی در ماه برای هر شماره."),
                  evidence={"rows": rows[:50], "count": len(fatigued)},
                  actions=[{"type": "set_setting", "label": "سقف ۲ پیامک تبلیغاتی در ماه برای هر شماره", "params": {"key": "sms.max_promo_per_month", "value": "2"}}],
                  expected_gain=len(fatigued) * 3000, metric={"metric": "avg_basket_size", "window_days": 28})]


def a_unregistered_sales(ctx: Ctx) -> list[Draft]:
    """Most invoices have no customer attached → the behaviour engine is blind to most of the shop."""
    n = len(ctx.invoices)
    if n < 100:
        return []
    anon = sum(1 for inv in ctx.invoices.values() if not inv["cust"])
    share = anon / n
    if share < 0.6:
        return []
    anon_sales = sum(inv["total"] for inv in ctx.invoices.values() if not inv["cust"])
    big = sum(1 for inv in ctx.invoices.values() if not inv["cust"] and inv["total"] > 500_000)
    return [Draft(kind="UNREGISTERED_SALES", dedupe_key=f"month:{ctx.today.strftime('%Y-%m')}", priority=3,
                  title=f"{_fa(share*100)}٪ فاکتورها بدون مشتری ثبت می‌شوند — هوش فروشگاه نیمه‌کور است",
                  body=(f"{_money(anon_sales)} فروش این دوره به هیچ مشتری‌ای وصل نیست، از جمله {_fa(big)} فاکتور بالای ۵۰۰ هزار تومان. تحلیل رفتار، پیامک شخصی و بازگشت مشتری فقط برای مشتریان ثبت‌شده کار می‌کند. "
                        f"یک جمله پای صندوق («شماره‌تان را بدهید تا امتیاز جمع شود») روی فاکتورهای بزرگ، در دو هفته این عدد را نصف می‌کند."),
                  evidence={"invoices": n, "anonymous": anon, "anonymous_sales": round(anon_sales), "big_anonymous": big},
                  actions=[{"type": "set_setting", "label": "یادآوری ثبت شماره برای فاکتورهای بالای ۵۰۰ هزار تومان پای صندوق", "params": {"key": "pos.ask_phone_above", "value": "500000"}}],
                  expected_gain=anon_sales * (30 / ctx.days) * _profit_rate(ctx) * 0.02, metric={"metric": "avg_basket_size", "window_days": 28})]


def a_hero_product(ctx: Ctx) -> list[Draft]:
    """Which products are in the *first* basket of new customers far more than in ordinary baskets? Those bring people in — advertise them outside."""
    e = ext(ctx)
    firsts = []
    for cid, invs in e.by_cust.items():
        f = e.first_visit.get(cid)
        if f and f >= ctx.since(ctx.days) and invs:
            firsts.append(invs[0]["pids"])
    if len(firsts) < 20:
        return []
    fc: Counter = Counter()
    for pids in firsts:
        for p in pids:
            fc[p] += 1
    allc: Counter = Counter()
    for inv in ctx.invoices.values():
        for p in inv["pids"]:
            allc[p] += 1
    n_all = len(ctx.invoices)
    rows = []
    for p, k in fc.items():
        if k < 5:
            continue
        lift = (k / len(firsts)) / max(1e-9, allc[p] / n_all)
        if lift >= 1.5:
            rows.append({"product_id": p, "name": _pname(ctx, p), "first_baskets": k, "first_share_pct": round(k / len(firsts) * 100), "lift": round(lift, 1), "margin": round(_avg_margin(ctx, p))})
    if not rows:
        return []
    rows.sort(key=lambda r: -r["lift"] * r["first_baskets"])
    rows = rows[:10]
    return [Draft(kind="HERO_PRODUCT", dedupe_key=f"month:{ctx.today.strftime('%Y-%m')}", priority=3,
                  title=f"«{rows[0]['name']}» مشتری جدید می‌آورد ({_fa(rows[0]['first_share_pct'])}٪ اولین خریدها)",
                  body=(f"در {_fa(len(firsts))} «اولین خرید» این دوره، این کالا {_fa(rows[0]['lift'],1)}× بیشتر از سبدهای عادی دیده می‌شود؛ یعنی مردم به‌خاطر آن وارد می‌شوند. "
                        f"همین را روی بنر بیرون، استوری و پیامک جذب بگذارید — نه پرفروش‌ترین کالا را. {_fa(len(rows))} کالای «قلاب» پیدا شد."),
                  evidence={"rows": rows, "first_baskets": len(firsts)},
                  actions=[{"type": "note", "label": "استفاده از کالای قلاب در تبلیغ بیرونی", "params": {}}],
                  expected_gain=len(firsts) * (30 / ctx.days) * 0.15 * 80_000, metric={"metric": "product_units", "product_id": rows[0]["product_id"], "window_days": 28})]


def a_slow_day(ctx: Ctx) -> list[Draft]:
    """The weakest weekday (≤ 65 % of the average) — a weekday-only offer fills the trough instead of discounting the peak."""
    by_wd: Counter = Counter()
    cnt: Counter = Counter()
    for inv in ctx.invoices.values():
        wd = (inv["at"] + timedelta(hours=3, minutes=30)).weekday()
        by_wd[wd] += inv["total"]
        cnt[wd] += 1
    if len(ctx.invoices) < 200 or len(by_wd) < 6:
        return []
    avg = sum(by_wd.values()) / 7
    rows = sorted(({"weekday": WEEKDAY_FA[w], "wd": w, "sales": round(by_wd[w]), "invoices": cnt[w], "vs_avg_pct": round((by_wd[w] / avg - 1) * 100)} for w in by_wd), key=lambda r: r["sales"])
    worst = rows[0]
    if worst["sales"] > avg * 0.65:
        return []
    gap = (avg - worst["sales"]) * (30 / ctx.days)
    return [Draft(kind="SLOW_DAY", dedupe_key=f"wd:{worst['wd']}:{ctx.today.strftime('%Y-%m')}", priority=3,
                  title=f"{worst['weekday']}‌ها {_fa(abs(worst['vs_avg_pct']))}٪ زیر میانگین هفته می‌فروشید",
                  body=(f"فروش {worst['weekday']} در این دوره {_money(worst['sales'])} بوده در برابر میانگین روزانهٔ {_money(avg)}. تخفیف در روز اوج فقط سود را کم می‌کند؛ "
                        f"همان تخفیف در {worst['weekday']} مشتری تازه می‌آورد. پیشنهاد: «{worst['weekday']}‌های ۵٪» فقط با ثبت شماره."),
                  evidence={"rows": rows, "avg_day_sales": round(avg)},
                  actions=[{"type": "flash_sale", "label": f"کمپین «{worst['weekday']}‌های ۵٪» (۴ هفته)", "params": {"percent": 5, "days": 28}}],
                  expected_gain=gap * 0.2 * _profit_rate(ctx), metric={"metric": "weekday_sales", "weekday": worst["wd"], "window_days": 28})]


def a_basket_trend(ctx: Ctx) -> list[Draft]:
    """Average basket over 8 weeks trending down while visits hold → assortment/price perception, not traffic."""
    now = ctx.now_utc
    wk: dict[int, list[float]] = defaultdict(list)
    for inv in ctx.invoices.values():
        k = int((now - inv["at"]).total_seconds() // (7 * 86400))
        if 0 <= k < 8:
            wk[7 - k].append(inv["total"])
    if len(wk) < 6 or any(len(v) < 15 for v in wk.values()):
        return []
    avg = [sum(wk[i]) / len(wk[i]) for i in sorted(wk)]
    cnt = [len(wk[i]) for i in sorted(wk)]
    s_avg, s_cnt = _slope(avg), _slope(cnt)
    if s_avg > -0.02 or s_cnt < -0.03:
        return []
    loss = (avg[0] - avg[-1]) * sum(cnt[-4:]) * _profit_rate(ctx)
    return [Draft(kind="BASKET_TREND", dedupe_key=f"week:{ctx.today.isocalendar()[1]}", priority=2,
                  title=f"میانگین فاکتور هشت هفته است هر هفته ≈{_fa(abs(s_avg)*100,1)}٪ کوچک‌تر می‌شود",
                  body=(f"{_money(avg[0])} → {_money(avg[-1])} در حالی که تعداد مشتری ثابت مانده. یعنی همان آدم‌ها کمتر می‌خرند: یا چیزی از سبدشان کم شده (موجودی/تنوع)، یا برداشت قیمت بد شده، یا رقیبی نزدیک باز شده. "
                        f"با «سبد {_money(round(avg[0]/1000)*1000)} = هدیه» و پیشنهاد پای صندوق شروع کنید و کمبود کالاهای پرفروش را ببندید."),
                  evidence={"weekly_avg_ticket": [round(a) for a in avg], "weekly_invoices": cnt},
                  actions=[{"type": "enable_nudges", "label": "فعال‌کردن پیشنهاد پای صندوق", "params": {}},
                           {"type": "threshold_campaign", "label": f"کمپین «بالای {_money(round(avg[0]/1000)*1000)} = ۳٪»", "params": {"percent": 3, "min_purchase": round(avg[0] / 1000) * 1000, "days": 28}}],
                  expected_gain=loss * 0.3, metric={"metric": "avg_basket_size", "window_days": 28})]


def a_new_product_watch(ctx: Ctx) -> list[Draft]:
    """Products first sold < 45 days ago: ramping (double facing) or flopping (stop reorder) — decide with data, not gut."""
    e = ext(ctx)
    rows = []
    for pid, first in e.first_sold.items():
        age = (ctx.now_utc - first).days
        if not (14 <= age <= 45) or pid not in ctx.products:
            continue
        w = e.weekly_units(pid, 4)
        units = sum(w)
        stock = e.stock_by_pid.get(pid, 0)
        rows.append({"product_id": pid, "name": _pname(ctx, pid), "age_days": age, "weekly": [round(x, 1) for x in w], "units": round(units), "stock": stock,
                     "verdict": "win" if units >= 20 and _slope(w) > 0 else "flop" if units <= 3 and stock > 5 else "watch", "margin": round(_avg_margin(ctx, pid))})
    wins, flops = [r for r in rows if r["verdict"] == "win"], [r for r in rows if r["verdict"] == "flop"]
    if not wins and not flops:
        return []
    cap = sum(e.capital_by_pid.get(r["product_id"], 0) for r in flops)
    return [Draft(kind="NEW_PRODUCT_WATCH", dedupe_key=f"week:{ctx.today.isocalendar()[1]}", priority=3,
                  title=f"کالاهای تازه: {_fa(len(wins))} برنده، {_fa(len(flops))} ناموفق ({_money(cap)} سرمایه)",
                  body=((f"«{wins[0]['name']}» در {_fa(wins[0]['age_days'])} روز {_fa(wins[0]['units'])} عدد فروخته و هر هفته بیشتر می‌شود — جا و موجودی‌اش را دو برابر کنید. " if wins else "")
                        + (f"«{flops[0]['name']}» بعد از {_fa(flops[0]['age_days'])} روز فقط {_fa(flops[0]['units'])} عدد؛ سفارش دوم نگیرید و بقیه را با کالای پرفروش باندل کنید." if flops else "")),
                  evidence={"rows": sorted(rows, key=lambda r: -r["units"])},
                  actions=[{"type": "reorder_note", "label": "سفارش بیشتر برای برنده‌ها", "params": {"products": [r["product_id"] for r in wins]}}] if wins else [{"type": "note", "label": "یادداشت «سفارش نگیر» برای ناموفق‌ها", "params": {}}],
                  expected_gain=sum(r["units"] * r["margin"] for r in wins) * 0.5 + cap * 0.05, metric={"metric": "product_units", "product_id": (wins or flops)[0]["product_id"], "window_days": 21})]


def a_category_depth(ctx: Ctx) -> list[Draft]:
    """High-velocity categories carried with only 1–2 SKUs → customers who want a choice go elsewhere."""
    e = ext(ctx)
    if not e.categories:
        return []
    units: Counter = Counter()
    skus: dict[int, set] = defaultdict(set)
    for l in ctx.lines:
        c = e.cat_of(l["pid"])
        if c:
            units[c] += l["qty"]
            skus[c].add(l["pid"])
    if len(units) < 5:
        return []
    med_units = _median(list(units.values()))
    rows = [{"category_id": c, "category": e.cat_name(c), "units": round(u), "skus": len(skus[c])} for c, u in units.items() if u >= med_units * 2 and len(skus[c]) <= 2]
    if not rows:
        return []
    rows.sort(key=lambda r: -r["units"])
    return [Draft(kind="CATEGORY_DEPTH", dedupe_key=f"month:{ctx.today.strftime('%Y-%m')}", priority=4,
                  title=f"«{rows[0]['category']}» پرفروش است اما فقط {_fa(rows[0]['skus'])} قلم دارید",
                  body=(f"این دسته {_fa(rows[0]['units'])} عدد در دوره فروخته (دو برابر میانهٔ دسته‌ها) با تنها {_fa(rows[0]['skus'])} کالا. وقتی تقاضا هست و انتخاب نیست، مشتری برای همان قلم هم جای دیگر می‌رود. "
                        f"یک برند یا اندازهٔ دوم (یک ارزان‌تر، یک بهتر) معمولاً فروش دسته را ۲۰ تا ۳۰٪ بالا می‌برد."),
                  evidence={"rows": rows, "median_units": round(med_units)},
                  actions=[{"type": "note", "label": "افزودن تنوع به این دسته‌ها", "params": {}}],
                  expected_gain=sum(r["units"] for r in rows) * (30 / ctx.days) * 0.2 * 5000, metric={"metric": "avg_basket_size", "window_days": 28})]


# =============================================================================
# DAILY SURPRISE
# =============================================================================
def surprise_facts(ctx: Ctx) -> list[dict]:
    """A pool of small, checkable, *interesting* facts; ``a_surprise`` picks a different one each day."""
    e = ext(ctx)
    facts: list[dict] = []
    if not ctx.invoices:
        return facts
    # record day
    by_day: Counter = Counter()
    for inv in ctx.invoices.values():
        by_day[(inv["at"] + timedelta(hours=3, minutes=30)).date()] += inv["total"]
    if by_day:
        d, v = by_day.most_common(1)[0]
        jy, jm, jd = to_jalali(datetime.combine(d, datetime.min.time()))
        facts.append({"key": "record_day", "title": f"پرفروش‌ترین روز {_fa(ctx.days)} روز اخیر: {_fa(jd)} {JMONTH[jm-1]}", "body": f"{_money(v)} فروش در یک روز ({WEEKDAY_FA[d.weekday()]}). چه چیزی آن روز فرق داشت؟ همان را تکرار کنید."})
    # busiest hour
    hrs = Counter(_local_hour(inv["at"]) for inv in ctx.invoices.values())
    if hrs:
        h, n = hrs.most_common(1)[0]
        facts.append({"key": "busiest_hour", "title": f"ساعت {_fa(h)} شلوغ‌ترین ساعت شماست", "body": f"{_fa(n)} فاکتور در این دوره ({_fa(n/len(ctx.invoices)*100)}٪ کل). بهترین جا برای کالای تازه و پیشنهاد پای صندوق."})
    # most loyal streak
    best = None
    for cid, invs in e.by_cust.items():
        ds = sorted({i["at"].date() for i in invs})
        wk = {d.isocalendar()[:2] for d in ds}
        if not best or len(wk) > best[1]:
            best = (cid, len(wk))
    if best and best[1] >= 6:
        facts.append({"key": "loyal", "title": f"«{e.cname(best[0])}» {_fa(best[1])} هفته پیاپی آمده است", "body": "وفادارترین مشتری این دوره. یک تشکر شخصی امروز، ارزان‌ترین سرمایه‌گذاری ممکن است."})
    # most social product (most distinct partners)
    partners: dict[int, set] = defaultdict(set)
    for inv in ctx.invoices.values():
        for p in inv["pids"]:
            partners[p] |= inv["pids"] - {p}
    if partners:
        p, s = max(partners.items(), key=lambda kv: len(kv[1]))
        facts.append({"key": "social", "title": f"«{_pname(ctx, p)}» با {_fa(len(s))} کالای مختلف هم‌سبد شده", "body": "اجتماعی‌ترین کالای شما؛ کنارش هر چیزی را بگذارید دیده می‌شود."})
    # fastest grower
    rows = _trend_rows(ctx, True)
    if rows:
        r = rows[0]
        facts.append({"key": "grower", "title": f"«{r['name']}» هر هفته {_fa(r['trend_pct_per_week'])}٪ رشد می‌کند", "body": f"شش هفتهٔ اخیر: {'، '.join(_fa(x) for x in r['weekly'])} عدد. پیش‌بینی هفتهٔ بعد {_fa(r['next_week'],1)} عدد."})
    # customers registered share
    n = len(ctx.invoices)
    reg = sum(1 for inv in ctx.invoices.values() if inv["cust"])
    facts.append({"key": "registered", "title": f"{_fa(reg/n*100)}٪ فاکتورها به یک مشتری وصل‌اند", "body": "هر ۱۰٪ بیشتر یعنی پیش‌بینی دقیق‌تر خرید بعدی و پیامک‌های شخصی‌تر."})
    # profit per invoice
    pr = sum(l["profit"] for l in ctx.lines)
    facts.append({"key": "profit_per_invoice", "title": f"هر فاکتور به‌طور میانگین {_money(pr/n)} سود دارد", "body": f"یعنی هر مشتری‌ای که در صف می‌رود، همین‌قدر می‌برد. {_fa(math.ceil(1_000_000/max(1, pr/n)))} فاکتور اضافه = یک میلیون تومان سود."})
    # weekday pattern
    wd = Counter((inv["at"] + timedelta(hours=3, minutes=30)).weekday() for inv in ctx.invoices.values())
    if wd:
        w, k = wd.most_common(1)[0]
        facts.append({"key": "weekday", "title": f"{WEEKDAY_FA[w]} پرمشتری‌ترین روز هفته است", "body": f"{_fa(k)} فاکتور در این دوره؛ چیدمان و موجودی را از شب قبل آماده کنید."})
    # top margin product
    pm2: Counter = Counter()
    for l in ctx.lines:
        pm2[l["pid"]] += l["profit"]
    if pm2:
        p, v = pm2.most_common(1)[0]
        facts.append({"key": "top_profit", "title": f"«{_pname(ctx, p)}» سودآورترین کالای شماست", "body": f"{_money(v)} سود در دوره. هرگز نباید خالی بماند — حداقل موجودی‌اش را چک کنید."})
    return facts


def a_surprise(ctx: Ctx) -> list[Draft]:
    facts = surprise_facts(ctx)
    if not facts:
        return []
    f = facts[ctx.today.toordinal() % len(facts)]
    return [Draft(kind="SURPRISE", dedupe_key=f"day:{ctx.today.isoformat()}", priority=4, title="امروز می‌دانستید؟ " + f["title"], body=f["body"],
                  evidence={"fact": f["key"], "pool": len(facts)}, actions=[], expected_gain=0.0, metric={})]


# ----------------------------------------------------------------------------- registry
ANALYZERS_PRO = {
    "PAY_CYCLE": a_pay_cycle, "CUST_FAVORITE": a_cust_favorite, "CUST_ITEM_DUE": a_cust_item_due, "TICKET_DROP": a_ticket_drop, "FREQ_DROP": a_freq_drop,
    "NEW_CUST_2ND": a_new_cust_2nd, "OFFER_SENSITIVE": a_offer_sensitive, "CATEGORY_GAP": a_category_gap, "CREDIT_RISK": a_credit_risk,
    "ANNIVERSARY": a_anniversary, "BULK_BUYER": a_bulk_buyer, "THRESHOLD_UPSELL": a_threshold_upsell,
    "REORDER_POINT": a_reorder_point, "OVERSTOCK": a_overstock, "STOCKOUT_HISTORY": a_stockout_history, "TREND_UP": a_trend_up, "TREND_DOWN": a_trend_down,
    "EXPIRY_RISK_BUY": a_expiry_risk_buy, "WASTE_PATTERN": a_waste_pattern, "SHRINKAGE": a_shrinkage, "CATEGORY_TURNS": a_category_turns,
    "FIFO_BREAK": a_fifo_break, "SUPPLIER_LEAD": a_supplier_lead, "SEASONAL_YOY": a_seasonal_yoy,
    "PROFIT_PARETO": a_profit_pareto, "NEGATIVE_MARGIN": a_negative_margin, "DISCOUNT_LEAK": a_discount_leak, "PRICE_ROUNDING": a_price_rounding,
    "ELASTICITY": a_elasticity, "CATEGORY_MARGIN": a_category_margin,
    "PEAK_HOURS": a_peak_hours, "QUEUE_STRESS": a_queue_stress, "CASHIER_PERF": a_cashier_perf, "CASH_DIFF": a_cash_diff, "RETURNS_PRODUCT": a_returns_product,
    "RECEIVABLES_AGING": a_receivables_aging, "EXPENSE_SPIKE": a_expense_spike, "SMS_ROI": a_sms_roi,
    "CAMPAIGN_FATIGUE": a_campaign_fatigue, "UNREGISTERED_SALES": a_unregistered_sales, "HERO_PRODUCT": a_hero_product, "SLOW_DAY": a_slow_day,
    "BASKET_TREND": a_basket_trend, "NEW_PRODUCT_WATCH": a_new_product_watch, "CATEGORY_DEPTH": a_category_depth,
    "SURPRISE": a_surprise,
}

KIND_LABELS_PRO = {
    "PAY_CYCLE": "روز تسویهٔ مشتری", "CUST_FAVORITE": "کالای موردعلاقهٔ مشتری", "CUST_ITEM_DUE": "چرخهٔ خرید کالا", "TICKET_DROP": "کوچک‌شدن سبد",
    "FREQ_DROP": "کاهش دفعات خرید", "NEW_CUST_2ND": "خرید دوم مشتری جدید", "OFFER_SENSITIVE": "حساسیت به تخفیف", "CATEGORY_GAP": "دستهٔ خریداری‌نشده",
    "CREDIT_RISK": "ریسک نسیه", "ANNIVERSARY": "سالگرد مشتری", "BULK_BUYER": "خریدار عمده", "THRESHOLD_UPSELL": "آستانهٔ سبد",
    "REORDER_POINT": "نقطهٔ سفارش", "OVERSTOCK": "موجودی مازاد", "STOCKOUT_HISTORY": "اتمام‌های تکراری", "TREND_UP": "روند صعودی", "TREND_DOWN": "روند نزولی",
    "EXPIRY_RISK_BUY": "پیش‌بینی انقضا", "WASTE_PATTERN": "الگوی ضایعات", "SHRINKAGE": "کسری انبار", "CATEGORY_TURNS": "گردش دسته", "FIFO_BREAK": "چیدمان FIFO",
    "SUPPLIER_LEAD": "نوبت تأمین‌کننده", "SEASONAL_YOY": "الگوی سال گذشته",
    "PROFIT_PARETO": "قلب فروشگاه (۸۰/۲۰)", "NEGATIVE_MARGIN": "فروش زیر قیمت", "DISCOUNT_LEAK": "نشت تخفیف", "PRICE_ROUNDING": "گردکردن قیمت",
    "ELASTICITY": "کشش قیمتی", "CATEGORY_MARGIN": "حاشیهٔ دسته",
    "PEAK_HOURS": "ساعات اوج", "QUEUE_STRESS": "فشار صف", "CASHIER_PERF": "عملکرد صندوق‌دار", "CASH_DIFF": "کسری صندوق", "RETURNS_PRODUCT": "مرجوعی کالا",
    "RECEIVABLES_AGING": "سن طلب‌ها", "EXPENSE_SPIKE": "جهش هزینه", "SMS_ROI": "بازده کمپین",
    "CAMPAIGN_FATIGUE": "خستگی پیامکی", "UNREGISTERED_SALES": "فروش بی‌نام", "HERO_PRODUCT": "کالای قلاب", "SLOW_DAY": "روز کم‌فروش",
    "BASKET_TREND": "روند سبد", "NEW_PRODUCT_WATCH": "کالاهای تازه", "CATEGORY_DEPTH": "عمق دسته",
    "SURPRISE": "امروز می‌دانستید؟", "AI_ADVISOR": "مشاور هوش مصنوعی",
}

GROUPS = {
    "customer": ("رفتار مشتری", ["VIP", "CHURN", "VISIT_PATTERN", "PAY_CYCLE", "CUST_FAVORITE", "CUST_ITEM_DUE", "TICKET_DROP", "FREQ_DROP", "NEW_CUST_2ND", "OFFER_SENSITIVE", "CATEGORY_GAP", "CREDIT_RISK", "ANNIVERSARY", "BULK_BUYER", "THRESHOLD_UPSELL"]),
    "stock": ("انبار و پیش‌بینی", ["VELOCITY", "EXPIRY_LADDER", "DEAD_STOCK", "SUPPLIER", "REORDER_POINT", "OVERSTOCK", "STOCKOUT_HISTORY", "TREND_UP", "TREND_DOWN", "EXPIRY_RISK_BUY", "WASTE_PATTERN", "SHRINKAGE", "CATEGORY_TURNS", "FIFO_BREAK", "SUPPLIER_LEAD", "SEASONAL_YOY"]),
    "price": ("قیمت و سود", ["PRICE_GAP", "PROFIT_PARETO", "NEGATIVE_MARGIN", "DISCOUNT_LEAK", "PRICE_ROUNDING", "ELASTICITY", "CATEGORY_MARGIN"]),
    "ops": ("عملیات و مالی", ["CASHFLOW", "LOSS_PREV", "PEAK_HOURS", "QUEUE_STRESS", "CASHIER_PERF", "CASH_DIFF", "RETURNS_PRODUCT", "RECEIVABLES_AGING", "EXPENSE_SPIKE", "SMS_ROI"]),
    "growth": ("رشد و بازاریابی", ["CROSS_SELL", "BASKET_NUDGE", "SEASON", "CAMPAIGN_FATIGUE", "UNREGISTERED_SALES", "HERO_PRODUCT", "SLOW_DAY", "BASKET_TREND", "NEW_PRODUCT_WATCH", "CATEGORY_DEPTH"]),
    "daily": ("روزانه", ["SURPRISE", "AI_ADVISOR"]),
}
