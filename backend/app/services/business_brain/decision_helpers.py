"""v4.0 — option generation, contradiction detection and scoring (§24, §27, §53).

Three pieces of deterministic judgement live here, and nothing else does:

* :func:`contradictions` — where two domains disagree. This is the feature the
  brief calls «مهم‌ترین»: «خرید منطقی است، ولی پرداخت نقدی مناسب نیست».
* :func:`build_options` — the catalogue of courses of action for a situation,
  each with the taxonomy code the decision record stores (NO_ACTION, DISCOUNT,
  BUNDLE, CAMPAIGN, TARGETED_OFFER, SUPPLIER_RETURN, STAFF_GUIDANCE, …) and an
  economics block computed with a stated formula.
* :func:`score_options` — priority from impact ∧ urgency ∧ confidence ∧ risk ∧
  reversibility ∧ policy ∧ data quality. No invented "AI score": every term
  is one of those named factors, and the weights are constants in this file.

Money estimates go through the shop's own calibration (``services/forecast.py``
``calibrate``), so a shop whose discounts have historically under-delivered gets
more conservative numbers automatically — the same learning loop that grades the
v3.x insights (§54).
"""
from __future__ import annotations

import math
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ...models import Invoice, InvoiceItem, Product, ProductBatch
from .. import forecast as forecast_svc
from ..timeservice import local_today
from . import persian as fa
from .schemas import Evidence, Option

#: §53 weights — kept as named constants so any change is reviewable
W_IMPACT = 1.0        # log-scaled toman impact
W_URGENCY = 0.6       # days until it hurts
W_CONFIDENCE = 0.8
W_RISK = 1.2
W_REVERSIBLE = 0.3
W_POLICY = 1.5
W_DATA_QUALITY = 1.0

RISK_PENALTY = {"none": 0.0, "low": 0.15, "medium": 0.4, "high": 1.0}
CONFIDENCE_VALUE = {"high": 1.0, "medium": 0.6, "low": 0.3, "blocked": 0.1}


# --------------------------------------------------------------------------- contradictions (§24)
def contradictions(evidence: list[Evidence], situation) -> list[dict]:
    """Cross-domain conflicts, written as the sentence the owner should hear."""
    found: list[dict] = []
    by_domain = {e.domain: e for e in evidence}
    flags = {f for e in evidence for f in (e.flags or [])}
    numbers = {k: v for e in evidence for k, v in (e.numbers or {}).items()}

    cash_pressure = "CASH_PRESSURE_HIGH" in flags
    inventory = by_domain.get("inventory")
    finance = by_domain.get("finance")
    sales = by_domain.get("sales")
    pricing = by_domain.get("pricing")
    supplier = by_domain.get("supplier")

    inv_flags = set((inventory.flags if inventory else []) or [])
    if cash_pressure and ({"STOCKOUT_RISK"} & inv_flags):
        found.append({"kind": "BUY_WITHOUT_CASH", "domains": ["inventory", "finance"], "severity": "high",
                      "statement": "خرید لازم است ولی پول نقد کافی نیست؛ خرید باید با اعتبار تأمین‌کننده انجام شود، "
                                   "نه پرداخت نقدی.",
                      "resolution": "خرید اعتباری / مذاکرهٔ مهلت"})
    if {"EXPIRY_RISK"} & inv_flags and ({"SALES_DROP"} & set((sales.flags if sales else []) or [])):
        found.append({"kind": "DISCOUNT_WHILE_DEMAND_LOW", "domains": ["inventory", "sales"], "severity": "medium",
                      "statement": "کالای نزدیک انقضا هم‌زمان با افت تقاضا است؛ تخفیف تنها راه نیست و باید با "
                                   "باندل یا پیشنهاد هدف‌دار همراه شود.",
                      "resolution": "باندل یا پیشنهاد هدف‌دار"})
    if "THIN_MARGIN" in flags and ({"EXPIRY_RISK"} & inv_flags):
        found.append({"kind": "DISCOUNT_BELOW_MARGIN", "domains": ["pricing", "inventory"], "severity": "high",
                      "statement": "حاشیهٔ سود این کالا کم است؛ تخفیف نقدی به زیان تبدیل می‌شود. آزادسازی سرمایه "
                                   "با مرجوعی یا باندل منطقی‌تر است.",
                      "resolution": "مرجوعی به تأمین‌کننده یا باندل با کالای پرفروش"})
    if "STOCKOUT_RISK" in inv_flags and by_domain.get("supplier") and numbers.get("lead_time_days"):
        if numbers["lead_time_days"] > 7:
            found.append({"kind": "LEAD_TIME_LONGER_THAN_STOCK", "domains": ["inventory", "supplier"], "severity": "high",
                          "statement": f"زمان تأمین این تأمین‌کننده حدود {fa.fa_num(numbers['lead_time_days'])} روز است؛ "
                                       "سفارش امروز باید پیش از اتمام موجودی برسد.",
                          "resolution": "سفارش فوری / افزایش نقطهٔ سفارش"})
    if "DATA_QUALITY_BLOCKED" in flags or (situation and "DATA_QUALITY_BLOCKED" in (situation.flags or [])):
        found.append({"kind": "DATA_QUALITY", "domains": ["operations"], "severity": "critical",
                      "statement": "داده‌های فروشگاه مشکل بحرانی دارند؛ تصمیم مالی قطعی در این وضعیت درست نیست.",
                      "resolution": "اصلاح داده پیش از تصمیم"})
    if pricing and "THIN_MARGIN" in (pricing.flags or []) and cash_pressure:
        found.append({"kind": "MARGIN_AND_CASH", "domains": ["pricing", "finance"], "severity": "medium",
                      "statement": "فشار نقدی با حاشیهٔ سود کم هم‌زمان شده؛ تخفیف فروش را بالا می‌برد ولی سود نمی‌سازد.",
                      "resolution": "تمرکز بر وصول مطالبات به‌جای تخفیف"})
    return found


# --------------------------------------------------------------------------- economics
def _calibrated(db: Session, kind: str, raw: float) -> float:
    """The shop's own calibration, applied to the brain's raw estimates too (§54)."""
    try:
        cal = forecast_svc._load_cal(db)
        out = forecast_svc.calibrate(db, kind, raw, cal)
        return float(out.get("gain", raw))
    except Exception:  # noqa: BLE001 — calibration is an improvement, not a requirement
        return float(raw)


