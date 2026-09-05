# DEVELOPMENT PLAN — نقشه راه تبدیل به محصول تجاری

**تاریخ:** 2026-09-04 · **مبنا:** `SYSTEM_AUDIT.md` + `BUG_REPORT.md` + Master Prompt (§66، §69)

> قاعده حاکم: هر قابلیت فقط پس از «Implemented + Integrated + Tested + Verified + Documented» تکمیل‌شده اعلام می‌شود. هر فاز با تست رگرسیون تمام فازهای قبل همراه است.

---

## فاز ۰ — تثبیت (Stabilization) «P0»
**هدف:** یکپارچگی داده و صحت مالی — بدون این فاز، هر قابلیت دیگری بی‌معناست.

| # | اقدام | باگها | خروجی پذیرش |
|---|---|---|---|
| 0.1 | بازنویسی محاسبات Checkout (gross/discount/tax/total) + پذیرش discount در API | BUG-001 | REG-001 سبز؛ تست مالی جدید |
| 0.2 | کنترل سقف مرجوعی تجمعی + وضعیت صحیح REFUNDED | BUG-002, 019 | REG-002 سبز |
| 0.3 | موتور Allocation چند-Batch (تخصیص حسابداری، نه واقعیت فیزیکی — §17) | BUG-003 | REG-003 سبز + تست §37 |
| 0.4 | شماره فاکتور اتمیک + کاهش موجودی اتمیک (`UPDATE … WHERE qty≥n`) | BUG-004, 005 | تست همزمانی سبز |
| 0.5 | اتصال PriceVersion به فروش (تصمیم معماری A/B مستند در ADR-001) | BUG-017 | تاریخچه قیمت واقعی |
| 0.6 | Exception Handler سراسری + Error-ID + پیام کاربرپسند | BUG-020 | هیچ 500 خامی در تست‌ها |
| 0.7 | ماسک Settings محرمانه + write-only | BUG-010 | REG-005 سبز |
| 0.8 | تک‌مسیر کردن Alembic (حذف create_all از lifespan) | BUG-014 | مهاجرت تمیز پس از بوت |

## فاز ۱ — Resolver واقعی «P1»
- معماری **Provider Interface** قابل‌افزودن (§11): `Provider` protocol + Registry؛ Providerها: OpenFoodFacts (جهانی/رایگان)، GS1-style، Provider ایرانی (نیازمند انتخاب کاربر — ABD)، Local DB.
- CRUD منابع + اولویت/فعال/غیرفعال از API/UI (BUG-008)؛ نتایج با source/timestamp/confidence ذخیره و commit شوند (BUG-006/007)؛ گزارش خطای per-provider (BUG-009).
- جریان کامل §9: Local → Cache → External(چندمنبع) → Normalization → Validation → Confidence → AutoFill → **Human Review UI** → Save.
- اعتبارسنجی بارکد (checksum GTIN-13/EAN-8/EAN-13/UPC-A) قبل از هر lookup.
- Image Resolver: چندمنبعی + Validation (دانلود واقعی، بررسی فرمت/حداقل ابعاد/خرابی) (§13).
- Price Resolver: منابع بازار + Freshness + پیشنهاد Accept/Edit/Reject (§15).
- تست‌های §10 و §40 با Providerهای mock (13 سناریو) + تست واقعی شبکه برای Providerهای عمومی؛ نتیجه در TEST_REPORT.

## فاز ۲ — Stocktaking کامل + امنیت «P1»
- چرخه کامل §19: DRAFT→IN_PROGRESS→(شمارش با ذخیره فوری)→COMPLETED→**APPROVAL**→ADJUSTED؛ پیشرفت/remaining/resume (§20)؛ شامل Batchهای صفر؛ ثبت شمارنده هر آیتم.
- امنیت: Rate-limit لاگین + قفل حساب، Logout+Audit، Audit لاگین ناموفق، حذف رمز پیش‌فرض (اولین‌بار wizard)، XSS fix (escape همه سنک‌ها + CSP)، Security headers، بازطراحی نقش Cashier (BUG-011/012/013/021).
- Restore از Backup + Backup خودکار زمان‌بندی‌شده + تست واقعی Restore (§59).

