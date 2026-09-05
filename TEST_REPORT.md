# TEST REPORT — گزارش تست فاز Audit

**تاریخ:** 2026-09-04 · **نسخه:** v0.1.0 (کامیت `ba4a4ad`) · **محیط:** Linux / Python 3.11.2 / venv تازه‌ساخته

> این گزارش فقط چیزی را ثبت می‌کند که **واقعاً اجرا شده است**. سخت‌افزار فیزیکی (پرینتر، کشو، اسکنر، ویندوز) در دسترس نبوده و صریحاً «تست‌نشده» اعلام می‌شود.

---

## ۱. تست‌های موجود مخزن

```
$ python -m pytest tests/ -q
21 passed, 2 warnings in 1.97s
```

| فایل | تعداد | وضعیت | پوشش |
|---|---|---|---|
| test_auth.py | 4 | PASS | لاگین موفق/ناموفق، /me، رد بدون توکن |
| test_pos.py | 8 | PASS | فروش چندخطی چندBatch، کسر موجودی، کمبود موجودی، بلاک منقضی، Void، Snapshot قیمت، پیشنهاد Batch، بارکد ناشناخته |
| test_batches.py | 4 | PASS | Batch جدید بدون بازنویسی، فرمت شماره، نمایش قیمت قدیم/جدید، رد حذف Batch پر |
| test_inventory.py | 3 | PASS | تطبیق انبارگردانی، Adjustment+movement+audit، ضایعات |
| test_pricing.py | 2 | PASS | تاریخچه نسخه قیمت، پیشنهاد قیمت با مارجین |

**شکاف‌های پوشش (Critical):** تخفیف، مرجوعی، همزمانی، مجوزها (403)، Resolver خارجی، SMS، تنظیمات محرمانه، چاپ، Backup، انبارگردانیِ نیمه‌کاره/ادامه، Kiosk (ناموجود).

---

## ۲. اثبات‌های تجربی فاز Audit (Probes)

هر probe روی اپلیکیشن واقعاً بوت‌شده (TestClient با lifespan / uvicorn) اجرا شد.

| Probe | ماژول | سناریو | نتیجه مورد انتظار | نتیجه واقعی | وضعیت | باگ |
|---|---|---|---|---|---|---|
| P-01 | POS | Checkout با تخفیف خطی (۲,۰۰۰ − ۵۰۰) | Total=1500، پرداخت پذیرفته شود | `PAYMENT_MISMATCH: Paid 1500 but total is 1000.00` | **FAIL** | BUG-001 |
| P-02 | POS | دو مرجوعی ۲تایی روی آیتم ۲تایی | مرجوعی دوم رد شود | هر دو 201؛ موجودی 12 به‌جای 2 | **FAIL** | BUG-002 |
| P-03 | POS | خرید qty=7 با Batchهای A=3,B=10 | تقسیم 3+4 بین دو Batch | `422 INSUFFICIENT_STOCK «Only 3 available»` | **FAIL** | BUG-003 |
| P-04 | POS | دو Checkout همزمان یک Batch | شماره‌های یکتا؛ هر دو معتبر | فاکتور دوم: `UNIQUE constraint failed: invoices.invoice_number` → 500 خام | **FAIL** | BUG-004/005/020 |
| P-05 | Resolver | منبع خارجی روی پورت بسته | خطای اتصال گزارش شود | `origin=none` بدون خطا — خطا بلعیده شد | FAIL | BUG-009 |
| P-06 | Resolver | نتایج external بعد از بستن session | ردیفها ذخیره شده باشند | `rows persisted: 0` (بدون commit → rollback) | **FAIL** | BUG-006 |
| P-07 | Settings | کلید محرمانه `sms.password` در GET | مقدار ماسک شود | plaintext کامل برگشت؛ `is_secret` در PUT به‌روز نشد | **FAIL** | BUG-010 |
| P-08 | SMS | ارسال پیام | تحویل یا خطای provider | رکورد PENDING؛ هیچ Workerی در کد نیست (grep تأیید) | **FAIL** | BUG-015 |
| P-09 | Hardware | چاپ با پرینتر CONNECTED بدون درایور | وضعیت صادقانه | `ok=True, print_status=SUCCESS` بدون هیچ چاپی | **FAIL** | BUG-016 |
| P-10 | Auth | ۱۰ لاگین غلط متوالی | 429/قفل | فقط 401×10 | FAIL | BUG-011 |
| P-11 | Auth | `POST /api/auth/logout` | اندپوینت وجود دارد | 405 (وجود ندارد) | FAIL | BUG-011 |
| P-12 | RBAC | Cashier → GET /settings، POST /inventory/adjust | 403 | 403 / 403 ✔ | **PASS** | — |
| P-13 | RBAC | Cashier → GET /reports/dashboard | 403 (داشبورد مدیریتی) | **200** — سود و ارزش انبار نمایان | FAIL | BUG-021 |
| P-14 | Pricing | `price_freshness(utcnow, now=tz-aware)` | بدون Exception | `TypeError: can't subtract offset-naive and offset-aware datetimes` | FAIL | BUG-022 |
| P-15 | DB | اجرای برنامه سپس `alembic upgrade head` | مهاجرت تمیز | `sqlite3.OperationalError: table brands already exists` | **FAIL** | BUG-014 |
| P-16 | Infra | بوت uvicorn: /health، /، /docs، 401 API | همه سالم | `{"status":"ok"…}`، 200، 200، 401 ✔ | **PASS** | — |
| P-17 | Seed | `python -m scripts.seed_demo` | داده نمونه | «Seeded 5 demo products» ✔ | **PASS** | — |

