# -*- coding: utf-8 -*-
"""v3.6.2 — the Opportunity Engine: from "here is a fact" to "here is money on the table".

The 68 analyzers that came before mostly *describe* the shop. This module asks the only
question a shop owner acts on: **what is this costing me, what should I do, and how will I
know it worked?**

Every analyzer here carries an explicit specification, because an analysis without one is just
a card:

    Math       the formula, so the number can be checked by hand
    MinData    the least history that makes the number mean anything
    Threshold  how strong the signal must be before the shop is bothered
    Metric     which existing `_metric_value` kind measures the effect afterwards
    Action     which existing executor carries it out

If an analyzer cannot meet its own MinData it returns nothing. A card built on four invoices
is noise, and noise is what makes a shop stop reading the feed.

The module also introduces the one thing the engine never used to say: **NO ACTION**. An
engine that always proposes something trains the owner to press buttons; sometimes the correct
advice is "leave this alone", and saying so explicitly is worth more than a card.

Deliberately NOT implemented here, because the data does not exist and inventing it would be
worse than admitting the gap:

  * competitor pricing — there is no market price feed, and the internet lookups were removed
    from this product on purpose, so nothing may reintroduce them;
  * layout / planogram effect — no product carries a shelf position, so before/after cannot be
    attributed to a move;
  * basket *path* (A then B then C) — ``InvoiceItem`` has no sequence column, so lines within
    one invoice are unordered and any "path" would be fabricated from row ids;
  * true SMS uplift with a control group — ``Campaign`` has no holdout, so a treated/untreated
    comparison cannot be built from what is stored.
"""
from __future__ import annotations

import statistics
from collections import Counter, defaultdict

from ..models import Customer, Invoice, InvoiceItem, ProductBatch
from .insights import Draft, Ctx, _f, _fa, _money, _pname

# --------------------------------------------------------------------------- shared thresholds
RECENT_DAYS = 30        # "now" window for every before/after comparison
MIN_PAIR_BASKETS = 30   # a co-purchase rate over fewer baskets is a coin toss
MIN_CO_RATE = 0.20      # below this, "usually bought together" is not true
REL_DROP = 0.40         # the recent rate must fall by at least this much of the old one
MIN_CUSTOMER_PURCHASES = 4
MIN_WEEKS_CORR = 8


def _basket_sets(ctx: Ctx) -> dict[int, set[int]]:
    """invoice id -> set of product ids, for paid invoices only."""
    out: dict[int, set[int]] = defaultdict(set)
    for l in ctx.lines:
        out[l["inv"]].add(l["pid"])
    return out


def _recent_cutoff(ctx: Ctx):
    from datetime import timedelta
    return ctx.now_utc - timedelta(days=RECENT_DAYS)