## فاز ۳ — POS تجاری + Kiosk «P1»
- POS اختصاصی تمام‌صفحه طبق §6 (Keyboard-first، بردار بزرگ، دکمه‌های لمسی، تخفیف، مشتری، برگشت، ابطال با مجوز، انتخاب Batch/قیمت قدیم).
- **Kiosk/Lock Mode (§7):** شورت‌کات قابل‌تنظیم، مخفی‌سازی navigation، Fullscreen API، خروج فقط با احراز مدیر — صادقانه مستند می‌شود که ماندگاری OS-level kiosk به مرورگر/ویندوز بستگی دارد و در نسخه Desktop (PyWebview/Edge kiosk) قوی‌تر اعمال می‌شود.
- Hardware صادق: درایور ESC/POS واقعی (python-escpos روی ویندوز) یا وضعیت NOT_SUPPORTED؛ drawer pulse از طریق پرینتر (BUG-016)؛ UI تنظیمات سخت‌افزار.
- SMS واقعی: Adapter ملی‌پیامک/کاوه‌نگار + Worker با retry (BUG-015).

## فاز ۴ — موبایل «P1/P2» (نیازمند تصمیم ADR-002)
- گزینه A: **PWA** (یک کدبیس، دوربین با BarcodeDetector API، Offline با IndexedDB+Service Worker، نصب روی اندروید) — پیشنهاد اولیه به‌دلیل تک‌repos و تک‌backend.
- گزینه B: Android Native (Kotlin) — هزینه بیشتر، دسترسی سخت‌افزار بهتر.
- در هر حالت: Mobile Stocktaking UI (§24)، ذخیره فوری هر شمارش، صف آفلاین + Sync + Conflict detection (§25) — تا وقتی پیاده و تست نشود، ادعای Offline نمی‌کنیم.

## فاز ۵ — گزارش‌ها، UI/UX و Design System «P2»
- Design System واحد (§47) + بازطراحی نقش‌محور (§5)؛ گزارش‌های §49 (مغایرت ریالی، تاریخچه خرید، صندوق‌دار، قیمت)؛ Dashboard بهینه با SQL تجمعی؛ پاجینیشن واقعی.

## فاز ۶ — استقرار و مستندسازی نهایی
- Installer ویندوز: build واقعی روی ویندوز + نصب و تست روی VM ویندوز (خروجی: Setup.exe تست‌شده یا اعلام صادقانه تست‌نشده).
- معماری Server (ADR-003): تک‌فروشنده = Local/LAN اولیه؛ چندترمینال = PostgreSQL + سرور مرکزی — مقایسه §29 در سند DEPLOYMENT.
- CI (GitHub Actions: lint+test+ruff)، ساختار §62، مستندات §68 (14 سند + PDF نهایی با اسکرین‌شات واقعی از سیستم اجراشده) و GitHub Release.

---

## تصمیمات معماری باز (ADR) — نیازمند تأیید شما

| ID | موضوع | گزینه‌ها | پیشنهاد اولیه |
|---|---|---|---|
| ADR-001 | منبع حقیقت قیمت فروش | A) PriceVersion محور و Batch از آن ارث می‌برد · B) Batch محور و PriceVersion فقط ثبت تاریخچه | A — با backward-sync به Batchهای فعال |
| ADR-002 | معماری موبایل | A) PWA · B) Android Native · C) Flutter | A (PWA) — تک‌کدبیس، offline بومی وب |
| ADR-003 | استقرار سرور | A) تک‌ماشینه SQLite · B) LAN + سرور محلی · C) Cloud/VPS | A برای v1 تک‌صندوق → مسیر مهاجرت به B/C با PostgreSQL |
| ADR-004 | Provider خارجی بارکد | OpenFoodFacts (رایگان) · GS1 · ایرانی (نیازمند API key) | OpenFoodFacts به‌عنوان پیش‌فرض تست‌پذیر + پشتیبانی افزونه ایرانی |
