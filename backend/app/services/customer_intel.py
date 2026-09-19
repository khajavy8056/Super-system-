"""v3.5.13 — customer-behaviour and shop-floor analytics: 30 new analyzers.

Why a separate module: ``insights.py`` had 13 detectors and every one of them looked at PRODUCTS
(what to reorder, what to mark down). The shop owner's question is different — *which customer*,
*when*, and *what do I send them*. That needs the invoice stream read per customer, which is what
this module does.

Two hard rules were kept, because a suggestion that cannot be executed or measured is decoration:

  * every action uses a type that ``insight_actions.ACTIONS`` can actually run
    (vip_coupons, winback_sms, visit_sms, sms_buyers, debt_reminders, set_min_stock,
    reorder_note, shelf_note, markdown_ladder, flash_sale, pos_nudge, note);
  * every metric uses a kind ``insights._metric_value`` can compute, so ``accept()`` captures a
    real baseline and ``measure()`` can report a real gain in toman.

Analyzers return ``Draft`` objects and are registered in ``ANALYZERS`` at the bottom; ``insights``
merges that dict into its own. One analyzer raising must not stop the rest — ``insights.run``
already catches per-kind exceptions.
"""
from __future__ import annotations

import statistics
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta

from sqlalchemy import func, select

from ..models import Customer, CustomerLedgerEntry, Invoice, InvoiceItem, Product
from .insights import Draft, Ctx, _f, _pname, _today

PAID = "PAID"


# --------------------------------------------------------------------------- helpers
def _cust_rows(ctx: Ctx) -> dict[int, dict]:
    """Per-customer purchase stream, oldest first: {id: {"at": [...], "total": [...], "pids": set}}."""
    out: dict[int, dict] = {}
    for ln in ctx.lines:
        cid = ln["cust"]
        if not cid:
            continue
        r = out.setdefault(cid, {"at": [], "total": [], "pids": set(), "profit": 0.0, "inv": set()})
        r["inv"].add(ln["inv"])
        r["profit"] += ln["profit"]
        r["pids"].add(ln["pid"])
    for cid, r in out.items():
        for inv in r["inv"]:
            d = ctx.invoices.get(inv)
            if d:
                r["at"].append(d["at"])
                r["total"].append(d["total"])
        r["at"].sort()
    return out


def _names(ctx: Ctx, ids: list[int]) -> dict[int, Customer]:
    if not ids:
        return {}
    return {c.id: c for c in ctx.db.execute(select(Customer).where(Customer.id.in_(ids))).scalars()}


def _cname(ctx: Ctx, cid: int) -> str:
    c = ctx.db.get(Customer, cid)
    return c.name if c else f"مشتری #{cid}"


def _days_between(dates: list[datetime]) -> list[float]:
    return [(b - a).total_seconds() / 86400 for a, b in zip(dates, dates[1:])]


def _unit_price(ctx: Ctx, pid: int) -> float:
    """Average unit price a product actually sold at in the window (Product stores no price)."""
    q = s = 0.0
    for l in ctx.lines:
        if l["pid"] == pid:
            q += l["qty"]; s += l["sub"]
    return s / q if q else 0.0


def _toman(v: float) -> str:
    return f"{int(round(v)):,}"


def _split(ctx: Ctx, days: int) -> tuple[list[dict], list[dict]]:
    """The analysis window split in half: (older, newer). Every trend claim compares these."""
    cut = ctx.now_utc - timedelta(days=days / 2)
    return [l for l in ctx.lines if l["at"] < cut], [l for l in ctx.lines if l["at"] >= cut]


# --------------------------------------------------------------------------- 1-6: who to contact, and when
def a_cust_payday(ctx: Ctx) -> list[Draft]:
    """Customers whose purchases cluster on a day of the month — i.e. when their money arrives.

    Sending an offer the day BEFORE that day is worth far more than sending it at random, and this
    is the single most actionable thing the stream contains.
    """
    out = []
    for cid, r in _cust_rows(ctx).items():
        if len(r["at"]) < 4:
            continue
        dom = [d.day for d in r["at"]]
        c = Counter(dom)
        day, hits = c.most_common(1)[0]
        if hits < max(3, len(dom) * 0.4):
            continue
        cust = ctx.db.get(Customer, cid)
        if not cust or not cust.phone:
            continue
        spend = sum(r["total"]) / max(1, len(r["total"]))
        out.append(Draft(
            kind="CUST_PAYDAY", dedupe_key=str(cid),
            title=f"{cust.name}: روز {day} هر ماه خرید می‌کند",
            body=(f"از {len(r['at'])} خرید ثبت‌شدهٔ این مشتری، {hits} مورد در روز {day} ماه انجام شده — "
                  f"الگویی که معمولاً به زمان واریز حقوق مربوط است. میانگین سبد او {_toman(spend)} تومان است. "
                  f"پیشنهاد: یک روز قبل از روز {day} پیامک پیشنهاد بفرستید تا خرید در همان روز انجام شود."),
            priority=2,
            evidence={"customer_id": cid, "day_of_month": day, "visits": len(r["at"]),
                      "hits": hits, "avg_basket": round(spend), "top": [p for p in list(r["pids"])[:8]]},
            actions=[{"type": "visit_sms", "label": "ارسال پیامک در روز مناسب",
                      "params": {"customers": [{"id": cid, "day": day}]}}],
            expected_gain=spend * 0.12,
            metric={"metric": "customer_sales", "customer_ids": [cid], "window_days": 30}))
        if len(out) >= 12:
            break
    return out


def a_cust_churn_risk(ctx: Ctx) -> list[Draft]:
    """A customer whose current silence is long *for them* — not long in absolute terms.

    Comparing the gap to the customer's own median gap is what makes this fire early: someone who
    comes every 5 days is already lost after 12, while a monthly customer is fine at 40.
    """
    out = []
    for cid, r in _cust_rows(ctx).items():
        if len(r["at"]) < 4:
            continue
        gaps = _days_between(r["at"])
        if not gaps:
            continue
        med = statistics.median(gaps)
        if med < 2:
            continue
        silent = (ctx.now_utc - r["at"][-1]).total_seconds() / 86400
        if silent < med * 1.8:
            continue
        cust = ctx.db.get(Customer, cid)
        if not cust:
            continue
        avg = sum(r["total"]) / max(1, len(r["total"]))
        out.append(Draft(
            kind="CUST_CHURN_RISK", dedupe_key=str(cid),
            title=f"{cust.name}: {int(silent)} روز است نیامده (عادتش هر {int(med)} روز)",
            body=(f"فاصلهٔ معمول خریدهای این مشتری {int(med)} روز است و اکنون {int(silent)} روز گذشته — "
                  f"{silent / med:.1f} برابر عادت خودش. میانگین سبد {_toman(avg)} تومان. "
                  f"یک پیامک بازگرداندن با تخفیف کوچک معمولاً قبل از عادت‌کردن به فروشگاه رقیب جواب می‌دهد."),
            priority=1 if silent > med * 3 else 2,
            evidence={"customer_id": cid, "median_gap_days": round(med, 1), "silent_days": round(silent, 1),
                      "ratio": round(silent / med, 2), "visits": len(r["at"]), "avg_basket": round(avg)},
            actions=[{"type": "winback_sms", "label": "پیامک بازگرداندن + تخفیف",
                      "params": {"customer_ids": [cid], "percent": 10, "days": 7}}],
            expected_gain=avg * 0.8,
            metric={"metric": "customer_sales", "customer_ids": [cid], "window_days": 30}))
        if len(out) >= 12:
            break
    return out


