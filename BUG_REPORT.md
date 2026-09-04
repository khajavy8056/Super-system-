# BUG REPORT — رجیستری باگ‌های تأییدشده (فاز Audit)

**تاریخ:** 2026-09-04 · **نسخه:** v0.1.0 (کامیت `ba4a4ad`)

هر باگ با **اثبات تجربی** (اجرای واقعی روی سیستم بوت‌شده) یا **استناد کد** ثبت شده است.
باگ‌های 001 تا 009 به‌صورت تست رگرسیون `xfail(strict=True)` در `backend/tests/test_audit_regressions.py` ماندگار شده‌اند — پس از Fix باید علامت `xfail` برداشته شود (الزام §55/§65).

وضعیت‌ها: `OPEN` (تأییدشده، هنوز اصلاح نشده) · `FIXED` · `WONTFIX`

---

## باگ‌های Critical / High (بلاک‌کننده تجاری‌سازی)

### BUG-001 — کسر دوگانه تخفیف در Checkout (POS / مالی)
- **Severity:** Critical · **Status:** FIXED (فاز ۰ — تست REG-001 + test_discount_via_api_with_tax)
- **توضیح:** `item.subtotal = gross − item.discount` است؛ سپس در `checkout()`: `total = subtotal − discount + tax` → تخفیف **دو بار** کسر می‌شود. مالیات هم روی مبلغ غلط حساب می‌شود.
- **Root Cause:** `app/services/pos.py` — تابع `checkout`، جمع `subtotal` و `discount` ناسازگار.
- **اثبات:** کالای ۲,۰۰۰ با تخفیف ۵۰۰ → پرداخت صحیح ۱,۵۰۰ با `PAYMENT_MISMATCH` رد شد؛ سیستم ۱,۰۰۰ را «درست» می‌داند: `forced: subtotal=1500 discount=500 total=1000 (expected 1500)`
- **Fix برنامه‌ریزی‌شده:** بازتعریف صریح: `gross = Σ(unit_price×qty)`، `subtotal = gross`، `total = gross − Σdiscount + tax(gross−Σdiscount)`؛ افزودن فیلد discount به `CartLineIn` API؛ تست رگرسیون.

### BUG-002 — مرجوعی بیش از مقدار خرید ممکن است (POS / یکپارچگی داده)
- **Severity:** Critical · **Status:** FIXED (فاز ۰ — REG-002 + وضعیت REFUNDED/PARTIALLY)
- **توضیح:** `process_return` فقط `qty > invoice_item.qty` را چک می‌کند؛ مجموع مرجوعی‌های قبلی همان آیتم چک نمی‌شود → با چند مرجوعی جزئی، موجودی به‌دلخواه تورم می‌یابد.
- **Root Cause:** `app/services/pos.py::process_return` — عدم تجمیع `Return`های موجود.
- **اثبات:** خرید ۲ عدد → دو بار مرجوعی ۲ عددی → هر دو `201`؛ موجودی Batch از ۱۰ به **۱۲** رسید (باید ۱۰ بماند).
- **Fix:** `Σ(returns.qty) + qty ≤ invoice_item.qty` + وضعیت صحیح `REFUNDED` در تکمیل + تست.

### BUG-003 — تخصیص خودکار فروش بین چند Batch وجود ندارد (POS / معماری)
- **Severity:** High · **Status:** FIXED (فاز ۰ — موتور allocate + REG-003؛ انتخاب Batch صریح عمداً split نمی‌شود)
- **توضیح:** اگر qty درخواستی از یک Batch بیشتر باشد، حتی وقتی مجموع چند Batch کافی است، `INSUFFICIENT_STOCK` داده می‌شود. سناریوی §37 (A=3، B=10، خرید 7) رد می‌شود.
- **Root Cause:** `_resolve_cart_line` فقط تک‌Batch را می‌بیند؛ موتور Allocation پیاده نشده.
- **اثبات:** `checkout qty7 (A=3@20,B=10@22): 422 INSUFFICIENT_STOCK «Only 3 available»`
- **Fix:** تابع `allocate(db, product, qty, policy) → [(batch, qty)…]` + ثبت صریح به‌عنوان «تخصیص حسابداری» نه واقعیت فیزیکی (§17).

