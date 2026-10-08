# AI TOOL REGISTRY (v4.0)

**قاعدهٔ اول:** مدل هیچ‌وقت SQL نمی‌نویسد. مدل فقط `tool_call` می‌سازد:
`LLM → Tool Registry → Permission Check → Service → DB → verified result → LLM`.

هر ابزار یک `ToolSpec` است با: `name`, `description`, `input_schema`, `output_schema`,
`permissions`, `side_effects`, `reversible`, `risk_level`, `data_sources`.

---

## ۱. ابزارهای خواندن (۳۲ ابزار)

| ابزار | مجوز لازم | منبع داده |
|---|---|---|
| `get_store_profile` | `reports.view` | system_settings, invoices, customers |
| `get_cash_position` | `accounting.view` | acc_journal_lines |
| `get_cash_forecast` | `accounting.view` | acc_cheques, acc_expenses |
| `get_upcoming_cheques` | `accounting.view` | acc_cheques |
| `get_payables` | `accounting.view` | acc_cheques, acc_accounts |
| `get_receivables` | `customers.ledger` | customer_ledger_entries |
| `get_expected_collections` | `customers.ledger` | customer_ledger_entries |
| `get_expenses` | `accounting.view` | acc_expenses |
| `get_profit_forecast` | `reports.view` | invoices, invoice_items |
| `get_sales_trend` | `reports.view` | invoices, invoice_items |
| `get_product_sales` | `reports.view` | invoice_items |
| `get_product_snapshot` | `products.view` + `inventory.view` | products, product_batches, invoice_items |
| `get_inventory_summary` | `inventory.view` | product_batches, products |
| `get_expiry_risk` | `inventory.view` | product_batches, invoice_items |
| `get_overstock` | `inventory.view` | product_batches, invoice_items |
| `get_stockout_risk` | `inventory.view` | product_batches, invoice_items |
| `get_price_history` | `pricing.manage` + `products.view` | price_versions |
| `get_customer_behavior` | `customers.ledger` | customers, invoices |
| `get_customer_segment` | `customers.ledger` | customers, invoices |
| `get_supplier_profile` | `accounting.view` | acc_suppliers, product_batches |
| `get_supplier_history` | `accounting.view` | product_batches |
| `get_business_policies` | `settings.manage` | brain_policies |
| `get_active_campaigns` | `settings.manage` | campaigns, invoices |
| `get_campaign_outcome` | `settings.manage` | campaigns, invoices |
| `get_recent_decisions` | `settings.manage` | brain_decisions |
| `search_decisions` | `settings.manage` | brain_decisions |
| `get_open_followups` | `settings.manage` | brain_followups |
| `get_memory_facts` | `settings.manage` | brain_memory_facts |
| `get_data_quality` | `reports.view` | invoices, product_batches, customers |
| `get_hardware_status` | `settings.manage` | hardware_devices |
| `run_existing_analyzer` | `reports.view` | invoices, invoice_items, … |
| `search_web` | `settings.manage` | internet (فقط خواندن) |

هر ابزار ساختار خروجی ثابت دارد و همان را در `ctx.register_numbers()` ثبت می‌کند؛ عددی که ثبت نشده باشد اجازهٔ ورود به پاسخ ندارد (`grounding.py`).

## ۲. ابزارهای نوشتن (۵ ابزار — کم‌خطر)

| ابزار | اثر جانبی | برگشت‌پذیر | ریسک |
|---|---|---|---|
| `set_policy` | تغییر سیاست فروشگاه | بله | low |
| `create_task` | ساخت یادآور/کار | بله | low |
| `create_followup` | ثبت پیگیری اندازه‌گیری | بله | low |
| `record_memory_fact` | ثبت فکت کسب‌وکار | بله | low |
| `measure_action` | اندازه‌گیری نتیجهٔ تصمیم | بله | low |