def a_cust_rfm(ctx: Ctx) -> list[Draft]:
    """RFM segmentation: the best customers, named, with the offer that fits their segment."""
    rows = _cust_rows(ctx)
    if len(rows) < 5:
        return []
    def score(vals, cid, reverse=False):
        ordered = sorted(rows, key=lambda k: vals[k])
        try:
            pos = ordered.index(cid)
        except ValueError:
            return 3
        q = pos / max(1, len(ordered) - 1)
        return 5 - int(q * 4) if reverse else int(q * 4) + 1
    rec = {c: (ctx.now_utc - r["at"][-1]).total_seconds() / 86400 for c, r in rows.items() if r["at"]}
    freq = {c: len(r["inv"]) for c, r in rows.items()}
    mon = {c: sum(r["total"]) for c, r in rows.items()}
    champs = sorted(rows, key=lambda c: (score(rec, c, True) + score(freq, c) + score(mon, c)), reverse=True)[:5]
    champs = [c for c in champs if rec.get(c, 999) <= 45]
    if not champs:
        return []
    nm = _names(ctx, champs)
    total = sum(mon.values()) or 1
    share = sum(mon[c] for c in champs) / total
    return [Draft(
        kind="CUST_RFM", dedupe_key="champions",
        title=f"{len(champs)} مشتری قهرمان، {share * 100:.0f}٪ از فروش دوره",
        body=("با امتیازدهی RFM (تازگی، تعداد خرید، مبلغ) این مشتریان در صدر هستند: "
              + "، ".join(nm[c].name if c in nm else f"#{c}" for c in champs)
              + f". سهمشان از فروش {_toman(sum(mon[c] for c in champs))} تومان از {_toman(total)} است. "
                "باشگاه VIP با کوپن ماهانه، ارزان‌ترین راه نگه‌داشتن همین‌هاست."),
        priority=2,
        evidence={"customer_ids": champs, "share_of_sales": round(share, 3),
                  "segments": [{"id": c, "name": nm[c].name if c in nm else f"#{c}",
                                "recency_days": round(rec.get(c, 0), 1), "visits": freq[c],
                                "total": round(mon[c])} for c in champs]},
        actions=[{"type": "vip_coupons", "label": "ساخت باشگاه VIP و کوپن ماهانه",
                  "params": {"customer_ids": champs, "percent": 8, "days": 30}}],
        expected_gain=sum(mon[c] for c in champs) * 0.05,
        metric={"metric": "customer_sales", "customer_ids": champs, "window_days": 30})]


def a_cust_basket_shrink(ctx: Ctx) -> list[Draft]:
    """Customers whose basket is shrinking while they still come — the quiet kind of churn."""
    out = []
    older, newer = _split(ctx, ctx.days)
    for cid in {l["cust"] for l in ctx.lines if l["cust"]}:
        o = [l["total"] for l in older if l["cust"] == cid]
        n = [l["total"] for l in newer if l["cust"] == cid]
        if len(o) < 3 or len(n) < 2:
            continue
        a, b = statistics.mean(o), statistics.mean(n)
        if a <= 0 or b >= a * 0.8:
            continue
        cust = ctx.db.get(Customer, cid)
        if not cust:
            continue
        out.append(Draft(
            kind="CUST_BASKET_SHRINK", dedupe_key=str(cid),
            title=f"{cust.name}: سبد خریدش {(1 - b / a) * 100:.0f}٪ کوچک‌تر شده",
            body=(f"میانگین سبد این مشتری از {_toman(a)} تومان به {_toman(b)} تومان رسیده، در حالی که هنوز "
                  f"سرِ پا می‌آید ({len(n)} خرید در نیمهٔ اخیر). این الگو یعنی بخشی از خرید به جای دیگری "
                  f"رفته است — معمولاً قبل از قطع کامل رابطه."),
            priority=2,
            evidence={"customer_id": cid, "before": round(a), "after": round(b),
                      "drop_pct": round((1 - b / a) * 100, 1)},
            actions=[{"type": "winback_sms", "label": "پیشنهاد بازگرداندن سهم سبد",
                      "params": {"customer_ids": [cid], "percent": 12, "days": 10}}],
            expected_gain=(a - b) * len(n),
            metric={"metric": "customer_sales", "customer_ids": [cid], "window_days": 30}))
        if len(out) >= 10:
            break
    return out


def a_cust_category_loss(ctx: Ctx) -> list[Draft]:
    """A customer stopped buying a category they used to buy regularly — the most concrete win-back."""
    out = []
    older, newer = _split(ctx, ctx.days)
    for cid in {l["cust"] for l in ctx.lines if l["cust"]}:
        op = {l["pid"] for l in older if l["cust"] == cid}
        np = {l["pid"] for l in newer if l["cust"] == cid}
        lost = op - np
        if len(lost) < 2:
            continue
        # rank the lost items by what they used to spend on them
        spend = defaultdict(float)
        for l in older:
            if l["cust"] == cid and l["pid"] in lost:
                spend[l["pid"]] += l["sub"]
        top = sorted(spend, key=spend.get, reverse=True)[0]
        cust = ctx.db.get(Customer, cid)
        if not cust:
            continue
        out.append(Draft(
            kind="CUST_CATEGORY_LOSS", dedupe_key=str(cid),
            title=f"{cust.name}: {len(lost)} کالای همیشگی‌اش را دیگر نمی‌خرد",
            body=(f"بیشترین مبلغ از دست رفته مربوط به «{_pname(ctx, top)}» است "
                  f"({_toman(spend[top])} تومان در نیمهٔ اول، صفر در نیمهٔ اخیر). "
                  f"یک پیامک روی همان کالا، مستقیم‌ترین راه برگرداندن این سبد است."),
            priority=2,
            evidence={"customer_id": cid, "lost_products": list(lost)[:10], "top_product_id": top,
                      "top_spend": round(spend[top])},
            actions=[{"type": "sms_buyers", "label": "پیامک به خریداران این کالا",
                      "params": {"product_id": top, "percent": 10}}],
            expected_gain=spend[top] * 0.35,
            metric={"metric": "customer_sales", "customer_ids": [cid], "window_days": 30}))
        if len(out) >= 10:
            break
    return out


