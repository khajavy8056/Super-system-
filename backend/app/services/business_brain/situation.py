"""v4.0 — Situation Builder (§9).

Before the brain answers anything it builds a *business state*: identity, time,
cash, obligations, receivables, inventory, sales, customers, suppliers,
campaigns, decisions, follow-ups, data quality — each with the few numbers that
change decisions, plus the flags that say how to read them.

Two rules make this different from "load the database":

1. **Relevance, not volume.** A situation is built from tools, and tools return
   summaries plus pointers. The full row set never enters a prompt.
2. **Quality is part of the state.** If the inventory data is broken, the state
   says so (``data_quality.flags``), and every consumer — planner, proactive,
   the UI — must degrade honestly rather than compute a confident number on
   corrupt input (§10, acceptance scenario #4).
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...models import BrainDecision, BrainFollowup
from ..timeservice import local_now, local_today
from .context import ToolContext
from .registry import REGISTRY
from .schemas import Situation
from . import persian as fa


def _hash(payload: dict) -> str:
    blob = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def build(db: Session, ctx: ToolContext | None = None, *, light: bool = False) -> Situation:
    """Assemble the situation.

    ``light=True`` skips the two expensive aggregates (segment analysis and the
    cash projection) — used by the proactive scanner, which runs on a timer and
    only needs the fact flags.
    """
    ctx = ctx or ToolContext(db=db, system=True)
    situation = Situation(generated_at=datetime.utcnow())
    situation.time = {"utc": datetime.utcnow().isoformat(), "local": local_now().isoformat(),
                      "today": local_today().isoformat(), "today_fa": fa.fa_date(local_today())}
    situation.store = REGISTRY.call_or_none(ctx, "get_store_profile").get("details", {})
    situation.cash = REGISTRY.call_or_none(ctx, "get_cash_position")
    situation.obligations = REGISTRY.call_or_none(ctx, "get_upcoming_cheques", {"days": 30})
    situation.receivables = REGISTRY.call_or_none(ctx, "get_receivables")
    situation.inventory = REGISTRY.call_or_none(ctx, "get_inventory_summary")
    situation.sales = REGISTRY.call_or_none(ctx, "get_sales_trend", {"days": 7})
    situation.data_quality = REGISTRY.call_or_none(ctx, "get_data_quality")
    if not light:
        situation.cash["forecast"] = REGISTRY.call_or_none(ctx, "get_cash_forecast", {"days": 14})
        situation.customers = REGISTRY.call_or_none(ctx, "get_customer_segment")
        situation.inventory["expiry_risk"] = REGISTRY.call_or_none(ctx, "get_expiry_risk", {"days": 30})
        situation.inventory["overstock"] = REGISTRY.call_or_none(ctx, "get_overstock")
        situation.inventory["stockout"] = REGISTRY.call_or_none(ctx, "get_stockout_risk", {"days": 14})
        situation.campaigns = REGISTRY.call_or_none(ctx, "get_active_campaigns")
    else:
        situation.inventory["expiry_risk"] = REGISTRY.call_or_none(ctx, "get_expiry_risk", {"days": 30})
        situation.campaigns = REGISTRY.call_or_none(ctx, "get_active_campaigns")
    situation.decisions = _decisions_block(db)
    situation.followups = REGISTRY.call_or_none(ctx, "get_open_followups")
    situation.suppliers = REGISTRY.call_or_none(ctx, "get_payables")
    situation.tool_trace = ctx.trace_payload()
    situation.flags = _flags(situation)
    situation.state_hash = _hash({"cash": situation.cash.get("numbers", {}),
                                  "sales": situation.sales.get("numbers", {}),
                                  "inventory": situation.inventory.get("numbers", {}),
                                  "dq": situation.data_quality.get("numbers", {}),
                                  "flags": situation.flags})
    return situation


def _decisions_block(db: Session) -> dict:
    rows = db.execute(select(BrainDecision).order_by(BrainDecision.id.desc()).limit(20)).scalars().all()
    open_rows = [r for r in rows if r.status in ("NEEDS_DECISION", "WAITING_APPROVAL", "RUNNING", "MONITORING")]
    measured = [r for r in rows if r.measured_gain is not None]
    return {"recent_count": len(rows), "open_count": len(open_rows), "measured_count": len(measured),
            "open": [{"id": r.id, "title": r.title, "status": r.status, "kind": r.decision_kind} for r in open_rows[:5]],
            "last_measured": ({"id": measured[0].id, "title": measured[0].title,
                               "gain": float(measured[0].measured_gain or 0),
                               "outcome": measured[0].outcome} if measured else None)}


def _flags(s: Situation) -> list[str]:
    """The read-me-first list: what would make a naive number misleading."""
    flags: list[str] = []
    cash = s.cash.get("numbers", {}) if s.cash else {}
    if cash.get("cash_available") is not None and cash.get("reserve_floor"):
        if float(cash["cash_available"]) < float(cash["reserve_floor"]):
            flags.append("CASH_BELOW_RESERVE")
    forecast_block = (s.cash.get("forecast") or {}) if s.cash else {}
    forecast = forecast_block.get("numbers", {}) or {}
    forecast_flags = set(forecast_block.get("flags") or [])
    if (forecast.get("breach_days") or (forecast.get("min_projected_cash") or 0) < 0
            or forecast.get("days_below_safety")):
        flags.append("CASH_GAP_AHEAD")
    if (forecast.get("min_projected_cash") or 0) < 0:
        flags.append("CASH_NEGATIVE_AHEAD")
    # the expected path survives, but only because the collections land — say so
    if "CASH_FRAGILE" in forecast_flags or (forecast.get("min_without_collections") or 0) < 0 \
            and (forecast.get("min_projected_cash") or 0) >= 0:
        flags.append("CASH_FRAGILE")
    if (s.data_quality.get("flags") or []):
        flags.append("DATA_QUALITY_BLOCKED")
    elif (s.data_quality.get("numbers", {}) or {}).get("critical"):
        flags.append("DATA_QUALITY_CRITICAL")
    elif (s.data_quality.get("numbers", {}) or {}).get("high"):
        flags.append("DATA_QUALITY_DEGRADED")
    expiry = (s.inventory.get("expiry_risk") or {}).get("numbers", {}) if s.inventory else {}
    if expiry.get("at_risk_value"):
        flags.append("EXPIRY_RISK")
    stockout = (s.inventory.get("stockout") or {}).get("numbers", {}) if s.inventory else {}
    if stockout.get("count"):
        flags.append("STOCKOUT_RISK")
    if (s.sales.get("flags") or []):
        flags.append("SALES_DROP")
    if (s.obligations.get("numbers", {}) or {}).get("overdue_count"):
        flags.append("CHEQUE_OVERDUE")
    followups = (s.followups.get("numbers") or {}) if s.followups else {}
    if followups.get("overdue"):
        flags.append("FOLLOWUP_OVERDUE")
    return flags


def summary_for_prompt(s: Situation, *, max_chars: int = 2200) -> str:
    """Bounded text form. Never the whole state, never customer identities."""
    from .store_profile import StoreProfile

    profile = StoreProfile(declared=(s.store.get("declared") or {}), observed=(s.store.get("observed") or {}))
    parts = [f"امروز {s.time.get('today_fa')}", "پروفایل: " + profile.digest(), s.digest()]
    text = "\n".join(p for p in parts if p)
    return text[:max_chars]


def situation_hash(db: Session, ctx: ToolContext | None = None) -> str:
    return build(db, ctx, light=True).state_hash
