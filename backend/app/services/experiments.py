# -*- coding: utf-8 -*-
"""v3.8 — durable experiment orchestration (user order §6).

``experiment_stats`` is pure mathematics; this module is the *flow* the math
module explicitly demands before any real send:

  CREATE → PLAN → ASSIGN → START → RECORD EXPOSURE → RECORD OUTCOME →
  CLOSE → EVALUATE

Honesty rules, enforced in code (not in comments):

* the seed is server-generated at CREATE, before any outcome can exist;
* the eligible population freezes at PLAN — ASSIGN can only split that set;
* arms freeze at ASSIGN and are immutable (re-assignment is refused);
* ASSIGNED ≠ EXPOSED: customers who never saw the treatment are reported,
  never silently counted as zeros;
* a MISSING outcome (no row) is never confused with a ZERO outcome;
* CLOSE is allowed only after the window elapsed, and only once;
* EVALUATE stores whatever the math says — including INSUFFICIENT_DATA —
  and links the verdict back to the originating insight. No data ⇒ no result.
"""
from __future__ import annotations

import json
import secrets
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from ..models import Experiment, Insight
from . import experiment_stats as stats
from .audit import write_audit

TERMINAL = ("COMPLETE", "CANCELLED")


class ExperimentError(ValueError):
    pass


def _loads(raw: str | None, default):
    try:
        return json.loads(raw) if raw else default
    except ValueError:
        raise ExperimentError("CORRUPT_EXPERIMENT_JSON")


def _now() -> datetime:
    return datetime.utcnow()


# ------------------------------------------------------------------ life-cycle
def create(db: Session, *, name: str, hypothesis: str = "", action_type: str = "",
           insight_id: int | None = None, window_days: int = 28,
           minimum_net_profit: float = 0.0, created_by: int | None = None) -> Experiment:
    if not (name or "").strip():
        raise ExperimentError("NAME_REQUIRED")
    if int(window_days) < 1:
        raise ExperimentError("WINDOW_TOO_SHORT")
    exp = Experiment(name=name.strip(), hypothesis=hypothesis or None, action_type=action_type,
                     insight_id=insight_id, window_days=int(window_days),
                     minimum_net_profit=str(float(minimum_net_profit)),
                     status="DRAFT", seed=secrets.token_hex(16), created_by=created_by)
    db.add(exp)
    db.flush()
    write_audit(db, action="EXPERIMENT_CREATED", user_id=created_by,
                entity_type="Experiment", entity_id=exp.id, after={"name": exp.name})
    return exp


def plan(db: Session, exp: Experiment, *, customer_ids: list[int],
         baseline_rate: float, minimum_lift: float, user_id: int | None = None) -> dict:
    """Freeze the eligible population and pre-register the required arm size."""
    if exp.status != "DRAFT":
        raise ExperimentError(f"PLAN_REQUIRES_DRAFT (is {exp.status})")
    if len(customer_ids) < 2 or len(set(customer_ids)) != len(customer_ids):
        raise ExperimentError("INVALID_ELIGIBLE_POPULATION")
    if any(type(c) is not int or c <= 0 for c in customer_ids):
        raise ExperimentError("INVALID_CUSTOMER_ID")
    exp.planned_per_arm = stats.plan_sample(baseline_rate, minimum_lift)
    exp.eligible = json.dumps(sorted(customer_ids))
    exp.status = "PLANNED"
    db.flush()
    write_audit(db, action="EXPERIMENT_PLANNED", user_id=user_id,
                entity_type="Experiment", entity_id=exp.id,
                after={"eligible": len(customer_ids), "planned_per_arm": exp.planned_per_arm})
    return {"eligible": len(customer_ids), "planned_per_arm": exp.planned_per_arm}


def assign(db: Session, exp: Experiment, *, user_id: int | None = None) -> dict:
    """Split the FROZEN eligible set into immutable arms. Exactly once."""
    if exp.status != "PLANNED":
        raise ExperimentError(f"ASSIGN_REQUIRES_PLANNED (is {exp.status})")
    if _loads(exp.treatment, []) or _loads(exp.control, []):
        raise ExperimentError("ARMS_ALREADY_FROZEN")
    eligible = _loads(exp.eligible, [])
    arms = stats.assign(eligible, exp.seed)
    exp.treatment = json.dumps(sorted(arms["treatment"]))
    exp.control = json.dumps(sorted(arms["control"]))
    exp.status = "ASSIGNED"
    db.flush()
    write_audit(db, action="EXPERIMENT_ASSIGNED", user_id=user_id,
                entity_type="Experiment", entity_id=exp.id,
                after={"treatment": len(arms["treatment"]), "control": len(arms["control"])})
    return {"treatment": len(arms["treatment"]), "control": len(arms["control"])}


def start(db: Session, exp: Experiment, *, user_id: int | None = None) -> Experiment:
    if exp.status != "ASSIGNED":
        raise ExperimentError(f"START_REQUIRES_ASSIGNED (is {exp.status})")
    exp.status = "RUNNING"
    exp.started_at = _now()
    db.flush()
    write_audit(db, action="EXPERIMENT_STARTED", user_id=user_id,
                entity_type="Experiment", entity_id=exp.id)
    return exp


def _arms(exp: Experiment) -> tuple[set[int], set[int]]:
    return set(_loads(exp.treatment, [])), set(_loads(exp.control, []))


