# SYSTEM AUDIT — گزارش کامل بررسی مخزن (فاز ۱)

**تاریخ:** 2026-09-04
**نسخه بررسی‌شده:** v0.1.0 (کامیت `ba4a4ad`)
**دامنه:** تمام ۷۸ فایل مخزن (backend/frontend/installer/docs/tests)
**روش:** مطالعه خط‌به‌خط کد + اجرای واقعی تست‌ها + ۱۷ اثبات تجربی (probe) روی سیستم اجراشده — هیچ ادعایی بدون اجرا ثبت نشده است.

> مطابق اصل «No Fake Completion»: هیچ قابلیتی صرفاً به دلیل وجود کد/UI/API، تکمیل‌شده اعلام نشده است.

---

## ۱. خلاصه اجرایی

| شاخص | مقدار |
|---|---|
| فایل‌های کد | ۵۵ فایل پایتون/JS/CSS (≈۴,۹۰۰ خط) |
| تست‌های موجود | ۲۱ عدد — همه PASS (ولی پوشش ناقص: تخفیف، مرجوعی، Race، Resolver، SMS، مجوزها پوشش داده نشده) |
| باگ تأییدشده با اثبات تجربی | **۹ باگ Critical/High** + ۱۶ Medium/Low (جزئیات: `BUG_REPORT.md`) |
| ماژول‌های کاملاً VERIFIED | ۹ از ۳۳ |
| ماژول‌های غایب (MISSING) | ۸ (موبایل، Kiosk، Sync، Restore و…) |
| ادعاهای نادرست/فوق‌العاده در مستندات | ۷ مورد (بخش ۴) |

**جمع‌بندی:** هسته داده‌ای (Product ≠ Batch، Snapshot قیمت در فاکتور، Ledger گردش موجودی، Audit) **بنیاد خوب و سالمی** دارد و تست‌پذیر است؛ اما در لایه‌های حیاتی POS (تخفیف، مرجوعی، تخصیص چند-Batch)، Resolver، سخت‌افزار، SMS، امنیت کاربردی و موبایل، سیستم **تجاری‌شدنی نیست** و بخش عمده‌ای از ادعاهای README/CHANGELOG با واقعیت کد نمی‌خواند.

---

## ۲. متدولوژی (چه چیزهایی واقعاً اجرا شد)

1. `pytest tests/ -q` → **21 passed** (محیط: Python 3.11.2، venv تازه).
2. بوت سرور با uvicorn → `/health` ✓، پنل `/` ✓، Swagger `/docs` ✓، API بدون توکن → 401 ✓.
3. `python -m scripts.seed_demo` → موفق.
4. `alembic upgrade head` روی دیتابیس تازه → موفق؛ **اما بعد از اجرای برنامه** (که `create_all` می‌زند) → خطای `table brands already exists` (BUG-014).
5. ۱۷ probe تجربی روی TestClient/سرویس‌ها (اسکریپت‌های اثبات در `TEST_REPORT.md` خلاصه شده و به‌صورت تست رگرسیون `xfail` در `backend/tests/test_audit_regressions.py` ماندگار شده‌اند).

---

## ۳. جدول اصلی Audit

وضعیت‌ها: **VERIFIED** (پیاده‌سازی + یکپارچه + تست‌شده) · **PARTIAL** (ناقص) · **STUB** (اسکلت/شبیه‌سازی) · **BROKEN** (شکسته) · **MISSING** (غایب) · **UNTESTED** (تست‌نشده)