def a_cust_new_second(ctx: Ctx) -> list[Draft]:
    """Customers acquired recently who bought once and never came back — the cheapest conversion there is."""
    cut = ctx.now_utc - timedelta(days=45)
    once = []
    for cid, r in _cust_rows(ctx).items():
        if len(r["inv"]) == 1 and r["at"] and r["at"][-1] >= cut:
            once.append(cid)
    if len(once) < 3:
        return []
    nm = _names(ctx, once[:20])
    ids = [c for c in once[:20] if c in nm]
    avg = statistics.mean([sum(r["total"]) for c, r in _cust_rows(ctx).items() if c in ids]) if ids else 0
    return [Draft(
        kind="CUST_NEW_SECOND", dedupe_key=f"{_today().isoformat()[:7]}",
        title=f"{len(once)} مشتری تازه، فقط یک خرید داشته‌اند",
        body=(f"این مشتریان در ۴۵ روز اخیر ثبت شده‌اند و یک بار خرید کرده‌اند: "
              f"{len(ids)} نفر شمارهٔ تماس دارند. خرید دوم، سخت‌ترین و ارزشمندترین قدم است؛ "
              f"یک پیشنهاد محدود برای همین گروه، معمولاً چند برابر هزینهٔ خودش برمی‌گردد."),
        priority=2,
        evidence={"count": len(once), "with_phone": len(ids), "customer_ids": ids, "avg_first_basket": round(avg)},
        actions=[{"type": "winback_sms", "label": "پیشنهاد خرید دوم",
                  "params": {"customer_ids": ids, "percent": 15, "days": 7}}],
        expected_gain=avg * len(ids) * 0.25,
        metric={"metric": "customer_sales", "customer_ids": ids, "window_days": 30})]


# --------------------------------------------------------------------------- 7-12: money and risk
def a_cust_credit_slow(ctx: Ctx) -> list[Draft]:
    """Customers whose credit balance grows faster than they settle it."""
    rows = ctx.db.execute(
        select(CustomerLedgerEntry.customer_id, func.coalesce(func.sum(CustomerLedgerEntry.amount), 0))
        .where(CustomerLedgerEntry.customer_id.is_not(None))
        .group_by(CustomerLedgerEntry.customer_id)).all()
    out = []
    for cid, bal in rows:
        bal = _f(bal)
        if bal <= 0:
            continue
        cust = ctx.db.get(Customer, cid)
        if not cust:
            continue
        r = _cust_rows(ctx).get(cid)
        monthly = (sum(r["total"]) / max(1, len(r["inv"]))) * 2 if r else 0
        if monthly <= 0 or bal < monthly * 1.5:
            continue
        out.append(Draft(
            kind="CUST_CREDIT_SLOW", dedupe_key=str(cid),
            title=f"{cust.name}: {_toman(bal)} تومان نسیهٔ باز",
            body=(f"ماندهٔ حساب این مشتری {_toman(bal)} تومان است، در حالی که خرید ماهانهٔ تقریبی‌اش "
                  f"{_toman(monthly)} تومان. یعنی بیش از یک و نیم ماه فروش، نزد او مانده. "
                  f"یادآوری سررسید، نقدینگی را بدون از دست دادن مشتری برمی‌گرداند."),
            priority=2,
            evidence={"customer_id": cid, "balance": round(bal), "est_monthly": round(monthly),
                      "months_outstanding": round(bal / monthly, 1)},
            actions=[{"type": "debt_reminders", "label": "یادآوری سررسید به بدهکاران"}],
            expected_gain=0.0,
            metric={"metric": "receivables_collected", "window_days": 28}))
        if len(out) >= 10:
            break
    return out


def a_cust_concentration(ctx: Ctx) -> list[Draft]:
    """How much of the turnover rests on very few customers — a risk, not a compliment."""
    mon = {c: sum(r["total"]) for c, r in _cust_rows(ctx).items()}
    total = sum(mon.values())
    if total <= 0 or len(mon) < 5:
        return []
    top = sorted(mon, key=mon.get, reverse=True)[:5]
    share = sum(mon[c] for c in top) / total
    if share < 0.3:
        return []
    nm = _names(ctx, top)
    return [Draft(
        kind="CUST_CONCENTRATION", dedupe_key="top5",
        title=f"{share * 100:.0f}٪ فروش روی {len(top)} مشتری",
        body=("پنج مشتری اول "
              + "، ".join(nm[c].name if c in nm else f"#{c}" for c in top)
              + f" هستند و {share * 100:.0f}٪ فروش دوره را می‌سازند. رفتن هر کدام ضربهٔ مستقیم می‌زند؛ "
                "همزمان یعنی پایهٔ مشتریِ 넓 هنوز ساخته نشده است."),
        priority=3,
        evidence={"top_customer_ids": top, "share": round(share, 3),
                  "customers_total": len(mon)},
        actions=[{"type": "vip_coupons", "label": "محکم کردن رابطه با مشتریان اصلی",
                  "params": {"customer_ids": top, "percent": 8, "days": 30}}],
        expected_gain=0.0,
        metric={"metric": "customer_sales", "customer_ids": top, "window_days": 30})]


def a_cust_anonymous(ctx: Ctx) -> list[Draft]:
    """Sales with no registered customer: invisible demand that can never be re-marketed."""
    tot = len(ctx.invoices)
    anon = sum(1 for d in ctx.invoices.values() if not d["cust"])
    if tot < 30 or anon / tot < 0.5:
        return []
    anon_val = sum(d["total"] for d in ctx.invoices.values() if not d["cust"])
    return [Draft(
        kind="CUST_ANONYMOUS", dedupe_key="share",
        title=f"{anon / tot * 100:.0f}٪ فاکتورها بدون مشتری ثبت شده",
        body=(f"از {tot} فاکتور دوره، {anon} مورد ({_toman(anon_val)} تومان) به هیچ مشتری‌ای وصل نیست. "
              f"این فروش دیگر قابل پیامک، کوپن یا پیش‌بینی نیست. گرفتن شمارهٔ تماس هنگام پرداخت، "
              f"ارزان‌ترین سرمایه‌گذاری بازاریابی فروشگاه است."),
        priority=3,
        evidence={"invoices": tot, "anonymous": anon, "anonymous_value": round(anon_val),
                  "share": round(anon / tot, 3)},
        actions=[{"type": "note", "label": "یادداشت اجرایی برای صندوق"}],
        expected_gain=0.0,
        metric={"metric": "avg_basket_size", "window_days": 28})]


