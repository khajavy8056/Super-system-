"""v4.0 — the reasoning loop (§15, §24, §49).

Order of operations for every request:

    1. understand the request      (intent + entities, with conversation continuity)
    2. build the relevant state    (situation + only the tools this intent needs)
    3. collect specialist evidence (agents per domain)
    4. find contradictions         (inventory says buy, finance says there is no cash)
    5. build options               (deterministic economics for each)
    6. evaluate and choose         (impact, urgency, risk, policy, data quality)
    7. propose a decision          (persisted, with a measurement contract)
    8. phrase the answer           (local model if present — grounded, else deterministic)
    9. remember                    (conversation + decision + follow-ups)

Steps 1–7 and 9 are **pure deterministic code**. A language model only ever
touches step 8, and only through ``grounding.py``. That is what makes the same
question produce different, correct answers for two different shops
(acceptance scenario #2) and makes «چرا؟» answerable with real numbers.
"""
from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ...models import Customer, Product, ProductBatch, Supplier, User
from ..timeservice import local_today
from . import agents as agents_mod
from . import persian as fa
from . import prompts
from . import store_profile
from .context import ToolContext
from .decision_helpers import build_options, contradictions, score_options
from .decisions import build_measurement, create as create_decision
from .grounding import verify as verify_numbers
from .memory import conversation_digest, decision_to_dict, last_user_intent, log_message, pattern_for
from .policies import action_requires_approval, check_cash, check_discount, get_value
from .registry import REGISTRY
from .situation import build as build_situation, summary_for_prompt

log = logging.getLogger("supermarket.brain.planner")

#: intents the brain distinguishes. Kept small on purpose: a fuzzy classifier
#: on top of a small model would be another place to lose the plot.
INTENTS = ("CASH_CRISIS", "CHEQUE_MANAGEMENT", "RECEIVABLE", "EXPIRY", "STOCKOUT", "OVERSTOCK", "SALES_DROP",
           "PRODUCT_ACTION", "CUSTOMER_ACTION", "SUPPLIER", "CAMPAIGN_FOLLOWUP", "DECISION_RECALL",
           "STORE_STATUS", "POLICY_SET", "EXECUTE_DECISION", "GENERAL")

#: plain-language kinds stored on the decision row (grouping + pattern memory)
KIND_BY_INTENT = {
    "CASH_CRISIS": "cash", "CHEQUE_MANAGEMENT": "cash", "RECEIVABLE": "receivables",
    "EXPIRY": "expiry", "STOCKOUT": "stockout", "OVERSTOCK": "overstock", "SALES_DROP": "sales",
    "PRODUCT_ACTION": "product", "CUSTOMER_ACTION": "customer", "SUPPLIER": "supplier",
    "CAMPAIGN_FOLLOWUP": "campaign", "STORE_STATUS": "status", "GENERAL": "general",
    "EXECUTE_DECISION": "execution",
}
TITLE_BY_INTENT = {
    "CASH_CRISIS": "برنامهٔ نقدینگی فروشگاه", "CHEQUE_MANAGEMENT": "مدیریت سررسید چک‌ها",
    "RECEIVABLE": "وصول مطالبات", "EXPIRY": "کالاهای نزدیک انقضا", "STOCKOUT": "خطر اتمام موجودی",
    "OVERSTOCK": "سرمایهٔ راکد", "SALES_DROP": "روند فروش", "PRODUCT_ACTION": "تصمیم کالا",
    "CUSTOMER_ACTION": "تصمیم مشتری", "SUPPLIER": "تصمیم تأمین‌کننده", "CAMPAIGN_FOLLOWUP": "نتیجهٔ کمپین",
    "STORE_STATUS": "وضعیت فروشگاه", "GENERAL": "بررسی وضعیت فروشگاه",
    "EXECUTE_DECISION": "اجرای تصمیم در انتظار تأیید",
}

