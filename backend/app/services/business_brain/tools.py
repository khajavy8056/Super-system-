"""v4.0 — Tool implementations (the brain's only way to touch the shop's data).

Every function here is deterministic: given the same database it returns the
same numbers. **No language model is involved in any of them**, which is what
makes the "LLM never invents cash / profit / margin" rule enforceable rather
than aspirational (``grounding.py`` checks the model's prose against exactly
these numbers).

Conventions
-----------
* Signature ``(ctx: ToolContext, params: dict) -> dict``.
* Return value always contains ``summary`` (one Persian sentence),
  ``numbers`` (the citable figures) and ``details`` (structured extras).
* A tool that cannot answer says so through ``flags`` — it never guesses. The
  registry turns an exception into a visible failure so the model can say
  «به این اطلاعات دسترسی پیدا نکردم» instead of fabricating a value.
* Read tools dominate. The few write tools (``create_task``, ``set_policy``,
  ``create_followup``) exist so the brain's *low-risk* actions can go through
  the same audited path as everything else; anything that moves money is
  executed by ``services/insight_actions.py``, not here.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select

from ...models import (BrainDecision, BrainFollowup, BrainMemoryFact, Campaign, Cheque, Customer,
                       CustomerLedgerEntry, Expense, Invoice, InvoiceItem, Product, ProductBatch,
                       StockMovement, Supplier, SystemSetting, User)
from .. import accounting as acct_svc
from .. import data_quality as dq_svc
from .. import forecast as forecast_svc
from .. import insights as ins_svc
from .. import inventory as inv_svc
from .. import expiry as expiry_svc
from .. import reports as report_svc
from ..timeservice import local_now, local_today
from .context import ToolContext
from . import persian as fa


# --------------------------------------------------------------------------- helpers
def _money(v) -> float:
    return float(v or 0)


def _since(days: int) -> datetime:
    return datetime.utcnow() - timedelta(days=days)


def _setting(ctx: ToolContext, key: str, default: str = "") -> str:
    row = ctx.db.execute(select(SystemSetting).where(SystemSetting.key == key)).scalar_one_or_none()
    return row.value if row else default


def _orders_of(a: str) -> list[int]:
    raw = _safe_json(a, []) if isinstance(a, str) else (a or [])
    return [int(x) for x in raw if isinstance(x, (int, float, str)) and str(x).isdigit()]


def _safe_json(raw, default):
    try:
        return json.loads(raw) if isinstance(raw, str) else (raw if raw is not None else default)
    except (TypeError, ValueError):
        return default


# --------------------------------------------------------------------------- store & policy
def get_store_profile(ctx: ToolContext, params: dict) -> dict:
    from .store_profile import load

    profile = load(ctx.db)
    return {"summary": "پروفایل فروشگاه: " + profile.digest(),
            "numbers": {"min_cash_reserve": _money(profile.declared.get("min_cash_reserve")),
                        "avg_basket": _money(profile.observed.get("avg_basket")),
                        "invoices_90d": profile.observed.get("invoices", 0)},
            "details": profile.to_dict()}


def get_business_policies(ctx: ToolContext, params: dict) -> dict:
    from .policies import all_policies

    policies = all_policies(ctx.db)
    key = params.get("key")
    if key:
        policies = {k: v for k, v in policies.items() if k == key or k.startswith(str(key))}
    return {"summary": f"{fa.fa_num(len(policies))} سیاست فروشگاه",
            "numbers": {k: float(v["value"]) for k, v in policies.items()
                        if isinstance(v.get("value"), (int, float)) and not isinstance(v.get("value"), bool)},
            "details": {"policies": policies}}


def set_policy(ctx: ToolContext, params: dict) -> dict:
    """WRITE (low risk): store the owner's rule. Never moves money."""
    from .policies import get_value, set_value

    key = params["key"]
    before = get_value(ctx.db, key)
    out = set_value(ctx.db, key, params.get("value"), user_id=getattr(ctx.user, "id", None),
                    source=params.get("source", "OWNER"), note=params.get("note"))
    return {"summary": f"سیاست «{key}» ثبت شد", "numbers": {},
            "details": {"policy": out, "before": before}}


#: v4.4.0 — the keys the brain may READ and (with the manager's approval in
#: the chat) WRITE. Deliberately a whitelist: the brain manages the shop's
#: communication settings and its own manager-phone, never arbitrary keys.
SETTING_WHITELIST = (
    "sms.reminder_template",          # متن پیامک یادآوری به مشتری
    "sms.debt_template",
    "sms.winback_template",
    "sms.visit_template",
    "brain.manager_phone",            # شماره مدیر برای پیامک‌های یادآوری
    "brain.reminder_escalate_hours",  # هر چند ساعت دوباره پیامک برود
    "store.name",
)


def get_setting_tool(ctx: ToolContext, params: dict) -> dict:
    """v4.4.0 — read a whitelisted setting (for consulting on e.g. the SMS text)."""
    key = str(params.get("key", ""))
    if key not in SETTING_WHITELIST:
        return {"summary": f"کلید «{key}» در فهرست مجاز نیست", "numbers": {},
                "details": {"allowed_keys": list(SETTING_WHITELIST)}, "flags": ["DENIED_KEY"]}
    return {"summary": f"«{key}» = {_setting(ctx, key) or '(خالی)'}", "numbers": {},
            "details": {"key": key, "value": _setting(ctx, key)}}


def set_setting_tool(ctx: ToolContext, params: dict) -> dict:
    """v4.4.0 — WRITE (manager-approved via the chat's تأیید button): set a
    whitelisted setting, e.g. the SMS reminder text the manager agreed to."""
    key = str(params.get("key", ""))
    value = str(params.get("value", ""))
    if key not in SETTING_WHITELIST:
        return {"summary": f"کلید «{key}» در فهرست مجاز نیست", "numbers": {},
                "details": {"allowed_keys": list(SETTING_WHITELIST)}, "flags": ["DENIED_KEY"]}
    before = _setting(ctx, key)
    row = ctx.db.execute(select(SystemSetting).where(SystemSetting.key == key)).scalar_one_or_none()
    if row is None:
        ctx.db.add(SystemSetting(key=key, value=value))
    else:
        row.value = value
    ctx.db.flush()
    return {"summary": f"تنظیم «{key}» ذخیره شد", "numbers": {},
            "details": {"key": key, "before": before, "after": value}}


def sms_draft(ctx: ToolContext, params: dict) -> dict:
    """v4.4.0 — draft an SMS to ONE customer for the manager to approve.

    Creates a WAITING_APPROVAL decision whose approval executes the REAL send
    through the audited Action Engine (personal_sms). The text is never sent
    without the manager pressing تأیید.
    """
    text = str(params.get("text", "")).strip()
    customer_id = params.get("customer_id")
    cust = None
    if customer_id is not None:
        cust = ctx.db.get(Customer, int(customer_id))
    if cust is None:
        name = str(params.get("customer", "")).strip()
        if name:
            cust = ctx.db.execute(
                select(Customer).where(Customer.full_name.ilike(f"%{name}%")).limit(1)
            ).scalar_one_or_none()
    if cust is None:
        return {"summary": "مشتری پیدا نشد", "numbers": {},
                "details": {}, "flags": ["CUSTOMER_NOT_FOUND"]}
    if not text:
        return {"summary": "متن پیامک خالی است", "numbers": {}, "details": {}, "flags": ["EMPTY_TEXT"]}
    row = BrainDecision(
        type="sms_draft", title=f"ارسال پیامک به {cust.name}",
        problem="پیش‌نویس پیامک از طرف مغز فروشگاه",
        options=json.dumps([{
            "id": "send", "label": "ارسال پیامک", "description": text[:200],
            "actions": [{"type": "personal_sms",
                         "params": {"customers": [{"customer_id": cust.id, "text": text}]}}],
            "risk": "low", "reversible": False}], ensure_ascii=False),
        reason="متن با مدیر مشورت شد؛ با تأیید شما ارسال می‌شود.",
        recommended_option="send", status="WAITING_APPROVAL", confidence="high",
        created_by=getattr(ctx.user, "id", None))
    ctx.db.add(row)
    ctx.db.flush()
    return {"summary": f"پیش‌نویس پیامک به {cust.name} آماده شد — با تأیید شما ارسال می‌شود",
            "numbers": {},
            "details": {"decision_id": row.id, "customer": cust.name, "text": text}}


