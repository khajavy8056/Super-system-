# -*- coding: utf-8 -*-
"""Proactive engine (v4.0 §24 + §25).

Runs on a schedule (or on demand from the API) and looks for problems the owner
has not asked about yet.  Three rules shape everything here:

* The brain does not nag.  Every alert has a *dedupe key*, a *cooldown* and a
  ceiling (the ``max_active_alerts`` policy).  An alert that is still open, or
  was closed less than ``cooldown_days`` ago, is not raised again.
* Zero is a valid answer.  A shop with nothing wrong gets no cards at all —
  the engine never fills a quota.
* Proposals only.  The engine writes decisions, never prices, orders or SMS:
  acting on a card still goes through approval and the Action Engine.

Jobs read the *same* deterministic tools the chat answers from, so a card and an
answer can never disagree about a number.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Callable

from sqlalchemy.orm import Session

from ...models import BrainDecision, SystemSetting
from . import decisions as decision_svc
from . import followups as followup_svc
from . import persian as fa
from .audit import log as audit_log
from .context import ToolContext
from .registry import REGISTRY
from .situation import build as build_situation

log = logging.getLogger("business_brain.proactive")

#: decision statuses that mean "already on the owner's desk"
OPEN_STATUSES = ("NEEDS_DECISION", "WAITING_APPROVAL", "RUNNING", "MONITORING")

SETTING_LAST_RUN = "brain.proactive.last_run"
DEFAULT_MAX_ALERTS = 5


# --------------------------------------------------------------------- helpers
@dataclass
class Alert:
    job: str
    domain: str
    priority: int
    title: str
    problem: str
    reason: str
    dedupe_key: str
    options: list = field(default_factory=list)
    evidence: list = field(default_factory=list)
    cooldown_days: int = 3
    confidence: str = "medium"

    def to_dict(self) -> dict:
        return {"job": self.job, "domain": self.domain, "priority": self.priority,
                "title": self.title, "problem": self.problem, "reason": self.reason,
                "dedupe_key": self.dedupe_key, "confidence": self.confidence}


def _opt(option_id: str, label: str, *, gain: float = 0.0, risk: str = "medium",
         actions: list | None = None, description: str = "") -> dict:
    """An option shaped exactly like the planner's, so approval works unchanged."""
    actions = actions or [{"type": "note", "params": {}, "label": "ثبت یادداشت پیگیری",
                           "reversible": True}]
    external = any(a.get("type") in ("personal_sms", "debt_reminders", "visit_sms", "winback_sms",
                                     "vip_coupons", "personal_coupons", "sms_buyers") for a in actions)
    return {"id": option_id, "label": label, "description": description,
            "economics": {"gain_toman": round(float(gain), 2), "source": "deterministic"},
            "risk": risk, "reversible": True, "confidence": "medium",
            "requires_approval": True, "action_class": "APPROVAL",
            "actions": actions, "tradeoffs": [], "policy_notes": [], "preconditions": [],
            "score": 0.0, "external_side_effect": external}


def _note(label: str) -> list:
    return [{"type": "note", "params": {}, "label": label, "reversible": True}]


def _sms(label: str, *, customers: list | None = None) -> list:
    return [{"type": "personal_sms", "params": {"customers": customers or []}, "label": label,
             "reversible": True},
            {"type": "note", "params": {}, "label": "ثبت پیگیری", "reversible": True}]


# ----------------------------------------------------------------------- facts
def _facts(ctx: ToolContext, situation) -> dict:
    """The one expensive call the proactive pass makes, shared by all jobs."""
    forecast = REGISTRY.call_or_none(ctx, "get_cash_forecast", {"days": 14})
    collections = REGISTRY.call_or_none(ctx, "get_expected_collections", {"days": 14})
    return {"forecast": forecast or {}, "collections": collections or {},
            "cash": (situation.cash or {}).get("numbers", {}) or {},
            "obligations": (situation.obligations or {}).get("numbers", {}) or {},
            "receivables": (situation.receivables or {}).get("numbers", {}) or {},
            "expiry": ((situation.inventory or {}).get("expiry_risk") or {}).get("numbers", {}) or {},
            "stockout": ((situation.inventory or {}).get("stockout") or {}).get("numbers", {}) or {},
            "sales": (situation.sales or {}).get("numbers", {}) or {}}