#: which read tools each intent needs. The brain never runs the whole tool list.
INTENT_TOOLS: dict[str, tuple[tuple[str, dict], ...]] = {
    "CASH_CRISIS": (("get_cash_position", {}), ("get_upcoming_cheques", {"days": 30}),
                    ("get_receivables", {}), ("get_expected_collections", {"days": 14}),
                    ("get_cash_forecast", {"days": 14}), ("get_payables", {}),
                    ("get_expenses", {"days": 30})),
    "CHEQUE_MANAGEMENT": (("get_upcoming_cheques", {"days": 30}), ("get_cash_position", {}),
                          ("get_expected_collections", {"days": 14}), ("get_payables", {}),
                          ("get_cash_forecast", {"days": 14})),
    "RECEIVABLE": (("get_receivables", {}), ("get_expected_collections", {"days": 14}),
                   ("get_cash_position", {})),
    "EXPIRY": (("get_expiry_risk", {"days": 30}), ("get_cash_position", {}), ("get_active_campaigns", {})),
    "STOCKOUT": (("get_stockout_risk", {"days": 14}), ("get_sales_trend", {"days": 7}), ("get_cash_position", {})),
    "OVERSTOCK": (("get_overstock", {}), ("get_cash_position", {}), ("get_active_campaigns", {})),
    "SALES_DROP": (("get_sales_trend", {"days": 7}), ("get_customer_segment", {}), ("get_stockout_risk", {"days": 14}),
                   ("get_data_quality", {})),
    "PRODUCT_ACTION": (("get_cash_position", {}), ("get_active_campaigns", {}), ("get_business_policies", {})),
    "CUSTOMER_ACTION": (("get_customer_segment", {}), ("get_active_campaigns", {})),
    "SUPPLIER": (("get_payables", {}), ("get_cash_position", {}), ("get_upcoming_cheques", {"days": 30})),
    # «جشنوارهٔ قبلی جواب داد؟» is a question about a FINISHED campaign, so the plan
    # has to read the outcome (latest campaign, real before/during windows) — the
    # active-campaign list alone would always answer «کمپینی ثبت نشده».
    "CAMPAIGN_FOLLOWUP": (("get_campaign_outcome", {}), ("get_active_campaigns", {}),
                          ("get_sales_trend", {"days": 14})),
    "DECISION_RECALL": (("get_recent_decisions", {"limit": 10}), ("get_open_followups", {})),
    "STORE_STATUS": (("get_cash_position", {}), ("get_sales_trend", {"days": 7}), ("get_inventory_summary", {}),
                     ("get_data_quality", {})),
    "EXECUTE_DECISION": (("get_recent_decisions", {"limit": 5}), ("get_open_followups", {})),
    "GENERAL": (("get_cash_position", {}), ("get_sales_trend", {"days": 7}), ("get_open_followups", {})),
}

#: words → intent. Persian phrasing first, with the shop's own vocabulary.
INTENT_PATTERNS: tuple[tuple[str, str], ...] = (
    # «اجراش کن» is about a decision already on the owner's desk — it never starts
    # a new analysis, so it is matched before everything else.
    (r"اجراش کن|اجرا کن|اجراش کنیم|همینو اجرا|انجامش بده|تأییدش کن|تاییدش کن|قبولش کن", "EXECUTE_DECISION"),
    (r"چک|برات|سررسید", "CHEQUE_MANAGEMENT"),
    (r"پول(?:م)?\s*(?:کم|نیست|نمی)|چقدر پول لازم|پول لازم دار|نقدینگی|کسری|کمبود پول|پرداخت", "CASH_CRISIS"),
    (r"طلب|وصول|بدهکار|مطالبات|پولم را", "RECEIVABLE"),
    # the owner says «کدوم کالا داره خراب می‌شه؟» far more often than «انقضا» —
    # a question the brain must recognise in the words people actually use.
    (r"انقضا|تاریخ\s?(?:مصرف|انقضا)|منقضی|خراب|فاسد|کپک|بو گرفته|تاریخ گذشته|دیت|expire",
     "EXPIRY"),
    (r"تمام می‌شود|تمام شد|تموم می‌?شه|ته می‌?کشه|کمبود موجودی|سفارش بدم|stockout|اتمام", "STOCKOUT"),
    (r"راکد|نمی‌فروشد|کند-?فروش|انبار پر|اشباع", "OVERSTOCK"),
    (r"فروش (?:چرا )?(?:افت|کم)|افت فروش|کم شده فروش|روند فروش", "SALES_DROP"),
    (r"تأمین‌?کننده|تامین ?کننده|فروشنده|تسویه", "SUPPLIER"),
    (r"جشنواره|کمپین|تخفیف|تخفیف بدم|کمپین قبلی|جشنواره قبل", "CAMPAIGN_FOLLOWUP"),
    (r"تصمیم|قبلاً چی شد|قبلا چی شد|یادت هست|پیگیری", "DECISION_RECALL"),
    (r"سیاست|قانون فروشگاه|قرار ما|از این به بعد", "POLICY_SET"),
    (r"چه خبر|وضعیت|امروز چه|گزارش|خوب(?:ه| است)\?|چطور(?:ه| است)", "STORE_STATUS"),
)

