"""v4.0 — the Business Brain façade (§5, §6).

One object that owns the whole pipeline, so routers, the background worker and
the tests all talk to the same thing:

    Data → Situation → Tools/Agents → Reasoning → Options → Decision →
    Policy → (Approval) → Action → Verification → Measurement → Memory

The façade is deliberately *thin*: it orchestrates and gates, it does not compute.
Financial numbers still come from the v3.x services through the Tool Registry, and
execution still happens inside the existing Action Engine.

Two access rules live here:

* every entry point takes the :class:`~...models.User` and derives permissions
  from it — there is no "brain key" that bypasses RBAC;
* the assistant surface (chat, decisions, memory) requires *both* ``reports.view``
  and ``settings.manage``, i.e. the primary administrator. A cashier's token
  reaches ``403`` on every one of them (§88).
"""
from __future__ import annotations

import json
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...models import BrainDecision, BrainFollowup, BrainMemoryFact, BrainMessage, User
from ...security import has_permission
from ..timeservice import local_now
from . import audit as audit_svc
from . import decisions as decision_svc
from . import followups as followup_svc
from . import memory as memory_svc
from . import model_manager as model_svc
from . import persian as fa
from . import planner as planner_svc
from . import proactive as proactive_svc
from . import runtime as runtime_svc
from . import situation as situation_svc
from . import vision as vision_svc
from .context import ToolContext
from .policies import all_policies, ensure_defaults
from .registry import REGISTRY

log = logging.getLogger("supermarket.brain")

#: what the manager's surface needs — the two permissions together are the
#: "primary administrator" definition used across v4.0
ADMIN_SURFACE = ("reports.view", "settings.manage")


class BrainDenied(PermissionError):
    """Raised when a caller lacks the brain surface permissions."""


def _codes(user: User | None) -> set[str]:
    from ...security import _user_permission_codes

    return set(_user_permission_codes(user)) if user is not None else set()