### BUG-004 — تصادم/بازاستفاده شماره فاکتور (POS / یکپارچگی)
- **Severity:** High · **Status:** FIXED (فاز ۰ — جدول counters + شماره‌گذاری اتمیک؛ تست همزمانی سبز)
- **توضیح:** `_next_invoice_number` بر پایه `COUNT(invoices per day)` است → (۱) زیر همزمانی دو فاکتور هم‌شماره می‌گیرند و دومی با `UNIQUE constraint failed: invoices.invoice_number` به‌صورت **500 خام** می‌شکند؛ (۲) با حذف رکورد، شماره بازاستفاده می‌شود.
- **Root Cause:** شمارش به‌جای sequence اتمیک.
- **اثبات:** probe همزمانی: `[('OK','INV-…000001'), ('ERR','UNIQUE constraint failed: invoices.invoice_number')]`
- **Fix:** جدول sequence جدا با `UPDATE … RETURNING` (اتمیک) یا `max+1` داخل همان تراکنش با قفل.

### BUG-005 — پنجره Race در کسر موجودی (POS / همزمانی)
- **Severity:** High · **Status:** FIXED (فاز ۰ — کاهش اتمیک شرطی UPDATE…WHERE current_qty≥n؛ تست دو ترمینال همزمان: دقیقاً یک فروش موفق)
- **توضیح:** الگوی read→validate→write بدون قفل سطر/کاهش اتمیک (`UPDATE … SET current_qty = current_qty − n WHERE current_qty ≥ n`) است. دو صندوق می‌توانند موجودی یکسان را بفروشند (TOCTOU).
- **Fix:** کاهش اتمیک شرطی + بررسی `rowcount`؛ در PostgreSQL ردیف‌لاک؛ تست همزمانی واقعی.

### BUG-006 — نتایج Resolver خارجی هرگز ذخیره نمی‌شوند (Barcode Resolver)
- **Severity:** High · **Status:** FIXED (فاز ۱ — POST /barcode/resolve با commit؛ GET فقط‌خواندنی؛ تست endpoint-level PASS)
- **توضیح:** `resolve_barcode` نتایج خارجی را `db.add + flush` می‌کند اما اندپوینت `GET /api/barcode/resolve/{barcode}` هرگز `commit` نمی‌کند و `get_db` با close، تراکنش را rollback می‌کند → «کش محلی» همیشه خالی است؛ GET با عارضه‌ی جانبی هم ضدالگو است.
- **اثبات:** پس از فراخوانی سرویس با منبع خارجی فعال و بستن session بدون commit → `rows persisted: 0`.
- **Fix:** جداسازی خواندن/نوشتن؛ اندپوینت POST برای lookup با commit؛ یا commit صریح.

### BUG-007 — داده خارجی بدون Human-Review وارد جریان می‌شود (Resolver / قاعده §52)
- **Severity:** High · **Status:** FIXED (فاز ۱ — need_manual=True همیشه برای داده خارجی + اندپوینت review + apply با Audit)
- **توضیح:** پاسخ external با `need_manual=False` برمی‌گردد؛ هیچ اندپوینت Approve/Reject برای `ProductResolverResult` وجود ندارد؛ فیلد `status` همیشه PENDING می‌ماند (و به‌واسطه BUG-006 اصلاً ذخیره هم نمی‌شود).
- **Fix:** جریان کامل §9: candidates → review UI → approve → ساخت Product.

### BUG-008 — منابع خارجی (Providers) از API/UI قابل پیکربندی نیستند (Resolver)
- **Severity:** High · **Status:** FIXED (فاز ۱ — معماری Provider/Registry + CRUD کامل منابع از API؛ Providerهای ثبت‌شده: openfoodfacts، custom_http)
- **توضیح:** هیچ CRUDی برای `ExternalSource` وجود ندارد (نه router، نه UI). تنها راه، دستکاری مستقیم دیتابیس است → کل زیرسیستم Multi-Source عملاً غیرقابل بهره‌برداری. Provider Interface هم不存在 نیست (منطق URL-template داخل `_fetch` هاردکد است).
- **Fix:** معماری Provider قابل‌افزودن (§11) + CRUD + اولویت/فعال‌سازی.

