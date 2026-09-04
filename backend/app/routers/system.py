from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import __version__
from ..config import settings
from ..database import get_db
from ..models import Notification, User
from ..security import get_current_user, require_permission
from ..services import expiry as expiry_svc
from ..services.audit import write_audit

router = APIRouter(tags=["system"])


@router.get("/health")
def health(db: Session = Depends(get_db)):
    db.execute(select(Notification.id).limit(1))
    return {"status": "ok", "app": settings.APP_NAME, "version": __version__,
            "environment": settings.ENVIRONMENT, "time": datetime.utcnow().isoformat()}


@router.post("/jobs/expiry-scan")
def run_expiry_scan(db: Session = Depends(get_db), _: User = Depends(require_permission("inventory.view"))):
    result = expiry_svc.expiry_scan(db)
    db.commit()
    return result


@router.get("/notifications")
def notifications(unread_only: bool = False, db: Session = Depends(get_db),
                  _: User = Depends(get_current_user)):
    stmt = select(Notification).order_by(Notification.created_at.desc()).limit(100)
    if unread_only:
        stmt = stmt.where(Notification.is_read.is_(False))
    return [
        {"id": n.id, "type": n.type, "title": n.title, "body": n.body,
         "severity": n.severity, "is_read": n.is_read,
         "created_at": n.created_at.isoformat()}
        for n in db.execute(stmt).scalars()
    ]


@router.post("/notifications/read-all")
def mark_all_read(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    for n in db.execute(select(Notification).where(Notification.is_read.is_(False))).scalars():
        n.is_read = True
    db.commit()
    return {"ok": True}


@router.post("/backup")
def backup(db: Session = Depends(get_db), _: User = Depends(require_permission("settings.manage"))):
    """SQLite-safe online backup using the engine's backup API (not a raw copy)."""
    if not settings.DATABASE_URL.startswith("sqlite"):
        raise HTTPException(status_code=400, detail="Online backup is implemented for SQLite. Use your DB engine's tooling otherwise.")
    db_path = settings.DATABASE_URL.split("///")[-1]
    if db_path == ":memory:":
        raise HTTPException(status_code=400, detail="Cannot back up an in-memory database")

    backup_dir = settings.data_dir / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    dest = backup_dir / f"supermarket_{stamp}.db"

    # Use the sqlite3 online backup API (safe even while the app is running).
    import sqlite3
    source = sqlite3.connect(db_path)
    target = sqlite3.connect(str(dest))
    with target:
        source.backup(target)
    source.close()
    target.close()

    write_audit(db, action="BACKUP_CREATED", entity_type="Backup", entity_id=None, reference=str(dest))
    db.commit()
    return {"ok": True, "path": str(dest), "size": dest.stat().st_size}
