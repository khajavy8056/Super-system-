"""v4.0 — Business Brain API («مغز کسب‌وکار»).

Contract, in one screen:

* every route requires ``reports.view``; every route that *decides*, *executes*,
  changes a policy or touches the local model additionally requires
  ``settings.manage``. The chat route requires both, i.e. the primary
  administrator — a cashier's token gets ``403`` and never reaches the manager's
  private business state (§88).
* the API never returns the raw model output, a tool's internal JSON, or
  reasoning text. It returns the answer, the evidence summary, the decision card
  and the audit identifiers.
* nothing here writes to the database directly: it asks
  :class:`~...business_brain.brain.BusinessBrain`, which goes through the Tool
  Registry, the policies and the Action Engine like every other caller.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import User
from ..security import require_permission
from ..services.business_brain import BusinessBrain, BrainDenied
from ..services.business_brain import decisions as decision_svc

router = APIRouter(prefix="/brain", tags=["brain"])

#: the "primary administrator" gate: the brain is never exposed on a single
#: permission, because `reports.view` alone belongs to cashiers as well.
def admin_user(user: User = Depends(require_permission("reports.view")),
               _: User = Depends(require_permission("settings.manage"))) -> User:
    return user



class ChatIn(BaseModel):
    question: str = Field(min_length=1, max_length=1000)
    session_key: str = Field(default="default", max_length=64)
    prefer_llm: bool = True


class DecideIn(BaseModel):
    option_id: str | None = None
    reason: str = ""
    days: int = 3


class FollowupIn(BaseModel):
    result: str = ""


class NoteIn(BaseModel):
    text: str = Field(min_length=1, max_length=500)


class DownloadIn(BaseModel):
    model_id: str | None = None


def _brain(db: Session, user: User) -> BusinessBrain:
    return BusinessBrain(db, user=user)


def _guard(fn, *args, **kwargs):
    """Translate the façade's permission error into an HTTP 403."""
    try:
        return fn(*args, **kwargs)
    except BrainDenied as exc:                                  # pragma: no cover - defensive
        raise HTTPException(status_code=403, detail=str(exc)) from exc


def _write(db: Session, fn, *args, **kwargs):
    """Run a *mutating* brain operation and make it stick.

    ``get_db`` closes the session without committing — every router in this
    product commits its own writes — so a decision that is only ``flush()``ed
    would be rolled back when the request ends: the owner would approve an
    action, watch it execute, and then find the same card back on the desk with
    no measurement appointment. Every write route below goes through here.
    """
    out = _guard(fn, *args, **kwargs)
    db.commit()
    return out


# --------------------------------------------------------------------------- status
@router.get("")
def brain_root(db: Session = Depends(get_db), user: User = Depends(admin_user)):
    """Server-side capability check: what the brain can do for this user."""
    brain = _brain(db, user)
    return {"version": "4.0.0", "admin_surface": brain.is_admin_surface(),
            "tools": len(brain.tools()), "runtime": brain.status()["runtime"]}


@router.get("/status")
def status(deep: bool = Query(False), db: Session = Depends(get_db), user: User = Depends(admin_user)):
    return _guard(_brain(db, user).status, deep=deep)


@router.get("/situation")
def situation(light: bool = Query(True), db: Session = Depends(get_db), user: User = Depends(admin_user)):
    return _guard(_brain(db, user).situation, light=light)


@router.get("/tools")
def tools(db: Session = Depends(get_db), user: User = Depends(admin_user)):
    """The capability surface, with permissions already applied for this caller."""
    return {"tools": _brain(db, user).tools()}


@router.get("/policies")
def policies(db: Session = Depends(get_db), user: User = Depends(admin_user)):
    return _brain(db, user).policies()


# --------------------------------------------------------------------------- conversation
@router.post("/chat")
def chat(payload: ChatIn, db: Session = Depends(get_db), user: User = Depends(admin_user)):
    """Ask the brain a question. Admin-only by contract (§88)."""
    brain = _brain(db, user)
    if not brain.is_admin_surface():
        raise HTTPException(status_code=403, detail="BUSINESS_BRAIN_ADMIN_ONLY")
    return _write(db, brain.chat, payload.question, session_key=payload.session_key,
                  prefer_llm=payload.prefer_llm)


@router.get("/chat/history")
def chat_history(session_key: str = Query("default"), limit: int = Query(50, le=200),
                 db: Session = Depends(get_db), user: User = Depends(admin_user)):
    return {"messages": _guard(_brain(db, user).history, session_key=session_key, limit=limit)}