def get_data_quality(ctx: ToolContext, params: dict) -> dict:
    report = ctx.cached("dq", lambda: dq_svc.run_all(ctx.db))
    critical = [c for c in report["checks"] if c["severity"] == "CRITICAL"]
    high = [c for c in report["checks"] if c["severity"] == "HIGH"]
    return {"summary": f"کیفیت داده: {report['verdict']} — {fa.fa_num(len(critical))} مورد بحرانی، "
                       f"{fa.fa_num(len(high))} مورد مهم",
            "numbers": {"critical": len(critical), "high": len(high), "total": len(report["checks"])},
            "details": report,
            "flags": (["DATA_QUALITY_BLOCKED"] if dq_svc.blocks_intelligence(report) else [])}


# --------------------------------------------------------------------------- cash & obligations
def get_cash_position(ctx: ToolContext, params: dict) -> dict:
    ov = ctx.cached("acct_overview", lambda: acct_svc.overview(ctx.db))
    from .store_profile import reserve_floor
    reserve = _money(ctx.cached("reserve", lambda: reserve_floor(ctx.db)))
    cash, bank, card = _money(ov.get("cash")), _money(ov.get("bank")), _money(ov.get("card"))
    available = cash + bank + card
    return {"summary": f"نقد {fa.toman_short(cash)} + بانک {fa.toman_short(bank)} + کارتخوان "
                       f"{fa.toman_short(card)} = {fa.toman_short(available)} تومان",
            "numbers": {"cash_available": available, "cash_cash": cash, "bank": bank, "card": card,
                        "reserve_floor": reserve, "net_of_reserve": available - reserve},
            "details": ov,
            "flags": ["CASH_BELOW_RESERVE"] if reserve and available < reserve else []}


def get_upcoming_cheques(ctx: ToolContext, params: dict) -> dict:
    horizon = int(params.get("days", 30) or 30)
    today: date = local_today()
    end = today + timedelta(days=horizon)
    rows = list(ctx.db.execute(select(Cheque).where(Cheque.status == "PENDING", Cheque.due_date <= end)
                               .order_by(Cheque.due_date)).scalars())
    issued = [c for c in rows if c.direction == "ISSUED"]
    received = [c for c in rows if c.direction == "RECEIVED"]
    overdue = [c for c in rows if c.due_date < today]
    out = [{"id": c.id, "direction": c.direction, "number": c.number, "amount": _money(c.amount),
            "due_date": c.due_date.isoformat(), "days_left": (c.due_date - today).days,
            "party_name": c.party_name, "party_id": c.party_id, "bank": c.bank_name} for c in rows]
    next7 = sum(_money(c.amount) for c in issued if (c.due_date - today).days <= 7)
    return {"summary": f"{fa.fa_num(len(issued))} چک پرداختی تا {fa.fa_num(horizon)} روز آینده "
                       f"({fa.toman_short(next7)} تومان در ۷ روز) و {fa.fa_num(len(received))} چک دریافتی",
            "numbers": {"issued_total": sum(_money(c.amount) for c in issued),
                        "issued_next_7d": next7,
                        "received_total": sum(_money(c.amount) for c in received),
                        "overdue_count": len(overdue), "count": len(rows)},
            "details": {"cheques": out, "horizon_days": horizon, "today": today.isoformat()},
            "flags": (["CHEQUE_OVERDUE"] if overdue else [])}


def get_payables(ctx: ToolContext, params: dict) -> dict:
    ov = ctx.cached("acct_overview", lambda: acct_svc.overview(ctx.db))
    # supplier debts recorded as expenses/cheques plus the payable account balance
    issued_pending = db_sum = ctx.db.execute(
        select(func.coalesce(func.sum(Cheque.amount), 0)).where(Cheque.direction == "ISSUED",
                                                                Cheque.status == "PENDING")).scalar_one()
    today = local_today()
    by_supplier: dict[str, float] = {}
    for c in ctx.db.execute(select(Cheque).where(Cheque.direction == "ISSUED", Cheque.status == "PENDING",
                                                 Cheque.due_date <= today + timedelta(days=30))).scalars():
        key = c.party_name or (f"تأمین‌کننده #{c.party_id}" if c.party_id else "نامشخص")
        by_supplier[key] = by_supplier.get(key, 0.0) + _money(c.amount)
    net = _money(ov.get("payables"))
    lead = (f"بدهی ثبت‌شده به تأمین‌کنندگان {fa.toman_short(net)} تومان"
            if net >= 0 else
            f"ماندهٔ حساب تأمین‌کنندگان {fa.toman_short(abs(net))} تومان بدهکار است "
            "(پیش‌پرداخت یا چک بدون ثبت خرید)")
    return {"summary": f"{lead}؛ {fa.toman_short(issued_pending)} تومان چک پرداختی در جریان",
            "numbers": {"payables": _money(ov.get("payables")), "cheques_pending": _money(issued_pending),
                        "by_supplier_total": sum(by_supplier.values())},
            "details": {"by_supplier": by_supplier, "issued_count": int(ov.get("cheques", {}).get("issued_count", 0))}}


def get_receivables(ctx: ToolContext, params: dict) -> dict:
    """What customers owe — from the append-only customer ledger (never estimated)."""
    from .. import ledger as ledger_svc

    debtors = ctx.cached("debtors", lambda: ledger_svc.debtors(ctx.db, 0))
    today = local_today()
    rows = []
    for d in debtors[:40]:
        cid = d["customer_id"]
        last_pay = ctx.db.execute(
            select(func.max(CustomerLedgerEntry.created_at)).where(CustomerLedgerEntry.customer_id == cid,
                                                                  CustomerLedgerEntry.entry_type == "PAYMENT")).scalar_one()
        pays = ctx.db.execute(select(func.count(CustomerLedgerEntry.id))
                              .where(CustomerLedgerEntry.customer_id == cid,
                                     CustomerLedgerEntry.entry_type == "PAYMENT")).scalar_one()
        days_since = (datetime.utcnow() - last_pay).days if last_pay else None
        balance = _money(d["balance"])
        # deterministic collection confidence: history of paying + recency + size
        if pays >= 3 and (days_since is not None and days_since <= 45):
            conf = "high"
        elif pays >= 1:
            conf = "medium"
        else:
            conf = "low"
        rows.append({"customer_id": cid, "name": d.get("name"), "phone": d.get("phone"),
                     "balance": balance, "payments": int(pays),
                     "last_payment_days_ago": days_since, "collection_confidence": conf})
    total = sum(r["balance"] for r in rows)
    high = sum(r["balance"] for r in rows if r["collection_confidence"] == "high")
    return {"summary": f"مطالبات از مشتریان {fa.toman_short(total)} تومان "
                       f"({fa.toman_short(high)} تومان با احتمال وصول بالا)",
            "numbers": {"total": total, "high_confidence": high, "debtor_count": len(rows)},
            "details": {"debtors": rows}}