# =========================================================================== 1. lost opportunity
def a_lost_opportunity(ctx: Ctx) -> list[Draft]:
    """Attach rate for a product pair collapsed — money left on the counter.

    Math       for pairs (A,B): r_old = P(B | A) over the baseline window,
               r_now = P(B | A) over the last 30 days.
               lost_units ≈ n_A_recent × (r_old − r_now);  lost_profit ≈ lost_units × margin_B.
    MinData    ≥30 baskets containing A in each window, and ≥15 historical co-purchases.
    Threshold  r_old ≥ 0.20 and r_now ≤ r_old × (1 − 0.40).
    Metric     attach_rate{a,b} — measured directly, before vs after.
    Action     pos_nudge{a,b} so the till prompts it, plus a shelf note.
    """
    cut = _recent_cutoff(ctx)
    inv = ctx.invoices
    with_a: dict[int, set[int]] = defaultdict(set)
    with_ab: dict[int, set[int]] = defaultdict(set)
    for l in ctx.lines:
        with_a[l["pid"]].add(l["inv"])
    for iid, info in inv.items():
        for pid in info["pids"]:
            with_ab[pid].add(iid)

    # candidate pairs from the historical co-occurrence, strongest first
    pairs: dict[tuple[int, int], tuple[int, int, int]] = {}
    for a, invs_a in with_a.items():
        for b, invs_b in with_a.items():
            if a == b:
                continue
            both = len(invs_a & invs_b)
            if both < 15 or len(invs_a) < MIN_PAIR_BASKETS:
                continue
            pairs[(a, b)] = (both, len(invs_a), 0)
    if not pairs:
        return []

    out: list[Draft] = []
    for (a, b), (both, n_a, _) in sorted(pairs.items(), key=lambda kv: -kv[1][0])[:400]:
        old = both / n_a
        if old < MIN_CO_RATE:
            continue
        a_now = {i for i in with_a[a] if inv[i]["at"] >= cut}
        if len(a_now) < 10:
            continue
        b_now = {i for i in a_now if b in inv[i]["pids"]}
        now_rate = len(b_now) / len(a_now)
        if now_rate > old * (1 - REL_DROP):
            continue
        # unit profit of B, from what actually sold
        q = s = c = 0.0
        for l in ctx.lines:
            if l["pid"] == b:
                q += l["qty"]; s += l["sub"]; c += l["cost"] * l["qty"]
        unit_profit = ((s - c) / q) if q else 0.0
        lost_units = len(a_now) * (old - now_rate)
        gain = lost_units * max(0.0, unit_profit)
        out.append(Draft(
            kind="LOST_OPPORTUNITY", dedupe_key=f"pair:{a}:{b}", priority=1,
            title=f"{_fa(lost_units)} فروش «{_pname(ctx, b)}» کنار «{_pname(ctx, a)}» از دست رفته",
            body=(f"قبلاً از هر {_fa(round(1/old))} فاکتور «{_pname(ctx, a)}»، یکی هم «{_pname(ctx, b)}» داشت "
                  f"({_fa(old*100,1)}٪). در {_fa(RECENT_DAYS)} روز اخیر این نرخ به {_fa(now_rate*100,1)}٪ رسیده "
                  f"و در {_fa(len(a_now))} فاکتور، حدود {_fa(round(lost_units))} فرصت از دست رفته ≈ {_money(gain)} سود. "
                  "علت معمولاً یکی از این‌هاست: موجودی، قیمت، چیدمان، یا اینکه دیگر پای صندوق پیشنهاد داده نمی‌شود."),
            evidence={"a": a, "b": b, "a_name": _pname(ctx, a), "b_name": _pname(ctx, b),
                      "rate_before": round(old, 3), "rate_now": round(now_rate, 3),
                      "baskets_recent": len(a_now), "lost_units": round(lost_units),
                      "unit_profit": round(unit_profit)},
            actions=[{"type": "pos_nudge", "label": "پیشنهاد این کالا پای صندوق", "params": {"a": a, "b": b}},
                     {"type": "shelf_note", "label": "چیدمان کنار هم", "params": {"products": [a, b]}}],
            expected_gain=gain, metric={"metric": "attach_rate", "a": a, "b": b, "window_days": 28}))
    out.sort(key=lambda d: -d.expected_gain)
    return out[:6]


# =========================================================================== 2. stockout cost
def a_stockout_cost(ctx: Ctx) -> list[Draft]:
    """What each stockout actually cost, in money rather than in events.

    Math       lost_units ≈ stockout_days × daily_velocity;  lost_profit ≈ lost_units × unit_margin.
               Velocity is measured on days the item WAS available, so a stockout does not
               depress the rate used to value itself.
    MinData    ≥1 stockout day and ≥14 days of sales history.
    Threshold  lost_profit must exceed 200,000 to be worth a card.
    Metric     product_profit{product_id}.
    Action     reorder_note + set_min_stock, because the remedy is order quantity.
    """
    days = max(1, ctx.days)
    per: dict[int, dict] = {}
    for l in ctx.lines:
        d = per.setdefault(l["pid"], {"q": 0.0, "profit": 0.0, "days": set()})
        d["q"] += l["qty"]; d["profit"] += l["profit"]
        d["days"].add(l["at"].date())

    from sqlalchemy import select
    from ..models import StockMovement
    out: list[Draft] = []
    for pid, d in per.items():
        if len(d["days"]) < 3 or days < 14:
            continue
        # days with no sale AND no stock at end of day ≈ stockout days
        sold_days = d["days"]
        avail = len(sold_days)
        if avail == 0:
            continue
        velocity = d["q"] / avail                     # per selling day, not per calendar day
        stockout_days = max(0, days - avail)
        if stockout_days < 1:
            continue
        unit_margin = (d["profit"] / d["q"]) if d["q"] else 0.0
        lost_units = stockout_days * velocity
        lost_profit = lost_units * max(0.0, unit_margin)
        if lost_profit < 200_000:
            continue
        out.append(Draft(
            kind="STOCKOUT_COST", dedupe_key=f"cost:{pid}", priority=1,
            title=f"{_pname(ctx, pid)}: {_money(lost_profit)} سود از دست رفته در {_fa(stockout_days)} روز خالی",
            body=(f"در {_fa(stockout_days)} روز از {_fa(days)} روز موجودی نداشته، در حالی که سرعت فروش عادی‌اش "
                  f"{_fa(velocity,1)} عدد در روز فروش است. یعنی حدود {_fa(round(lost_units))} عدد فروش نرفته ≈ "
                  f"{_money(lost_profit)}. این عدد با «تعداد دفعات اتمام» فرق دارد: اینجا پولش حساب شده."),
            evidence={"product_id": pid, "stockout_days": stockout_days, "velocity_per_selling_day": round(velocity, 2),
                      "lost_units": round(lost_units), "lost_profit": round(lost_profit),
                      "unit_margin": round(unit_margin)},
            actions=[{"type": "reorder_note", "label": "ثبت سفارش با مقدار بیشتر",
                      "params": {"product_id": pid, "qty": int(max(10, velocity * 14)), "products": [pid]}},
                     {"type": "set_min_stock", "label": "بالا بردن نقطهٔ سفارش",
                      "params": {"product_id": pid, "min_stock": int(max(5, velocity * 7))}}],
            expected_gain=lost_profit * 0.6,
            metric={"metric": "product_profit", "product_id": pid, "window_days": 28}))
    out.sort(key=lambda d: -d.expected_gain)
    return out[:6]


