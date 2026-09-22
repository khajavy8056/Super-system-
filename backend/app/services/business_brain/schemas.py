"""v4.0 — Business Brain data contracts.

Everything the brain reasons about passes through one of these structures, so
the boundary between "what the shop's data says" (deterministic, typed) and
"what a language model said" (prose, unverified) stays visible in the types
themselves. A ``ToolResult`` may carry numbers; an ``Answer`` may carry prose
whose numbers have been checked against those results by ``grounding.py``.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Callable

# --------------------------------------------------------------------------- risk / permission taxonomy

RISK_LEVELS = ("none", "low", "medium", "high")

#: §47 — how an action may be executed without a human in the loop
#:   AUTO      low risk and fully reversible (a task note, a reorder-list line)
#:   APPROVAL  changes money or touches customers (price, campaign, SMS, PO)
#:   HIGH_RISK irreversible or payment-related (transfers, deletions)
ACTION_CLASSES = ("AUTO", "APPROVAL", "HIGH_RISK")


@dataclass
class ToolSpec:
    """One callable capability of the brain.

    ``permissions`` is the RBAC gate: calling a tool whose permission the user
    does not hold raises ``ToolDenied`` before a single row is read.
    """

    name: str
    description: str
    fn: Callable[..., dict]
    permissions: tuple[str, ...] = ()
    input_schema: dict = field(default_factory=dict)
    output_schema: dict = field(default_factory=dict)
    #: params without which the tool cannot produce a truthful answer. Checked by
    #: the registry *before* the call, so an incomplete request becomes
    #: ``MISSING_PARAMS`` instead of an exception inside a service.
    required: tuple[str, ...] = ()
    data_sources: tuple[str, ...] = ()
    side_effects: bool = False
    reversible: bool = True
    risk_level: str = "none"
    #: read tools are always safe to call during reasoning; write tools are not
    read_only: bool = True
    #: action class used when this tool is used to EXECUTE something (§47)
    action_class: str = "AUTO"

    def public(self, allowed: bool) -> dict:
        return {"name": self.name, "description": self.description, "input_schema": self.input_schema,
                "output_schema": self.output_schema, "permissions": list(self.permissions),
                "data_sources": list(self.data_sources), "side_effects": self.side_effects,
                "reversible": self.reversible, "risk_level": self.risk_level,
                "read_only": self.read_only, "action_class": self.action_class, "allowed": allowed}


@dataclass
class ToolCall:
    """One executed tool call — the auditable unit of the brain's reasoning."""

    name: str
    params: dict
    ok: bool
    ms: int = 0
    error: str | None = None
    source: str = ""
    #: deterministic result the model may cite; never model-generated
    data: dict = field(default_factory=dict)
    permission: str | None = None

    def trace(self) -> dict:
        return {"name": self.name, "params": {k: v for k, v in self.params.items()},
                "ok": self.ok, "ms": self.ms, "error": self.error, "source": self.source,
                "permission": self.permission}


class ToolDenied(PermissionError):
    """Raised when a user (or the model acting for a user) lacks a tool's permission."""


class ToolFailed(RuntimeError):
    """A tool failed for a non-permission reason. The brain must not invent a result."""


@dataclass
class Evidence:
    """What one domain (or one tool) contributes to a decision."""

    domain: str
    summary: str
    numbers: dict = field(default_factory=dict)
    flags: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    confidence: str = "medium"
    tool_calls: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Option:
    """A candidate course of action with deterministic economics."""

    id: str
    label: str
    description: str = ""
    #: deterministic economics (toman/month, cost, margin impact) — never model-made
    economics: dict = field(default_factory=dict)
    risk: str = "medium"
    reversible: bool = True
    confidence: str = "medium"
    requires_approval: bool = True
    action_class: str = "APPROVAL"
    actions: list[dict] = field(default_factory=list)
    tradeoffs: list[str] = field(default_factory=list)
    #: policy checks that shaped this option
    policy_notes: list[str] = field(default_factory=list)
    #: what must be true for this option to be the right one
    preconditions: list[str] = field(default_factory=list)
    score: float = 0.0

    def to_dict(self) -> dict:
        d = asdict(self)
        d["score"] = round(float(self.score), 4)
        return d


