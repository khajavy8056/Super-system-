"""v4.0 — the deterministic Persian answer (§20, §21, §23, §89).

This module is what makes the brain *work without a model*. Every answer the
product can give is available here, in the shape the brief asks for —
وضعیت / دلیل / پیشنهاد / اقدام بعدی — built from numbers that came out of tools.

It is also the fallback when:

* no local model is installed (offline mode on a 4 GB device),
* the model's draft contained a number no tool produced (grounding rejection),
* a tool failed and the model wanted to guess.

In all three cases the owner still gets a correct, specific answer in Persian —
just without the model's phrasing. Nothing is ever silently invented.
"""
from __future__ import annotations

from . import persian as fa


def compose(plan, question: str) -> str:
    intent = plan.understanding.intent
    if "no_data" in plan.degraded:
        return fa.NO_DATA_TEXT
    if plan.blocked:
        checks = ((plan.situation.data_quality or {}).get("details") or {}).get("checks", []) if plan.situation else []
        messages = [c.get("message") for c in checks if c.get("severity") == "CRITICAL" and c.get("count")]
        return fa.blocked_by_data_quality(messages)
    builder = {
        "CASH_CRISIS": _cash, "CHEQUE_MANAGEMENT": _cash, "RECEIVABLE": _receivable,
        "EXPIRY": _expiry, "STOCKOUT": _stockout, "OVERSTOCK": _overstock,
        "SALES_DROP": _sales, "PRODUCT_ACTION": _product, "CUSTOMER_ACTION": _customer,
        "SUPPLIER": _supplier, "CAMPAIGN_FOLLOWUP": _campaign, "DECISION_RECALL": _recall,
        "POLICY_SET": _policy, "STORE_STATUS": _status, "GENERAL": _status,
        "EXECUTE_DECISION": _execute,
    }.get(intent, _status)
    text = builder(plan, question)
    # §24 — the contradiction sentence leads the answer when two domains disagree
    if plan.contradictions:
        head = next((c for c in plan.contradictions if c.get("severity") in ("high", "critical")), None)
        if head:
            text = f"{head['statement']}\n\n{text}"
    if plan.degraded:
        text += "\n\n" + fa.degraded_notice(plan.degraded)
    return text


def _num(plan, key: str, default: float = 0.0) -> float:
    for evidence in plan.evidence:
        if key in (evidence.numbers or {}):
            return float(evidence.numbers[key])
    return default


def _situation_numbers(plan) -> dict:
    """The same numeric bag the option builders use — one implementation only."""
    from .decision_helpers import _situation_numbers as flatten

    return flatten(plan.situation)


def _proposal(plan) -> str:
    option = plan.chosen
    if option is None:
        return "پیشنهاد مشخصی ندارم."
    if option.id == "no_action":
        return option.description or "پیشنهاد می‌کنم اقدام خاصی انجام نشود."
    return option.description or option.label


def _next_step(plan) -> str:
    option = plan.chosen
    if option is None or option.id == "no_action":
        return "اگر موضوع دیگری هست بگویید؛ وگرنه همین روند را ادامه دهید."
    if option.requires_approval:
        return "اگر تأیید کنی، اقدام را ثبت و اجرا می‌کنم و نتیجه را بعداً اندازه می‌گیرم."
    return "این کار کم‌ریسک است؛ در صورت تأیید همان‌جا اجرا می‌شود و در مرکز تصمیم ثبت می‌گردد."


