# Consolidation & Final Release Report — v1.0.0

گزارش نهایی مأموریت یکپارچه‌سازی. هر بند مطابق فهرست خروجی §۵۸ است و فقط
ادعاهایی که با ابزار/اجرا در همین نشست تأیید شده‌اند ثبت شده؛ بقیه صریحاً
NOT VERIFIED نوشته شده‌اند.

## 1. Architecture Summary
یک Codebase واحد: FastAPI (لایهٔ services + repositories) ← SQLite/PostgreSQL؛
وب‌پنل SPA فارسی RTL؛ PWA موبایل مستقل؛ لانچر دسکتاپ ویندوز. اصل بنیادی حفظ
شده: Product≠Batch، قیمت تاریخی بازنویسی‌ناپذیر، InvoiceItem snapshot، Checkout
اتمی، چاپ هرگز فروش را خراب نمی‌کند. دو خط توسعهٔ موازی (v0.3.x و v0.4.0) در یک
Branch ادغام شدند؛ `main` همچنان مرجع است و این نشست روی Branch اختصاصی کار کرد.

## 2. Branch Audit
| Branch/Tag | فایل | محتوا | سرنوشت |
|---|---|---|---|
| v0.1.0 (01a06c38) | 78 | هستهٔ اولیه | جد همه؛ چیزی منحصربه‌فرد ندارد |
| v0.2.0 | — | installer/launcher + اسکرین‌شات | در main بود |
| v0.3.0/v0.3.1 (01a06e5f) | 212 | فاز ۷–۱۱ + CI | **به main برگشت** |
| v0.4.0 (01a06c54) | 143 | installer اصلاح‌شده | روی main بود؛ با خط B ادغام شد |
| main (قبل) | 143 | فقط خط A | ناقص بود (۸ ماژول، ۲ روتر، ۳ مهاجرت، ۱۲ تست کم) |

## 3. Feature Consolidation Report
ماتریس کامل در [`FEATURE_MATRIX.md`](FEATURE_MATRIX.md). خلاصه: همهٔ قابلیت‌های
خط B به main آمد؛ شکاف‌های §۲۳/§۳۶/§۴۳/§۴۹/§۱۹/§۲ بسته شد؛ باگ‌های `\$ScriptDir`،
`x64compatible`، نسخهٔ سخت‌کدشده و import تکراری اصلاح شد.

## 4. Database Changes
۶ مهاجرت (۳ جدید از خط B). ۳۶ جدول. FK/unique بازبینی شد. هیچ ستونی حذف/تغییرنام
نشد (§۲۹/§۵۴). Restore/Backup با SQLite online-backup API تست شد.

## 5. API Changes
۱۴ endpoint. جدید در ۱٫۰٫۰: بلوک‌های `receivables/sms/system` در
`/api/reports/dashboard`. بقیهٔ سطح API بدون شکست سازگاری حفظ شد.

## 6. UI/UX Changes
داشبورد سه کارت جدید؛ تنظیمات تب‌بندی‌شدهٔ فارسی؛ لوگوی برداری در همه‌جا؛ RTL و
Light/Dark حفظ شد. همهٔ viewها در DOM بدون خطا اجرا شدند.

## 7. Mobile Changes
PWA مستقل با اسکن دوربین (BarcodeDetector)، صف آفلاین، و همهٔ ماژول‌ها. لوگو به
manifest/PWA افزوده شد. بدون خطای runtime اجرا شد.

## 8. Windows Changes
لانچر اکنون پنجرهٔ اختصاصی Edge/Chrome app-mode باز می‌کند (fallback به مرورگر).
بستن پنجره = توقف سرور. builder یک موتور مشترک دارد؛ portable همیشه ساخته می‌شود.

## 9. Bug Fixes
`$ScriptDir` (مرگبار)، `x64compatible`، AppId غیرGUID، نسخهٔ سخت‌کدشدهٔ artifact،
نسخهٔ قدیمی config، import تکراری، و شکاف‌های داشبورد/لاگ/واحد/لوگو/تنظیمات.

