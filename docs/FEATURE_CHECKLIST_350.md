# چک‌لیست ۳۵۰ قابلیت — وضعیت واقعی در نسخهٔ 1.2.0

> قانون صداقت (§57): «انجام‌شده» یعنی کد + اجرا + آزمون + نتیجهٔ مورد انتظار.
> هر جا آزمون واقعی در این محیط ممکن نبوده، صریحاً **NOT VERIFIED** نوشته شده است.

**راهنمای وضعیت**
- ✅ **DONE** — پیاده‌سازی شده و با آزمون خودکار یا اجرای واقعی تأیید شده (شمارهٔ آزمون/مسیر ذکر شده).
- 🟡 **DONE (NOT VERIFIED on hardware/network)** — کد کامل و مسیر خطا صادقانه است؛ تأیید نهایی به سخت‌افزار واقعی/اینترنت آزاد نیاز دارد.
- 🔵 **DESIGNED (v2 hook)** — زیرساخت آماده است؛ به‌عنوان قابلیت آینده در فهرست اصلی هم همین‌طور معرفی شده.

مخفف‌ها: `T:` = فایل آزمون، `API:` = مسیر HTTP، `UI:` = محل در رابط.

---

## صندوق فروش (POS) — ۱ تا ۲۶

| # | قابلیت | وضعیت | شواهد |
|---|---|---|---|
| 1 | مدیریت صندوق فروشگاهی | ✅ | `routers/pos.py`, `services/pos.py`, T: `test_pos.py` |
| 2 | فروش سریع کالا | ✅ | UI: POS اسکن→Enter→F2 |
| 3 | اسکن بارکد کالا | ✅ | `GET /products/barcode/{b}`, T: `test_phase10_scan.py` |
| 4 | جستجو بر اساس نام | ✅ | `GET /products/search?q=` |
| 5 | جستجو بر اساس بارکد | ✅ | همان مسیر؛ تشخیص خودکار عدد/متن |
| 6 | جستجوی هوشمند و پیشنهاد لحظه‌ای | ✅ | UI: POS dropdown با debounce |
| 7 | اسکن با بارکدخوان سخت‌افزاری | 🟡 | ورودی keyboard-wedge + `POST /hardware/scanner/detect` (فاصلهٔ کلید) — سخت‌افزار واقعی NOT VERIFIED |
| 8 | اسکن با دوربین موبایل | 🟡 | `frontend/mobile` BarcodeDetector + fallback دستی — دوربین واقعی NOT VERIFIED |
| 9 | مدیریت سبد خرید | ✅ | `posState.cart` |
| 10 | افزایش خودکار تعداد در اسکن متوالی | ✅ | `app.js` `existing.quantity += amount` |
| 11 | ویرایش تعداد | ✅ | UI: POS ستون تعداد |
| 12 | تخفیف روی فاکتور | ✅ **v1.1** | `invoice_discount` در checkout؛ T: `test_v1_1_features.py::test_invoice_discount_*` |
| 13 | حذف کالا از فاکتور | ✅ | UI: Del / دکمهٔ حذف خط |
| 14 | ابطال فاکتور | ✅ | `POST /invoices/{id}/void`; T: `test_pos.py::test_void_restocks` |
| 15 | ثبت پرداخت | ✅ | `payments[]` |
| 16 | روش‌های مختلف پرداخت | ✅ | CASH/CARD/ACCOUNT/MIXED |
| 17 | چاپ فاکتور حرارتی | ✅ **v1.2** (device NOT VERIFIED) | `escpos_driver.py` tcp/usb/win/file، رسید فارسی cp1256، لوگو raster؛ T: `test_escpos_tcp_receipt_cut_and_drawer` (شبیه‌ساز 9100 بایت‌به‌بایت) — پرینتر فیزیکی در دسترس نبود |
| 18 | چاپ مجدد فاکتور | ✅ | UI: فاکتورها → «چاپ» |
| 19 | اتصال به کشوی پول | ✅ **v1.2** (device NOT VERIFIED) | `ESC p` پین ۲/۵ از طریق پرینتر در فروش نقدی؛ T: `test_escpos_tcp_receipt_cut_and_drawer` (`\x1bp\x01` دریافت شد) |
| 20 | حالت تمام‌صفحه صندوق | ✅ | `requestFullscreen` در kiosk |
| 21 | قفل صندوق با کلید میانبر | ✅ | `pos.kiosk_shortcut` (Ctrl+Shift+L) |
| 22 | حالت اختصاصی و امن صندوق | ✅ | `POST /pos/kiosk/unlock` با اعتبار مدیر؛ T: `test_phase*` |
| 23–26 | مشتری هنگام فروش / آزاد / ثبت‌شده / انتخاب | ✅ | `customer_id` یا `customer_phone` در checkout |