def record_exposure(db: Session, exp: Experiment, customer_id: int) -> dict:
    """The customer actually SAW the treatment (opened the SMS, got the coupon…)."""
    if exp.status != "RUNNING":
        raise ExperimentError(f"EXPOSURE_REQUIRES_RUNNING (is {exp.status})")
    t, c = _arms(exp)
    if customer_id not in t and customer_id not in c:
        raise ExperimentError("CUSTOMER_NOT_ASSIGNED")
    exposed = _loads(exp.exposed, {})
    exposed[str(customer_id)] = _now().isoformat(timespec="seconds")
    exp.exposed = json.dumps(exposed)
    db.flush()
    return {"exposed": len(exposed), "assigned": len(t) + len(c)}


def record_outcome(db: Session, exp: Experiment, customer_id: int, *,
                   profit: float, purchased: bool,
                   variable_cost: float | None) -> dict:
    """Store one REAL outcome. Absent customers stay absent — never auto-zeroed."""
    if exp.status not in ("RUNNING", "OBSERVING"):
        raise ExperimentError(f"OUTCOME_REQUIRES_OPEN_WINDOW (is {exp.status})")
    t, c = _arms(exp)
    if customer_id not in t and customer_id not in c:
        raise ExperimentError("CUSTOMER_NOT_ASSIGNED")
    if not isinstance(purchased, bool):
        raise ExperimentError("INVALID_PURCHASE_FLAG")
    outcomes = _loads(exp.outcomes, {})
    outcomes[str(customer_id)] = {"profit": float(profit), "purchased": purchased,
                                  "variable_cost": variable_cost}
    exp.outcomes = json.dumps(outcomes)
    db.flush()
    return {"outcomes": len(outcomes)}


def coverage(exp: Experiment) -> dict:
    t, c = _arms(exp)
    outcomes = _loads(exp.outcomes, {})
    exposed = _loads(exp.exposed, {})
    t_out = sum(1 for cid in t if str(cid) in outcomes)
    c_out = sum(1 for cid in c if str(cid) in outcomes)
    return {"assigned_treatment": len(t), "assigned_control": len(c),
            "outcomes_treatment": t_out, "outcomes_control": c_out,
            "exposed": len(exposed),
            "missing": sorted((t | c) - {int(k) for k in outcomes})}


def close(db: Session, exp: Experiment, *, user_id: int | None = None) -> dict:
    """Close the window — only after it elapsed, and only once."""
    if exp.status in TERMINAL or exp.status == "OBSERVING":
        raise ExperimentError(f"WINDOW_ALREADY_CLOSED (is {exp.status})")
    if exp.status != "RUNNING" or not exp.started_at:
        raise ExperimentError(f"CLOSE_REQUIRES_RUNNING (is {exp.status})")
    if _now() < exp.started_at + timedelta(days=exp.window_days):
        raise ExperimentError("WINDOW_NOT_ELAPSED")
    exp.status = "OBSERVING"
    exp.closed_at = _now()
    db.flush()
    cov = coverage(exp)
    write_audit(db, action="EXPERIMENT_CLOSED", user_id=user_id,
                entity_type="Experiment", entity_id=exp.id, after=cov)
    return cov


def evaluate(db: Session, exp: Experiment, *, user_id: int | None = None,
             seed: int = 0) -> dict:
    """Run the pre-registered math on RECORDED outcomes only.

    Stores the verdict — including INSUFFICIENT_DATA — and links it to the
    originating insight. COMPLETE is set only when the math itself evaluated.
    """
    if exp.status not in ("OBSERVING", "COMPLETE"):
        raise ExperimentError(f"EVALUATE_REQUIRES_CLOSED_WINDOW (is {exp.status})")
    t, c = _arms(exp)
    outcomes = _loads(exp.outcomes, {})

    def rows(arm: set[int]) -> list[dict]:
        rs = []
        for cid in sorted(arm):
            o = outcomes.get(str(cid))
            if o is None:
                continue  # missing stays missing — never invented as zero
            rs.append({"customer_id": cid, "profit": o["profit"],
                       "purchased": o["purchased"], "variable_cost": o["variable_cost"]})
        return rs

    res = stats.evaluate(rows(t), rows(c), planned_per_arm=exp.planned_per_arm,
                         window_closed=True,
                         minimum_net_profit=float(exp.minimum_net_profit or 0),
                         seed=seed)
    cov = coverage(exp)
    res["coverage"] = cov
    res["exposure_rate"] = (round(cov["exposed"] / (cov["assigned_treatment"] + cov["assigned_control"]), 3)
                            if (cov["assigned_treatment"] + cov["assigned_control"]) else 0.0)
    exp.result = json.dumps(res, ensure_ascii=False, default=str)
    if res.get("status") == "COMPLETE":
        exp.status = "COMPLETE"
    if exp.insight_id:
        ins = db.get(Insight, exp.insight_id)
        if ins is not None:
            try:
                ev = json.loads(ins.evidence or "{}")
            except ValueError:
                ev = {}
            ev["experiment"] = {"id": exp.id, "name": exp.name,
                                "decision": res.get("decision"),
                                "status": res.get("status"),
                                "net_profit_per_customer": res.get("net_profit_per_customer"),
                                "interval": res.get("net_profit_interval")}
            ins.evidence = json.dumps(ev, ensure_ascii=False, default=str)
    db.flush()
    write_audit(db, action="EXPERIMENT_EVALUATED", user_id=user_id,
                entity_type="Experiment", entity_id=exp.id,
                after={"decision": res.get("decision"), "status": res.get("status")})
    return res


def cancel(db: Session, exp: Experiment, *, user_id: int | None = None) -> Experiment:
    if exp.status in TERMINAL:
        raise ExperimentError(f"ALREADY_TERMINAL (is {exp.status})")
    exp.status = "CANCELLED"
    db.flush()
    write_audit(db, action="EXPERIMENT_CANCELLED", user_id=user_id,
                entity_type="Experiment", entity_id=exp.id)
    return exp