| # | Module | Status | Problems | Severity | Required Action |
|---|---|---|---|---|---|
| 1 | **Project Structure** | PARTIAL | ساختار backend/docs تمیز؛ اما `mobile/`، `database/`، `scripts/` کامل و CI وجود ندارد | Medium | ایجاد ساختار هدف §62 + CI |
| 2 | **Database (Schema)** | PARTIAL | ۲۸ جدول (نه ۲۹ كما CHANGELOG)؛ طراحی Batch/PriceVersion/Ledger خوب؛ ولی مدیریت دوگانه schema (create_all + Alembic) ناسازگار (BUG-014)؛ بدون CHECK constraint برای qty؛ شماره فاکتور count-based | High | تک‌مسیر کردن Alembic + constraintهای واقعی |
| 3 | **Backend Architecture** | VERIFIED‑* | لایه‌بندی router→service→model تمیز و واقعی. *استثناها: Resolvers بدون معماری Provider، Pricing از POS جدا افتاده (BUG-017) | Medium | Refactor بخش‌های مشخص‌شده |
| 4 | **Authentication** | PARTIAL | JWT/bcrypt کار می‌کند (تست‌شده)؛ اما بدون Rate Limit، بدون Logout/REV، بدون قفل حساب، ورود ناموفق Audit نمی‌شود، توکن ۱۲ ساعته، `SECRET_KEY` و `admin/admin123` پیش‌فرض خودکار (BUG-011/013) | High | Hardening امنیتی |
| 5 | **Authorization (RBAC)** | PARTIAL | اجرای مجوز سمت سرور واقعی است (Cashier→403 تأیید شد)؛ اما Cashier به `reports.view` دارد و داشبورد مدیریتی کامل (سود/ارزش موجودی) را می‌بیند — نقض §45؛ API تخفیف/هزینه بدون تفکیک نقش | Medium | بازطراحی Preset نقش‌ها + فیلتر پاسخ بر اساس مجوز |
| 6 | **POS — Core Checkout** | BROKEN | تخفیف دو بار کسر می‌شود و Total غلط است (BUG-001، اثبات‌شده)؛ شماره فاکتور تحت همزمانی تصادم → 500 خام (BUG-004، اثبات‌شده) | **Critical** | بازنویسی محاسبات + شماره‌گذاری اتمیک |
| 7 | **POS — Multi-Batch Split** | BROKEN | فروش qty 7 وقتی A=3 و B=10 → رد می‌شود؛ تخصیص خودکار بین Batch وجود ندارد (BUG-003، اثبات‌شده)؛ انتخاب دستی چندخطی کار می‌کند | **Critical** | موتور تخصیص (Allocation Engine) |
| 8 | **POS — Returns/Void** | BROKEN | مرجوعی تجمعی چک نمی‌شود → موجودی قابل تورم است (BUG-002، اثبات: stock 12 به‌جای 2)؛ وضعیت فاکتور همیشه PARTIALLY_REFUNDED؛ `reference_id=0` جایگزین | **Critical** | بازنویسی Return با کنترل سقف |
| 9 | **POS — UI (وب)** | PARTIAL | POS شبیه Dashboard است نه محیط صندوق؛ بدون Kiosk، بدون تخفیف، بدون انتخاب مشتری، بدون حذف با کلید؛ leak لیسنر `click` در هر بار ورود به view | High | POS اختصاصی + Kiosk (§6‑7) |
| 10 | **Barcode Scanner (HW)** | PARTIAL | تشخیص timing-based با threshold قابل تنظیم (خوب)؛ فقط سمت سرورِ اطلاعاتی — ورودی POS فقط یک input است؛ تنظیم threshold فقط از جدول settings خام | Medium | یکپارچه‌سازی واقعی + کالیبراسیون UI |
| 11 | **Barcode Product Resolver** | BROKEN | نتایج External هرگز ذخیره نمی‌شوند (GET بدون commit → کش همیشه خالی؛ BUG-006 اثبات‌شده)؛ `need_manual=False` برای داده خارجی خلاف قاعده Human-Review (BUG-007)؛ **هیچ اندپوینتی برای CRUD منابع خارجی وجود ندارد** → سیستم عیرقابل‌بهره‌برداری (BUG-008)؛ خطاها بی‌صدا swallow می‌شوند (BUG-009) | **Critical** | معماری Provider + endpoints + جریان تأیید |
| 12 | **Image Resolver** | MISSING | فقط ذخیره URL؛ هیچ Validation (رزولوشن/فرمت/خرابی/دسترسی)، هیچ Image-Search fallback، هیچ Quality-Check | High | پیاده‌سازی §13 |
| 13 | **Price Resolver (Market)** | STUB | ساختار MarketPrice/تجمیع median هست؛ بدون هیچ منبع واقعی، بدون Freshness مؤثر (BUG-017)، غیرقابل پیکربندی از API/UI | High | اتصال به Providerها + جریان Accept/Edit/Reject |
| 14 | **FIFO/FEFO Policy** | VERIFIED‑* | مرتب‌سازی/پیشنهاد Batch طبق سیاست کار می‌کند (تست‌شده) و به‌درستی «پیشنهاد» است نه واقعیت فیزیکی؛ *فقط هنگام AUTO تک‌Batch | Medium | کامل شدن با Allocation Engine (#7) |
| 15 | **Expiry Management** | VERIFIED | سطل‌بندی + بلاک فروش منقضی تست‌شده؛ job اسکن دستی است (بدون زمان‌بند) | Low | زمان‌بند + اعلان |
| 16 | **Stock Movements (Ledger)** | VERIFIED | append-only + مرجع فاکتور/تطبیق؛ تست‌شده | — | — |
| 17 | **Inventory/Adjustment/Waste** | PARTIAL | کار می‌کند + Audit؛ ولی بدون صفحه‌بندی، `if total>0 or True` کد مرده، شمارش با `len(all)` | Medium | بهینه‌سازی + پاکسازی |
| 18 | **Stocktaking** | PARTIAL | ایجاد/شمارش/تطبیق کار می‌کند (تست‌شده)؛ اما: بدون وضعیت IN_PROGRESS/پیشرفت/Resume صریح، **بدون مرحله تأیید مدیر** (§19)، Batchهای صفر excluded → کشف موجودی صفر غیرممکن، شمارنده هر آیتم Audit نمی‌شود | High | تکمیل §19‑20 |
| 19 | **Products API** | PARTIAL | CRUD + soft-delete سالم؛ شمارش با بارگذاری کل جدول؛ اعتبارسنجی بارکد (checksum GTIN) غایب | Medium | بهینه‌سازی + validation |
| 20 | **Batch/Receiving** | VERIFIED‑* | Batch جدید + هشدار تغییر قیمت خرید + movement؛ *حذف Batch = تغییر status به BLOCKED (نام‌گذاری گمراه‌کننده) | Low | اصلاح نام/رفتار |
| 21 | **Pricing (PriceVersion)** | BROKEN | تاریخچه قیمت از POS **کاملاً جدا** است: تغییر قیمت از `/api/prices` روی فروش اثر صفر دارد؛ `receive_batch` هیچ PriceVersion نمی‌سازد → تاریخچه قیمت عملاً خالی می‌ماند (BUG-017) | **Critical** | اتصال مدل قیمت به موتور فروش |
| 22 | **Dashboard** | PARTIAL | کار می‌کند؛ O(n) روی همه Batch/Productها در حافظه (برای 10k+ کالا کند می‌شود)؛ Cashier هم همه‌چیز را می‌بیند (#5) | Medium | کوئری‌های تجمعی + کنترل دسترسی |
| 23 | **Reports** | PARTIAL | ۶ گزارش پایه؛ `group` پارامتر نادیده گرفته می‌شود؛ گزارش مغایرت ارزش ریالی، تاریخچه خرید، گزارش صندوق‌دار، قیمت‌ها غایب | Medium | تکمیل §49 |
| 24 | **SMS** | STUB | فقط صف رکورد `PENDING`؛ **هیچ Worker/Providerای وجود ندارد** → پیام همیشه برای همیشه PENDING می‌ماند (BUG-015، اثبات‌شده) | High | Provider (ملی‌پیامک…) + Worker |
| 25 | **Printer (ESC/POS)** | STUB | رندر متن رسید خوب؛ درایور واقعی ESC/POS وجود ندارد؛ روی دستگاه `CONNECTED` بدون چاپ، `print_status=SUCCESS` ثبت می‌شود → **موفقیت جعلی در داده** (BUG-016، اثبات‌شده) | High | درایور واقعی + صداقت وضعیت |
| 26 | **Cash Drawer** | STUB | «pulse sent» بدون هیچ ارسال واقعی بایت (کد صریحاً اعتراف می‌کند) | Medium | درایور ESC/POS pulse |
| 27 | **Offline Mode** | PARTIAL | تک‌ماشینه/SQLite-WAL: بله. هیچ صف آفلاین/همگام‌سازی چندکاربر/موبایلی وجود ندارد | High | معماری Sync (§25‑27) |
| 28 | **Mobile / Android** | MISSING | **صفر فایل.** نه PWA (بدون manifest/service-worker)، نه APK، نه دوربین barcode | **Critical** | تصمیم معماری + پیاده‌سازی (§21‑24) |
| 29 | **Kiosk/Lock Mode** | MISSING | هیچ ردی از fullscreen/lock/shortcut وجود ندارد | High | §7 |
| 30 | **Settings** | BROKEN | مقادیر `is_secret` به‌صورت plaintext برگردانده می‌شوند؛ فیلد `is_secret` در PUT به‌روز نمی‌شود (BUG-010، اثبات‌شده) | High | Mask + write-only secrets |
| 31 | **Logging / Error Handling** | PARTIAL | AuditLog کسب‌وکاری خوب؛ اما HTTP 500 خام (BUG-020 اثبات‌شده در race)، بدون Error-ID، بدون هندلر سراسری، بدون لاگ فنی ساخت‌یافته | High | Exception middleware + Error-ID |
| 32 | **Security (کلی)** | PARTIAL | RBAC سمت سرور ✓، bcrypt ✓؛ غایب: Rate-Limit، CSRF-نتیجه‌گیری، CSP/Security-headers، خروج از حساب، XSS ذخیره‌شده در UI (سنک‌های `innerHTML` با نام کالا — BUG-012)، رمز پیش‌فرض admin123 در bootstrap و prefilled در فرم لاگین | High | Security Audit اجرایی (§44) |
| 33 | **Backup / Restore** | PARTIAL | Backup آنلاین SQLite واقعاً کار می‌کند ✓؛ **Restore غایب**؛ زمان‌بندی خودکار غایب؛ تست Restore غایب (§59) | High | Restore + تست واقعی |
| 34 | **Tests** | PARTIAL | ۲۱ تست PASS اما پوشش حیاتی صفر است (تخفیف! مرجوعی! همزمانی! Resolver! SMS! مجوزها! Kiosk!)؛ تست‌های رگرسیون باگ‌های تأییدشده این فاز اضافه شد (`test_audit_regressions.py`، xfail) | High | افزایش پوشش به‌ازای هر Fix |
| 35 | **Windows Installer** | UNTESTED | اسکریپت PyInstaller+Inno موجود و منطقی؛ روی ویندوز واقعی هرگز build/نصب نشده (خود مستندات اذعان دارد)؛ `AppId` در setup.iss GUID معتبر نیست | Medium | Build+تست روی ویندوز واقعی |
| 36 | **Documentation** | PARTIAL | ۴ سند موجود؛ اما ۷ ادعای نادرست/بی‌اهمیت‌کننده (بخش ۴)؛ مستندات §68 (DATABASE.md, API_DOCUMENTATION.md, …) غایب | Medium | بازنویسی صادقانه پس از فازها |

---

## ۴. ادعاهای مستندات در برابر واقعیت (Claims vs Reality)

| سند | ادعا | واقعیت اثبات‌شده |
|---|---|---|
| README | «فروش ترکیبی از چند Batch» (به‌عنوان قابلیت POS) | فقط انتخاب دستی چندخطی کار می‌کند؛ تخصیص خودکار qty بزرگ‌تر از یک Batch → `422 INSUFFICIENT_STOCK` (BUG-003) |
| README | «تخفیف» در جریان فروش | API اصلاً فیلد تخفیف نمی‌پذیرد؛ و منطق داخلی آن هم Double-count دارد (BUG-001) |
| README | «Checkout تراکنشی … شکست یکی = Rollback» | درست، به‌استثنای Race شماره فاکتور که کل تراکنش دوم را با 500 می‌شکند (BUG-004) |
| README | «لایه انتزاعی پرینتر حرارتی (ESC/POS)» | هیچ بایت ESC/POS تولید نمی‌شود؛ `SUCCESS` ثبت می‌شود بی‌آنکه چاپی انجام شود (BUG-016) |
| README | «پیامک» | صف ثابت PENDING؛ هیچ ارسال‌کننده‌ای وجود ندارد (BUG-015) |
| README | «تنظیمات رمزنگاری‌شده» | تنظیمات plaintext ذخیره و plaintext برگردانده می‌شوند (BUG-010) |
| CHANGELOG | «۲۹ جدول» | ۲۸ جدول |
| docs/API.md | کدهای خطای `EXTERNAL_API_TIMEOUT`, `SMS_PROVIDER_ERROR`, `DATABASE_ERROR` | هیچ‌کدام در کد وجود ندارند |
| docs/ARCHITECTURE.md | «قیمت فروش تاریخچه دارد (PriceVersion)» | POS هرگز PriceVersion را نمی‌خواند؛ فروش فقط از `batch.sell_price` (BUG-017) |
| README | «POS بدون اینترنت کار می‌کند» | فقط برای استقرار تک‌ماشینه صادق است (که فعلاً حالت تنها است) — قابل قبول با قید صریح |

---

## ۵. اولویت‌بندی اقدامات (پس از تأیید این گزارش)

- **P0 — یکپارچگی داده و POS (بلاک‌کننده تجاری):** BUG-001، BUG-002، BUG-003، BUG-004، BUG-017، BUG-006/007/008 (Resolver)، BUG-010، BUG-020
- **P1:** Stocktaking کامل (§19-20)، SMS واقعی، درایور چاپ صادق، Kiosk Mode، امنیت (Rate-limit/Logout/XSS)، Restore، POS UI اختصاصی
- **P2:** موبایل/اندروید + Sync آفلاین، Providerهای قیمت بازار، گزارش‌های پیشرفته، Installer تست‌شده

جزئیات کامل در `DEVELOPMENT_PLAN.md` و رجیستری باگ‌ها در `BUG_REPORT.md`.