# ------------------------------------------------------------------------ jobs
def _data_job(situation, ctx, *, today: date, facts: dict) -> Alert | None:
    if "DATA_QUALITY_BLOCKED" not in situation.flags:
        return None
    details = (situation.data_quality or {}).get("details") or {}
    blocking = [c for c in (details.get("checks") or []) if c.get("severity") == "CRITICAL"]
    names = "، ".join((c.get("title") or c.get("key") or "") for c in blocking[:3]) or \
        (details.get("summary") or "کیفیت داده پایین است")
    return Alert(
        job="data_watch", domain="operations", priority=1,
        title="داده‌های ناقص، تصمیم مالی را متوقف کرده",
        problem=f"تا رفع این موارد، عدد مالی قابل اتکا نیست: {names}",
        reason="سیستم به‌جای حدس زدن، تصمیم مالی را متوقف می‌کند تا پول روی دادهٔ غلط خرج نشود.",
        dedupe_key="data_quality", cooldown_days=7, confidence="high",
        options=[_opt("no_action", "باشه، اول داده را اصلاح می‌کنم", actions=_note("بازبینی داده"))],
    )


def _cash_job(situation, ctx, *, today: date, facts: dict) -> Alert | None:
    numbers = (facts["forecast"] or {}).get("numbers") or {}
    breaches = int(numbers.get("breach_days") or 0)
    minimum = float(numbers.get("min_projected_cash") or 0.0)
    shortfall = float(numbers.get("shortfall") or 0.0)
    below_safety = int(numbers.get("days_below_safety") or 0)
    safety = float(numbers.get("safety_target") or 0.0)
    without = numbers.get("min_without_collections")
    # Three ways this is worth the owner's attention — the projection going
    # negative, the projection sitting under the safety buffer, and the buffer
    # surviving *only* because the collections land on time.
    if not breaches and minimum >= 0 and not below_safety and (without is None or float(without) >= 0):
        return None
    cash = facts["cash"]
    expected = float(numbers.get("expected_collections") or 0.0)
    due = float(facts["obligations"].get("issued_next_7d") or 0.0)
    first_date = numbers.get("first_breach_date") or numbers.get("lowest_day")

    options = []
    if expected > 0:
        options.append(_opt("chase_receivable", "پیگیری مشتریان بدهکار (سریع‌ترین منبع نقد)",
                            gain=min(expected, shortfall or expected),
                            actions=_sms("پیام یادآوری بدهی به مشتریان"), risk="low"))
    if due > 0:
        options.append(_opt("negotiate_supplier_terms", "مذاکره برای مهلت با تأمین‌کننده",
                            gain=due * 0.5, actions=_note("یادداشت مذاکره با تأمین‌کننده"), risk="low"))
    return Alert(
        job="cash_watch", domain="finance", priority=1,
        title="کمبود نقدینگی در پیش است" if (breaches or minimum < 0) else "حاشیهٔ نقدی نازک است",
        problem=f"پیش‌بینی ۱۴ روز: کمترین موجودی {fa.toman_short(minimum)} تومان"
                + (f" در {fa.fa_date(_as_date(first_date))}" if first_date else "")
                + (f" و کسری تا {fa.toman_short(shortfall)} تومان" if shortfall else "")
                + (f"؛ {fa.fa_num(below_safety)} روز زیر کف امن {fa.toman_short(safety)} تومانی"
                   if below_safety and safety else "")
                + f"؛ تعهدات هفت روز آینده {fa.toman_short(due)} تومان است.",
        reason=f"ماندهٔ قابل استفاده {fa.toman_short(cash.get('cash_available') or 0)} تومان، "
               f"مطالبات وصول‌شدنی {fa.toman_short(expected)} تومان است."
               + (f" اگر وصول مطالبات چند روز عقب بیفتد، موجودی تا {fa.toman_short(abs(float(without)))} "
                  f"تومان منفی می‌شود." if without is not None and float(without) < 0 else ""),
        dedupe_key="cash_pressure", cooldown_days=2, confidence="high",
        options=options or [_opt("no_action", "فعلاً اقدام نمی‌کنم")],
    )


