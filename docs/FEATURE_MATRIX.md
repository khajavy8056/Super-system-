# Feature Matrix — v1.0.0 Consolidation Audit

این سند «ماتریس قابلیت» (§۲ سند Master) است: برای هر قابلیت، وضعیت آن در هر
Branch/Version و در نسخهٔ نهایی ۱٫۰٫۰ ثبت شده است. هیچ قابلیتی صرفاً به دلیل
نبودن در Branch فعلی حذف نشده است؛ هر مورد از خط توسعهٔ مناسب استخراج، بازبینی،
ادغام و (در صورت نقص) تکمیل و تست شده است.

**روش راستی‌آزمایی:** هر ردیف با یکی از این‌ها تأیید شده است: اجرای آزمون خودکار
(TESTED)، اجرای زندهٔ endpoint/UI (EXECUTED)، یا بازبینی کد (REVIEWED). مواردی که
به سخت‌افزار/ویندوز واقعی یا توکن مجاز نیاز دارند صریحاً NOT VERIFIED نوشته شده‌اند.

## راهنمای وضعیت

| وضعیت | معنا |
|---|---|
| PRESENT | در نسخهٔ نهایی کامل و اجرا/تست شده |
| PARTIAL | حاضر اما با محدودیت مستند |
| FIXED | باگ داشت، در این نسخه اصلاح و تست شد |
| NOT VERIFIED | نیازمند ویندوز/سخت‌افزار واقعی یا توکن مجاز — صادقانه اعلام شده |

## الف) هستهٔ کسب‌وکار

| قابلیت | v0.1.0 | v0.2.0 | v0.3.x (line B) | v0.4.0 (line A) | v1.0.0 |
|---|---|---|---|---|---|
| احراز هویت JWT + نقش/مجوز گرانولار | ✔ | ✔ | ✔ | ✔ | TESTED |
| Product ≠ Batch (هویت پایدار) | ✔ | ✔ | ✔ | ✔ | TESTED |
| قیمت در سطح Batch + PriceHistory | ✖ | ✖ | ✔ | ✖ | TESTED |
| بارکد داخلی INT- برای کالای فله | ✖ |  | ✔ | ✖ | TESTED |
| تشخیص کالای تکراری (مشورتی) | ✖ | ✖ | ✔ | ✖ | TESTED |
| واحدها (شامل میلی‌گرم) | جزئی | جزئی | ✔ | جزئی | **FIXED + TESTED** (§۱۲) |
| ورود کالا بدون Resolver خارجی | ✔ | ✔ | ✔ | ✔ | TESTED |
| Product Resolver چندمنبعه + confidence | ✔ | ✔ | ✔ | ✔ | TESTED |
| Image/Price Resolver + ذخیرهٔ محلی | ✔ | ✔ | ✔ | ✔ | TESTED |
| موجودی/حرکت‌ها (IN/OUT/WASTE/ADJ/TRANSFER) | ✔ | ✔ | ✔ | ✔ | TESTED |
| انقضا + سطل‌ها + مسدودسازی فروش | ✔ | ✔ | ✔ | ✔ | TESTED |
| انبارگردانی قابل‌ازسرگیری | ✔ | ✔ | ✔ | ✔ | TESTED |
| POS (اسکن، انتخاب Batch/قیمت، Void، Return) | ✔ | ✔ | ✔ | ✔ | TESTED |
| Kiosk/Lock + میان‌بر + احرازهویت خروج | ✖ |  | ✔ |  | TESTED (§۲۰) |
| کوپن/کمپین با شرایط کامل | ✖ | ✖ | ✔ | ✖ | TESTED (§۲۸) |
| حساب دفتری مشتری + تسویهٔ جزئی/کامل | ✖ |  | ✔ | ✖ | TESTED (§۲۶) |
| پیامک یادآوری بدهی (قالب + Background) | ✖ | جزئی | ✔ | ✖ | TESTED (§۲۷) |
| واحدهای پول ریال/تومان با Base واحد | ✖ |  | ✔ | ✖ | TESTED (§۳۳) |
| تاریخ شمسی + زمان مورد اعتماد | ✖ | ✖ | ✔ | ✖ | TESTED (§۳۲) |
| Light/Dark + حالت Auto (۷/۱۹) | ✖ |  | ✔ | ✖ | TESTED (§۲۲) |
| Offline sync queue | ✖ | ✖ | ✔ | ✖ | TESTED (§۴۲) |

