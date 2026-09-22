# AI BRAIN — ARCHITECTURE AUDIT (v4.0)

**تاریخ:** 2026-09-23
**کامیت پایه:** `c7079af` (Release 3.8.0)
**دامنهٔ بررسی:** کل مخزن — backend (۹۶ فایل Python)، ۱۶ migration، ۴۸ فایل تست، frontend (۸٫۱۲۶ خط JS)، mobile-android (۴۳ فایل Java، pipeline بدون Gradle)، installer/CI، hardware layer، security/RBAC، Intelligence، Action Engine، accounting، inventory، sales، customers، suppliers، sync.
**روش:** خواندن کد + اجرای واقعی `pytest` (نتیجه: **۵۹۳ passed, 1 skipped** در ۳۳۸ ثانیه) + ردیابی مسیر داده تا دیتابیس. هیچ ادعایی در این سند بدون ارجاع به فایل/خط ثبت نشده است.

> این سند **قبل از** پیاده‌سازی نوشته شده و مبنای طراحی v4.0 است. هر تغییری که در ادامه با این سند نخواند، در `RELEASE_AUDIT_4.0.0.md` به‌عنوان انحراف ثبت می‌شود.

---

## ۱. معماری فعلی — واقعیت کد، نه ادعای مستندات

### ۱.۱ لایه‌ها

```
frontend (index.html + app.js + insights.js)     ← SPA بدون فریم‌ورک، توکن در localStorage
        ↓ fetch /api/*
backend/app/routers/*.py      (۲۴ روتر، همگی prefix=/api)     ← فقط اعتبارسنجی + مجوز
        ↓
backend/app/services/*.py     (۴۲ سرویس)                        ← منطق کسب‌وکار + تراکنش
        ↓
backend/app/models/*.py       (۲۶ مدل، ۳۵ جدول)                 ← SQLAlchemy 2.0 style
        ↓
SQLite (WAL) / PostgreSQL                                       ← Alembic (head: c5d9e2f7a4b6)
```

مسیر فکر فعلی برای «هوش»:

```
InvoiceItem/StockMovement/Cheque/... → services/insights.py (Ctx) → ANALYZERS (۷۸ عدد)
   → Draft(kind, dedupe_key, title, body, priority, evidence, actions, expected_gain, metric)
   → جدول ai_insights (upsert بر اساس (kind, dedupe_key))
   → UI: کارت‌های فید «هوش فروشگاه» (frontend/insights.js)
   → accept() → insight_actions.execute() → VALIDATE/SAVEPOINT/EXECUTE/VERIFY
   → baseline + measure_all() → measured_gain  (AND-CALIBRATION: services/forecast.py)
```

**نتیجهٔ دقیق:** v3.8 یک Rule/Analyzer Engine محلیِ *صادق* است — نه یک مغز کسب‌وکار. عدد جعلی تولید نمی‌کند، Data Quality را گیت می‌کند، Action Engine با savepoint و verify دارد، و outcome را اندازه می‌گیرد. اما:

| شکاف | شاهد در کد |
|---|---|
| «وضعیت فروشگاه» وجود ندارد؛ فقط لیست کارت‌ها وجود دارد | `insights.run()` خروجی `{created, refreshed, errors}` می‌دهد، هیچ snapshot از وضعیت نمی‌سازد |
| کاربر نمی‌تواند سؤال بپرسد | هیچ endpoint مکالمه‌ای وجود ندارد؛ `ai_narrator` فقط *روایت* یک insight آماده را می‌نویسد |
| تصمیم ثبت نمی‌شود | جدول `ai_insights` تصمیم را نگه نمی‌دارد: `reason`, `options`, `approval` ندارد |
| حافظه وجود ندارد | نه تاریخچهٔ مکالمه، نه سیاست مدیر (`mpolicy`)، نه حافظهٔ تصمیم در سطح موجودیت |
| Follow-up وجود ندارد | `Notification` یک‌بارمصرف است؛ پیگیری زمان‌دار وجود ندارد |
| Proactive محدود | ۷۸ analyzer با آستانه‌های سخت‌کد؛ خوشه‌بندی، سقف هشدار و «meaningful» بودن ندارد |
| LLM اختیاری و غیرمحلی است | `ai_narrator` فقط OpenAI-compatible ابری (OpenRouter/Groq/…) یا Ollama روی PC؛ روی Android هیچ runtime محلی وجود ندارد |
| Agent/Tool وجود ندارد | Analyzer تابع خالص روی `Ctx` است؛ قابل فراخوانی هدف‌دار توسط یک مغز نیست |
| Policy Memory وجود ندارد | تخفیف/بدهی/چک فقط در تنظیمات پراکنده (`pos.max_manual_discount_pct`) است، نه یک لایهٔ سیاست تصمیم |