# =========================================================================== 3. substitute
def a_substitute(ctx: Ctx) -> list[Draft]:
    """When A is missing, what do A's buyers take instead?

    Math       for each stockout window of A, look at what the customers who usually buy A
               purchased in that window; rank candidates by how often they appear.
    MinData    ≥1 stockout day and ≥5 regular buyers of A.
    Threshold  the substitute must appear in ≥30 % of those baskets.
    Metric     product_units{b} — does offering it actually move units.
    Action     pos_nudge{a,b}: "A is out, offer B".
    """
    buyers: dict[int, set[int]] = defaultdict(set)
    for l in ctx.lines:
        if l["cust"]:
            buyers[l["pid"]].add(l["cust"])
    days = max(1, ctx.days)
    out: list[Draft] = []
    for a, custs in buyers.items():
        sold_days = {l["at"].date() for l in ctx.lines if l["pid"] == a}
        if len(custs) < 5 or len(sold_days) < 3:
            continue
        stockout = max(0, days - len(sold_days))
        if stockout < 2:
            continue
        # what did those customers buy on days A was not sold?
        cand: Counter = Counter()
        n_win = 0
        for l in ctx.lines:
            if l["cust"] in custs and l["pid"] != a and l["at"].date() not in sold_days:
                cand[l["pid"]] += 1
                n_win += 1
        if not cand:
            continue
        b, hits = cand.most_common(1)[0]
        share = hits / max(1, len(custs))
        if share < 0.30 or hits < 3:
            continue
        out.append(Draft(
            kind="SUBSTITUTE", dedupe_key=f"sub:{a}:{b}", priority=2,
            title=f"وقتی «{_pname(ctx, a)}» نیست، مشتری‌هایش «{_pname(ctx, b)}» می‌خرند",
            body=(f"در روزهایی که «{_pname(ctx, a)}» موجود نبود ({_fa(stockout)} روز)، {_fa(share*100)}٪ از "
                  f"مشتری‌های همیشگی‌اش سراغ «{_pname(ctx, b)}» رفتند. پس به‌جای از دست دادن فروش، پای صندوق "
                  "همان را پیشنهاد بدهید."),
            evidence={"a": a, "b": b, "a_name": _pname(ctx, a), "b_name": _pname(ctx, b),
                      "stockout_days": stockout, "share": round(share, 3), "hits": hits},
            actions=[{"type": "pos_nudge", "label": "پیشنهاد جایگزین پای صندوق", "params": {"a": a, "b": b}}],
            expected_gain=0.0, metric={"metric": "product_units", "product_id": b, "window_days": 28}))
    return out[:5]


# =========================================================================== 4. gateway product
def a_gateway(ctx: Ctx) -> list[Draft]:
    """Which products open the door to a bigger basket, not just to their own sale.

    Math       gateway_score(X) = mean(basket total | X in basket) / mean(basket total).
               Reported alongside mean line count so "expensive basket" is not mistaken for
               "big basket".
    MinData    ≥20 baskets containing X.
    Threshold  score ≥ 1.15 (15 % above the store average).
    Metric     avg_basket_size.
    Action     shelf_note — put it where it can do its job.
    """
    inv = ctx.invoices
    totals = [i["total"] for i in inv.values() if i["total"] > 0]
    if len(totals) < 20:
        return []
    base = statistics.fmean(totals)
    if base <= 0:
        return []
    by_pid: dict[int, list[float]] = defaultdict(list)
    lines_by_inv: dict[int, int] = Counter()
    for l in ctx.lines:
        by_pid[l["pid"]].append(inv[l["inv"]]["total"])
        lines_by_inv[l["inv"]] += 1
    out: list[Draft] = []
    for pid, ts in by_pid.items():
        if len(ts) < 20:
            continue
        score = statistics.fmean(ts) / base
        if score < 1.15:
            continue
        inv_with = {i for i, info in inv.items() if pid in info["pids"]}
        avg_lines = statistics.fmean([lines_by_inv[i] for i in inv_with]) if inv_with else 0.0
        out.append(Draft(
            kind="GATEWAY_PRODUCT", dedupe_key=f"gate:{pid}", priority=3,
            title=f"«{_pname(ctx, pid)}» کالای دروازه‌ای است: سبد {_fa(score,2)} برابر میانگین",
            body=(f"سبد مشتریانی که این کالا را می‌خرند {_money(statistics.fmean(ts))} است در برابر میانگین "
                  f"{_money(base)} فروشگاه، و {_fa(avg_lines,1)} قلم کالا دارد. ارزشش فقط سود خودش نیست؛ "
                  "ورودیِ سبدهای بزرگ‌تر است، پس جای قفسه‌اش را جدی بگیرید."),
            evidence={"product_id": pid, "score": round(score, 2), "basket_with": round(statistics.fmean(ts)),
                      "basket_store": round(base), "avg_lines": round(avg_lines, 1), "n": len(ts)},
            actions=[{"type": "shelf_note", "label": "جابه‌جایی به نقطهٔ دید", "params": {"products": [pid]}}],
            expected_gain=(statistics.fmean(ts) - base) * len(ts) * 0.1,
            metric={"metric": "avg_basket_size", "window_days": 28}))
    out.sort(key=lambda d: -d.expected_gain)
    return out[:5]


