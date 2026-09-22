"""v4.0 — Decision Memory, approval, execution and measurement (§13, §45, §47, §55).

A decision is a first-class record, not a chat message:

    problem → evidence → options → selected option → reason → policy verdict
    → approval → execution (Action Engine) → measurement → outcome → memory

Everything that *moves money* is executed by ``services/insight_actions.py``
through :class:`ActionOwner` — the same VALIDATE → SAVEPOINT → EXECUTE → VERIFY
path an insight uses, with the same audit rows. The brain brings the reasoning;
it does not get its own private write path.

Measurement reuses the v3.8 machinery (``insights._metric_value`` +
``MEASUREMENT_SPECS`` + the store-wide difference-in-differences control), so a
brain decision's outcome is comparable with an insight's — and the same
calibration learns from both (§54).
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ...models import BrainDecision, BrainFollowup, Insight, User
from .. import insights as ins_svc
from .. import insight_actions as engine
from . import persian as fa
from .audit import log as audit_log

log = logging.getLogger("supermarket.brain.decisions")

TERMINAL = ("RESOLVED", "MEASURED", "FAILED", "NO_ACTION")
NEGATIVE_VERDICTS = {"NEGATIVE_OUTCOME"}
POSITIVE_VERDICTS = {"POSITIVE_OUTCOME"}


# --------------------------------------------------------------------------- creation
def build_measurement(*, metric: str, window_days: int = 14, entities: dict | None = None,
                      success_rule: str = "", method: str = "") -> dict:
    """§55 — every important action ships with a contract, written before it runs."""
    entities = entities or {}
    return {
        "metric": metric,
        "window_days": int(window_days),
        "baseline": "same-length window immediately before approval",
        "success_rule": success_rule or "سود روزانهٔ تعدیل‌شده بالاتر از بازهٔ قبل باشد",
        "method": method or "before/after with store-wide difference-in-differences control",
        "entities": entities,
        "known_metric": metric in ins_svc.MEASUREMENT_SPECS,
    }


def create(db: Session, *, title: str, problem: str, reason: str, options: list[dict],
           evidence: list[dict], situation: dict, objective: str = "", confidence: str = "medium",
           requires_approval: bool = True, actions: list[dict] | None = None, risks: list[dict] | None = None,
           policy_verdict: dict | None = None, selected_option: str | None = None,
           decision_kind: str = "", measurement: dict | None = None, origin: str = "CHAT",
           user_id: int | None = None, insight_id: int | None = None, dedupe_key: str | None = None,
           tool_trace: list[dict] | None = None, local_decision: bool = False, pending_sync: bool = False,
           priority: int = 3, status: str | None = None) -> BrainDecision:
    row = BrainDecision(
        type="business_decision", title=title[:255], problem=problem, objective=objective,
        situation=json.dumps(situation, ensure_ascii=False, default=str),
        evidence=json.dumps(evidence, ensure_ascii=False, default=str),
        options=json.dumps(options, ensure_ascii=False, default=str),
        recommended_option=selected_option, selected_option=selected_option, reason=reason,
        risks=json.dumps(risks or [], ensure_ascii=False, default=str),
        confidence=confidence, policy_verdict=json.dumps(policy_verdict or {}, ensure_ascii=False, default=str),
        requires_approval=requires_approval, actions=json.dumps(actions or [], ensure_ascii=False, default=str),
        measurement=json.dumps(measurement or {}, ensure_ascii=False, default=str),
        decision_kind=decision_kind, origin=origin, dedupe_key=dedupe_key, insight_id=insight_id,
        tool_trace=json.dumps(tool_trace or [], ensure_ascii=False, default=str),
        local_decision=local_decision, pending_sync=pending_sync, priority=priority,
        created_by=user_id,
        status=status or ("WAITING_APPROVAL" if requires_approval else "NEEDS_DECISION"),
        history=json.dumps([{"status": status or "NEEDS_DECISION", "at": datetime.utcnow().isoformat(),
                             "by": user_id, "note": "ایجاد شد"}], ensure_ascii=False),
    )
    db.add(row)
    db.flush()
    audit_log(db, event="BRAIN_DECISION_CREATED", user_id=user_id, decision_id=row.id,
              after={"title": row.title, "kind": decision_kind, "requires_approval": requires_approval,
                     "origin": origin})
    if local_decision:
        audit_log(db, event="BRAIN_OFFLINE_DECISION", user_id=user_id, decision_id=row.id)
    return row


def _set_status(row: BrainDecision, status: str, *, user_id: int | None = None, note: str = "") -> None:
    try:
        history = json.loads(row.history or "[]")
    except ValueError:
        history = []
    history.append({"status": status, "at": datetime.utcnow().isoformat(), "by": user_id, "note": note})
    row.history = json.dumps(history, ensure_ascii=False, default=str)
    row.status = status


# --------------------------------------------------------------------------- execution
def approve(db: Session, row: BrainDecision, *, user: User | None, option_id: str | None = None,
            execute: bool = True) -> dict:
    """§48 — turn the selected option into real actions through the Action Engine."""
    options = _json(row.options, [])
    selected = option_id or row.selected_option or row.recommended_option
    option = next((o for o in options if o.get("id") == selected), None)
    if option is None and options:
        option = options[0]
    if option is None or not option.get("actions"):
        _set_status(row, "NO_ACTION", user_id=getattr(user, "id", None), note="گزینهٔ اجرایی وجود نداشت")
        db.flush()
        return {"ok": True, "executed": [], "status": row.status, "note": "no_action"}
    if not execute:
        _set_status(row, "WAITING_APPROVAL", user_id=getattr(user, "id", None), note="منتظر اجرا")
        db.flush()
        return {"ok": True, "executed": [], "status": row.status}

    row.selected_option = option.get("id")
    row.approval = json.dumps({"approved_by": getattr(user, "id", None),
                               "approved_at": datetime.utcnow().isoformat(),
                               "option": option.get("id")}, ensure_ascii=False)
    _set_status(row, "RUNNING", user_id=getattr(user, "id", None), note="در حال اجرا")
    db.flush()

    owner = engine.ActionOwner(id=row.id, actions=option.get("actions") or [], title=row.title,
                               body=row.reason, evidence=_json(row.evidence, []), kind="brain_decision")
    try:
        executed = engine.execute_actions(db, option.get("actions") or [], owner=owner, user=user,
                                          audit_action="BRAIN_DECISION_APPROVED",
                                          audit_reference=f"decision #{row.id}")
    except Exception as exc:  # noqa: BLE001 — a broken action must leave a record, not a 500
        log.exception("decision %s execution blew up", row.id)
        row.execution = json.dumps({"error": str(exc)[:400]}, ensure_ascii=False)
        _set_status(row, "FAILED", user_id=getattr(user, "id", None), note=str(exc)[:200])
        audit_log(db, event="BRAIN_DECISION_FAILED", user_id=getattr(user, "id", None), decision_id=row.id,
                  after={"error": str(exc)[:400]})
        db.flush()
        return {"ok": False, "executed": [], "status": "FAILED", "error": str(exc)[:400]}

    ok = [e for e in executed if e.get("ok")]
    failed = [e for e in executed if not e.get("ok")]
    row.execution = json.dumps({"executions": executed, "verified": bool(ok) and not failed,
                                "failed": len(failed)}, ensure_ascii=False, default=str)
    if failed and not ok:
        _set_status(row, "FAILED", user_id=getattr(user, "id", None), note="همهٔ اقدام‌ها شکست خورد")
        audit_log(db, event="BRAIN_DECISION_FAILED", user_id=getattr(user, "id", None), decision_id=row.id,
                  after={"failures": failed})
    else:
        _set_status(row, "COMPLETED", user_id=getattr(user, "id", None),
                    note=("همهٔ اقدام‌ها تأیید شد" if not failed else f"{len(failed)} اقدام ناموفق"))
        audit_log(db, event="BRAIN_DECISION_EXECUTED", user_id=getattr(user, "id", None), decision_id=row.id,
                  after={"actions": [e["type"] for e in ok], "failed": len(failed)})
    # §14 — execution creates its own measurement appointment
    from .followups import auto_for_decision
    followup = auto_for_decision(db, row, user_id=getattr(user, "id", None))
    db.flush()
    return {"ok": not failed, "executed": executed, "status": row.status,
            "followup_id": followup.id if followup else None}


def reject(db: Session, row: BrainDecision, *, user: User | None, reason: str = "") -> dict:
    row.approval = json.dumps({"rejected_by": getattr(user, "id", None),
                               "rejected_at": datetime.utcnow().isoformat(),
                               "reason": reason}, ensure_ascii=False)
    _set_status(row, "RESOLVED", user_id=getattr(user, "id", None), note=reason or "رد شد")
    audit_log(db, event="BRAIN_DECISION_REJECTED", user_id=getattr(user, "id", None), decision_id=row.id,
              after={"reason": reason})
    db.flush()
    return {"ok": True, "status": row.status}


def snooze(db: Session, row: BrainDecision, *, days: int = 3, user: User | None = None) -> dict:
    _set_status(row, "WAITING_APPROVAL", user_id=getattr(user, "id", None),
                note=f"{days} روز به تعویق افتاد")
    from .followups import create as create_followup
    create_followup(db, title=f"یادآوری تصمیم: {row.title[:120]}", kind="REMIND", days=days,
                    note="مدیر این تصمیم را به تعویق انداخت", decision_id=row.id,
                    user_id=getattr(user, "id", None))
    db.flush()
    return {"ok": True, "status": row.status}


# --------------------------------------------------------------------------- measurement (§54, §55)
def measure(db: Session, row: BrainDecision, *, user_id: int | None = None) -> dict:
    """Measure a completed decision over its own contract window.

    Returns an honest verdict. Unknown metrics are ``NOT_MEASURABLE`` and short
    windows are ``INSUFFICIENT_DATA`` — the brain never reports a gain it did
    not measure.
    """
    if row.status not in ("COMPLETED", "MONITORING", "MEASURED"):
        return {"summary": "این تصمیم هنوز اجرا نشده؛ چیزی برای سنجش نیست",
                "verdict": "NOT_EXECUTED", "numbers": {}}
    contract = _json(row.measurement, {})
    metric = contract.get("metric") or "product_profit"
    mspec = ins_svc.MEASUREMENT_SPECS.get(metric)
    window = int(contract.get("window_days") or 14)
    entities = contract.get("entities") or {}
    start = row.updated_at if row.status != "MEASURED" else (row.updated_at or datetime.utcnow())
    try:
        history = json.loads(row.history or "[]")
        executed_at = next((h["at"] for h in reversed(history) if h.get("status") == "COMPLETED"), None)
        start = datetime.fromisoformat(executed_at) if executed_at else start
    except (ValueError, TypeError):
        pass
    end = min(datetime.utcnow(), start + timedelta(days=window))
    elapsed = max(1e-9, (end - start).total_seconds() / 86400)
    if mspec is None:
        payload = {"window_days": window, "elapsed_days": round(elapsed, 1), "enough_data": False,
                   "verdict": "NOT_MEASURABLE", "reason": f"no measurement contract for {metric!r}",
                   "from": start.isoformat(), "to": end.isoformat()}
        row.result = json.dumps(payload, ensure_ascii=False)
        row.measured_at = datetime.utcnow()
        row.outcome = "NOT_MEASURABLE"
        _set_status(row, "MEASURED", user_id=user_id, note="قرارداد اندازه‌گیری برای این سنجه وجود ندارد")
        db.flush()
        return {"summary": "برای این نوع تصمیم قرارداد اندازه‌گیری وجود ندارد؛ عددی اعلام نمی‌شود",
                "verdict": "NOT_MEASURABLE", "numbers": {}, "detail": payload}
    spec = {"metric": metric, "window_days": window, **{k: v for k, v in entities.items()}}
    base = ins_svc._metric_value(db, spec, start - timedelta(days=window), start)
    post = ins_svc._metric_value(db, spec, start, end)
    base_days = float(window)
    enough = elapsed >= min(3.0, window / 2)
    ctrl = 1.0
    if mspec.get("gain_source") != "none":
        sb = ins_svc._store_profit_rate(db, start - timedelta(days=window), start)
        sp = ins_svc._store_profit_rate(db, start, end)
        if sb > 0 and sp > 0:
            ctrl = max(0.5, min(2.0, sp / sb))
    base_rate = float(base.get("profit") or base.get("value") or 0) / base_days
    post_rate = float(post.get("profit") or post.get("value") or 0) / elapsed
    adjusted = (post_rate - base_rate * ctrl) * elapsed
    verdict = ins_svc.measurement_verdict(adjusted if enough else None, enough=enough, spec=mspec)
    if mspec.get("gain_source") == "none":
        gain: float | None = None
    else:
        gain = adjusted if enough else None
    payload = {"window_days": window, "elapsed_days": round(elapsed, 1), "enough_data": enough,
               "from": start.isoformat(), "to": end.isoformat(), "control_ratio": round(ctrl, 3),
               "base_rate_per_day": round(base_rate), "post_rate_per_day": round(post_rate),
               "raw_gain": round((post_rate - base_rate) * elapsed), "adjusted_gain": round(adjusted),
               "verdict": verdict, "metric": metric, "baseline": base, "post": post,
               "projected_month": round(adjusted / elapsed * 30) if enough else None,
               "gain_basis": mspec.get("gain_basis", "measured")}
    row.result = json.dumps(payload, ensure_ascii=False, default=str)
    row.measured_at = datetime.utcnow()
    row.measured_gain = Decimal(str(round(gain))) if gain is not None else None
    row.outcome = {"POSITIVE_OUTCOME": "POSITIVE", "NEGATIVE_OUTCOME": "NEGATIVE",
                   "NEUTRAL_OUTCOME": "NEUTRAL", "INSUFFICIENT_DATA": "INSUFFICIENT_DATA",
                   "NOT_MEASURABLE": "NOT_MEASURABLE"}.get(verdict, "INSUFFICIENT_DATA")
    if row.outcome != "INSUFFICIENT_DATA":
        _set_status(row, "MEASURED", user_id=user_id, note=f"نتیجه: {verdict}")
    audit_log(db, event="BRAIN_DECISION_MEASURED", user_id=user_id, decision_id=row.id,
              after={"verdict": verdict, "gain": gain})
    db.flush()
    _learn(db, row)
    summary = {
        "POSITIVE": f"نتیجهٔ این تصمیم مثبت بود؛ حدود {fa.toman_short(gain or 0)} تومان اثر سود",
        "NEGATIVE": f"این تصمیم نتیجهٔ منفی داشت ({fa.toman_short(abs(gain or 0))} تومان زیان نسبت به بازهٔ قبل)",
        "NEUTRAL": "اثر قابل توجهی نداشت (تقریباً بی‌تغییر)",
        "INSUFFICIENT_DATA": f"برای قضاوت زود است؛ فقط {fa.fa_num(elapsed, 1)} روز از پنجرهٔ "
                             f"{fa.fa_num(window)} روز گذشته",
        "NOT_MEASURABLE": "برای این تصمیم قرارداد اندازه‌گیری وجود ندارد؛ عددی اعلام نمی‌شود",
    }.get(row.outcome or "", f"نتیجه: {verdict}")
    return {"summary": summary, "verdict": verdict, "outcome": row.outcome,
            "numbers": {"gain": gain or 0, "base_rate_per_day": round(base_rate),
                        "post_rate_per_day": round(post_rate)}, "detail": payload}


def _learn(db: Session, row: BrainDecision) -> None:
    """§56/§57 — the outcome must be findable by the NEXT decision of this kind."""
    from .memory import remember

    kind = row.decision_kind or "general"
    key = f"kind:{kind}"
    from .memory import recall
    agg = recall(db, "PATTERN", key) or {"n": 0, "positive": 0, "gain": 0.0}
    gain = float(row.measured_gain or 0)
    agg["n"] = int(agg.get("n", 0)) + 1
    agg["gain"] = float(agg.get("gain", 0)) + gain
    if row.outcome == "POSITIVE":
        agg["positive"] = int(agg.get("positive", 0)) + 1
    agg["avg_gain"] = round(agg["gain"] / max(1, agg["n"]))
    agg["win_rate"] = round(agg["positive"] / max(1, agg["n"]), 2)
    remember(db, kind="PATTERN", key=key, value=agg, confidence=min(0.9, 0.4 + 0.1 * agg["n"]),
             source="MEASUREMENT", reference_type="BrainDecision", reference_id=row.id)
    remember(db, kind="EVENT", key=f"decision:{row.id}:outcome",
             value={"title": row.title, "kind": kind, "verdict": row.outcome, "gain": round(gain),
                    "option": row.selected_option},
             confidence=0.8, source="MEASUREMENT", reference_type="BrainDecision", reference_id=row.id)


def measure_all(db: Session) -> int:
    """Worker hook: measure every decision whose window has closed."""
    n = 0
    rows = db.execute(select(BrainDecision).where(BrainDecision.status.in_(["COMPLETED", "MONITORING"]),
                                                 BrainDecision.measured_at.is_(None))).scalars().all()
    for row in rows:
        try:
            contract = _json(row.measurement, {})
            executed = _executed_at(row)
            if executed is None:
                continue
            window = int(contract.get("window_days") or 14)
            if datetime.utcnow() < executed + timedelta(days=min(window, 3)):
                continue
            measure(db, row)
            n += 1
        except Exception:  # noqa: BLE001 — a failed measurement must not stop the loop
            log.exception("decision measurement failed for %s", row.id)
    if n:
        db.flush()
    return n


# --------------------------------------------------------------------------- offline & conflicts (§60/§61)
def mark_synced(db: Session, row: BrainDecision, *, store_key: str = "") -> dict:
    row.pending_sync = False
    if store_key:
        row.store_key = store_key
    db.flush()
    return {"ok": True, "id": row.id}


def detect_conflict(db: Session, row: BrainDecision, *, window_minutes: int = 30) -> BrainDecision | None:
    """Two devices deciding about the same thing at nearly the same time.

    Nothing is overwritten: the newer row is linked to the older one via
    ``conflict_with`` and both are left for the administrator to resolve (§61).
    """
    if not row.dedupe_key:
        return None
    cutoff = (row.created_at or datetime.utcnow()) - timedelta(minutes=window_minutes)
    other = db.execute(select(BrainDecision).where(BrainDecision.id != row.id,
                                                  BrainDecision.dedupe_key == row.dedupe_key,
                                                  BrainDecision.created_at >= cutoff)
                       .order_by(BrainDecision.id.desc())).scalars().first()
    if other is None:
        return None
    row.conflict_with = other.id
    _set_status(row, "NEEDS_DECISION", note=f"تضاد با تصمیم #{other.id} — نیاز به تصمیم مدیر")
    audit_log(db, event="BRAIN_CONFLICT", decision_id=row.id,
              after={"conflict_with": other.id, "dedupe_key": row.dedupe_key})
    db.flush()
    return other


# --------------------------------------------------------------------------- queries
def to_dict(row: BrainDecision, *, full: bool = False) -> dict:
    """Decision card for the Decision Center; ``full=True`` adds the reasoning.

    The card stays short on purpose (§84): title, status, the recommended action
    and its money estimate. Options, evidence and the policy verdict are only in
    the expanded payload — the manager who wants the reasoning asks for it.
    """
    options = _json(row.options, [])
    chosen = next((o for o in options if o.get("id") == (row.selected_option or row.recommended_option)), None)
    card = {
        "id": row.id, "title": row.title, "status": row.status, "priority": row.priority,
        "decision_kind": row.decision_kind, "origin": row.origin,
        "requires_approval": bool(row.requires_approval),
        "confidence": row.confidence, "reason": row.reason, "problem": row.problem,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "selected_option": row.selected_option, "recommended_option": row.recommended_option,
        "action_label": (chosen or {}).get("label") or "",
        "gain_toman": float(row.measured_gain) if row.measured_gain is not None
        else float(((chosen or {}).get("economics") or {}).get("gain_toman") or 0),
        "measured_gain": float(row.measured_gain) if row.measured_gain is not None else None,
        "outcome": row.outcome, "priority_label": fa.priority_label(row.priority),
        "status_label": fa.status_label(row.status),
        "local_decision": bool(row.local_decision), "pending_sync": bool(row.pending_sync),
        "conflict_with": row.conflict_with,
        "followup_due": (_json(row.measurement, {}) or {}).get("followup_days"),
    }
    if not full:
        return card
    card.update({
        "situation": _json(row.situation, {}), "evidence": _json(row.evidence, []),
        "options": options, "risks": _json(row.risks, []), "actions": _json(row.actions, []),
        "approval": _json(row.approval, {}), "execution": _json(row.execution, {}),
        "measurement": _json(row.measurement, {}), "result": _json(row.result, {}),
        "policy_verdict": _json(row.policy_verdict, {}), "history": _json(row.history, []),
        "tool_trace": _json(row.tool_trace, []),
        "executed_at": _executed_at(row).isoformat() if _executed_at(row) else None,
    })
    return card


def list_decisions(db: Session, *, status: str | None = None, origin: str | None = None, limit: int = 50,
                   offset: int = 0,
                   since: datetime | None = None) -> list[dict]:
    q = select(BrainDecision).order_by(BrainDecision.created_at.desc()).limit(limit)
    if status and status != "ALL":
        q = select(BrainDecision).where(BrainDecision.status.in_(status.split(","))) \
            .order_by(BrainDecision.created_at.desc()).limit(limit)
    if origin:
        q = select(BrainDecision).where(BrainDecision.origin == origin).order_by(BrainDecision.created_at.desc()).limit(limit)
    if since:
        q = select(BrainDecision).where(BrainDecision.created_at >= since).order_by(BrainDecision.created_at.desc()).limit(limit)
    from .memory import decision_to_dict
    return [decision_to_dict(r) for r in db.execute(q).scalars()]


def open_count(db: Session) -> int:
    return int(db.execute(select(func.count(BrainDecision.id))
                          .where(BrainDecision.status.in_(["NEEDS_DECISION", "WAITING_APPROVAL", "RUNNING"]))
                          ).scalar_one())


def from_insight(db: Session, insight: Insight, *, user_id: int | None = None) -> BrainDecision | None:
    """Bridge: an accepted insight becomes a decision record too.

    This is how v3.x suggestions inherit the v4.0 reasoning/measurement/memory
    story without the insight table being rewritten.
    """
    key = f"insight:{insight.id}"
    exists = db.execute(select(BrainDecision).where(BrainDecision.dedupe_key == key)).scalar_one_or_none()
    if exists:
        return exists
    actions = _json(insight.actions, [])
    spec = _json(insight.metric, {})
    contract = build_measurement(metric=spec.get("metric") or "avg_basket_size",
                                 window_days=int(spec.get("window_days") or 28),
                                 entities={k: v for k, v in spec.items() if k != "window_days"},
                                 success_rule="پیشرفت سنجهٔ همان insight در بازهٔ بعد از اجرا")
    return create(db, title=insight.title, problem=insight.body, reason="پیشنهاد موتور تحلیل v3.x",
                  options=[{"id": "accept", "label": "اجرای پیشنهاد", "description": insight.body,
                            "actions": actions, "risk": "medium", "reversible": True,
                            "economics": {"expected_gain": float(insight.expected_gain or 0)}}],
                  evidence=[{"domain": "analyzer", "summary": insight.body,
                             "numbers": _json(insight.evidence, {})}],
                  situation={}, selected_option="accept", decision_kind=insight.kind,
                  measurement=contract, origin="ANALYZER", user_id=user_id, insight_id=insight.id,
                  dedupe_key=key, actions=actions, requires_approval=True)


# --------------------------------------------------------------------------- helpers
def _json(raw, default):
    try:
        return json.loads(raw) if raw else default
    except (TypeError, ValueError):
        return default


def _executed_at(row: BrainDecision) -> datetime | None:
    try:
        history = json.loads(row.history or "[]")
    except ValueError:
        return None
    for entry in reversed(history):
        if entry.get("status") in ("COMPLETED", "MONITORING"):
            try:
                return datetime.fromisoformat(entry["at"])
            except (KeyError, ValueError):
                return None
    return None