def _cheque_job(situation, ctx, *, today: date, facts: dict) -> Alert | None:
    cheques = ((situation.obligations or {}).get("details") or {}).get("cheques") or []
    horizon = today + timedelta(days=3)
    urgent = [c for c in cheques
              if c.get("direction") == "ISSUED" and _as_date(c.get("due_date")) <= horizon]
    if not urgent:
        return None
    total = sum(float(c.get("amount") or 0) for c in urgent)
    available = float((facts["cash"] or {}).get("cash_available") or 0.0)
    if total <= available:
        return None
    first = urgent[0]
    return Alert(
        job="cheque_watch", domain="finance", priority=1,
        title="چک نزدیک‌سررسید پوشش ندارد",
        problem=f"{fa.money(total)} چک تا دو روز آینده سررسید دارد (نزدیک‌ترین: "
                f"{fa.fa_date(_as_date(first.get('due_date')))}، {fa.money(float(first.get('amount') or 0))}) "
                f"و موجودی قابل استفاده {fa.money(available)} است.",
        reason=f"مطالبات با احتمال وصول بالا {fa.money(float(facts['receivables'].get('high_confidence') or 0))} "
               f"تومان است؛ وصول بخشی از آن، پوشش چک را می‌سازد.",
        dedupe_key=f"cheque::{first.get('due_date')}", cooldown_days=1, confidence="high",
        options=[_opt("chase_receivable", "تماس با بدهکاران برای وصول پیش از سررسید چک",
                      gain=min(total, float(facts["receivables"].get("high_confidence") or 0)),
                      actions=_sms("پیام یادآوری بدهی"), risk="low"),
                 _opt("negotiate_supplier_terms", "گرفتن مهلت از تأمین‌کننده",
                      gain=total * 0.5, actions=_note("یادداشت مذاکره"), risk="low")],
    )


def _expiry_job(situation, ctx, *, today: date, facts: dict) -> Alert | None:
    value = float(facts["expiry"].get("at_risk_value") or 0.0)
    if value <= 0:
        return None
    return Alert(
        job="expiry_watch", domain="inventory", priority=2,
        title="کالای نزدیک به انقضا",
        problem=f"{fa.money(value)} کالا تا یک ماه آینده منقضی می‌شود.",
        reason="فروش با سرعت فعلی این موجودی را تمام نمی‌کند؛ تخفیف محدود یا بازگرداندن به تأمین‌کننده "
               "ارزان‌تر از دور ریختن است.",
        dedupe_key="expiry_risk", cooldown_days=3,
        options=[_opt("clear_expiring_stock", "فروش سریع اقلام در معرض انقضا با تخفیف محدود",
                      gain=value * 0.35,
                      actions=[{"type": "flash_sale", "params": {"percent": 15, "days": 7},
                                "label": "تخفیف ۱۵٪ برای اقلام در معرض انقضا", "reversible": True}]),
                 _opt("return_to_supplier", "هماهنگی بازگشت با تأمین‌کننده",
                      gain=value * 0.5, actions=_note("تماس با تأمین‌کننده برای بازگشت کالا"), risk="low")],
    )


def _stockout_job(situation, ctx, *, today: date, facts: dict) -> Alert | None:
    count = int(facts["stockout"].get("count") or 0)
    if count <= 0:
        return None
    return Alert(
        job="stockout_watch", domain="inventory", priority=2,
        title="خطر اتمام موجودی پرفروش‌ها",
        problem=f"{fa.fa_num(count)} قلم کالا تا کمتر از دو هفتهٔ فروش موجودی دارند.",
        reason="سفارش دیرهنگام فروش را از دست می‌دهد؛ مقدار پیشنهادی بر پایهٔ سرعت فروش خودِ کالا محاسبه شده.",
        dedupe_key="stockout_risk", cooldown_days=4,
        options=[_opt("reorder", "ثبت لیست سفارش برای اقلام پرفروش", gain=0.0,
                      actions=[{"type": "reorder_note", "params": {}, "label": "لیست سفارش پرفروش‌ها",
                                "reversible": True}]),
                 _opt("no_action", "فعلاً اقدام نمی‌کنم")],
    )


def _receivable_job(situation, ctx, *, today: date, facts: dict) -> Alert | None:
    high = float(facts["receivables"].get("high_confidence") or 0.0)
    total = float(facts["receivables"].get("total") or 0.0)
    under_pressure = bool((facts["forecast"] or {}).get("numbers", {}).get("breach_days"))
    if total < 5_000_000 or not under_pressure:
        return None
    return Alert(
        job="receivable_watch", domain="finance", priority=3,
        title="مطالبات، منبع نقد بدون هزینه",
        problem=f"{fa.money(total)} از مشتریان طلب دارید که {fa.money(high)} آن "
                f"با احتمال وصول بالا طبقه‌بندی شده است.",
        reason="وصول مطالبات، برخلاف تخفیف یا وام، حاشیهٔ سود را کم نمی‌کند.",
        dedupe_key="receivables_followup", cooldown_days=7,
        options=[_opt("remind_debtors", "پیام یادآوری بدهی برای بدهکاران خوش‌حساب",
                      gain=high, actions=_sms("پیام یادآوری بدهی"), risk="low"),
                 _opt("no_action", "فعلاً اقدام نمی‌کنم")],
    )