#: How long a debtor of each confidence band is assumed to take. These are
#: *bands*, not predictions — the tool says "within 3 days" and the plan is told
#: that collections are estimates (``COLLECTION_IS_ESTIMATE``).
COLLECTION_DAYS = {"high": 3, "medium": 8, "low": 14}
COLLECTION_SHARE = {"high": 0.55, "medium": 0.25, "low": 0.05}


def expected_collection_lines(ctx: ToolContext, horizon: int | None = None) -> list[dict]:
    """Per-debtor collection expectation, shared by the schedule and the forecast."""
    horizon = horizon or 14
    ctx.cache.pop("debtors", None)
    recv = get_receivables(ctx, {"days": horizon})
    lines = []
    for r in recv["details"]["debtors"]:
        conf = r["collection_confidence"]
        amount = round(r["balance"] * COLLECTION_SHARE[conf])
        if amount <= 0:
            continue
        lines.append({"customer_id": r["customer_id"], "name": r["name"], "phone": r.get("phone"),
                      "balance": r["balance"], "confidence": conf,
                      "expected_days": COLLECTION_DAYS[conf], "expected_amount": amount,
                      "basis": f"{int(r['payments'])} پرداخت ثبت‌شده، آخرین پرداخت "
                               f"{r['last_payment_days_ago'] if r['last_payment_days_ago'] is not None else '—'} روز پیش"})
    return lines


def get_expected_collections(ctx: ToolContext, params: dict) -> dict:
    """Deterministic collection projection for the next N days.

    Uses the customer's OWN payment history (how many settlements they have, how
    recently) to place them in a confidence band, then schedules the expected
    amount at that band's *day* — so a cheque due in three days is compared with
    the money that can actually arrive in three days, not with a two-week average.
    """
    horizon = int(params.get("days", 14) or 14)
    lines = expected_collection_lines(ctx, horizon)
    total = sum(l["expected_amount"] for l in lines)
    next3 = sum(l["expected_amount"] for l in lines if l["expected_days"] <= 3)
    next7 = sum(l["expected_amount"] for l in lines if l["expected_days"] <= 7)
    recv = get_receivables(ctx, {"days": horizon})
    return {"summary": f"انتظار وصول حدود {fa.toman_short(total)} تومان از مطالبات در "
                       f"{fa.fa_num(horizon)} روز آینده؛ تا ۳ روز آینده {fa.toman_short(next3)} تومان "
                       f"(بر پایهٔ رفتار پرداخت خود مشتریان)",
            "numbers": {"expected_total": total, "expected_next_3d": next3, "expected_next_7d": next7,
                        "high_confidence_total": recv["numbers"].get("high_confidence", 0),
                        "receivables_total": recv["numbers"]["total"], "horizon_days": horizon,
                        "debtors_with_expectation": len(lines)},
            "details": {"lines": lines, "method": "confidence band from the customer's own payment history",
                        "bands": {"high": COLLECTION_DAYS["high"], "medium": COLLECTION_DAYS["medium"],
                                  "low": COLLECTION_DAYS["low"]}},
            "flags": ["COLLECTION_IS_ESTIMATE"]}


def get_cash_forecast(ctx: ToolContext, params: dict) -> dict:
    """Deterministic cash projection: opening cash + collections − obligations − run-rate.

    Two scenarios are always computed, because the honest answer to "will the
    cheque clear?" depends on whether the collections arrive:

    * **expected** — collections scheduled by the debtors' own confidence bands;
    * **no collections** — only money already in hand against the same cheques.

    The floor used for "is this a problem" is the owner's ``minimum_cash_reserve``
    when it is set, and **zero** when it is not; the *safety target* is
    ``20% of the cheques falling due inside the horizon``, which is the buffer a
    shop needs when a debtor is a few days late.
    """
    horizon = int(params.get("days", 14) or 14)
    cash = get_cash_position(ctx, {})
    cheques = get_upcoming_cheques(ctx, {"days": horizon})
    collections = get_expected_collections(ctx, {"days": horizon})
    expenses = ctx.db.execute(select(func.coalesce(func.avg(Expense.amount), 0)).where(
        Expense.expense_date >= (local_today() - timedelta(days=30)))).scalar_one()
    daily_expense = _money(expenses)
    today = local_today()
    res = _money(cash["numbers"].get("reserve_floor"))
    floor = max(res, 0.0)
    cheques_in = [c for c in cheques["details"]["cheques"] if c["direction"] == "RECEIVED"]
    cheques_out = [c for c in cheques["details"]["cheques"] if c["direction"] == "ISSUED"]
    issued_total = sum(c["amount"] for c in cheques_out)
    safety_target = max(floor, round(issued_total * 0.2))

    # collections arrive on the day their band says, not spread evenly
    inflow_by_day: dict[date, float] = {}
    for line in collections["details"]["lines"]:
        day = today + timedelta(days=int(line["expected_days"]))
        if day <= today + timedelta(days=horizon):
            inflow_by_day[day] = inflow_by_day.get(day, 0.0) + float(line["expected_amount"])

    running = cash["numbers"]["cash_available"]
    stress = running                      # same walk, without a single collection
    days, breaches, strains = [], [], []
    for i in range(horizon + 1):
        d = today + timedelta(days=i)
        drawn = sum(c["amount"] for c in cheques_out if c["due_date"] == d.isoformat())
        received = sum(c["amount"] for c in cheques_in if c["due_date"] == d.isoformat())
        collected = inflow_by_day.get(d, 0.0)
        outflow = drawn + daily_expense
        running = running + received + collected - outflow
        stress = stress + received - outflow
        days.append({"date": d.isoformat(), "in": round(received + collected), "out": round(outflow),
                     "projected_cash": round(running), "no_collections": round(stress)})
        if running < floor:
            breaches.append({"date": d.isoformat(), "projected_cash": round(running),
                             "shortfall": round(max(floor - running, -running))})
        if i > 0 and running < safety_target:
            strains.append({"date": d.isoformat(), "projected_cash": round(running),
                            "below": round(safety_target - running)})

    lowest = min(days, key=lambda d: d["projected_cash"])
    stress_lowest = min(days[1:], key=lambda d: d["no_collections"]) if len(days) > 1 else days[0]
    first_breach = breaches[0] if breaches else None
    numbers = {"min_projected_cash": lowest["projected_cash"],
               "min_projected_day": lowest["date"],
               "final_projected_cash": days[-1]["projected_cash"],
               "min_without_collections": stress_lowest["no_collections"],
               "min_without_collections_day": stress_lowest["date"],
               "breach_days": len(breaches),
               "days_below_safety": len(strains),
               "first_strain_date": strains[0]["date"] if strains else None,
               "first_breach_date": first_breach["date"] if first_breach else None,
               "shortfall": first_breach["shortfall"] if first_breach else 0,
               "lowest_day": lowest["date"],
               "expected_collections": collections["numbers"]["expected_total"],
               "expected_next_3d": collections["numbers"]["expected_next_3d"],
               "expected_next_7d": collections["numbers"]["expected_next_7d"],
               "issued_in_horizon": issued_total,
               "safety_target": safety_target, "reserve_floor": res,
               "daily_operating_expense": daily_expense}
    flags = []
    if len(breaches) or numbers["min_projected_cash"] < 0:
        flags.append("CASH_GAP_AHEAD")
    if numbers["min_projected_cash"] < 0:
        flags.append("CASH_NEGATIVE_AHEAD")
    if strains and not flags:
        flags.append("CASH_GAP_AHEAD")
    if numbers["min_without_collections"] < 0 and numbers["min_projected_cash"] >= 0:
        flags.append("CASH_FRAGILE")
    summary = (f"پیش‌بینی {fa.fa_num(horizon)} روز آینده: کمترین موجودی "
               f"{fa.toman_short(numbers['min_projected_cash'])} تومان در "
               f"{fa.fa_date(_parse_date(numbers['min_projected_day']))}"
               + (f"؛ {fa.fa_num(len(breaches))} روز زیر کف نقدینگی" if breaches and res else "")
               + (f"؛ کف امن پیشنهادی {fa.toman_short(safety_target)} تومان و "
                  f"{fa.fa_num(len(strains))} روز زیر آن" if strains and not breaches else "")
               + (f"؛ اگر وصول مطالبات عقب بیفتد تا {fa.toman_short(abs(numbers['min_without_collections']))} "
                  f"تومان منفی می‌شود" if numbers["min_without_collections"] < 0 else ""))
    return {"summary": summary, "numbers": numbers,
            "details": {"days": days, "breaches": breaches, "strains": strains, "reserve_floor": res,
                        "safety_target": safety_target,
                        "collections_scheduled": [
                            {"date": d.isoformat(), "amount": round(a)} for d, a in sorted(inflow_by_day.items())],
                        "assumption": "کف نقدینگی صفر فرض شده چون مدیر مقداری تعیین نکرده است"
                        if not res else None},
            "flags": sorted(set(flags))}


