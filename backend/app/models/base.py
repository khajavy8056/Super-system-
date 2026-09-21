from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, func
from sqlalchemy.orm import Mapped, mapped_column


def _utcnow() -> datetime:
    """Naive UTC timestamp.

    Storage policy: every timestamp in the database is UTC (see
    ``services/timeservice.py``); display-time conversion to the store's
    timezone / Jalali calendar happens in the presentation layer.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)


class TimestampMixin:
    # Both a Python-side ``default`` and a ``server_default`` are set on
    # purpose. Relying on the server default alone silently wrote NULL on
    # tables whose migration emitted the column without DEFAULT now() (this
    # actually happened to customer_ledger_entries and made every ledger row
    # render as 1348/10/11). The Python default makes correctness independent
    # of the DDL that happens to be on disk.
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow, onupdate=_utcnow,
        server_default=func.now(), nullable=False
    )


class SoftDeleteMixin:
    """Data-lifecycle: prefer soft delete over destructive DELETE (blueprint §144)."""

    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
