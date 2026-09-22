"""v4.0 — the three layers of memory (§11, §56, §57).

| layer | table | what it remembers | who writes it |
|---|---|---|---|
| conversation | ``brain_messages`` | what the owner asked and what the brain answered (with the tool trace) | the chat layer |
| decision | ``brain_decisions`` | what was decided, why, what was executed, what it produced | the planner + Action Engine + measurer |
| business facts | ``brain_memory_facts`` | durable knowledge: supplier lead times, campaign payback, churn patterns | the learners below |
| policy | ``brain_policies`` | the owner's rules | the owner (``policies.py``) |

The retrieval here is **deterministic**: tokens, entity ids and time windows —
no embeddings, no vector store, no dependency. It has to work on a 4 GB phone
with no internet, and it has to be explainable: if the brain recalls a decision,
it can say exactly which row it read.

§57 is respected literally: nothing in this module calls "learning" what is
merely *storing a conversation*. Learning here means a later decision can find
the earlier outcome and act differently because of it.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ...models import BrainDecision, BrainFollowup, BrainMemoryFact, BrainMessage, Campaign, Invoice, Supplier
from . import persian as fa

#: fact kinds that may be learned automatically
LEARNABLE_KINDS = ("SUPPLIER", "CAMPAIGN", "PRODUCT", "CUSTOMER", "PATTERN")
#: every kind a fact row may carry (``LEARNABLE_KINDS`` are the ones the brain
#: writes on its own; the rest are recorded by the owner or by a measurement)
KINDS = ("SUPPLIER", "CAMPAIGN", "PRODUCT", "CUSTOMER", "PATTERN", "EVENT", "DATA", "OWNER")


# --------------------------------------------------------------------------- conversation memory
def log_message(db: Session, *, session_key: str, role: str, content: str, tool_trace: list | None = None,
                meta: dict | None = None, decision_id: int | None = None, user_id: int | None = None,
                local_decision: bool = False, pending_sync: bool = False) -> BrainMessage:
    row = BrainMessage(session_key=session_key or "default", role=role, content=content or "",
                       tool_trace=json.dumps(tool_trace or [], ensure_ascii=False, default=str),
                       meta=json.dumps(meta or {}, ensure_ascii=False, default=str),
                       decision_id=decision_id, user_id=user_id,
                       local_decision=local_decision, pending_sync=pending_sync)
    db.add(row)
    db.flush()
    return row


def conversation(db: Session, *, session_key: str = "default", limit: int = 20) -> list[dict]:
    rows = db.execute(select(BrainMessage).where(BrainMessage.session_key == session_key)
                      .order_by(BrainMessage.id.desc()).limit(limit)).scalars().all()
    return [{"id": r.id, "role": r.role, "content": r.content, "at": r.created_at.isoformat() if r.created_at else None,
             "decision_id": r.decision_id} for r in reversed(rows)]


def conversation_digest(db: Session, *, session_key: str = "default", limit: int = 6) -> str:
    """Last few turns as text for the prompt — bounded, never the whole history."""
    rows = conversation(db, session_key=session_key, limit=limit)
    lines = []
    for r in rows:
        who = "مدیر" if r["role"] == "USER" else "سیستم"
        lines.append(f"{who}: {r['content'][:300]}")
    return "\n".join(lines)


def last_user_intent(db: Session, *, session_key: str = "default", within_minutes: int = 30) -> dict:
    """What the owner was talking about — used for «این» / «همون» continuity (§70)."""
    # the meta (intent + resolved entities) is written on the ASSISTANT row, so the
    # lookup must not be restricted to the owner's own messages — otherwise
    # «این کالا» / «۵ روز» lose the subject they refer to.
    rows = db.execute(select(BrainMessage).where(BrainMessage.session_key == session_key,
                                                 BrainMessage.role.in_(("USER", "ASSISTANT")))
                      .order_by(BrainMessage.id.desc()).limit(8)).scalars().all()
    cutoff = datetime.utcnow() - timedelta(minutes=within_minutes)
    for r in rows:
        if r.created_at and r.created_at >= cutoff:
            try:
                meta = json.loads(r.meta or "{}")
            except ValueError:
                meta = {}
            if meta.get("entities") or meta.get("intent"):
                return {"text": r.content, "meta": meta, "at": r.created_at.isoformat()}
    return {}


def pending_context(db: Session, *, session_key: str = "default") -> dict:
    """Unanswered decision + its entities — «پس اجراش کن» must find them."""
    text = last_user_intent(db, session_key=session_key)
    row = db.execute(select(BrainDecision).where(BrainDecision.status.in_(["NEEDS_DECISION", "WAITING_APPROVAL"]))
                     .order_by(BrainDecision.id.desc()).limit(1)).scalar_one_or_none()
    return {"intent": text, "decision": decision_to_dict(row) if row else None}


# --------------------------------------------------------------------------- business facts
def remember(db: Session, *, kind: str, key: str, value: dict, confidence: float = 0.5,
             source: str = "ANALYZER", reference_type: str | None = None, reference_id: int | None = None,
             ttl_days: int | None = None) -> BrainMemoryFact:
    """Upsert one fact. Confidence grows with repeated, agreeing observations."""
    row = db.execute(select(BrainMemoryFact).where(BrainMemoryFact.kind == kind,
                                                   BrainMemoryFact.key == key)).scalar_one_or_none()
    now = datetime.utcnow()
    expires = now + timedelta(days=ttl_days) if ttl_days else None
    if row is None:
        row = BrainMemoryFact(kind=kind, key=key, value=json.dumps(value, ensure_ascii=False, default=str),
                              confidence=confidence, source=source, reference_type=reference_type,
                              reference_id=reference_id, observed_at=now, expires_at=expires)
        db.add(row)
    else:
        # read the PREVIOUS value before overwriting it — a repeated agreeing
        # observation raises confidence, a contradiction resets it downwards.
        try:
            previous = json.loads(row.value or "{}")
        except ValueError:
            previous = {}
        agree = previous == value
        row.value = json.dumps(value, ensure_ascii=False, default=str)
        row.confidence = min(0.95, float(row.confidence or 0.5) + 0.1) if agree \
            else max(0.2, confidence * 0.8)
        row.source = source
        row.observed_at = now
        row.expires_at = expires
        row.reference_type, row.reference_id = reference_type, reference_id
    db.flush()
    return row


def recall(db: Session, kind: str, key: str) -> dict | None:
    row = db.execute(select(BrainMemoryFact).where(BrainMemoryFact.kind == kind,
                                                   BrainMemoryFact.key == key)).scalar_one_or_none()
    if row is None:
        return None
    if row.expires_at and row.expires_at <= datetime.utcnow():
        return None
    try:
        return json.loads(row.value or "{}")
    except ValueError:
        return None


def facts(db: Session, *, kind: str | None = None, min_confidence: float = 0.0, limit: int = 50) -> list[dict]:
    q = select(BrainMemoryFact).order_by(BrainMemoryFact.observed_at.desc())
    if kind:
        q = select(BrainMemoryFact).where(BrainMemoryFact.kind == kind).order_by(BrainMemoryFact.observed_at.desc())
    out = []
    for row in db.execute(q.limit(limit * 2)).scalars():
        if float(row.confidence or 0) < min_confidence:
            continue
        if row.expires_at and row.expires_at <= datetime.utcnow():
            continue
        try:
            value = json.loads(row.value or "{}")
        except ValueError:
            value = {}
        out.append({"id": row.id, "kind": row.kind, "key": row.key, "value": value,
                    "confidence": round(float(row.confidence or 0), 2), "source": row.source,
                    "observed_at": row.observed_at.isoformat() if row.observed_at else None})
        if len(out) >= limit:
            break
    return out


# --------------------------------------------------------------------------- learners (§56)
def learn_from_campaign(db: Session, campaign: Campaign) -> dict:
    """Did the promotion pay for itself? Recorded so the next one is smarter."""
    from .. import insights as ins_svc
    from .tools import _sales_between
    from .context import ToolContext

    start = campaign.valid_from or campaign.created_at
    end = campaign.valid_until or (start + timedelta(days=7))
    days = max(1, (end - start).days)
    ctx = ToolContext(db=db, system=True)
    during = _sales_between(ctx, start, end)
    before = _sales_between(ctx, start - timedelta(days=days), start)
    delta = during["profit"] - before["profit"]
    value = {"campaign_id": campaign.id, "name": campaign.name, "window_days": days,
             "profit_delta": round(delta), "revenue_delta": round(during["revenue"] - before["revenue"]),
             "discount": float(campaign.discount_value or 0), "verdict": "POSITIVE" if delta > 0 else
             ("NEGATIVE" if delta < 0 else "NEUTRAL")}
    remember(db, kind="CAMPAIGN", key=f"campaign:{campaign.id}:outcome", value=value,
             confidence=0.7, source="MEASUREMENT", reference_type="Campaign", reference_id=campaign.id)
    return value


def learn_from_decisions(db: Session, *, limit: int = 200) -> dict:
    """Turn measured decisions into durable facts (the §56 learning step).

    Only decisions the deterministic measurer has already scored are used — a
    decision without a measurement teaches nothing and is skipped rather than
    guessed at.
    """
    rows = db.execute(select(BrainDecision).where(BrainDecision.outcome.isnot(None))
                      .order_by(BrainDecision.measured_at.desc()).limit(limit)).scalars().all()
    learned: dict[str, int] = {}
    for row in rows:
        key = f"kind:{row.decision_kind or 'unknown'}"
        agg = recall(db, "PATTERN", key) or {"n": 0, "gain": 0.0, "positive": 0}
        gain = float(row.measured_gain or 0)
        agg["n"] = int(agg.get("n", 0)) + 1
        agg["gain"] = float(agg.get("gain", 0)) + gain
        if gain > 0:
            agg["positive"] = int(agg.get("positive", 0)) + 1
        agg["avg_gain"] = round(agg["gain"] / max(1, agg["n"]))
        agg["win_rate"] = round(agg["positive"] / max(1, agg["n"]), 2)
        remember(db, kind="PATTERN", key=key, value=agg,
                 confidence=min(0.9, 0.4 + 0.1 * agg["n"]), source="MEASUREMENT",
                 reference_type="BrainDecision", reference_id=row.id)
        learned[key] = agg["n"]
    return {"patterns": learned, "count": len(learned)}


def pattern_for(db: Session, decision_kind: str) -> dict | None:
    """The brain's own track record for this class of decision, if it has one."""
    return recall(db, "PATTERN", f"kind:{decision_kind}")