def _cash(plan, question: str) -> str:
    """The cash answer states the crunch by *date* and the sequencing that avoids it.

    Three shapes, in order of severity:

    * the projection goes negative — say by how much and on which day;
    * the projection survives but only under the safety buffer, or only because
      the collections land — that is the *fragile* case, and the fix is timing;
    * nothing is due — say so and stop.
    """
    nums = _situation_numbers(plan)
    available = nums.get("cash_available", 0.0)
    next7 = nums.get("issued_next_7d", 0.0)
    obligations = nums.get("issued_total", 0.0)
    reserve = nums.get("reserve_floor", 0.0)
    expected = nums.get("expected_total", 0.0)
    expected_3d = nums.get("forecast_expected_next_3d") or nums.get("expected_next_3d") or 0.0
    receivables = nums.get("receivables_total") or nums.get("total") or 0.0
    high_conf = nums.get("high_confidence", 0.0)
    min_projected = nums.get("min_projected_cash")
    min_day = nums.get("forecast_min_projected_day") or nums.get("lowest_day")
    without = nums.get("forecast_min_without_collections")
    safety = nums.get("forecast_safety_target", 0.0)
    days_below = int(nums.get("forecast_days_below_safety") or 0)
    shortfall = nums.get("shortfall", 0.0)
    cheques = _cheque_lines(plan)

    situation = f"الان {fa.money(available)} نقد و بانک در دسترس داری"
    if reserve:
        situation += f" و کف نقدینگی تعیین‌شده {fa.money(reserve)} است"
    situation += "."
    if next7:
        situation += f" تا ۷ روز آینده {fa.money(next7)} چک پرداختی داری"
        if cheques:
            first = cheques[0]
            situation += (f" که اولین آن ({first.get('number')}، {fa.money(first.get('amount'))}) "
                          f"{fa.rel_days(first.get('days_left'))} سررسید می‌شود")
        situation += "."
        if obligations and obligations != next7:
            situation += f" کل تعهدات ۳۰ روز {fa.money(obligations)} است."
    else:
        situation += " در ۷ روز آینده چک پرداختی سررسیدی ثبت نشده."

    if min_projected is not None and min_projected < 0:
        reason = (f"با احتساب {fa.money(expected)} وصول مورد انتظار از مطالبات (از مجموع "
                  f"{fa.money(receivables)})، کمترین موجودی پیش‌بینی‌شده {fa.money(min_projected)} می‌شود"
                  + (f" در {fa.fa_date(min_day)}" if min_day else "")
                  + (f"؛ یعنی حدود {fa.money(shortfall)} کسری." if shortfall else "."))
        reason += " پس مسئله کمبود کل پول نیست، زمان‌بندی ورود پول در برابر سررسید چک است."
    elif min_projected is not None and next7 > 0 and (days_below or (without is not None and without < 0)
                                                     or (safety and min_projected < safety)):
        second = cheques[1] if len(cheques) > 1 else None
        reason = (f"با احتساب {fa.money(expected)} وصول مورد انتظار، کمترین موجودی "
                  f"{fa.money(min_projected)} می‌شود"
                  + (f" در {fa.fa_date(min_day)}" if min_day else "")
                  + (f"؛ کف امن این بازه {fa.money(safety)} است و "
                     f"{fa.fa_num(days_below)} روز زیر آن قرار می‌گیرد" if safety and days_below else "")
                  + ".")
        if without is not None and without < 0:
            reason += (f" اگر وصول مطالبات چند روز عقب بیفتد، موجودی تا {fa.toman_short(abs(without))} "
                       f"تومان منفی می‌شود؛ یعنی این برنامه به وصول {fa.toman_short(expected_3d)} "
                       f"تومان در سه روز آینده وابسته است.")
        if second:
            reason += (f" چک بعدی ({second.get('number')}، {fa.money(second.get('amount'))}) "
                       f"{fa.rel_days(second.get('days_left'))} سررسید می‌شود.")
        reason += " یعنی مسئله کمبود کل پول نیست، ترتیب و زمان ورود پول است."
    elif expected:
        reason = (f"با احتساب {fa.money(expected)} وصول مورد انتظار از {fa.money(receivables)} مطالبات، "
                  "پرداخت‌های پیش‌رو از موجودی پوشش داده می‌شود؛ جای نگرانی نیست، ولی ترتیب پرداخت‌ها مهم است.")
    else:
        reason = "فعلاً جریان ورود پول مشخصی در بازهٔ آینده ثبت نشده، پس برنامه باید محافظه‌کارانه باشد."

    if high_conf:
        reason += (f" از این مبلغ، {fa.money(high_conf)} مربوط به مشتریانی است که سابقهٔ پرداخت "
                   "منظم دارند.")
    return fa.structured_answer(situation=situation, reason=reason, proposal=_proposal(plan),
                               next_step=_next_step(plan))


def _cheque_lines(plan) -> list[dict]:
    """Upcoming *issued* cheques from the situation, soonest first."""
    block = getattr(plan.situation, "obligations", None) or {}
    rows = ((block.get("details") or {}).get("cheques") or [])
    issued = [c for c in rows if c.get("direction") == "ISSUED" and (c.get("amount") or 0) > 0]
    return sorted(issued, key=lambda c: (c.get("days_left") if c.get("days_left") is not None else 999))