@dataclass
class Alert:
    """A proactive finding, already gated by impact ∧ confidence ∧ actionability (§26)."""

    key: str
    kind: str
    domain: str
    title: str
    body: str
    severity: str = "medium"          # low | medium | high | critical
    priority: int = 3                 # 1 = today, 5 = whenever
    impact_toman: float = 0.0
    urgency_days: int | None = None
    confidence: str = "medium"
    actionable: bool = True
    numbers: dict = field(default_factory=dict)
    evidence: list[dict] = field(default_factory=list)
    cluster: str = ""                 # several alerts may share one cluster title
    suggested_decision: dict | None = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Situation:
    """The store's business state at a point in time (§9).

    Deliberately a *summary with pointers*, not a database dump: each block
    carries the few numbers a decision needs plus the flags that change how
    those numbers must be read (cash pressure, data-quality problems,
    expiring stock, open follow-ups…).
    """

    generated_at: datetime
    store: dict = field(default_factory=dict)
    time: dict = field(default_factory=dict)
    cash: dict = field(default_factory=dict)
    obligations: dict = field(default_factory=dict)
    receivables: dict = field(default_factory=dict)
    inventory: dict = field(default_factory=dict)
    sales: dict = field(default_factory=dict)
    customers: dict = field(default_factory=dict)
    suppliers: dict = field(default_factory=dict)
    campaigns: dict = field(default_factory=dict)
    decisions: dict = field(default_factory=dict)
    followups: dict = field(default_factory=dict)
    data_quality: dict = field(default_factory=dict)
    flags: list[str] = field(default_factory=list)
    #: tools that produced this situation (auditable)
    tool_trace: list[dict] = field(default_factory=list)
    #: deterministic hash of the numeric core — used to avoid recomputing
    state_hash: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        d["generated_at"] = self.generated_at.isoformat()
        return d

    def digest(self, *, limit: int = 24) -> str:
        """Compact text form for prompts — never the whole database.

        Only facts the shop actually has are printed; a missing number says so
        instead of showing a zero, because "no data" and "zero" lead to
        different decisions.
        """

        def num(block: dict, key: str, digits: int = 0):
            value = (block.get("numbers") or {}).get(key)
            if value is None:
                return None
            try:
                return round(float(value), digits)
            except (TypeError, ValueError):
                return None

        lines: list[str] = []
        cash = self.cash or {}
        if cash:
            available = num(cash, "cash_available")
            if available is not None:
                cash_only, bank = num(cash, "cash_cash"), num(cash, "bank")
                lines.append(f"موجودی نقد/بانک: {available:,} تومان (نقد {cash_only:,} + بانک {bank:,})"
                             if cash_only is not None and bank is not None
                             else f"موجودی نقد/بانک: {available:,} تومان")
            forecast = cash.get("forecast") or {}
            lowest = num(forecast, "min_projected_cash")
            if lowest is not None:
                lines.append(f"کمترین موجودی پیش‌بینی‌شده (۱۴ روز): {lowest:,} تومان")
        obligations = self.obligations or {}
        issued = num(obligations, "issued_next_7d")
        if issued is not None:
            lines.append(f"چک پرداختی ۷ روز آینده: {issued:,} تومان "
                         f"(کل ۳۰ روز: {num(obligations, 'issued_total') or 0:,})")
        receivables = self.receivables or {}
        total_due = num(receivables, "total")
        if total_due:
            lines.append(f"مطالبات: {total_due:,} تومان "
                         f"(با احتمال وصول بالا {num(receivables, 'high_confidence') or 0:,})")
        inventory = self.inventory or {}
        stock_value = num(inventory, "stock_value")
        if stock_value is not None:
            expiry = inventory.get("expiry_risk") or {}
            overstock = inventory.get("overstock") or {}
            stockout = inventory.get("stockout") or {}
            lines.append(
                f"ارزش موجودی: {stock_value:,} تومان؛ در معرض انقضا: "
                f"{num(expiry, 'at_risk_value') or 0:,}؛ سرمایهٔ راکد: {num(overstock, 'capital') or 0:,}؛ "
                f"در خطر اتمام: {num(stockout, 'count') or 0} قلم")
        sales = self.sales or {}
        revenue = num(sales, "revenue")
        if revenue is not None:
            change = num(sales, "change_pct", 1)
            lines.append(f"فروش {int(num(sales, 'window_days') or 7)} روز: {revenue:,} تومان "
                         f"(تغییر {change or 0}٪)، سود {num(sales, 'profit') or 0:,}")
        quality = (self.data_quality or {}).get("details") or {}
        if quality:
            lines.append(f"کیفیت داده: {quality.get('verdict')} "
                         f"({(quality.get('summary') or {}).get('CRITICAL', 0)} مورد بحرانی)")
        if self.flags:
            lines.append("پرچم‌ها: " + "، ".join(self.flags[:8]))
        return "\n".join(lines[:limit])


@dataclass
class Answer:
    """What the manager sees.

    ``text`` is the short Persian answer. ``numbers_verified`` is the grounding
    verdict: False means at least one number in the LLM text could not be traced
    to a tool result, and the text was therefore replaced by the deterministic
    one (see ``grounding.py``).
    """

    text: str
    intent: str = "GENERAL"
    mode: str = "deterministic"        # deterministic | llm | hybrid
    degraded: list[str] = field(default_factory=list)
    evidence: list[dict] = field(default_factory=list)
    tools_used: list[dict] = field(default_factory=list)
    decision: dict | None = None
    numbers_verified: bool = True
    followups: list[dict] = field(default_factory=list)
    model: str | None = None
    ms: int = 0
    warnings: list[str] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)