def a_cust_return_abuse(ctx: Ctx) -> list[Draft]:
    """Customers whose returns are far out of line with their purchases."""
    from ..models import Return
    rows = ctx.db.execute(
        select(Invoice.customer_id, func.count(Return.id), func.coalesce(func.sum(Invoice.total_amount), 0))
        .join(Invoice, Invoice.id == Return.invoice_id)
        .where(Invoice.customer_id.is_not(None), Invoice.created_at >= ctx.since(ctx.days))
        .group_by(Invoice.customer_id)).all()
    out = []
    for cid, n, val in rows:
        r = _cust_rows(ctx).get(cid)
        visits = len(r["inv"]) if r else 0
        if visits < 4 or n < 3 or n / visits < 0.3:
            continue
        cust = ctx.db.get(Customer, cid)
        out.append(Draft(
            kind="CUST_RETURN_ABUSE", dedupe_key=str(cid),
            title=f"{cust.name if cust else cid}: {n} مرجوعی از {visits} خرید",
            body=(f"نرخ مرجوعی این مشتری {n / visits * 100:.0f}٪ است — چند برابر حد معمول. "
                  f"یا کالا با انتظارش نمی‌خواند (که با راهنمای فروش حل می‌شود) یا الگوی سوءاستفاده است. "
                  f"قبل از هر تخفیف تازه، این مورد را بررسی کنید."),
            priority=3,
            evidence={"customer_id": cid, "returns": int(n), "visits": visits,
                      "rate": round(n / visits, 3)},
            actions=[{"type": "note", "label": "یادداشت بررسی مورد"}],
            expected_gain=0.0,
            metric={"metric": "customer_sales", "customer_ids": [cid], "window_days": 28}))
        if len(out) >= 8:
            break
    return out


def a_cust_loyalty_gap(ctx: Ctx) -> list[Draft]:
    """Regulars with no phone number on file: unreachable customers you already paid to acquire."""
    rows = _cust_rows(ctx)
    if len(rows) < 5:
        return []
    missing = [c for c, r in rows.items() if len(r["inv"]) >= 3]
    have = ctx.db.execute(select(Customer.id, Customer.phone).where(Customer.id.in_(missing))).all()
    no_phone = [c for c, p in have if not p]
    if len(no_phone) < 3:
        return []
    return [Draft(
        kind="CUST_LOYALTY_GAP", dedupe_key="no_phone",
        title=f"{len(no_phone)} مشتریِ پایدار، بدون شمارهٔ تماس",
        body=("این مشتریان سه بار یا بیشتر خرید کرده‌اند ولی شمارهٔ تماس ندارند؛ یعنی نه پیامک می‌شود "
              "فرستاد، نه کوپن، نه پیشنهاد روزِ حقوق. تکمیل شمارهٔ این گروه، سریع‌ترین راه رساندن "
              "همهٔ پیشنهادهای دیگر به دست مشتری است."),
        priority=3,
        evidence={"customer_ids": no_phone[:30], "count": len(no_phone)},
        actions=[{"type": "note", "label": "یادداشت تکمیل شماره‌ها"}],
        expected_gain=0.0,
        metric={"metric": "avg_basket_size", "window_days": 28})]


# --------------------------------------------------------------------------- 13-20: pricing and margin
def _product_agg(lines: list[dict]) -> dict[int, dict]:
    out: dict[int, dict] = {}
    for l in lines:
        a = out.setdefault(l["pid"], {"qty": 0.0, "rev": 0.0, "profit": 0.0, "cost": 0.0, "n": 0})
        a["qty"] += l["qty"]; a["rev"] += l["sub"]; a["profit"] += l["profit"]; a["cost"] += l["cost"] * l["qty"]; a["n"] += 1
    return out


def a_margin_erosion(ctx: Ctx) -> list[Draft]:
    """Margin percentage that fell between the two halves of the window: cost rose, price did not."""
    older, newer = _split(ctx, ctx.days)
    o, n = _product_agg(older), _product_agg(newer)
    out = []
    for pid, a in n.items():
        b = o.get(pid)
        if not b or a["rev"] < 500000 or b["rev"] < 500000:
            continue
        ma, mb = a["profit"] / a["rev"], b["profit"] / b["rev"]
        if mb <= 0.02 or mb - ma < 0.03:
            continue
        out.append(Draft(
            kind="MARGIN_EROSION", dedupe_key=str(pid),
            title=f"{_pname(ctx, pid)}: حاشیهٔ سود {mb * 100:.0f}٪ ← {ma * 100:.0f}٪",
            body=(f"حاشیهٔ این کالا از {mb * 100:.1f}٪ به {ma * 100:.1f}٪ رسیده بدون اینکه فروشش کم شود؛ "
                  f"یعنی قیمت خرید بالا رفته و قیمت فروش سرِ جایش مانده. "
                  f"روی {_toman(a['rev'])} تومان فروش، این {_toman((mb - ma) * a['rev'])} تومان سود از دست رفته است."),
            priority=2,
            evidence={"product_id": pid, "margin_before": round(mb, 4), "margin_after": round(ma, 4),
                      "revenue": round(a["rev"]), "lost_profit": round((mb - ma) * a["rev"])},
            actions=[{"type": "reorder_note", "label": "یادداشت بازبینی قیمت خرید/فروش",
                      "params": {"product_id": pid, "qty": 0, "products": [pid]}}],
            expected_gain=(mb - ma) * a["rev"] * 0.5,
            metric={"metric": "product_profit", "product_id": pid, "window_days": 28}))
        if len(out) >= 10:
            break
    return out


def a_discount_leak(ctx: Ctx) -> list[Draft]:
    """A cashier whose discounting is far above the shop's own norm — margin leaving at the till."""
    per: dict[int, dict] = {}
    for inv, d in ctx.invoices.items():
        u = d.get("user")
        if not u:
            continue
        rev = sum(l["sub"] for l in ctx.lines if l["inv"] == inv)
        disc = max(0.0, rev - d["total"])
        a = per.setdefault(u, {"rev": 0.0, "disc": 0.0, "n": 0})
        a["rev"] += rev; a["disc"] += disc; a["n"] += 1
    norms = [a["disc"] / a["rev"] for a in per.values() if a["rev"] > 0]
    if len(norms) < 3:
        return []
    med = statistics.median(norms)
    out = []
    for u, a in per.items():
        if a["rev"] <= 0 or a["n"] < 10:
            continue
        rate = a["disc"] / a["rev"]
        if rate <= max(0.02, med * 2):
            continue
        out.append(Draft(
            kind="DISCOUNT_LEAK", dedupe_key=str(u),
            title=f"صندوقدار #{u}: تخفیف {rate * 100:.1f}٪ (میانهٔ فروشگاه {med * 100:.1f}٪)",
            body=(f"در {a['n']} فاکتور، میانگین تخفیف این صندوق {rate * 100:.2f}٪ است در برابر میانهٔ "
                  f"{med * 100:.2f}٪. اختلاف {_toman(a['disc'] - med * a['rev'])} تومان در همین دوره. "
                  f"گاهی علتش نبودِ قیمت درست روی قفسه است، نه تخفیف عمدی — هر دو با یک بررسی روشن می‌شود."),
            priority=2,
            evidence={"user_id": u, "rate": round(rate, 4), "median_rate": round(med, 4),
                      "invoices": a["n"], "excess": round(a["disc"] - med * a["rev"])},
            actions=[{"type": "note", "label": "یادداشت بررسی تخفیف‌ها"}],
            expected_gain=(a["disc"] - med * a["rev"]) * 0.4,
            metric={"metric": "avg_basket_size", "window_days": 28}))
        if len(out) >= 6:
            break
    return out