def _parse_date(value: str):
    from datetime import date as _date

    try:
        return _date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return local_today()


# --------------------------------------------------------------------------- inventory
def get_inventory_summary(ctx: ToolContext, params: dict) -> dict:
    rows = ctx.db.execute(
        select(func.count(ProductBatch.id),
               func.coalesce(func.sum(ProductBatch.current_qty * ProductBatch.buy_price), 0),
               func.coalesce(func.sum(ProductBatch.current_qty * ProductBatch.sell_price), 0))
        .where(ProductBatch.status == "ACTIVE", ProductBatch.current_qty > 0)).one()
    count, cost_value, retail_value = int(rows[0] or 0), _money(rows[1]), _money(rows[2])
    by_cat = ctx.db.execute(
        select(Product.category_id, func.coalesce(func.sum(ProductBatch.current_qty * ProductBatch.buy_price), 0))
        .join(Product, Product.id == ProductBatch.product_id)
        .where(ProductBatch.status == "ACTIVE", ProductBatch.current_qty > 0)
        .group_by(Product.category_id)).all()
    return {"summary": f"{fa.fa_num(count)} بچ فعال؛ ارزش خرید موجودی {fa.toman_short(cost_value)} تومان",
            "numbers": {"batch_count": count, "stock_value": cost_value, "retail_value": retail_value,
                        "potential_margin": retail_value - cost_value},
            "details": {"by_category": [{"category_id": c, "value": _money(v)} for c, v in by_cat]}}


def get_expiry_risk(ctx: ToolContext, params: dict) -> dict:
    """§27 — expiring stock is a *situation*, not automatically a discount."""
    horizon = int(params.get("days", 30) or 30)
    today = local_today()
    limit = today + timedelta(days=horizon)
    rows = ctx.db.execute(
        select(ProductBatch).where(ProductBatch.status == "ACTIVE", ProductBatch.current_qty > 0,
                                   ProductBatch.expiry_date.isnot(None),
                                   ProductBatch.expiry_date <= limit)
        .order_by(ProductBatch.expiry_date)).scalars().all()
    items = []
    for b in rows:
        days_left = (b.expiry_date - today).days
        velocity = _velocity(ctx, b.product_id)
        qty = _money(b.current_qty)
        sellable = min(qty, velocity * max(0, days_left))
        at_risk_qty = max(0.0, qty - sellable)
        items.append({"batch_id": b.id, "product_id": b.product_id, "product": b.product.name if b.product else "",
                      "qty": qty, "days_left": days_left,
                      "value": round(at_risk_qty * _money(b.buy_price)),
                      "at_risk_qty": round(at_risk_qty, 2), "velocity_per_day": round(velocity, 3),
                      "buy_price": _money(b.buy_price), "sell_price": _money(b.sell_price),
                      "margin_per_unit": _money(b.sell_price) - _money(b.buy_price),
                      "supplier_id": b.supplier_id})
    items.sort(key=lambda x: -x["value"])
    total = sum(i["value"] for i in items)
    return {"summary": f"{fa.fa_num(len(items))} بچ نزدیک انقضا؛ حدود {fa.toman_short(total)} تومان "
                       f"با سرعت فروش فعلی در معرض خطر",
            "numbers": {"batches": len(items), "at_risk_value": total,
                        "at_risk_units": round(sum(i["at_risk_qty"] for i in items), 2)},
            "details": {"items": items[:25], "horizon_days": horizon},
            "flags": (["EXPIRY_RISK"] if total > 0 else [])}


def get_overstock(ctx: ToolContext, params: dict) -> dict:
    """Slow movers holding capital: days-of-cover above a deterministic threshold."""
    days_cover = int(params.get("days_cover", 90) or 90)
    rows = ctx.db.execute(
        select(ProductBatch).where(ProductBatch.status == "ACTIVE", ProductBatch.current_qty > 0)
        .order_by((ProductBatch.current_qty * ProductBatch.buy_price).desc()).limit(400)).scalars().all()
    items = []
    for b in rows:
        velocity = _velocity(ctx, b.product_id)
        qty = _money(b.current_qty)
        cover = (qty / velocity) if velocity > 0.01 else None
        if cover is not None and cover < days_cover:
            continue
        items.append({"batch_id": b.id, "product_id": b.product_id,
                      "product": b.product.name if b.product else "", "qty": qty,
                      "days_of_cover": round(cover) if cover is not None else None,
                      "capital": round(qty * _money(b.buy_price)),
                      "velocity_per_day": round(velocity, 3)})
    items.sort(key=lambda x: -x["capital"])
    total = sum(i["capital"] for i in items)
    return {"summary": f"{fa.fa_num(len(items))} قلم راکد/کند-فروش با {fa.toman_short(total)} تومان سرمایهٔ راکد",
            "numbers": {"count": len(items), "capital": total, "threshold_days_cover": days_cover},
            "details": {"items": items[:25]},
            "flags": (["OVERSTOCK"] if total > 0 else [])}


def get_stockout_risk(ctx: ToolContext, params: dict) -> dict:
    horizon = int(params.get("days", 14) or 14)
    products = ctx.db.execute(select(Product.id, Product.name, Product.min_stock_alert)
                              .where(Product.is_active == True, Product.deleted_at.is_(None))).all()  # noqa: E712
    items = []
    for pid, name, min_alert in products:
        stock = _stock(ctx, pid)
        velocity = _velocity(ctx, pid)
        if velocity <= 0.01:
            continue
        days_left = stock / velocity
        if days_left > horizon and not (min_alert and stock <= min_alert):
            continue
        items.append({"product_id": pid, "product": name, "stock": round(stock, 2),
                      "velocity_per_day": round(velocity, 3), "days_left": round(days_left, 1),
                      "min_stock_alert": int(min_alert or 0)})
    items.sort(key=lambda x: x["days_left"])
    return {"summary": f"{fa.fa_num(len(items))} قلم تا {fa.fa_num(horizon)} روز آینده ممکن است تمام شود",
            "numbers": {"count": len(items), "horizon_days": horizon},
            "details": {"items": items[:25]},
            "flags": (["STOCKOUT_RISK"] if items else [])}