### BUG-009 — خطای سرویس خارجی بی‌صدا بلعیده می‌شود (Resolver)
- **Severity:** Medium · **Status:** FIXED (فاز ۱ — ProviderError با kind طبقه‌بندی‌شده: TIMEOUT/UNREACHABLE/NOT_FOUND/INVALID_RESPONSE/RATE_LIMITED/AUTH_ERROR/HTTP_x)
- **توضیح:** `_fetch` همه exceptionها را `return None` می‌کند → Timeout/404/InvalidResponse/RateLimit غیرقابل تفکیک از «یافت نشد». اثبات: منبع روی پورت بسته → `origin=none` بدون هیچ گزارش خطا.
- **Fix:** نتیجه per-source با status code/خطا + timeout مجزا (§40).

### BUG-010 — افشای تنظیمات محرمانه (Settings / امنیت)
- **Severity:** High · **Status:** FIXED (فاز ۰ — REG-005: ماسک + has_value + سنتینل __KEEP__ + به‌روزرسانی is_secret)
- **توضیح:** `GET /api/settings` مقدار واقعی کلیدهای محرمانه را plaintext برمی‌گرداند (`sms.password` تست شد: `SUPER-SECRET-99` برگشت_data شد). ضمناً `upsert_setting` فیلد `is_secret` را به‌روز نمی‌کند.
- **Fix:** write-only برای secrets + ماسک در پاسخ + ثبت Audit بدون مقدار.

### BUG-011 — نداشتن Rate-Limit / Logout / قفل حساب (Auth / امنیت)
- **Severity:** High · **Status:** OPEN
- **توضیح:** ۱۰ ورود غلط پشت‌سرهم → فقط 401 (بدون 429/قفل). `POST /api/auth/logout` وجود ندارد (405) → رویداد LOGOUT هم هرگز Audit نمی‌شود (نقض §43). ورودهای ناموفق Audit نمی‌شوند.
- **Fix:** محدودسازی تلاش + logout با Audit + ثبت USER_LOGIN_FAILED.

### BUG-012 — XSS ذخیره‌شده در پنل وب (Frontend / امنیت)
- **Severity:** High · **Status:** OPEN
- **توضیح:** نام کالا بدون escape داخل `innerHTML` تزریق می‌شود: مودال انتخاب Batch (`${p.name}`)، رسید (`showReceipt` → `<pre>${text}</pre>`)، مودال انبارگردانی (`${st.name}`). کاربرِ دارای `products.manage` می‌تواند در مرورگر صندوق‌دار کد اجرا کند. CSP هم وجود ندارد.
- **Fix:** escaper/`textContent` برای همه سنک‌ها + CSP + Security headers.

### BUG-013 — اعتبارنامه پیش‌فرض admin/admin123 خودکار (Auth / استقرار)
- **Severity:** Medium · **Status:** OPEN
- **توضیح:** bootstrap همیشه admin با `ADMIN_PASSWORD` پیش‌فرض می‌سازد؛ فرم لاگین هم `value="admin"/"value="admin123"` پر شده؛ هیچ اجباری برای تغییر در اولین ورود نیست؛ SECRET_KEY پیش‌فرض هاردکد fallback.
- **Fix:** wizard اولین‌بار (تولید رمز تصادفی + نمایش یک‌باره) + حذف prefilled.

### BUG-014 — ناسازگاری Alembic با create_all (Database)
- **Severity:** Medium · **Status:** FIXED (فاز ۰ — create_all + stamp/upgrade در init_db؛ تأیید تجربی: upgrade بعد از بوت = no-op در head)
- **توضیح:** برنامه در هر بوت `Base.metadata.create_all` می‌زند؛ پس از اولین اجرا، `alembic upgrade head` با `table brands already exists` fail می‌شود → سیستم مهاجرت عملاً بلااستفاده/گمراه‌کننده است.
- **Fix:** حذف create_all از lifespan (فقط Alembic) + `alembic stamp` برای نصب‌های موجود.