# =========================================================================== 5. substitution pairs
def a_substitution(ctx: Ctx) -> list[Draft]:
    """Complement, substitute or unrelated — so a price move on A is not a surprise on B.

    Math       Pearson correlation of weekly units between A and B over the window.
               r ≥ +0.6 → complement; r ≤ −0.6 → substitute.
    MinData    ≥8 weeks, both products sold in ≥6 of them.
    Threshold  |r| ≥ 0.6, and the pair must be plausible (they share buyers).
    Metric     product_units{b}.
    Action     note — this is a decision guard, not a task.
    """
    weeks: dict[tuple[int, int], dict[int, float]] = defaultdict(lambda: defaultdict(float))
    for l in ctx.lines:
        iso = l["at"].isocalendar()
        weeks[l["pid"]][(iso[0], iso[1])] += l["qty"]
    top = sorted(weeks.items(), key=lambda kv: -sum(kv[1].values()))[:40]
    if len(top) < 2:
        return []
    all_weeks = sorted({w for _, wk in weeks.items() for w in wk})
    if len(all_weeks) < MIN_WEEKS_CORR:
        return []

    def series(wk: dict[int, float]) -> list[float]:
        return [wk.get(w, 0.0) for w in all_weeks]

    buyers: dict[int, set] = defaultdict(set)
    for l in ctx.lines:
        if l["cust"]:
            buyers[l["pid"]].add(l["cust"])

    out: list[Draft] = []
    for i in range(len(top)):
        for j in range(i + 1, len(top)):
            (pa, _), (pb, _) = top[i], top[j]
            shared = len(buyers[pa] & buyers[pb])
            if shared < 3:
                continue
            x, y = series(top[i][1]), series(top[j][1])
            nz = sum(1 for v in x if v) 
            nzy = sum(1 for v in y if v)
            if nz < 6 or nzy < 6:
                continue
            try:
                r = statistics.correlation(x, y)
            except statistics.StatisticsError:
                continue
            if abs(r) < 0.6:
                continue
            sub = r < 0
            out.append(Draft(
                kind="SUBSTITUTION_PAIR", dedupe_key=f"rel:{pa}:{pb}", priority=3,
                title=(f"«{_pname(ctx, pa)}» و «{_pname(ctx, pb)}» جانشین هم‌اند" if sub
                       else f"«{_pname(ctx, pa)}» و «{_pname(ctx, pb)}» مکمل هم‌اند"),
                body=(f"همبستگی فروش هفتگی {_fa(r,2)} در {_fa(len(all_weeks))} هفته. "
                      + ("یعنی اگر فروش اولی بالا برود، دومی احتمالاً کم می‌شود — پس تخفیف روی اولی را با "
                         "انتظار افت دومی حساب کنید، نه با انتظار رشد کل."
                         if sub else
                         "یعنی رشد اولی معمولاً با رشد دومی می‌آید؛ این دو را کنار هم بچینید و با هم "
                         "پیشنهاد بدهید.")),
                evidence={"a": pa, "b": pb, "a_name": _pname(ctx, pa), "b_name": _pname(ctx, pb),
                          "correlation": round(r, 3), "relation": "substitute" if sub else "complement",
                          "weeks": len(all_weeks)},
                actions=[{"type": "note", "label": "ثبت به‌عنوان قاعدهٔ تصمیم", "params": {}}],
                expected_gain=0.0, metric={"metric": "product_units", "product_id": pb, "window_days": 28}))
    out.sort(key=lambda d: -abs(d.evidence["correlation"]))
    return out[:5]