def a_price_rounding(ctx: Ctx) -> list[Draft]:
    """Prices that are not cash-friendly: slow the till and lose the odd toman on every sale."""
    out = []
    # Product carries no price column (prices live on ProductBatch), so the price is taken from
    # what the item actually sold for in the window — which is the number the till sees anyway.
    for pid, a in _product_agg(ctx.lines).items():
        sold = a["qty"]
        sp = a["rev"] / sold if sold else 0.0
        if sp <= 0 or sold < 20 or sp % 500 == 0:
            continue
        p = ctx.products.get(pid)
        if p is None:
            continue
        rounded = int(round(sp / 500) * 500)
        out.append(Draft(
            kind="PRICE_ROUNDING", dedupe_key=str(pid),
            title=f"{p.name}: قیمت {_toman(sp)} تومان",
            body=(f"قیمت این کالا به ۵۰۰ تومان رُند نیست. با {int(sold)} عدد فروش در دوره، "
                  f"گرد کردن به {_toman(rounded)} تومان هم صندوق را سریع‌تر می‌کند و هم "
                  f"{_toman((rounded - sp) * sold)} تومان اختلاف در دورهٔ بعد می‌سازد."),
            priority=3,
            evidence={"product_id": pid, "sell_price": round(sp), "suggested": rounded,
                      "units": int(sold), "delta": round((rounded - sp) * sold)},
            actions=[{"type": "shelf_note", "label": "یادداشت بازبینی قیمت", "params": {"products": [pid]}}],
            expected_gain=max(0.0, (rounded - sp) * sold) * 0.5,
            metric={"metric": "product_profit", "product_id": pid, "window_days": 28}))
        if len(out) >= 12:
            break
    return out


def a_promo_depth(ctx: Ctx) -> list[Draft]:
    """Products sold at a discount deeper than the margin can carry."""
    out = []
    for ln in ctx.lines:
        if ln["price"] <= 0 or ln["cost"] <= 0:
            continue
        margin = (ln["price"] - ln["cost"]) / ln["price"]
        if margin > 0.05:
            continue
        pid = ln["pid"]
        qty = sum(l["qty"] for l in ctx.lines if l["pid"] == pid)
        if qty < 10:
            continue
        out.append(Draft(
            kind="PROMO_DEPTH", dedupe_key=str(pid),
            title=f"{_pname(ctx, pid)}: با حاشیهٔ {margin * 100:.1f}٪ فروخته می‌شود",
            body=(f"قیمت فروش تقریباً به قیمت خرید رسیده است ({_toman(ln['price'])} در برابر "
                  f"{_toman(ln['cost'])}). اگر این تخفیف برای جلب مشتریِ کالای دیگر است، ارزش دارد؛ "
                  f"اگر نه، هر فروش ضرر است. {int(qty)} عدد در دوره فروخته شده."),
            priority=2,
            evidence={"product_id": pid, "sell": round(ln["price"]), "cost": round(ln["cost"]),
                      "margin": round(margin, 4), "units": int(qty)},
            actions=[{"type": "shelf_note", "label": "یادداشت بازبینی تخفیف", "params": {"products": [pid]}}],
            expected_gain=abs(min(0.0, margin)) * ln["price"] * qty * 0.5,
            metric={"metric": "product_profit", "product_id": pid, "window_days": 28}))
        if len(out) >= 10:
            break
    return out


# --------------------------------------------------------------------------- 21-26: stock
def a_stockout_cost(ctx: Ctx) -> list[Draft]:
    """Products that ran out while demand was still there — the sales you never saw."""
    from .insights import _stock
    agg = _product_agg(ctx.lines)
    out = []
    for pid, a in agg.items():
        if _stock(ctx, pid) > 0 or a["qty"] < 10:
            continue
        days = ctx.days
        per_day = a["qty"] / max(1, days)
        p = ctx.products.get(pid)
        margin = a["profit"] / a["qty"] if a["qty"] else 0
        lost = per_day * 14 * margin
        out.append(Draft(
            kind="STOCKOUT_COST", dedupe_key=str(pid),
            title=f"{_pname(ctx, pid)}: تمام شده و مشتری دارد",
            body=(f"این کالا در دوره {int(a['qty'])} عدد فروش داشته (≈{per_day:.1f} عدد در روز) و الان "
                  f"موجودی‌اش صفر است. هر روز خالی ≈{_toman(per_day * margin)} تومان سود از دست رفته؛ "
                  f"دو هفته ≈{_toman(lost)} تومان."),
            priority=1,
            evidence={"product_id": pid, "units_in_window": int(a["qty"]), "per_day": round(per_day, 2),
                      "margin_per_unit": round(margin), "est_lost_14d": round(lost)},
            actions=[{"type": "reorder_note", "label": "ثبت سفارش فوری",
                      "params": {"product_id": pid, "qty": int(max(10, per_day * 14)), "products": [pid]}},
                     {"type": "set_min_stock", "label": "تنظیم نقطهٔ سفارش",
                      "params": {"product_id": pid, "min_stock": int(max(5, per_day * 7))}}],
            expected_gain=lost,
            metric={"metric": "stockout_days", "product_id": pid, "window_days": 28}))
        if len(out) >= 12:
            break
    return out