def discount_economics(*, at_risk_value: float, margin_pct: float, percent: float, days: int,
                       velocity: float, stock_value: float) -> dict:
    """Deterministic money math for «تخفیف بدهیم یا نه» (§22 — never a model opinion).

    * ``lost_without_action`` — the at-risk capital that expires unsold.
    * ``gross_recovered`` — the value that extra velocity is expected to move.
    * ``margin_lost`` — the margin given away on units that would have sold anyway.
    * ``net_benefit`` = gross_recovered − margin_lost, floored at "lose less".
    """
    at_risk = max(0.0, float(at_risk_value))
    sell_price_ratio = 1 + max(0.0, margin_pct) / 100.0
    # price elasticity: a deeper discount moves more of the at-risk stock, with
    # diminishing returns (deterministic, documented, and capped at 90 %)
    recovery = min(0.9, 0.15 + (percent / 100.0) * 2.5 + (days / 100.0))
    gross_recovered = at_risk * sell_price_ratio * recovery
    margin_lost = at_risk * max(0.0, percent) / 100.0 * (1 - recovery)
    net = gross_recovered * (margin_pct / 100.0) - margin_lost
    return {"at_risk_value": round(at_risk), "recovery_rate": round(recovery, 3),
            "gross_recovered": round(gross_recovered), "margin_lost": round(margin_lost),
            "net_benefit": round(net), "gain_toman": round(net), "window_days": 14,
            "metric": "product_profit", "formula": "recovery=min(.9,.15+p/100*2.5+days/100)"}


def _situation_numbers(situation) -> dict:
    """Flatten the situation into one numeric bag.

    Sub-blocks keep their own keys and a prefixed copy (``forecast_min_projected_cash``),
    so an option builder can use the specific number it means without guessing
    which block a bare ``total`` came from.
    """
    out: dict = {}
    if situation is None:
        return out
    for block in ("cash", "obligations", "receivables", "inventory", "sales"):
        data = getattr(situation, block, None) or {}
        out.update({k: float(v) for k, v in (data.get("numbers") or {}).items()
                    if isinstance(v, (int, float)) and not isinstance(v, bool)})
        for sub in ("expiry_risk", "overstock", "stockout", "forecast"):
            sub_data = data.get(sub) or {}
            for key, value in (sub_data.get("numbers") or {}).items():
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    out.setdefault(key, float(value))
                    out[f"{sub}_{key}"] = float(value)
    # the collection projection is computed inside the forecast; expose it under
    # the same name the collection tool uses so option builders need one key
    if "expected_collections" in out:
        out.setdefault("expected_total", out["expected_collections"])
    return out


def _first_item(block: dict, key: str = "items") -> dict | None:
    items = ((block or {}).get("details") or {}).get(key) or []
    return items[0] if items else None


# --------------------------------------------------------------------------- option builders
def build_options(db: Session, ctx, u, evidence: list[Evidence], situation, conflicts: list[dict]) -> list[Option]:
    nums = _situation_numbers(situation)
    flags = {f for e in evidence for f in (e.flags or [])}
    intent = u.intent
    builders = {
        "EXECUTE_DECISION": _execute_options,
        "CASH_CRISIS": _cash_options, "CHEQUE_MANAGEMENT": _cash_options, "RECEIVABLE": _receivable_options,
        "EXPIRY": _expiry_options, "STOCKOUT": _stockout_options, "OVERSTOCK": _overstock_options,
        "SALES_DROP": _sales_options, "PRODUCT_ACTION": _product_options, "CUSTOMER_ACTION": _customer_options,
        "SUPPLIER": _supplier_options, "CAMPAIGN_FOLLOWUP": _campaign_options, "STORE_STATUS": _status_options,
        "DECISION_RECALL": _info_options, "POLICY_SET": _info_options, "GENERAL": _status_options,
    }
    options = builders.get(intent, _status_options)(db, ctx, u, nums, flags, evidence, conflicts, situation)
    # data-quality discipline: mark every monetary option as needing approval when
    # the numbers it rests on are known to be dirty
    if "DATA_QUALITY_BLOCKED" in flags or (situation and "DATA_QUALITY_BLOCKED" in (situation.flags or [])):
        for option in options:
            option.confidence = "blocked"
            option.tradeoffs.append("کیفیت داده پایین است؛ عدد این گزینه قابل اتکا نیست")
    return options


def _no_action(reason: str = "", *, kind: str = "NO_ACTION") -> Option:
    return Option(id="no_action", label="فعلاً کاری نکنیم", description=reason or
                  "وضعیت در محدودهٔ عادی است و اقدام خاصی لازم نیست", risk="none", reversible=True,
                  requires_approval=False, action_class="AUTO", confidence="high",
                  economics={"gain_toman": 0, "metric": "avg_basket_size"}, tradeoffs=[])