def get_product_snapshot(ctx: ToolContext, params: dict) -> dict:
    """Everything a decision about ONE product needs: stock, velocity, margin, batches."""
    pid = int(params["product_id"])
    product = ctx.db.get(Product, pid)
    if product is None:
        return {"summary": "کالا پیدا نشد", "numbers": {}, "details": {}, "flags": ["PRODUCT_NOT_FOUND"]}
    batches = ctx.db.execute(select(ProductBatch).where(ProductBatch.product_id == pid,
                                                        ProductBatch.status == "ACTIVE",
                                                        ProductBatch.current_qty > 0)
                             .order_by(ProductBatch.expiry_date)).scalars().all()
    velocity = _velocity(ctx, pid, days=int(params.get("velocity_days", 28) or 28))
    stock = sum(_money(b.current_qty) for b in batches)
    cost = _weighted(batches, "buy_price")
    sell = _weighted(batches, "sell_price")
    margin = (sell - cost) if sell else 0.0
    margin_pct = (margin / sell * 100) if sell else 0.0
    last30 = _sold_qty(ctx, pid, 30)
    prev30 = _sold_qty(ctx, pid, 60) - last30
    return {"summary": f"{product.name}: موجودی {fa.fa_num(stock, 1)}، فروش "
                       f"{fa.fa_num(velocity, 2)} در روز، حاشیه {fa.fa_num(margin_pct, 1)}٪",
            "numbers": {"product_id": pid, "stock": stock, "velocity_per_day": velocity,
                        "avg_cost": cost, "avg_sell": sell, "margin_per_unit": margin,
                        "margin_pct": margin_pct, "sold_30d": last30, "sold_prev_30d": prev30,
                        "stock_value": stock * cost, "days_of_cover": round(stock / velocity, 1) if velocity > 0 else None},
            "details": {"product": {"id": pid, "name": product.name, "barcode": product.barcode,
                                    "min_stock_alert": product.min_stock_alert},
                        "batches": [{"id": b.id, "qty": _money(b.current_qty), "buy_price": _money(b.buy_price),
                                     "sell_price": _money(b.sell_price),
                                     "expiry_date": b.expiry_date.isoformat() if b.expiry_date else None,
                                     "days_left": (b.expiry_date - local_today()).days if b.expiry_date else None,
                                     "supplier_id": b.supplier_id} for b in batches]}}


def get_price_history(ctx: ToolContext, params: dict) -> dict:
    pid = int(params["product_id"])
    history = report_svc.price_history(ctx.db, pid)
    return {"summary": f"{fa.fa_num(len(history))} تغییر قیمت ثبت‌شده برای این کالا",
            "numbers": {"changes": len(history)},
            "details": {"history": history[-20:]}}


def get_expenses(ctx: ToolContext, params: dict) -> dict:
    days = int(params.get("days", 30) or 30)
    rows = ctx.db.execute(select(Expense.category_id, func.coalesce(func.sum(Expense.amount), 0), func.count(Expense.id))
                          .where(Expense.expense_date >= (local_today() - timedelta(days=days)))
                          .group_by(Expense.category_id)).all()
    total = sum(_money(r[1]) for r in rows)
    return {"summary": f"هزینه‌های {fa.fa_num(days)} روز گذشته {fa.toman_short(total)} تومان",
            "numbers": {"total": total, "daily_average": total / max(1, days)},
            "details": {"by_category": [{"category_id": c, "total": _money(v), "count": int(n)} for c, v, n in rows]}}


# --------------------------------------------------------------------------- sales
def get_sales_trend(ctx: ToolContext, params: dict) -> dict:
    days = int(params.get("days", 7) or 7)
    now = datetime.utcnow()
    cur = _sales_between(ctx, now - timedelta(days=days), now)
    prev = _sales_between(ctx, now - timedelta(days=2 * days), now - timedelta(days=days))
    change = ((cur["revenue"] - prev["revenue"]) / prev["revenue"] * 100) if prev["revenue"] else 0.0
    profit_cur, profit_prev = cur["profit"], prev["profit"]
    return {"summary": f"فروش {fa.fa_num(days)} روز: {fa.toman_short(cur['revenue'])} تومان "
                       f"({fa.fa_num(change, 1)}٪ نسبت به دورهٔ قبل)، سود {fa.toman_short(profit_cur)}",
            "numbers": {"sales_7d": cur["revenue"] if days == 7 else cur["revenue"],
                        "window_days": days, "revenue": cur["revenue"], "profit": profit_cur,
                        "revenue_prev": prev["revenue"], "profit_prev": profit_prev,
                        "change_pct": round(change, 1), "invoices": cur["invoices"],
                        "avg_basket": cur["avg_basket"]},
            "details": cur,
            "flags": (["SALES_DROP"] if change <= -20 and prev["revenue"] > 0 else [])}


def get_product_sales(ctx: ToolContext, params: dict) -> dict:
    days = int(params.get("days", 28) or 28)
    limit = int(params.get("limit", 10) or 10)
    rows = ctx.db.execute(
        select(InvoiceItem.product_id, func.sum(InvoiceItem.qty), func.sum(InvoiceItem.profit),
               func.sum(InvoiceItem.subtotal))
        .join(Invoice, Invoice.id == InvoiceItem.invoice_id)
        .where(Invoice.status == "PAID", Invoice.created_at >= _since(days))
        .group_by(InvoiceItem.product_id)
        .order_by(func.sum(InvoiceItem.qty).desc()).limit(limit)).all()
    names = {p.id: p.name for p in ctx.db.execute(select(Product)).scalars()}
    items = [{"product_id": pid, "product": names.get(pid, f"#{pid}"), "qty": _money(q),
              "profit": _money(pr), "revenue": _money(sub)} for pid, q, pr, sub in rows]
    return {"summary": f"{fa.fa_num(len(items))} کالای پرفروش {fa.fa_num(days)} روز گذشته",
            "numbers": {f"qty_{i['product_id']}": i["qty"] for i in items},
            "details": {"items": items, "window_days": days}}


# --------------------------------------------------------------------------- customers & suppliers
def get_customer_behavior(ctx: ToolContext, params: dict) -> dict:
    cid = int(params["customer_id"])
    customer = ctx.db.get(Customer, cid)
    if customer is None:
        return {"summary": "مشتری پیدا نشد", "numbers": {}, "details": {}, "flags": ["CUSTOMER_NOT_FOUND"]}
    since = _since(int(params.get("days", 180) or 180))
    row = ctx.db.execute(select(func.count(Invoice.id), func.coalesce(func.sum(Invoice.total_amount), 0),
                                func.coalesce(func.avg(Invoice.total_amount), 0), func.max(Invoice.created_at))
                         .where(Invoice.customer_id == cid, Invoice.status == "PAID",
                                Invoice.created_at >= since)).one()
    balance = ctx.db.execute(select(func.coalesce(func.sum(CustomerLedgerEntry.amount), 0))
                             .where(CustomerLedgerEntry.customer_id == cid)).scalar_one()
    fav = ctx.db.execute(
        select(InvoiceItem.product_id, func.sum(InvoiceItem.qty).label("q"))
        .join(Invoice, Invoice.id == InvoiceItem.invoice_id)
        .where(Invoice.customer_id == cid, Invoice.status == "PAID")
        .group_by(InvoiceItem.product_id).order_by(func.sum(InvoiceItem.qty).desc()).limit(5)).all()
    names = {p.id: p.name for p in ctx.db.execute(select(Product)).scalars()}
    last = row[3]
    days_since = (datetime.utcnow() - last).days if last else None
    return {"summary": f"{customer.name}: {fa.fa_num(int(row[0] or 0))} خرید، مانده حساب "
                       f"{fa.toman_short(balance)} تومان"
                       + (f"؛ آخرین خرید {fa.fa_num(days_since)} روز پیش" if days_since is not None else ""),
            "numbers": {"customer_id": cid, "invoices": int(row[0] or 0), "revenue": _money(row[1]),
                        "avg_basket": _money(row[2]), "balance": _money(balance),
                        "days_since_last_purchase": days_since},
            "details": {"favorites": [{"product_id": p, "product": names.get(p, f"#{p}"), "qty": _money(q)}
                                      for p, q in fav],
                        "credit_limit": _money(customer.credit_limit),
                        "credit_enabled": bool(customer.credit_enabled)},
            "flags": (["CUSTOMER_CHURNED"] if days_since is not None and days_since > 45 else [])}