class BusinessBrain:
    """The supervisor of the v4.0 intelligence layer."""

    def __init__(self, db: Session, user: User | None = None) -> None:
        self.db = db
        self.user = user
        ensure_defaults(db)

    # ------------------------------------------------------------------ identity
    def codes(self) -> set[str]:
        return _codes(self.user)

    def is_admin_surface(self) -> bool:
        codes = self.codes()
        return all(code in codes for code in ADMIN_SURFACE) if self.user is not None else self.system

    @property
    def system(self) -> bool:
        """Background work (scheduler, sync) runs with no user attached."""
        return self.user is None

    def require_admin(self) -> None:
        if not self.is_admin_surface():
            raise BrainDenied("BUSINESS_BRAIN_ADMIN_ONLY")

    def ctx(self, *, system: bool | None = None) -> ToolContext:
        return ToolContext(db=self.db, user=self.user, permissions=frozenset(self.codes()),
                           system=self.system if system is None else system)

    # ------------------------------------------------------------------ conversation
    def chat(self, question: str, *, session_key: str = "default", prefer_llm: bool = True) -> dict:
        self.require_admin()
        return planner_svc.respond(self.db, question=question, user=self.user, session_key=session_key,
                                   permissions=frozenset(self.codes()), prefer_llm=prefer_llm)

    def history(self, *, session_key: str = "default", limit: int = 50) -> list[dict]:
        rows = self.db.execute(select(BrainMessage).where(BrainMessage.session_key == session_key)
                               .order_by(BrainMessage.id.desc()).limit(limit)).scalars().all()
        out = []
        for row in reversed(list(rows)):
            try:
                meta = json.loads(row.meta or "{}")
            except ValueError:
                meta = {}
            out.append({"id": row.id, "role": row.role, "content": row.content,
                        "at": row.created_at.isoformat() if row.created_at else None,
                        "decision_id": row.decision_id, "meta": meta})
        return out

    # ------------------------------------------------------------------ status
    def status(self, *, deep: bool = False) -> dict:
        situation = situation_svc.build(self.db, self.ctx(system=True), light=not deep)
        runtime = runtime_svc.provider_status(self.db)
        model = model_svc.ModelManager(self.db).status(include_registry=deep)
        return {
            "version": "4.0.0",
            "time": {"utc": local_now().isoformat(), "today_fa": fa.fa_date(local_now())},
            "access": {"admin_surface": self.is_admin_surface(), "system": self.system},
            "runtime": runtime,
            "local_mode": (runtime.get("mode") or "local_only"),
            "model": {"active": model.get("active"), "ready": model.get("active_ready"),
                      "recommended": model.get("recommended"), "context": model.get("context"),
                      "binary": model.get("binary"), "models_root": model.get("models_root"),
                      "installed_count": len([r for r in model.get("history", [])
                                              if r.get("status") in model_svc.READY_STATES])},
            "tools": {"count": len(REGISTRY.names()), "writable": len(REGISTRY.write_tools())},
            "flags": situation.flags,
            "state_hash": situation.state_hash,
            "data_quality": (situation.data_quality.get("details", {}) or {}).get("verdict"),
            "decisions": {"open": decision_svc.open_count(self.db)},
            "followups": (situation.followups.get("numbers") or {}),
            "memory": memory_svc.stats(self.db),
            "vision": vision_svc.status(),
            "proactive": proactive_svc.status(self.db),
            "notes": (runtime.get("notes") or []) + ([] if model.get("binary") else
                                                     ["فایل اجرایی llama.cpp پیدا نشد؛ حالت قطعی فعال است"]),
        }

    def situation(self, *, light: bool = True) -> dict:
        built = situation_svc.build(self.db, self.ctx(system=True), light=light)
        return {"flags": built.flags, "state_hash": built.state_hash,
                "digest": built.digest(), "blocks": built.to_dict()}

    # ------------------------------------------------------------------ decisions
    def decisions(self, *, status: str | None = None, origin: str | None = None, limit: int = 50,
                  offset: int = 0) -> list[dict]:
        rows = decision_svc.list_decisions(self.db, status=status, origin=origin, limit=limit, offset=offset)
        return [decision_svc.to_dict(row) for row in rows]

    def decision(self, decision_id: int) -> dict | None:
        row = self.db.get(BrainDecision, decision_id)
        return decision_svc.to_dict(row, full=True) if row else None

    def approve(self, decision_id: int, *, option_id: str | None = None) -> dict:
        self.require_admin()
        row = self.db.get(BrainDecision, decision_id)
        if row is None:
            return {"ok": False, "code": "NOT_FOUND", "message": "این تصمیم پیدا نشد"}
        return decision_svc.approve(self.db, row, user=self.user, option_id=option_id)

    def reject(self, decision_id: int, *, reason: str = "") -> dict:
        self.require_admin()
        row = self.db.get(BrainDecision, decision_id)
        if row is None:
            return {"ok": False, "code": "NOT_FOUND", "message": "این تصمیم پیدا نشد"}
        return decision_svc.reject(self.db, row, user=self.user, reason=reason)

    def snooze(self, decision_id: int, *, days: int = 3) -> dict:
        self.require_admin()
        row = self.db.get(BrainDecision, decision_id)
        if row is None:
            return {"ok": False, "code": "NOT_FOUND", "message": "این تصمیم پیدا نشد"}
        return decision_svc.snooze(self.db, row, days=days, user=self.user)

    def measure(self, decision_id: int) -> dict:
        self.require_admin()
        row = self.db.get(BrainDecision, decision_id)
        if row is None:
            return {"ok": False, "code": "NOT_FOUND", "message": "این تصمیم پیدا نشد"}
        return decision_svc.measure(self.db, row)

    # ------------------------------------------------------------------ follow-ups
    def followups(self, *, include_closed: bool = False, limit: int = 50) -> list[dict]:
        if include_closed:
            rows = self.db.execute(select(BrainFollowup).order_by(BrainFollowup.due_at.desc())
                                   .limit(limit)).scalars().all()
            return [followup_svc.to_dict(r) for r in rows]
        return followup_svc.open_items(self.db, limit=limit)

    def resolve_followup(self, followup_id: int, *, result: str = "") -> dict:
        self.require_admin()
        return followup_svc.resolve(self.db, followup_id, result=result,
                                    user_id=getattr(self.user, "id", None))

    # ------------------------------------------------------------------ memory
    def memory(self, *, kind: str | None = None, limit: int = 100) -> dict:
        query = select(BrainMemoryFact)
        if kind:
            query = query.where(BrainMemoryFact.kind == kind)
        rows = self.db.execute(query.order_by(BrainMemoryFact.observed_at.desc()).limit(limit)).scalars().all()
        facts = []
        for row in rows:
            try:
                value = json.loads(row.value or "{}")
            except ValueError:
                value = {}
            facts.append({"id": row.id, "kind": row.kind, "key": row.key, "value": value,
                          "confidence": float(row.confidence or 0), "source": row.source,
                          "observed_at": row.observed_at.isoformat() if row.observed_at else None,
                          "expires_at": row.expires_at.isoformat() if row.expires_at else None})
        return {"facts": facts, "stats": memory_svc.stats(self.db),
                "recent_decisions": self.decisions(limit=10), "kinds": list(memory_svc.KINDS)}

    def policies(self) -> dict:
        return {"policies": all_policies(self.db), "gate_summary": {
            "requires_approval": ["send_sms", "update_price", "create_campaign", "create_purchase_order"]}}

    def tools(self) -> list[dict]:
        """The capability surface, with the caller's own permissions applied."""
        return REGISTRY.catalogue(self.ctx())

    # ------------------------------------------------------------------ model
    def model_status(self) -> dict:
        manager = model_svc.ModelManager(self.db)
        return {**manager.status(), "runtime": runtime_svc.provider_status(self.db),
                "detect": manager.detect()}

    def model_select(self, model_id: str | None = None) -> dict:
        self.require_admin()
        return model_svc.ModelManager(self.db).select(model_id=model_id)

    def model_download(self, model_id: str | None = None, *, progress=None) -> dict:
        self.require_admin()
        manager = model_svc.ModelManager(self.db)
        chosen = model_id or manager.select().get("model", {}).get("model_id")
        if not chosen:
            return {"ok": False, "code": "NO_MODEL", "message": "مدل مناسبی برای این دستگاه یافت نشد"}
        return manager.download(chosen, progress=progress)

    def model_benchmark(self, model_id: str | None = None) -> dict:
        self.require_admin()
        return model_svc.ModelManager(self.db).benchmark(model_id)

    # ------------------------------------------------------------------ proactive
    def proactive(self, *, force: bool = False) -> dict:
        """Run the scanner. Safe to call from the scheduler or a status poll."""
        return proactive_svc.evaluate(self.db, user_id=getattr(self.user, "id", None), force=force)

    def alerts(self, *, limit: int = 20) -> list[dict]:
        return proactive_svc.recommendations(self.db, limit=limit)

    # ------------------------------------------------------------------ audit helpers
    def note(self, event: str, **detail) -> None:
        audit_svc.log(self.db, event=event, user_id=getattr(self.user, "id", None), after=detail or None)


def get_brain(db: Session, user: User | None = None) -> BusinessBrain:
    return BusinessBrain(db, user=user)


__all__ = ["BusinessBrain", "get_brain", "BrainDenied", "ADMIN_SURFACE", "has_permission"]