**نتیجه کلی:** ۳ PASS از ۱۷ — زیرسیستم‌های پایه سالم‌اند اما ۱۴ سناریوی عملیاتی حیاتی شکست خوردند.

---

## ۳. تست‌های رگرسیون فاز Audit

فایل `backend/tests/test_audit_regressions.py` اضافه شد: ۶ تست `xfail(strict=True)` که رفتار **صحیح** مورد انتظار را assert می‌کنند و فعلاً fail هستند (باگ‌ها هنوز Fix نشده‌اند):

```
$ python -m pytest tests/ -q   # پس از این فاز
21 passed, 6 xfailed
```

| Test ID | باگ | رفتار صحیح مورد انتظار |
|---|---|---|
| REG-001 | BUG-001 | Total با تخفیف = gross−discount؛ پرداخت صحیح پذیرفته شود |
| REG-002 | BUG-002 | مرجوعی تجمعی > مقدار خرید → خطای `RETURN_EXCEEDS` |
| REG-003 | BUG-003 | خرید 7 از A=3,B=10 → دو InvoiceItem (3+4) با قیمت هر Batch |
| REG-004 | BUG-006 | نتایج resolver خارجی پس از فراخوانی API ذخیره شوند |
| REG-005 | BUG-010 | کلید محرمانه در GET ماسک شود |
| REG-006 | BUG-022 | price_freshness با now آگاه از timezone کار کند |

پس از هر Fix، علامت `xfail` برداشته می‌شود و اگر تست هنوز fail باشد، Fix ناقص است (الزام §65).

---

## ۵. فاز ۰ — تثبیت P0 (2026-09-04، همان روز)

### تغییرات اعمال‌شده
| مورد | توضیح |
|---|---|
| `services/pos.py` | بازنویسی: محاسبات تخفیف/مالیات تک‌بار، موتور `allocate()` چند-Batch، کاهش اتمیک موجودی، شماره‌گذاری اتمیک با جدول `counters`، سقف تجمعی مرجوعی، وضعیت‌های REFUNDED صحیح |
| `services/catalog.py` | ADR-001: ارث قیمت فروش از PriceVersion فعال + seed تاریخچه از اولین Batch |
| `routers/settings.py` + `bootstrap.py` | ماسک secretها، سنتینل `__KEEP__`، به‌روزرسانی `is_secret`، پیش‌فرض‌های محرمانه |
| `main.py` | Exception Handler سراسری + Error-ID + پیام کاربرپسند فارسی + Security Headers (CSP/XFO/nosniff) |
| `database.py` + مهاجرت `c2f10a9b3e01` | تک‌مسیر کردن Alembic (stamp/upgrade در startup) |
| `routers/pos.py` | پذیرش `discount` در خطوط سبد + خروجی discount در آیتم فاکتور |
| `services/pricing.py` | price_freshness مقاوم به timezone |