def get_customer_segment(ctx: ToolContext, params: dict) -> dict:
    """Deterministic segments computed from invoices — no clustering model needed."""
    since = _since(int(params.get("days", 90) or 90))
    rows = ctx.db.execute(
        select(Invoice.customer_id, func.count(Invoice.id), func.sum(Invoice.total_amount), func.max(Invoice.created_at))
        .where(Invoice.status == "PAID", Invoice.created_at >= since, Invoice.customer_id.isnot(None))
        .group_by(Invoice.customer_id)).all()
    names = {c.id: c.name for c in ctx.db.execute(select(Customer)).scalars()}
    vip, regular, new, churned = [], [], [], []
    for cid, count, total, last in rows:
        days = (datetime.utcnow() - last).days if last else 999
        entry = {"customer_id": cid, "name": names.get(cid, f"#{cid}"), "invoices": int(count),
                 "revenue": _money(total), "last_purchase_days_ago": days}
        if days > 45:
            churned.append(entry)
        elif count >= 8 and _money(total) >= 5_000_000:
            vip.append(entry)
        elif count <= 2:
            new.append(entry)
        else:
            regular.append(entry)
    return {"summary": f"{fa.fa_num(len(vip))} مشتری VIP، {fa.fa_num(len(new))} مشتری تازه، "
                       f"{fa.fa_num(len(churned))} مشتری غایب",
            "numbers": {"vip": len(vip), "new": len(new), "churned": len(churned), "regular": len(regular)},
            "details": {"vip": vip[:15], "new": new[:15], "churned": churned[:15]}}


def get_supplier_profile(ctx: ToolContext, params: dict) -> dict:
    sid = int(params["supplier_id"])
    supplier = ctx.db.get(Supplier, sid)
    if supplier is None:
        return {"summary": "تأمین‌کننده پیدا نشد", "numbers": {}, "details": {}, "flags": ["SUPPLIER_NOT_FOUND"]}
    batches = ctx.db.execute(select(ProductBatch).where(ProductBatch.supplier_id == sid)
                             .order_by(ProductBatch.received_at.desc()).limit(200)).scalars().all()
    from .policies import supplier_rank
    purchases = sum(_money(b.quantity_received) * _money(b.buy_price) for b in batches)
    returns = ctx.db.execute(select(func.count(StockMovement.id)).join(ProductBatch, ProductBatch.id == StockMovement.batch_id)
                             .where(ProductBatch.supplier_id == sid, StockMovement.movement_type == "RETURN_OUT")).scalar_one()
    short_expiry = sum(1 for b in batches if b.production_date and b.expiry_date
                       and (b.expiry_date - b.production_date).days < 60)
    lead_times = [_lead_time(ctx, b) for b in batches[:40]]
    lead_times = [x for x in lead_times if x is not None]
    lead_avg = sum(lead_times) / len(lead_times) if lead_times else None
    return {"summary": f"{supplier.name}: {fa.fa_num(len(batches))} محموله، خرید کل "
                       f"{fa.toman_short(purchases)} تومان، اولویت {supplier_rank(ctx.db, sid)}",
            "numbers": {"supplier_id": sid, "purchases": purchases, "batches": len(batches),
                        "returns": int(returns), "short_shelf_life_batches": short_expiry,
                        "lead_time_days": round(lead_avg, 1) if lead_avg else None},
            "details": {"supplier": {"id": sid, "name": supplier.name, "phone": supplier.phone},
                        "priority": supplier_rank(ctx.db, sid)},
            "flags": (["STRATEGIC_SUPPLIER"] if supplier_rank(ctx.db, sid) == "HIGH" else [])}


def get_supplier_history(ctx: ToolContext, params: dict) -> dict:
    sid = int(params["supplier_id"])
    batches = ctx.db.execute(select(ProductBatch).where(ProductBatch.supplier_id == sid)
                             .order_by(ProductBatch.received_at.desc()).limit(30)).scalars().all()
    rows = [{"batch_id": b.id, "product_id": b.product_id, "received_at": b.received_at.isoformat() if b.received_at else None,
             "qty": _money(b.quantity_received), "buy_price": _money(b.buy_price),
             "expiry_days": (b.expiry_date - b.received_at.date()).days if (b.expiry_date and b.received_at) else None}
            for b in batches]
    return {"summary": f"{fa.fa_num(len(rows))} محمولهٔ اخیر این تأمین‌کننده",
            "numbers": {"shipments": len(rows)},
            "details": {"shipments": rows}}


# --------------------------------------------------------------------------- existing intelligence as tools
def run_existing_analyzer(ctx: ToolContext, params: dict) -> dict:
    """§8 — the v3.x analyzers become callable capabilities.

    Only the analyzers the caller asks for run, and only over the requested
    scope, so the brain never dumps 78 cards to "fill the screen".
    """
    kinds = params.get("analyzer_id") or params.get("kinds")
    if isinstance(kinds, str):
        kinds = [kinds]
    days = int(params.get("days", 90) or 90)
    available = sorted(ins_svc.ANALYZERS.keys())
    unknown = [k for k in (kinds or []) if k not in ins_svc.ANALYZERS]
    if unknown:
        return {"summary": f"Analyzer ناشناخته: {', '.join(unknown)}", "numbers": {},
                "details": {"available": available}, "flags": ["ANALYZER_UNKNOWN"]}
    ctx_ins = ins_svc._load_ctx(ctx.db, days)
    drafts = []
    for kind in (kinds or []):
        for d in ins_svc.ANALYZERS[kind](ctx_ins):
            drafts.append({"kind": d.kind, "dedupe_key": d.dedupe_key, "title": d.title, "body": d.body,
                           "priority": d.priority, "expected_gain": _money(d.expected_gain),
                           "evidence": d.evidence, "actions": d.actions, "metric": d.metric})
    drafts.sort(key=lambda d: (d["priority"], -d["expected_gain"]))
    return {"summary": f"{fa.fa_num(len(drafts))} یافته از {fa.fa_num(len(kinds or []))} تحلیل‌گر",
            "numbers": {"findings": len(drafts), "total_expected_gain": sum(d["expected_gain"] for d in drafts)},
            "details": {"findings": drafts[:20], "available_analyzers": available}}


def get_profit_forecast(ctx: ToolContext, params: dict) -> dict:
    horizon = int(params.get("horizon", 30) or 30)
    plan = ctx.cached(f"plan:{horizon}", lambda: forecast_svc.plan(ctx.db, horizon=horizon))
    base = plan.get("baseline") or plan.get("forecast") or {}
    return {"summary": f"پیش‌بینی سود {fa.fa_num(horizon)} روز آینده بر پایهٔ روند واقعی فروش",
            "numbers": {k: float(v) for k, v in base.items() if isinstance(v, (int, float))},
            "details": plan}


