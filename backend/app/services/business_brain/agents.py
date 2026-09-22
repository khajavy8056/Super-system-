"""v4.0 — Specialist agents (§6).

Each agent owns one domain and answers one question: *what does my part of the
shop look like right now, and what does that imply?* It returns ``Evidence`` —
numbers with their source tool names attached — and it is **never** allowed to
make the final call. The planner sees all agents, spots the contradictions
between them, and decides.

That division is the whole point of the design: an inventory agent that says
«بخر» and a finance agent that says «پول نیست» must both be heard. The decision
that comes out is «با اعتبار ۳۰ روزه بخر» — a judgement no single specialist
could make.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from . import persian as fa
from .context import ToolContext
from .registry import REGISTRY
from .schemas import Evidence

#: the domains a decision can involve. The planner uses these names to cluster
#: evidence blocks and to detect cross-domain contradictions.
DOMAINS = ("finance", "inventory", "sales", "customer", "supplier", "pricing", "operations", "marketing")


@dataclass
class Agent:
    domain: str
    label: str
    #: tools this agent may call (subset of the registry; permissions still apply)
    tools: tuple[str, ...]
    #: what the agent looks at, in the owner's words (shown in the UI)
    looks_at: str = ""
    _last: list[dict] = field(default_factory=list)

    # ------------------------------------------------------------------ helpers
    def gather(self, ctx: ToolContext, names: Iterable[str] | None = None) -> tuple[dict, list[dict]]:
        """Call the agent's tools, honouring RBAC (denied tools are simply absent)."""
        data: dict = {}
        for name in (names or self.tools):
            out = REGISTRY.call_or_none(ctx, name)
            if out:
                data[name] = out
        return data, ctx.trace_payload()[-len(data):] if data else []

    # ------------------------------------------------------------------ contract
    def collect(self, ctx: ToolContext, *, question: str = "", entities: dict | None = None) -> Evidence:
        raise NotImplementedError


class FinanceAgent(Agent):
    def __init__(self) -> None:
        super().__init__("finance", "امور مالی", ("get_cash_position", "get_upcoming_cheques", "get_payables",
                                                 "get_receivables", "get_expected_collections", "get_cash_forecast",
                                                 "get_expenses", "get_profit_forecast"),
                         looks_at="نقدینگی، چک‌ها، مطالبات، بدهی‌ها و هزینه‌ها")

    def collect(self, ctx, *, question="", entities=None) -> Evidence:
        data, trace = self.gather(ctx)
        cash = data.get("get_cash_position", {})
        cheques = data.get("get_upcoming_cheques", {})
        recv = data.get("get_receivables", {})
        forecast = data.get("get_cash_forecast", {})
        nums = {**cash.get("numbers", {}), **cheques.get("numbers", {}), **recv.get("numbers", {}),
                **forecast.get("numbers", {})}
        available = float(cash.get("numbers", {}).get("cash_available") or 0)
        next7 = float(cheques.get("numbers", {}).get("issued_next_7d") or 0)
        expected = float(data.get("get_expected_collections", {}).get("numbers", {}).get("expected_total") or 0)
        reserve = float(cash.get("numbers", {}).get("reserve_floor") or 0)
        pressure = "LOW"
        if next7 > available + expected:
            pressure = "HIGH"
        elif next7 > available + expected * 0.5 or (reserve and available < reserve):
            pressure = "MEDIUM"
        if forecast.get("numbers", {}).get("breach_days", 0):
            pressure = "HIGH" if pressure != "HIGH" else pressure
        flags = []
        if pressure == "HIGH":
            flags.append("CASH_PRESSURE_HIGH")
        if cheques.get("numbers", {}).get("overdue_count"):
            flags.append("CHEQUE_OVERDUE")
        if reserve and available < reserve:
            flags.append("BELOW_CASH_RESERVE")
        summary = (f"نقدینگی {fa.toman_short(available)} تومان؛ تعهدات ۷ روز {fa.toman_short(next7)}؛ "
                   f"انتظار وصول {fa.toman_short(expected)}؛ فشار نقدی {pressure}")
        return Evidence(domain="finance", summary=summary, numbers=nums, flags=flags,
                        sources=["get_cash_position", "get_upcoming_cheques", "get_receivables",
                                 "get_expected_collections", "get_cash_forecast"],
                        confidence="high" if data.get("get_cash_position") else "low",
                        tool_calls=trace)