### نتیجه تست فاز ۰
```
$ python -m pytest tests/ -q
34 passed, 1 xfailed  (1 xfail = REG-004 مربوط به فاز ۱ Resolver)
```
| سناریوی پذیرش جدید | نتیجه |
|---|---|
| تخفیف + مالیات ۱۰٪ (gross 3000 − 500 → tax 250 → total 2750) | **PASS** |
| مرجوعی دوم فراتر از خرید → `RETURN_EXCEEDS_PURCHASE`، موجودی سالم، وضعیت REFUNDED | **PASS** |
| تخصیص خودکار 7 از (A=3, B=10) → دو آیتم 3+4 با سود واقعی هر Batch (70) | **PASS** |
| انتخاب Batch صریح split نمی‌شود (اصل §17) | **PASS** |
| دو ترمینال همزمان روی Batch 5تایی → دقیقاً یک فروش موفق، موجودی 0 (بدون oversell) | **PASS** |
| شماره فاکتورها پیوسته و یکتا | **PASS** |
| Batch جدید قیمت را از PriceVersion فعال ارث می‌برد؛ Batch قدیم قیمت خودش را نگه می‌دارد | **PASS** |
| secret در GET ماسک، سنتینل مقدار ذخیره‌شده را خراب نمی‌کند | **PASS** |
| خطای شبیه‌سازی‌شده → 500 با code/message/error_id و بدون نشت متن exception | **PASS** |
| `alembic upgrade head` بعد از بوت برنامه → no-op موفق در head (قبلاً crash) | **PASS** |
| هدرهای امنیتی (CSP, X-Frame-Options, nosniff, Referrer-Policy) | **PASS** |

---

## ۷. فاز ۱ — Barcode Resolver واقعی (2026-09-04)

### معماری پیاده‌شده
- `services/barcode.py`: اعتبارسنجی checksum (GTIN-13/EAN-8/UPC-A/GTIN-14) — بارکد خراب قبل از هر lookup خارجی رد می‌شود.
- `services/providers/`: معماری Provider (BaseProvider + Registry) — هسته به هیچ vendor خاصی وابسته نیست (§11). Providerها: `openfoodfacts` (رایگان/بدون کلید) و `custom_http` (قالب URL + نگاشت فیلد JSON قابل‌پیکربندی — برای GS1-سازگار/ایرانی/داخلی).
- `services/resolvers.py`: خط‌لوله کامل §9: validate → local → cache → چند منبع خارجی → نرمال‌سازی → merge + تشخیص تعارض → confidence (HIGH توافق ۲+ منبع / MEDIUM تک‌منبع / LOW تعارض) → ذخیره PENDING → مرور انسانی → apply.
- CRUD منابع (`/barcode/sources`) + جریان review/apply + Image Resolver با Validation واقعی دانلود/امضا/حجم + Price Resolver چندمنبعی.

### ۱۳ سناریوی الزامی §10 (همه با httpx.MockTransport — قطعی و آفلاین)

| # | سناریو | نتیجه |
|---|---|---|
| 1 | بارکد موجود در Local DB | PASS — origin=local بدون تماس خارجی |
| 2 | فقط Source A دارد | PASS — MEDIUM |
| 3 | فقط Source B دارد | PASS |
| 4 | هر دو منبع دارند (توافق) | PASS — confidence=HIGH، بدون تعارض |
| 5 | اطلاعات متناقض | PASS — conflict=True، confidence=LOW، الزام مرور انسانی |
| 6 | بدون تصویر | PASS — valid_count=0، best=None |
| 7 | تصویر خراب (404 / غیرتصویر با حجم سالم) | PASS — HTTP_404 / NOT_AN_IMAGE؛ تصویر سالم JPEG: PASS |
| 8 | بارکد ناشناخته | PASS — origin=none + NOT_FOUND per-source؛ checksum نامعتبر: origin=invalid |
| 9 | Timeout خارجی | PASS — error.kind=TIMEOUT، بدون fake success |
| 10 | API قطع | PASS — UNREACHABLE |
| 11 | پاسخ نامعتبر (HTML) | PASS — INVALID_RESPONSE |
| 12 | Rate Limit | PASS — RATE_LIMITED |
| 13 | کالای تکراری | PASS — local برنده می‌شود؛ apply روی بارکد تکراری 409 |