این ۵ مورد تنها ابزارهای «نوشتنی» قابل فراخوانی مستقیم هستند. هیچ‌کدام پول، قیمت یا پیامک را تغییر نمی‌دهد.

## ۳. ابزارهای اقدامی (`ACTION_TOOLS`) — از مسیر Action Engine

این‌ها در واژگان مدل هستند اما **مستقیم اجرا نمی‌شوند**؛ «پیشنهاد» می‌سازند و از
`services/insight_actions.py` (VALIDATE → SAVEPOINT → EXECUTE → VERIFY → COMMIT → audit) می‌گذرند:

| ابزار | نوع اقدام واقعی | کلاس | مجوز | برگشت‌پذیر |
|---|---|---|---|---|
| `create_campaign` | `flash_sale` | APPROVAL | `settings.manage` | بله |
| `update_price` | `set_price` | APPROVAL | `pricing.manage` | بله |
| `send_sms` | `personal_sms` | APPROVAL | `settings.manage` | **خیر** |
| `create_purchase_order` | `reorder_note` | APPROVAL | `batches.manage` | بله |
| `create_purchase_order_note` | `reorder_note` | APPROVAL | `batches.manage` | بله |

**پرداخت، انتقال وجه و حذف** همیشه `HIGH_RISK` و همیشه نیازمند تأیید مدیر هستند — در هیچ حالتی `AUTO` نمی‌شوند.

## ۴. چرخهٔ فراخوانی

```python
call = REGISTRY.call(ctx, "get_cash_forecast", {"days": 14})
if not call.ok:            # error ∈ {TOOL_UNKNOWN, MISSING_PARAMS, TOOL_DENIED, …}
    ...
call.data                  # خروجی ساختاریافته، هم‌زمان در ctx.trace ثبت شده
```

- `call()` رکورد `ToolCall` را حتی در حالت رد شدن ثبت می‌کند و سپس `ToolDenied` می‌اندازد.
- `call_or_none()` برای فراخوانی داخلی: دیکشنری خالی به‌جای استثنا.
- پارامتر اجباری جاافتاده → `ok=False, error="MISSING_PARAMS"` (استثنا نیست).
- نام ناشناس → `ok=False, error="TOOL_UNKNOWN"`.

## ۵. همهٔ ابزارها روی سرویس‌های موجود v3.x سوارند

هیچ تحلیلگر یا سرویسی بازنویسی نشد. نمونه‌ها:

- `run_existing_analyzer` → همان موتور `services/insights.py` (۷۹ تحلیل‌گر).
- `get_receivables`/`get_expected_collections` → `customer_ledger_entries` (همان دفتر معین v3.x).
- `get_cash_position`/`get_cash_forecast` → `acc_journal_lines`, `acc_cheques`, `acc_expenses`.
- اقدام‌ها → `insight_actions.py` بدون هیچ تغییر در منطق تراکنش.

## ۶. دسته‌بندی دامنه → متخصص

| متخصص | ابزارهای اصلی |
|---|---|
| Finance | `get_cash_position`, `get_cash_forecast`, `get_upcoming_cheques`, `get_payables`, `get_receivables`, `get_expected_collections`, `get_expenses` |
| Inventory | `get_inventory_summary`, `get_expiry_risk`, `get_overstock`, `get_stockout_risk`, `get_product_snapshot` |
| Sales | `get_sales_trend`, `get_product_sales`, `get_profit_forecast` |
| Customer | `get_customer_behavior`, `get_customer_segment` |
| Supplier | `get_supplier_profile`, `get_supplier_history` |
| Pricing | `get_price_history`, `get_product_sales` |
| Operations | `get_data_quality`, `get_hardware_status`, `get_open_followups` |
| Marketing | `get_active_campaigns`, `get_campaign_outcome` |

متخصص‌ها فقط `Evidence` تولید می‌کنند؛ **تصمیم را مغز می‌گیرد** (`brain.py`).
