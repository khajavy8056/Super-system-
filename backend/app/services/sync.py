"""Durable offline job queue (§48–49).

Anything that needs the network is enqueued instead of executed inline, so a
sale never fails because the internet is down. A worker drains the queue with
exponential backoff; handlers are registered per job type.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import SyncJob

log = logging.getLogger("supermarket.sync")

#: job_type -> callable(db, payload: dict) -> dict | None ; raise to retry
HANDLERS: dict[str, callable] = {}

BACKOFF_SECONDS = [5, 30, 120, 600, 3600]


def register(job_type: str):
    def deco(fn):
        HANDLERS[job_type] = fn
        return fn
    return deco


def enqueue(
    db: Session,
    *,
    job_type: str,
    payload: dict,
    max_attempts: int = 5,
    reference_type: str | None = None,
    reference_id: int | None = None,
    idempotency_key: str | None = None,
    user_id: int | None = None,
) -> SyncJob:
    """Add a job. An existing job with the same idempotency key is returned
    unchanged (safe replay of an offline client queue)."""
    if idempotency_key:
        existing = db.execute(
            select(SyncJob).where(SyncJob.idempotency_key == idempotency_key)
        ).scalar_one_or_none()
        if existing is not None:
            return existing
    job = SyncJob(
        job_type=job_type,
        payload=json.dumps(payload, ensure_ascii=False, default=str),
        status="PENDING",
        attempts=0,
        max_attempts=max_attempts,
        next_attempt_at=datetime.utcnow(),
        reference_type=reference_type,
        reference_id=reference_id,
        idempotency_key=idempotency_key,
        created_by=user_id,
    )
    db.add(job)
    db.flush()
    return job


def due_jobs(db: Session, limit: int = 50) -> list[SyncJob]:
    now = datetime.utcnow()
    return list(
        db.execute(
            select(SyncJob)
            .where(
                SyncJob.status == "PENDING",
                (SyncJob.next_attempt_at.is_(None)) | (SyncJob.next_attempt_at <= now),
            )
            .order_by(SyncJob.id.asc())
            .limit(limit)
        ).scalars()
    )


def run_once(db: Session, limit: int = 50) -> dict:
    """Drain up to ``limit`` due jobs. Never raises — failures are recorded."""
    processed = succeeded = failed = skipped = 0
    for job in due_jobs(db, limit):
        handler = HANDLERS.get(job.job_type)
        processed += 1
        if handler is None:
            job.status = "FAILED"
            job.last_error = f"NO_HANDLER:{job.job_type}"
            failed += 1
            continue
        job.attempts += 1
        try:
            handler(db, json.loads(job.payload or "{}"))
        except Exception as exc:  # noqa: BLE001 - queue must never crash
            job.last_error = f"{type(exc).__name__}: {exc}"[:2000]
            if job.attempts >= job.max_attempts:
                job.status = "FAILED"
                failed += 1
            else:
                delay = BACKOFF_SECONDS[min(job.attempts - 1, len(BACKOFF_SECONDS) - 1)]
                job.next_attempt_at = datetime.utcnow() + timedelta(seconds=delay)
                skipped += 1
            log.warning("sync job %s failed (attempt %s): %s", job.id, job.attempts, exc)
        else:
            job.status = "COMPLETED"
            job.completed_at = datetime.utcnow()
            job.last_error = None
            succeeded += 1
    db.commit()
    return {"processed": processed, "succeeded": succeeded,
            "failed": failed, "retry_scheduled": skipped}


def stats(db: Session) -> dict:
    from sqlalchemy import func

    rows = db.execute(
        select(SyncJob.status, SyncJob.job_type, func.count())
        .group_by(SyncJob.status, SyncJob.job_type)
    ).all()
    by_status: dict[str, int] = {}
    by_type: dict[str, dict[str, int]] = {}
    for status, jtype, n in rows:
        by_status[status] = by_status.get(status, 0) + n
        by_type.setdefault(jtype, {})[status] = n
    return {"by_status": by_status, "by_type": by_type,
            "pending": by_status.get("PENDING", 0),
            "failed": by_status.get("FAILED", 0)}


# --- built-in handlers --------------------------------------------------------

@register("SMS")
def _handle_sms(db: Session, payload: dict) -> None:
    from . import sms as sms_svc

    msg_id = payload.get("sms_id")
    if msg_id:
        sms_svc.dispatch_one(db, msg_id)
    else:
        sms_svc.queue_sms(db, phone=payload["phone"], text=payload["text"])


@register("PRICE_UPDATE")
def _handle_price_update(db: Session, payload: dict) -> None:
    from . import resolvers as res_svc

    res_svc.resolve_market_price(db, payload["barcode"], payload.get("product_id"))


@register("EXTERNAL_LOOKUP")
def _handle_lookup(db: Session, payload: dict) -> None:
    from . import resolvers as res_svc

    res_svc.resolve_product(db, payload["barcode"])
