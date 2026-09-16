"""v3.0 — Store Intelligence engine («هوش فروشگاه»).

Pure-local analytics over the shop's own SQLite data. No network is needed for
anything in this module; the optional cloud narrator lives in ``ai_narrator``.

Design rules
------------
* Every analyzer is a function ``(Ctx) -> list[Draft]``. It reads real
  tables, never invents numbers, and returns *evidence* the manager can check.
* Drafts are upserted by ``(kind, dedupe_key)`` so re-runs refresh instead of
  duplicating. Insights not re-confirmed for ``STALE_DAYS`` are auto-closed.
* Accepting an insight executes its ``actions`` through the normal service
  layer (campaigns / coupons / SMS / price versions / notifications), freezes a
  *baseline* of its metric, and the measurer later computes the same metric over
  an equally long *post* window → ``measured_gain`` (toman). That is the number
  the dashboard shows under «اثر پیشنهادها» — a real before/after, not a model
  guess.

Analyzers (kind codes)
----------------------
CROSS_SELL   کالاهایی که با هم خریده می‌شوند → پیشنهاد چیدمان/باندل
EXPIRY_LADDER تخفیف پله‌ای برای بچ‌های نزدیک انقضا
DEAD_STOCK   سرمایهٔ راکد → باندل با کالای پرفروش
VELOCITY     پیش‌بینی اتمام موجودی بر اساس سرعت فروش
SUPPLIER     امتیاز تأمین‌کننده (قیمت خرید، مرجوعی، انقضای کوتاه)
CASHFLOW     پیش‌بینی کسری نقدینگی با سررسید چک‌ها و هزینه‌ها
VIP          مشتریان «نهنگ» → باشگاه VIP
CHURN        مشتریان ثابتی که مدتی نیامده‌اند → پیامک بازگشت
BASKET_NUDGE پیشنهاد پای صندوق (زوج‌های قوی به‌عنوان nudge لحظه‌ای)
PRICE_GAP    حاشیهٔ سود غیرعادی (زیر کف / خیلی بالاتر از مصرف‌کننده)
LOSS_PREV    الگوی مشکوک ابطال/مرجوعی به تفکیک کاربر و ساعت
SEASON       الگوی هفتگی/فصلی فروش → شارژ کالا قبل از روزهای اوج
"""
from __future__ import annotations

import json
import logging
import math
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from itertools import combinations

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from ..models import (AuditLog, Cheque, Customer, Expense, Insight, Invoice, InvoiceItem, Product, StockMovement,
                      ProductBatch, Return, Supplier, User)
from .timeservice import local_now, local_today, local_day_range

log = logging.getLogger("supermarket.insights")

PAID = "PAID"
STALE_DAYS = 3


# ----------------------------------------------------------------------------- helpers
def _f(x) -> float:
    return float(x or 0)


def _fa(n: float | int | Decimal, digits: int = 0) -> str:
    """Persian-formatted number with thousands separators."""
    v = round(float(n), digits)
    s = f"{v:,.{digits}f}" if digits else f"{int(round(v)):,}"
    return s.translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹"))


def _money(n) -> str:
    return _fa(n) + " تومان"


@dataclass
class Draft:
    kind: str
    dedupe_key: str
    title: str
    body: str
    priority: int = 3
    evidence: dict = field(default_factory=dict)
    actions: list = field(default_factory=list)
    expected_gain: float = 0.0
    metric: dict = field(default_factory=dict)


_CLOCK: datetime | None = None   # demo/test override of "now" (UTC); None = real clock


def set_clock(dt: datetime | None) -> None:
    global _CLOCK
    _CLOCK = dt


def _now() -> datetime:
    return _CLOCK or datetime.utcnow()


def _today() -> date:
    return (_CLOCK + timedelta(hours=3, minutes=30)).date() if _CLOCK else local_today()


@dataclass
class Ctx:
    db: Session
    today: date
    now_utc: datetime
    days: int = 90
    # cached frames
    lines: list[dict] = field(default_factory=list)      # invoice lines (paid) in window
    invoices: dict[int, dict] = field(default_factory=dict)
    products: dict[int, Product] = field(default_factory=dict)

    def since(self, days: int) -> datetime:
        return self.now_utc - timedelta(days=days)


def _load_ctx(db: Session, days: int = 90) -> Ctx:
    today = _today()
    now_utc = _now()
    ctx = Ctx(db=db, today=today, now_utc=now_utc, days=days)
    since = now_utc - timedelta(days=days)
    rows = db.execute(
        select(InvoiceItem.invoice_id, InvoiceItem.product_id, InvoiceItem.qty, InvoiceItem.unit_sell_price,
               InvoiceItem.unit_buy_price, InvoiceItem.subtotal, InvoiceItem.profit, InvoiceItem.batch_id,
               Invoice.created_at, Invoice.customer_id, Invoice.total_amount, Invoice.created_by)
        .join(Invoice, Invoice.id == InvoiceItem.invoice_id)
        .where(Invoice.status == PAID, Invoice.created_at >= since)
    ).all()
    for r in rows:
        ctx.lines.append({"inv": r[0], "pid": r[1], "qty": _f(r[2]), "price": _f(r[3]), "cost": _f(r[4]),
                          "sub": _f(r[5]), "profit": _f(r[6]), "batch": r[7], "at": r[8], "cust": r[9],
                          "total": _f(r[10]), "user": r[11]})
        ctx.invoices.setdefault(r[0], {"at": r[8], "cust": r[9], "total": _f(r[10]), "pids": set(), "user": r[11]})
        ctx.invoices[r[0]]["pids"].add(r[1])
    for p in db.execute(select(Product).where(Product.is_active == True)).scalars():  # noqa: E712
        ctx.products[p.id] = p
    return ctx


def _pname(ctx: Ctx, pid: int) -> str:
    p = ctx.products.get(pid)
    return p.name if p else f"#{pid}"


def _stock(ctx: Ctx, pid: int) -> float:
    v = ctx.db.execute(select(func.coalesce(func.sum(ProductBatch.current_qty), 0))
                       .where(ProductBatch.product_id == pid, ProductBatch.status == "ACTIVE")).scalar_one()
    return _f(v)


def _daily_velocity(ctx: Ctx, pid: int, days: int = 28) -> float:
    since = ctx.since(days)
    q = sum(l["qty"] for l in ctx.lines if l["pid"] == pid and l["at"] >= since)
    return q / days


def _avg_margin(ctx: Ctx, pid: int) -> float:
    ls = [l for l in ctx.lines if l["pid"] == pid and l["qty"] > 0]
    if not ls:
        return 0.0
    return sum(l["profit"] for l in ls) / max(1e-9, sum(l["qty"] for l in ls))


# ----------------------------------------------------------------------------- analyzers
def a_cross_sell(ctx: Ctx) -> list[Draft]:
    """Association rules (support / confidence / lift) over paid baskets."""
    baskets = [inv["pids"] for inv in ctx.invoices.values() if len(inv["pids"]) >= 2]
    n = len(ctx.invoices)
    if n < 40 or len(baskets) < 20:
        return []
    item_cnt: Counter = Counter()
    pair_cnt: Counter = Counter()
    for inv in ctx.invoices.values():
        for p in inv["pids"]:
            item_cnt[p] += 1
    for b in baskets:
        for a, c in combinations(sorted(b), 2):
            pair_cnt[(a, c)] += 1
    out: list[Draft] = []
    ranked = []
    for (a, c), k in pair_cnt.items():
        if k < max(5, n * 0.02):
            continue
        sup = k / n
        conf_ac = k / item_cnt[a]
        conf_ca = k / item_cnt[c]
        lift = sup / ((item_cnt[a] / n) * (item_cnt[c] / n))
        if lift < 1.6:
            continue
        ranked.append((lift * k, a, c, k, sup, max(conf_ac, conf_ca), lift))
    ranked.sort(reverse=True)
    for score, a, c, k, sup, conf, lift in ranked[:6]:
        na, nc = _pname(ctx, a), _pname(ctx, c)
        # opportunity: baskets that contain a but not c (and vice versa) × margin of the missing item
        miss_c = item_cnt[a] - k
        miss_a = item_cnt[c] - k
        gain_month = (miss_c * _avg_margin(ctx, c) * 0.25 + miss_a * _avg_margin(ctx, a) * 0.25) * (30 / ctx.days)
        out.append(Draft(
            kind="CROSS_SELL", dedupe_key=f"pair:{a}:{c}",
            title=f"«{na}» و «{nc}» با هم خریده می‌شوند",
            body=(f"در {_fa(k)} فاکتور از {_fa(n)} فاکتور اخیر این دو کالا با هم بوده‌اند "
                  f"(اطمینان {_fa(conf*100)}٪، ضریب هم‌خرید {_fa(lift,1)}×). "
                  f"اگر کنار هم چیده شوند و صندوق‌دار هنگام اسکن یکی، دیگری را پیشنهاد دهد، "
                  f"در {_fa(miss_c + miss_a)} فاکتورِ دیگر فرصت فروش وجود داشت."),
            priority=2 if lift > 2.5 else 3,
            evidence={"pair_count": k, "invoices": n, "support": round(sup, 3), "confidence": round(conf, 2),
                      "lift": round(lift, 2), "products": [{"id": a, "name": na}, {"id": c, "name": nc}]},
            actions=[{"type": "shelf_note", "label": "یادداشت چیدمان برای انباردار", "params": {"products": [a, c]}},
                     {"type": "pos_nudge", "label": "پیشنهاد پای صندوق را فعال کن", "params": {"a": a, "b": c}}],
            expected_gain=max(0.0, gain_month),
            metric={"metric": "attach_rate", "a": a, "b": c, "window_days": 28},
        ))
    return out


