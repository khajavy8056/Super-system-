from __future__ import annotations

import shutil
import sqlite3
import tempfile
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel
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


_REQUIRED_TABLES = {"users", "products", "product_batches", "invoices", "audit_logs"}


def _backup_keep_count(db: Session) -> int:
    from ..models import SystemSetting
    row = db.execute(select(SystemSetting).where(SystemSetting.key == "backup.keep")).scalar_one_or_none()
    try:
        return max(1, int(row.value)) if row else 10
    except ValueError:
        return 10


def _prune_backups(backup_dir: Path, keep: int) -> None:
    files = sorted(backup_dir.glob("supermarket_*.db"), key=lambda f: f.stat().st_mtime, reverse=True)
    for old in files[keep:]:
        old.unlink(missing_ok=True)


@router.get("/backups")
def list_backups(db: Session = Depends(get_db), _: User = Depends(require_permission("settings.manage"))):
    backup_dir = settings.data_dir / "backups"
    files = sorted(backup_dir.glob("supermarket_*.db"), key=lambda f: f.stat().st_mtime, reverse=True)
    return [{"name": f.name, "size": f.stat().st_size,
             "created_at": datetime.fromtimestamp(f.stat().st_mtime).isoformat()} for f in files]


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
    stamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S_%f")
    dest = backup_dir / f"supermarket_{stamp}.db"

    # Use the sqlite3 online backup API (safe even while the app is running).
    source = sqlite3.connect(db_path)
    target = sqlite3.connect(str(dest))
    with target:
        source.backup(target)
    source.close()
    target.close()

    _prune_backups(backup_dir, _backup_keep_count(db))
    write_audit(db, action="BACKUP_CREATED", entity_type="Backup", entity_id=None, reference=str(dest))
    db.commit()
    return {"ok": True, "path": str(dest), "size": dest.stat().st_size}


@router.post("/restore")
def restore(file: UploadFile = File(...), db: Session = Depends(get_db),
            _: User = Depends(require_permission("settings.manage"))):
    """Restore a backup file (validated) via the SQLite online-backup API.

    Validation before touching the live DB: integrity_check + required tables.
    """
    if not settings.DATABASE_URL.startswith("sqlite"):
        raise HTTPException(status_code=400, detail="Online restore is implemented for SQLite.")
    db_path = settings.DATABASE_URL.split("///")[-1]
    if db_path == ":memory:":
        raise HTTPException(status_code=400, detail="Cannot restore into an in-memory database")

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp_path = tmp.name

    try:
        try:
            candidate = sqlite3.connect(tmp_path)
            integrity = candidate.execute("PRAGMA integrity_check").fetchone()[0]
        except sqlite3.DatabaseError as exc:
            raise HTTPException(status_code=400, detail=f"File is not a valid SQLite database: {exc}")
        tables = {r[0] for r in candidate.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if integrity != "ok":
            raise HTTPException(status_code=400, detail=f"Backup file failed integrity check: {integrity}")
        if not _REQUIRED_TABLES <= tables:
            missing = _REQUIRED_TABLES - tables
            raise HTTPException(status_code=400, detail=f"File is not a system backup (missing tables: {sorted(missing)})")

        # Safety backup of the current state before overwriting it.
        backup_dir = settings.data_dir / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        safety = backup_dir / f"supermarket_pre_restore_{datetime.utcnow().strftime('%Y%m%d_%H%M%S_%f')}.db"
        current = sqlite3.connect(db_path)
        snap = sqlite3.connect(str(safety))
        with snap:
            current.backup(snap)
        current.close()

        target = sqlite3.connect(db_path)
        with target:
            candidate.backup(target)
        candidate.close()
        target.close()
    finally:
        Path(tmp_path).unlink(missing_ok=True)

    write_audit(db, action="BACKUP_RESTORED", entity_type="Backup", entity_id=None,
                reference=getattr(file, "filename", None))
    db.commit()
    return {"ok": True, "detail": "بازیابی انجام شد؛ نسخه وضعیت قبل از بازیابی نیز ذخیره شد.",
            "safety_backup": str(safety)}


# ---------------------------------------------------------------------------
# Update system (§27–29)
#
# Mounted under /api (unlike the bare /health route above), so every client
# reaches it through the same authenticated API surface.
# ---------------------------------------------------------------------------
update_router = APIRouter(prefix="/system", tags=["update"])


class UpdateAuthIn(BaseModel):
    password: str
    download: bool = True


@update_router.get("/update/check")
def check_update(_: User = Depends(require_permission("settings.manage"))):
    """Report whether a newer release exists. Read-only and side-effect free."""
    from ..services.updater import check_for_update

    return check_for_update()


@update_router.post("/update/prepare")
def prepare_update_endpoint(body: UpdateAuthIn, db: Session = Depends(get_db),
                            user: User = Depends(require_permission("settings.manage"))):
    """Owner-authenticated update: re-auth → backup → download → verify.

    §28 requires password confirmation even for an already-signed-in admin,
    because an open session is not proof of who is at the keyboard.
    §29 makes the backup a blocking step — no backup, no update.
    """
    from ..security import verify_password
    from ..services.updater import prepare_update

    if not verify_password(body.password, user.password_hash):
        write_audit(db, action="UPDATE_AUTH_FAILED", user_id=user.id,
                    entity_type="System")
        db.commit()
        raise HTTPException(status_code=403, detail={
            "code": "BAD_PASSWORD", "message": "رمز عبور نادرست است"})

    result = prepare_update(db, download=body.download)
    write_audit(db, action="UPDATE_PREPARE", user_id=user.id,
                entity_type="System", after={"status": result["status"]})
    db.commit()
    return result