def a_overstock(ctx: Ctx) -> list[Draft]:
    """Capital asleep on the shelf: months of cover on slow movers."""
    from .insights import _stock
    agg = _product_agg(ctx.lines)
    out = []
    for pid, p in ctx.products.items():
        st = _stock(ctx, pid)
        if st <= 0:
            continue
        a = agg.get(pid)
        per_day = (a["qty"] / ctx.days) if a else 0.0
        if per_day <= 0:
            continue
        cover = st / per_day
        if cover < 120:
            continue
        cost = (a["cost"] / a["qty"]) if a["qty"] else 0.0   # observed unit cost; Product has none
        value = cost * st
        if value < 2000000:
            continue
        out.append(Draft(
            kind="OVERSTOCK", dedupe_key=str(pid),
            title=f"{p.name}: {int(cover)} روز موجودی (≈{_toman(value)} تومان خوابیده)",
            body=(f"با فروش روزانهٔ {per_day:.2f} عدد، موجودی فعلی {int(st)} عدد یعنی {int(cover)} روز. "
                  f"سرمایهٔ خوابیده {_toman(value)} تومان است. یک حراج پلکانی یا جابه‌جایی به جلوی قفسه، "
                  f"نقدینگی را برمی‌گرداند."),
            priority=3,
            evidence={"product_id": pid, "stock": int(st), "cover_days": int(cover),
                      "capital": round(value)},
            actions=[{"type": "shelf_note", "label": "جابه‌جایی به نقطهٔ دید", "params": {"products": [pid]}}],
            expected_gain=value * 0.04,
            metric={"metric": "product_units", "product_id": pid, "window_days": 28}))
        if len(out) >= 10:
            break
    return out


def a_abc_drift(ctx: Ctx) -> list[Draft]:
    """A-items losing their rank to C-items — the assortment is quietly changing under you."""
    older, newer = _split(ctx, ctx.days)
    def rank(lines):
        agg = {p: a["rev"] for p, a in _product_agg(lines).items()}
        tot = sum(agg.values()) or 1
        order = sorted(agg, key=agg.get, reverse=True)
        out, cum = {}, 0.0
        for i, p in enumerate(order):
            cum += agg[p] / tot
            out[p] = "A" if cum <= 0.7 else "B" if cum <= 0.9 else "C"
        return out
    ro, rn = rank(older), rank(newer)
    demoted = [p for p in rn if ro.get(p) == "A" and rn[p] == "C"]
    promoted = [p for p in rn if ro.get(p) == "C" and rn[p] == "A"]
    if not demoted and not promoted:
        return []
    return [Draft(
        kind="ABC_DRIFT", dedupe_key="shift",
        title=f"{len(demoted)} کالای درجهٔ A افت کرد، {len(promoted)} کالای درجهٔ C بالا آمد",
        body=("طبقه‌بندی ABC با سهم از فروش محاسبه شد. افت‌کرده‌ها: "
              + "، ".join(_pname(ctx, p) for p in demoted[:5])
              + ". بالاآمده‌ها: " + ("، ".join(_pname(ctx, p) for p in promoted[:5]) or "—")
              + ". جای قفسه و نقطهٔ سفارش باید با این واقعیت جدید تنظیم شود."),
        priority=3,
        evidence={"demoted": demoted[:15], "promoted": promoted[:15]},
        actions=[{"type": "shelf_note", "label": "بازچینی قفسه بر پایهٔ ABC جدید",
                  "params": {"products": (promoted + demoted)[:20]}}],
        expected_gain=0.0,
        metric={"metric": "avg_basket_size", "window_days": 28})]


def a_data_hygiene(ctx: Ctx) -> list[Draft]:
    """Selling from a product the database says is empty or misconfigured — silent stock loss."""
    from .insights import _stock
    bad = []
    for pid, p in ctx.products.items():
        sold = sum(l["qty"] for l in ctx.lines if l["pid"] == pid)
        if sold <= 0:
            continue
        if _stock(ctx, pid) < 0:
            bad.append((pid, "موجودی منفی"))
        elif not getattr(p, "barcode", None):
            bad.append((pid, "بدون بارکد"))
    if len(bad) < 3:
        return []
    return [Draft(
        kind="DATA_HYGIENE", dedupe_key="issues",
        title=f"{len(bad)} کالا با دادهٔ ناسازگار، در حال فروش",
        body=("این کالاها فروش دارند ولی داده‌شان درست نیست — موجودی منفی یا نبود بارکد. "
              "هر دو باعث می‌شود گزارش موجودی و نقطهٔ سفارش اشتباه بگویند و انبارگردانی بعدی "
              "پر از مغایرت باشد. نمونه‌ها: " + "، ".join(_pname(ctx, p) for p, _ in bad[:6]) + "."),
        priority=3,
        evidence={"count": len(bad), "items": [{"product_id": p, "issue": w} for p, w in bad[:25]]},
        actions=[{"type": "note", "label": "یادداشت اصلاح دادهٔ کالاها"}],
        expected_gain=0.0,
        metric={"metric": "availability", "product_id": bad[0][0], "window_days": 28})]


# --------------------------------------------------------------------------- 27-30: floor and time
def a_peak_hour(ctx: Ctx) -> list[Draft]:
    """The hour the shop is busiest, and how sharp that peak is — the staffing and promo window."""
    hours = Counter(l["at"].hour for l in ctx.lines)
    if len(hours) < 5 or not ctx.lines:
        return []
    h, n = hours.most_common(1)[0]
    total = sum(hours.values())
    if n / total < 0.12:
        return []
    quiet = min(hours, key=hours.get)
    return [Draft(
        kind="PEAK_HOUR", dedupe_key="hour",
        title=f"شلوغ‌ترین ساعت: {h}:۰۰ ({n / total * 100:.0f}٪ فروش)",
        body=(f"{n / total * 100:.0f}٪ قلم‌های فروخته‌شده در ساعت {h}:۰۰ ثبت شده و کم‌شلوغ‌ترین ساعت "
              f"{quiet}:۰۰ است. صفِ ساعت شلوغ، فروش از دست رفته است؛ ساعت خلوت هم ظرفیت بیکار. "
              f"تخفیف ساعتی یا جابه‌جایی نیرو بین این دو، بدون هزینهٔ اضافه سود می‌سازد."),
        priority=3,
        evidence={"peak_hour": h, "peak_share": round(n / total, 3), "quiet_hour": quiet,
                  "by_hour": {str(k): v for k, v in sorted(hours.items())}},
        actions=[{"type": "flash_sale", "label": "تخفیف ساعت خلوت", "params": {"percent": 8, "days": 7}}],
        expected_gain=0.0,
        metric={"metric": "avg_basket_size", "window_days": 28})]


