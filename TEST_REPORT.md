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

## ۶. تست‌های ناممکن در این محیط (اعلام صادقانه)

| مورد | وضعیت |
|---|---|
| پرینتر حرارتی واقعی (ESC/POS، برش، پهنای کاغذ) | **تست‌نشده** — سخت‌افزار موجود نیست |
| کشوی پول واقعی | **تست‌نشده** |
| اسکنر بارکد فیزیکی USB/بلوتوث | **تست‌نشده** (فقط منطق timing داخلی تست‌پذیر است) |
| نصب‌کننده Windows (Setup.exe) روی ویندوز | **تست‌نشده** — محیط Linux |
| دوربین موبایل / APK | **تست‌نشده** — موبایل اصلاً پیاده نشده |
| Providerهای واقعی بارکد (GS1، ایرانی) | **تست‌نشده** — هیچ Provider قابل پیکربندی وجود ندارد (BUG-008) |