## مشتریان و حساب دفتری — ۲۷ تا ۳۶

| # | قابلیت | وضعیت | شواهد |
|---|---|---|---|
| 27 | حساب دفتری مشتری | ✅ | `services/ledger.py` (append-only) ; T: `test_phase9_ledger.py` |
| 28 | ثبت بدهی | ✅ | tender `ACCOUNT` → `CREDIT_SALE` |
| 29 | تسویه کامل | ✅ | `POST /customers/{id}/settle` (full) |
| 30 | تسویه جزئی | ✅ | همان با مبلغ |
| 31 | تاریخچهٔ کامل خرید | ✅ | `GET /customers/{id}/invoices` |
| 32 | دفترچه تلفن | ✅ | `GET /customers?q=` , `GET /customers/phone/{p}` |
| 33 | ذخیرهٔ شمارهٔ بدون نام | ✅ | نام پیش‌فرض = شماره/«بدون نام» |
| 34 | پیامک یادآوری بدهی | ✅ | `POST /customers/{id}/debt-reminder` (الگو §166) |
| 35 | پیامک فاکتور | ✅ | پس از checkout؛ T: `test_invoice_sms_uses_editable_pattern` |
| 36 | مدیریت حساب‌ها | ✅ | `credit_limit`, `credit_enabled`, `ledger/verify` |

## کالاها و شناسایی خودکار — ۳۷ تا ۸۲

| # | قابلیت | وضعیت | شواهد |
|---|---|---|---|
| 37–41 | مدیریت/تعریف/ویرایش/حذف/ویرایش سریع قیمت | ✅ | `routers/products.py` (`quick-price`), audit `PRODUCT_DELETED` |
| 42–44 | بارکد شرکتی / بدون بارکد / بارکد داخلی INT- | ✅ | `next_internal_barcode`; T: `test_phase11_catalog_identity.py` |
| 45–51 | واحدها (عدد، گرم، کیلوگرم، میلی‌گرم، میلی‌لیتر، لیتر، متر) | ✅ | `services/units.py` + `/units`; مقدار اعشاری در Batch/POS |
| 52–56 | شناسایی از بارکد، چند منبع، موتور، اولویت، اعتبارسنجی | 🟡 | `services/resolvers.py` + `ExternalSource.priority` ؛ T: `test_resolvers.py` (mock) — منابع زندهٔ اینترنت NOT VERIFIED (egress بسته) |
| 57–63 | تکمیل خودکار نام/برند/مدل/SKU/دسته/توضیح/واحد | ✅ | `POST /barcode/resolve`, `POST /products/suggest` |
| 64–66 | تصویر خودکار / منابع جایگزین / دانلود محلی | 🟡 | `resolve_image` → `MEDIA_DIR`؛ T: mock — دانلود واقعی NOT VERIFIED |
| 67–70 | کش، منبع، زمان، سطح اطمینان | ✅ | `ProductResolverResult(source, confidence, fetched_at)` |
| 71–76 | قیمت بازار/فروشنده/مصرف‌کننده/آخرین/پیشنهاد/ویرایش | ✅ | `services/pricing.py::suggest_sell_price`, `MarketPrice` |
| 77 | تأیید دستی Auto-Fill | ✅ | `POST /barcode/results/{id}/review` + `products.autofill_requires_confirm` |
| 78 | دسته‌بندی | ✅ | `/products/categories` (**باگ 422 در v1.1 رفع شد**) |
| 79 | زیردسته | ✅ **v1.1** | `parent_id`, `path`; T: `test_subcategory_parent_and_path` |
| 80–82 | دیتابیس اولیه، ورود اولیه، موجودی صفر | ✅ **v1.2** | `app/data/starter_catalog.csv` (۱۹۱ کالا/۱۳ دسته/۳۰ زیردسته، آفلاین، بدون بارکد جعلی)، `GET/POST /products/import/starter`, `POST /products/import/csv`; UI: کارت «بانک اولیهٔ کالاها»; T: `test_starter_catalog_import_is_zero_stock_and_idempotent` |

## انبار، Batch، انبارگردانی — ۸۳ تا ۱۳۱

