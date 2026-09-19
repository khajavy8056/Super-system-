# AUDIT — نسخه جدید (STEP 1–5)

> روش: بررسی واقعی کد + بررسی OpenAPI سرور در حال اجرا (۱۰۲ endpoint) +
> اجرای کل تست‌ها (۱۳۴ تست موفق) — نه صرفاً جستجوی نام فایل.
> قانون §61 رعایت شده: وجود فایل/کلاس = تکمیل‌بودن نیست.

## خلاصهٔ وضعیت

| # | قابلیت (بند سند) | وضعیت | شواهد |
|---|---|---|---|
| §4 | Core: Backend/DB/Migration/Auth/Logging | ✅ WORKING | ۱۳۴ تست، ۴ migration، head `e5b21c74a903` |
| §5 | POS (اسکن، جستجو، سبد، پرداخت، Void/Refund، چاپ) | ✅ WORKING | `test_pos.py`, `returns.py`, `escpos_driver.py` |
| §6 | Inventory + Batch + Movement + Expiry | ✅ WORKING | `test_batches.py`, `test_inventory.py` |
| §7 | واحدها (KG/گرم/لیتر/عدد…) + مقدار اعشاری | ✅ WORKING | ۸ واحد seed، `validate_for_unit`, `test_phase7_units.py` |
| §8–9 | Barcode Resolver چندمنبعی + بررسی License | ✅ WORKING | `services/providers/`, `test_resolvers.py` |
| §11 | Image Resolver (دانلود و ذخیرهٔ محلی) | ✅ WORKING | `_image_dimensions`, MEDIA_DIR |
| §12 | قیمت‌ها با Source + Timestamp | ✅ WORKING | `models/pricing.py`, `PriceVersion` |
| §13 | چند Batch با قیمت‌های مستقل | ✅ WORKING | عدم ادغام، تست‌شده |
| §14 | FIFO/FEFO به‌عنوان Policy (نه ادعای فیزیکی) | ✅ WORKING | `pos.allocation_policy`=HYBRID، FEFO/FIFO/MANUAL |
| §15–16 | انبارگردانی + ذخیرهٔ Progress + Resume | ✅ WORKING | `test_phase7_stocktaking.py` |
| §17 | Mobile Stocktaking UX | ✅ WORKING | فاز ۸ |
| §18–19 | Mobile PWA — همهٔ ماژول‌ها | ✅ WORKING | فاز ۸، ۱۴ تست قرارداد |
| §20 | POS Kiosk / Fullscreen | ✅ WORKING | `enterKiosk`, `kiosk_unlock`, shortcut |
| §36–39 | Coupon / Festival Engine | ✅ WORKING | `test_phase7_coupons.py` (۱۱ تست) |
| §41 | واحد پول تومان/ریال (بدون Float) | ✅ WORKING | `MONEY` Numeric، `pos.currency` |
| §44–46 | Diagnostics واقعی + Log | ✅ WORKING | ۱۰ check واقعی، §58 honesty |
| §26 | Users/Roles/Permissions | ✅ WORKING | Permission-based، `ROLE_PRESETS` |
| §54 | امنیت LAN (hash, JWT, rate limit) | ✅ WORKING | `security.py` |
| — | — | — | — |
| **§30–35** | **حساب دفتری مشتری، بدهی، تسویه، SMS یادآوری** | ✅ **DONE** | `services/ledger.py`، ۷ endpoint، UI مودال دفتر + ستون مانده + تسویه + `POST /customers/{id}/debt-reminder` |
| **§25** | **پروفایل فروشگاه (نام/لوگو/آدرس/تلفن)** | ✅ **DONE** | ۱۰ کلید `store.*`، `GET/PUT /settings/store-profile`، کارت تنظیمات + نوار وضعیت |
| **§22** | **NTP / زمان مورد اعتماد + تقویم شمسی** | ✅ **DONE** | `services/timeservice.py` (جدول Borkowski، بدون وابستگی)، `/settings/time[/verify]`، ساعت نوار وضعیت |
| **§23** | **Dark / Light Mode + زمان‌بندی خودکار** | ✅ **DONE** | `[data-theme]` روی همان قرارداد متغیرهای CSS، `resolved` سمت سرور، کلید نوار وضعیت |
| **§27–29** | **Update System + Backup اجباری قبل از Update** | ✅ **DONE** | `services/updater.py`: check → backup (مسدودکننده) → download → verify؛ شکست backup ⇒ ABORTED |
| **§59** | About / سازنده | ✅ **DONE** | `GET /settings/about` — «خواجوی»، کارت «دربارهٔ سامانه» |