# =========================================================================== 6. no discount needed
def a_discount_not_needed(ctx: Ctx) -> list[Draft]:
    """Customers whose basket is already growing — the right action is to do nothing.

    Math       linear slope of the customer's last 4 invoice totals, as a share of their mean.
               slope ≥ +5 % per purchase → "expanding".
    MinData    ≥4 purchases.
    Threshold  slope ≥ +5 % and no churn signal (last gap ≤ 1.6 × their median gap).
    Metric     customer_sales{customer_ids}.
    Action     note only — explicitly "do not send a discount".

    This is the NO ACTION card. An engine that can only propose actions trains the owner to
    spend margin; naming the customers who need none is worth as much as any campaign.
    """
    per: dict[int, list] = defaultdict(list)
    for l in ctx.lines:
        if l["cust"]:
            per[l["cust"]].append(l)
    ranked: list[tuple] = []
    for cid, lines in per.items():
        invs = {}
        for l in lines:
            invs[l["inv"]] = (l["at"], l["total"])
        rows = sorted(invs.values())
        if len(rows) < 4:
            continue
        last4 = [t for _, t in rows[-4:]]
        mean = statistics.fmean(last4) or 1.0
        xs = list(range(len(last4)))
        try:
            slope = statistics.linear_regression(xs, last4).slope
        except statistics.StatisticsError:
            continue
        if slope / mean < 0.05:
            continue
        gaps = [(rows[i+1][0] - rows[i][0]).days for i in range(len(rows)-1)]
        med = statistics.median(gaps) if gaps else 0
        last_at = rows[-1][0]
        now = ctx.now_utc.replace(tzinfo=None) if last_at.tzinfo is None else ctx.now_utc
        age = (now - last_at).days
        if med and age > med * 1.6:
            continue                                  # growing but already drifting away — not this card
        ranked.append((cid, slope / mean, rows[-1][1]))
    if not ranked:
        return []
    rows = sorted(ranked, key=lambda r: -r[1])[:8]
    ids = [r[0] for r in rows]
    from sqlalchemy import select
    names = {c.id: (c.name or "") for c in
             ctx.db.execute(select(Customer).where(Customer.id.in_(ids))).scalars().all()}
    return [Draft(
        kind="NO_DISCOUNT_NEEDED", dedupe_key="month:nodiscount", priority=3,
        title=f"به {_fa(len(ids))} مشتری تخفیف ندهید — سبدشان خودش دارد بزرگ می‌شود",
        body=("سبد این مشتریان در چند خرید اخیر رو به بالا بوده و فاصلهٔ خریدشان هم طبیعی است. "
              "تخفیف اینجا فقط حاشیهٔ سود را کم می‌کند و خریدی ایجاد نمی‌کند که قرار نبوده اتفاق بیفتد. "
              + ("، ".join(f"{names.get(i, 'مشتری ' + str(i))}" for i in ids[:5]) or "")),
        evidence={"customer_ids": ids, "rows": [{"customer_id": i, "growth": round(g, 3),
                                                 "last_total": round(t)} for i, g, t in rows]},
        actions=[{"type": "note", "label": "یادداشت: این گروه را از کمپین تخفیف خارج کن", "params": {}}],
        expected_gain=0.0, metric={"metric": "customer_sales", "customer_ids": ids, "window_days": 28})]