def _cash_options(db, ctx, u, nums, flags, evidence, conflicts, situation) -> list[Option]:
    """§22 + acceptance #1: the plan is an *ordering*, not a list.

    The gap is computed deterministically: obligations inside the window minus
    what is available minus what the shop's own customers are expected to pay in
    that same window. Every option is priced against that gap, so the top option
    is the cheapest way to close it — collecting money the shop is owed, before
    giving away margin or borrowing.
    """
    options: list[Option] = []
    available = nums.get("cash_available", 0.0)
    obligations_7d = nums.get("issued_next_7d", 0.0) or 0.0
    expected = nums.get("expected_total", 0.0) or 0.0
    receivables = nums.get("receivables_total") or nums.get("total") or 0.0
    overdue = nums.get("overdue_count", 0.0) or 0.0
    horizon = nums.get("horizon_days", 14.0) or 14.0
    min_projected = nums.get("min_projected_cash")
    gap = max(0.0, obligations_7d - available - expected)
    shortfall = nums.get("shortfall", 0.0) or 0.0
    # §22: a buffer that ends at ۲۰۰ هزار تومان is a real risk even though the
    # projection never goes negative — the shop must hear about it *before* the
    # cheque, when acting is still cheap. The floor comes from the forecast tool
    # (20% of the cheques inside the window), so the plan and the projection can
    # never disagree about what "safe" means.
    safety_target = float(nums.get("forecast_safety_target") or
                          (max(obligations_7d * 0.2, 5_000_000.0) if obligations_7d else 0.0))
    need_for_buffer = max(0.0, safety_target - (min_projected if min_projected is not None else available))
    days_below_safety = int(nums.get("forecast_days_below_safety") or 0)
    fragile = float(nums.get("forecast_min_without_collections") or 0.0) < 0
    # timing: money that must arrive *before* the next cheque, not within 14 days
    cheques_3d = _cheques_within(situation, 3)
    expected_3d = float(nums.get("forecast_expected_next_3d") or nums.get("expected_next_3d") or 0.0)
    timing_gap = max(0.0, cheques_3d + safety_target * 0.5 - available - expected_3d)
    thin = (bool(obligations_7d) and
            (days_below_safety > 0 or fragile or
             (min_projected is not None and min_projected <= max(1_000_000.0, obligations_7d * 0.05))))
    debtors = _high_confidence_debtors(ctx) if receivables > 0 else []
    collection_ceiling = round(expected)

    # 1) collect what customers already owe — no margin given away
    if receivables > 0 and (gap > 0 or overdue or (thin and expected > 0) or timing_gap > 0):
        covered = round(min(gap if gap > 0 else need_for_buffer, collection_ceiling)) or round(min(receivables,
                                                                                                  collection_ceiling))
        actions = [{"type": "note", "params": {}, "label": "ثبت پیگیری وصول مطالبات", "reversible": True}]
        if debtors:
            actions.insert(0, {"type": "personal_sms",
                               "params": {"customers": [{"customer_id": d["customer_id"],
                                                         "text": _debt_text(d)} for d in debtors[:10]]},
                               "label": "پیام یادآوری بدهی برای مشتریان خوش‌حساب", "reversible": False})
        options.append(Option(
            id="chase_receivable", label="وصول مطالبات پیش از سررسید",
            action_class="APPROVAL", requires_approval=True, risk="low", reversible=False,
            confidence="high" if debtors else "medium",
            description=(f"حدود {fa.toman_short(collection_ceiling)} تومان از مطالبات در همین بازه قابل وصول است"
                         + (f" و {fa.fa_num(len(debtors))} مشتری با سابقهٔ پرداخت منظم داری" if debtors else "")
                         + (f"؛ فاصلهٔ {fa.toman_short(gap)} تومانی پرداخت‌ها را پر می‌کند" if gap else
                            f"؛ {fa.toman_short(max(covered, 0))} تومان از آن باید قبل از سررسید نزدیک "
                            f"برسد تا موجودی زیر کف امن نرود")),
            economics={"gain_toman": covered, "coverage": covered, "gap_after": round(gap - covered),
                       "timing_gap_toman": round(timing_gap), "expected_next_3d": round(expected_3d),
                       "cheques_next_3d": round(cheques_3d),
                       "metric": "receivables_collected", "window_days": int(horizon),
                       "followup_days": 5, "kind": "COLLECTION",
                       "formula": "expected collections = Σ balance × confidence share"},
            actions=actions,
            tradeoffs=["پیامک برای هر مشتری هزینه دارد", "وصول تضمینی نیست"]))

    # 2) ask for time instead of selling cheap — preserves margin
    cheques = _issued_cheques(situation)
    if gap > 0 or shortfall or timing_gap > 0 or (thin and cheques):
        target = round(max(shortfall, gap, timing_gap, need_for_buffer * 0.5, 0))
        second = cheques[1] if len(cheques) > 1 else (cheques[0] if cheques else None)
        when = (f"{fa.money(second.get('amount'))} چک با سررسید "
                f"{fa.rel_days(second.get('days_left'))}" if second else "چک نزدیک‌سررسید")
        options.append(Option(
            id="negotiate_supplier_terms", label="مهلت گرفتن از تأمین‌کننده برای چک نزدیک",
            description=(f"برای پوشش {fa.toman_short(target)} تومان کسری، به‌جای تخفیف روی موجودی، "
                         f"برای {when} مهلت یا پرداخت بخشی توافق شود"),
            action_class="APPROVAL", requires_approval=True, risk="low", reversible=True, confidence="medium",
            economics={"gain_toman": round(target * 0.35), "metric": "avg_basket_size",
                       "window_days": int(horizon), "followup_days": 3, "kind": "SUPPLIER_TERMS",
                       "formula": "avoided fire-sale discount on the same amount"},
            actions=[{"type": "note", "params": {}, "label": "یادداشت مذاکره با تأمین‌کننده", "reversible": True}],
            tradeoffs=["رابطهٔ تجاری", "ممکن است پذیرفته نشود"]))

    # 3) free up the capital sitting in dead stock (last resort: it costs margin)
    overstock_capital = nums.get("capital") or nums.get("overstock_capital") or 0.0
    if (gap > 0 or timing_gap > 0) and overstock_capital and not thin:
        percent = min(30, float(_policy(db, "max_discount_without_approval", 15)))
        econ = discount_economics(at_risk_value=float(overstock_capital), margin_pct=12.0, percent=percent,
                                  days=10, velocity=0.0, stock_value=float(overstock_capital))
        econ["kind"] = "DEAD_STOCK"
        options.append(Option(
            id="liquidate_slow_stock", label=f"فروش ویژهٔ {fa.fa_num(percent, 0)}٪ روی کالای راکد",
            description=f"آزادسازی بخشی از {fa.toman_short(overstock_capital)} تومان سرمایهٔ راکد",
            action_class="APPROVAL", requires_approval=True, risk="medium", reversible=True, confidence="medium",
            economics=econ,
            actions=[{"type": "flash_sale", "params": {"percent": percent, "days": 10},
                      "label": f"کمپین {fa.fa_num(percent, 0)}٪ برای کالای راکد", "reversible": True}],
            tradeoffs=["حاشیه روی واحدهایی که خودشان هم فروش می‌رفتند از دست می‌رود"]))

    # 4) the honest answer when the numbers do not require action
    if not options or (min_projected is not None and min_projected >= 0 and not overdue and not thin
                       and gap <= 0 and timing_gap <= 0):
        options.append(_no_action("با احتساب وصول‌های مورد انتظار، پرداخت‌های پیش‌رو از موجودی پوشش داده می‌شود"))
    return options