def a_expiry_ladder(ctx: Ctx) -> list[Draft]:
    """Batches that will not sell out before expiry at current velocity → step markdowns."""
    out: list[Draft] = []
    rows = ctx.db.execute(
        select(ProductBatch).where(ProductBatch.status == "ACTIVE", ProductBatch.current_qty > 0,
                                   ProductBatch.expiry_date.is_not(None))
    ).scalars().all()
    for b in rows:
        days_left = (b.expiry_date - ctx.today).days
        if days_left < 0 or days_left > 45:
            continue
        v = _daily_velocity(ctx, b.product_id)
        qty = _f(b.current_qty)
        will_sell = v * days_left
        if will_sell >= qty * 0.9:
            continue
        surplus = max(0.0, qty - will_sell)
        cost, price = _f(b.buy_price), _f(b.sell_price)
        at_risk = surplus * cost
        if at_risk < 50_000:
            continue
        # ladder: 3 steps sized so that the deepest step still covers cost
        max_disc = max(5, min(60, int((1 - cost / price) * 100) - 3)) if price > 0 else 20
        steps = [max(5, max_disc // 3), max(10, (max_disc * 2) // 3), max_disc]
        s1 = max(1, days_left // 3)
        ladder = [{"from_day": 0, "percent": steps[0]}, {"from_day": s1, "percent": steps[1]}, {"from_day": 2 * s1, "percent": steps[2]}]
        recovered = surplus * price * (1 - steps[1] / 100) * 0.7  # assume ~70 % moves at mid step
        name = _pname(ctx, b.product_id)
        out.append(Draft(
            kind="EXPIRY_LADDER", dedupe_key=f"batch:{b.id}",
            title=f"{name}: {_fa(surplus)} عدد تا انقضا نمی‌فروشد",
            body=(f"{_fa(days_left)} روز تا انقضا مانده؛ سرعت فروش {_fa(v*7,1)} عدد در هفته است و از {_fa(qty)} عدد موجود "
                  f"حدود {_fa(surplus)} عدد ضایعات می‌شود ({_money(at_risk)} ضرر). "
                  f"پیشنهاد: تخفیف پله‌ای {steps[0]}٪ ← {steps[1]}٪ ← {steps[2]}٪ (آخرین پله هنوز بالای قیمت خرید است) "
                  f"و پیامک به مشتریانی که قبلاً این کالا را خریده‌اند."),
            priority=1 if days_left <= 7 else 2,
            evidence={"batch_id": b.id, "product_id": b.product_id, "days_left": days_left, "qty": qty, "velocity_per_day": round(v, 3),
                      "surplus": round(surplus, 1), "at_risk": round(at_risk), "buy": cost, "sell": price, "ladder": ladder},
            actions=[{"type": "markdown_ladder", "label": "اجرای تخفیف پله‌ای روی این بچ", "params": {"batch_id": b.id, "ladder": ladder}},
                     {"type": "sms_buyers", "label": "پیامک به خریداران قبلی", "params": {"product_id": b.product_id, "percent": steps[1]}}],
            expected_gain=recovered - 0,  # money that would otherwise be written off
            metric={"metric": "product_units", "product_id": b.product_id, "window_days": min(28, max(7, days_left))},
        ))
    out.sort(key=lambda d: (d.priority, -d.expected_gain))
    return out[:8]


def a_dead_stock(ctx: Ctx) -> list[Draft]:
    """Stock with zero/near-zero movement for 60+ days → bundle with a mover."""
    out: list[Draft] = []
    since60 = ctx.since(60)
    sold60: Counter = Counter()
    for l in ctx.lines:
        if l["at"] >= since60:
            sold60[l["pid"]] += l["qty"]
    movers = [p for p, _ in Counter({l["pid"]: l["qty"] for l in ctx.lines}).most_common(10)]
    stock_rows = ctx.db.execute(
        select(ProductBatch.product_id, func.sum(ProductBatch.current_qty), func.sum(ProductBatch.current_qty * ProductBatch.buy_price),
               func.min(ProductBatch.received_at))
        .where(ProductBatch.status == "ACTIVE", ProductBatch.current_qty > 0).group_by(ProductBatch.product_id)
    ).all()
    cands = []
    for pid, qty, value, first_rx in stock_rows:
        if pid not in ctx.products:
            continue
        age = (ctx.now_utc - first_rx).days if first_rx else 0
        if age < 45 or _f(value) < 100_000:
            continue
        if sold60[pid] > _f(qty) * 0.15:
            continue
        cands.append((_f(value), pid, _f(qty), age, sold60[pid]))
    cands.sort(reverse=True)
    total_locked = sum(c[0] for c in cands)
    for value, pid, qty, age, s60 in cands[:6]:
        partner = next((m for m in movers if m != pid), None)
        pn = _pname(ctx, partner) if partner else "کالای پرفروش"
        name = _pname(ctx, pid)
        out.append(Draft(
            kind="DEAD_STOCK", dedupe_key=f"product:{pid}",
            title=f"سرمایهٔ راکد: {name} ({_money(value)})",
            body=(f"{_fa(qty)} عدد از این کالا {_fa(age)} روز است در انبار مانده و در ۶۰ روز اخیر فقط {_fa(s60)} عدد فروخته شده. "
                  f"پیشنهاد: باندل «{name} + {pn}» با ۱۵٪ تخفیف روی کالای راکد، یا جابه‌جایی به قفسهٔ کنار صندوق. "
                  f"کل سرمایهٔ قفل‌شده در کالاهای راکد: {_money(total_locked)}."),
            priority=2 if value > 500_000 else 3,
            evidence={"product_id": pid, "qty": qty, "locked_value": round(value), "age_days": age, "sold_60d": s60,
                      "partner_id": partner, "partner_name": pn, "total_locked": round(total_locked)},
            actions=[{"type": "bundle_campaign", "label": "ساخت جشنوارهٔ باندل ۱۵٪", "params": {"product_id": pid, "partner_id": partner, "percent": 15}},
                     {"type": "shelf_note", "label": "یادداشت جابه‌جایی به کنار صندوق", "params": {"products": [pid]}}],
            expected_gain=value * 0.5 * (30 / 60),   # free half the locked cash over ~2 months
            metric={"metric": "product_units", "product_id": pid, "window_days": 28},
        ))
    return out


def a_velocity(ctx: Ctx) -> list[Draft]:
    """Days-of-cover forecast; alert before the shelf goes empty."""
    out: list[Draft] = []
    since = ctx.since(28)
    qty_by: Counter = Counter()
    days_seen: dict[int, set] = defaultdict(set)
    for l in ctx.lines:
        if l["at"] >= since:
            qty_by[l["pid"]] += l["qty"]
            days_seen[l["pid"]].add(l["at"].date())
    for pid, q in qty_by.most_common(120):
        v = q / 28
        if v <= 0 or len(days_seen[pid]) < 6:
            continue
        stock = _stock(ctx, pid)
        cover = stock / v if v > 0 else 999
        if cover > 6:
            continue
        margin = _avg_margin(ctx, pid)
        lost_per_week = v * 7 * margin
        name = _pname(ctx, pid)
        reorder = math.ceil(v * 14 - stock)   # two weeks of cover
        out.append(Draft(
            kind="VELOCITY", dedupe_key=f"product:{pid}",
            title=f"{name} تا {_fa(max(0, cover), 1)} روز دیگر تمام می‌شود",
            body=(f"میانگین فروش {_fa(v*7,1)} عدد در هفته ({_fa(len(days_seen[pid]))} روز فروش از ۲۸ روز)؛ موجودی فعلی {_fa(stock)} عدد. "
                  f"هر هفته بدون موجودی یعنی {_money(lost_per_week)} سود ازدست‌رفته. پیشنهاد سفارش: {_fa(max(reorder, 1))} عدد (پوشش ۲ هفته)."),
            priority=1 if cover <= 2 else 2,
            evidence={"product_id": pid, "velocity_per_day": round(v, 3), "stock": stock, "days_cover": round(cover, 1),
                      "sold_28d": q, "sale_days": len(days_seen[pid]), "reorder_qty": max(reorder, 1), "margin_per_unit": round(margin)},
            actions=[{"type": "reorder_note", "label": "افزودن به لیست سفارش", "params": {"product_id": pid, "qty": max(reorder, 1)}},
                     {"type": "set_min_stock", "label": "تنظیم حداقل موجودی هوشمند", "params": {"product_id": pid, "min_stock": math.ceil(v * 5)}}],
            expected_gain=lost_per_week * 2,
            metric={"metric": "availability", "product_id": pid, "window_days": 14, "margin_per_day": round(v * margin)},
        ))
    out.sort(key=lambda d: (d.priority, -d.expected_gain))
    return out[:10]


def a_supplier(ctx: Ctx) -> list[Draft]:
    """Supplier scorecard: landed price vs. best price seen, short shelf-life on receipt, returns."""
    sups = {s.id: s for s in ctx.db.execute(select(Supplier).where(Supplier.is_active == True)).scalars()}  # noqa: E712
    if len(sups) < 2:
        return []
    rows = ctx.db.execute(select(ProductBatch).where(ProductBatch.received_at >= ctx.since(180),
                                                     ProductBatch.supplier_id.is_not(None))).scalars().all()
    if not rows:
        return []
    best_price: dict[int, float] = {}
    for b in rows:
        bp = _f(b.buy_price)
        if bp > 0:
            best_price[b.product_id] = min(best_price.get(b.product_id, bp), bp)
    score: dict[int, dict] = defaultdict(lambda: {"n": 0, "over": 0.0, "short": 0, "value": 0.0})
    for b in rows:
        s = score[b.supplier_id]
        s["n"] += 1
        s["value"] += _f(b.buy_price) * _f(b.quantity_received)
        if _f(b.buy_price) > 0 and b.product_id in best_price:
            s["over"] += (_f(b.buy_price) - best_price[b.product_id]) / best_price[b.product_id]
        if b.expiry_date and b.received_at and (b.expiry_date - b.received_at.date()).days < 60:
            s["short"] += 1
    ret_by: Counter = Counter()
    for (sid, n) in ctx.db.execute(
        select(ProductBatch.supplier_id, func.count(Return.id)).join(Return, Return.batch_id == ProductBatch.id)
        .where(Return.created_at >= ctx.since(180)).group_by(ProductBatch.supplier_id)
    ).all():
        ret_by[sid] = n
    table = []
    for sid, s in score.items():
        if s["n"] < 3 or sid not in sups:
            continue
        over_pct = s["over"] / s["n"] * 100
        short_pct = s["short"] / s["n"] * 100
        ret_rate = ret_by[sid] / s["n"]
        pts = max(0, min(100, 100 - over_pct * 3 - short_pct * 0.6 - ret_rate * 40))
        table.append({"supplier_id": sid, "name": sups[sid].name, "batches": s["n"], "over_best_pct": round(over_pct, 1),
                      "short_life_pct": round(short_pct), "returns": ret_by[sid], "value": round(s["value"]), "score": round(pts)})
    if len(table) < 2:
        return []
    table.sort(key=lambda r: -r["score"])
    worst, best = table[-1], table[0]
    if worst["score"] >= 70:
        return []
    saving = worst["value"] * (worst["over_best_pct"] / 100) * (30 / 180)
    return [Draft(
        kind="SUPPLIER", dedupe_key=f"supplier:{worst['supplier_id']}",
        title=f"تأمین‌کنندهٔ «{worst['name']}» امتیاز {_fa(worst['score'])} از ۱۰۰",
        body=(f"قیمت خرید به‌طور میانگین {_fa(worst['over_best_pct'],1)}٪ بالاتر از بهترین قیمتی است که برای همان کالاها داشته‌اید، "
              f"{_fa(worst['short_life_pct'])}٪ بچ‌ها با کمتر از ۶۰ روز تاریخ تحویل شده و {_fa(worst['returns'])} مرجوعی ثبت شده. "
              f"بهترین شریک شما «{best['name']}» با امتیاز {_fa(best['score'])} است. پیشنهاد: کالاهای مشترک را از «{best['name']}» بگیرید "
              f"یا با همین ارقام برای تخفیف مذاکره کنید."),
        priority=3, evidence={"table": table},
        actions=[{"type": "note", "label": "ذخیرهٔ کارت امتیاز برای جلسهٔ مذاکره", "params": {"supplier_id": worst["supplier_id"]}}],
        expected_gain=saving,
        metric={"metric": "purchase_over_best", "supplier_id": worst["supplier_id"], "window_days": 60},
    )]


def a_cashflow(ctx: Ctx) -> list[Draft]:
    """Cash-in forecast (avg daily net sales cash) vs. cash-out (cheques due + recurring expenses)."""
    horizon = 30
    since = ctx.since(56)
    daily: dict[date, float] = defaultdict(float)
    for inv in ctx.invoices.values():
        if inv["at"] >= since:
            daily[inv["at"].date()] += inv["total"]
    if len(daily) < 14:
        return []
    avg_in = sum(daily.values()) / 56
    # expenses: average monthly of the last 90 days
    exp_total = _f(ctx.db.execute(select(func.coalesce(func.sum(Expense.amount), 0))
                                  .where(Expense.expense_date >= ctx.today - timedelta(days=90))).scalar_one())
    exp_daily = exp_total / 90
    cheques = ctx.db.execute(select(Cheque).where(Cheque.status == "PENDING", Cheque.direction == "ISSUED",
                                                  Cheque.due_date >= ctx.today, Cheque.due_date <= ctx.today + timedelta(days=horizon))
                             .order_by(Cheque.due_date)).scalars().all()
    incoming = ctx.db.execute(select(Cheque).where(Cheque.status == "PENDING", Cheque.direction == "RECEIVED",
                                                   Cheque.due_date >= ctx.today, Cheque.due_date <= ctx.today + timedelta(days=horizon))).scalars().all()
    # purchases: average of last 60 days receiving cost per day (cash-out for stock)
    buy_total = _f(ctx.db.execute(select(func.coalesce(func.sum(ProductBatch.buy_price * ProductBatch.quantity_received), 0))
                                  .where(ProductBatch.received_at >= ctx.since(60))).scalar_one())
    buy_daily = buy_total / 60
    # opening cash: from cash sessions is optional; we project *net* cumulative position from zero
    bal, low, low_day, timeline = 0.0, 0.0, ctx.today, []
    for d in range(1, horizon + 1):
        day = ctx.today + timedelta(days=d)
        out_ch = sum(_f(c.amount) for c in cheques if c.due_date == day)
        in_ch = sum(_f(c.amount) for c in incoming if c.due_date == day)
        bal += avg_in - exp_daily - buy_daily - out_ch + in_ch
        timeline.append({"day": day.isoformat(), "balance": round(bal), "cheques_out": round(out_ch), "cheques_in": round(in_ch)})
        if bal < low:
            low, low_day = bal, day
    if low >= -avg_in * 2:   # shortfall smaller than two days of sales is noise
        return []
    biggest = max(cheques, key=lambda c: _f(c.amount)) if cheques else None
    body = (f"با فروش میانگین {_money(avg_in)} در روز و هزینه/خرید روزانهٔ حدود {_money(exp_daily + buy_daily)}، "
            f"سررسید {_fa(len(cheques))} چک صادره ({_money(sum(_f(c.amount) for c in cheques))}) در ۳۰ روز آینده باعث "
            f"کسری تقریبی {_money(-low)} در تاریخ {low_day.isoformat()} می‌شود. ")
    if biggest:
        body += f"بزرگ‌ترین چک: {_money(biggest.amount)} به «{biggest.party_name or '—'}» در {biggest.due_date.isoformat()}. "
    body += "پیشنهاد: وصول بدهی مشتریان با پیامک یادآوری، جابه‌جایی سررسید بزرگ‌ترین چک یا فروش ویژهٔ ۳ روزهٔ کالاهای راکد."
    return [Draft(
        kind="CASHFLOW", dedupe_key=f"month:{ctx.today.strftime('%Y-%m')}",
        title=f"هشدار نقدینگی: کسری {_money(-low)} تا {(low_day - ctx.today).days} روز دیگر",
        body=body, priority=1,
        evidence={"avg_daily_sales": round(avg_in), "expense_daily": round(exp_daily), "purchase_daily": round(buy_daily),
                  "cheques_out": [{"due": c.due_date.isoformat(), "amount": _f(c.amount), "party": c.party_name} for c in cheques],
                  "lowest": round(low), "lowest_day": low_day.isoformat(), "timeline": timeline},
        actions=[{"type": "debt_reminders", "label": "پیامک یادآوری به همهٔ بدهکاران", "params": {}},
                 {"type": "flash_sale", "label": "فروش ویژهٔ ۳ روزهٔ کالاهای راکد", "params": {"percent": 15, "days": 3}}],
        expected_gain=0.0,
        metric={"metric": "receivables_collected", "window_days": 14},
    )]


def _customer_stats(ctx: Ctx) -> dict[int, dict]:
    st: dict[int, dict] = defaultdict(lambda: {"n": 0, "sum": 0.0, "profit": 0.0, "first": None, "last": None, "gaps": []})
    seen_inv: set[int] = set()
    for l in ctx.lines:
        if not l["cust"]:
            continue
        s = st[l["cust"]]
        s["profit"] += l["profit"]
        if l["inv"] in seen_inv:
            continue
        seen_inv.add(l["inv"])
        s["n"] += 1
        s["sum"] += l["total"]
        s["first"] = l["at"] if not s["first"] or l["at"] < s["first"] else s["first"]
        s["last"] = l["at"] if not s["last"] or l["at"] > s["last"] else s["last"]
    for cid, s in st.items():
        dates = sorted({inv["at"].date() for inv in ctx.invoices.values() if inv["cust"] == cid})
        s["gaps"] = [(b - a).days for a, b in zip(dates, dates[1:])]
    return st


def a_vip(ctx: Ctx) -> list[Draft]:
    st = _customer_stats(ctx)
    if len(st) < 10:
        return []
    ranked = sorted(st.items(), key=lambda kv: -kv[1]["profit"])
    total_profit = sum(s["profit"] for s in st.values()) or 1
    top = ranked[:max(3, len(ranked) // 10)]
    share = sum(s["profit"] for _, s in top) / total_profit
    if share < 0.25:
        return []
    names = {c.id: f"{c.name} {c.last_name or ''}".strip() for c in ctx.db.execute(select(Customer).where(Customer.id.in_([c for c, _ in top]))).scalars()}
    rows = [{"customer_id": cid, "name": names.get(cid, str(cid)), "invoices": s["n"], "sales": round(s["sum"]), "profit": round(s["profit"])} for cid, s in top]
    return [Draft(
        kind="VIP", dedupe_key=f"quarter:{ctx.today.year}-{(ctx.today.month-1)//3}",
        title=f"{_fa(len(top))} مشتری، {_fa(share*100)}٪ سود شما را می‌سازند",
        body=(f"این {_fa(len(top))} نفر در {_fa(ctx.days)} روز اخیر {_money(sum(r['sales'] for r in rows))} خرید و "
              f"{_money(sum(r['profit'] for r in rows))} سود آورده‌اند. پیشنهاد: باشگاه VIP — کوپن ۵٪ ماهانه با پیامک شخصی، "
              f"اولویت در کالاهای کمیاب، و تبریک مناسبت‌ها. هزینهٔ حفظ این‌ها بسیار کمتر از جذب مشتری جدید است."),
        priority=2, evidence={"rows": rows, "profit_share": round(share, 3), "customers": len(st)},
        actions=[{"type": "vip_coupons", "label": "صدور کوپن VIP ۵٪ + پیامک", "params": {"customer_ids": [r["customer_id"] for r in rows], "percent": 5, "days": 30}}],
        expected_gain=sum(r["profit"] for r in rows) * (30 / ctx.days) * 0.10,
        metric={"metric": "customer_sales", "customer_ids": [r["customer_id"] for r in rows], "window_days": 28},
    )]


def a_churn(ctx: Ctx) -> list[Draft]:
    st = _customer_stats(ctx)
    out_rows = []
    for cid, s in st.items():
        if s["n"] < 4 or len(s["gaps"]) < 3:
            continue
        typical = sorted(s["gaps"])[len(s["gaps"]) // 2]   # median gap
        silent = (ctx.now_utc - s["last"]).days
        if silent > max(14, typical * 2.5):
            out_rows.append({"customer_id": cid, "silent_days": silent, "typical_gap": typical, "invoices": s["n"],
                             "avg_ticket": round(s["sum"] / s["n"]), "monthly_profit": round(s["profit"] / (ctx.days / 30))})
    if not out_rows:
        return []
    out_rows.sort(key=lambda r: -r["monthly_profit"])
    out_rows = out_rows[:25]
    names = {c.id: (f"{c.name} {c.last_name or ''}".strip(), c.phone) for c in ctx.db.execute(select(Customer).where(Customer.id.in_([r["customer_id"] for r in out_rows]))).scalars()}
    for r in out_rows:
        r["name"], r["phone"] = names.get(r["customer_id"], (str(r["customer_id"]), None))
    at_risk = sum(r["monthly_profit"] for r in out_rows)
    return [Draft(
        kind="CHURN", dedupe_key=f"week:{ctx.today.isocalendar()[1]}",
        title=f"{_fa(len(out_rows))} مشتری ثابت مدتی است نیامده‌اند",
        body=(f"این مشتریان به‌طور معمول هر {_fa(sorted(r['typical_gap'] for r in out_rows)[len(out_rows)//2])} روز خرید می‌کردند اما "
              f"اکنون بیش از دو برابر آن غایب‌اند. سود ماهانهٔ در خطر: {_money(at_risk)}. "
              f"پیشنهاد: پیامک بازگشت با کوپن ۱۰٪ یک‌هفته‌ای؛ تجربه نشان می‌دهد ۲۰ تا ۳۰٪ برمی‌گردند."),
        priority=2, evidence={"rows": out_rows, "monthly_profit_at_risk": round(at_risk)},
        actions=[{"type": "winback_sms", "label": "پیامک بازگشت + کوپن ۱۰٪ (۷ روز)", "params": {"customer_ids": [r["customer_id"] for r in out_rows], "percent": 10, "days": 7}}],
        expected_gain=at_risk * 0.25,
        metric={"metric": "customer_sales", "customer_ids": [r["customer_id"] for r in out_rows], "window_days": 21},
    )]


def a_basket_nudge(ctx: Ctx) -> list[Draft]:
    """Rules strong enough to whisper to the cashier in real time (served by /insights/nudges)."""
    # Represented as a single insight with the rule table; acceptance turns the POS hint on.
    n = len(ctx.invoices)
    if n < 60:
        return []
    item_cnt: Counter = Counter()
    pair_cnt: Counter = Counter()
    for inv in ctx.invoices.values():
        for p in inv["pids"]:
            item_cnt[p] += 1
        for a, c in combinations(sorted(inv["pids"]), 2):
            pair_cnt[(a, c)] += 1
    rules = []
    for (a, c), k in pair_cnt.items():
        if k < 6:
            continue
        for x, y in ((a, c), (c, a)):
            conf = k / item_cnt[x]
            lift = (k / n) / ((item_cnt[x] / n) * (item_cnt[y] / n))
            if conf >= 0.35 and lift >= 1.8:
                rules.append({"if": x, "then": y, "if_name": _pname(ctx, x), "then_name": _pname(ctx, y), "confidence": round(conf, 2), "lift": round(lift, 2), "count": k})
    if len(rules) < 3:
        return []
    rules.sort(key=lambda r: -(r["confidence"] * r["lift"]))
    rules = rules[:30]
    gain = sum(_avg_margin(ctx, r["then"]) * item_cnt[r["if"]] * (1 - r["confidence"]) * 0.15 for r in rules) * (30 / ctx.days)
    return [Draft(
        kind="BASKET_NUDGE", dedupe_key="rules",
        title=f"{_fa(len(rules))} پیشنهاد لحظه‌ای برای صندوق‌دار آماده است",
        body=(f"وقتی مثلاً «{rules[0]['if_name']}» اسکن می‌شود، {_fa(rules[0]['confidence']*100)}٪ مواقع «{rules[0]['then_name']}» هم خریده شده. "
              f"با فعال‌سازی، صندوق (رایانه و گوشی) هنگام اسکن یک خط کوچک «پیشنهاد» نشان می‌دهد؛ صندوق‌دار فقط یک جمله می‌گوید. "
              f"نه پاپ‌آپ، نه مزاحمت."),
        priority=2, evidence={"rules": rules, "invoices": n},
        actions=[{"type": "enable_nudges", "label": "فعال‌سازی پیشنهاد پای صندوق", "params": {}}],
        expected_gain=gain,
        metric={"metric": "avg_basket_size", "window_days": 28},
    )]


def a_price_gap(ctx: Ctx) -> list[Draft]:
    out: list[Draft] = []
    rows = ctx.db.execute(select(ProductBatch).where(ProductBatch.status == "ACTIVE", ProductBatch.current_qty > 0)).scalars().all()
    seen: set[int] = set()
    for b in rows:
        if b.product_id in seen:
            continue
        cost, sell, cons = _f(b.buy_price), _f(b.sell_price), _f(b.consumer_price)
        if cost <= 0 or sell <= 0:
            continue
        margin = (sell - cost) / sell
        v = _daily_velocity(ctx, b.product_id)
        if margin < 0.03 and v > 0.2:
            seen.add(b.product_id)
            new_price = round(cost * 1.12 / 100) * 100
            out.append(Draft(
                kind="PRICE_GAP", dedupe_key=f"low:{b.product_id}",
                title=f"{_pname(ctx, b.product_id)} تقریباً بدون سود فروخته می‌شود",
                body=(f"قیمت خرید {_money(cost)} و فروش {_money(sell)} → حاشیهٔ {_fa(margin*100,1)}٪ با {_fa(v*7,1)} فروش در هفته. "
                      f"پیشنهاد: قیمت {_money(new_price)}" + (f" (مصرف‌کننده {_money(cons)})" if cons else "") + "."),
                priority=2, evidence={"product_id": b.product_id, "batch_id": b.id, "buy": cost, "sell": sell, "consumer": cons, "margin": round(margin, 3), "velocity": round(v, 2)},
                actions=[{"type": "set_price", "label": f"تغییر قیمت به {_money(new_price)}", "params": {"batch_id": b.id, "sell_price": new_price}}],
                expected_gain=(new_price - sell) * v * 30,
                metric={"metric": "product_profit", "product_id": b.product_id, "window_days": 28},
            ))
        elif cons and sell > cons * 1.02 and v > 0:
            seen.add(b.product_id)
            out.append(Draft(
                kind="PRICE_GAP", dedupe_key=f"over:{b.product_id}",
                title=f"{_pname(ctx, b.product_id)} بالاتر از قیمت مصرف‌کننده است",
                body=f"فروش {_money(sell)} در حالی که قیمت درج‌شده {_money(cons)} است؛ ریسک شکایت و از دست دادن اعتماد. پیشنهاد: اصلاح به قیمت مصرف‌کننده.",
                priority=1, evidence={"product_id": b.product_id, "batch_id": b.id, "sell": sell, "consumer": cons},
                actions=[{"type": "set_price", "label": "اصلاح به قیمت مصرف‌کننده", "params": {"batch_id": b.id, "sell_price": cons}}],
                expected_gain=0.0, metric={"metric": "product_units", "product_id": b.product_id, "window_days": 28},
            ))
    out.sort(key=lambda d: (d.priority, -d.expected_gain))
    return out[:8]


def a_loss_prevention(ctx: Ctx) -> list[Draft]:
    """Voids / returns / no-sale drawer opens per cashier vs. peers, plus after-hours activity."""
    since = ctx.since(60)
    sales_by_user: Counter = Counter()
    for inv in ctx.invoices.values():
        if inv["at"] >= since and inv["user"]:
            sales_by_user[inv["user"]] += 1
    if sum(sales_by_user.values()) < 100 or len(sales_by_user) < 2:
        return []
    voids: Counter = Counter()
    for uid, n in ctx.db.execute(select(AuditLog.user_id, func.count(AuditLog.id)).where(AuditLog.action == "SALE_VOIDED", AuditLog.created_at >= since).group_by(AuditLog.user_id)).all():
        voids[uid] = n
    drawer: Counter = Counter()
    for uid, n in ctx.db.execute(select(AuditLog.user_id, func.count(AuditLog.id)).where(AuditLog.action == "DRAWER_OPENED", AuditLog.created_at >= since).group_by(AuditLog.user_id)).all():
        drawer[uid] = n
    returns: Counter = Counter()
    for uid, n in ctx.db.execute(select(Return.created_by, func.count(Return.id)).where(Return.created_at >= since).group_by(Return.created_by)).all():
        returns[uid] = n
    users = {u.id: u.full_name or u.username for u in ctx.db.execute(select(User)).scalars()}
    rows = []
    for uid, n in sales_by_user.items():
        rows.append({"user_id": uid, "name": users.get(uid, str(uid)), "sales": n, "void_rate": voids[uid] / n,
                     "return_rate": returns[uid] / n, "drawer_rate": drawer[uid] / n})
    med = lambda k: sorted(r[k] for r in rows)[len(rows) // 2]  # noqa: E731
    flagged = []
    for r in rows:
        why = []
        if r["void_rate"] > max(0.03, med("void_rate") * 3):
            why.append(f"نرخ ابطال {_fa(r['void_rate']*100,1)}٪ (میانه {_fa(med('void_rate')*100,1)}٪)")
        if r["return_rate"] > max(0.03, med("return_rate") * 3):
            why.append(f"نرخ مرجوعی {_fa(r['return_rate']*100,1)}٪")
        if r["drawer_rate"] > max(0.10, med("drawer_rate") * 3):
            why.append(f"باز کردن کشو بدون فروش {_fa(r['drawer_rate']*100,1)}٪")
        if why and r["sales"] >= 30:
            flagged.append((r, why))
    out = []
    for r, why in flagged:
        out.append(Draft(
            kind="LOSS_PREV", dedupe_key=f"user:{r['user_id']}",
            title=f"الگوی غیرعادی در صندوق «{r['name']}»",
            body=("در ۶۰ روز اخیر: " + "، ".join(why) + ". این لزوماً تقلب نیست (ممکن است آموزش یا مشتری خاص باشد)، "
                  "اما ارزش یک گفت‌وگوی دوستانه و بررسی چند فاکتور باطل‌شده را دارد."),
            priority=1, evidence={"row": r, "peers": rows},
            actions=[{"type": "note", "label": "یادداشت بررسی برای مدیر", "params": {"user_id": r["user_id"]}}],
            expected_gain=0.0, metric={"metric": "void_rate", "user_id": r["user_id"], "window_days": 30},
        ))
    return out


def a_season(ctx: Ctx) -> list[Draft]:
    """Weekday pattern → which day peaks, and which products spike on that day."""
    if len(ctx.invoices) < 150:
        return []
    by_wd: dict[int, list[float]] = defaultdict(list)
    daily: dict[date, float] = defaultdict(float)
    for inv in ctx.invoices.values():
        daily[inv["at"].date()] += inv["total"]
    for d, s in daily.items():
        by_wd[d.weekday()].append(s)
    avg = {wd: sum(v) / len(v) for wd, v in by_wd.items() if len(v) >= 3}
    if len(avg) < 5:
        return []
    overall = sum(avg.values()) / len(avg)
    peak = max(avg, key=avg.get)
    if avg[peak] < overall * 1.15:
        return []
    names_fa = ["دوشنبه", "سه‌شنبه", "چهارشنبه", "پنجشنبه", "جمعه", "شنبه", "یکشنبه"]
    # products that over-index on the peak weekday
    p_all: Counter = Counter(); p_peak: Counter = Counter()
    for l in ctx.lines:
        p_all[l["pid"]] += l["qty"]
        if l["at"].weekday() == peak:
            p_peak[l["pid"]] += l["qty"]
    share_peak = len([d for d in daily if d.weekday() == peak]) / max(1, len(daily))
    spikes = []
    for pid, q in p_all.most_common(80):
        if q < 20:
            continue
        idx = (p_peak[pid] / q) / share_peak if share_peak else 0
        if idx > 1.4:
            spikes.append({"product_id": pid, "name": _pname(ctx, pid), "index": round(idx, 2), "qty_total": q})
    spikes = spikes[:8]
    days_ahead = (peak - ctx.today.weekday()) % 7
    return [Draft(
        kind="SEASON", dedupe_key=f"weekday:{peak}",
        title=f"{names_fa[peak]}‌ها {_fa((avg[peak]/overall-1)*100)}٪ بیشتر از میانگین می‌فروشید",
        body=(f"میانگین فروش {names_fa[peak]} {_money(avg[peak])} در برابر میانگین هفته {_money(overall)}. "
              + (f"کالاهایی که آن روز بیشتر می‌روند: " + "، ".join(s["name"] for s in spikes[:5]) + ". " if spikes else "")
              + f"پیشنهاد: تا {_fa(days_ahead)} روز دیگر قفسه‌ها و صندوق دوم را برای اوج آماده کنید."),
        priority=3, evidence={"weekday_avg": {names_fa[k]: round(v) for k, v in avg.items()}, "peak": names_fa[peak], "spikes": spikes},
        actions=[{"type": "reorder_note", "label": "افزودن کالاهای اوج به لیست سفارش", "params": {"products": [s["product_id"] for s in spikes]}}],
        expected_gain=0.0, metric={"metric": "weekday_sales", "weekday": peak, "window_days": 28},
    )]


# ----------------------------------------------------------------------------- v3.2 customer purchase-pattern prediction
WEEKDAY_FA = ["دوشنبه", "سه‌شنبه", "چهارشنبه", "پنجشنبه", "جمعه", "شنبه", "یکشنبه"]


def customer_patterns(ctx: Ctx, *, min_visits: int = 5, horizon_days: int = 3) -> list[dict]:
    """Per-customer rhythm model: median gap between visits (robust to one-off trips), its spread,
    the usual weekday/hour, the usual basket and the predicted next visit. Returns the customers
    whose predicted visit falls inside [today − 1, today + horizon] and who have not come yet,
    sorted by monthly profit — the list a shop owner should message *today*."""
    visits: dict[int, list[datetime]] = defaultdict(list)
    totals: dict[int, float] = defaultdict(float)
    profit: dict[int, float] = defaultdict(float)
    items: dict[int, Counter] = defaultdict(Counter)
    for inv_id, inv in ctx.invoices.items():
        if inv["cust"]:
            visits[inv["cust"]].append(inv["at"])
            totals[inv["cust"]] += inv["total"]
    for l in ctx.lines:
        if l["cust"]:
            profit[l["cust"]] += l["profit"]
            items[l["cust"]][l["pid"]] += 1
    out = []
    now = ctx.now_utc
    for cid, vs in visits.items():
        days = sorted({v.date() for v in vs})
        if len(days) < min_visits:
            continue
        gaps = [(b - a).days for a, b in zip(days, days[1:]) if (b - a).days > 0]
        if len(gaps) < 3:
            continue
        gaps_s = sorted(gaps)
        med = gaps_s[len(gaps_s) // 2]
        mad = sorted(abs(g - med) for g in gaps)[len(gaps) // 2]   # median absolute deviation
        regularity = max(0.0, 1 - mad / max(1.0, med))              # 1 = clockwork, 0 = random
        last = days[-1]
        nxt = last + timedelta(days=med)
        due_in = (nxt - ctx.today).days
        if due_in < -1 or due_in > horizon_days:
            continue
        if last == ctx.today:
            continue
        wd = Counter(v.weekday() for v in vs).most_common(1)[0][0]
        hour = Counter(((v + timedelta(hours=3, minutes=30)).hour) for v in vs).most_common(1)[0][0]
        top = [{"product_id": p, "name": _pname(ctx, p), "times": n} for p, n in items[cid].most_common(4)]
        out.append({"customer_id": cid, "visits": len(days), "typical_gap": med, "regularity": round(regularity, 2),
                    "last_visit": last.isoformat(), "predicted": nxt.isoformat(), "due_in": due_in,
                    "usual_weekday": WEEKDAY_FA[wd], "usual_hour": hour, "avg_ticket": round(totals[cid] / len(vs)),
                    "monthly_profit": round(profit[cid] / (ctx.days / 30)), "usual_items": top})
    if not out:
        return []
    names = {c.id: (f"{c.name} {c.last_name or ''}".strip(), c.phone) for c in ctx.db.execute(select(Customer).where(Customer.id.in_([r["customer_id"] for r in out]))).scalars()}
    for r in out:
        r["name"], r["phone"] = names.get(r["customer_id"], (str(r["customer_id"]), None))
    out.sort(key=lambda r: (-r["regularity"] * r["monthly_profit"]))
    return out


def a_visit_pattern(ctx: Ctx) -> list[Draft]:
    """«این هفته چه کسی می‌آید؟» — customers whose rhythm says they are due in the next 3 days,
    with what they usually buy; one tap sends each a personal reminder (with their usual item)."""
    rows = customer_patterns(ctx)
    rows = [r for r in rows if r["regularity"] >= 0.35][:30]
    if len(rows) < 3:
        return []
    with_phone = [r for r in rows if r["phone"]]
    month_profit = sum(r["monthly_profit"] for r in rows)
    ex = rows[0]
    body = (f"از روی فاصلهٔ خریدهای هر مشتری، {_fa(len(rows))} مشتری ثابت در ۳ روز آینده نوبت خریدشان است "
            f"(مثلاً «{ex['name']}» معمولاً هر {_fa(ex['typical_gap'])} روز، {ex['usual_weekday']}‌ها ساعت {_fa(ex['usual_hour'])}، "
            f"و بیشتر «{ex['usual_items'][0]['name'] if ex['usual_items'] else '—'}» می‌خرد). "
            f"یک پیامک کوتاه و شخصی درست قبل از نوبتشان — «فلان کالای همیشگی‌تان رسیده» — احتمال آمدن و اندازهٔ سبد را بالا می‌برد. "
            f"سود ماهانهٔ این گروه: {_money(month_profit)}؛ {_fa(len(with_phone))} نفر شماره دارند.")
    return [Draft(
        kind="VISIT_PATTERN", dedupe_key=f"day:{ctx.today.isoformat()}",
        title=f"{_fa(len(rows))} مشتری ثابت طی ۳ روز آینده می‌آیند — پیامک شخصی بفرستید",
        body=body, priority=2,
        evidence={"rows": rows, "monthly_profit": round(month_profit), "with_phone": len(with_phone),
                  "gap_hist": Counter(min(14, r["typical_gap"]) for r in rows).most_common()},
        actions=[{"type": "visit_sms", "label": "پیامک شخصی «کالای همیشگی‌تان» به مشتریان در نوبت",
                  "params": {"customers": [{"customer_id": r["customer_id"], "item": (r["usual_items"][0]["name"] if r["usual_items"] else "")} for r in with_phone]}}],
        expected_gain=month_profit * 0.12,
        metric={"metric": "customer_sales", "customer_ids": [r["customer_id"] for r in rows], "window_days": 14},
    )]


ANALYZERS = {
    "CROSS_SELL": a_cross_sell, "EXPIRY_LADDER": a_expiry_ladder, "DEAD_STOCK": a_dead_stock, "VELOCITY": a_velocity,
    "SUPPLIER": a_supplier, "CASHFLOW": a_cashflow, "VIP": a_vip, "CHURN": a_churn, "BASKET_NUDGE": a_basket_nudge,
    "PRICE_GAP": a_price_gap, "LOSS_PREV": a_loss_prevention, "SEASON": a_season, "VISIT_PATTERN": a_visit_pattern,
}

KIND_LABELS = {
    "CROSS_SELL": "هم‌خرید و چیدمان", "EXPIRY_LADDER": "حراج تاریخ انقضا", "DEAD_STOCK": "سرمایهٔ راکد", "VELOCITY": "هشدار اتمام موجودی",
    "SUPPLIER": "امتیاز تأمین‌کننده", "CASHFLOW": "نقدینگی و چک‌ها", "VIP": "مشتریان VIP", "CHURN": "بازگشت مشتری",
    "BASKET_NUDGE": "پیشنهاد پای صندوق", "PRICE_GAP": "قیمت‌گذاری", "LOSS_PREV": "کنترل تقلب", "SEASON": "الگوی هفتگی",
    "VISIT_PATTERN": "پیش‌بینی خرید مشتری",
}

# v3.5 — the PRO pack (46 more analyzers) registers itself here; it imports the helpers above,
# so the import must stay below them.
from . import insights_pro as _pro  # noqa: E402
ANALYZERS.update(_pro.ANALYZERS_PRO)
KIND_LABELS.update(_pro.KIND_LABELS_PRO)
GROUPS = _pro.GROUPS


# ----------------------------------------------------------------------------- run / upsert
def run(db: Session, *, kinds: list[str] | None = None, days: int = 90) -> dict:
    ctx = _load_ctx(db, days)
    created = refreshed = 0
    errors: dict[str, str] = {}
    seen: set[tuple[str, str]] = set()
    from . import forecast   # v3.1 — learned per-kind calibration of the expected gain
    cal = forecast._load_cal(db)
    for kind, fn in ANALYZERS.items():
        if kinds and kind not in kinds:
            continue
        try:
            drafts = fn(ctx)
        except Exception as exc:  # one broken analyzer must not stop the rest
            log.exception("analyzer %s failed", kind)
            errors[kind] = str(exc)
            continue
        for d in drafts:
            seen.add((d.kind, d.dedupe_key))
            # keep the analyzer's raw estimate (for learning) and expose the calibrated one
            raw = float(d.expected_gain or 0.0)
            c = forecast.calibrate(db, d.kind, raw, cal)
            d.evidence = {**d.evidence, "expected_gain_raw": round(raw), "forecast": {"gain_month": c["gain"], "low_month": c["low"], "high_month": c["high"], "confidence": c["confidence"], "history_n": c["n"]}}
            d.expected_gain = c["gain"]
            row = db.execute(select(Insight).where(Insight.kind == d.kind, Insight.dedupe_key == d.dedupe_key,
                                                   Insight.status.in_(["NEW", "SNOOZED", "ACCEPTED"]))).scalar_one_or_none()
            if row:
                if row.status == "NEW":
                    row.title, row.body, row.priority = d.title, d.body, d.priority
                    row.evidence, row.actions = json.dumps(d.evidence, ensure_ascii=False, default=str), json.dumps(d.actions, ensure_ascii=False)
                    row.expected_gain, row.metric = Decimal(str(round(d.expected_gain))), json.dumps(d.metric, ensure_ascii=False)
                row.last_seen_at = ctx.now_utc
                refreshed += 1
            else:
                db.add(Insight(kind=d.kind, dedupe_key=d.dedupe_key, title=d.title, body=d.body, priority=d.priority,
                               evidence=json.dumps(d.evidence, ensure_ascii=False, default=str), actions=json.dumps(d.actions, ensure_ascii=False),
                               expected_gain=Decimal(str(round(d.expected_gain))), metric=json.dumps(d.metric, ensure_ascii=False),
                               status="NEW", last_seen_at=ctx.now_utc))
                created += 1
    # auto-close stale NEW insights that no analyzer re-confirmed
    stale_before = ctx.now_utc - timedelta(days=STALE_DAYS)
    for row in db.execute(select(Insight).where(Insight.status == "NEW", Insight.last_seen_at < stale_before)).scalars():
        if (row.kind, row.dedupe_key) not in seen and (not kinds or row.kind in kinds):
            row.status = "EXPIRED"
    # wake snoozed
    for row in db.execute(select(Insight).where(Insight.status == "SNOOZED", Insight.snoozed_until <= ctx.now_utc)).scalars():
        row.status = "NEW"
    db.commit()
    measure_all(db)
    return {"created": created, "refreshed": refreshed, "errors": errors, "invoices_analyzed": len(ctx.invoices), "window_days": days}


# ----------------------------------------------------------------------------- metrics / A-B
def _net_profit(db: Session, where) -> float:
    """Σ line profit − invoice-level discounts (coupons / whole-invoice discounts are a real
    cost of the action and must be charged against it)."""
    line = db.execute(select(func.coalesce(func.sum(InvoiceItem.profit), 0), func.coalesce(func.sum(InvoiceItem.discount), 0))
                      .join(Invoice, Invoice.id == InvoiceItem.invoice_id).where(where)).one()
    inv_disc = db.execute(select(func.coalesce(func.sum(Invoice.discount), 0)).where(where)).scalar_one()
    return _f(line[0]) - max(0.0, _f(inv_disc) - _f(line[1]))


def _metric_value(db: Session, spec: dict, start: datetime, end: datetime) -> dict:
    """Compute the metric over [start, end) on real data. Returns {"value", "unit", "detail"}."""
    m = spec.get("metric")
    paid = and_(Invoice.status == PAID, Invoice.created_at >= start, Invoice.created_at < end)
    if m == "product_units":
        v = db.execute(select(func.coalesce(func.sum(InvoiceItem.qty), 0)).join(Invoice, Invoice.id == InvoiceItem.invoice_id)
                       .where(paid, InvoiceItem.product_id == spec["product_id"])).scalar_one()
        pr = db.execute(select(func.coalesce(func.sum(InvoiceItem.profit), 0)).join(Invoice, Invoice.id == InvoiceItem.invoice_id)
                        .where(paid, InvoiceItem.product_id == spec["product_id"])).scalar_one()
        return {"value": _f(v), "unit": "عدد", "profit": _f(pr)}
    if m == "product_profit":
        pr = db.execute(select(func.coalesce(func.sum(InvoiceItem.profit), 0)).join(Invoice, Invoice.id == InvoiceItem.invoice_id)
                        .where(paid, InvoiceItem.product_id == spec["product_id"])).scalar_one()
        return {"value": _f(pr), "unit": "تومان", "profit": _f(pr)}
    if m == "customer_sales":
        ids = spec.get("customer_ids") or []
        s = db.execute(select(func.coalesce(func.sum(Invoice.total_amount), 0)).where(paid, Invoice.customer_id.in_(ids))).scalar_one()
        pr = _net_profit(db, and_(paid, Invoice.customer_id.in_(ids)))
        return {"value": _f(s), "unit": "تومان", "profit": pr}
    if m == "attach_rate":
        a, b = spec["a"], spec["b"]
        inv_a = {r[0] for r in db.execute(select(InvoiceItem.invoice_id).join(Invoice, Invoice.id == InvoiceItem.invoice_id).where(paid, InvoiceItem.product_id == a)).all()}
        inv_b = {r[0] for r in db.execute(select(InvoiceItem.invoice_id).join(Invoice, Invoice.id == InvoiceItem.invoice_id).where(paid, InvoiceItem.product_id == b)).all()}
        both = len(inv_a & inv_b)
        pr = db.execute(select(func.coalesce(func.sum(InvoiceItem.profit), 0)).join(Invoice, Invoice.id == InvoiceItem.invoice_id)
                        .where(paid, InvoiceItem.product_id.in_([a, b]))).scalar_one()
        return {"value": round(both / max(1, len(inv_a | inv_b)), 3), "unit": "نرخ هم‌خرید", "profit": _f(pr), "both": both}
    if m == "avg_basket_size":
        n = db.execute(select(func.count(Invoice.id)).where(paid)).scalar_one() or 0
        s = db.execute(select(func.coalesce(func.sum(Invoice.total_amount), 0)).where(paid)).scalar_one()
        pr = _net_profit(db, paid)
        return {"value": round(_f(s) / n) if n else 0, "unit": "تومان/فاکتور", "profit": pr, "invoices": n}
    if m == "receivables_collected":
        from ..models import CustomerLedgerEntry
        v = db.execute(select(func.coalesce(func.sum(CustomerLedgerEntry.amount), 0))
                       .where(CustomerLedgerEntry.entry_type.in_(["PAYMENT", "SETTLE", "SETTLEMENT"]),
                              CustomerLedgerEntry.created_at >= start, CustomerLedgerEntry.created_at < end)).scalar_one()
        return {"value": _f(v), "unit": "تومان", "profit": 0.0}
    if m == "void_rate":
        n = db.execute(select(func.count(Invoice.id)).where(Invoice.created_at >= start, Invoice.created_at < end, Invoice.created_by == spec["user_id"])).scalar_one() or 0
        v = db.execute(select(func.count(AuditLog.id)).where(AuditLog.action == "SALE_VOIDED", AuditLog.user_id == spec["user_id"],
                                                             AuditLog.created_at >= start, AuditLog.created_at < end)).scalar_one() or 0
        return {"value": round(v / n, 3) if n else 0, "unit": "نرخ ابطال", "profit": 0.0}
    if m == "weekday_sales":
        rows = db.execute(select(Invoice.created_at, Invoice.total_amount).where(paid)).all()
        s = sum(_f(t) for at, t in rows if at.weekday() == spec["weekday"])
        return {"value": s, "unit": "تومان", "profit": 0.0}
    if m == "stockout_days":
        # days in the window with zero sellable stock, reconstructed from movements:
        # a day counts as a stockout when the product had no sale AND its stock at end of day was ≤ 0.
        pid = spec["product_id"]
        sold_days = {r[0].date() for r in db.execute(select(Invoice.created_at).join(InvoiceItem, InvoiceItem.invoice_id == Invoice.id)
                                                     .where(paid, InvoiceItem.product_id == pid)).all()}
        mv = db.execute(select(StockMovement.created_at, StockMovement.quantity).join(ProductBatch, ProductBatch.id == StockMovement.batch_id)
                        .where(ProductBatch.product_id == pid, StockMovement.created_at < end).order_by(StockMovement.created_at)).all()
        bal, bal_by_day, idx = 0.0, {}, 0
        d0, days = start.date(), max(1, int((end - start).total_seconds() // 86400))
        for k in range(days):
            day = d0 + timedelta(days=k)
            while idx < len(mv) and mv[idx][0].date() <= day:
                bal += _f(mv[idx][1]); idx += 1
            bal_by_day[day] = bal
        out_days = sum(1 for day, b in bal_by_day.items() if b <= 0.5 and day not in sold_days)
        lost = out_days * _f(spec.get("margin_per_day"))
        return {"value": out_days, "unit": "روز بدون موجودی", "profit": -lost, "days": days}
    if m == "availability":
        # v3.2 — share of days the product was actually on the shelf (reconstructed from movements)
        # + the profit it made; fewer empty-shelf days ⇒ more units ⇒ more profit (measured, not assumed).
        pid = spec["product_id"]
        sold_days = {r[0].date() for r in db.execute(select(Invoice.created_at).join(InvoiceItem, InvoiceItem.invoice_id == Invoice.id)
                                                     .where(paid, InvoiceItem.product_id == pid)).all()}
        mv = db.execute(select(StockMovement.created_at, StockMovement.quantity).join(ProductBatch, ProductBatch.id == StockMovement.batch_id)
                        .where(ProductBatch.product_id == pid, StockMovement.created_at < end).order_by(StockMovement.created_at)).all()
        bal, idx, out_days = 0.0, 0, 0
        d0, days = start.date(), max(1, int(round((end - start).total_seconds() / 86400)))
        for k in range(days):
            day = d0 + timedelta(days=k)
            while idx < len(mv) and mv[idx][0].date() <= day:
                bal += _f(mv[idx][1]); idx += 1
            if bal <= 0.5 and day not in sold_days:
                out_days += 1
        units = db.execute(select(func.coalesce(func.sum(InvoiceItem.qty), 0)).join(Invoice, Invoice.id == InvoiceItem.invoice_id)
                           .where(paid, InvoiceItem.product_id == pid)).scalar_one()
        pr = db.execute(select(func.coalesce(func.sum(InvoiceItem.profit), 0)).join(Invoice, Invoice.id == InvoiceItem.invoice_id)
                        .where(paid, InvoiceItem.product_id == pid)).scalar_one()
        return {"value": round((days - out_days) / days * 100, 1), "unit": "٪ روزهای موجود", "profit": _f(pr), "units": _f(units),
                "stockout_days": out_days, "days": days}
    if m == "purchase_over_best":
        return {"value": 0.0, "unit": "—", "profit": 0.0}
    return {"value": 0.0, "unit": "—", "profit": 0.0}


def _daily_series(db: Session, spec: dict, start: datetime, end: datetime, base: dict) -> dict:
    """Before/after daily profit of the measured slice (for the charts): 14 days before acceptance
    and the days since. Returns {"before": [...], "after": [...]} in toman/day."""
    m = spec.get("metric")
    try:
        b_from = datetime.fromisoformat(base["from"]) if base.get("from") else start - timedelta(days=14)
    except Exception:
        b_from = start - timedelta(days=14)
    b_from = max(b_from, start - timedelta(days=14))
    q = select(func.date(Invoice.created_at), func.coalesce(func.sum(InvoiceItem.profit), 0)).join(Invoice, Invoice.id == InvoiceItem.invoice_id) \
        .where(Invoice.status == PAID, Invoice.created_at >= b_from, Invoice.created_at < end)
    if m in ("product_units", "product_profit", "availability", "stockout_days"):
        q = q.where(InvoiceItem.product_id == spec.get("product_id"))
    elif m == "attach_rate":
        q = q.where(InvoiceItem.product_id.in_([spec.get("a"), spec.get("b")]))
    elif m == "customer_sales":
        q = q.where(Invoice.customer_id.in_(spec.get("customer_ids") or []))
    elif m == "avg_basket_size":
        pass
    else:
        return {"before": [], "after": []}
    by_day = {str(d)[:10]: _f(v) for d, v in db.execute(q.group_by(func.date(Invoice.created_at))).all()}
    before, after = [], []
    d = b_from.date()
    while d < end.date() or (d == end.date() and len(after) == 0):
        v = round(by_day.get(d.isoformat(), 0.0))
        (before if datetime.combine(d, datetime.min.time()) < start.replace(hour=0, minute=0, second=0, microsecond=0) else after).append(v)
        d += timedelta(days=1)
        if len(before) + len(after) > 60:
            break
    return {"before": before, "after": after}


def _store_profit_rate(db: Session, start: datetime, end: datetime) -> float:
    days = max(1e-9, (end - start).total_seconds() / 86400)
    v = db.execute(select(func.coalesce(func.sum(InvoiceItem.profit), 0)).join(Invoice, Invoice.id == InvoiceItem.invoice_id)
                   .where(Invoice.status == PAID, Invoice.created_at >= start, Invoice.created_at < end)).scalar_one()
    return _f(v) / days


def accept(db: Session, insight: Insight, *, user: User | None, action_types: list[str] | None = None) -> dict:
    from . import insight_actions
    spec = json.loads(insight.metric or "{}")
    wd = int(spec.get("window_days", 28))
    now = _now()
    first = db.execute(select(func.min(Invoice.created_at))).scalar_one()
    if first and first > now - timedelta(days=wd):
        wd = max(3, (now - first).days)   # young store: baseline cannot predate its first sale
    base = _metric_value(db, spec, now - timedelta(days=wd), now)
    executed = insight_actions.execute(db, insight, user=user, only=action_types)
    insight.status = "ACCEPTED"
    insight.accepted_at = now
    insight.accepted_by = user.id if user else None
    insight.baseline = json.dumps({"window_days": wd, "from": (now - timedelta(days=wd)).isoformat(), "to": now.isoformat(), **base}, ensure_ascii=False)
    db.commit()
    return {"baseline": base, "executed": executed}


def measure(db: Session, insight: Insight) -> dict | None:
    """Same metric over the post window; sets measured_gain in toman.

    Gain = Δprofit when the metric carries profit, otherwise Δvalue for money
    metrics; unit-less metrics (rates) are reported but do not add to gain."""
    if insight.status not in ("ACCEPTED", "MEASURED") or not insight.accepted_at:
        return None
    spec = json.loads(insight.metric or "{}")
    wd = int(spec.get("window_days", 28))
    start = insight.accepted_at
    end = min(_now(), start + timedelta(days=wd))
    elapsed = max(1e-9, (end - start).total_seconds() / 86400)
    post = _metric_value(db, spec, start, end)
    base = json.loads(insight.baseline or "{}")
    base_days = max(1e-9, float(base.get("window_days", wd)))
    unit = post.get("unit", "")
    enough = elapsed >= 1.0
    # Difference-in-differences: the rest of the store is the control group. If store
    # profit grew 8 % in the same period (season, growth), only the lift *beyond* that 8 %
    # is credited to the action. Reported both raw and adjusted; the adjusted one counts.
    ctrl_ratio = 1.0
    if m := spec.get("metric"):
        if m in ("product_units", "product_profit", "customer_sales", "attach_rate", "receivables_collected", "weekday_sales", "availability"):
            b_from = datetime.fromisoformat(base["from"]) if base.get("from") else start - timedelta(days=int(base_days))
            sb = _store_profit_rate(db, b_from, start)
            sp = _store_profit_rate(db, start, end)
            if sb > 0 and sp > 0:
                ctrl_ratio = max(0.5, min(2.0, sp / sb))
    if m == "avg_basket_size":
        # store-wide action (POS nudges): profit per invoice before vs. after × invoices after
        bi, pi = max(1, int(base.get("invoices") or 1)), max(1, int(post.get("invoices") or 1))
        base_rate, post_rate = _f(base.get("profit")) / bi, _f(post.get("profit")) / pi
        raw_gain = (post_rate - base_rate) * pi
        adj_gain = raw_gain
        change_pct = round((post_rate - base_rate) / base_rate * 100, 1) if base_rate else None
    else:
        if unit == "تومان" and not base.get("profit") and not post.get("profit"):
            base_rate, post_rate = _f(base.get("value")) / base_days, _f(post.get("value")) / elapsed
        else:
            base_rate, post_rate = _f(base.get("profit")) / base_days, _f(post.get("profit")) / elapsed
        raw_gain = (post_rate - base_rate) * elapsed
        adj_gain = (post_rate - base_rate * ctrl_ratio) * elapsed
        bv, pv = _f(base.get("value")), _f(post.get("value"))
        change_pct = round(((pv / elapsed) - (bv / base_days)) / (bv / base_days) * 100, 1) if bv else None
    gain = adj_gain if enough else 0.0
    # v3.2 — growth in percent (what managers actually quote): profit rate after vs. before,
    # and the same after removing the store-wide trend (the honest number).
    profit_pct = round((post_rate - base_rate) / abs(base_rate) * 100, 1) if base_rate else None
    profit_pct_adj = round((post_rate - base_rate * ctrl_ratio) / abs(base_rate * ctrl_ratio) * 100, 1) if base_rate else None
    insight.result = json.dumps({"window_days": wd, "elapsed_days": round(elapsed, 1), "from": start.isoformat(), "to": end.isoformat(),
                                 "enough_data": enough, "change_pct": change_pct, "control_ratio": round(ctrl_ratio, 3),
                                 "profit_pct": profit_pct, "profit_pct_adj": profit_pct_adj,
                                 "base_value": base.get("value"), "post_value": post.get("value"),
                                 "base_profit_per_day": round(base_rate), "post_profit_per_day": round(post_rate),
                                 "daily": _daily_series(db, spec, start, end, base),
                                 "raw_gain": round(raw_gain), "adjusted_gain": round(adj_gain),
                                 "projected_month": round(adj_gain / elapsed * 30) if enough else None,
                                 "base_rate_per_day": round(base_rate, 2), "post_rate_per_day": round(post_rate, 2), **post}, ensure_ascii=False)
    insight.measured_gain = Decimal(str(round(gain))) if enough else None
    insight.measured_at = _now()
    if elapsed >= wd - 0.01 and insight.status != "MEASURED":
        insight.status = "MEASURED"
        db.flush()
        try:   # v3.1 — every completed measurement re-fits the calibration (the engine learns)
            from . import forecast
            forecast.learn(db)
        except Exception:
            log.exception("calibration failed")
    return {"baseline": base, "post": post, "gain": gain, "complete": insight.status == "MEASURED"}


def measure_all(db: Session) -> int:
    n = 0
    for row in db.execute(select(Insight).where(Insight.status == "ACCEPTED")).scalars():
        try:
            if measure(db, row):
                n += 1
        except Exception:
            log.exception("measure failed for insight %s", row.id)
    db.commit()
    return n


def _parse_dt(v):
    if not v:
        return None
    try:
        return datetime.fromisoformat(str(v)[:19])
    except Exception:
        return None


def impact_summary(db: Session) -> dict:
    """Dashboard block: what the accepted suggestions did to profit."""
    rows = db.execute(select(Insight).where(Insight.status.in_(["ACCEPTED", "MEASURED"])).order_by(Insight.accepted_at.desc())).scalars().all()
    total = sum(_f(r.measured_gain) for r in rows)
    by_kind: dict[str, float] = defaultdict(float)
    for r in rows:
        by_kind[r.kind] += _f(r.measured_gain)
    top = sorted(rows, key=lambda r: -_f(r.measured_gain))[:5]
    open_cnt = db.execute(select(func.count(Insight.id)).where(Insight.status == "NEW")).scalar_one()
    expected_open = _f(db.execute(select(func.coalesce(func.sum(Insight.expected_gain), 0)).where(Insight.status == "NEW")).scalar_one())
    # "recent" = rolling 30 days; each action's measured gain is pro-rated by how much of its
    # measurement window falls inside the last 30 days (so a long-running effect still shows up).
    now = _now(); m0 = now - timedelta(days=30)
    month_gain = 0.0
    for r in rows:
        if not r.accepted_at or not r.measured_gain:
            continue
        res = r.result if isinstance(r.result, dict) else {}
        end = _parse_dt(res.get("to")) or now
        span = max(1e-9, (end - r.accepted_at).total_seconds())
        overlap = max(0.0, (min(end, now) - max(r.accepted_at, m0)).total_seconds())
        month_gain += _f(r.measured_gain) * min(1.0, overlap / span)
    profit_month = _f(db.execute(select(func.coalesce(func.sum(InvoiceItem.profit), 0)).join(Invoice, Invoice.id == InvoiceItem.invoice_id)
                                 .where(Invoice.status == PAID, Invoice.created_at >= m0)).scalar_one())
    return {
        "accepted": len(rows), "measured": len([r for r in rows if r.status == "MEASURED"]), "open": open_cnt,
        "total_gain": round(total), "month_gain": round(month_gain), "expected_open": round(expected_open),
        "month_profit": round(profit_month), "share_of_month_profit": round(month_gain / profit_month, 3) if profit_month else 0,
        "by_kind": [{"kind": k, "label": KIND_LABELS.get(k, k), "gain": round(v)} for k, v in sorted(by_kind.items(), key=lambda kv: -kv[1])],
        "top": [{"id": r.id, "kind": r.kind, "label": KIND_LABELS.get(r.kind, r.kind), "title": r.title, "gain": round(_f(r.measured_gain)),
                 "status": r.status, "accepted_at": r.accepted_at.isoformat() if r.accepted_at else None} for r in top],
    }


def group_of(kind: str) -> str:
    for g, (_, ks) in GROUPS.items():
        if kind in ks:
            return g
    return "growth"


def to_dict(r: Insight) -> dict:
    return {
        "id": r.id, "kind": r.kind, "label": KIND_LABELS.get(r.kind, r.kind), "group": group_of(r.kind), "title": r.title, "body": r.body, "priority": r.priority,
        "evidence": json.loads(r.evidence or "{}"), "actions": json.loads(r.actions or "[]"), "expected_gain": _f(r.expected_gain),
        "metric": json.loads(r.metric or "{}"), "status": r.status, "created_at": r.created_at.isoformat() if r.created_at else None,
        "accepted_at": r.accepted_at.isoformat() if r.accepted_at else None, "baseline": json.loads(r.baseline) if r.baseline else None,
        "result": json.loads(r.result) if r.result else None, "measured_gain": _f(r.measured_gain) if r.measured_gain is not None else None,
        "narrative": r.narrative, "last_seen_at": r.last_seen_at.isoformat() if r.last_seen_at else None,
    }


def nudges(db: Session, product_ids: list[int]) -> list[dict]:
    """Real-time POS hints: for the scanned products, the strongest «then» items not in the cart."""
    row = db.execute(select(Insight).where(Insight.kind == "BASKET_NUDGE", Insight.status.in_(["ACCEPTED", "MEASURED"]))
                     .order_by(Insight.accepted_at.desc())).scalars().first()
    if not row:
        return []
    rules = json.loads(row.evidence or "{}").get("rules", [])
    cart = set(product_ids)
    out, seen = [], set()
    for r in rules:
        if r["if"] in cart and r["then"] not in cart and r["then"] not in seen:
            seen.add(r["then"])
            out.append({"product_id": r["then"], "name": r["then_name"], "because": r["if_name"], "confidence": r["confidence"]})
        if len(out) >= 2:
            break
    return out


# ----------------------------------------------------------------------------- background worker
import threading as _th  # noqa: E402

_stop = _th.Event()
_thread: "_th.Thread | None" = None


def _worker_tick(session_factory) -> None:
    from . import insight_actions
    db = session_factory()
    try:
        from ..models import SystemSetting as _SS
        row = db.execute(select(_SS).where(_SS.key == "insights.enabled")).scalar_one_or_none()
        if row and row.value == "false":
            return
        insight_actions.apply_markdown_steps(db)
        db.commit()
        last = db.execute(select(_SS).where(_SS.key == "insights.last_run")).scalar_one_or_none()
        every_h = 6
        row_h = db.execute(select(_SS).where(_SS.key == "insights.interval_hours")).scalar_one_or_none()
        try:
            every_h = max(1, int(row_h.value)) if row_h else 6
        except ValueError:
            pass
        due = not last or not last.value or datetime.fromisoformat(last.value) < datetime.utcnow() - timedelta(hours=every_h)
        if due:
            res = run(db)
            insight_actions._set_setting(db, "insights.last_run", datetime.utcnow().isoformat())
            db.commit()
            # surface urgent ones as notifications (once)
            from .notifications import notify
            for r in db.execute(select(Insight).where(Insight.status == "NEW", Insight.priority == 1, Insight.narrative.is_(None))).scalars():
                notify(db, type="INSIGHT", title="پیشنهاد فوری هوش فروشگاه", body=r.title, severity="WARN", reference_type="Insight", reference_id=r.id)
                r.narrative = ""   # marks «notified» without spending a narrator call
            db.commit()
            log.info("insights run: %s", res)
    finally:
        db.close()


def start_worker(session_factory) -> None:
    global _thread
    if _thread and _thread.is_alive():
        return
    _stop.clear()

    def loop():
        _stop.wait(20)   # let the app finish booting first
        while not _stop.is_set():
            try:
                _worker_tick(session_factory)
            except Exception:
                log.exception("insights worker tick failed")
            _stop.wait(15 * 60)

    _thread = _th.Thread(target=loop, name="insights-worker", daemon=True)
    _thread.start()


def stop_worker() -> None:
    _stop.set()