### ۱.۲ قابلیت‌های سالمی که v4.0 **باید** روی آن‌ها سوار شود (بازنویسی = ممنوع)

| قابلیت | فایل | چرا reusable است |
|---|---|---|
| Action Engine | `services/insight_actions.py` | `validate_action()` + `ACTIONS` + `_verify()` + `execute()` با savepoint و audit. هر action جدید فقط با اضافه‌کردن یک entry + یک verify-kind به همان موتور می‌نشیند |
| Measurement Contract | `services/insights.py` (`METRIC_SPECS`, `measure()`, `measurement_verdict`) | baseline/window/success-rule و خروجی‌های صادقانه (`NOT_MEASURABLE`, `INSUFFICIENT_DATA`) |
| Calibration | `services/forecast.py` (`learn`, `calibrate`) | ضریب یادگیری per-kind روی outcome واقعی |
| Data Quality Gate | `services/data_quality.py` (`run_all`, `blocks_intelligence`) | CRITICAL → سکوت کامل؛ MEDIUM/LOW → کاهش confidence |
| ۷۸ Analyzer | `services/insights.py` + `services/insights_pro.py` + `services/opportunity.py` | تابع `(Ctx) -> list[Draft]`؛ برای Brain به «Tool» تبدیل می‌شوند نه بازنویسی |
| RBAC | `security.py` (`PERMISSIONS`, `require_permission`, `has_permission`, `_user_permission_codes`) | Brain همان مجوزها را چک می‌کند؛ هیچ مسیر دور زدن ندارد |
| Audit | `services/audit.py` (`write_audit`) | همهٔ اقدام‌ها قبل/بعد ثبت می‌شوند |
| Accounting/Cheque/Cash | `services/accounting.py` (`trial_balance`, `account_balance`, `record_cheque`, `clear_cheque`, `session_summary`) | منبع حقیقت پول؛ Brain هرگز عدد پول خود نمی‌سازد |
| Expiry | `services/expiry.py` (`expiry_scan`, `classify`, `days_until`) | ورودی مستقیم Tool «ریسک انقضا» |
| Inventory | `services/inventory.py` (`product_total_stock`, `adjust_batch`, `record_waste`) | Tool موجودی/اتلاف |
| POS/Sales | `services/pos.py`, `services/reports.py` | Tool فروش و روند |
| Prediction | `services/forecast.py` (`plan`, `predict_for`) | Tool پیش‌بینی سود |
| Sync | `services/sync.py` + `services/cloud.py` + `routers/mobile.py` | مسیر آفلاین Android→PC که تصمیم‌های `pending_sync` رویش سوار می‌شوند |
| Hardware | `services/hw/*` + `services/hardware.py` | Toolهای printer/drawer/scanner/scale برای Brain |
| SMS/Campaign/Coupon | `services/sms.py`, `services/coupons.py`, `models/marketing.py` | اجراکنندهٔ واقعی actions |
| Settings | `models/system.py::SystemSetting` | بستر Policy/Store Profile بدون migration سنگین |

### ۱.۳ محدودیت‌های محیطی (صادقانه)

| موضوع | وضعیت واقعی |
|---|---|
| Python | 3.11.2 در sandbox؛ deps نصب‌شدنی از PyPI ✓ |
| تست‌ها | ۵۹۳ تست موجود، ~۵٫۵ دقیقه؛ baseline سبز |
| Android SDK / Gradle / JDK | **در sandbox نصب نیست**. مخزن اما یک pipeline بدون Gradle دارد (`scripts/android/fetch-tools.sh` + `build-apk.sh`) که JRE/ecj/aapt2/d8/apksigner را از PyPI/npm/GitHub می‌گیرد — اگر شبکه اجازه دهد، APK واقعی ساخته می‌شود |
| Windows EXE | غیرقابل ساخت روی Linux (PyInstaller cross-compile نمی‌کند، Inno Setup فقط Windows). سیاست موجود (§3.8.0): **fake EXE ممنوع**؛ workflow آماده + ثبت شفاف |
| GitHub Actions | `.github/workflows/` خالی است؛ workflowها در `installer/ci/` staged هستند (توکن maintenance اسکوپ `workflow` ندارد) |
| llama.cpp | binary در sandbox موجود نیست؛ runtime باید Provider-محور باشد و نبودش را صادقانه اعلام کند |

