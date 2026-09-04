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
| **§30–35** | **حساب دفتری مشتری، بدهی، تسویه، SMS یادآوری** | ❌ **MISSING** | مدل `Customer` فقط name/phone/email؛ هیچ endpoint ledger/payment/debt در ۱۰۲ endpoint نیست |
| **§25** | **پروفایل فروشگاه (نام/لوگو/آدرس/تلفن)** | ❌ **MISSING** | هیچ کلید `store.*` در `DEFAULT_SETTINGS` |
| **§22** | **NTP / زمان مورد اعتماد + تقویم شمسی** | ❌ **MISSING** | صفر نتیجه برای `ntp` و `jalali` در کل مخزن |
| **§23** | **Dark / Light Mode + زمان‌بندی خودکار** | ❌ **MISSING** | هیچ theme در `app.js` یا settings |
| **§27–29** | **Update System + Backup اجباری قبل از Update** | ❌ **MISSING** | Backup/Restore هست، اما مسیر Update وجود ندارد |
| **§59** | **About / سازنده** | ❌ MISSING | — |

## اولویت‌بندی اجرا

۱. **Customer Ledger (§30–35)** — بزرگ‌ترین ماژول تجاری غایب؛ روی POS،
   فاکتور، گزارش و SMS اثر مستقیم دارد.
۲. Store Profile (§25) + About (§59) — پیش‌نیاز چاپ فاکتور و Installer.
۳. Trusted Time + Persian Calendar (§22).
۴. Theme (§23).
۵. Update System (§27–29).

## باگ‌های یافت‌شده در این فاز

(در حین پیاده‌سازی هر بخش ثبت می‌شود — §47 Regression Rule.)