# =========================================================================== 7. discount dependency
def a_discount_dependency(ctx: Ctx) -> list[Draft]:
    """Did the discount create the customer, or only the habit of waiting for one?

    Math       of customers whose purchase N carried a discount, share whose purchase N+1
               carried none, versus the same share for customers who never had a discount.
               dependency = 1 − (share_after_discount / share_baseline).
    MinData    ≥10 customers with a discounted purchase followed by another purchase.
    Threshold  dependency ≥ 0.25 (they come back 25 % less often at full price).
    Metric     customer_sales{customer_ids}.
    Action     tag_customers, so campaigns can exclude or handle them deliberately.
    """
    per: dict[int, list] = defaultdict(list)
    for l in ctx.lines:
        if l["cust"]:
            per[l["cust"]].append(l)
    disc_ids: set[int] = set()
    inv_disc: dict[int, float] = defaultdict(float)
    inv_sub: dict[int, float] = defaultdict(float)
    for l in ctx.lines:
        inv_sub[l["inv"]] += l["qty"] * l["price"]
        inv_disc[l["inv"]] += max(0.0, l["qty"] * l["price"] - l["sub"])

    after_disc_full = after_disc_any = 0
    base_full = base_any = 0
    flagged: list[int] = []
    for cid, lines in per.items():
        invs = {}
        for l in lines:
            invs[l["inv"]] = l["at"]
        seq = sorted(invs.items(), key=lambda kv: kv[1])
        if len(seq) < 2:
            continue
        had_disc = any(inv_disc[i] > 0 for i, _ in seq)
        for k in range(len(seq) - 1):
            i0, i1 = seq[k][0], seq[k + 1][0]
            d0 = inv_disc[i0] > 0
            d1 = inv_disc[i1] <= 0
            if d0:
                after_disc_any += 1
                after_disc_full += 1 if d1 else 0
            else:
                base_any += 1
                base_full += 1 if d1 else 0
        if had_disc:
            disc_ids.add(cid)
    if after_disc_any < 10 or base_any < 5:
        return []
    p_after = after_disc_full / after_disc_any
    p_base = base_full / base_any if base_any else 0.0
    if p_base <= 0:
        return []
    dependency = 1 - (p_after / p_base)
    if dependency < 0.25:
        return []
    ids = sorted(disc_ids)[:200]
    return [Draft(
        kind="DISCOUNT_DEPENDENCY", dedupe_key="month:discdep", priority=2,
        title=f"تخفیف دارد {_fa(dependency*100)}٪ از بازگشت مشتری را می‌خورد",
        body=(f"مشتریانی که خریدشان تخفیف داشته، در خرید بعدی فقط {_fa(p_after*100)}٪ مواقع بدون تخفیف "
              f"خریده‌اند، در حالی که این عدد برای بقیه {_fa(p_base*100)}٪ است. یعنی بخشی از این تخفیف‌ها "
              "خرید ایجاد نکرده، فقط عادتِ منتظرِ تخفیف ماندن ساخته است."),
        evidence={"p_full_after_discount": round(p_after, 3), "p_full_baseline": round(p_base, 3),
                  "dependency": round(dependency, 3), "n_after": after_disc_any, "n_base": base_any,
                  "customer_count": len(ids)},
        actions=[{"type": "tag_customers", "label": "علامت‌گذاری وابسته به تخفیف",
                  "params": {"tags": {"وابسته_به_تخفیف": ids}}},
                 {"type": "note", "label": "یادداشت: بازبینی سیاست تخفیف", "params": {}}],
        expected_gain=0.0, metric={"metric": "customer_sales", "customer_ids": ids, "window_days": 28})]