def a_weekday_dip(ctx: Ctx) -> list[Draft]:
    """A weekday materially below the shop's own average — a targetable hole in the week."""
    per = defaultdict(float)
    cnt = Counter()
    for inv, d in ctx.invoices.items():
        per[d["at"].weekday()] += d["total"]
        cnt[d["at"].weekday()] += 1
    if len(cnt) < 6 or sum(cnt.values()) < 60:
        return []
    avg = sum(cnt.values()) / len(cnt)
    worst = min(cnt, key=lambda k: cnt[k])
    if cnt[worst] >= avg * 0.8:
        return []
    names = ["شنبه", "یکشنبه", "دوشنبه", "سه‌شنبه", "چهارشنبه", "پنجشنبه", "جمعه"]
    return [Draft(
        kind="WEEKDAY_DIP", dedupe_key=str(worst),
        title=f"{names[worst]}: {cnt[worst]} فاکتور در برابر میانگین {avg:.0f}",
        body=(f"این روز {(1 - cnt[worst] / avg) * 100:.0f}٪ زیر میانگین هفتگی فروشگاه است. "
              f"یک پیشنهاد محدود روی همین روز، ارزان‌ترین راه پر کردن آن است — چون زیرساخت و "
              f"نیروی روزهای شلوغ از قبل هست."),
        priority=3,
        evidence={"weekday": worst, "invoices": cnt[worst], "avg": round(avg, 1),
                  "by_weekday": {str(k): v for k, v in sorted(cnt.items())}},
        actions=[{"type": "flash_sale", "label": "تخفیف ویژهٔ همان روز", "params": {"percent": 10, "days": 7}}],
        expected_gain=(avg - cnt[worst]) * (sum(per.values()) / max(1, sum(cnt.values()))) * 0.08,
        metric={"metric": "weekday_sales", "weekday": worst, "window_days": 28})]


def a_supplier_concentration(ctx: Ctx) -> list[Draft]:
    """Most stock coming from one supplier: a single point of failure for the whole shelf."""
    from ..models import ProductBatch, Supplier
    rows = ctx.db.execute(
        select(Supplier.name, func.count(ProductBatch.id), func.coalesce(func.sum(ProductBatch.current_qty * ProductBatch.buy_price), 0))
        .join(Supplier, Supplier.id == ProductBatch.supplier_id)
        .where(ProductBatch.status == "ACTIVE", ProductBatch.current_qty > 0)
        .group_by(Supplier.id)).all()
    if len(rows) < 2:
        return []
    tot = sum(_f(r[2]) for r in rows) or 1
    top = max(rows, key=lambda r: _f(r[2]))
    share = _f(top[2]) / tot
    if share < 0.5:
        return []
    return [Draft(
        kind="SUPPLIER_CONCENTRATION", dedupe_key=str(top[0]),
        title=f"{top[0]}: {share * 100:.0f}٪ ارزش موجودی",
        body=(f"از {_toman(tot)} تومان کالای روی قفسه، {_toman(_f(top[2]))} تومان از یک تأمین‌کننده است. "
              f"هر اختلال در تأمین او، قفسه را خالی می‌کند و جایگزین فوری ندارد. "
              f"دست‌کم برای پرفروش‌ها یک منبع دوم پیدا کنید."),
        priority=3,
        evidence={"supplier": top[0], "share": round(share, 3), "value": round(_f(top[2])),
                  "suppliers": [{"name": r[0], "batches": int(r[1]), "value": round(_f(r[2]))} for r in rows]},
        actions=[{"type": "note", "label": "یادداشت منبع دوم"}],
        expected_gain=0.0,
        metric={"metric": "availability", "product_id": 0, "window_days": 28})]


def a_trend_break(ctx: Ctx) -> list[Draft]:
    """A change point in daily turnover: the shop's trend broke, and the reason is worth knowing."""
    daily = defaultdict(float)
    for inv, d in ctx.invoices.items():
        daily[d["at"].date()] += d["total"]
    if len(daily) < 20:
        return []
    keys = sorted(daily)
    half = len(keys) // 2
    a = [daily[k] for k in keys[:half]]
    b = [daily[k] for k in keys[half:]]
    ma, mb = statistics.mean(a), statistics.mean(b)
    if ma <= 0:
        return []
    chg = (mb - ma) / ma
    if abs(chg) < 0.15:
        return []
    sd = statistics.pstdev(a) or 1
    if abs(mb - ma) < sd * 0.8:
        return []
    word = "بالا" if chg > 0 else "پایین"
    return [Draft(
        kind="TREND_BREAK", dedupe_key=keys[-1].isoformat()[:7],
        title=f"فروش روزانه {abs(chg) * 100:.0f}٪ {word} رفته است",
        body=(f"میانگین فروش روزانه از {_toman(ma)} تومان به {_toman(mb)} تومان رسیده — "
              f"{(mb - ma) / sd:+.1f} انحراف معیار، یعنی احتمالاً تصادفی نیست. "
              f"اگر دلیلش را می‌دانید (فصل، رقیب، تغییر قیمت) روی همان کار کنید؛ "
              f"اگر نه، پیدا کردنش اولویت دارد."),
        priority=2 if chg < 0 else 3,
        evidence={"before": round(ma), "after": round(mb), "change_pct": round(chg * 100, 1),
                  "sigma": round((mb - ma) / sd, 2), "days": len(keys)},
        actions=[{"type": "note", "label": "یادداشت بررسی علت"}],
        expected_gain=0.0,
        metric={"metric": "avg_basket_size", "window_days": 28})]


def a_attach_opportunity(ctx: Ctx) -> list[Draft]:
    """The strongest product pair that is NOT yet suggested at the till — free basket growth."""
    pair = Counter()
    for inv, d in ctx.invoices.items():
        pids = sorted(d["pids"])
        for i in range(len(pids)):
            for j in range(i + 1, min(i + 6, len(pids))):
                pair[(pids[i], pids[j])] += 1
    if not pair:
        return []
    (a, b), n = pair.most_common(1)[0]
    inv_a = {i for i, d in ctx.invoices.items() if a in d["pids"]}
    both = {i for i in inv_a if b in ctx.invoices[i]["pids"]}
    rate = len(both) / max(1, len(inv_a))
    if n < 8 or rate > 0.35:
        return []   # either too rare, or already happening by itself
    return [Draft(
        kind="ATTACH_OPPORTUNITY", dedupe_key=f"{a}-{b}",
        title=f"«{_pname(ctx, a)}» و «{_pname(ctx, b)}» با هم خریده می‌شوند",
        body=(f"این دو کالا {n} بار در یک سبد بوده‌اند، ولی در {rate * 100:.0f}٪ سبدهایی که "
              f"«{_pname(ctx, a)}» دارد. یعنی {100 - rate * 100:.0f}٪ مواقع، مشتری اولی را برداشته و "
              f"دومی را نه — دقیقاً جایی که یک یادآوری پای صندوق پول می‌سازد."),
        priority=2,
        evidence={"a": a, "b": b, "co": n, "attach_rate": round(rate, 3), "invoices_with_a": len(inv_a)},
        actions=[{"type": "pos_nudge", "label": "یادآوری پای صندوق", "params": {"a": a, "b": b}}],
        expected_gain=len(inv_a) * (1 - rate) * 0.1 * _unit_price(ctx, b),
        metric={"metric": "attach_rate", "a": a, "b": b, "window_days": 28})]


