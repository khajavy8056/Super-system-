"""Offline-first support: durable job queue + diagnostics runs (§48, §49, §42).

The queue is the single retry mechanism for anything that needs the network
(SMS, external lookups, price refresh, mobile writes replayed from IndexedDB).
It lives in the database so a power cut can never lose a pending job.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base
from .base import TimestampMixin


class SyncJob(TimestampMixin, Base):
    __tablename__ = "sync_jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_type: Mapped[str] = mapped_column(String(32), index=True)
    # SMS | EXTERNAL_LOOKUP | PRICE_UPDATE | STOCKTAKE_COUNT | CUSTOM
    payload: Mapped[str] = mapped_column(Text, default="{}")  # JSON
    status: Mapped[str] = mapped_column(String(16), default="PENDING", index=True)
    # PENDING | RUNNING | COMPLETED | FAILED | CANCELLED
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=5)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    reference_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    reference_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    #: client-supplied idempotency key so a replayed offline job runs once
    idempotency_key: Mapped[str | None] = mapped_column(String(96), unique=True, nullable=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)


class DiagnosticRun(Base):
    """One execution of the Connection Center (§42–44). Full log is JSON."""

    __tablename__ = "diagnostic_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    total: Mapped[int] = mapped_column(Integer, default=0)
    passed: Mapped[int] = mapped_column(Integer, default=0)
    failed: Mapped[int] = mapped_column(Integer, default=0)
    skipped: Mapped[int] = mapped_column(Integer, default=0)
    report: Mapped[str] = mapped_column(Text, default="[]")  # JSON list of checks
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
