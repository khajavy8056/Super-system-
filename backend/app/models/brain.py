"""v4.0 — Business Brain persistence («مغز کسب‌وکار»).

The v3.x intelligence engine answered *"what is worth doing?"* with an
``Insight`` row. The Business Brain answers a bigger question — *"what is going
on, what are my options, what did I decide, and what happened?"* — and needs
five durable things the insight table does not have:

* **Conversation memory** (``brain_messages``) — the manager's chat with the
  brain, including the *tool trace* that produced each answer (so a reply can
  be audited back to the deterministic query that produced its numbers).
* **Decision memory** (``brain_decisions``) — the §45 structured decision:
  situation, problem, objective, evidence, options, selected option, reason,
  risks, confidence, approval, actions, measurement, outcome. This is what
  makes «اون تصمیمی که ماه قبل گرفتیم چی شد؟» answerable.
* **Follow-ups** (``brain_followups``) — «بعداً یادم بنداز» as a real record,
  not a chat sentence.
* **Policy memory** (``brain_policies``) — the owner's structured rules
  (max discount without approval, minimum cash reserve, supplier priority).
  Kept in its own table rather than ``system_settings`` so it can carry scope,
  source and history without polluting the settings namespace.
* **Business memory facts** (``brain_memory_facts``) — long-lived knowledge
  learned from reality: supplier lead times, campaign outcomes, customer
  behaviour. Distinct from a decision (an action) and from a policy (a rule).

Plus ``brain_model_installs``: the Model Manager's ledger of what was
downloaded, verified and benchmarked on *this* device. A model is never
"installed" because a file exists — only because a row here says the SHA-256
matched and a benchmark ran.

Design rules
------------
* Append-only where it matters: a decision is never silently rewritten; a
  status change is recorded in ``history`` (JSON list).
* No LLM output is stored as a number. ``measurement``/``outcome`` are written
  by the deterministic measurer, never by the chat layer (see
  ``services/business_brain/grounding.py``).
* Everything is offline-first: ``local_decision``/``pending_sync`` mark rows
  created while the phone had no link to the PC; a conflict set
  ``conflict_with`` instead of overwriting.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base
from .base import TimestampMixin

MONEY = Numeric(18, 2)

#: life-cycle of a decision (matches the Decision Center status chips)
DECISION_STATUSES = (
    "NEEDS_DECISION",   # brain proposed it; the owner has not answered yet
    "WAITING_APPROVAL",  # action is drafted and waiting for the owner's go-ahead
    "RUNNING",          # action engine is executing it
    "MONITORING",       # executed; measurement window is open
    "COMPLETED",        # executed and verified
    "MEASURED",         # post-window measurement landed
    "FAILED",           # execution failed (rolled back)
    "RESOLVED",         # closed: done and learned from, or dropped
    "NO_ACTION",        # the brain deliberately decided to do nothing
)

ACTION_CLASSES = ("AUTO", "APPROVAL", "HIGH_RISK")


class BrainMessage(TimestampMixin, Base):
    """One turn of the conversation with the Business Brain (conversation memory)."""

    __tablename__ = "brain_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    #: conversation key — one per admin session; phones keep their own
    session_key: Mapped[str] = mapped_column(String(64), index=True, default="default")
    #: USER | ASSISTANT | SYSTEM | TOOL
    role: Mapped[str] = mapped_column(String(12), index=True)
    content: Mapped[str] = mapped_column(Text, default="")
    #: JSON list: [{name, params, ok, ms, verified, source}] — auditable tool trace
    tool_trace: Mapped[str] = mapped_column(Text, default="[]")
    #: JSON: intent, mode (llm|deterministic), model id, degradation flags
    meta: Mapped[str] = mapped_column(Text, default="{}")
    decision_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    #: offline creation (phone) — synced later, never silently merged
    local_decision: Mapped[bool] = mapped_column(Boolean, default=False)
    pending_sync: Mapped[bool] = mapped_column(Boolean, default=False)


class BrainDecision(TimestampMixin, Base):
    """A structured business decision (§45) plus its execution and outcome."""

    __tablename__ = "brain_decisions"

    id: Mapped[int] = mapped_column(primary_key=True)
    type: Mapped[str] = mapped_column(String(32), default="business_decision", index=True)
    title: Mapped[str] = mapped_column(String(255), default="")
    problem: Mapped[str] = mapped_column(Text, default="")
    objective: Mapped[str] = mapped_column(Text, default="")
    #: JSON snapshot of the business situation the decision was taken in
    situation: Mapped[str] = mapped_column(Text, default="{}")
    #: JSON list of evidence blocks (one per specialist agent / tool)
    evidence: Mapped[str] = mapped_column(Text, default="[]")
    #: JSON list of options [{id,label,description,economics,risk,reversible,confidence,tradeoffs}]
    options: Mapped[str] = mapped_column(Text, default="[]")
    recommended_option: Mapped[str | None] = mapped_column(String(64), nullable=True)
    selected_option: Mapped[str | None] = mapped_column(String(64), nullable=True)
    #: why this option, in the owner's language (short — the UI shows this)
    reason: Mapped[str] = mapped_column(Text, default="")
    #: JSON list of risks with severity + mitigations
    risks: Mapped[str] = mapped_column(Text, default="[]")
    #: high | medium | low | blocked
    confidence: Mapped[str] = mapped_column(String(16), default="medium")
    #: JSON: {verdict, allowed, requires_approval, checks:[{policy, ok, note}]}
    policy_verdict: Mapped[str] = mapped_column(Text, default="{}")
    requires_approval: Mapped[bool] = mapped_column(Boolean, default=True)
    #: JSON list of proposed actions ([{type, params, label, action_class, reversible}])
    actions: Mapped[str] = mapped_column(Text, default="[]")
    #: JSON: {approved_by, approved_at, rejected_reason}
    approval: Mapped[str] = mapped_column(Text, default="{}")
    #: JSON: {executions:[…], verified, status} — written by the Action Engine
    execution: Mapped[str] = mapped_column(Text, default="{}")
    #: JSON Measurement Contract: {baseline, window_days, success_rule, method, metric}
    measurement: Mapped[str] = mapped_column(Text, default="{}")
    #: JSON measurement result once the window closed
    result: Mapped[str] = mapped_column(Text, default="{}")
    measured_gain: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    #: POSITIVE | NEUTRAL | NEGATIVE | INSUFFICIENT_DATA | NOT_MEASURABLE | None
    outcome: Mapped[str | None] = mapped_column(String(24), nullable=True)
    measured_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    #: free-form machine status: NO_ACTION, DISCOUNT, BUNDLE, … (from §27 taxonomy)
    decision_kind: Mapped[str] = mapped_column(String(32), default="")
    status: Mapped[str] = mapped_column(String(20), default="NEEDS_DECISION", index=True)
    priority: Mapped[int] = mapped_column(Integer, default=3)
    #: JSON list of {status, at, by, note} — the decision is never rewritten silently
    history: Mapped[str] = mapped_column(Text, default="[]")
    #: link back to the insight/analyzer that raised it (if any)
    insight_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    dedupe_key: Mapped[str | None] = mapped_column(String(160), nullable=True, index=True)
    #: CHAT | PROACTIVE | UI | OFFLINE | ANALYZER
    origin: Mapped[str] = mapped_column(String(16), default="CHAT", index=True)
    #: the tool/agent trace that produced the evidence (auditable)
    tool_trace: Mapped[str] = mapped_column(Text, default="[]")
    #: phone made this decision without the PC — merged on sync, never overwritten
    local_decision: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    pending_sync: Mapped[bool] = mapped_column(Boolean, default=False)
    conflict_with: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    store_key: Mapped[str] = mapped_column(String(64), default="", index=True)


class BrainFollowup(TimestampMixin, Base):
    """A promise to check something later (§14)."""

    __tablename__ = "brain_followups"

    id: Mapped[int] = mapped_column(primary_key=True)
    decision_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    #: MEASURE | REMIND | SUPPLIER | CUSTOMER | DATA | CUSTOM
    kind: Mapped[str] = mapped_column(String(16), default="REMIND")
    title: Mapped[str] = mapped_column(String(255))
    note: Mapped[str] = mapped_column(Text, default="")
    due_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    status: Mapped[str] = mapped_column(String(16), default="OPEN", index=True)  # OPEN | DONE | CANCELLED
    notified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    #: v4.4.0 — earliest next SMS-to-manager for an unanswered reminder
    next_sms_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    result: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pending_sync: Mapped[bool] = mapped_column(Boolean, default=False)


class BrainPolicy(TimestampMixin, Base):
    """The owner's structured rules (policy memory, §11)."""

    __tablename__ = "brain_policies"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    #: JSON-encoded value (number | string | bool | object) — always structured
    value: Mapped[str] = mapped_column(Text, default="null")
    #: text | number | percent | money | bool | json
    value_type: Mapped[str] = mapped_column(String(16), default="text")
    scope: Mapped[str] = mapped_column(String(32), default="store")
    #: OWNER (set in UI) | DEFAULT (shipped) | LEARNED (inferred from outcomes)
    source: Mapped[str] = mapped_column(String(12), default="OWNER", index=True)
    label: Mapped[str] = mapped_column(String(160), default="")
    note: Mapped[str] = mapped_column(Text, default="")
    updated_by: Mapped[int | None] = mapped_column(Integer, nullable=True)