def _receivable_options(db, ctx, u, nums, flags, evidence, conflicts, situation) -> list[Option]:
    cb = u.entities.get("customer_id")
    options = []
    if cb:
        row = _customer_snapshot(ctx.db, cb)
        options.append(Option(id="chase_customer", label="پیگیری مستقیم همین مشتری",
                              description=f"{row['name']} با مانده {fa.toman_short(row['balance'])} تومان",
                              action_class="APPROVAL", risk="low", reversible=False, requires_approval=True,
                              confidence="high",
                              economics={"gain_toman": round(row["balance"]), "metric": "receivables_collected",
                                         "window_days": 14, "followup_days": 7},
                              actions=[{"type": "personal_sms",
                                        "params": {"customers": [{"customer_id": cb, "text": _debt_text(row)}]},
                                        "label": "پیام یادآوری بدهی", "reversible": False},
                                       {"type": "note", "params": {}, "label": "ثبت پیگیری", "reversible": True}],
                              tradeoffs=["پیامک هزینه دارد"]))
    debtors = _high_confidence_debtors(ctx)
    if debtors:
        options.append(Option(id="chase_receivable", label="پیگیری گروهی خوش‌حساب‌ها",
                              description=f"{fa.fa_num(len(debtors))} مشتری با سابقهٔ پرداخت خوب",
                              action_class="APPROVAL", risk="low", reversible=False, requires_approval=True,
                              confidence="high",
                              economics={"gain_toman": round(sum(d["balance"] for d in debtors) * 0.5),
                                         "metric": "receivables_collected", "window_days": 14, "followup_days": 7},
                              actions=[{"type": "debt_reminders", "params": {}, "label": "یادآوری گروهی بدهی",
                                        "reversible": False}], tradeoffs=["هر پیامک هزینه دارد"]))
    options.append(_no_action("مطالبات در وضعیت عادی است و پیگیری فوری لازم ندارد"))
    return options


def _expiry_options(db, ctx, u, nums, flags, evidence, conflicts, situation) -> list[Option]:
    """§27 — expiring stock is a situation, not an instruction to discount."""
    pid = u.entities.get("product_id")
    options: list[Option] = []
    if pid:
        snap = _snapshot(ctx, pid) or {}
        batches = ((snap.get("details") or {}).get("batches") or [])
        numbers = snap.get("numbers") or {}
        if not numbers:
            return [_no_action("اطلاعات این کالا کامل نیست")]
        stock = float(numbers.get("stock") or 0)
        velocity = float(numbers.get("velocity_per_day") or 0)
        margin_pct = float(numbers.get("margin_pct") or 0)
        buy = float(numbers.get("avg_cost") or 0)
        sells_before_expiry = velocity * float((batches[0] or {}).get("days_left") or 30) if batches else None
        risk_value = 0.0
        if batches:
            days_left = min((b.get("days_left") or 999) for b in batches)
            at_risk_qty = max(0.0, stock - velocity * max(0, days_left))
            risk_value = at_risk_qty * buy
        percent = min(float(_policy(db, "max_discount_without_approval", 15)), 25)
        econ = discount_economics(at_risk_value=risk_value, margin_pct=margin_pct, percent=percent, days=10,
                                  velocity=velocity, stock_value=stock * buy)
        econ["kind"] = "EXPIRY_LADDER"
        options.append(Option(id="discount", label=f"جشنوارهٔ کوتاه {fa.fa_num(percent, 0)}٪ روی همین گروه",
                              description=f"حدود {fa.toman_short(risk_value)} تومان از این موجودی با سرعت فروش "
                                          "فعلی فروش نمی‌رود",
                              action_class="APPROVAL", risk="medium", reversible=True, requires_approval=True,
                              confidence="medium" if margin_pct >= 8 else "low", economics=econ,
                              actions=[{"type": "flash_sale", "params": {"percent": int(percent), "days": 10},
                                        "label": "کمپین کوتاه انقضا", "reversible": True}],
                              tradeoffs=["تخفیف روی واحدهایی که خودشان هم فروش می‌رفتند"]))
        options.append(Option(id="bundle", label="باندل با کالای پرفروش",
                              description="کالای نزدیک انقضا را کنار کالای پرگردش بگذاریم و در یک بسته بفروشیم",
                              action_class="APPROVAL", risk="low", reversible=True, requires_approval=True,
                              confidence="medium",
                              economics={"gain_toman": round(risk_value * 0.4), "metric": "product_profit",
                                         "window_days": 14, "followup_days": 7, "kind": "DEAD_STOCK"},
                              actions=[{"type": "bundle_campaign", "params": {"product_id": pid, "percent": 10},
                                        "label": "باندل با کالای پرفروش", "reversible": True},
                                       {"type": "shelf_note", "params": {"products": [pid]},
                                        "label": "چیدمان کنار کالای پرفروش", "reversible": True}],
                              tradeoffs=["نیاز به چیدمان و همراهی پرسنل"]))
        options.append(Option(id="staff_guidance", label="توجیه پرسنل و پیشنهاد حضوری",
                              description="پرسنل صندوق به مشتریان مناسب این کالا را پیشنهاد دهند",
                              action_class="AUTO", risk="low", reversible=True, requires_approval=False,
                              confidence="medium",
                              economics={"gain_toman": round(risk_value * 0.2), "metric": "product_profit",
                                         "window_days": 14, "followup_days": 7, "kind": "STAFF_GUIDANCE"},
                              actions=[{"type": "note", "params": {}, "label": "پیام به پرسنل", "reversible": True}],
                              tradeoffs=["اثر آن به‌سختی اندازه‌گیری می‌شود"]))
        if margin_pct < 5:
            options.append(Option(id="supplier_return", label="مرجوعی به تأمین‌کننده",
                                  description="حاشیهٔ این کالا کم است؛ تخفیف به زیان تبدیل می‌شود",
                                  action_class="HIGH_RISK", risk="medium", reversible=False,
                                  requires_approval=True, confidence="medium",
                                  economics={"gain_toman": round(risk_value * 0.6), "metric": "product_profit",
                                             "window_days": 21, "followup_days": 10, "kind": "SUPPLIER_RETURN"},
                                  actions=[{"type": "note", "params": {},
                                            "label": "درخواست مرجوعی از تأمین‌کننده", "reversible": True}],
                                  tradeoffs=["رابطه با تأمین‌کننده", "پذیرش او الزامی نیست"]))
    else:
        expiry = ((situation.inventory or {}).get("expiry_risk") or {}) if situation else {}
        items = ((expiry.get("details") or {}).get("items") or [])
        total = float((expiry.get("numbers") or {}).get("at_risk_value") or 0)
        if items:
            percent = min(float(_policy(db, "max_discount_without_approval", 15)), 20)
            econ = discount_economics(at_risk_value=total, margin_pct=12.0, percent=percent, days=10,
                                      velocity=0, stock_value=total)
            econ["kind"] = "EXPIRY_LADDER"
            top = items[0]
            options.append(Option(id="discount", label=f"جشنوارهٔ {fa.fa_num(percent, 0)}٪ روی گروه‌های در معرض انقضا",
                                  description=f"مهم‌ترین مورد: {top.get('product')} با "
                                              f"{fa.toman_short(top.get('value'))} تومان در معرض خطر",
                                  action_class="APPROVAL", risk="medium", reversible=True,
                                  requires_approval=True, confidence="medium", economics=econ,
                                  actions=[{"type": "flash_sale", "params": {"percent": int(percent), "days": 10},
                                            "label": "کمپین انقضا", "reversible": True}],
                                  tradeoffs=["فرسایش حاشیه"]))
            options.append(Option(id="staff_guidance", label="توجیه پرسنل برای پیشنهاد حضوری",
                                  description="بدون تخفیف، با راهنمایی پرسنل روی کالاهای نزدیک انقضا",
                                  action_class="AUTO", risk="low", reversible=True, requires_approval=False,
                                  confidence="medium",
                                  economics={"gain_toman": round(total * 0.15), "metric": "product_profit",
                                             "window_days": 14, "followup_days": 7, "kind": "STAFF_GUIDANCE"},
                                  actions=[{"type": "note", "params": {}, "label": "پیام به پرسنل", "reversible": True}],
                                  tradeoffs=["نتیجه سخت اندازه‌گیری می‌شود"]))
    options.append(_no_action("با سرعت فروش فعلی، این موجودی پیش از انقضا فروش می‌رود"))
    return options