class InventoryAgent(Agent):
    def __init__(self) -> None:
        super().__init__("inventory", "انبار و موجودی",
                         ("get_inventory_summary", "get_expiry_risk", "get_overstock", "get_stockout_risk",
                          "get_product_snapshot"),
                         looks_at="موجودی، انقضا، کالای راکد و خطر اتمام")

    def collect(self, ctx, *, question="", entities=None) -> Evidence:
        names = list(self.tools)
        pid = (entities or {}).get("product_id")
        data, trace = self.gather(ctx, names)
        if pid:
            snap = ctx.cached(f"snap:{pid}", lambda: REGISTRY.call_or_none(ctx, "get_product_snapshot", {"product_id": pid}))
            if snap:
                data["get_product_snapshot"] = snap
        nums = {}
        for key in ("get_inventory_summary", "get_expiry_risk", "get_overstock", "get_stockout_risk",
                    "get_product_snapshot"):
            nums.update({k: float(v) for k, v in (data.get(key, {}).get("numbers") or {}).items()
                         if isinstance(v, (int, float)) and not isinstance(v, bool)})
        flags = [f for key in data for f in (data[key].get("flags") or [])]
        summary = "؛ ".join(filter(None, [
            (data.get("get_inventory_summary", {}).get("summary") or ""),
            (data.get("get_expiry_risk", {}).get("summary") or ""),
            (data.get("get_stockout_risk", {}).get("summary") or ""),
        ]))
        return Evidence(domain="inventory", summary=summary, numbers=nums, flags=flags,
                        sources=[k for k in data], confidence="high" if data else "low", tool_calls=trace)


class SalesAgent(Agent):
    def __init__(self) -> None:
        super().__init__("sales", "فروش", ("get_sales_trend", "get_product_sales", "get_profit_forecast"),
                         looks_at="روند فروش و سود، کالاهای پرفروش، پیش‌بینی")

    def collect(self, ctx, *, question="", entities=None) -> Evidence:
        data, trace = self.gather(ctx)
        trend = data.get("get_sales_trend", {})
        nums = dict(trend.get("numbers", {}))
        top = data.get("get_product_sales", {}).get("details", {}).get("items", [])[:5]
        summary = trend.get("summary") or "روند فروش در دسترس نیست"
        return Evidence(domain="sales", summary=summary, numbers=nums, flags=list(trend.get("flags") or []),
                        sources=["get_sales_trend", "get_product_sales", "get_profit_forecast"],
                        confidence="high" if trend else "low", tool_calls=trace)


class CustomerAgent(Agent):
    def __init__(self) -> None:
        super().__init__("customer", "مشتریان", ("get_customer_segment", "get_customer_behavior"),
                         looks_at="بخش‌بندی مشتریان، ریزش، VIP، رفتار خرید")

    def collect(self, ctx, *, question="", entities=None) -> Evidence:
        seg = REGISTRY.call_or_none(ctx, "get_customer_segment")
        nums = dict(seg.get("numbers", {}))
        cid = (entities or {}).get("customer_id")
        detail = REGISTRY.call_or_none(ctx, "get_customer_behavior", {"customer_id": cid}) if cid else {}
        if detail:
            nums.update(detail.get("numbers", {}))
        summary = seg.get("summary") or "دادهٔ مشتریان در دسترس نیست"
        if detail:
            summary += "؛ " + detail.get("summary", "")
        return Evidence(domain="customer", summary=summary, numbers=nums,
                        flags=list(seg.get("flags") or []) + list(detail.get("flags") or []),
                        sources=["get_customer_segment"] + (["get_customer_behavior"] if cid else []),
                        confidence="high" if seg else "low", tool_calls=ctx.trace_payload()[-2:])


class SupplierAgent(Agent):
    def __init__(self) -> None:
        super().__init__("supplier", "تأمین‌کنندگان", ("get_supplier_profile", "get_supplier_history", "get_payables"),
                         looks_at="اعتبار، رفتار تأمین‌کننده، بدهی به او")

    def collect(self, ctx, *, question="", entities=None) -> Evidence:
        sid = (entities or {}).get("supplier_id")
        data = {}
        if sid:
            data["get_supplier_profile"] = REGISTRY.call_or_none(ctx, "get_supplier_profile", {"supplier_id": sid})
            data["get_supplier_history"] = REGISTRY.call_or_none(ctx, "get_supplier_history", {"supplier_id": sid})
        data["get_payables"] = REGISTRY.call_or_none(ctx, "get_payables")
        nums = {}
        for value in data.values():
            nums.update({k: float(v) for k, v in (value.get("numbers") or {}).items()
                         if isinstance(v, (int, float)) and not isinstance(v, bool)})
        flags = [f for v in data.values() for f in (v.get("flags") or [])]
        summary = data.get("get_supplier_profile", {}).get("summary") or data.get("get_payables", {}).get("summary", "")
        return Evidence(domain="supplier", summary=summary, numbers=nums, flags=flags,
                        sources=[k for k, v in data.items() if v], confidence="high" if data else "low",
                        tool_calls=ctx.trace_payload()[-3:])


