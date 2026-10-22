# AI BRAIN — ARCHITECTURE (v4.0)

**نسخه:** 4.0.0 · **پایه:** `c7079af` (3.8.0) · **سند طراحی:** `docs/AI_BRAIN_ARCHITECTURE_AUDIT.md`

> این سند معماری‌ای را توصیف می‌کند که **واقعاً در مخزن هست**، نه معماری آرمانی. هر بخش با نام ماژول/مسیر API ارجاع داده شده تا قابل راستی‌آزمایی باشد.

---

## ۱. ایدهٔ اصلی

v3.8.0 یک **موتور تحلیل صادق** بود: ۷۹ تحلیل‌گر، ۴۶ پیشنهاد حرفه‌ای، Action Engine با چرخهٔ VALIDATE → EXECUTE → VERIFY → COMMIT. اما مسیر همیشه یک‌طرفه بود: `Analyzer #79 → Recommendation #79` — یعنی سیستم **ماشین اجرای دستور** بود، نه کسی که فروشگاه را می‌شناسد.

v4.0 همان موتور را **زیر** یک لایهٔ تصمیم‌گیری می‌گذارد:

```
سؤال مدیر
   ↓
BUSINESS STATE  (situation.py)          ← وضعیت واقعی فروشگاه با اعداد
   ↓
RETRIEVAL       (memory.py, prompts.py) ← فقط چیزهای مربوط به همین سؤال
   ↓
SPECIALIST AGENTS (agents.py ×۸)        ← فقط شواهد، هیچ‌کدام تصمیم نمی‌گیرد
   ↓
REASONING       (runtime.py, planner.py)
   ↓
OPTIONS         (decision_helpers.py)   ← چند گزینه با اقتصاد هر گزینه
   ↓
DECISION        (decisions.py)          ← ثبت با decision_id
   ↓
POLICY          (policies.py)           ← سیاست‌های خود فروشگاه
   ↓
APPROVAL        (routers/brain.py)      ← تصمیم مدیر
   ↓
ACTION          (services/insight_actions.py — بدون بازنویسی)
   ↓
VERIFICATION → MEASUREMENT → MEMORY     (followups.py, memory.py)
```

سه قاعدهٔ سخت که جای دیگری ورد زبان نیست، اینجا **در کد** اعمال می‌شوند:

1. **LLM → SQL ممنوع.** مدل فقط `tool_call` می‌سازد. مسیر مجاز:
   `LLM → Tool Registry → Permission Check → Service → DB → نتیجهٔ تأییدشده → LLM`.
2. **عدد مالی از مدل ممنوع.** هر عددی که در پاسخ به مدیر می‌رود باید در `ctx.register_numbers()` ثبت شده باشد (خروجی ابزار). عدد بدون منبع حذف می‌شود (`grounding.py`).
3. **نوشتن فقط از Action Engine.** مدل «پیشنهاد» می‌دهد؛ اجرا با `insight_actions.execute_actions` و تراکنش موجود انجام می‌شود.

---

## ۲. ماژول‌ها (`backend/app/services/business_brain/`)