## 10. Test Results
**۲۵۰ آزمون خودکار موفق** (main قبلی ۸۸؛ خط B ۲۲۸). آزمون جدید
`test_v1_consolidation.py` شامل ۲۲ تست هدفمند برای همهٔ شکاف‌ها.

## 11. Regression Results
پس از هر تغییر، کل سوئیت اجرا شد (۴ بار). همهٔ viewهای ادمین و موبایل با اجرای DOM
بدون خطا (regression UI). زنجیرهٔ Database→POS→Invoice→Profit→Report با آزمون‌های
فازهای قبل پوشش داده شد و سبز ماند.

## 12. Installer Test Results
منطق لانچر و مهاجرت فریزشده روی لینوکس boot-تست شده (از قبل). اسکریپت‌های builder
بازبینی ایستا + آزمون متنی شدند. **ساخت PyInstaller/Inno و نصب Setup.exe روی
ویندوز واقعی: NOT VERIFIED** (سند صداقت) — مسیر CI در `installer/ci/` آماده است.

## 13. Update Test Results
چرخهٔ check→backup→download→verify با کانال آفلاین تست شد؛ رویدادهای
UPDATE_STARTED/COMPLETED/FAILED ثبت می‌شوند. Backup قبل از update اجباری است.

## 14. Known Issues
- فعال‌سازی CI ویندوز نیازمند توکن با مجوز `workflows` است (توکن فعلی App بدون آن).
- ارسال زندهٔ SMS به melipayamak/kavenegar و دانلود از OpenFoodFacts در این سندباکس
  به دلیل محدودیت egress/TLS تست نشد (آداپتورها پیاده‌اند؛ UNTESTED-LIVE).
- PyInstaller/Inno و نصب ویندوز واقعی در این محیط قابل اجرا نیست.

## 15. Security Findings
بدون hard-code اعتبارنامه؛ تنظیمات محرمانه write-only و با ماسک؛ JWT با کلید
پایدار per-install؛ خطاهای ۵۰۰ بدون لوختStackTrace؛ هدرهای امنیتی تنظیم شد.

## 16. Performance Findings
داشبورد/گزارش‌ها با کوئری‌های group-by (نه materialize)؛ در ۲۰ کالا و دادهٔ
نمایشی پاسخ‌ها <۱۰۰ms. هیچ حلقهٔ N+1 جدیدی افزوده نشد.

## 17. v1.0.0 Release Status
- کد: Branch `arena/01a076d3-super-system` push شد (تک‌کامیت تمیز روی main).
- نسخه: `1.0.0` در همهٔ نقاط یکسان.
- تست: ۲۵۰ موفق + اجرای DOM.
- تگ: `v1.0.0` push شد. ✅
- Release گیت‌هاب: **ایجاد شد** (بدون asset) —
  `https://github.com/khajavy8056/Super-system-/releases/tag/v1.0.0`. ✅
- آپلود asset از این سندباکس: **ناممکن** — `uploads.github.com` خارج از
  allowlist خروج شبکه است (خطای EOF). سورس tarball + checksum به‌صورت محلی
  ساخته و در `/tmp/relassets/` محاسبه شد؛ CI پس از فعال‌سازی، Setup.exe و
  tarball لینوکس و checksumها را به همین Release پیوست می‌کند.

### فعال‌سازی نهایی توسط نگهدارنده (دارای مجوز)
```bash
# ۱) فعال‌سازی CI (مجوز workflows)
git mv installer/ci/release-windows.yml .github/workflows/release-windows.yml
git commit -m "ci: activate the Windows release workflow" && git push
# ۲) تگ و Release
git tag v1.0.0 && git push origin v1.0.0
gh release create v1.0.0 --title "v1.0.0" --notes-file docs/CONSOLIDATION_REPORT.md
```