def _execute(plan, question: str) -> str:
    """«اجراش کن» — say exactly what will run, and that approval is the switch."""
    option = plan.chosen
    nums = _situation_numbers(plan)
    if option is None or option.id == "no_action":
        return fa.structured_answer(
            situation="تصمیم اجرانشده‌ای روی میز نیست.",
            reason="اجرا فقط روی تصمیمی انجام می‌شود که قبلاً بررسی و ثبت شده باشد؛ "
                   "تا تأیید تو هیچ اقدامی خودسرانه اجرا نمی‌شود.",
            proposal=_proposal(plan),
            next_step="اگر بخواهی همین حالا بررسی تازه‌ای برای موضوع مورد نظرت انجام می‌دهم.")
    decision_id = option.economics.get("decision_id")
    risk = {"low": "کم", "medium": "متوسط", "high": "بالا"}.get(option.risk, "متوسط")
    situation = f"تصمیم «{option.label}»"
    if decision_id:
        situation += f" (شمارهٔ {fa.fa_num(decision_id, 0)})"
    situation += " آمادهٔ اجراست."
    reason = (f"ریسک این اقدام {risk} است و اثر تخمینی آن "
              f"{fa.money(option.economics.get('gain_toman', 0))} در بازهٔ "
              f"{fa.fa_num(option.economics.get('window_days', 14), 0)} روز سنجیده می‌شود"
              + (f"؛ {option.description}" if option.description else "")
              + ". پس از اجرا نتیجه در همان بازه اندازه‌گیری و در حافظه ثبت می‌شود.")
    if nums.get("forecast_days_below_safety"):
        reason += " تا آن زمان، پرداخت‌های سررسیدشده اولویت دارند."
    return fa.structured_answer(situation=situation, reason=reason, proposal=_proposal(plan),
                               next_step="برای اجرا، در مرکز تصمیم دکمهٔ «اجرا» را بزن؛ "
                                         "از همین گفت‌وگو هیچ اقدامی بدون تأیید تو اجرا نمی‌شود.")


def _receivable(plan, question: str) -> str:
    nums = _situation_numbers(plan)
    situation = (f"جمع مطالبات فروشگاه {fa.money(nums.get('total', 0))} است؛ "
                 f"{fa.money(nums.get('high_confidence', 0))} آن مربوط به مشتریانی است که سابقهٔ پرداخت "
                 "منظم دارند.")
    reason = ("پول طلب‌شده سرمایهٔ خود فروشگاه است؛ با یک یادآوری محترمانه معمولاً بدون هزینهٔ تخفیف برمی‌گردد.")
    return fa.structured_answer(situation=situation, reason=reason, proposal=_proposal(plan),
                                next_step=_next_step(plan))


def _expiry(plan, question: str) -> str:
    nums = _situation_numbers(plan)
    value = nums.get("at_risk_value", 0.0) or nums.get("value", 0.0)
    count = nums.get("batches", nums.get("count", 0))
    product = plan.understanding.entities.get("product_name")
    if product:
        situation = (f"دربارهٔ «{product}»: موجودی {fa.fa_num(nums.get('stock', 0), 1)} و سرعت فروش "
                     f"{fa.fa_num(nums.get('velocity_per_day', 0), 2)} در روز؛ حاشیهٔ سود "
                     f"{fa.fa_num(nums.get('margin_pct', 0), 1)}٪.")
    else:
        situation = (f"{fa.fa_num(count)} گروه کالا نزدیک انقضاست و حدود {fa.money(value)} از آن "
                     "با سرعت فروش فعلی پیش از موعد فروش نمی‌رود.")
    reason = ("تخفیف تنها گزینه نیست: اول باید حاشیهٔ سود، سرعت فروش و امکان مرجوعی بررسی شود؛ "
              "اگر کالا با سرعت فعلی می‌فروشد، هیچ اقدامی لازم نیست.")
    return fa.structured_answer(situation=situation, reason=reason, proposal=_proposal(plan),
                               next_step=_next_step(plan))


def _stockout(plan, question: str) -> str:
    nums = _situation_numbers(plan)
    product = plan.understanding.entities.get("product_name")
    if product:
        situation = (f"«{product}» حدود {fa.fa_num(nums.get('days_of_cover', 0), 1)} روز دیگر تمام می‌شود "
                     f"(سرعت فروش {fa.fa_num(nums.get('velocity_per_day', 0), 2)} در روز).")
    else:
        situation = f"{fa.fa_num(nums.get('count', 0))} قلم کالا در خطر اتمام موجودی است."
    reason = "هر روز نبودن کالای پرگردش، هم فروش آن روز و هم خرید همراه آن را از دست می‌دهد."
    return fa.structured_answer(situation=situation, reason=reason, proposal=_proposal(plan),
                               next_step=_next_step(plan))


