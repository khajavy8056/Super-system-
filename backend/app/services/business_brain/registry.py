"""v4.0 — Tool Registry (§7).

One place where every capability of the brain is declared, gated and executed.
The registry is the *only* surface a language model may reach the shop's data
through, which is what turns "the LLM must not run SQL" from a guideline into a
structural fact:

    LLM → registry.call(name, params) → permission check → tool → verified dict → LLM

Each entry declares its permission, whether it writes, whether that write is
reversible, its risk level and which tables it reads — so the UI can show the
owner what the brain is allowed to do, and the security tests can assert that a
cashier cannot reach a financial tool even by asking for it by name.
"""
from __future__ import annotations

import logging

from . import tools as T
from .context import Timer, ToolContext
from .schemas import ToolCall, ToolDenied, ToolSpec

log = logging.getLogger("supermarket.brain.tools")

#: every tool the brain knows, declared with its contract. Kept as data (not
#: decorators) so the whole capability surface is readable in one screen and
#: tool-surface tests can iterate it.
SPECS: tuple[ToolSpec, ...] = (
    # ---------------------------------------------------------------- store & rules
    ToolSpec("get_store_profile", "پروفایل فروشگاه: نوع کسب‌وکار، راهبرد قیمت، تحمل ریسک، ترجیحات مدیر",
             T.get_store_profile, ("reports.view",), data_sources=("system_settings", "invoices", "customers")),
    ToolSpec("get_business_policies", "سیاست‌های ساخت‌یافتهٔ مدیر (سقف تخفیف، کف نقدینگی، اولویت تأمین‌کننده)",
             T.get_business_policies, ("settings.manage",), data_sources=("brain_policies",)),
    ToolSpec("set_policy", "ثبت یا تغییر یک سیاست فروشگاه (فقط مدیر)",
             T.set_policy, ("settings.manage",), side_effects=True, risk_level="low",
             required=("key", "value"), input_schema={"key": "str", "value": "any"},
             read_only=False, action_class="AUTO", data_sources=("brain_policies",)),
    ToolSpec("get_data_quality", "کیفیت داده: آیا اعداد فروشگاه قابل اعتمادند؟",
             T.get_data_quality, ("reports.view",), data_sources=("invoices", "product_batches", "customers")),

    # ---------------------------------------------------------------- money
    ToolSpec("get_cash_position", "موجودی نقد، بانک و کارتخوان + کف نقدینگی تعیین‌شده",
             T.get_cash_position, ("accounting.view", "reports.view"), data_sources=("acc_journal_lines",)),
    ToolSpec("get_upcoming_cheques", "چک‌های پرداختی و دریافتی تا N روز آینده با سررسید",
             T.get_upcoming_cheques, ("accounting.view", "reports.view"), data_sources=("acc_cheques",)),
    ToolSpec("get_payables", "بدهی به تأمین‌کنندگان و چک‌های در جریان",
             T.get_payables, ("accounting.view", "reports.view"), data_sources=("acc_cheques", "acc_accounts")),
    ToolSpec("get_receivables", "مطالبات از مشتریان با احتمال وصول هر مشتری",
             T.get_receivables, ("customers.ledger", "reports.view"), data_sources=("customer_ledger_entries",)),
    ToolSpec("get_expected_collections", "برآورد قطعی وصول مطالبات در بازهٔ آینده (بر پایهٔ رفتار خود مشتری)",
             T.get_expected_collections, ("customers.ledger", "reports.view"), data_sources=("customer_ledger_entries",)),
    ToolSpec("get_cash_forecast", "پیش‌بینی نقدینگی: ورود/خروج پول و روزهای زیر کف",
             T.get_cash_forecast, ("accounting.view", "reports.view"), data_sources=("acc_cheques", "acc_expenses")),
    ToolSpec("get_expenses", "هزینه‌های جاری فروشگاه به تفکیک دسته",
             T.get_expenses, ("accounting.view", "reports.view"), data_sources=("acc_expenses",)),

    # ---------------------------------------------------------------- inventory
    ToolSpec("get_inventory_summary", "خلاصهٔ موجودی: تعداد بچ، ارزش خرید/فروش، حاشیهٔ بالقوه",
             T.get_inventory_summary, ("inventory.view",), data_sources=("product_batches", "products")),
    ToolSpec("get_expiry_risk", "کالای نزدیک انقضا: ارزش در معرض خطر با توجه به سرعت فروش واقعی",
             T.get_expiry_risk, ("inventory.view",), data_sources=("product_batches", "invoice_items")),
    ToolSpec("get_overstock", "سرمایهٔ راکد: کالای کند-فروش با پوشش موجودی بالا",
             T.get_overstock, ("inventory.view",), data_sources=("product_batches", "invoice_items")),
    ToolSpec("get_stockout_risk", "کالاهایی که تا N روز آینده تمام می‌شوند",
             T.get_stockout_risk, ("inventory.view",), data_sources=("product_batches", "invoice_items")),
    ToolSpec("get_product_snapshot", "تصویر کامل یک کالا: موجودی، سرعت فروش، حاشیه، بچ‌ها، انقضا",
             T.get_product_snapshot, ("products.view", "inventory.view"),
             input_schema={"product_id": "int", "days": "int"}, required=("product_id",), data_sources=("products", "product_batches", "invoice_items")),
    ToolSpec("get_price_history", "تاریخچهٔ تغییر قیمت یک کالا",
             T.get_price_history, ("pricing.manage", "products.view"),
             input_schema={"product_id": "int"}, required=("product_id",), data_sources=("price_versions",)),

    # ---------------------------------------------------------------- sales
    ToolSpec("get_sales_trend", "روند فروش و سود در بازهٔ اخیر در مقایسه با بازهٔ قبل",
             T.get_sales_trend, ("reports.view",), data_sources=("invoices", "invoice_items")),
    ToolSpec("get_product_sales", "پرفروش‌ترین کالاها در بازهٔ اخیر",
             T.get_product_sales, ("reports.view",), data_sources=("invoice_items",)),
    ToolSpec("get_profit_forecast", "پیش‌بینی سود بر پایهٔ روند واقعی فروش (کالیبره‌شده)",
             T.get_profit_forecast, ("reports.view",), data_sources=("invoices", "invoice_items")),

    # ---------------------------------------------------------------- customers
    ToolSpec("get_customer_behavior", "رفتار یک مشتری: خریدها، مانده حساب، کالاهای محبوب، فاصلهٔ آخرین خرید",
             T.get_customer_behavior, ("customers.ledger", "reports.view"),
             input_schema={"customer_id": "int"}, required=("customer_id",), data_sources=("customers", "invoices", "customer_ledger_entries")),
    ToolSpec("get_customer_segment", "بخش‌بندی قطعی مشتریان: VIP، تازه، غایب، عادی",
             T.get_customer_segment, ("customers.ledger", "reports.view"), data_sources=("customers", "invoices")),

    # ---------------------------------------------------------------- suppliers
    ToolSpec("get_supplier_profile", "پروفایل تأمین‌کننده: حجم خرید، مرجوعی، عمر قفسه، اولویت",
             T.get_supplier_profile, ("accounting.view",), input_schema={"supplier_id": "int"},
             data_sources=("acc_suppliers", "product_batches"), required=("supplier_id",)),
    ToolSpec("get_supplier_history", "محموله‌های اخیر یک تأمین‌کننده",
             T.get_supplier_history, ("accounting.view",), input_schema={"supplier_id": "int"},
             data_sources=("product_batches",), required=("supplier_id",)),

    # ---------------------------------------------------------------- existing intelligence
    ToolSpec("run_existing_analyzer", "اجرای یکی از ۷۸ تحلیل‌گر موجود v3.x (فقط همان‌هایی که لازم است)",
             T.run_existing_analyzer, ("reports.view",),
             input_schema={"analyzer_id": "str", "days": "int"},
             data_sources=("invoices", "invoice_items", "product_batches", "customers")),
    ToolSpec("get_active_campaigns", "کمپین‌های فعال و بازهٔ آن‌ها",
             T.get_active_campaigns, ("settings.manage",), data_sources=("campaigns", "invoices")),
    ToolSpec("get_campaign_outcome", "نتیجهٔ واقعی یک کمپین: فروش و سود در برابر بازهٔ قبل",
             T.get_campaign_outcome, ("settings.manage",), data_sources=("campaigns", "invoices")),

    # ---------------------------------------------------------------- brain memory
    ToolSpec("get_recent_decisions", "تصمیم‌های اخیر ثبت‌شده در حافظهٔ تصمیم",
             T.get_recent_decisions, ("settings.manage",), data_sources=("brain_decisions",)),
    ToolSpec("search_decisions", "جست‌وجو در تصمیم‌های گذشته («آن تصمیم چی شد؟»)",
             T.search_decisions, ("settings.manage",), input_schema={"query": "str"},
             data_sources=("brain_decisions",)),
    ToolSpec("get_open_followups", "پیگیری‌های باز و سررسیدگذشته",
             T.get_open_followups, ("settings.manage",), data_sources=("brain_followups",)),
    ToolSpec("get_memory_facts", "دانش بلندمدت فروشگاه (رفتار تأمین‌کننده، نتیجهٔ کمپین‌ها، الگوها)",
             T.get_memory_facts, ("settings.manage",), data_sources=("brain_memory_facts",)),

    # ---------------------------------------------------------------- writes (brain-owned)
    ToolSpec("create_task", "ثبت کار/یادداشت برای کارکنان (کم‌ریسک، برگشت‌پذیر)",
             T.create_task, ("reports.view", "settings.manage"), side_effects=True, risk_level="low",
             read_only=False, action_class="AUTO", data_sources=("notifications",), required=("title",)),
    ToolSpec("create_followup", "ثبت پیگیری/یادآوری زمان‌دار برای مدیر («یادم بنداز»)",
             T.create_followup, ("reports.view", "settings.manage"), side_effects=True, risk_level="low",
             read_only=False, action_class="AUTO", data_sources=("brain_followups",), required=("title",)),
    ToolSpec("get_setting", "خواندن یک تنظیم مجاز (مثل متن پیامک یادآوری یا شمارهٔ مدیر)",
             T.get_setting_tool, ("settings.manage",), data_sources=("system_settings",),
             required=("key",), input_schema={"key": "str"}),
    ToolSpec("set_setting", "ثبت یک تنظیم مجاز (مثل متن پیامک یادآوری) — با تأیید مدیر در چت",
             T.set_setting_tool, ("settings.manage",), side_effects=True, risk_level="low",
             read_only=False, action_class="APPROVAL", data_sources=("system_settings",),
             required=("key", "value"), input_schema={"key": "str", "value": "str"}),
    ToolSpec("sms_draft", "پیش‌نویس پیامک برای یک مشتری — با تأیید مدیر ارسال می‌شود",
             T.sms_draft, ("settings.manage",), side_effects=True, risk_level="medium",
             read_only=False, action_class="APPROVAL", data_sources=("customers", "sms"),
             required=("text",), input_schema={"customer_id": "int?", "customer": "str?", "text": "str"}),
    ToolSpec("record_memory_fact", "ثبت دانش حاصل‌شده در حافظهٔ کسب‌وکار",
             T.record_memory_fact, ("settings.manage",), side_effects=True, risk_level="low",
             read_only=False, action_class="AUTO", data_sources=("brain_memory_facts",), required=("kind", "key", "value")),
    ToolSpec("measure_action", "اندازه‌گیری نتیجهٔ یک تصمیم در پنجرهٔ قرارداد اندازه‌گیری",
             T.measure_action, ("settings.manage",), side_effects=True, risk_level="low",
             read_only=False, action_class="AUTO", data_sources=("invoices", "brain_decisions"), required=("decision_id",)),

    # ---------------------------------------------------------------- external / hardware
    ToolSpec("search_web", "جست‌وجوی وب برای ایدهٔ کمپین/مناسبت — هرگز جای دادهٔ فروشگاه را نمی‌گیرد",
             T.search_web, ("settings.manage",), input_schema={"query": "str"},
             data_sources=("internet",), risk_level="low", required=("query",)),
    ToolSpec("get_hardware_status", "وضعیت دستگاه‌های فروشگاه (پرینتر، کشو، اسکنر، ترازو…)",
             T.get_hardware_status, ("settings.manage",), data_sources=("hardware_devices",)),
)