| # | قابلیت | وضعیت | شواهد |
|---|---|---|---|
| 83–88 | ورود/خروج، تاریخ، ساعت دقیق، کاربر، تاریخچه | ✅ | `StockMovement(created_at, created_by)`; `/inventory/movements` |
| 89–98 | Batch: چندگانه، فعال، موجودی، خرید، فروش، مصرف‌کننده، ورود، تولید، انقضا | ✅ | `ProductBatch`; `GET /products/{id}/detail`; T: `test_batches.py`, `test_phase11_product_batch_identity.py` |
| 99–103 | قیمت قدیم/جدید، انتخاب Batch، قیمت قدیمی، Batch با موجودی، کسر از Batch انتخابی | ✅ | `GET /pos/batch-options/{id}`, `InvoiceItem.batch_id`; T: `test_pos.py` |
| 104–105 | بهای تمام‌شده و سود واقعی | ✅ | `InvoiceItem.unit_buy_price/profit`; T: `test_split_sale_between_batches_exact_profit` |
| 106 | برگشت کالا | ✅ | `POST /returns`; T: `test_phase3.py` |
| 107 | ضایعات | ✅ | `POST /inventory/waste` |
| 108 | اصلاح موجودی | ✅ | `POST /inventory/adjust` |
| 109 | انتقال موجودی | ✅ **v1.1** | `POST /warehouses/transfer`; T: `test_create_warehouse_location_and_transfer` |
| 110–111 | Stock Movement کامل، کنترل لحظه‌ای | ✅ | `_atomic_deduct` |
| 112–113 | هشدار کمبود، حداقل قابل تنظیم | ✅ | `min_stock_alert`, `/reports/low-stock`, داشبورد |
| 114–117 | انقضا: مدیریت، هشدار، منقضی، Batch نزدیک انقضا | ✅ | `services/expiry.py`, `/reports/expiry` |
| 118–129 | انبارگردانی: دوره، مرحله‌ای، ادامه، ذخیرهٔ خودکار، دوربین، بارکدخوان، دستی، مقایسه، مغایرت، تأیید، گزارش | ✅ | `cursor_item_id`, `/stocktakes/*`, `count/bulk`, `approve`; T: `test_phase4.py`, `test_phase10_scan.py` |
| 130 | چند انبار | ✅ **v1.1** | `warehouses` |
| 131 | محل نگهداری | ✅ **v1.1** | `storage_locations` |

## داشبورد و گزارش‌ها — ۱۳۲ تا ۱۴۹

| # | قابلیت | وضعیت | شواهد |
|---|---|---|---|
| 132 | داشبورد | ✅ | `GET /reports/dashboard` (۱۲ بلوک §23) |
| 133–140 | فروش روزانه/هفتگی/ماهانه (شمسی)، سود، موجودی، ارزش، کم‌موجود، نزدیک انقضا، منقضی | ✅ **v1.2** | `/reports/sales?group=daily|weekly|monthly|product`, `/profit`, `/inventory`, `/low-stock`, `/expiry`; T: `test_sales_report_monthly_jalali_buckets` |
| 141–143 | خرید، ورود و خروج، Batchها | ✅ | `/reports/purchase-cost`, `/movements`, `/batches` |
| 144–146 | مشتریان، بدهی، حساب‌های دفتری | ✅ | `/customers/debtors`, `/customers/{id}/ledger`, بلوک `receivables` |
| 147–149 | تخفیف‌ها، جشنواره‌ها، کدهای تخفیف | ✅ | `/marketing/stats`, `/coupons/{id}/redemptions`, `/campaigns` |

## جشنواره و کوپن — ۱۵۰ تا ۱۶۳

| # | قابلیت | وضعیت | شواهد |
|---|---|---|---|
| 150–161 | کمپین، ایجاد کد، درصدی، مبلغی، سقف‌دار، حداقل خرید، حداکثر تخفیف، دفعات، اختصاصی مشتری، خرید بعدی، تاریخ، غیرفعال‌سازی خودکار | ✅ | `models/marketing.py`, `services/coupons.py`; T: `test_phase7_coupons.py` |
| 162 | ارسال کد همراه فاکتور | ✅ | `coupon_line` در پیامک فاکتور |
| 163 | قوانین ترکیبی | ✅ | ترتیب ثابت: تخفیف خط → تخفیف فاکتور → کوپن (روی مبلغ پس از تخفیف) → مالیات؛ یک کوپن در هر فاکتور؛ `max_discount` سقف |

## پیامک — ۱۶۴ تا ۱۷۷