def _overstock(plan, question: str) -> str:
    nums = _situation_numbers(plan)
    situation = (f"{fa.money(nums.get('capital', 0))} سرمایه در کالاهای کند-فروش/راکد قفل شده است "
                 f"({fa.fa_num(nums.get('count', 0))} قلم).")
    reason = "این پول می‌تواند به کالای پرگردش تبدیل شود؛ راه‌حل فقط تخفیف نیست."
    return fa.structured_answer(situation=situation, reason=reason, proposal=_proposal(plan),
                               next_step=_next_step(plan))


def _sales(plan, question: str) -> str:
    nums = _situation_numbers(plan)
    change = nums.get("change_pct", 0.0)
    situation = (f"فروش {fa.fa_num(nums.get('window_days', 7))} روز گذشته "
                 f"{fa.money(nums.get('revenue', nums.get('sales_7d', 0)))} بوده و نسبت به بازهٔ قبل "
                 f"{fa.fa_num(change, 1)}٪ تغییر کرده؛ سود این بازه {fa.money(nums.get('profit', 0))} است.")
    reason = ("افت فروش معمولاً از سه جا می‌آید: نبود کالای پرگردش، کاهش مشتریان فعال، یا دادهٔ ناقص. "
              "بررسی‌ها نشان می‌دهد کدام‌یک در فروشگاه شما نقش دارد.")
    return fa.structured_answer(situation=situation, reason=reason, proposal=_proposal(plan),
                               next_step=_next_step(plan))


def _product(plan, question: str) -> str:
    nums = _situation_numbers(plan)
    name = plan.understanding.entities.get("product_name") or "این کالا"
    situation = (f"«{name}»: موجودی {fa.fa_num(nums.get('stock', 0), 1)}، سرعت فروش "
                 f"{fa.fa_num(nums.get('velocity_per_day', 0), 2)} در روز، حاشیهٔ سود "
                 f"{fa.fa_num(nums.get('margin_pct', 0), 1)}٪.")
    reason = "این اعداد تعیین می‌کنند که گزینهٔ درست تخفیف است، سفارش مجدد، اصلاح قیمت یا هیچ‌کدام."
    return fa.structured_answer(situation=situation, reason=reason, proposal=_proposal(plan),
                               next_step=_next_step(plan))


def _customer(plan, question: str) -> str:
    nums = _situation_numbers(plan)
    name = plan.understanding.entities.get("customer_name") or "این مشتری"
    situation = (f"«{name}»: مانده حساب {fa.money(nums.get('balance', 0))}، "
                 f"{fa.fa_num(nums.get('invoices', 0))} خرید ثبت‌شده"
                 + (f"، آخرین خرید {fa.fa_num(nums.get('days_since_last_purchase', 0))} روز پیش"
                    if nums.get("days_since_last_purchase") is not None else "") + ".")
    reason = "تصمیم دربارهٔ یک مشتری باید هم‌زمان سود و ریسک اعتباری او را ببیند."
    return fa.structured_answer(situation=situation, reason=reason, proposal=_proposal(plan),
                               next_step=_next_step(plan))


def _supplier(plan, question: str) -> str:
    nums = _situation_numbers(plan)
    situation = (f"بدهی ثبت‌شده به تأمین‌کنندگان {fa.money(nums.get('payables', 0))} است"
                 + (f" و {fa.money(nums.get('cheques_pending', 0))} چک پرداختی در جریان داریم"
                    if nums.get("cheques_pending") else "") + ".")
    reason = "اولویت پرداخت باید با اهمیت رابطه و اندازهٔ ریسک قطع تأمین تعیین شود، نه فقط با سررسید."
    return fa.structured_answer(situation=situation, reason=reason, proposal=_proposal(plan),
                               next_step=_next_step(plan))


def _campaign(plan, question: str) -> str:
    nums = _situation_numbers(plan)
    change = nums.get("revenue_change_pct")
    situation = (f"کمپین قبلی: فروش {fa.money(nums.get('revenue_during', 0))} در بازهٔ اجرا در برابر "
                 f"{fa.money(nums.get('revenue_before', 0))} در بازهٔ قبل"
                 + (f" ({fa.fa_num(change, 1)}٪)" if change is not None else "") + ".")
    reason = ("نتیجهٔ واقعی کمپین را فقط با مقایسهٔ سود بازهٔ اجرا با بازهٔ قبل می‌توان گفت؛ "
              f"تغییر سود: {fa.money(nums.get('profit_change', 0))}.")
    return fa.structured_answer(situation=situation, reason=reason, proposal=_proposal(plan),
                               next_step=_next_step(plan))