---

## ۲. Business Brain در کدام لایه می‌نشیند

قاعدهٔ حاکم (از خود صورت‌مسئله، §4): **LLM → SQL ممنوع.**

```
                         ┌─────────────────────── frontend: Decision Center + Admin Chat
                         │
routers/brain.py  ───────┴───►  services/business_brain/brain.py   (BusinessBrain façade)
                                        │
        ┌───────────────────────────────┼──────────────────────────────┐
        ▼                               ▼                              ▼
  situation.py                    planner.py                      decisions.py
  (Business State)          (reasoning loop + tools)         (record/approve/execute)
        │                               │                              │
        │                      ┌────────┴─────────┐                    │
        │                      ▼                  ▼                    ▼
        │                 registry.py       agents.py         services/insight_actions.py
        │                 (Tool Registry)  (8 متخصص)          (VALIDATE→SAVEPOINT→
        │                      │                  │            EXECUTE→VERIFY→COMMIT)
        │                      ▼                  ▼                    │
        │                 tools.py  ◄─── سرویس‌های موجود (accounting, inventory,     │
        │                      │        insights analyzers, forecast, expiry, sms…)  │
        │                      ▼                                                   ▼
        └──────────────►  DB (فقط از طریق سرویس، هرگز از LLM)  ◄─────────── audit.py
                                        ▲
                       context.py ──────┘        policies.py / memory.py / followups.py
                                                 runtime.py (llama.cpp | cloud | template)
```

سه ضلع مستقل: **فهم وضعیت** (situation)، **استدلال** (planner + agents + tools)، **اجرا و پیگیری** (decisions + insight_actions + followups + measurement + memory).

قاعدهٔ سخت قابل تست:

1. `BusinessBrain` هیچ‌گاه `db.execute(select(...))` دست‌نویس برای دامنهٔ مالی نمی‌زند؛ فقط Tool.
2. هر Tool در `registry.py` مجوز (`permission`) و `risk_level` دارد؛ فراخوانی بدون مجوز → `ToolDenied` (تست‌پذیر).
3. مدل زبانی چه در حالت LLM و چه در حالت deterministic فقط می‌تواند **پیشنهاد** بدهد؛ اعتبارسنجی اعداد در `grounding.py` انجام می‌شود و عدد بدون منبع deterministic → `REJECT`.
4. اجرای هر action از مسیر `insight_actions.execute()` می‌گذرد (بدون استثنا).
5. اگر مدل بارگذاری نشده باشد، Brain **کار می‌کند** — با پاسخ‌های deterministic فارسی از همان Tool/Agent/Policy. حالت `degraded` در UI و `/api/brain/status` اعلام می‌شود.

---

## ۳. فایل‌هایی که تغییر می‌کنند (و چرا)

### ۳.۱ جدید — backend