+ تست‌های تکمیلی: CRUD منابع (کد Provider ناشناس → 400)، ذخیره‌سازی نتایج در سطح endpoint، جریان کامل review→apply→cache-hit، قیمت بازار دو منبعی (aggregate).

### تست زنده (Live) — اعلام صادقانه
از این محیط، خروجی HTTPS به `world.openfoodfacts.org` (و هر host عمومی دیگر) **امکان‌پذیر نبود** (TLS EOF / certificate intercept). بنابراین:
- Provider OpenFoodFacts: IMPLEMENTED + MOCK-TESTED — **تست زنده انجام‌نشده** (نیازمند محیط با اینترنت باز؛ سناریوی تست در `BARCODE_RESOLVER.md` فاز مستندسازی مستند می‌شود).
- ادعایی مبنی بر «کار می‌کند با منبع واقعی» ثبت نشده است.

```
$ python -m pytest tests/ -q
52 passed  (بدون هیچ xfail باقی‌مانده از فاز Audit)
```

---

## ۸. فاز ۲ — Stocktaking کامل + امنیت + Backup/Restore (2026-09-04)

### چرخه کامل انبارگردانی (§19-20)
```
DRAFT → IN_PROGRESS (اولین شمارش) → PENDING_APPROVAL (پایان شمارش)
      → ADJUSTED (تأیید مدیر با مجوز inventory.approve_stocktake)
```
- هر شمارش **بلافاصله ذخیره و Audit می‌شود** (STOCKTAKE_COUNTED) → Resume دقیق بعد از بستن برنامه (progress + next_item_id).
- **هیچ تغییری قبل از تأیید مدیر اعمال نمی‌شود**؛ انباردار (Inventory Operator) اجازه Approve ندارد (403 تست‌شده).
- Batchهای «صفرِ سیستمی» هم شمرده می‌شوند → کشف موجودی گم‌شده ممکن شد (اختلاف مثبت تست‌شده).
- گزارش اختلافات با ارزش ریالی (§34).

### امنیت
| سناریو | نتیجه |
|---|---|
| ۶ ورود غلط → قفل موقت با 429 | PASS |
| ورودهای ناموفق در Audit (USER_LOGIN_FAILED) | PASS |
| Logout → توکن بلافاصله باطل (401 بعد از خروج) | PASS |
| /auth/me اکنون permissions برمی‌گرداند → منوی نقش‌محور | PASS |
| XSS: escaper روی سنک‌های Receipt/مودال‌ها + حذف prefill ادمین | PASS (کد) |
| محدودیت: blocklist توکن in-memory است (تک‌پردازشه) — برای سرور چندترمینال جدول دائمی لازم است | مستند |

### Backup/Restore
| سناریو | نتیجه |
|---|---|
| Backup آنلاین → فروش → Restore → موجودی به نقطه Backup بازگشت | PASS |
| فایل خراب/غیرSQLite → 400 بدون دست زدن به دیتابیس | PASS |
| بکاپ ایمنی خودکار قبل از Restore + Audit | PASS |
| چرخش نسخه‌ها (backup.keep) | PASS |

```
$ python -m pytest tests/ -q
61 passed  (بدون xfail)
```

---

## ۹. فاز ۳ — POS تجاری + Kiosk + SMS واقعی + صداقت سخت‌افزار (2026-09-04)

### POS اختصاصی (§6-7)
- رابط تمام‌صفحه صندوق: هدر فروشگاه/صندوق‌دار/ساعت، ورودی بارکد همیشه‌متمرکز، جدول سبد، جمع‌ها، دکمه‌های لمسی بزرگ (پرداخت/تخفیف/مشتری/خالی).
- Keyboard-first: Enter افزودن · F2 پرداخت (با محاسبه باقی‌مانده پول) · F4 تخفیف (خطی یا کل سبد با تقسیم متناسب) · F8 مشتری · Del حذف آخرین · Esc خالی.
- انتخاب قیمت قدیم/جدید (§16) با پیشنهاد سیستمی + انتخاب صندوق‌دار؛ سود/قیمت خرید فقط با مجوز `pricing.view_cost` نمایش داده می‌شود (§45).
- **Kiosk/Lock (§7):** میان‌بر قابل‌تنظیم (پیش‌فرض Ctrl+Shift+L)، تمام‌صفحه، مخفی‌سازی منو، خروج فقط با احراز کاربر دارای `settings.manage` (اندپوینت `/pos/kiosk/unlock` — تست: رمز غلط 401، صندوق‌دار 403، ادمین OK + Audit هر سه حالت).
- محدودیت صادقانه: ماندگاری Kiosk در سطح OS (بدون مرورگر/کاربر) به ابزار ویندوز نیاز دارد — در HARDWARE_SETUP.md فاز مستندسازی ثبت می‌شود.

