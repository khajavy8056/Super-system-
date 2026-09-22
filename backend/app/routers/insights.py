"""v3.0 — Store Intelligence API («هوش فروشگاه»)."""
from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Insight, User
from ..security import get_current_user, require_permission
from ..services import ai_narrator, insight_actions
from ..services import insights as svc

router = APIRouter(prefix="/insights", tags=["insights"])


class AcceptIn(BaseModel):
    actions: list[str] | None = None   # subset of action types; None = all


class SnoozeIn(BaseModel):
    days: int = 7


class NudgeIn(BaseModel):
    product_ids: list[int]


def _get(db: Session, insight_id: int) -> Insight:
    row = db.get(Insight, insight_id)
    if not row:
        raise HTTPException(status_code=404, detail="INSIGHT_NOT_FOUND")
    return row


@router.get("")
def list_insights(status: str = Query("NEW"), kind: str | None = None, limit: int = 50, group: str | None = None,
                  db: Session = Depends(get_db), _: User = Depends(require_permission("reports.view"))):
    q = select(Insight)
    if status and status != "ALL":
        q = q.where(Insight.status.in_(status.split(",")))
    if kind:
        q = q.where(Insight.kind == kind)
    if group and group in svc.GROUPS:
        q = q.where(Insight.kind.in_(svc.GROUPS[group][1]))
    q = q.order_by(Insight.priority.asc(), Insight.expected_gain.desc(), Insight.created_at.desc()).limit(limit)
    return [svc.to_dict(r) for r in db.execute(q).scalars()]


@router.get("/summary")
def summary(db: Session = Depends(get_db), _: User = Depends(require_permission("reports.view"))):
    out = svc.impact_summary(db)
    out["kinds"] = [{"kind": k, "label": v} for k, v in svc.KIND_LABELS.items()]
    out["ai"] = ai_narrator.configured(db)
    return out


@router.post("/run")
def run_now(kinds: str | None = None, days: int = 90, db: Session = Depends(get_db),
            _: User = Depends(require_permission("reports.view"))):
    return svc.run(db, kinds=kinds.split(",") if kinds else None, days=days)


@router.get("/report")
def report(db: Session = Depends(get_db), _: User = Depends(require_permission("reports.view"))):
    s = svc.impact_summary(db)
    open_rows = [svc.to_dict(r) for r in db.execute(select(Insight).where(Insight.status == "NEW").order_by(Insight.priority, Insight.expected_gain.desc()).limit(10)).scalars()]
    return {"summary": s, "open": open_rows, "narrative": ai_narrator.weekly_report(db, s, open_rows), "generated_at": datetime.utcnow().isoformat()}


@router.get("/plan")
def plan(horizon: int = Query(90, ge=14, le=365), db: Session = Depends(get_db), _: User = Depends(require_permission("reports.view"))):
    """v3.1 — profit forecast (baseline vs. plan), calibrated gain per open suggestion, accuracy history."""
    from ..services import forecast
    return forecast.plan(db, horizon=horizon)


@router.post("/plan/learn")
def plan_learn(db: Session = Depends(get_db), _: User = Depends(require_permission("reports.view"))):
    from ..services import forecast
    return {"ok": True, "calibration": forecast.learn(db)}


@router.get("/data-quality")
def data_quality(db: Session = Depends(get_db), _: User = Depends(require_permission("reports.view"))):
    """v3.8 — the Data Quality report the intelligence engine gates on."""
    from ..services import data_quality as dq
    return dq.run_all(db)


@router.get("/customers/patterns")
def customer_patterns(days: int = Query(7, ge=0, le=30), db: Session = Depends(get_db), _: User = Depends(require_permission("reports.view"))):
    """v3.2 — per-customer purchase rhythm: who is due in the next `days` days, their usual weekday,
    hour and items (for the customer-prediction screen on Windows and Android)."""
    ctx = svc._load_ctx(db, 180)
    rows = svc.customer_patterns(ctx, horizon_days=days)
    return {"today": ctx.today.isoformat(), "horizon_days": days, "rows": rows}


# ---------------------------------------------------------------- v3.5 AI advisor (free providers)
class PresetIn(BaseModel):
    preset: str
    api_key: str | None = None


@router.get("/ai/presets")
def ai_presets(db: Session = Depends(get_db), _: User = Depends(require_permission("settings.manage"))):
    return {"presets": ai_narrator.presets(), "current": ai_narrator.configured(db)}


@router.post("/ai/preset")
def ai_apply_preset(body: PresetIn, db: Session = Depends(get_db), _: User = Depends(require_permission("settings.manage"))):
    try:
        if body.api_key:
            insight_actions._set_setting(db, "ai.api_key", body.api_key.strip())
        return ai_narrator.apply_preset(db, body.preset)
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@router.post("/ai/test")
def ai_test(db: Session = Depends(get_db), _: User = Depends(require_permission("settings.manage"))):
    return ai_narrator.test_connection(db)


@router.get("/ai/report")
def ai_report(db: Session = Depends(get_db), _: User = Depends(require_permission("reports.view"))):
    """What would be sent — shown to the owner before anything leaves the machine."""
    return ai_narrator.build_report(db)