```
backend/app/services/business_brain/
    __init__.py          خروجی‌های عمومی (BusinessBrain, get_brain)
    schemas.py           dataclass/enum: Situation, ToolSpec, Evidence, Option, Decision, Measurement
    store_profile.py     پروفایل فروشگاه (structured، از settings + برآورد از داده)
    policies.py          Policy Memory + PolicyGate (max_discount, min_cash_reserve, اولویت تأمین‌کننده)
    context.py           ToolContext (db, user, permissions, clock, cache, audit hook)
    situation.py         SituationBuilder — وضعیت چنددامنه‌ای + Data Quality + state_hash
    tools.py             پیاده‌سازی ~۴۰ Tool روی سرویس‌های موجود
    registry.py          ToolRegistry: schema/permission/risk/reversible/side_effects + اجرا + audit
    agents.py            ۸ Agent متخصص (Finance, Inventory, Sales, Customer, Supplier, Pricing, Operations, Marketing)
    memory.py            Conversation / Business / Policy memory + retrieval قطعی
    decisions.py         ثبت تصمیم، تأیید، اجرا، Measurement Contract، Outcome، Conflict
    followups.py         موتور پیگیری (زمان‌دار، نتیجه‌محور)
    proactive.py         اسکن proactive + خوشه‌بندی + سقف هشدار + گیت meaningful/actionable
    planner.py           حلقهٔ استدلال: intent → tools → agents → تعارض → گزینه‌ها → تصمیم → policy
    prompts.py           پرامپت فارسی + پارامترهای thinking/fast + قواعد لحن
    runtime.py           AIProvider: LlamaCppProvider | OpenAICompatProvider | TemplateProvider
    model_registry.py    رجیستری مدل‌ها با sha256/حجم/سقف 2GB (Qwen3-1.7B Q4_K_M / Q3_K_M)
    model_manager.py     detect → select → download → verify → install → load → benchmark → activate → rollback
    device_profile.py    تشخیص RAM/CPU/دیسک → پروفایل (4GB | 6GB+)
    grounding.py         اعتبارسنجی اعداد و «NO_FAKE_NUMBER»
    persian.py           قالب‌های پاسخ (وضعیت/دلیل/پیشنهاد/اقدام بعدی) + ارقام فارسی
    audit.py             رویدادهای BRAIN_* در AuditLog
    vision.py            VisionProvider / VisionAgent (interface — پیاده‌سازی فاز بعد، فعال نیست)

backend/app/models/brain.py         ۶ جدول جدید (BrainMessage, BrainDecision, BrainFollowup,
                                    BrainPolicy, BrainModelInstall, BrainMemoryFact)
backend/app/routers/brain.py        /api/brain/*
backend/alembic/versions/20260923_*_v4_0_business_brain.py   (down_revision=c5d9e2f7a4b6)
backend/tests/test_v40_*.py         ۶ فایل تست جدید
frontend/brain.js                   Decision Center + Admin Chat + پنل مدل/وضعیت
scripts/model/fetch_model.py        دانلود/verify مدل (مشترک Windows/Android/CI)
```

### ۳.۲ تغییر — حداقلی و جراحی‌شده

| فایل | تغییر | دلیل/محدودیت |
|---|---|---|
| `backend/app/main.py` | `include_router(brain.router, prefix="/api")` + شروع/توقف worker proactive | یک خط در حلقهٔ روترها + یک بند در lifespan |
| `backend/app/__init__.py` | `__version__ = "4.0.0"` | منبع واحد نسخه (CI هم از همین می‌خواند) |
| `frontend/index.html` | `<script src="brain.js">` + یک nav entry | بدون تغییر ساختار SPA |
| `frontend/insights.js` | **فقط** لینک «مرکز تصمیم» در بالای فید | فید قدیمی حذف نمی‌شود (§85 نباید بشکند) |
| `frontend/sw.js` | افزودن `brain.js` به کش | آفلاین |
| `backend/app/services/insight_actions.py` | افزودن چند action type جدید (task/PO/price برای Brain) با همان الگوی spec+verify | **بازنویسی نمی‌شود**؛ فقط توسعهٔ رجیستری |
| `installer/windows/run_supermarket.py` | مرحلهٔ model bootstrap پیش از اجرا (idempotent) | مدل داخل EXE نباشد |
| `installer/ci/release-windows.yml` | نصب/benchmark مدل + تست‌های جدید | CI واقعی |
| `installer/ci/tests.yml` | بدون تغییر منطق (کل suite اجرا می‌شود) | گیت سبز |
| `mobile-android/.../Brain*.java`, `ModelManager.java`, `LlamaRuntime.java` | Admin Chat + Decision Center + دانلود/verify مدل + runtime bridge | فقط برای Administrator |
| `mobile-android/app/src/main/AndroidManifest.xml` | `BrainActivity` | UI جدای مدیر |
| `README.md`, `CHANGELOG.md`, `docs/AI_*.md`, `RELEASE_AUDIT_4.0.0.md` | مستندسازی | §82 |

### ۳.۳ فایل‌هایی که **بازنویسی نمی‌شوند**

