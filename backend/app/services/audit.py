"""Audit logging (blueprint §81) — who / what / when / before / after / reference."""
from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy.orm import Session

from ..models import AuditLog, User


def write_audit(
    db: Session,
    *,
    action: str,
    user_id: int | None = None,
    entity_type: str | None = None,
    entity_id: int | None = None,
    before: dict | None = None,
    after: dict | None = None,
    reference: str | None = None,
    ip_address: str | None = None,
) -> AuditLog:
    entry = AuditLog(
        user_id=user_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        before=json.dumps(before, default=str, ensure_ascii=False) if before else None,
        after=json.dumps(after, default=str, ensure_ascii=False) if after else None,
        reference=reference,
        ip_address=ip_address,
        created_at=datetime.utcnow(),
    )
    db.add(entry)
    db.flush()
    return entry


def user_id_of(user: User | None) -> int | None:
    return user.id if user else None