def _sales_job(situation, ctx, *, today: date, facts: dict) -> Alert | None:
    if "SALES_DROP" not in situation.flags:
        return None
    change = (situation.sales or {}).get("numbers", {}).get("change_pct")
    return Alert(
        job="sales_watch", domain="sales", priority=3,
        title="کاهش فروش نسبت به دورهٔ قبل",
        problem=f"فروش هفت روز گذشته {(fa.fa_num(abs(change)) + '٪') if change else ''} نسبت به هفتهٔ قبل کمتر است، "
                f"در حالی که میانگین سبد {fa.toman_short(facts['sales'].get('avg_basket') or 0)} تومان است.",
        reason="کاهش فروش می‌تواند از موجودی، قیمت یا نبود مشتری باشد؛ تشخیص علت قبل از هر تبلیغی لازم است.",
        dedupe_key="sales_drop", cooldown_days=5,
        options=[_opt("no_action", "فعلاً اقدام نمی‌کنم")],
    )


def _followup_job(situation, ctx, *, today: date, facts: dict) -> Alert | None:
    due = followup_svc.due_items(ctx.db)
    if not due:
        return None
    return Alert(
        job="followup_watch", domain="operations", priority=2,
        title="پیگیری‌های امروز",
        problem=f"{fa.fa_num(len(due))} پیگیری از تصمیم‌های قبلی امروز موعدشان رسیده است.",
        reason="بدون ثبت نتیجه، اثر تصمیم قبلی اندازه‌گیری نمی‌شود و تصمیم بعدی روی حدس سوار می‌شود.",
        dedupe_key="followups_due", cooldown_days=1, confidence="high",
        options=[_opt("no_action", "پیگیری‌ها را می‌بینم")],
    )


#: ``(stable job id, watcher)``. The id is what the UI, the audit trail and the
#: tests see — an alert always carries the same name as the job that raised it.
JOBS: tuple[tuple[str, Callable[..., Alert | None]], ...] = (
    ("data_watch", _data_job),
    ("cash_watch", _cash_job),
    ("cheque_watch", _cheque_job),
    ("expiry_watch", _expiry_job),
    ("stockout_watch", _stockout_job),
    ("receivable_watch", _receivable_job),
    ("sales_watch", _sales_job),
    ("followup_watch", _followup_job),
)
JOB_IDS: tuple[str, ...] = tuple(name for name, _ in JOBS)


def _as_date(value) -> date:
    if isinstance(value, date):
        return value
    if isinstance(value, str) and value:
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            pass
    return date.today()


# --------------------------------------------------------------------- engine
def _setting(db: Session, key: str, default: str = "") -> str:
    row = db.query(SystemSetting).filter(SystemSetting.key == key).first()
    return (row.value if row is not None else default) or default


def _put_setting(db: Session, key: str, value: str) -> None:
    row = db.query(SystemSetting).filter(SystemSetting.key == key).first()
    if row is None:
        db.add(SystemSetting(key=key, value=value))
    else:
        row.value = value


def _limit(ctx) -> int:
    from . import policies as policy_svc
    try:
        return max(0, int(float(policy_svc.get_value(ctx.db, "max_active_alerts", DEFAULT_MAX_ALERTS))))
    except Exception:  # noqa: BLE001
        return DEFAULT_MAX_ALERTS


def _open_cards(db: Session) -> tuple[int, dict[str, datetime]]:
    rows = (db.query(BrainDecision)
            .filter(BrainDecision.status.in_(OPEN_STATUSES))
            .filter(BrainDecision.origin == "PROACTIVE")
            .order_by(BrainDecision.id.desc()).limit(200).all())
    last: dict[str, datetime] = {}
    for row in rows:
        key = row.dedupe_key or f"id:{row.id}"
        stamp = row.created_at or datetime.utcnow()
        if key not in last or stamp > last[key]:
            last[key] = stamp
    return len(rows), last


def _recent_touched(db: Session, days: int = 30) -> dict[str, datetime]:
    since = datetime.utcnow() - timedelta(days=days)
    rows = (db.query(BrainDecision).filter(BrainDecision.origin == "PROACTIVE")
            .filter(BrainDecision.updated_at >= since).all())
    last: dict[str, datetime] = {}
    for row in rows:
        key = row.dedupe_key or f"id:{row.id}"
        stamp = row.updated_at or row.created_at or datetime.utcnow()
        if key not in last or stamp > last[key]:
            last[key] = stamp
    return last