`services/insights.py`, `services/insights_pro.py`, `services/opportunity.py`, `services/pos.py`, `services/accounting.py`, `services/inventory.py`, `services/pricing*.py`, `services/sms.py`, `services/sync.py`, `services/cloud.py`, `services/data_quality.py`, `services/forecast.py`, `services/experiments.py`, `services/hw/*`, `security.py`, `models/*` (به‌جز افزودن `brain.py`). هرگونه بازنویسی این‌ها ریسک رگرسیون روی ۵۹۳ تست سبز را ایجاد می‌کند بدون آنکه چیزی به ارزش محصول اضافه کند.

---

## ۴. Migration لازم

یک migration، یک head جدید (`down_revision = "c5d9e2f7a4b6"`)، idempotent (`IF NOT EXISTS`-style با `sa.inspect`) و reversible:

| جدول | نقش | کلیدهای مهم |
|---|---|---|
| `brain_messages` | Conversation Memory | `session_key`, `role`, `content`, `tool_trace` JSON, `decision_id`, `user_id`, `created_at` |
| `brain_decisions` | Decision Memory (schema §45) | `type`, `problem`, `situation` JSON, `objective`, `evidence` JSON, `options` JSON, `recommended_option`, `selected_option`, `reason`, `risks` JSON, `confidence`, `requires_approval`, `approval` JSON, `actions` JSON, `status`, `policy_verdict` JSON, `execution` JSON, `measurement` JSON, `outcome`, `measured_gain`, `insight_id`, `origin` (CHAT/PROACTIVE/UI/OFFLINE), `local_decision`, `pending_sync`, `conflict_with` |
| `brain_followups` | Follow-up Engine | `decision_id`, `kind`, `title`, `due_at`, `status`, `note`, `notified_at`, `resolved_at` |
| `brain_policies` | Policy Memory | `key` (unique), `value` JSON, `scope`, `source` (OWNER/DEFAULT/LEARNED), `updated_by`, `note` |
| `brain_model_installs` | Model Manager | `model_id`, `path`, `size_bytes`, `sha256`, `status`, `device_profile` JSON, `benchmark` JSON, `activated_at`, `previous_install_id` (rollback) |
| `brain_memory_facts` | Business Memory بلندمدت | `kind`, `key`, `value` JSON, `confidence`, `source`, `observed_at`, `expires_at` |

بدون حذف/تغییر هیچ ستون موجود → بدون data loss. `upgrade()` جداول را می‌سازد، `downgrade()` آن‌ها را می‌اندازد (تنها همین‌ها).

---

## ۵. API لازم (پیروی از convention موجود: prefix `/api`, مجوز گرانولار، پاسخ فارسی-دوست)

```
GET    /api/brain/status                 وضعیت: model/mode/profile/context/ready/degraded/cloud/web/dq
POST   /api/brain/chat                   {message, session_key} → {reply, decision?, tools_used[], mode}
GET    /api/brain/situation              وضعیت فعلی فروشگاه (بدون LLM)
GET    /api/brain/alerts                 هشدارهای proactive (خوشه‌بندی‌شده، سقف‌دار)
GET    /api/brain/decisions              لیست تصمیم‌ها (فیلتر status/from/to)
GET    /api/brain/decisions/{id}         جزئیات + evidence + options + measurement
POST   /api/brain/decisions/{id}/approve اجرا از طریق Action Engine
POST   /api/brain/decisions/{id}/reject
POST   /api/brain/decisions/{id}/measure اندازه‌گیری نتیجه
GET    /api/brain/followups              پیگیری‌های باز/انجام‌شده
POST   /api/brain/followups/{id}/resolve
GET    /api/brain/memory                 حافظهٔ کسب‌وکار (facts + decisions + conversations)
GET/PUT/DELETE /api/brain/policies       Policy Memory
GET/PUT /api/brain/profile               Store Profile
GET    /api/brain/model                  لیست رجیستری + وضعیت نصب + پروفایل دستگاه
GET    /api/brain/model/status           آماده/در حال دانلود/نصب‌شده
POST   /api/brain/model/download         شروع دانلود (HTTPS + SHA256)
POST   /api/brain/model/benchmark        اجرای benchmark واقعی روی دستگاه
POST   /api/brain/model/activate|unload|rollback|delete
```

