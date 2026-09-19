"""Connection Center / diagnostics + sync queue API (§42–44, §49)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import SyncJob, User
from ..security import require_permission
from ..services import diagnostics as diag
from ..services import sync as sync_svc

router = APIRouter(prefix="/diagnostics", tags=["diagnostics"])


@router.post("/run")
def run_diagnostics(include_external: bool = Query(default=True),
                    db: Session = Depends(get_db),
                    user: User = Depends(require_permission("settings.manage"))):
    """Execute the FULL diagnostic suite. Every check performs real I/O."""
    return diag.run_full(db, user, include_external=include_external)


@router.get("/history")
def diagnostics_history(limit: int = Query(default=20, le=100),
                        db: Session = Depends(get_db),
                        _: User = Depends(require_permission("settings.manage"))):
    return diag.history(db, limit)


@router.get("/runs/{run_id}")
def diagnostics_run(run_id: int, db: Session = Depends(get_db),
                    _: User = Depends(require_permission("settings.manage"))):
    res = diag.get_run(db, run_id)
    if res is None:
        raise HTTPException(status_code=404, detail="RUN_NOT_FOUND")
    return res


# --- sync queue ----------------------------------------------------------------

class EnqueueIn(BaseModel):
    job_type: str
    payload: dict = {}
    idempotency_key: str | None = None


@router.get("/sync/stats")
def sync_stats(db: Session = Depends(get_db),
               _: User = Depends(require_permission("inventory.view"))):
    return sync_svc.stats(db)


@router.get("/sync/jobs")
def sync_jobs(status: str | None = None, limit: int = Query(default=100, le=500),
              db: Session = Depends(get_db),
              _: User = Depends(require_permission("settings.manage"))):
    stmt = select(SyncJob).order_by(SyncJob.id.desc()).limit(limit)
    if status:
        stmt = stmt.where(SyncJob.status == status.upper())
    return [{"id": j.id, "job_type": j.job_type, "status": j.status,
             "attempts": j.attempts, "max_attempts": j.max_attempts,
             "last_error": j.last_error,
             "next_attempt_at": j.next_attempt_at.isoformat() if j.next_attempt_at else None,
             "created_at": j.created_at.isoformat() if j.created_at else None}
            for j in db.execute(stmt).scalars()]


@router.post("/sync/enqueue", status_code=201)
def enqueue_job(body: EnqueueIn, db: Session = Depends(get_db),
                user: User = Depends(require_permission("inventory.view"))):
    job = sync_svc.enqueue(db, job_type=body.job_type.upper(), payload=body.payload,
                           idempotency_key=body.idempotency_key, user_id=user.id)
    db.commit()
    return {"id": job.id, "status": job.status, "job_type": job.job_type}


@router.post("/sync/run")
def run_sync(limit: int = Query(default=50, le=500), db: Session = Depends(get_db),
             _: User = Depends(require_permission("settings.manage"))):
    """Drain the queue now (also runs automatically in the background worker)."""
    return sync_svc.run_once(db, limit)


@router.post("/sync/jobs/{job_id}/retry")
def retry_job(job_id: int, db: Session = Depends(get_db),
              _: User = Depends(require_permission("settings.manage"))):
    job = db.get(SyncJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="JOB_NOT_FOUND")
    job.status = "PENDING"
    job.attempts = 0
    job.last_error = None
    db.commit()
    return {"id": job.id, "status": job.status}