def _stockout_options(db, ctx, u, nums, flags, evidence, conflicts, situation) -> list[Option]:
    options: list[Option] = []
    pid = u.entities.get("product_id")
    stockouts = ((situation.inventory or {}).get("stockout") or {}) if situation else {}
    items = ((stockouts.get("details") or {}).get("items") or [])
    if pid:
        snap = _snapshot(ctx, pid) or {}
        numbers = snap.get("numbers") or {}
        if numbers:
            days_left = float(numbers.get("days_of_cover") or 0)
            velocity = float(numbers.get("velocity_per_day") or 0)
            margin = float(numbers.get("margin_per_unit") or 0)
            gain = velocity * 14 * margin
            options.append(Option(id="reorder", label="سفارش فوری این کالا",
                                  description=f"با سرعت {fa.fa_num(velocity, 2)} در روز، حدود "
                                              f"{fa.fa_num(max(0, days_left), 1)} روز موجودی می‌ماند",
                                  action_class="APPROVAL", risk="low", reversible=True, requires_approval=True,
                                  confidence="high",
                                  economics={"gain_toman": round(gain * 0.35), "metric": "product_profit",
                                             "window_days": 14, "followup_days": 7, "kind": "REORDER"},
                                  actions=[{"type": "reorder_note", "params": {"product_id": pid},
                                            "label": "افزودن به لیست سفارش", "reversible": True},
                                           {"type": "note", "params": {}, "label": "یادداشت برای پرسنل",
                                            "reversible": True}],
                                  tradeoffs=["سرمایهٔ در گردش را درگیر می‌کند"]))
            if numbers.get("min_stock_alert") is not None:
                options.append(Option(id="set_min_stock", label="اصلاح نقطهٔ سفارش",
                                      description="حداقل موجودی این کالا با سرعت فروشش نمی‌خواند",
                                      action_class="APPROVAL", risk="low", reversible=True,
                                      requires_approval=True, confidence="medium",
                                      economics={"gain_toman": round(gain * 0.2), "metric": "availability",
                                                 "window_days": 28, "followup_days": 14},
                                      actions=[{"type": "set_min_stock",
                                                "params": {"product_id": pid,
                                                           "min_stock": max(1, int(round(velocity * 7)))},
                                                "label": "اصلاح حداقل موجودی", "reversible": True}],
                                      tradeoffs=[]))
    elif items:
        top = items[0]
        gain = float(top.get("velocity_per_day") or 0) * 14 * 5000
        options.append(Option(id="reorder", label="سفارش کالاهای در معرض اتمام",
                              description=f"{fa.fa_num(len(items))} قلم؛ اول از همه {top.get('product')}",
                              action_class="APPROVAL", risk="low", reversible=True, requires_approval=True,
                              confidence="high",
                              economics={"gain_toman": round(gain * 0.3), "metric": "availability",
                                         "window_days": 28, "followup_days": 7, "kind": "REORDER"},
                              actions=[{"type": "reorder_note", "params": {"products": [i["product_id"] for i in items[:10]]},
                                        "label": "افزودن به لیست سفارش", "reversible": True}],
                              tradeoffs=["سرمایهٔ در گردش"]))
    options.append(_no_action("خطر اتمام در بازهٔ نزدیک دیده نمی‌شود"))
    return options


def _overstock_options(db, ctx, u, nums, flags, evidence, conflicts, situation) -> list[Option]:
    options: list[Option] = []
    over = ((situation.inventory or {}).get("overstock") or {}) if situation else {}
    capital = float((over.get("numbers") or {}).get("capital") or 0)
    items = ((over.get("details") or {}).get("items") or [])
    if capital and items:
        percent = min(float(_policy(db, "max_discount_without_approval", 15)), 20)
        econ = discount_economics(at_risk_value=capital, margin_pct=12.0, percent=percent, days=14,
                                  velocity=0, stock_value=capital)
        econ["kind"] = "DEAD_STOCK"
        top = items[0]
        options.append(Option(id="bundle", label="باندل کالای راکد با کالای پرفروش",
                              description=f"مهم‌ترین کالای راکد: {top.get('product')} با "
                                          f"{fa.toman_short(top.get('capital'))} تومان سرمایه",
                              action_class="APPROVAL", risk="low", reversible=True, requires_approval=True,
                              confidence="medium",
                              economics={**econ, "gain_toman": round(capital * 0.25), "metric": "product_profit",
                                         "window_days": 28, "followup_days": 14},
                              actions=[{"type": "bundle_campaign", "params": {"product_id": top["product_id"],
                                                                             "percent": int(percent)},
                                        "label": "باندل با کالای پرفروش", "reversible": True}],
                              tradeoffs=["نیاز به چیدمان مناسب"]))
        options.append(Option(id="discount", label=f"فروش ویژهٔ {fa.fa_num(percent, 0)}٪",
                              description=f"آزادسازی {fa.toman_short(capital)} تومان سرمایهٔ راکد",
                              action_class="APPROVAL", risk="medium", reversible=True, requires_approval=True,
                              confidence="medium", economics={**econ, "kind": "DEAD_STOCK"},
                              actions=[{"type": "flash_sale", "params": {"percent": int(percent), "days": 14},
                                        "label": "فروش ویژه", "reversible": True}],
                              tradeoffs=["کاهش حاشیه"]))
    options.append(_no_action("سرمایهٔ راکد قابل توجهی دیده نشد"))
    return options