| ماژول | مسئولیت | نکتهٔ مهم |
|---|---|---|
| `brain.py` | نمای بیرونی (façade): `answer()`, `status()`, `card()` | فقط این ماژول را روتر صدا می‌زند |
| `situation.py` | ساخت وضعیت کسب‌وکار + فلگ‌ها | `CASH_GAP_AHEAD`, `CASH_FRAGILE`, `EXPIRY_RISK`, `DATA_QUALITY_*` |
| `store_profile.py` | پروفایل فروشگاه (اندازه، ساعات، دسته‌بندی غالب) | از دادهٔ واقعی، نه پرسشنامه |
| `planner.py` | تشخیص قصد + استخراج موجودیت‌ها + حل ارجاع («این کالا») | `meta["entities"]` برای ادامهٔ گفت‌وگو |
| `planner_text.py` | تولید متن فارسی پاسخ در مسیر قطعی | بدون LLM هم جواب کامل |
| `decision_helpers.py` | ساخت گزینه‌ها + اقتصاد هر گزینه (تخمین زمانی، نازک‌بودن حاشیه) | منبع `expected_gain` |
| `decisions.py` | ساخت/به‌روزرسانی/تأیید/اندازه‌گیری `BrainDecision` | یک `decision_id` در تمام مسیر |
| `policies.py` | سیاست ساختاریافتهٔ فروشگاه | ۱۲ کلید پیش‌فرض، قابل تغییر توسط مدیر |
| `memory.py` | گفت‌وگو، فکت کسب‌وکار، سیاست، حافظهٔ تصمیم | هرگز کل تاریخچه به پرامپت نمی‌رود |
| `followups.py` | موتور پیگیری + قرارداد اندازه‌گیری | `MEASUREMENT_SPECS` (۱۰ معیار) |
| `agents.py` | ۸ متخصص؛ فقط `Evidence` | تضاد بین متخصص‌ها تشخیص داده می‌شود |
| `tools.py` | پیاده‌سازی ۳۷ ابزار | همه از سرویس‌های موجود v3.x می‌خوانند |
| `registry.py` | `ToolSpec` + مجوز + `ACTION_TOOLS` | دروازهٔ امنیتی اصلی |
| `context.py` | `ToolContext`: db، user، trace، اعداد ثبت‌شده | `ctx.cached(key, producer)` |
| `prompts.py` | پرامپت‌ها + قواعد لحن فارسی | «وضعیت / دلیل / پیشنهاد / اقدام بعدی» |
| `runtime.py` | `AIProvider` (local/cloud/template) + `ToolLoop` | حداکثر ۸ دور ابزار |
| `model_manager.py` | detect→select→download→verify→install→load→benchmark→activate | rollback با `previous_install_id` |
| `model_registry.py` | رجیستری مدل‌ها + FORBIDDEN + sha256 | سقف ۲ گیگابایت |
| `device_profile.py` | RAM/CPU/دیسک → انتخاب مدل و context | روی ۴ گیگابایت هرگز ۸۱۹۲ نمی‌دهد |
| `proactive.py` | ۸ ناظر، بدون تکرار، با سقف سیاست | `evaluate()`, `status()`, `recommendations()` |
| `grounding.py` | اعتبارسنجی اعداد و ارجاع‌ها | عدد بی‌منبع → REJECT |
| `vision.py` | `VisionProvider`/`VisionAgent` فقط اینترفیس | عمداً بدون پیاده‌سازی |
| `audit.py` | ثبت رخداد مغز | `log()`/`label()` |
| `persian.py` | اعداد/تاریخ/پول فارسی | `money()` خودش « تومان» می‌گذارد |
| `schemas.py` | ساختار داده‌های مشترک | `Situation.digest` عدد-آگاه |

---

## ۳. جریان یک سؤال واقعی

مسیر کامل «فردا چقدر پول لازم دارم؟» روی فروشگاه نمونه:

```
/routers/brain.py  →  brain.answer(db, question, user)
   planner.classify()        →  intent=CASH_PRESSURE, entities={}
   situation.build(light)    →  cash=186M, cheques=[120M فردا, 80M +3روز], flags={CASH_GAP_AHEAD,CASH_FRAGILE}
   agents: Finance.collect() →  Evidence(forecast: کمترین 32.2M، روز 12 زیر کف 40M)
           Inventory.collect()→  Evidence(expiry: ۳ قلم نزدیک انقضا)
           Supplier.collect() →  Evidence(شرایط پرداخت تأمین‌کنندهٔ راهبردی)
   contradictions.detect()   →  MARGIN_AND_CASH (هشدار، نه توقف)
   decision_helpers.options()→  chase_receivable (+7.8M) | negotiate_supplier_terms (+1.365M) | no_action
   policies.evaluate()       →  «تخفیف بیش از ۱۵٪ بدون تأیید ممنوع»
   decisions.create()        →  decision_id=1 (NEEDS_DECISION)
   planner_text._cash()      →  متن فارسی با اعداد ثبت‌شده
```

پاسخ نهایی برای مدیر کوتاه است، اما همهٔ اعدادش از `ctx.known_numbers()` می‌آید.

---

## ۴. قراردادها

### ۴.۱ `ToolSpec`

هر ابزار اعلام می‌کند: `name`, `description`, `input_schema`, `output_schema`, `permissions`, `side_effects`, `reversible`, `risk_level`, `data_sources`.
بدون این فیلدها ابزار در رجیستری ثبت نمی‌شود (`tests/test_v40_security.py` این را چک می‌کند).

### ۴.۲ `Evidence`

```python
Evidence(kind="expiry_risk", summary="…", numbers={…}, confidence="high",
         source="get_expiry_risk", details=[…])
```

- `kind` از فهرست بسته.
- `numbers` باید دقیقاً همان چیزی باشد که ابزار برگردانده.
- متخصص (agent) هیچ‌وقت `decision` یا `action` نمی‌سازد.