### SMS (BUG-015)
| سناریو | نتیجه |
|---|---|
| Provider «file» → ارسال → dispatch → SENT + نوشتن در فایل | PASS |
| بدون Provider → پیام صادقانه PENDING می‌ماند (بدون fake SENT) | PASS |
| Provider همیشه‌شکست → RETRYING با error_message → FAILED پس از max_retries | PASS |
| Worker پس‌زمینه در lifespan (thread + interval قابل تنظیم) | IMPLEMENTED (همان مسیر کد dispatch تست‌شده؛ تیک خودکار زمان‌بند است) |
| melipayamak / kavenegar واقعی | **UNTESTED-LIVE** — خروجی HTTPS از sandbox ممکن نیست؛ adapter پیاده و mock-تست نشده چون fake هم نداریم؛ نیازمند تست با پنل واقعی |

### چاپ (BUG-016)
| سناریو | نتیجه |
|---|---|
| پرینتر CONNECTED بدون درایور → `ok=False, print_status=FAILED, NOT_SUPPORTED` + فروش PAID دست‌نخورده | PASS |
| پرینتر file:// → SUCCESS واقعی (فایل رسید نوشته شد) | PASS |
| پرینتر escpos: بدون پکیج python-escpos → DRIVER_UNAVAILABLE صادقانه | PASS |
| چند پرینتر ثبت‌شده → انتخاب آخرین پرینتر فعال (فیکس MultipleResultsFound) | PASS |
| چاپ روی پرینتر حرارتی فیزیکی | **UNTESTED** — سخت‌افزار موجود نیست |

```
$ python -m pytest tests/ -q
69 passed
```

---

## ۱۰. فاز ۴ — موبایل PWA (2026-09-04)

- پوسته PWA (manifest + service worker + آیکون‌ها) سرو می‌شود؛ سیاست SW: **کش فقط برای پوسته؛ `/api` هرگز کش/جعل نمی‌شود** (تست source-level).
- اپ انبارگردانی موبایل: جلسات + ادامه دقیق، شمارش §24 با ذخیره فوری، اسکن دوربین (BarcodeDetector) با checksum سمت کلاینت، صف آفلاین IndexedDB + Sync + تعارض انسانی.
- تست‌های API مرتبط (۸ عدد): سرو شدن `/mobile/`، manifest/sw/icon، اطلاعات کالا در آیتم‌ها، `item-by-barcode` (یافته/PRODUCT_NOT_FOUND/ITEM_NOT_IN_SESSION)، جریان کامل شمارش موبایل، ردّ Replay پس از بستن جلسه (= تعارض انسانی). همه PASS.
- **UNTESTED (صادقانه):** دوربین روی گوشی واقعی، نصب Add to Home Screen، رفتار واقعی IndexedDB در مرورگر موبایل — در sandbox دستگاه موبایل/دوربین موجود نیست. منطق سمت سرور همان مسیرهای تست‌شده است.

## ۱۱. فاز ۵ — گزارش‌های کامل + Design System (2026-09-04)

| گزارش جدید (§49) | نتیجه |
|---|---|
| فروش روزانه (group=daily) و به تفکیک کالا (group=product) | PASS (با سناریوی اقتصادی شناخته‌شده: 4800 فروش/2300 سود) |
| گزارش صندوق‌دار (تخفیف/سود به ازای کاربر) | PASS |
| ارزش موجودی به بهای تمام‌شده | PASS |
| تاریخچه بهای خرید (نوسان قیمت) | PASS (+نیازمند pricing.view_cost) |
| گزارش کامل انقضا | PASS |
| اصلاحات/ضایعات/انبارگردانی با نام کاربر و علت | PASS |
| داشبورد — بازنویسی با SQL تجمعی (بدون بارگذاری کل جداول) | PASS (دلتای فروش/سود/ارزش دقیقاً برابر فعالیت شناخته‌شده) |
| صفحه‌بندی کالاها با COUNT واقعی | PASS |