مجوزها: `reports.view` برای خواندن وضعیت/تصمیم‌ها، `settings.manage` برای approve/reject/policies/profile/model. Chat فقط برای کاربری که هم `reports.view` و هم `settings.manage` دارد (Administrator؛ Cashier → 403). این معیار در تست امنیتی صریح بررسی می‌شود.

---

## ۶. تست‌های لازم (همه باید واقعاً اجرا شوند)

| فایل | پوشش |
|---|---|
| `test_v40_brain_tools.py` | registry، schema، permission-denied، risk/side-effect/reversible، no-SQL از LLM، tools واقعی عدد deterministic می‌دهند |
| `test_v40_brain_reasoning.py` | سؤال ساده، چنددامنه‌ای، داده ناقص، NO_ACTION، انتخاب tool، حلقهٔ محدود (≤8)، حافظه، policy retrieval، تضاد Agentها |
| `test_v40_brain_finance.py` | فشار نقدینگی، تضاد چک، اولویت مطالبات، اولویت تأمین‌کننده، no-fake-number |
| `test_v40_brain_decisions.py` | create → approve → execute → verify → measure → outcome، followup، conflict، offline/pending_sync |
| `test_v40_model_manager.py` | رجیستری ≤2GB، checksum نامعتبر → حذف، فایل خراب، load/unload، benchmark، fallback Q3، rollback |
| `test_v40_acceptance.py` | سناریوهای ۶۶ تا ۷۱ صورت‌مسئله (شامل تفاوت جواب دو فروشگاه متفاوت) |
| `test_v40_brain_security.py` | Cashier → 403، tool مالی بدون مجوز بلاک، action بدون مجوز بلاک، عدم نشت privacy |

معیار: تمام تست‌های قبلی سبز بمانند (رگرسیون صفر) + تست‌های جدید سبز.

---

## ۷. ریسک‌ها و تصمیم‌های طراحی

| ریسک | تصمیم |
|---|---|
| اضافه‌کردن dependency سنگین (llama-cpp-python با کامپایل C++ روی Windows/Android) | **اضافه نمی‌شود.** runtime از طریق subprocess/HTTP به یک binary مستقل llama.cpp حرف می‌زند؛ اگر نبود، `TemplateProvider` |
| مدل 1.28GB داخل APK/EXE | داخل بسته نیست؛ `ModelManager` دانلود + verify می‌کند |
| LLM عدد مالی بسازد | `grounding.py` هر عدد پولی متن مدل را با خروجی Toolها تطبیق می‌دهد؛ عدم تطابق → حذف/جایگزینی |
| کندی ۴ گیگ رم | context=4096، thinking فقط در agent mode، unload در فشار حافظه، پروفایل سبک |
| شکستن فید قدیمی | `ai_insights` و همهٔ endpointهای v3.x دست‌نخورده می‌مانند؛ Decision Center یک صفحهٔ *اضافه* است که از همان موتور تغذیه می‌شود |
| تضاد Windows/Android | تصمیم آفلاین با `local_decision=1, pending_sync=1` ذخیره می‌شود؛ در همگام‌سازی، تضاد silent overwrite نمی‌شود و `conflict_with` + نیاز به تصمیم مدیر ثبت می‌گردد |
| Over-alert | `proactive.py` سقف سخت روی تعداد alertهای فعال + خوشه‌بندی + گیت (impact ∧ confidence ∧ actionability) دارد و در صورت نبود مسئلهٔ معنادار `NO_ACTION` برمی‌گرداند |

---

## ۸. جمع‌بندی

v3.8.0 یک **موتور تحلیل صادق** است. v4.0 همان موتور را به‌عنوان *ابزار* زیر یک **مغز کسب‌وکار** می‌برد: وضعیت می‌سازد، سؤال را می‌فهمد، ابزار مناسب را انتخاب می‌کند، شواهد را از چند دامنه جمع می‌کند، تضادها را می‌بیند، چند گزینه می‌سازد، سیاست صاحب فروشگاه را اعمال می‌کند، تصمیم را ثبت می‌کند، از Action Engine موجود برای اجرا استفاده می‌کند، نتیجه را اندازه می‌گیرد و در حافظه نگه می‌دارد تا دفعهٔ بعد هوشمندتر باشد — و اگر مدل محلی نبود، همان کار را با مسیر deterministic انجام می‌دهد و این محدودیت را پنهان نمی‌کند.