def remember_supplier_behaviour(db: Session, *, supplier_id: int) -> dict | None:
    """Lead time and shelf-life behaviour — learned from this shop's own receipts."""
    from ...models import ProductBatch

    supplier = db.get(Supplier, supplier_id)
    if supplier is None:
        return None
    batches = db.execute(select(ProductBatch).where(ProductBatch.supplier_id == supplier_id)
                         .order_by(ProductBatch.received_at.desc()).limit(60)).scalars().all()
    leads = [(b.received_at.date() - b.production_date).days for b in batches
             if b.received_at and b.production_date and 0 <= (b.received_at.date() - b.production_date).days <= 180]
    shelf = [(b.expiry_date - b.production_date).days for b in batches
             if b.expiry_date and b.production_date and 0 < (b.expiry_date - b.production_date).days <= 3650]
    value = {"supplier_id": supplier_id, "name": supplier.name,
             "lead_time_days": round(sum(leads) / len(leads), 1) if leads else None,
             "median_shelf_life_days": sorted(shelf)[len(shelf) // 2] if shelf else None,
             "shipments_seen": len(batches)}
    if not leads and not shelf:
        return None
    return {"key": f"supplier:{supplier_id}:behaviour",
            "value": remember(db, kind="SUPPLIER", key=f"supplier:{supplier_id}:behaviour", value=value,
                              confidence=min(0.85, 0.35 + 0.05 * len(batches)), source="ANALYZER",
                              reference_type="Supplier", reference_id=supplier_id, ttl_days=180) and value}


# --------------------------------------------------------------------------- shared serializer
def decision_to_dict(row: BrainDecision | None) -> dict | None:
    if row is None:
        return None

    def j(raw, default):
        try:
            return json.loads(raw) if raw else default
        except (TypeError, ValueError):
            return default

    return {
        "id": row.id, "type": row.type, "title": row.title, "problem": row.problem,
        "objective": row.objective, "situation": j(row.situation, {}), "evidence": j(row.evidence, []),
        "options": j(row.options, []), "recommended_option": row.recommended_option,
        "selected_option": row.selected_option, "reason": row.reason, "risks": j(row.risks, []),
        "confidence": row.confidence, "policy_verdict": j(row.policy_verdict, {}),
        "requires_approval": bool(row.requires_approval), "actions": j(row.actions, []),
        "approval": j(row.approval, {}), "execution": j(row.execution, {}),
        "measurement": j(row.measurement, {}), "result": j(row.result, {}),
        "measured_gain": float(row.measured_gain) if row.measured_gain is not None else None,
        "outcome": row.outcome, "status": row.status, "decision_kind": row.decision_kind,
        "priority": row.priority, "history": j(row.history, []), "origin": row.origin,
        "local_decision": bool(row.local_decision), "pending_sync": bool(row.pending_sync),
        "conflict_with": row.conflict_with, "insight_id": row.insight_id,
        "tool_trace": j(row.tool_trace, []),
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        "measured_at": row.measured_at.isoformat() if row.measured_at else None,
    }


def stats(db: Session) -> dict:
    """Small honest numbers for the Decision Center header."""
    total = db.execute(select(func.count(BrainDecision.id))).scalar_one()
    open_rows = db.execute(select(func.count(BrainDecision.id))
                           .where(BrainDecision.status.in_(["NEEDS_DECISION", "WAITING_APPROVAL", "RUNNING",
                                                            "MONITORING", "COMPLETED"]))).scalar_one()
    measured = db.execute(select(func.coalesce(func.sum(BrainDecision.measured_gain), 0))
                          .where(BrainDecision.outcome.isnot(None))).scalar_one()
    open_followups = db.execute(select(func.count(BrainFollowup.id))
                                .where(BrainFollowup.status == "OPEN")).scalar_one()
    conversations = db.execute(select(func.count(BrainMessage.id))).scalar_one()
    facts_n = db.execute(select(func.count(BrainMemoryFact.id))).scalar_one()
    return {"decisions": int(total), "open": int(open_rows), "measured_gain": float(measured or 0),
            "followups_open": int(open_followups), "messages": int(conversations), "facts": int(facts_n),
            "measured_gain_label": fa.toman_short(measured or 0) + " تومان"}