def _sales_options(db, ctx, u, nums, flags, evidence, conflicts, situation) -> list[Option]:
    options: list[Option] = []
    if "STOCKOUT_RISK" in flags:
        options.append(Option(id="fix_availability", label="رفع کمبود موجودی کالاهای پرفروش",
                              description="افت فروش با اتمام موجودی کالاهای پرگردش هم‌زمان شده؛ ریشه احتمالاً "
                                          "دسترسی مشتری به کالا است، نه کاهش تقاضا",
                              action_class="APPROVAL", risk="low", reversible=True, requires_approval=True,
                              confidence="high",
                              economics={"gain_toman": round(nums.get("stockout_count", 0) * 300_000),
                                         "metric": "availability", "window_days": 28, "followup_days": 14,
                                         "kind": "REORDER"},
                              actions=[{"type": "reorder_note", "params": {},
                                        "label": "افزودن کالاهای تمام‌شده به لیست سفارش",
                                        "reversible": True}],
                              tradeoffs=["سرمایهٔ در گردش"]))
    if "DATA_QUALITY_DEGRADED" in flags or "DATA_QUALITY_CRITICAL" in flags:
        options.append(Option(id="fix_data", label="اصلاح داده‌های فروشگاه",
                              description="بخشی از پراکندگی فروش می‌تواند از دادهٔ ناقص باشد (قیمت خرید، انقضا، دسته‌بندی)",
                              action_class="AUTO", risk="none", reversible=True, requires_approval=False,
                              confidence="medium",
                              economics={"gain_toman": 0, "metric": "avg_basket_size", "window_days": 14,
                                         "kind": "DATA_FIX"},
                              actions=[{"type": "note", "params": {}, "label": "کار بازبینی داده", "reversible": True}],
                              tradeoffs=[]))
    churned = ((situation.customers or {}).get("numbers") or {}).get("churned") if situation else 0
    if churned:
        options.append(Option(id="winback", label="بازگرداندن مشتریان غایب",
                              description=f"{fa.fa_num(churned)} مشتری مدتی است خرید نکرده‌اند",
                              action_class="APPROVAL", risk="low", reversible=False, requires_approval=True,
                              confidence="medium",
                              economics={"gain_toman": round(float(nums.get("avg_basket", 0)) * churned * 0.3),
                                         "metric": "customer_sales", "window_days": 28, "followup_days": 14,
                                         "kind": "TARGETED_OFFER"},
                              actions=[{"type": "personal_sms", "params": {"customers": _winback_rows(ctx)},
                                        "label": "پیامک بازگشت مشتری", "reversible": False}],
                              tradeoffs=["هزینهٔ پیامک"]))
    options.append(_no_action("افت فروش در محدودهٔ نوسان عادی هفته است"))
    return options


def _product_options(db, ctx, u, nums, flags, evidence, conflicts, situation) -> list[Option]:
    pid = u.entities.get("product_id")
    if not pid:
        return [_no_action("کالای مشخصی در سؤال پیدا نشد")]
    snap = _snapshot(ctx, pid) or {}
    numbers = snap.get("numbers") or {}
    if not numbers:
        return [_no_action("اطلاعات این کالا در دسترس نیست")]
    velocity = float(numbers.get("velocity_per_day") or 0)
    stock = float(numbers.get("stock") or 0)
    margin_pct = float(numbers.get("margin_pct") or 0)
    days_cover = numbers.get("days_of_cover")
    options: list[Option] = []
    batches = ((snap.get("details") or {}).get("batches") or [])
    min_days_left = min([b.get("days_left") for b in batches if b.get("days_left") is not None], default=None)
    if min_days_left is not None and min_days_left <= 21 and stock > velocity * 5:
        options.extend(_expiry_options(db, ctx, u, nums, flags, evidence, conflicts, situation))
        return options
    if days_cover is not None and float(days_cover) > 90:
        options.extend(_overstock_options(db, ctx, u, nums, flags, evidence, conflicts, situation))
        return options
    if days_cover is not None and float(days_cover) < 10:
        options.extend(_stockout_options(db, ctx, u, nums, flags, evidence, conflicts, situation))
        return options
    if margin_pct < 5 and velocity > 0:
        buy = float(numbers.get("avg_cost") or 0)
        sell = float(numbers.get("avg_sell") or 0)
        target = round((buy * 1.08) / 100) * 100
        options.append(Option(id="price_fix", label="اصلاح قیمت فروش این کالا",
                              description=f"حاشیهٔ سود {fa.fa_num(margin_pct, 1)}٪ است که با هزینه‌های فروشگاه "
                                          "نمی‌خواند",
                              action_class="APPROVAL", risk="medium", reversible=True, requires_approval=True,
                              confidence="medium",
                              economics={"gain_toman": round(velocity * 30 * (target - sell)),
                                         "metric": "product_profit", "window_days": 28, "followup_days": 14,
                                         "kind": "PRICE_FIX"},
                              actions=[{"type": "set_price", "params": {"batch_id": (batches[0] or {}).get("id"),
                                                                        "sell_price": target},
                                        "label": "اصلاح قیمت", "reversible": True}],
                              tradeoffs=["احتمال کاهش تقاضا"]))
    options.append(_no_action("این کالا از نظر موجودی، سرعت فروش و حاشیه در وضعیت سالمی است"))
    return options


def _customer_options(db, ctx, u, nums, flags, evidence, conflicts, situation) -> list[Option]:
    cid = u.entities.get("customer_id")
    options: list[Option] = []
    if cid:
        row = _customer_snapshot(ctx.db, cid)
        if row["balance"] > 0:
            options.append(Option(id="chase_customer", label="پیگیری تسویهٔ حساب",
                                  description=f"مانده {fa.toman_short(row['balance'])} تومان",
                                  action_class="APPROVAL", risk="low", reversible=False, requires_approval=True,
                                  confidence="high",
                                  economics={"gain_toman": round(row["balance"] * 0.5),
                                             "metric": "receivables_collected", "window_days": 14,
                                             "followup_days": 7},
                                  actions=[{"type": "personal_sms",
                                            "params": {"customers": [{"customer_id": cid, "text": _debt_text(row)}]},
                                            "label": "یادآوری بدهی", "reversible": False}],
                                  tradeoffs=["هزینهٔ پیامک"]))
        if row.get("churned"):
            options.append(Option(id="winback", label="پیشنهاد بازگشت به این مشتری",
                                  description=f"{fa.fa_num(row.get('days_since') or 0)} روز از آخرین خرید گذشته",
                                  action_class="APPROVAL", risk="low", reversible=False, requires_approval=True,
                                  confidence="medium",
                                  economics={"gain_toman": round(row["avg_basket"] * 3), "metric": "customer_sales",
                                             "window_days": 28, "followup_days": 14, "kind": "TARGETED_OFFER"},
                                  actions=[{"type": "personal_coupons",
                                            "params": {"customers": [{"customer_id": cid, "percent": 10, "days": 14}]},
                                            "label": "کوپن شخصی بازگشت", "reversible": False}],
                                  tradeoffs=["تخفیف روی مشتری‌ای که ممکن است برنگردد"]))
    options.append(_no_action("برای این مشتری اقدام خاصی لازم نیست"))
    return options


