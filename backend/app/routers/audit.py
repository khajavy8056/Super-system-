from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import AuditLog, User
from ..security import get_current_user, require_permission

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("")
def list_audit(action: str | None = None, limit: int = Query(default=200, le=1000),
               db: Session = Depends(get_db), _: User = Depends(require_permission("audit.view"))):
    stmt = select(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit)
    if action:
        stmt = stmt.where(AuditLog.action == action)
    rows = db.execute(stmt).scalars().all()
    return [
        {"id": a.id, "action": a.action, "user_id": a.user_id, "entity_type": a.entity_type,
         "entity_id": a.entity_id, "reference": a.reference,
         "before": json.loads(a.before) if a.before else None,
         "after": json.loads(a.after) if a.after else None,
         "created_at": a.created_at.isoformat()}
        for a in rows
    ]