PRODUCT_HINTS = (r"این کالا", r"همین کالا", r"این محصول", r"همون کالا", r"این جنس", r"برای این")


# --------------------------------------------------------------------------- understanding
@dataclass
class Understanding:
    intent: str
    entities: dict = field(default_factory=dict)
    reason: str = ""
    continuity: bool = False


def detect_intent(text: str, entities: dict, prior: dict | None = None) -> str:
    blob = text or ""
    for pattern, intent in INTENT_PATTERNS:
        if re.search(pattern, blob):
            return intent
    if entities.get("product_id") and re.search(r"چیکار|چه کار|چی کار|اقدام|بکنیم|کنیم|بذاریم|بگذاریم", blob):
        return "PRODUCT_ACTION"
    if entities.get("customer_id"):
        return "CUSTOMER_ACTION"
    if prior and prior.get("meta", {}).get("intent") and _is_followup(blob):
        return prior["meta"]["intent"]
    return "GENERAL"


def _is_followup(text: str) -> bool:
    return bool(re.search(r"^\s*(خب|پس|آره|بله|باشه|همون|همان|این|ادامه|بعد)|کوتاه‌تر|بیشتر توضیح|چرا", text or ""))


def extract_entities(db: Session, ctx: ToolContext, text: str, prior: dict | None = None) -> dict:
    """Deterministic entity resolution — ids, numbers and the «این» of last turn."""
    out: dict = {}
    blob = text or ""
    # percentages and durations
    for match in re.finditer(r"([۰-۹0-9]{1,3})\s*(?:٪|درصد)", blob):
        out["percent"] = int(match.group(1).translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")))
    for match in re.finditer(r"([۰-۹0-9]{1,3})\s*روز", blob):
        out["days"] = int(match.group(1).translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")))
    ids = [int(m) for m in re.findall(r"#(\d+)", blob)]
    if ids:
        out["explicit_id"] = ids[0]
    # explicit product id / barcode
    for match in re.finditer(r"(?:کالا|محصول|کد|بارکد)\s*[:#]?\s*(\d{3,14})", blob):
        value = match.group(1)
        product = db.execute(select(Product).where(Product.barcode == value)).scalar_one_or_none()
        if product:
            out["product_id"] = product.id
            out["product_name"] = product.name
            break
    # product by name (longest match wins; Persian text, so substring search is honest here)
    if "product_id" not in out:
        candidates = db.execute(select(Product.id, Product.name).where(Product.is_active == True,  # noqa: E712
                                                                     Product.deleted_at.is_(None))).all()
        best = None
        for pid, name in candidates:
            if not name:
                continue
            core = name.strip()
            if len(core) >= 3 and core in blob and (best is None or len(core) > best[2]):
                best = (pid, core, len(core))
        if best:
            out["product_id"], out["product_name"] = best[0], best[1]
    # customer by name
    customers = db.execute(select(Customer.id, Customer.name).where(Customer.is_active == True)).all()  # noqa: E712
    for cid, name in customers:
        if name and len(name) >= 3 and name in blob:
            out["customer_id"], out["customer_name"] = cid, name
            break
    suppliers = db.execute(select(Supplier.id, Supplier.name).where(Supplier.is_active == True)).all()  # noqa: E712
    for sid, name in suppliers:
        if name and len(name) >= 3 and name in blob:
            out["supplier_id"], out["supplier_name"] = sid, name
            break
    # conversation continuity: «این کالا» / «پس اجراش کن» point at last turn's entities
    if prior and not out.get("product_id") and _needs_prior(blob):
        meta = (prior.get("meta") or {})
        # the assistant row stores its resolved entities under "meta.entities";
        # older/partial rows may keep them flat, so accept both
        source = meta.get("entities") if isinstance(meta.get("entities"), dict) else meta
        for key in ("product_id", "product_name", "customer_id", "supplier_id", "percent", "days"):
            if source.get(key) is not None and key not in out:
                out[key] = source[key]
        out["_continuity"] = True
    return out


def _needs_prior(text: str) -> bool:
    """Is this turn still about the previous turn's subject?

    True for pronouns («این کالا»، «همون»), for execution («اجراش کن») **and** for a
    bare duration or percentage answer («۵ روز»، «۱۰ درصد») — the three shapes of
    turn 2 and 3 in the brief's continuity scenario.
    """
    blob = text or ""
    if re.search(r"|".join(PRODUCT_HINTS) + r"|اجراش|اجرا کن|همون|همان|همین|کدوم|چند روز|چند درصد|بزنیم|بدم|بدیم",
                 blob):
        return True
    return bool(re.fullmatch(r"\s*[۰-۹0-9]{1,4}\s*(?:روز|٪|درصد|تومان|میلیون)?\s*[.!؟]?\s*", blob))


def understand(db: Session, ctx: ToolContext, question: str, *, session_key: str = "default") -> Understanding:
    prior = last_user_intent(db, session_key=session_key) or None
    entities = extract_entities(db, ctx, question, prior)
    intent = detect_intent(question, entities, prior)
    return Understanding(intent=intent, entities=entities,
                         reason="تشخیص بر اساس کلیدواژه‌ها و داده‌های همین فروشگاه",
                         continuity=bool(entities.get("_continuity")))


# --------------------------------------------------------------------------- evidence & options
@dataclass
class Plan:
    understanding: Understanding
    situation: object | None = None
    evidence: list = field(default_factory=list)
    contradictions: list = field(default_factory=list)
    options: list = field(default_factory=list)
    chosen: object | None = None
    decision: dict | None = None
    policy_verdict: dict = field(default_factory=dict)
    degraded: list = field(default_factory=list)
    followups: list = field(default_factory=list)
    deterministic_text: str = ""
    title: str = ""
    problem: str = ""
    decision_kind: str = ""
    blocked: bool = False


def gather_evidence(db: Session, ctx: ToolContext, u: Understanding, situation=None) -> list:
    domains = agents_mod.INTENT_AGENTS.get(u.intent, ("operations",))
    out = []
    for domain in domains:
        try:
            evidence = agents_mod.collect(domain, ctx, question="", entities=u.entities)
        except Exception:  # noqa: BLE001 — one broken domain must not kill the answer
            log.exception("agent %s failed", domain)
            continue
        if evidence.summary or evidence.numbers:
            out.append(evidence)
    return out


def analyse(db: Session, ctx: ToolContext, question: str, *, session_key: str = "default",
            situation=None) -> Plan:
    u = understand(db, ctx, question, session_key=session_key)
    plan = Plan(understanding=u)
    # 1) the tools this intent actually needs (RBAC still applies inside the registry)
    for name, params in INTENT_TOOLS.get(u.intent, INTENT_TOOLS["GENERAL"]):
        REGISTRY.call_or_none(ctx, name, params)
    if u.entities.get("product_id"):
        REGISTRY.call_or_none(ctx, "get_product_snapshot", {"product_id": u.entities["product_id"]})
    if u.entities.get("customer_id"):
        REGISTRY.call_or_none(ctx, "get_customer_behavior", {"customer_id": u.entities["customer_id"]})
    if u.intent == "DECISION_RECALL":
        REGISTRY.call_or_none(ctx, "search_decisions", {"query": question})
    if u.intent == "EXPIRY" and u.entities.get("product_id"):
        REGISTRY.call_or_none(ctx, "get_expiry_risk", {"days": 60})
    plan.situation = situation or build_situation(db, ctx)
    # 2) specialist evidence
    plan.evidence = gather_evidence(db, ctx, u, plan.situation)
    plan.contradictions = contradictions(plan.evidence, plan.situation)
    # 3) options with deterministic economics
    plan.options = build_options(db, ctx, u, plan.evidence, plan.situation, plan.contradictions)
    score_options(plan.options, db=db, situation=plan.situation)
    plan.chosen = plan.options[0] if plan.options else None
    plan.decision_kind = KIND_BY_INTENT.get(u.intent, "general")
    plan.problem = question.strip()[:400]
    if plan.chosen is not None and plan.chosen.id != "no_action":
        plan.title = plan.chosen.label[:200]
    else:
        plan.title = TITLE_BY_INTENT.get(u.intent, "بررسی وضعیت فروشگاه")
    # 4) policy gate on the chosen option
    if plan.chosen:
        plan.policy_verdict = _policy_gate(db, plan.chosen, plan.situation)
    # 4.5) empty-store discipline: with no sales and no stock there is nothing to
    #      reason about yet — say so instead of manufacturing a recommendation.
    seen = {}
    for block in (plan.situation.store, plan.situation.sales, plan.situation.inventory):
        seen.update((block or {}).get("numbers") or {})
    if not any(seen.get(key) for key in ("invoices", "invoices_90d", "batch_count")):
        plan.degraded.append("no_data")
    # 5) degraded discipline
    dq = (plan.situation.data_quality or {}).get("numbers", {}) if plan.situation else {}
    if (plan.situation and "DATA_QUALITY_BLOCKED" in (plan.situation.flags or [])) or dq.get("critical"):
        plan.degraded.append("data_quality")
        if plan.chosen and plan.chosen.requires_approval and (dq.get("critical") or 0) > 0:
            # §10 / scenario #4: never issue a confident financial instruction on corrupt data
            plan.blocked = True
    return plan


def _policy_gate(db: Session, option, situation) -> dict:
    verdicts = []
    for action in (option.actions or []):
        atype, params = action.get("type"), action.get("params", {}) or {}
        requires = action_requires_approval(db, atype, params)
        checks = []
        if "percent" in params:
            v = check_discount(db, float(params["percent"]))
            checks = [c.to_dict() for c in v.checks]
            requires = requires or v.requires_approval
        verdicts.append({"action": atype, "requires_approval": requires, "checks": checks,
                         "reversible": bool(action.get("reversible", True))})
    blocking = list(option.policy_notes or [])
    return {"allowed": not blocking, "requires_approval": any(v["requires_approval"] for v in verdicts) or
                                          bool(option.requires_approval),
            "actions": verdicts, "blocking": blocking,
            "reason": ("سیاست فروشگاه: " + "؛ ".join(blocking)) if blocking else
                      ("نیازمند تأیید شما" if any(v["requires_approval"] for v in verdicts) else "در محدودهٔ سیاست‌ها")}


# --------------------------------------------------------------------------- deterministic answer
def deterministic_text(plan: Plan, question: str) -> str:
    """The guaranteed answer (§20): وضعیت → دلیل → پیشنهاد → اقدام بعدی."""
    from .planner_text import compose   # kept separate: it is pure string work

    return compose(plan, question)


# --------------------------------------------------------------------------- the loop
def respond(db: Session, *, question: str, user: User | None = None, session_key: str = "default",
            permissions: frozenset[str] | None = None, prefer_llm: bool = True,
            origin: str = "CHAT") -> dict:
    """Answer the owner. Returns the serialised :class:`~.schemas.Answer`."""
    from ...security import _user_permission_codes
    from .runtime import get_runtime

    t0 = time.perf_counter()
    perms = permissions if permissions is not None else (
        frozenset(_user_permission_codes(user)) if user is not None else frozenset())
    ctx = ToolContext(db=db, user=user, permissions=perms, system=user is None)
    log_message(db, session_key=session_key, role="USER", content=question,
                user_id=getattr(user, "id", None))
    plan = analyse(db, ctx, question, session_key=session_key)

    text = deterministic_text(plan, question)
    mode = "deterministic"
    model_id = None
    numbers_verified = True
    warnings: list[str] = []

    runtime = get_runtime(db)
    if prefer_llm and runtime.available():
        try:
            refined = _refine_with_model(db, ctx, plan, question, runtime=runtime, session_key=session_key)
            if refined:
                text, model_id = refined, runtime.model_id
                mode = "llm"
        except Exception as exc:  # noqa: BLE001 — the model is an enhancement, never a dependency
            log.warning("model refinement failed: %s", exc)
            warnings.append("MODEL_FAILED")

    # grounding: a model may only quote numbers a tool produced
    known = ctx.known_numbers()
    check = verify_numbers(text, known, context=plan.understanding.intent)
    if not check["ok"]:
        from .audit import log as audit_log
        audit_log(db, event="BRAIN_NUMBER_REJECTED", user_id=getattr(user, "id", None),
                  after={"offending": check["offending"], "question": question[:200]})
        warnings.append("NUMBER_REJECTED")
        text = deterministic_text(plan, question)
        mode = "deterministic"
        numbers_verified = False

    if plan.blocked:
        text = fa.blocked_by_data_quality(
            [c.get("message", "") for c in ((plan.situation.data_quality or {}).get("details", {}) or {}).get("checks", [])
             if c.get("severity") == "CRITICAL"][:3]) or text

    decision_row = _persist(db, plan, ctx, user=user, question=question, origin=origin)
    followups = _auto_followups(db, plan, decision_row, user=user)

    log_message(db, session_key=session_key, role="ASSISTANT", content=text,
                tool_trace=ctx.trace_payload(), decision_id=decision_row.id if decision_row else None,
                user_id=getattr(user, "id", None),
                meta={"intent": plan.understanding.intent, "mode": mode, "entities": plan.understanding.entities,
                      "model": model_id, "warnings": warnings})
    db.commit()

    from .schemas import Answer
    answer = Answer(text=text, intent=plan.understanding.intent, mode=mode, degraded=plan.degraded,
                    evidence=[e.to_dict() for e in plan.evidence],
                    tools_used=ctx.trace_payload(),
                    decision=decision_to_dict(decision_row) if decision_row else None,
                    numbers_verified=numbers_verified, followups=followups, model=model_id,
                    ms=int((time.perf_counter() - t0) * 1000), warnings=warnings,
                    meta={"contradictions": [c.to_dict() if hasattr(c, "to_dict") else c for c in plan.contradictions],
                          "policy_verdict": plan.policy_verdict,
                          "entities": plan.understanding.entities,
                          "options": [o.to_dict() for o in plan.options]})
    return answer.to_dict()


def _refine_with_model(db: Session, ctx: ToolContext, plan: Plan, question: str, *, runtime,
                       session_key: str) -> str | None:
    """Let the local model phrase the answer — bounded, grounded, optional."""
    from .runtime import ToolLoop

    situation_text = summary_for_prompt(plan.situation) if plan.situation else ""
    policy_text = json.dumps(_policy_digest(db), ensure_ascii=False)
    memory_text = _memory_digest(db, plan)
    system = prompts.SYSTEM_PROMPT
    user_msg = "\n\n".join([
        prompts.situation_block(situation_text, policy_text, memory_text),
        prompts.tools_block(REGISTRY.for_llm(ctx)),
        prompts.tool_call_instruction(),
        prompts.decision_block(plan.title or (plan.chosen.label if plan.chosen else ""),
                               (plan.chosen.description if plan.chosen else ""),
                               (plan.chosen.label if plan.chosen else "بدون اقدام"),
                               "نیازمند تأیید مدیر" if (plan.chosen and plan.chosen.requires_approval) else "کم‌ریسک"),
        "[سؤال مدیر]\n" + question,
        "[حافظهٔ گفت‌وگو]\n" + (conversation_digest(db, session_key=session_key) or "—"),
    ])
    loop = ToolLoop(runtime=runtime, ctx=ctx, max_rounds=prompts.MAX_TOOL_ROUNDS)
    return loop.run(system=system, user=user_msg)


def _policy_digest(db: Session) -> dict:
    from .policies import all_policies

    return {k: v["value"] for k, v in all_policies(db).items()
            if k in ("max_discount_without_approval", "maximum_discount_any", "minimum_cash_reserve",
                     "minimum_margin_pct", "supplier_priority", "ai_mode")}


def _memory_digest(db: Session, plan: Plan) -> str:
    parts = []
    pattern = pattern_for(db, plan.decision_kind or plan.understanding.intent)
    if pattern:
        parts.append(f"سابقهٔ قطعی این نوع تصمیم در همین فروشگاه: {json.dumps(pattern, ensure_ascii=False)}")
    return "\n".join(parts)


def _persist(db: Session, plan: Plan, ctx: ToolContext, *, user: User | None, question: str, origin: str):
    """Persist a decision record when the turn produced a real business decision."""
    if not plan.options or plan.chosen is None or "no_data" in plan.degraded:
        return None
    if plan.understanding.intent in ("GENERAL", "DECISION_RECALL", "POLICY_SET") and plan.chosen.id == "no_action":
        return None
    if plan.understanding.intent not in WATCHED_INTENTS and plan.chosen.id == "no_action":
        return None
    chosen = plan.chosen
    actions = list(chosen.actions or [])
    requires = chosen.id != "no_action" and bool(
        plan.policy_verdict.get("requires_approval", chosen.requires_approval))
    no_action = chosen.id == "no_action"
    contract = {} if no_action else build_measurement(
        metric=chosen.economics.get("metric") or "avg_basket_size",
        window_days=int(chosen.economics.get("window_days") or 14),
        entities={"product_ids": [plan.understanding.entities["product_id"]]}
        if plan.understanding.entities.get("product_id") else {})
    row = create_decision(
        db, title=plan.title or chosen.label, problem=plan.problem or question[:400], reason=chosen.description,
        options=[o.to_dict() for o in plan.options], evidence=[e.to_dict() for e in plan.evidence],
        situation=(plan.situation.to_dict() if plan.situation else {}), selected_option=chosen.id,
        confidence=chosen.confidence, requires_approval=requires, actions=actions,
        risks=[{"risk": note, "severity": chosen.risk} for note in chosen.tradeoffs],
        policy_verdict=plan.policy_verdict, decision_kind=plan.decision_kind or plan.understanding.intent.lower(),
        measurement=contract, origin=origin, user_id=getattr(user, "id", None),
        tool_trace=ctx.trace_payload(), dedupe_key=_dedupe_key(plan), priority=_priority(plan),
        status="NO_ACTION" if no_action else None,
    )
    return row


#: intents where "we checked and nothing is needed" is worth a permanent record
WATCHED_INTENTS = frozenset({"CASH_CRISIS", "CHEQUE_MANAGEMENT", "RECEIVABLE", "EXPIRY", "STOCKOUT",
                             "OVERSTOCK", "SALES_DROP"})


def _dedupe_key(plan: Plan) -> str | None:
    e = plan.understanding.entities
    base = None
    if e.get("product_id"):
        base = f"product:{e['product_id']}"
    elif e.get("customer_id"):
        base = f"customer:{e['customer_id']}"
    elif e.get("supplier_id"):
        base = f"supplier:{e['supplier_id']}"
    kind = plan.decision_kind or plan.understanding.intent.lower()
    return f"{kind}:{base}" if base else None


def _priority(plan: Plan) -> int:
    if not plan.chosen:
        return 3
    if plan.chosen.risk == "high":
        return 1
    if plan.chosen.economics.get("gain_toman", 0) and plan.chosen.economics["gain_toman"] > 0:
        return 2
    return 3


def _auto_followups(db: Session, plan: Plan, decision_row, *, user: User | None) -> list[dict]:
    """§14/§50 — the brain creates follow-ups when the plan implies a later check."""
    from .followups import create as create_followup, to_dict as followup_dict

    created: list[dict] = []
    if decision_row is not None and plan.chosen and plan.chosen.economics.get("followup_days"):
        row = create_followup(db, title=f"بررسی نتیجه: {decision_row.title[:110]}", kind="MEASURE",
                              days=int(plan.chosen.economics["followup_days"]),
                              note=plan.chosen.description, decision_id=decision_row.id,
                              user_id=getattr(user, "id", None))
        created.append(followup_dict(row))
    return created