### BUG-015 — SMS صف بی‌فرستنده (SMS)
- **Severity:** High · **Status:** OPEN
- **توضیح:** `POST /sms/send` فقط رکورد `PENDING` می‌سازد؛ هیچ Worker/Provider/زمان‌بندی وجود ندارد → پیام همیشه PENDING می‌ماند (تأیید کد + grep). مستندات API کد خطای `SMS_PROVIDER_ERROR` را می‌دهد که وجود خارجی ندارد.
- **Fix:** Adapter ملی‌پیامک/کاوه‌نگار + Worker با retry (SmsStatus.RETRYING استفاده نشده).

### BUG-016 — ثبت موفقیت جعلی چاپ (Hardware / صداقت داده)
- **Severity:** High · **Status:** OPEN
- **توضیح:** با دستگاه PRINTER با status=CONNECTED (بدون هیچ درایوری) → `print_receipt` مقدار `print_status=SUCCESS` و `ok=True` برمی‌گرداند بی‌آنکه بایتی چاپ شود (اثبات‌شده). Drawer هم در حالت CONNECTED «pulse sent» برمی‌گرداند بدون ارسال.
- **Fix:** درایور واقعی (ESC/POS) یا وضعیت صادقانه `NOT_SUPPORTED` تا راه‌اندازی درایور.

### BUG-017 — جداافتادگی کامل PriceVersion از موتور فروش (Pricing / معماری)
- **Severity:** High · **Status:** FIXED (فاز ۰ — ADR-001: ارث قیمت از نسخه فعال + seed تاریخچه از اولین Batch؛ تست test_receive_inherits_active_price_version)
- **توضیح:** `set_price` نسخه قیمت می‌سازد اما POS فقط `batch.sell_price` را می‌خواند → تغییر قیمت از API **هیچ اثری بر فروش ندارد**. `receive_batch` هم PriceVersion نمی‌سازد → «تاریخچه قیمت» عملاً همیشه خالی است. مستندات معماری خلاف این را القا می‌کند.
- **Fix:** تصمیم معماری: PriceVersion به‌عنوان منبع حقیقت + پیش‌فرض Batch جدید از آن، یا حذف صریح و اتصال تاریخچه به Batch.

### BUG-018 — Stocktaking ناقص (Inventory)
- **Severity:** Medium · **Status:** OPEN
- **توضیح:** (۱) وضعیت `IN_PROGRESS` هرگز set نمی‌شود؛ (۲) اندپوینت پیشرفت/ادامه‌ی معنادار (remaining/resume) وجود ندارد — UI همه آیتم‌ها را در یک مودال نشان می‌دهد؛ (۳) **مرحله تأیید مدیر قبل از Adjustment وجود ندارد** (§19: Manager Approval → Adjustment) — هر انبارداری با `inventory.stocktake` مستقیم موجودی را تغییر می‌دهد؛ (۴) فقط Batchهای `current_qty>0` وارد لیست می‌شوند → کشف موجودیِ کالای «صفرِ سیستمی» غیرممکن است؛ (۵) شمارنده‌ی هر آیتم Audit نمی‌شود.
- **Fix:** چرخه کامل §19-20 + `COUNTED_BY` + پیشرفت + تأیید دو مرحله‌ای.

### BUG-019 — منطق ناقص وضعیت مرجوعی/ابطال (POS)
- **Severity:** Medium · **Status:** FIXED (فاز ۰ — REFUNDED/PARTIALLY_REFUNDED تجمعی + نوع VOID_REVERSAL + reference_id واقعی)
- **توضیح:** `process_return` همیشه `PARTIALLY_REFUNDED` می‌گذارد حتی وقتی کل آیتم برگشته (باید REFUNDED شود)؛ `StockMovement(reference_id=0)` placeholder؛ Void از نوع `RETURN_IN` استفاده می‌کند (گمراه‌کننده در Ledger).
- **Fix:** محاسبه وضعیت از مجموع مرجوعی‌ها + نوع movement مجزا (`VOID_REVERSAL` یا ثبت note).