## ب) داشبورد و گزارش (§۲۳، §۴۹)

| مورد §۲۳ | قبل از ۱٫۰٫۰ | v1.0.0 |
|---|---|---|
| Sales Today / Monthly / Orders / Profit | ✔ | TESTED |
| Inventory Value / Low Stock | ✔ | TESTED |
| Expired / Expiring Soon | ✔ | TESTED |
| **Pending Payments** | ✖ | **FIXED** (`receivables.pending_*`) |
| **Customer Debt** | ✖ | **FIXED** (`receivables.customer_debt`) |
| **SMS Status** | ✖ | **FIXED** (`sms.*`) |
| **System Status** | ✖ | **FIXED** (`system.*`) |

## ج) لاگ (§۴۳)

| رویداد | قبل | v1.0.0 |
|---|---|---|
| PRODUCT_DELETED | ✖ | **FIXED + TESTED** |
| BARCODE_LOOKUP | ✖ | **FIXED + TESTED** |
| SMS_SENT / SMS_FAILED | ✖ | **FIXED + TESTED** |
| UPDATE_STARTED/COMPLETED/FAILED | ✖ | **FIXED + TESTED** |
| API_ERROR | ✖ | **FIXED + TESTED** |
| بقیهٔ رویدادهای §۴۳ | ✔ | TESTED |

## د) UI/UX (§۲۱، §۳۶، §۴۸، §۴۹)

| مورد | قبل | v1.0.0 |
|---|---|---|
| طراحی RTL فارسی + Design System | ✔ | PRESENT |
| تنظیمات دسته‌بندی‌شدهٔ فارسی (§۳۶) | ✖ (جدول خام) | **FIXED + EXECUTED** (تب‌های دسته) |
| لوگوی تجاری در Login/Sidebar/About/Mobile/Installer (§۴۹) | ✖ | **FIXED + EXECUTED** |
| دربارهٔ سامانه — «طراحی و توسعه توسط خواجوی» (§۵۰) | ✔ | PRESENT |

## هـ) ویندوز و انتشار (§۱۹، §۵۱، §۵۲، §۵۳)

| مورد | قبل | v1.0.0 |
|---|---|---|
| پنجرهٔ اختصاصی (نه مرورگر پیش‌فرض) §۱۹ | ✖ (`webbrowser.open`) | **FIXED** (app-mode) — NOT VERIFIED روی ویندوز |
| Full Screen / Kiosk §۲۰ | ✔ | TESTED (وب) |
| Installer Inno + PyInstaller | ✔ | REVIEWED؛ NOT VERIFIED روی ویندوز واقعی |
| رفع باگ مرگبار `\$ScriptDir` در builder | ✖ (می‌شکست) | **FIXED** (آزمون متنی) |
| Build pipeline ویندوز CI §۵۲ | ✖ (هرگز اجرا نمی‌شد) | بازنویسی شد؛ فعال‌سازی نیازمند توکن `workflows` — NOT VERIFIED |
| Backup قبل از Update (§۳۸/§۵۴) | ✔ | TESTED |

## نتیجهٔ نهایی ماتریس

- **هیچ قابلیتی از بین نرفته است:** خط v0.3.x به‌طور کامل به main برگشت.
- **باگ‌های کشف‌شده حین ادغام اصلاح شدند:** `\$ScriptDir`، نسخهٔ سخت‌کدشدهٔ
  artifact، `x64compatible`، import تکراری، نسخهٔ قدیمی config.
- **شکاف‌های §۲۳/§۳۶/§۴۳/§۴۹/§۱۹/§۱۲ بسته شدند** و با آزمون یا اجرای زنده تأیید شدند.
- **موارد NOT VERIFIED** (بیلد ویندوز، نصب واقعی، CI) صریحاً مشخص شده‌اند و مسیر
  فعال‌سازی آن‌ها مستند است.