def evaluate(db: Session, *, ctx: ToolContext | None = None, now: date | None = None,
             force: bool = False, persist: bool = True, user_id: int | None = None) -> dict:
    """One proactive pass.  Never raises on a broken job, never invents an alert."""
    today = now or date.today()
    ctx = ctx or ToolContext(db=db, system=True)
    started = datetime.utcnow()

    situation = build_situation(db, ctx, light=True)
    facts = _facts(ctx, situation)
    limit = _limit(ctx)
    open_count, open_keys = _open_cards(db)
    touched = _recent_touched(db)

    raised: list[dict] = []
    skipped: list[dict] = []
    seen_domains: set[str] = set()

    for name, job in JOBS:
        try:
            alert = job(situation, ctx, today=today, facts=facts)
        except Exception as exc:  # noqa: BLE001 — one broken watcher must not stop the rest
            log.exception("proactive job %s failed", name)
            skipped.append({"job": name, "reason": "ERROR", "detail": str(exc)[:200]})
            continue
        if alert is None:
            skipped.append({"job": name, "reason": "NOTHING_TO_REPORT"})
            continue
        if alert.dedupe_key in open_keys:
            skipped.append({"job": name, "reason": "ALREADY_ON_DESK", "key": alert.dedupe_key})
            continue
        last = touched.get(alert.dedupe_key)
        if last and not force and (started - last) < timedelta(days=alert.cooldown_days):
            skipped.append({"job": name, "reason": "COOLDOWN", "key": alert.dedupe_key})
            continue
        # the ceiling and the one-card-per-domain rule are anti-spam policy, not a
        # debugging switch: even a forced run respects them.
        if open_count >= limit:
            skipped.append({"job": name, "reason": "ALERT_LIMIT", "limit": limit})
            continue
        if alert.domain in seen_domains:
            skipped.append({"job": name, "reason": "CLUSTERED", "domain": alert.domain})
            continue

        if not persist:
            raised.append(alert.to_dict())
        else:
            row = decision_svc.create(
                db, title=alert.title, problem=alert.problem, reason=alert.reason,
                options=alert.options, evidence=alert.evidence,
                situation={"summary": situation.digest(), "flags": list(situation.flags)},
                priority=alert.priority, decision_kind=alert.domain.upper(), origin="PROACTIVE",
                dedupe_key=alert.dedupe_key, confidence=alert.confidence, user_id=user_id,
                requires_approval=any(o.get("requires_approval") for o in alert.options),
            )
            raised.append({**alert.to_dict(), "decision_id": getattr(row, "id", None)})
        open_count += 1
        seen_domains.add(alert.domain)

    notified = 0
    if persist:
        try:
            notified = followup_svc.notify_due(db)
        except Exception:  # noqa: BLE001
            log.exception("follow-up notification failed")
        _put_setting(db, SETTING_LAST_RUN, started.isoformat())
        audit_log(db, event="BRAIN_PROACTIVE_RUN", user_id=None,
                  after={"raised": len(raised), "skipped": len(skipped), "domains": sorted(seen_domains)})
        db.commit()

    return {"ran_at": started.isoformat(), "alerts": raised, "skipped": skipped,
            "open_cards": open_count, "limit": limit, "followups_notified": notified,
            "digest": situation.digest()}


def status(db: Session) -> dict:
    """What the proactive engine is, and when it last looked — for the UI."""
    open_count, open_keys = _open_cards(db)
    return {"engine": "business_brain.proactive", "jobs": list(JOB_IDS),
            "last_run": last_run(db), "open_cards": open_count,
            "limit": _limit(ToolContext(db=db, system=True)),
            "open_keys": sorted(open_keys)}


def recommendations(db: Session, *, limit: int = 10) -> list[dict]:
    """Alias used by the façade/UI: the proactive cards still on the owner's desk."""
    return alerts(db, limit=limit)


def last_run(db: Session) -> str | None:
    return _setting(db, SETTING_LAST_RUN) or None


def alerts(db: Session, *, limit: int = 10) -> list[dict]:
    """The proactive cards that are still open, most urgent first."""
    rows = (db.query(BrainDecision).filter(BrainDecision.origin == "PROACTIVE")
            .filter(BrainDecision.status.in_(OPEN_STATUSES))
            .order_by(BrainDecision.priority.asc(), BrainDecision.id.desc()).limit(limit).all())
    return [decision_svc.to_dict(row, full=False) for row in rows]
