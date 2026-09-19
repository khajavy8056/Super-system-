"""v3.0 — Store Intelligence («هوش فروشگاه»).

An *Insight* is one concrete, evidence-backed recommendation produced by the
local analytics engine (services/insights.py): cross-sell pairs, expiry
markdown ladders, dead-stock bundles, stock-out forecasts, churn/VIP
customers, cash-flow shortfalls, loss-prevention anomalies, …

Life-cycle:  NEW → ACCEPTED (actions applied, baseline frozen) → MEASURED
                 ↘ DISMISSED / SNOOZED

The before/after measurement (NOT a randomized A/B experiment) is intentionally simple: the metric the insight
promises to move is sampled over a *baseline window* before acceptance and the
same-length *post window* after it, on the real invoice data — nothing is
simulated. The dashboard «اثر پیشنهادها» block sums those measured deltas.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base
from .base import TimestampMixin

MONEY = Numeric(18, 2)


class Insight(TimestampMixin, Base):
    __tablename__ = "ai_insights"

    id: Mapped[int] = mapped_column(primary_key=True)
    #: analyzer code — see services/insights.ANALYZERS
    kind: Mapped[str] = mapped_column(String(32), index=True)
    #: stable de-duplication key inside a kind (e.g. "pair:12:34", "batch:77")
    dedupe_key: Mapped[str] = mapped_column(String(128), index=True)
    title: Mapped[str] = mapped_column(String(255))
    body: Mapped[str] = mapped_column(Text)
    #: 1 (urgent) … 5 (nice to have)
    priority: Mapped[int] = mapped_column(Integer, default=3)
    #: JSON: numbers/rows that back the claim (shown as «شواهد»)
    evidence: Mapped[str] = mapped_column(Text, default="{}")
    #: JSON list of executable actions [{type, params, label}]
    actions: Mapped[str] = mapped_column(Text, default="[]")
    #: what we expect to gain if accepted (toman / month) — engine estimate
    expected_gain: Mapped[Decimal] = mapped_column(MONEY, default=0)
    #: metric spec used for measurement: JSON {metric, product_ids|customer_ids|…, window_days}
    metric: Mapped[str] = mapped_column(Text, default="{}")

    status: Mapped[str] = mapped_column(String(16), default="NEW", index=True)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    accepted_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    snoozed_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    #: JSON snapshot of the metric over the baseline window at acceptance
    baseline: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: JSON snapshot of the metric over the post window (filled by the measurer)
    result: Mapped[str | None] = mapped_column(Text, nullable=True)
    measured_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    #: measured delta in toman (positive = gain); NULL until measured
    measured_gain: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    #: last time the analyzer re-confirmed this insight (stale ones are auto-closed)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    #: optional LLM-written narrative (cached)
    narrative: Mapped[str | None] = mapped_column(Text, nullable=True)