### BUG-020 — نبود Exception Handler سراسری / Error-ID (API/UX)
- **Severity:** Medium · **Status:** FIXED (فاز ۰ — هندلر سراسری + Error-ID + پیام فارسی؛ تست عدم نشت متن exception)
- **توضیح:** خطای غیرمنتظره → 500 خام (در race واقعی، SQL خطا در پاسخ تست نمایان شد). هیچ Error-ID و پیام کاربرپسند و لاگ ساخت‌یافته‌ای وجود ندارد (نقض §42).
- **Fix:** middleware خطا + کد خطای کاربرپسند + همبستگی با لاگ فنی.

### BUG-021 — UI مبتنی بر نقش نیست + نواقص POS UI (Frontend)
- **Severity:** Medium · **Status:** OPEN
- **توضیح:** منویnavigation ثابت است و بر اساس مجوز فیلتر نمی‌شود (Cashier می‌بیند: Settings/Users/Audit و بعد 403 می‌خورد). Cashier کل داشبورد مدیریتی (سود/ارزش انبار) را می‌بیند (اثبات: `cashier GET /reports/dashboard → 200`). POS: بدون Kiosk/تخفیف/مشتری؛ listener جدید `click` در هر ورود به view اضافه می‌شود (leak).
- **Fix:** nav مبتنی بر مجوز (endpoint `/auth/me` باید permissions برگرداند) + POS اختصاصی.

### BUG-022 — کیفیت کد/عملکرد پراکنده (Backend)
- **Severity:** Low · **Status:** OPEN
- **Status:** PARTIAL-FIXED (فاز ۰: price_freshness tz ✓ · باقی موارد در پاکسازی فاز ۲)
- **توضیح:** `product_total_stock` با `__import__("sqlalchemy")`؛ `if total > 0 or True` کد مرده؛ `total = len(all-rows)` به‌جای COUNT؛ unused import (`notify` در pos.py)؛ تاریخ‌های naive/aware مخلوط → `price_freshness` با `now` آگاه TypeError می‌دهد (اثبات‌شده)؛ `count_item` خطای اعتبارسنجی را 404 می‌دهد؛ پارامتر `group` گزارش فروش ignore می‌شود.
- **Fix:** پاکسازی + lint (ruff) در CI.

### BUG-023 — مستندات بیش از واقعیت (Docs)
- **Severity:** Medium · **Status:** OPEN
- **توضیح:** CHANGELOG: «۲۹ جدول» (واقعیت ۲۸)؛ README ادعاهای §۴ گزارش Audit؛ API.md کدهای خطای ناموجود. برای محصول تجاری، مستندات گمراه‌کننده خطرناک‌تر از نبود قابلیت است.
- **Fix:** بازنویسی صادقانه پس از هر فاز + جدول وضعیت IMPLEMENTED/TESTED/… (§54).

### BUG-024 — Restore و Backup خودکار غایب (Data Safety)
- **Severity:** High · **Status:** OPEN
- **توضیح:** Backup دستی SQLite واقعاً کار می‌کند؛ Restore وجود ندارد؛ زمان‌بندی خودکار و اعتبارسنجی Backup هیچ‌کدام وجود ندارد (§59).
- **Fix:** Restore با تست واقعی + retention policy.

### BUG-025 — قابلیت‌های غایب (ثبت رسمی به‌عنوان MISSING)
- **Severity:** High · **Status:** OPEN (طراحی)
- **توضیح:** Kiosk/Lock Mode (§7)، موبایل/اندروید/PWA (§21-24)، دوربین barcode موبایل، Sync/Offline queue (§25-27)، Image Resolver با Validation (§13)، اعتبارسنجی checksum بارکد (GTIN-13/EAN-8)، GS1/Provider ایرانی، گزارش مغایرت ریالی/تاریخچه خرید/گزارش صندوق‌دار، تنظیمات UI برای SMS/Printer/Kiosk shortcut، CI/CD.
- **Fix:** طبق DEVELOPMENT_PLAN.md.

---

## جمع‌بندی شدت‌ها

| Severity | تعداد | شناسه‌ها |
|---|---|---|
| Critical | 2 | 001, 002 |
| High | 13 | 003, 004, 005, 006, 007, 008, 010, 011, 012, 015, 016, 017, 024 |
| Medium | 8 | 009, 013, 014, 018, 019, 020, 021, 023 |
| Low | 1 | 022 |
| MISSING (قابلیت) | 1 سند جامع | 025 |