def _recall(plan, question: str) -> str:
    decisions = []
    for evidence in plan.evidence:
        numbers = evidence.numbers or {}
        if "count" in numbers:
            decisions.append(numbers["count"])
    rows = []
    for option in plan.options:
        pass
    summary = "تصمیم‌های ثبت‌شده را از حافظه خواندم"
    detail = _recall_detail(plan)
    situation = detail or "در حافظهٔ تصمیم‌ها موردی که دقیقاً به این سؤال بخورد پیدا نشد."
    reason = ("اگر تصمیمی اجرا شده باشد، نتیجه‌اش با اندازه‌گیری واقعی (مقایسهٔ بازهٔ قبل و بعد) ثبت می‌شود؛ "
              "اگر اندازه‌گیری نشده باشد، صریح همان را می‌گویم.")
    return fa.structured_answer(situation=situation, reason=reason, proposal=summary,
                               next_step="اگر بخواهی، برای همین موضوع یک پیگیری زمان‌دار می‌سازم.")


def _recall_detail(plan) -> str:
    lines = []
    for evidence in plan.evidence:
        for note in (evidence.sources or []):
            pass
    # the tools already logged their results into the plan's evidence; the chat
    # layer prints the decision list itself when asked for it.
    for evidence in plan.evidence:
        if evidence.domain == "operations" and evidence.summary:
            lines.append(evidence.summary)
    return "؛ ".join(lines)


def _policy(plan, question: str) -> str:
    policies = []
    for evidence in plan.evidence:
        for check in (evidence.numbers or {}):
            policies.append(check)
    situation = "سیاست‌های فروشگاه را خواندم و از این پس تصمیم‌ها را با همان‌ها می‌سنجم."
    reason = ("سیاست‌ها جای سلیقهٔ مدل را می‌گیرند: سقف تخفیف بدون تأیید، کف نقدینگی و اولویت تأمین‌کننده "
              "به‌صورت عدد ذخیره می‌شوند.")
    return fa.structured_answer(situation=situation, reason=reason,
                               proposal="اگر بگویی چه قانونی می‌خواهی، همان را ثبت می‌کنم.",
                               next_step="قانون جدید را در تنظیمات هوش فروشگاه هم می‌توانی ویرایش کنی.")


def _status(plan, question: str) -> str:
    nums = _situation_numbers(plan)
    flags = set(plan.situation.flags or []) if plan.situation else set()
    situation = (f"نقدینگی {fa.money(nums.get('cash_available', 0))}، فروش ۷ روز "
                 f"{fa.money(nums.get('revenue', nums.get('sales_7d', 0)))}، ارزش موجودی "
                 f"{fa.money(nums.get('stock_value', 0))}.")
    notable = flags & {"CASH_PRESSURE_HIGH", "CASH_GAP_AHEAD", "CASH_FRAGILE", "CASH_NEGATIVE_AHEAD",
                       "CASH_BELOW_RESERVE", "EXPIRY_RISK", "STOCKOUT_RISK", "SALES_DROP",
                       "CHEQUE_OVERDUE", "DATA_QUALITY_CRITICAL", "DATA_QUALITY_BLOCKED"}
    if not notable:
        return fa.NO_ACTION_TEXT + "\n\n" + situation
    # only the flags a manager can act on, in their own words — never the internal codes
    reason = "چند نشانهٔ قابل بررسی وجود دارد: " + "، ".join(_flag_fa(f) for f in sorted(notable)) + "."
    return fa.structured_answer(situation=situation, reason=reason, proposal=_proposal(plan),
                               next_step=_next_step(plan))


FLAG_FA = {
    "CASH_PRESSURE_HIGH": "فشار نقدینگی",
    "CASH_GAP_AHEAD": "احتمال کسری نقدی در روزهای آینده",
    "CASH_FRAGILE": "نازک بودن حاشیهٔ نقدی اگر وصول مطالبات عقب بیفتد",
    "CASH_NEGATIVE_AHEAD": "منفی شدن موجودی در روزهای آینده",
    "CASH_BELOW_RESERVE": "موجودی زیر کف نقدینگی",
    "EXPIRY_RISK": "کالای نزدیک انقضا",
    "STOCKOUT_RISK": "خطر اتمام موجودی",
    "SALES_DROP": "افت فروش",
    "CHEQUE_OVERDUE": "چک سررسیدگذشته",
    "FOLLOWUP_OVERDUE": "پیگیری عقب‌افتاده",
    "DATA_QUALITY_BLOCKED": "مشکل بحرانی در داده‌ها",
    "DATA_QUALITY_CRITICAL": "خطای مهم در داده‌ها",
    "DATA_QUALITY_DEGRADED": "نقص جزئی در داده‌ها",
}


def _flag_fa(flag: str) -> str:
    return FLAG_FA.get(flag, flag)