- گزارش‌ها مبتنی بر delta تست شدند تا با فعالیت سایر ماژول‌های تست در همان روز تداخل نکنند.
- Design System مستند شد (`docs/DESIGN_SYSTEM.md`) و صفحه گزارش‌ها با تب‌های نقش‌محور بازطراحی شد.
- پاکسازی BUG-022 (کد مرده/`__import__`/COUNT) انجام شد.

```
$ python -m pytest tests/ -q
88 passed
```

---

## ۶. تست‌های ناممکن در این محیط (اعلام صادقانه)

| مورد | وضعیت |
|---|---|
| پرینتر حرارتی واقعی (ESC/POS، برش، پهنای کاغذ) | **تست‌نشده** — سخت‌افزار موجود نیست |
| کشوی پول واقعی | **تست‌نشده** |
| اسکنر بارکد فیزیکی USB/بلوتوث | **تست‌نشده** (فقط منطق timing داخلی تست‌پذیر است) |
| نصب‌کننده Windows (Setup.exe) روی ویندوز | **تست‌نشده** — محیط Linux |
| دوربین موبایل / APK | **تست‌نشده** — موبایل اصلاً پیاده نشده |
| Providerهای واقعی بارکد (GS1، ایرانی) | **تست‌نشده** — هیچ Provider قابل پیکربندی وجود ندارد (BUG-008) |

## ۱۲. فاز ۶ — Installer + رندر واقعی UI (2026-09-04)

### ۱۲.۱ رندر واقعی UI برای اسکرین‌شات (بدون X/GPU/fontconfig)

| بررسی | نتیجه |
|---|---|
| تولید stub-libs از خود کتابخانه‌های PySide6 (`scripts/make_qt_stublibs.py`: objdump verneed+UND → version-script + soname درست) | PASS — import WebEngine و رندر کامل با 20 stub |
| WebEngine offscreen: بارگذاری صفحه واقعی، متن فارسی DOM (title/innerText) | PASS |
| 21 اسکرین‌شات PNG از همه بخش‌ها + 2 PDF (`scripts/shoot.py` + `scripts/shots.json`) | PASS — همه با بررسی «not-blank» (شمار رنگ ≥ 150) |
| درون‌مایه تصاویر = صفحات واقعی: dashboard/reports/inventory/pos متن واقعی فارسی را نشان می‌دهند (استخراج DOM) | PASS |
| PDF نهایی `docs/SCREENSHOTS.pdf` (23 صفحه، 21 تصوور، فونت Vazirmatn embed) | PASS |

### ۱۲.۲ Frozen app (بیلد cx_Freeze لینوکس — تست‌پذیرترین مسیر installer)

| بررسی | نتیجه |
|---|---|
| بوت exe در HOME جدا (`/tmp/fz-home`)، پورت تصادفی | PASS — /health=200 در ~3s |
| ورود admin + JWT | PASS |
| سرو `/`، `/mobile/`، manifest (frontend باندل‌شده) | PASS (200) |
| API واقعی روی DB تازه | PASS (`/api/products` → JSON خالی درست) |
| دیتای کاربر: `supermarket.db` (29 جدول) + `logs/` + `secret.key` | PASS |
| ری‌استارت دوم: health/ورود OK و `secret.key` ثابت | PASS (توکن‌ها پایدار) |
| همان لانچر در حالت dev (غیر frozen) | PASS |
| رفع ریشه‌ای: باندل صریح `sqlalchemy.dialects.sqlite` (entry-point در frozen) | PASS (بدون آن NoSuchModuleError) |

### ۱۲.۳ UNTESTED (اعلام صادقانه)

- بیلد PyInstaller ویندوزی (`installer/windows/app.spec`)، `build.ps1`، Setup.exe
  ساخته Inno Setup، امضای دیجیتال/SmartScreen — sandbox لینوکسی است؛
  syntax و منطق بررسی شده ولی اجرا نشده‌اند.
- رندر فارسی روی ویندوز (فونت سیستم) — در لینوکس با Vazirmatn تست شد.

### ۱۲.۴ Regression

```
$ python -m pytest tests/ -q
88 passed
```