@router.post("/ai/advise")
def ai_advise(db: Session = Depends(get_db), user: User = Depends(require_permission("settings.manage"))):
    try:
        return ai_narrator.ask_advisor(db, user=user)
    except RuntimeError as exc:
        raise HTTPException(409, str(exc))
    except Exception as exc:
        raise HTTPException(502, ai_narrator._friendly_error(exc))


@router.get("/groups")
def groups(db: Session = Depends(get_db), _: User = Depends(require_permission("reports.view"))):
    """Kind groups with open counts — the tab strip of the intelligence page."""
    rows = db.execute(select(Insight.kind, func.count(Insight.id)).where(Insight.status == "NEW").group_by(Insight.kind)).all()
    cnt = {k: n for k, n in rows}
    out = []
    for gid, (label, kinds) in svc.GROUPS.items():
        out.append({"id": gid, "label": label, "kinds": kinds, "open": sum(cnt.get(k, 0) for k in kinds)})
    return {"groups": out, "analyzers": len(svc.ANALYZERS)}


@router.get("/{insight_id}")
def get_insight(insight_id: int, narrate: bool = False, db: Session = Depends(get_db), _: User = Depends(require_permission("reports.view"))):
    row = _get(db, insight_id)
    if narrate:
        ai_narrator.narrate(db, row)
        db.commit()
    out = svc.to_dict(row)
    if row.status in ("NEW", "SNOOZED"):
        from ..services import forecast
        try:
            out["prediction"] = forecast.predict_for(db, row)   # v3.1 what-if: profit path if executed
        except Exception:   # never break the card because of the forecast
            out["prediction"] = None
    return out


@router.post("/{insight_id}/accept")
def accept(insight_id: int, body: AcceptIn | None = None, db: Session = Depends(get_db),
           user: User = Depends(require_permission("settings.manage"))):
    row = _get(db, insight_id)
    if row.status not in ("NEW", "SNOOZED"):
        raise HTTPException(status_code=409, detail="INSIGHT_NOT_OPEN")
    res = svc.accept(db, row, user=user, action_types=body.actions if body else None)
    return {"ok": True, **res, "insight": svc.to_dict(row)}


@router.post("/{insight_id}/dismiss")
def dismiss(insight_id: int, db: Session = Depends(get_db), user: User = Depends(require_permission("settings.manage"))):
    row = _get(db, insight_id)
    row.status = "DISMISSED"
    db.commit()
    return {"ok": True}


@router.post("/{insight_id}/snooze")
def snooze(insight_id: int, body: SnoozeIn, db: Session = Depends(get_db), user: User = Depends(require_permission("settings.manage"))):
    row = _get(db, insight_id)
    row.status = "SNOOZED"
    row.snoozed_until = datetime.utcnow() + timedelta(days=max(1, body.days))
    db.commit()
    return {"ok": True, "until": row.snoozed_until.isoformat()}


@router.post("/{insight_id}/measure")
def measure(insight_id: int, db: Session = Depends(get_db), _: User = Depends(require_permission("reports.view"))):
    row = _get(db, insight_id)
    res = svc.measure(db, row)
    db.commit()
    if res is None:
        raise HTTPException(status_code=409, detail="INSIGHT_NOT_ACCEPTED")
    return {"ok": True, **res, "insight": svc.to_dict(row)}


@router.post("/nudges")
def nudges(body: NudgeIn, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    """POS: given the cart's product ids, return up to two whisper-suggestions."""
    import json
    from ..models import SystemSetting
    on = db.execute(select(SystemSetting).where(SystemSetting.key == "insights.pos_nudges")).scalar_one_or_none()
    if not on or on.value != "true":
        return []
    out = svc.nudges(db, body.product_ids)
    manual = db.execute(select(SystemSetting).where(SystemSetting.key == "insights.manual_rules")).scalar_one_or_none()
    if manual:
        cart = set(body.product_ids)
        for r in json.loads(manual.value or "[]"):
            if r["if"] in cart and r["then"] not in cart and all(o["product_id"] != r["then"] for o in out):
                out.append({"product_id": r["then"], "name": r["then_name"], "because": r["if_name"], "confidence": r["confidence"]})
    return out[:2]


@router.get("/tasks/reorder")
def reorder_list(db: Session = Depends(get_db), _: User = Depends(require_permission("reports.view"))):
    import json
    from ..models import SystemSetting
    row = db.execute(select(SystemSetting).where(SystemSetting.key == "insights.reorder_list")).scalar_one_or_none()
    return json.loads(row.value) if row and row.value else []


@router.delete("/tasks/reorder/{product_id}")
def reorder_done(product_id: int, db: Session = Depends(get_db), _: User = Depends(require_permission("settings.manage"))):
    import json
    from ..models import SystemSetting
    row = db.execute(select(SystemSetting).where(SystemSetting.key == "insights.reorder_list")).scalar_one_or_none()
    lst = [x for x in (json.loads(row.value) if row and row.value else []) if x["product_id"] != product_id]
    insight_actions._set_setting(db, "insights.reorder_list", json.dumps(lst, ensure_ascii=False))
    db.commit()
    return lst