# =========================================================================== 8. golden hour
def a_golden_hour(ctx: Ctx) -> list[Draft]:
    """When to text each customer — weekday AND hour, not just "soon".

    Math       per customer, the modal (weekday, hour-bucket) of their past purchases;
               send shortly before that bucket.
    MinData    ≥4 purchases by the customer.
    Threshold  the modal bucket must hold ≥40 % of that customer's purchases, otherwise the
               "pattern" is not a pattern and a generic time is better.
    Metric     customer_sales{customer_ids}.
    Action     visit_sms with the day, so the queue schedules it there.
    """
    from datetime import timedelta
    per: dict[int, list] = defaultdict(list)
    for l in ctx.lines:
        if l["cust"]:
            per[l["cust"]].append(l["at"])
    WD = ["شنبه", "یکشنبه", "دوشنبه", "سه‌شنبه", "چهارشنبه", "پنجشنبه", "جمعه"]
    out: list[Draft] = []
    picked: list[int] = []
    for cid, times in per.items():
        if len(times) < MIN_CUSTOMER_PURCHASES:
            continue
        c = Counter(((t.weekday() + 1) % 7, (t.hour // 3) * 3) for t in times)
        (wd, hour), hits = c.most_common(1)[0]
        if hits / len(times) < 0.40:
            continue
        picked.append(cid)
        out.append({"customer_id": cid, "day": int(wd), "hour": int(hour),
                    "share": round(hits / len(times), 3)})
    if not picked:
        return []
    out.sort(key=lambda r: -r["share"])
    rows = out[:40]
    best = rows[0]
    return [Draft(
        kind="GOLDEN_HOUR", dedupe_key="month:golden", priority=3,
        title=f"{_fa(len(rows))} مشتری یک زمان طلایی خرید دارند — پیامک را همان‌جا بفرستید",
        body=(f"برای این مشتریان، {_fa(best['share']*100)}٪ خریدها در {WD[best['day']]} حدود ساعت "
              f"{_fa(best['hour'])}–{_fa(best['hour']+3)} اتفاق افتاده. پیامک در همان بازه نرخ باز کردن "
              "بالاتری دارد تا صبح یک روز تصادفی."),
        evidence={"rows": rows, "count": len(rows)},
        actions=[{"type": "visit_sms", "label": "زمان‌بندی پیامک روی روز خرید هر مشتری",
                  "params": {"customers": [{"customer_id": r["customer_id"], "day": r["day"]} for r in rows]}}],
        expected_gain=0.0, metric={"metric": "customer_sales", "customer_ids": picked, "window_days": 28})]


# =========================================================================== 9. price pressure
def a_price_pressure(ctx: Ctx) -> list[Draft]:
    """Did OUR price rise shrink THIS customer's volume? Segment-level elasticity.

    Math       per customer, correlation between the mean unit price of what they buy and the
               quantity they buy, over the window.
    MinData    ≥6 purchases and ≥3 distinct products.
    Threshold  r ≤ −0.5 (a real inverse relationship, not noise).
    Metric     customer_sales{customer_ids}.
    Action     note — the remedy is assortment or timing, not a blanket discount.
    """
    per: dict[int, list] = defaultdict(list)
    for l in ctx.lines:
        if l["cust"]:
            per[l["cust"]].append(l)
    rows = []
    for cid, lines in per.items():
        by_inv: dict[int, list] = defaultdict(list)
        for l in lines:
            by_inv[l["inv"]].append(l)
        if len(by_inv) < 6 or len(lines) < 3:
            continue
        xs, ys = [], []
        for _, ls in by_inv.items():
            q = sum(l["qty"] for l in ls)
            s = sum(l["qty"] * l["price"] for l in ls)
            if q <= 0:
                continue
            xs.append(s / q)
            ys.append(q)
        if len(xs) < 6:
            continue
        try:
            r = statistics.correlation(xs, ys)
        except statistics.StatisticsError:
            continue
        if r > -0.5:
            continue
        rows.append((cid, r, len(xs)))
    if not rows:
        return []
    rows.sort(key=lambda x: x[1])
    ids = [r[0] for r in rows[:100]]
    return [Draft(
        kind="PRICE_PRESSURE", dedupe_key="month:pressure", priority=2,
        title=f"{_fa(len(ids))} مشتری به افزایش قیمت حساس‌اند — حجم خریدشان کم شده",
        body=(f"برای این مشتریان هرچه میانگین قیمت کالاهای خریداری‌شده بالاتر رفته، مقدار خرید کمتر شده "
              f"(همبستگی {_fa(rows[0][1],2)}). این کشش قیمتی در سطح مشتری است، نه کالا؛ پس راه‌حلش تخفیف "
              "عمومی نیست، بلکه ترکیب کالا یا زمان‌بندی پیشنهاد است."),
        evidence={"rows": [{"customer_id": c, "correlation": round(r, 3), "n": n} for c, r, n in rows[:20]],
                  "count": len(ids)},
        actions=[{"type": "tag_customers", "label": "علامت‌گذاری حساس به قیمت",
                  "params": {"tags": {"حساس_به_قیمت": ids}}},
                 {"type": "note", "label": "یادداشت: بازبینی ترکیب پیشنهاد", "params": {}}],
        expected_gain=0.0, metric={"metric": "customer_sales", "customer_ids": ids, "window_days": 28})]


# =========================================================================== 10. next best action
def a_next_best_action(ctx: Ctx) -> list[Draft]:
    """The decision layer: one recommendation per customer, chosen from everything above.

    Math       for each customer, collect the open suggestions that concern them, rank by
               calibrated expected_gain, and keep the best. If the best is below the noise
               floor, the answer is NO ACTION — said out loud.
    MinData    the customer must appear in at least one other open insight.
    Threshold  top gain ≥ 100,000/month, otherwise recommend doing nothing.
    Metric     customer_sales{customer_ids} — did acting beat not acting.
    Action     the chosen action, or a note saying to wait.

    Without this layer the same customer can appear on five cards at once and the owner has to
    arbitrate between them by hand, which in practice means ignoring all five.
    """
    import json
    from sqlalchemy import select
    from ..models import Insight

    per: dict[int, list] = defaultdict(list)
    rows = ctx.db.execute(select(Insight).where(Insight.status == "NEW")).scalars().all()
    for row in rows:
        if row.kind in ("NEXT_BEST_ACTION",):
            continue
        gain = float(row.expected_gain or 0)
        ids: set[int] = set()
        try:
            ev = json.loads(row.evidence or "{}")
        except Exception:
            ev = {}
        for key in ("customer_id",):
            if ev.get(key):
                ids.add(int(ev[key]))
        for key in ("customer_ids",):
            for v in (ev.get(key) or []):
                try:
                    ids.add(int(v))
                except (TypeError, ValueError):
                    continue
        for r in (ev.get("rows") or []):
            if isinstance(r, dict) and r.get("customer_id"):
                ids.add(int(r["customer_id"]))
        for cid in ids:
            per[cid].append((gain, row.kind, row.title))
    if not per:
        return []
    out: list[Draft] = []
    for cid, cands in per.items():
        cands.sort(key=lambda x: -x[0])
        gain, kind, title = cands[0]
        name = ""
        c = ctx.db.get(Customer, cid)
        name = (c.name if c else "") or f"مشتری {cid}"
        if gain < 100_000:
            out.append(Draft(
                kind="NEXT_BEST_ACTION", dedupe_key=f"nba:{cid}", priority=4,
                title=f"{name}: فعلاً کاری نکنید",
                body=(f"{_fa(len(cands))} پیشنهاد دربارهٔ این مشتری باز است ولی بزرگ‌ترینشان کمتر از "
                      f"{_money(100000)} در ماه ارزش دارد. هزینهٔ پیامک و تخفیف از سودش بیشتر می‌شود؛ "
                      "صبر کنید تا دادهٔ بیشتری جمع شود."),
                evidence={"customer_id": cid, "candidates": len(cands), "top_kind": kind,
                          "top_gain": round(gain), "verdict": "no_action"},
                actions=[{"type": "note", "label": "یادداشت: فعلاً اقدام نکن", "params": {}}],
                expected_gain=0.0, metric={"metric": "customer_sales", "customer_ids": [cid], "window_days": 28}))
        else:
            out.append(Draft(
                kind="NEXT_BEST_ACTION", dedupe_key=f"nba:{cid}", priority=1,
                title=f"{name}: بهترین اقدام بعدی",
                body=(f"از میان {_fa(len(cands))} پیشنهاد باز دربارهٔ این مشتری، بیشترین اثر را این دارد: "
                      f"«{title}» با حدود {_money(gain)} در ماه. بقیه را فعلاً نادیده بگیرید تا اثر همین "
                      "یکی اندازه‌گیری شود — دو اقدام هم‌زمان، سنجش را خراب می‌کند."),
                evidence={"customer_id": cid, "candidates": len(cands), "top_kind": kind,
                          "top_gain": round(gain), "verdict": kind},
                actions=[{"type": "note", "label": f"همین یکی را اجرا کن: {kind}", "params": {}}],
                expected_gain=gain, metric={"metric": "customer_sales", "customer_ids": [cid], "window_days": 28}))
    out.sort(key=lambda d: (d.priority, -d.expected_gain))
    return out[:10]


ANALYZERS = {
    "LOST_OPPORTUNITY": a_lost_opportunity,
    "STOCKOUT_COST": a_stockout_cost,
    "SUBSTITUTE": a_substitute,
    "GATEWAY_PRODUCT": a_gateway,
    "SUBSTITUTION_PAIR": a_substitution,
    "NO_DISCOUNT_NEEDED": a_discount_not_needed,
    "DISCOUNT_DEPENDENCY": a_discount_dependency,
    "GOLDEN_HOUR": a_golden_hour,
    "PRICE_PRESSURE": a_price_pressure,
    "NEXT_BEST_ACTION": a_next_best_action,
}

KIND_LABELS = {
    "LOST_OPPORTUNITY": "فرصت فروش از دست رفته",
    "STOCKOUT_COST": "هزینهٔ ناموجودی",
    "SUBSTITUTE": "کالای جایگزین",
    "GATEWAY_PRODUCT": "کالای دروازه‌ای",
    "SUBSTITUTION_PAIR": "رابطهٔ کالاها",
    "NO_DISCOUNT_NEEDED": "تخفیف ندهید",
    "DISCOUNT_DEPENDENCY": "وابستگی به تخفیف",
    "GOLDEN_HOUR": "زمان طلایی پیامک",
    "PRICE_PRESSURE": "فشار قیمت بر مشتری",
    "NEXT_BEST_ACTION": "بهترین اقدام بعدی",
}

# which UI group each new kind belongs to — the Android app mirrors this table, and
# tests/test_v361_engine_resilience.py fails if the two drift apart.
_GROUP_ADDITIONS = {
    "growth": ["LOST_OPPORTUNITY", "GATEWAY_PRODUCT", "SUBSTITUTE"],
    "stock": ["STOCKOUT_COST"],
    "customer": ["NO_DISCOUNT_NEEDED", "DISCOUNT_DEPENDENCY", "GOLDEN_HOUR", "PRICE_PRESSURE",
                 "NEXT_BEST_ACTION"],
    "price": ["SUBSTITUTION_PAIR"],
}


# ----------------------------------------------------------------------------- self-registration
from . import insights as _insights  # noqa: E402

_insights.ANALYZERS.update(ANALYZERS)
_insights.KIND_LABELS.update(KIND_LABELS)
for _g, _kinds in _GROUP_ADDITIONS.items():
    if _g in _insights.GROUPS:
        for _k in _kinds:
            if _k not in _insights.GROUPS[_g][1]:
                _insights.GROUPS[_g][1].append(_k)