# --------------------------------------------------------------------------- decisions
@router.get("/decisions")
def decisions(status: str | None = Query(None), origin: str | None = Query(None),
              limit: int = Query(50, le=200), offset: int = Query(0, ge=0),
              db: Session = Depends(get_db), user: User = Depends(admin_user)):
    return {"decisions": _brain(db, user).decisions(status=status, origin=origin, limit=limit, offset=offset),
            "open": decision_svc.open_count(db)}


@router.get("/decisions/{decision_id}")
def decision(decision_id: int, db: Session = Depends(get_db), user: User = Depends(admin_user)):
    row = _brain(db, user).decision(decision_id)
    if row is None:
        raise HTTPException(status_code=404, detail="DECISION_NOT_FOUND")
    return row


@router.post("/decisions/{decision_id}/approve")
def approve(decision_id: int, payload: DecideIn, db: Session = Depends(get_db), user: User = Depends(admin_user)):
    return _write(db, _brain(db, user).approve, decision_id, option_id=payload.option_id)


@router.post("/decisions/{decision_id}/reject")
def reject(decision_id: int, payload: DecideIn, db: Session = Depends(get_db), user: User = Depends(admin_user)):
    return _write(db, _brain(db, user).reject, decision_id, reason=payload.reason)


@router.post("/decisions/{decision_id}/snooze")
def snooze(decision_id: int, payload: DecideIn, db: Session = Depends(get_db), user: User = Depends(admin_user)):
    return _write(db, _brain(db, user).snooze, decision_id, days=max(1, min(payload.days, 30)))


@router.post("/decisions/{decision_id}/measure")
def measure(decision_id: int, db: Session = Depends(get_db), user: User = Depends(admin_user)):
    """Force a measurement now. Refuses to invent a number when the window is short."""
    return _write(db, _brain(db, user).measure, decision_id)


# --------------------------------------------------------------------------- follow-ups & memory
@router.get("/followups")
def followups(include_closed: bool = Query(False), limit: int = Query(50, le=200),
              db: Session = Depends(get_db), user: User = Depends(admin_user)):
    return {"followups": _brain(db, user).followups(include_closed=include_closed, limit=limit)}


@router.post("/followups/{followup_id}/resolve")
def resolve_followup(followup_id: int, payload: FollowupIn, db: Session = Depends(get_db),
                     user: User = Depends(admin_user)):
    return _write(db, _brain(db, user).resolve_followup, followup_id, result=payload.result)


@router.get("/memory")
def memory(kind: str | None = Query(None), limit: int = Query(100, le=500),
           db: Session = Depends(get_db), user: User = Depends(admin_user)):
    return _brain(db, user).memory(kind=kind, limit=limit)


@router.get("/alerts")
def alerts(limit: int = Query(20, le=100), db: Session = Depends(get_db), user: User = Depends(admin_user)):
    """Proactive findings already raised as decision cards."""
    return {"alerts": _brain(db, user).alerts(limit=limit)}


@router.post("/proactive/run")
def run_proactive(force: bool = Query(False), db: Session = Depends(get_db), user: User = Depends(admin_user)):
    """Scan now (or let the scheduler do it). Creating zero cards is a valid result."""
    return _write(db, _brain(db, user).proactive, force=force)


# --------------------------------------------------------------------------- local model
@router.get("/model")
def model(db: Session = Depends(get_db), user: User = Depends(admin_user)):
    return _brain(db, user).model_status()


@router.get("/model/status")
def model_status(db: Session = Depends(get_db), user: User = Depends(admin_user)):
    return _brain(db, user).model_status()


@router.post("/model/select")
def model_select(payload: DownloadIn, db: Session = Depends(get_db), user: User = Depends(admin_user)):
    return _write(db, _brain(db, user).model_select, payload.model_id)


@router.post("/model/download")
def model_download(payload: DownloadIn, db: Session = Depends(get_db), user: User = Depends(admin_user)):
    """Download the recommended model (or a named one) and verify its checksum.

    Runs inline because it is the owner watching a progress number on screen;
    a failing checksum deletes the file and returns the reason.
    """
    return _write(db, _brain(db, user).model_download, payload.model_id)


@router.post("/model/benchmark")
def model_benchmark(payload: DownloadIn, db: Session = Depends(get_db), user: User = Depends(admin_user)):
    return _write(db, _brain(db, user).model_benchmark, payload.model_id)