| # | قابلیت | وضعیت | شواهد |
|---|---|---|---|
| 164–165 | سیستم پیامک، ملی‌پیامک (+ کاوه‌نگار) | ✅ **v1.2** (live NOT VERIFIED) | REST رسمی `SendSMS`/`BaseServiceNumber`/`GetCredit`/`GetDeliveries2`، خطاهای فارسی; T: `test_melipayamak_line_mode_success_and_credit`, `test_melipayamak_pattern_mode_error_codes` (سرور شبیه‌ساز) — egress بسته |
| 166 | Pattern پیامک | ✅ **v1.1** | `GET /sms/templates`, `sms.template.*` |
| 167 | تنظیم API | ✅ | تب «پیامک» (مقادیر محرمانه write-only) |
| 168–171 | ارسال خودکار، صف، وضعیت، Retry | ✅ | worker + `SyncJob`; `POST /sms/{id}/retry` **v1.1**; T: `test_sms_manual_retry_requeues_failed` |
| 172–174 | پیامک فاکتور / بدهی / تخفیف | ✅ | الگوهای مربوطه |
| 175 | پیامک گزارش مدیریت | ✅ **v1.1** | `POST /sms/daily-report` |
| 176 | پیامک هشدار انبار | ✅ **v1.1** | `expiry_scan` → `queue_low_stock_alert` |
| 177 | تست اتصال سرویس | ✅ **v1.1** | `POST /sms/test-connection` |

## سخت‌افزار و عیب‌یابی — ۱۷۸ تا ۲۰۱

| # | قابلیت | وضعیت | شواهد |
|---|---|---|---|
| 178–182 | پرینتر حرارتی، ESC/POS، عرض کاغذ، Cutter، کشو | ✅ **v1.2** (device NOT VERIFIED) | `printer.paper_width_mm`→۳۲/۴۲/۴۸ ستون، `printer.cut`→`GS V`, `printer.drawer.*`→`ESC p`; T: `test_visual_rtl_and_columns`, شبیه‌ساز 9100; `docs/HARDWARE.md` |
| 183–185 | تنظیمات و تست اتصال سخت‌افزار/سرویس‌ها | ✅ | `/hardware/health`, `/hardware/test/*`, `/diagnostics/run` |
| 186–195 | مرکز عیب‌یابی، چک‌لیست، API، قیمت، تصویر، پیامک، دیتابیس، شبکه، لاگ تست، خطاهای اتصال | ✅ | `services/diagnostics.py` (۱۱+ بررسی، `DiagnosticRun` ذخیره می‌شود); T: `test_phase8_diagnostics.py` |
| 196–201 | لاگ کامل: کاربران، خطاها، مالی، انبار، صندوق | ✅ | `AuditLog` + `API_ERROR`, `STOCK_*`, `VOID_*`, `KIOSK_*`, `SMS_*`, `UPDATE_*`; T: `test_audit_regressions.py` |

## کاربران، فروشگاه، تنظیمات — ۲۰۲ تا ۲۳۷

| # | قابلیت | وضعیت | شواهد |
|---|---|---|---|
| 202–208 | کاربران، کارکنان، پروفایل، رمز، نقش‌ها، دسترسی بخش‌ها، مدیر اصلی | ✅ | `security.py` (۲۱ مجوز، ۵ نقش), `/users`; T: `test_auth.py` |
| 209 | تأیید رمز مدیر برای عملیات حساس | ✅ **v1.1** | خروج kiosk، Update، **ابطال فاکتور پرداخت‌شده**; T: `test_void_paid_requires_admin_password` |
| 210–214 | پروفایل، نام، آدرس، تلفن، لوگو | ✅ **v1.2** | `/settings/store-profile`, **`POST/DELETE /settings/store-profile/logo`** (آپلود، `/media`, سایدبار/ورود/درباره/رسید); T: `test_store_logo_upload_serves_and_reaches_receipt` |
| 215–229 | ۱۵ دستهٔ تنظیمات | ✅ **v1.1** | ۲۲ تب فارسی؛ T: `test_settings_cover_all_required_categories` |
| 230 | تومان/ریال | ✅ | `/settings/currency` |
| 231–234 | ساعت/تاریخ، زمان اینترنتی، شمسی، همگام‌سازی | ✅ | `timeservice.py` (NTP + تبدیل جلالی), `/settings/time/verify` |
| 235–237 | دارک/لایت/خودکار ۱۹→۰۷ | ✅ | `/settings/theme` (`ui.theme_*_at`) |