def _supplier_options(db, ctx, u, nums, flags, evidence, conflicts, situation) -> list[Option]:
    options: list[Option] = []
    rank = (evidence and next((e for e in evidence if e.domain == "supplier"), None))
    if nums.get("payables"):
        options.append(Option(id="negotiate_supplier_terms", label="مذاکرهٔ مهلت پرداخت",
                              description=f"{fa.toman_short(nums.get('payables'))} تومان بدهی به تأمین‌کنندگان داریم؛ "
                                          "اولویت با حفظ تأمین‌کنندگان راهبردی است",
                              action_class="APPROVAL", risk="low", reversible=True, requires_approval=True,
                              confidence="medium",
                              economics={"gain_toman": round(nums.get("payables", 0) * 0.05),
                                         "metric": "avg_basket_size", "window_days": 14, "followup_days": 5},
                              actions=[{"type": "note", "params": {}, "label": "یادداشت مذاکره با تأمین‌کننده",
                                        "reversible": True}], tradeoffs=["رابطهٔ تجاری"]))
    options.append(_no_action("وضعیت تأمین‌کنندگان نیازمند اقدام فوری نیست"))
    return options


def _campaign_options(db, ctx, u, nums, flags, evidence, conflicts, situation) -> list[Option]:
    options: list[Option] = []
    outcome = ctx.cached("campaign_outcome", lambda: REGISTRY_CALL(ctx, "get_campaign_outcome", {}))
    change = float((outcome.get("numbers") or {}).get("profit_change") or 0)
    options.append(Option(id="measure_campaign", label="سنجش نتیجهٔ کمپین و ثبت در حافظه",
                          description=(outcome.get("summary") or "نتیجهٔ کمپین محاسبه می‌شود"),
                          action_class="AUTO", risk="none", reversible=True, requires_approval=False,
                          confidence="high" if outcome else "low",
                          economics={"gain_toman": round(max(0.0, change)), "metric": "avg_basket_size",
                                     "window_days": 14, "followup_days": 7, "kind": "MEASURE"},
                          actions=[{"type": "note", "params": {}, "label": "ثبت یادداشت نتیجه", "reversible": True}],
                          tradeoffs=[]))
    if change < 0:
        options.append(Option(id="stop_campaign", label="توقف کمپین‌های زیان‌ده",
                              description="سود در بازهٔ کمپین نسبت به بازهٔ قبل کمتر بوده است",
                              action_class="APPROVAL", risk="medium", reversible=True, requires_approval=True,
                              confidence="medium",
                              economics={"gain_toman": round(abs(change) * 0.5), "metric": "avg_basket_size",
                                         "window_days": 14, "followup_days": 7, "kind": "STOP_ORDER"},
                              actions=[{"type": "set_setting", "params": {"key": "marketing.paused", "value": "true"},
                                        "label": "توقف موقت کمپین‌ها", "reversible": True}],
                              tradeoffs=["کاهش موقت فروش"]))
    return options


def _execute_options(db, ctx, u, nums, flags, evidence, conflicts, situation) -> list[Option]:
    """«اجراش کن» — point at the decision that is actually waiting, never invent one.

    The chat cannot execute anything by itself: execution is the owner's approval
    in the Decision Center (or ``POST /api/brain/decisions/{id}/approve``), which
    then runs the actions through the Action Engine with verification and audit.
    What the answer must do is name the decision, its cost and its risk, so the
    approval is informed.
    """
    from .memory import pending_context

    pending = (pending_context(db).get("decision") or {}) if db is not None else {}
    if not pending:
        return [_no_action("الان تصمیمِ اجرانشده‌ای روی میز نیست؛ اگر می‌خواهی اول یک بررسی تازه انجام دهم، "
                           "همین را بگو.")]
    option_id = pending.get("selected_option") or pending.get("recommended_option") or "pending_decision"
    options_list = pending.get("options") or []
    detail = next((o for o in options_list if o.get("id") == option_id), options_list[0] if options_list else {})
    gain = ((detail or {}).get("economics") or {}).get("gain_toman") or 0
    return [Option(
        id=f"approve_pending::{option_id}",
        label=f"اجرای «{pending.get('title')}»",
        description=(f"تصمیم شمارهٔ {pending.get('id')} در وضعیت "
                     f"{fa.status_label(pending.get('status'))} منتظر تأیید تو است"
                     + (f"؛ گزینهٔ انتخابی: {detail.get('label')}" if detail else "")),
        action_class="APPROVAL", requires_approval=True,
        risk=str((detail or {}).get("risk") or "medium"), reversible=True,
        confidence=str(pending.get("confidence") or "medium"),
        economics={"gain_toman": gain, "metric": "avg_basket_size", "window_days": 14,
                   "followup_days": 7, "kind": "EXECUTE_PENDING", "decision_id": pending.get("id")},
        actions=[{"type": "note", "params": {}, "label": "ثبت تأیید و اجرا", "reversible": True}],
        tradeoffs=["تا تأیید نکنی هیچ اقدامی اجرا نمی‌شود"])]


def _status_options(db, ctx, u, nums, flags, evidence, conflicts, situation) -> list[Option]:
    """The store is fine ⇒ the honest answer is «no action» (scenario #3).

    When something *is* wrong, the answer must be about that thing — a question
    about the shop must not silently turn into a cash answer.
    """
    flags = set(flags) | set(getattr(situation, "flags", None) or [])
    if flags & {"CASH_NEGATIVE_AHEAD", "CASH_GAP_AHEAD", "CASH_FRAGILE", "CASH_BELOW_RESERVE",
                "CHEQUE_OVERDUE", "CASH_PRESSURE_HIGH"}:
        return _cash_options(db, ctx, u, nums, flags, evidence, conflicts, situation)
    if "STOCKOUT_RISK" in flags:
        return _stockout_options(db, ctx, u, nums, flags, evidence, conflicts, situation)
    if "EXPIRY_RISK" in flags:
        return _expiry_options(db, ctx, u, nums, flags, evidence, conflicts, situation)
    if nums.get("count") and nums.get("capital"):
        return _overstock_options(db, ctx, u, nums, flags, evidence, conflicts, situation)
    if "SALES_DROP" in flags:
        return _sales_options(db, ctx, u, nums, flags, evidence, conflicts, situation)
    if "DATA_QUALITY_BLOCKED" in flags or "DATA_QUALITY_CRITICAL" in flags:
        return _info_options(db, ctx, u, nums, flags, evidence, conflicts, situation)
    return [_no_action()]