class PricingAgent(Agent):
    def __init__(self) -> None:
        super().__init__("pricing", "قیمت‌گذاری", ("get_product_snapshot", "get_price_history", "get_business_policies"),
                         looks_at="حاشیهٔ سود، تاریخچهٔ قیمت، سیاست تخفیف")

    def collect(self, ctx, *, question="", entities=None) -> Evidence:
        pid = (entities or {}).get("product_id")
        data = {"get_business_policies": REGISTRY.call_or_none(ctx, "get_business_policies")}
        if pid:
            data["get_product_snapshot"] = REGISTRY.call_or_none(ctx, "get_product_snapshot", {"product_id": pid})
            data["get_price_history"] = REGISTRY.call_or_none(ctx, "get_price_history", {"product_id": pid})
        snap = data.get("get_product_snapshot", {})
        nums = dict(snap.get("numbers", {}))
        flags = []
        if pid and snap and float(nums.get("margin_pct") or 0) < 5:
            flags.append("THIN_MARGIN")
        summary = snap.get("summary") or "سیاست‌های قیمت‌گذاری فروشگاه بررسی شد"
        return Evidence(domain="pricing", summary=summary, numbers=nums, flags=flags,
                        sources=[k for k, v in data.items() if v], confidence="high" if snap else "medium",
                        tool_calls=ctx.trace_payload()[-3:])


class OperationsAgent(Agent):
    def __init__(self) -> None:
        super().__init__("operations", "عملیات فروشگاه",
                         ("get_data_quality", "get_open_followups", "get_hardware_status", "get_recent_decisions"),
                         looks_at="کیفیت داده، پیگیری‌های باز، دستگاه‌ها، تصمیم‌های اخیر")

    def collect(self, ctx, *, question="", entities=None) -> Evidence:
        data, trace = self.gather(ctx)
        dq = data.get("get_data_quality", {})
        followups = data.get("get_open_followups", {})
        recent = data.get("get_recent_decisions", {})
        nums = {**dq.get("numbers", {}), **followups.get("numbers", {}), **recent.get("numbers", {})}
        flags = list(dq.get("flags") or []) + list(recent.get("flags") or [])
        summary = (f"کیفیت داده {dq.get('details', {}).get('verdict', '?')}؛ "
                   f"{fa.fa_num(followups.get('numbers', {}).get('open', 0))} پیگیری باز")
        return Evidence(domain="operations", summary=summary, numbers=nums, flags=flags,
                        sources=["get_data_quality", "get_open_followups", "get_recent_decisions"],
                        confidence="high", tool_calls=trace)


class MarketingAgent(Agent):
    def __init__(self) -> None:
        super().__init__("marketing", "بازاریابی و کمپین",
                         ("get_active_campaigns", "get_campaign_outcome", "get_customer_segment"),
                         looks_at="کمپین‌های فعال، نتیجهٔ کمپین‌های قبلی، مشتریان مناسب")

    def collect(self, ctx, *, question="", entities=None) -> Evidence:
        data, trace = self.gather(ctx)
        campaigns = data.get("get_active_campaigns", {})
        outcome = data.get("get_campaign_outcome", {})
        nums = {**campaigns.get("numbers", {}), **outcome.get("numbers", {})}
        summary = campaigns.get("summary", "کمپین فعالی نیست")
        if outcome.get("summary"):
            summary += "؛ " + outcome["summary"]
        return Evidence(domain="marketing", summary=summary, numbers=nums,
                        flags=list(outcome.get("flags") or []) + list(campaigns.get("flags") or []),
                        sources=[k for k, v in data.items() if v], confidence="high" if data else "low",
                        tool_calls=trace)


AGENTS: dict[str, Agent] = {a.domain: a for a in (
    FinanceAgent(), InventoryAgent(), SalesAgent(), CustomerAgent(), SupplierAgent(),
    PricingAgent(), OperationsAgent(), MarketingAgent(),
)}

#: which agents are worth waking for a given intent — the brain never runs all
#: eight "just in case": that is how a rule engine spams and a brain costs money
INTENT_AGENTS: dict[str, tuple[str, ...]] = {
    "CASH_CRISIS": ("finance", "supplier", "inventory", "sales"),
    "CHEQUE_MANAGEMENT": ("finance", "supplier", "sales"),
    "RECEIVABLE": ("finance", "customer"),
    "EXPIRY": ("inventory", "pricing", "marketing", "sales"),
    "STOCKOUT": ("inventory", "supplier", "sales"),
    "OVERSTOCK": ("inventory", "pricing", "marketing"),
    "SALES_DROP": ("sales", "customer", "inventory", "operations"),
    "PRODUCT_ACTION": ("inventory", "pricing", "sales", "marketing"),
    "CUSTOMER_ACTION": ("customer", "sales", "marketing"),
    "SUPPLIER": ("supplier", "finance", "inventory"),
    "CAMPAIGN_FOLLOWUP": ("marketing", "sales", "operations"),
    "DECISION_RECALL": ("operations",),
    "STORE_STATUS": ("finance", "sales", "inventory", "operations"),
    "GENERAL": ("operations", "sales", "finance"),
}


def collect(domain: str, ctx: ToolContext, *, question: str = "", entities: dict | None = None) -> Evidence:
    agent = AGENTS.get(domain)
    if agent is None:
        return Evidence(domain=domain, summary="", confidence="low")
    return agent.collect(ctx, question=question, entities=entities)