class BrainModelInstall(TimestampMixin, Base):
    """Model Manager ledger — one row per downloaded-and-verified model file."""

    __tablename__ = "brain_model_installs"

    id: Mapped[int] = mapped_column(primary_key=True)
    model_id: Mapped[str] = mapped_column(String(64), index=True)
    path: Mapped[str] = mapped_column(Text, default="")
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    sha256: Mapped[str] = mapped_column(String(64), default="")
    #: PENDING | DOWNLOADING | VERIFIED | INSTALLED | ACTIVE | FAILED | ROLLED_BACK | DELETED
    status: Mapped[str] = mapped_column(String(16), default="PENDING", index=True)
    #: JSON device profile the choice was made for (ram_mb, cores, storage_free_mb)
    device_profile: Mapped[str] = mapped_column(Text, default="{}")
    #: JSON real benchmark: load_ms, first_token_ms, tokens_per_sec, memory_mb, tool_call_ok…
    benchmark: Mapped[str] = mapped_column(Text, default="{}")
    activated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    previous_install_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class BrainMemoryFact(TimestampMixin, Base):
    """Long-term business knowledge (supplier behaviour, campaign outcome, …)."""

    __tablename__ = "brain_memory_facts"

    id: Mapped[int] = mapped_column(primary_key=True)
    #: SUPPLIER | CUSTOMER | CAMPAIGN | PRODUCT | PATTERN | EVENT | DATA
    kind: Mapped[str] = mapped_column(String(24), index=True)
    #: stable natural key inside the kind (e.g. "supplier:12:lead_time")
    key: Mapped[str] = mapped_column(String(128), index=True)
    #: JSON value with the numbers the brain may cite
    value: Mapped[str] = mapped_column(Text, default="{}")
    #: 0..1 — how much the brain trusts this fact (derived from sample size)
    confidence: Mapped[float] = mapped_column(Numeric(4, 3), default=0.5)
    #: ANALYZER | DECISION | OWNER | MEASUREMENT
    source: Mapped[str] = mapped_column(String(16), default="ANALYZER")
    reference_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    reference_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