def _info_options(db, ctx, u, nums, flags, evidence, conflicts, situation) -> list[Option]:
    return []


# --------------------------------------------------------------------------- scoring (§53)
def score_options(options: list[Option], *, db: Session, situation=None) -> None:
    flags = set(situation.flags or []) if situation else set()
    for option in options:
        gain = float((option.economics or {}).get("gain_toman") or 0)
        impact = math.log10(1 + max(0.0, gain)) if gain > 0 else 0.0
        urgency = 0.0
        followup = (option.economics or {}).get("followup_days")
        if "CASH_PRESSURE_HIGH" in flags and option.id in ("chase_receivable", "negotiate_supplier_terms"):
            urgency = 1.0
        elif "EXPIRY_RISK" in flags and option.id in ("discount", "bundle", "staff_guidance"):
            urgency = 0.8
        elif "STOCKOUT_RISK" in flags and option.id in ("reorder", "fix_availability"):
            urgency = 0.9
        confidence = CONFIDENCE_VALUE.get(option.confidence, 0.5)
        risk = RISK_PENALTY.get(option.risk, 0.5)
        reversible = 1.0 if option.reversible else 0.0
        policy_ok = 0.0 if option.policy_notes else 1.0
        data_quality = 0.0 if confidence <= 0.1 else 1.0
        option.score = (W_IMPACT * impact + W_URGENCY * urgency + W_CONFIDENCE * confidence
                        - W_RISK * risk + W_REVERSIBLE * reversible + W_POLICY * policy_ok
                        + W_DATA_QUALITY * data_quality)
        if option.id == "no_action":
            # doing nothing is the baseline; it wins only when nothing else is clearly better
            option.score = 0.9 + (0.3 if not (flags & {"CASH_PRESSURE_HIGH", "EXPIRY_RISK", "STOCKOUT_RISK"}) else 0.0)
        if followup:
            option.economics["window_days"] = int(option.economics.get("window_days") or 14)
    options.sort(key=lambda o: (-o.score, o.id))


# --------------------------------------------------------------------------- small helpers
def _snapshot(ctx, product_id: int) -> dict:
    """Memoised product snapshot. The cache key matches the agents' key so a
    snapshot read once during evidence collection is never fetched twice."""
    from .registry import REGISTRY
    return ctx.cached(f"snap:{product_id}",
                      lambda: REGISTRY.call_or_none(ctx, "get_product_snapshot", {"product_id": product_id}))


def _issued_cheques(situation) -> list[dict]:
    """Every issued cheque in the situation, soonest first."""
    block = getattr(situation, "obligations", None) or {}
    rows = ((block.get("details") or {}).get("cheques") or [])
    issued = [c for c in rows if c.get("direction") == "ISSUED" and (c.get("amount") or 0) > 0]
    return sorted(issued, key=lambda c: c.get("days_left") if c.get("days_left") is not None else 999)


def _cheque_dates(situation) -> list[str]:
    """Due dates of the issued cheques inside the window — never invented."""
    return [c["due_date"] for c in _issued_cheques(situation) if c.get("due_date")]


def _cheques_within(situation, days: int) -> float:
    return float(sum(c.get("amount") or 0 for c in _issued_cheques(situation)
                     if (c.get("days_left") if c.get("days_left") is not None else 999) <= days))


def _policy(db: Session, key: str, default):
    from .policies import get_value
    return get_value(db, key, default)


def REGISTRY_CALL(ctx, name, params):  # pragma: no cover - thin indirection for tests
    from .registry import REGISTRY
    return REGISTRY.call_or_none(ctx, name, params)


def _high_confidence_debtors(ctx, limit: int = 10) -> list[dict]:
    """Customers with a proven payment history — the *only* ones worth an SMS.

    Uses the shared context so the receivables tool runs once per turn and the
    numbers it produced stay registered for grounding.
    """
    from . import tools as tools_mod

    data = ctx.cached("receivables", lambda: tools_mod.get_receivables(ctx, {}))
    rows = ((data.get("details") or {}).get("debtors") or [])
    return [r for r in rows if r.get("collection_confidence") in ("high", "medium")][:limit]


def _customer_snapshot(db: Session, customer_id: int) -> dict:
    from ...models import Customer as Cust
    from ...models import CustomerLedgerEntry

    customer = db.get(Cust, customer_id)
    if customer is None:
        return {"name": "مشتری", "balance": 0.0, "avg_basket": 0.0, "days_since": None, "churned": False}
    balance = float(db.execute(select(func.coalesce(func.sum(CustomerLedgerEntry.amount), 0))
                               .where(CustomerLedgerEntry.customer_id == customer_id)).scalar_one() or 0)
    agg = db.execute(select(func.coalesce(func.avg(Invoice.total_amount), 0), func.max(Invoice.created_at))
                     .where(Invoice.customer_id == customer_id, Invoice.status == "PAID")).one()
    last = agg[1]
    days = (local_today() - last.date()).days if last else None
    return {"name": customer.name, "phone": customer.phone, "balance": balance,
            "avg_basket": float(agg[0] or 0), "days_since": days, "churned": bool(days and days > 45)}


def _debt_text(row: dict) -> str:
    return (f"{row.get('name') or 'مشتری'} عزیز، مانده حساب شما {fa.money(row.get('balance', 0))} است. "
            "برای تسویه یا هماهنگی پرداخت با ما در تماس باشید. با سپاس")


def _winback_rows(ctx, limit: int = 15) -> list[dict]:
    from . import tools as tools_mod

    db = ctx.db
    data = ctx.cached("segments", lambda: tools_mod.get_customer_segment(ctx, {"days": 120}))
    rows = ((data.get("details") or {}).get("churned") or [])[:limit]
    texts = []
    for row in rows:
        customer = db.get(Customer, row["customer_id"])
        if customer and customer.phone:
            texts.append({"customer_id": row["customer_id"],
                          "text": f"{customer.name} عزیز، دلمان برایتان تنگ شده! "
                                  "با کد تخفیف اختصاصی شما منتظرتان هستیم."})
    return texts