def get_active_campaigns(ctx: ToolContext, params: dict) -> dict:
    today = local_today()
    rows = ctx.db.execute(select(Campaign).where(Campaign.status == "ACTIVE")
                          .order_by(Campaign.valid_until.desc()).limit(50)).scalars().all()
    out = []
    for c in rows:
        redemptions = ctx.db.execute(select(func.count()).select_from(Invoice)
                                     .where(Invoice.discount > 0,
                                            Invoice.created_at >= datetime.combine(c.valid_from.date(), datetime.min.time()))).scalar_one() if c.valid_from else 0
        out.append({"id": c.id, "name": c.name, "discount_type": c.discount_type,
                    "discount_value": _money(c.discount_value), "valid_from": c.valid_from.isoformat() if c.valid_from else None,
                    "valid_until": c.valid_until.isoformat() if c.valid_until else None, "status": c.status,
                    "days_left": (c.valid_until.date() - today).days if c.valid_until else None,
                    "discounted_invoices": int(redemptions)})
    return {"summary": f"{fa.fa_num(len(out))} کمپین فعال", "numbers": {"active": len(out)},
            "details": {"campaigns": out}}


def get_campaign_outcome(ctx: ToolContext, params: dict) -> dict:
    """§71 — «جشنوارهٔ قبلی جواب داد؟» answered from real invoices, not memory."""
    campaign_id = params.get("campaign_id")
    campaign = ctx.db.get(Campaign, int(campaign_id)) if campaign_id else \
        ctx.db.execute(select(Campaign).order_by(Campaign.id.desc()).limit(1)).scalar_one_or_none()
    if campaign is None:
        return {"summary": "کمپینی ثبت نشده است", "numbers": {}, "details": {}, "flags": ["NO_CAMPAIGN"]}
    start = campaign.valid_from or campaign.created_at
    days = max(1, ((campaign.valid_until or campaign.created_at) - start).days or 1)
    during = _sales_between(ctx, start, start + timedelta(days=days))
    before = _sales_between(ctx, start - timedelta(days=days), start)
    change = ((during["revenue"] - before["revenue"]) / before["revenue"] * 100) if before["revenue"] else None
    profit_change = during["profit"] - before["profit"]
    return {"summary": f"کمپین «{campaign.name}»: فروش "
                       + (f"{fa.fa_num(change, 1)}٪ " if change is not None else "")
                       + f"نسبت به بازهٔ قبل، تغییر سود {fa.toman_short(profit_change)} تومان",
            "numbers": {"campaign_id": campaign.id, "window_days": days,
                        "revenue_during": during["revenue"], "revenue_before": before["revenue"],
                        "profit_during": during["profit"], "profit_before": before["profit"],
                        "profit_change": profit_change,
                        **({"revenue_change_pct": round(change, 1)} if change is not None else {})},
            "details": {"campaign": {"id": campaign.id, "name": campaign.name, "discount": _money(campaign.discount_value),
                                     "type": campaign.discount_type}},
            "flags": (["CAMPAIGN_POSITIVE"] if profit_change > 0 else
                      (["CAMPAIGN_NEGATIVE"] if profit_change < 0 else []))}


# --------------------------------------------------------------------------- brain memory
def get_recent_decisions(ctx: ToolContext, params: dict) -> dict:
    limit = int(params.get("limit", 10) or 10)
    q = select(BrainDecision).order_by(BrainDecision.created_at.desc()).limit(limit)
    status = params.get("status")
    if status:
        q = select(BrainDecision).where(BrainDecision.status == status).order_by(BrainDecision.created_at.desc()).limit(limit)
    rows = ctx.db.execute(q).scalars().all()
    return {"summary": f"{fa.fa_num(len(rows))} تصمیم اخیر" if rows else "تصمیمی ثبت نشده است",
            "numbers": {"count": len(rows), "measured": sum(1 for r in rows if r.measured_gain is not None)},
            "details": {"decisions": [{"id": r.id, "title": r.title, "status": r.status, "kind": r.decision_kind,
                                       "created_at": r.created_at.isoformat() if r.created_at else None,
                                       "selected_option": r.selected_option,
                                       "measured_gain": _money(r.measured_gain) if r.measured_gain is not None else None,
                                       "outcome": r.outcome} for r in rows]}}


def search_decisions(ctx: ToolContext, params: dict) -> dict:
    """Deterministic retrieval for «اون تصمیمی که ماه قبل گرفتیم چی شد؟»."""
    text = str(params.get("query", "")).strip()
    limit = int(params.get("limit", 5) or 5)
    q = select(BrainDecision).order_by(BrainDecision.created_at.desc()).limit(200)
    rows = ctx.db.execute(q).scalars().all()
    if text:
        tokens = [t for t in text.replace("‌", " ").split() if len(t) > 2][:8]
        scored = []
        for r in rows:
            blob = f"{r.title} {r.problem} {r.reason} {r.decision_kind}"
            score = sum(1 for t in tokens if t in blob)
            if score:
                scored.append((score, r))
        rows = [r for _, r in sorted(scored, key=lambda x: (-x[0], -x[1].id))][:limit]
    else:
        rows = list(rows)[:limit]
    return {"summary": f"{fa.fa_num(len(rows))} تصمیم مرتبط پیدا شد",
            "numbers": {"count": len(rows)},
            "details": {"decisions": [{"id": r.id, "title": r.title, "status": r.status,
                                       "reason": r.reason, "outcome": r.outcome,
                                       "measured_gain": _money(r.measured_gain) if r.measured_gain is not None else None,
                                       "created_at": r.created_at.isoformat() if r.created_at else None} for r in rows]}}


def get_open_followups(ctx: ToolContext, params: dict) -> dict:
    rows = ctx.db.execute(select(BrainFollowup).where(BrainFollowup.status == "OPEN")
                          .order_by(BrainFollowup.due_at)).scalars().all()
    overdue = [r for r in rows if r.due_at and r.due_at <= datetime.utcnow()]
    return {"summary": f"{fa.fa_num(len(rows))} پیگیری باز" + (f"، {fa.fa_num(len(overdue))} سررسید گذشته" if overdue else ""),
            "numbers": {"open": len(rows), "overdue": len(overdue)},
            "details": {"followups": [{"id": r.id, "title": r.title, "due_at": r.due_at.isoformat(),
                                       "kind": r.kind, "decision_id": r.decision_id} for r in rows]}}


def get_memory_facts(ctx: ToolContext, params: dict) -> dict:
    kind = params.get("kind")
    q = select(BrainMemoryFact).order_by(BrainMemoryFact.observed_at.desc()).limit(int(params.get("limit", 20) or 20))
    if kind:
        q = select(BrainMemoryFact).where(BrainMemoryFact.kind == kind).order_by(BrainMemoryFact.observed_at.desc()) \
            .limit(int(params.get("limit", 20) or 20))
    rows = ctx.db.execute(q).scalars().all()
    facts = []
    for r in rows:
        if r.expires_at and r.expires_at <= datetime.utcnow():
            continue
        facts.append({"kind": r.kind, "key": r.key, "value": _safe_json(r.value, {}),
                      "confidence": float(r.confidence or 0), "source": r.source,
                      "observed_at": r.observed_at.isoformat() if r.observed_at else None})
    return {"summary": f"{fa.fa_num(len(facts))} واقعیت در حافظهٔ کسب‌وکار",
            "numbers": {"count": len(facts)}, "details": {"facts": facts}}


# --------------------------------------------------------------------------- write tools (low risk only)
def create_task(ctx: ToolContext, params: dict) -> dict:
    """AUTO-class write: a note/task for staff. Reversible, no money movement."""
    from ..notifications import notify

    title = str(params.get("title") or "کار جدید")
    body = str(params.get("body") or "")
    n = notify(ctx.db, type="BRAIN_TASK", title=title, body=body, severity=str(params.get("severity", "INFO")),
               reference_type="Brain", reference_id=int(params.get("decision_id") or 0))
    return {"summary": f"کار «{title}» ثبت شد", "numbers": {}, "details": {"notification_id": n.id}}