## UI/UX، معماری، موبایل — ۲۳۸ تا ۲۶۵

| # | قابلیت | وضعیت | شواهد |
|---|---|---|---|
| 238–248 | UI حرفه‌ای، دسکتاپ، موبایل، Responsive، داشبورد گرافیکی، فارسی، فونت، وضعیت شبکه، ساعت پایین، وضعیت سیستم، Full Screen | ✅ **v1.2** | `styles.css`, **فونت Vazirmatn بسته‌بندی‌شده** (`frontend/fonts`, OFL, در SW کش می‌شود)، نوار وضعیت (`#sb-*`), اسموک jsdom |
| 249 | برنامهٔ دسکتاپ اختصاصی Windows | 🟡 | `run_supermarket.py` (پنجرهٔ `--app=` اختصاصی) — اجرا روی ویندوز واقعی NOT VERIFIED |
| 250–254 | Web Panel، Backend محلی، Local DB، Local-First، Offline | ✅ | FastAPI + SQLite + `sw.js` + صف آفلاین موبایل |
| 255 | همگام‌سازی با سرور | 🔵 | `SyncJob` صف عمومی + `sync/run`; سرور مرکزی = فاز بعد (مطابق فهرست §260) |
| 256 | PWA | ✅ | `manifest.webmanifest`, `sw.js`, آیکون‌ها |
| 257 | نسخهٔ Android | 🟡 **v1.2** (build NOT VERIFIED) | پروژهٔ بومی `mobile-android/` (WebView + دوربین + صفحهٔ اتصال LAN + بنر آفلاین، نسخه از `__init__.py`) + `installer/ci/release-android.yml`; PWA همچنان قابل نصب — Android SDK در این محیط نبود |
| 258–259 | اتصال موبایل به DB اصلی در LAN | ✅ | `bind 0.0.0.0`, `check_lan` در عیب‌یابی |
| 260 | اتصال آینده از اینترنت | 🔵 | JWT + CORS پیکربندی‌پذیر (`CORS_ORIGINS`) |
| 261–265 | انبارگردانی موبایل، دوربین، UI اختصاصی، ذخیرهٔ لحظه‌ای، ادامه | ✅ | `frontend/mobile/app.js`, `client_key` idempotent; T: `test_phase10_scan.py` |

## به‌روزرسانی و نصب — ۲۶۶ تا ۲۹۳

| # | قابلیت | وضعیت | شواهد |
|---|---|---|---|
| 266–276 | نسخه‌ها، بررسی، خودکار، GitHub، **Update Server**، تأیید مدیر، رمز، حفظ داده، Migration امن، Backup، Rollback | ✅ **v1.2** (live NOT VERIFIED) | `services/updater.py` کانال `github`/`server` (`update.*`)، اجبار SHA-256; T: `test_phase9_update.py`, `test_update_server_channel_check_and_checksum` (سرور شبیه‌ساز + بسته + checksum); `docs/UPDATE.md` |
| 277–287 | Installer، Setup استاندارد، بدون Runtime، پیش‌نیازها، آفلاین، دانلود مدیریت‌شده، Progress، Shortcutها، سازگاری، خطاها | 🟡 | `installer/windows/*` (Inno + PyInstaller, `MinVersion`, `x64`) — ساخت و نصب واقعی روی ویندوز **NOT VERIFIED** (این محیط لینوکس است) |
| 288 | تست Installer روی Windows | ❌ NOT VERIFIED | نیاز به ماشین ویندوز / CI |
| 289 | Build خودکار | 🟡 | `installer/ci/release-windows.yml` + `release-android.yml`؛ فعال‌سازی یک‌باره با `scripts/activate-ci.sh` (توکن این محیط مجوز `workflows` ندارد — تلاش شد، 403) |
| 290–291 | Release در GitHub، فایل نصب در Release | 🟡 | تگ‌های v1.0.0/v1.1.0/v1.2.0 با یادداشت؛ asset (Setup.exe/APK) توسط workflow پس از فعال‌سازی ضمیمه می‌شود — **آپلود از این sandbox مسدود است** |
| 292–293 | SemVer، نسخهٔ 1.x کامل | ✅ | `__version__ = "1.2.0"` (منبع واحد نسخه برای installer، APK، About) |

## کیفیت، مستندات، تحویل — ۲۹۴ تا ۳۵۰