## وضعیت نهایی فاز ۹

هر پنج شکاف پیاده‌سازی، یکپارچه و **روی سامانهٔ در حال اجرا** راستی‌آزمایی شد
(نه فقط با تست واحد). تست‌ها: **۱۹۹ passed**. تصاویر: ۳۷ اسکرین‌شات واقعی.

> **محدودیت محیطی:** GitHub از این Sandbox در دسترس نیست، بنابراین
> `GET /system/update/check` صادقانه `UNAVAILABLE` برمی‌گرداند و مسیر
> «دانلود از Release واقعی» نیازمند تست در محیط متصل به اینترنت است.

## اولویت‌بندی اجرا (تاریخچه)

۱. **Customer Ledger (§30–35)** — بزرگ‌ترین ماژول تجاری غایب؛ روی POS،
   فاکتور، گزارش و SMS اثر مستقیم دارد.
۲. Store Profile (§25) + About (§59) — پیش‌نیاز چاپ فاکتور و Installer.
۳. Trusted Time + Persian Calendar (§22).
۴. Theme (§23).
۵. Update System (§27–29).


## باگ‌های یافت‌شده و رفع‌شده در این فاز

| # | باگ | ریشه | رفع | تست رگرسیون |
|---|-----|------|-----|--------------|
| B-31 | `log_action` وجود نداشت | نام سرویس حدس زده شده بود | `write_audit` | سوئیت کامل |
| B-32 | `_invoice_out` فاقد `payment_status` | فیلد جدید به serializer اضافه نشده بود | افزوده شد | `test_phase9_platform` |
| B-33 | تداخل شمارهٔ تلفن ثابت در تست‌ها | فیکسچر session-scoped با DB مشترک | تولید تلفن یکتا | — |
| B-34 | `updater.backup_database` کرش می‌کرد | `settings.database_url` به‌جای `DATABASE_URL` | اصلاح | `test_phase9_update` |
| B-35 | **همهٔ سطرهای دفتر با تاریخ ۱۳۴۸/۱۰/۱۱** | مهاجرت ستون `created_at` را بدون `DEFAULT now()` ساخت و مدل فقط به `server_default` تکیه داشت ⇒ درج `NULL` | `default` سمت پایتون در `TimestampMixin` + backfill سطرهای موجود | ۲ تست جدید |
| B-36 | **ساعت نوار وضعیت و POS زمان اشتباه** | زمان محلیِ فروشگاه دوباره با منطقهٔ زمانی مرورگر تفسیر می‌شد | لنگر انداختن به زمان سرور | راستی‌آزمایی تصویری |
| B-37 | **آیکون‌های منو به‌صورت مربع خالی** | ایموجی روی ویندوز بدون فونت ایموجی | مجموعه آیکون SVG درون‌خطی | راستی‌آزمایی تصویری |
| B-38 | **دکمهٔ «پیامک یادآوری» همیشه ۴۲۲** | کلاینت `message` می‌فرستاد ولی schema `text` بود | endpoint اختصاصی با قالب سمت سرور | ۵ تست جدید |

سه باگ آخر فقط با **نگاه‌کردن به اسکرین‌شات‌های واقعی** پیدا شدند — نه با خواندن کد.