ANALYZERS = {
    "CUST_PAYDAY": a_cust_payday, "CUST_CHURN_RISK": a_cust_churn_risk, "CUST_RFM": a_cust_rfm,
    "CUST_BASKET_SHRINK": a_cust_basket_shrink, "CUST_CATEGORY_LOSS": a_cust_category_loss,
    "CUST_NEW_SECOND": a_cust_new_second, "CUST_CREDIT_SLOW": a_cust_credit_slow,
    "CUST_CONCENTRATION": a_cust_concentration, "CUST_ANONYMOUS": a_cust_anonymous,
    "CUST_RETURN_ABUSE": a_cust_return_abuse, "CUST_LOYALTY_GAP": a_cust_loyalty_gap,
    "MARGIN_EROSION": a_margin_erosion, "DISCOUNT_LEAK": a_discount_leak,
    "PRICE_ROUNDING": a_price_rounding, "PROMO_DEPTH": a_promo_depth,
    "STOCKOUT_COST": a_stockout_cost, "OVERSTOCK": a_overstock, "ABC_DRIFT": a_abc_drift,
    "DATA_HYGIENE": a_data_hygiene, "PEAK_HOUR": a_peak_hour, "WEEKDAY_DIP": a_weekday_dip,
    "SUPPLIER_CONCENTRATION": a_supplier_concentration, "TREND_BREAK": a_trend_break,
    "ATTACH_OPPORTUNITY": a_attach_opportunity,
}

KIND_LABELS = {
    "CUST_PAYDAY": "روز پول مشتری", "CUST_CHURN_RISK": "خطر ریزش مشتری", "CUST_RFM": "باشگاه مشتریان برتر",
    "CUST_BASKET_SHRINK": "کوچک شدن سبد", "CUST_CATEGORY_LOSS": "کالای فراموش‌شدهٔ مشتری",
    "CUST_NEW_SECOND": "خرید دوم مشتری تازه", "CUST_CREDIT_SLOW": "نسیهٔ دیرکرد",
    "CUST_CONCENTRATION": "وابستگی به چند مشتری", "CUST_ANONYMOUS": "فروش بدون مشتری",
    "CUST_RETURN_ABUSE": "مرجوعی غیرعادی", "CUST_LOYALTY_GAP": "مشتری بدون شماره",
    "MARGIN_EROSION": "فرسایش حاشیهٔ سود", "DISCOUNT_LEAK": "نشت تخفیف پای صندوق",
    "PRICE_ROUNDING": "رُند نبودن قیمت", "PROMO_DEPTH": "تخفیف بیش از حاشیه",
    "STOCKOUT_COST": "هزینهٔ اتمام موجودی", "OVERSTOCK": "سرمایهٔ خوابیده",
    "ABC_DRIFT": "جابه‌جایی درجهٔ کالاها", "DATA_HYGIENE": "دادهٔ ناسازگار کالا",
    "PEAK_HOUR": "ساعت اوج و خلوت", "WEEKDAY_DIP": "روز کم‌فروش هفته",
    "SUPPLIER_CONCENTRATION": "وابستگی به یک تأمین‌کننده", "TREND_BREAK": "شکست روند فروش",
    "ATTACH_OPPORTUNITY": "فرصت هم‌خرید",
}


# ----------------------------------------------------------------------------- superseded analyzers
# v3.6.1 — this module and ``insights_pro`` were written on two branches that did not know about
# each other. Registering both as-is meant the shop saw TWO cards for one problem, and for three
# kinds the identical key meant one analyzer silently replaced the other. The engine is only
# useful if every card is a distinct decision, so the analyzers below are deliberately NOT
# registered: ``insights_pro`` (or the base engine) already covers the same ground, usually with
# more evidence. The functions stay so the reasoning is not lost and so a future merge can see
# exactly what was folded into what.
SUPERSEDED_BY = {
    # exact kind collisions — without this filter one dict overwrote the other
    "DISCOUNT_LEAK":        "insights_pro.DISCOUNT_LEAK",
    "PRICE_ROUNDING":       "insights_pro.PRICE_ROUNDING",
    "OVERSTOCK":            "insights_pro.OVERSTOCK",
    # same decision, different name
    "CUST_PAYDAY":          "insights_pro.PAY_CYCLE",
    "CUST_BASKET_SHRINK":   "insights_pro.TICKET_DROP",
    "CUST_CHURN_RISK":      "insights_pro.FREQ_DROP + base CHURN",
    "CUST_NEW_SECOND":      "insights_pro.NEW_CUST_2ND",
    "CUST_CATEGORY_LOSS":   "insights_pro.CATEGORY_GAP",
    "CUST_CREDIT_SLOW":     "insights_pro.CREDIT_RISK",
    "CUST_ANONYMOUS":       "insights_pro.UNREGISTERED_SALES",
    "STOCKOUT_COST":        "insights_pro.STOCKOUT_HISTORY",
    "WEEKDAY_DIP":          "insights_pro.SLOW_DAY",
    "PEAK_HOUR":            "insights_pro.PEAK_HOURS",
    "TREND_BREAK":          "insights_pro.TREND_DOWN",
    "ATTACH_OPPORTUNITY":   "base CROSS_SELL",
}

ACTIVE = {k: v for k, v in ANALYZERS.items() if k not in SUPERSEDED_BY}


# ----------------------------------------------------------------------------- self-registration
# Register into the main registry from here so the import works in BOTH orders. When
# ``customer_intel`` is imported first, ``insights`` has already finished executing by the time
# this line runs; when ``insights`` is imported first, it imports this module explicitly and
# merges the dicts itself (see the bottom of insights.py).
from . import insights as _insights  # noqa: E402

_insights.ANALYZERS.update(ACTIVE)
_insights.KIND_LABELS.update({k: v for k, v in KIND_LABELS.items() if k in ACTIVE})

# The feed is grouped (insights_pro.GROUPS) and a kind with no group simply does not appear in
# any group's count — the insight exists but the shop never sees it. Every registered kind must
# sit in exactly one group; tests/test_v35_intelligence_pro.py enforces that invariant.
_GROUP_ADDITIONS = {
    "customer": ["CUST_RFM", "CUST_CONCENTRATION", "CUST_LOYALTY_GAP", "CUST_RETURN_ABUSE"],
    "price":    ["MARGIN_EROSION", "PROMO_DEPTH"],
    "stock":    ["ABC_DRIFT", "SUPPLIER_CONCENTRATION"],
    "ops":      ["DATA_HYGIENE"],
}
for _g, _kinds in _GROUP_ADDITIONS.items():
    if _g in _insights.GROUPS:
        for _k in _kinds:
            if _k in ACTIVE and _k not in _insights.GROUPS[_g][1]:
                _insights.GROUPS[_g][1].append(_k)