def create_followup(ctx: ToolContext, params: dict) -> dict:
    """AUTO-class write: a follow-up the manager asked for («یادم بنداز»)."""
    from .followups import create as create_followup_row

    row = create_followup_row(ctx.db, title=str(params["title"]),
                              due_at=params.get("due_at"), days=int(params.get("days", 3) or 3),
                              kind=str(params.get("kind", "REMIND")), note=str(params.get("note", "")),
                              decision_id=params.get("decision_id"), user_id=getattr(ctx.user, "id", None))
    return {"summary": f"پیگیری «{row.title}» ثبت شد", "numbers": {},
            "details": {"followup_id": row.id, "due_at": row.due_at.isoformat()}}


def record_memory_fact(ctx: ToolContext, params: dict) -> dict:
    """AUTO-class write: durable knowledge learned from a measured outcome."""
    from .memory import remember

    fact = remember(ctx.db, kind=str(params["kind"]), key=str(params["key"]),
                    value=params.get("value") or {}, confidence=float(params.get("confidence", 0.5)),
                    source=str(params.get("source", "DECISION")),
                    reference_type=params.get("reference_type"), reference_id=params.get("reference_id"))
    return {"summary": "به حافظهٔ کسب‌وکار اضافه شد", "numbers": {},
            "details": {"fact_id": fact.id, "key": fact.key}}


def measure_action(ctx: ToolContext, params: dict) -> dict:
    """§55 — measure a finished decision over its own contract window."""
    from .decisions import measure

    decision = ctx.db.get(BrainDecision, int(params["decision_id"]))
    if decision is None:
        return {"summary": "تصمیم پیدا نشد", "numbers": {}, "details": {}, "flags": ["DECISION_NOT_FOUND"]}
    out = measure(ctx.db, decision)
    return {"summary": out.get("summary", "اندازه‌گیری انجام شد"),
            "numbers": {k: float(v) for k, v in (out.get("numbers") or {}).items()
                        if isinstance(v, (int, float))},
            "details": out}


# --------------------------------------------------------------------------- web (never a substitute for shop data)
def search_web(ctx: ToolContext, params: dict) -> dict:
    """Optional web lookup (§25).

    Disabled unless the owner enabled cloud AI *and* the machine is online. It
    returns an honest ``WEB_UNAVAILABLE`` instead of inventing an answer, and it
    is never allowed to fill a shop number (see ``grounding.py``).
    """
    from .policies import get_value

    allowed = bool(get_value(ctx.db, "allow_cloud_ai", False))
    query = str(params.get("query", "")).strip()
    if not allowed:
        return {"summary": "جست‌وجوی وب خاموش است (فقط با اجازهٔ مدیر و اتصال اینترنت)",
                "numbers": {}, "details": {"enabled": False}, "flags": ["WEB_DISABLED"]}
    url = "https://duckduckgo.com/html/?q=" + urllib.parse.quote(query)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "SupermarketSystem/4.0"})
        with urllib.request.urlopen(req, timeout=8) as r:  # noqa: S310 — fixed https host
            body = r.read(4000).decode("utf-8", "ignore")
        return {"summary": "نتیجهٔ جست‌وجوی وب دریافت شد (منبع بیرونی، نه دادهٔ فروشگاه)",
                "numbers": {}, "details": {"query": query, "snippet": body[:1200], "source": "duckduckgo"},
                "flags": ["WEB_RESULT"]}
    except Exception as exc:  # noqa: BLE001 — offline is a normal state, not a crash
        return {"summary": "به اینترنت دسترسی نبود؛ از دادهٔ فروشگاه استفاده می‌کنم",
                "numbers": {}, "details": {"query": query, "error": str(exc)[:200]},
                "flags": ["WEB_UNAVAILABLE"]}


def get_hardware_status(ctx: ToolContext, params: dict) -> dict:
    """§62 — devices as tools; a broken device is a business fact, not a mystery."""
    from ..hw import manager as hw_manager

    try:
        report = hw_manager.detect_and_register(ctx.db, auto_create=False)
    except Exception as exc:  # noqa: BLE001 — hardware layer may be absent on servers
        return {"summary": "لایهٔ سخت‌افزار در دسترس نیست", "numbers": {},
                "details": {"error": str(exc)[:200]}, "flags": ["HARDWARE_UNAVAILABLE"]}
    devices = report.get("devices", report) if isinstance(report, dict) else {}
    return {"summary": "وضعیت دستگاه‌های فروشگاه بررسی شد", "numbers": {}, "details": {"report": report},
            "flags": ["HARDWARE_CHECKED"]}


# --------------------------------------------------------------------------- internal helpers
def _velocity(ctx: ToolContext, product_id: int, days: int = 28) -> float:
    key = f"vel:{product_id}:{days}"
    return ctx.cached(key, lambda: _sold_qty(ctx, product_id, days) / max(1, days))


def _sold_qty(ctx: ToolContext, product_id: int, days: int) -> float:
    v = ctx.db.execute(select(func.coalesce(func.sum(InvoiceItem.qty), 0))
                       .join(Invoice, Invoice.id == InvoiceItem.invoice_id)
                       .where(InvoiceItem.product_id == product_id, Invoice.status == "PAID",
                              Invoice.created_at >= _since(days))).scalar_one()
    return _money(v)


def _stock(ctx: ToolContext, product_id: int) -> float:
    key = f"stock:{product_id}"
    return ctx.cached(key, lambda: _money(ctx.db.execute(
        select(func.coalesce(func.sum(ProductBatch.current_qty), 0))
        .where(ProductBatch.product_id == product_id, ProductBatch.status == "ACTIVE")).scalar_one()))


def _weighted(batches, field: str) -> float:
    total_qty = sum(_money(b.current_qty) for b in batches)
    if total_qty <= 0:
        return 0.0
    return sum(_money(b.current_qty) * _money(getattr(b, field)) for b in batches) / total_qty


def _sales_between(ctx: ToolContext, start: datetime, end: datetime) -> dict:
    """Invoice-level totals and line-level profit are aggregated separately.

    Joining invoices to their items multiplies ``total_amount`` by the number of
    lines — a well-known way to report a 4× too-large revenue. Two queries keep
    both numbers honest (and are cheaper than DISTINCT on a wide row).
    """
    head = ctx.db.execute(
        select(func.count(Invoice.id), func.coalesce(func.sum(Invoice.total_amount), 0),
               func.coalesce(func.avg(Invoice.total_amount), 0), func.coalesce(func.sum(Invoice.discount), 0))
        .where(Invoice.status == "PAID", Invoice.created_at >= start, Invoice.created_at < end)).one()
    profit = ctx.db.execute(
        select(func.coalesce(func.sum(InvoiceItem.profit), 0))
        .join(Invoice, Invoice.id == InvoiceItem.invoice_id)
        .where(Invoice.status == "PAID", Invoice.created_at >= start, Invoice.created_at < end)).scalar_one()
    return {"invoices": int(head[0] or 0), "revenue": _money(head[1]), "profit": _money(profit),
            "avg_basket": _money(head[2]), "discount": _money(head[3]),
            "start": start.isoformat(), "end": end.isoformat()}


def _lead_time(ctx: ToolContext, batch: ProductBatch) -> int | None:
    """Days between the supplier's shipment and its arrival in the shop."""
    if not batch.received_at or not batch.production_date:
        return None
    delta = (batch.received_at.date() - batch.production_date).days
    return delta if 0 <= delta <= 180 else None