### ۴.۳ `Decision`

```
decision_id, problem, evidence[], options[], selected, reason,
approval{state,by,at}, action{type,payload}, result{}, measurement{metric,window_days,baseline,success_rule},
outcome ∈ {POSITIVE, NEUTRAL, NEGATIVE, INSUFFICIENT, NOT_MEASURABLE}
```

`INSUFFICIENT` یعنی «دادهٔ کافی برای داوری نبود» — هیچ‌وقت به `POSITIVE` تبدیل نمی‌شود.

### ۴.۴ دستهٔ اقدام

| کلاس | معنی | نمونه |
|---|---|---|
| `AUTO` | بی‌خطر، فقط ثبت | `create_followup`, `record_memory_fact` |
| `APPROVAL` | نیازمند تأیید مدیر | `update_price`, `create_campaign`, `send_sms`, `create_purchase_order` |
| `HIGH_RISK` | پرداخت/انتقال/حذف — همیشه تأیید | هر انتقال وجه یا حذف داده |

اجرای واقعی همیشه از `services/insight_actions.py` می‌گذرد (SAVEPOINT + VERIFY + COMMIT + audit).

---

## ۵. مرزهای امنیتی (خلاصه — جزئیات در `AI_SECURITY.md`)

- کل `/api/brain/*` پشت `Depends(admin_user)` است: `reports.view` **و** `settings.manage`.
- صندوق‌دار به هیچ مسیر مغز نمی‌رسد (۲۴ مسیر تست شده → ۴۰۳).
- ابزار مالی برای صندوق‌دار `ToolDenied` می‌دهد و تلاش در `ctx.trace` ثبت می‌شود.
- هیچ اجرایی پیش از تأیید رخ نمی‌دهد (`execution.executions == []`).
- پرداخت/انتقال/حذف بدون تأیید ممکن نیست، حتی اگر مدل پیشنهاد داده باشد.

---

## ۶. کاهش تدریجی (Degradation) — صادقانه

| وضعیت | رفتار | آنچه مدیر می‌بیند |
|---|---|---|
| مدل محلی نیست | `TemplateProvider` | «پاسخ قطعی» در نوار وضعیت |
| مدل خطا داد | پاسخ قطعی + `warnings=[MODEL_FAILED]` | «مدل محلی پاسخ نداد؛ پاسخ قطعی نمایش داده شد» |
| عدد بی‌منبع | حذف از پاسخ + `warnings=[NUMBER_REJECTED]` | «عددی که منبع نداشت حذف شد» |
| داده ناقص | تصمیم با `confidence=blocked` | «کیفیت داده پایین است» |
| اینترنت نیست | `search_web` خطا می‌دهد | «داده‌ای در دسترس نبود» — هرگز داده جعلی |
| ابر فعال نیست | مسیر محلی کامل کار می‌کند | حالت «فقط محلی» (پیش‌فرض) |

**فلسفهٔ حاکم:** اگر سیستم چیزی نمی‌داند، همان را می‌گوید. صفر پیشنهاد یک پاسخ معتبر است.

---

## ۷. آنچه عمداً ساخته نشد

- **Vision**: فقط اینترفیس (`vision.py`). تصمیم مالی از تصویر ممنوع.
- **Fine-tuning آنلاین**: هیچ به‌روزرسانی وزن مدل روی دستگاه. «یادگیری» = حافظهٔ ساختاریافته + قرارداد اندازه‌گیری، نه تغییر وزن.
- **مخزن برداری/embedding سنگین**: بازیابی با SQL و کلیدواژه، سبک برای Android.
- **قیمت‌گذاری/حسابداری دوباره‌نویسی‌شده**: همه به سرویس‌های موجود وصل شده‌اند.

---

## ۸. نگاشت به نیازهای بریف

| نیاز | جای پیاده‌سازی |
|---|---|
| Business State | `situation.py` |
| Tool Registry | `registry.py` + `tools.py` |
| ۸ متخصص | `agents.py` |
| حافظهٔ ۵گانه | `memory.py` + مدل‌های `brain_*` |
| Measurement Contract | `followups.py` |
| Finance قطعی | `tools.py` روی `accounting.py`/`ledger.py`/`insights.py` |
| Decision Center | `decisions.py` + `frontend/brain.js` |
| Proactive | `proactive.py` |
| Model Runtime | `runtime.py` + `model_manager.py` + `model_registry.py` |
| API | `routers/brain.py` |
