"""Notification centre helpers (blueprint §85)."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from ..models import Notification


def notify(
    db: Session,
    *,
    type: str,
    title: str,
    body: str | None = None,
    severity: str = "INFO",
    reference_type: str | None = None,
    reference_id: int | None = None,
) -> Notification:
    n = Notification(
        type=type,
        title=title,
        body=body,
        severity=severity,
        reference_type=reference_type,
        reference_id=reference_id,
        created_at=datetime.utcnow(),
    )
    db.add(n)
    db.flush()
    return n