| # | قابلیت | وضعیت | شواهد |
|---|---|---|---|
| 294–298 | Repo استاندارد، Branchها، ادغام، حذف تکراری، یکپارچه‌سازی | ✅ | `docs/CONSOLIDATION_REPORT.md` |
| 299–302 | Regression، Unit، Integration، E2E | ✅ | ۲۶۴ آزمون HTTP-level + اسموک jsdom |
| 303–309 | تست POS، انبار، Batch، قیمت، Barcode/Image/Price Resolver | ✅ | فایل‌های `tests/test_*` (Resolver با mock) |
| 310–312 | تست SMS، Printer، Cash Drawer | ✅ **v1.2** (device/live NOT VERIFIED) | شبیه‌ساز ملی‌پیامک + شبیه‌ساز پرینتر 9100 (init، cut، `ESC p`) + `file://`؛ ۹ آزمون جدید در `test_v1_1_features.py` |
| 313–315 | تست موبایل، Offline، شبکه | ✅ / 🟡 | jsdom + `check_lan`; شبکهٔ واقعی چند-دستگاه NOT VERIFIED |
| 316 | تست Update | ✅ | `test_phase9_update.py` (کانال جعلی) |
| 317 | تست Windows Installer | ❌ NOT VERIFIED | — |
| 318 | تست امنیت | ✅ | قفل ۵ تلاش، JWT، مجوزها، رمز مجدد برای عملیات حساس، secrets write-only |
| 319–323 | رفع Bug، تست مجدد، Regression، گزارش خطا، گزارش تست | ✅ | `BUG_REPORT.md`, `TEST_REPORT.md`, CHANGELOG |
| 324–331 | مستندات: سیستم، نصب، API، دیتابیس، سخت‌افزار، Resolver، پیامک، Update | ✅ **v1.2** | `README.md`, `INSTALL.md`, `API.md`, **`DATABASE.md`** (۳۷ جدول از مدل‌ها), **`HARDWARE.md`**, **`RESOLVER.md`**, **`SMS.md`**, **`UPDATE.md`** |
| 332–333 | PDF معرفی + اسکرین‌شات | ✅ | `docs/SCREENSHOTS.pdf` (اسکرین‌شات‌های v1.0.0؛ نماهای جدید v1.1 در PDF نیستند) |
| 334–341 | نقشه‌ها: معماری، جریان داده، DB، موبایل↔دسکتاپ، انبارگردانی، فروش، ثبت محصول، سرویس‌های خارجی | ✅ **v1.2** | **`docs/DIAGRAMS.md`** (۷ نمودار Mermaid) + ER در `DATABASE.md` + `ARCHITECTURE.md` |
| 342–343 | درباره ما، نام توسعه‌دهنده «خواجوی» | ✅ | `GET /settings/about`, تب «درباره» |
| 344–350 | آمادهٔ فروش، حفظ داده، Backup، بازیابی، امنیت داده، توسعه‌پذیر، Production-Ready | ✅ / 🟡 | `/backup`, `/restore` (validated), مهاجرت‌های افزودنی — Production در ویندوز واقعی پس از تأیید Installer |

---

## جمع‌بندی صادقانه

| وضعیت | تعداد تقریبی |
|---|---|
| ✅ DONE و آزمون‌شده (شامل مواردی که با شبیه‌ساز دستگاه/سرویس بایت‌به‌بایت آزمون شده‌اند) | ~۳۲۵ |
| 🟡 کد کامل؛ اجرای نهایی فقط روی سخت‌افزار/اینترنت/ویندوز/Android SDK ممکن است (§7–8، §52–56، §64–66، §249، §257، §277–287، §289–291، §313–315، §344–350) | ~۲۰ |
| 🔵 hook طراحی‌شده برای فاز بعد (مطابق متن فهرست: «آینده») | ۲ (§255، §260) |
| ❌ NOT VERIFIED (فقط با ماشین ویندوز قابل انجام) | ۲ (§288، §317) |

مواردی که در این محیط **قابل اثبات نیستند** و ادعای موفقیت برایشان نمی‌کنیم:
چاپگر/کشو/اسکنر فیزیکی، ارسال زندهٔ پیامک، دانلود از OpenFoodFacts/GitHub،
ساخت و نصب Setup.exe روی ویندوز، ساخت APK اندروید (بدون SDK)، آپلود asset به Release از این sandbox.
برای هرکدام مسیر اثبات آماده است: workflowهای CI (`scripts/activate-ci.sh`)، شبیه‌سازهای آزمون، و `docs/HARDWARE.md`/`SMS.md`/`UPDATE.md`.