#: tools that exist in the brain's vocabulary but are executed through the
#: Action Engine instead of being called directly (§47/§5). Declared here so
#: the model can *propose* them and the UI can show their risk class.
ACTION_TOOLS: dict[str, dict] = {
    "create_campaign": {"label": "ساخت کمپین", "action_type": "flash_sale", "action_class": "APPROVAL",
                        "permissions": ("settings.manage",), "reversible": True},
    "update_price": {"label": "تغییر قیمت", "action_type": "set_price", "action_class": "APPROVAL",
                     "permissions": ("pricing.manage",), "reversible": True},
    "send_sms": {"label": "ارسال پیامک", "action_type": "personal_sms", "action_class": "APPROVAL",
                 "permissions": ("settings.manage",), "reversible": False},
    "create_purchase_order": {"label": "سفارش خرید", "action_type": "reorder_note", "action_class": "APPROVAL",
                              "permissions": ("batches.manage",), "reversible": True},
    "create_purchase_order_note": {"label": "یادداشت سفارش", "action_type": "reorder_note",
                                   "action_class": "APPROVAL", "permissions": ("batches.manage",), "reversible": True},
}


class ToolRegistry:
    def __init__(self, specs=SPECS) -> None:
        self._specs: dict[str, ToolSpec] = {s.name: s for s in specs}

    # ------------------------------------------------------------------ introspection
    def names(self) -> list[str]:
        return sorted(self._specs)

    def get(self, name: str) -> ToolSpec | None:
        return self._specs.get(name)

    def catalogue(self, ctx: ToolContext | None = None) -> list[dict]:
        out = []
        for spec in self._specs.values():
            allowed = True if ctx is None else all(ctx.has(p) for p in spec.permissions)
            out.append(spec.public(allowed))
        return out

    def for_llm(self, ctx: ToolContext) -> list[dict]:
        """The tool list handed to a model: only what *this user* may call."""
        return [s for s in self.catalogue(ctx) if s["allowed"] and s["read_only"]]

    def write_tools(self) -> list[dict]:
        return [s.public(True) for s in self._specs.values() if not s.read_only]

    # ------------------------------------------------------------------ execution
    def call(self, ctx: ToolContext, name: str, params: dict | None = None) -> ToolCall:
        """Permission-check → run → record. Never raises for tool failures.

        A failure is returned as ``ok=False`` with the error text: the brain
        must be able to *say* it could not reach a fact instead of inventing
        one, and the security tests rely on ``ok=False`` never being a
        permission bypass.
        """
        params = params or {}
        spec = self._specs.get(name)
        if spec is None:
            call = ToolCall(name=name, params=params, ok=False, error="TOOL_UNKNOWN")
            return ctx.record(call)
        absent = [p for p in spec.required if params.get(p) in (None, "")]
        if absent:
            call = ToolCall(name=name, params=params, ok=False,
                            error=f"MISSING_PARAMS: {','.join(absent)}")
            return ctx.record(call)
        missing = [p for p in spec.permissions if not ctx.has(p)]
        if missing:
            call = ToolCall(name=name, params=params, ok=False, error=f"TOOL_DENIED: {','.join(missing)}",
                            permission=missing[0])
            ctx.record(call)
            raise ToolDenied(f"{name} requires {','.join(missing)}")
        with Timer() as t:
            try:
                data = spec.fn(ctx, params) or {}
                ok, error = True, None
            except ToolDenied:
                raise
            except Exception as exc:  # noqa: BLE001 — a broken tool must not break the brain
                log.warning("brain tool %s failed: %s", name, exc, exc_info=True)
                data, ok, error = {}, False, f"{type(exc).__name__}: {exc}"[:400]
        call = ToolCall(name=name, params=params, ok=ok, ms=t.ms, error=error,
                        source=",".join(spec.data_sources), data=data if ok else {},
                        permission=spec.permissions[0] if spec.permissions else None)
        ctx.record(call)
        if ok:
            ctx.register_numbers(data)
        return call

    def call_or_none(self, ctx: ToolContext, name: str, params: dict | None = None) -> dict:
        """Convenience for internal callers: ``{}`` instead of an exception."""
        try:
            call = self.call(ctx, name, params)
        except ToolDenied:
            return {}
        return call.data if call.ok else {}

    def spec_of_action(self, action_type: str) -> dict | None:
        for entry in ACTION_TOOLS.values():
            if entry["action_type"] == action_type:
                return entry
        return None


REGISTRY = ToolRegistry()


def registry() -> ToolRegistry:
    return REGISTRY
