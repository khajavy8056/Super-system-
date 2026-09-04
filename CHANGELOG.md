# Changelog

همه تغییرات مهم این پروژه در این فایل ثبت می‌شود. فرمت بر اساس [Keep a Changelog](https://keepachangelog.com) و نسخه‌گذاری [SemVer](https://semver.org).

## [0.2.0] - 2026-09-04 (فاز ۶)

### Added
- **Installer/Launcher**: لانچر standalone (`installer/windows/run_supermarket.py`) با پورت آزاد،
  دادهٔ کاربر در `~/SupermarketSystem` (DB+logs+secret پایدار بین ری‌استارت‌ها)،
  health-probe واقعی قبل از باز کردن مرورگر؛ spec پکی‌جینگ PyInstaller + اسکریپت Inno Setup
  + `build.ps1` + icon.ico؛ بیلد cx_Freeze برای تست frozen در لینوکس
  (**boot-test کامل**: health/login/frontend/DB/ری‌استارت). ویندوز واقعی: UNTESTED (مستند).
- **رندر واقعی UI**: `scripts/make_qt_stublibs.py` (تولید stub-libs از خود PySide6 با
  verneed parsing درست)، `scripts/shoot.py` (WebEngine offscreen، غیرblank-verified)،
  `scripts/shots.json` (۲۱ تصویر از همه بخش‌ها + PDF)؛
  `docs/SCREENSHOTS.md` + `docs/SCREENSHOTS.pdf` (معرفی فارسی هر بخش با تصویر واقعی،
  ۲۳ صفحه)؛ `scripts/make_pdf.py`.
- **مستندات**: `docs/BUILD.md` (روش build ویندوز/لینوکس + وضعیت تست‌شدگی صادقانه).

### Fixed
- PyInstaller spec: مسیر repo root اشتباه (سه parent به جای دو parent) و
  hiddenimports منسوخ → اصلاح شد.
- cx_Freeze: `sqlalchemy.dialects.sqlite` باید صریحاً باندل شود (entry-point loader).

## [0.1.0] - 2026-09-04

### Added
- **هسته**: احراز هویت JWT، کاربران، نقش‌ها و مجوزهای گرانولار، Audit Log.
- **کالا**: Product / Category / Brand / Unit + ثبت با بارکد.
- **Batch**: ورود کالا → Batch جدید با قیمت خرید/مصرف‌کننده/فروش و تاریخ تولید/انقضا؛ بدون بازنویسی تاریخچه.
- **قیمت**: PriceVersion با تاریخچه کامل؛ تشخیص و فروش هم‌زمان قیمت قدیم/جدید.
- **موجودی**: Stock Movements (PURCHASE_IN/SALE_OUT/WASTE/ADJUSTMENT/STOCKTAKE/...)، Adjustment، Waste.
- **انبارگردانی**: Stocktaking + تطبیق فیزیکی/سیستمی + Audit.
- **انقضا**: موتور Expiry با آستانه‌های قابل تنظیم و مسدودسازی فروش کالای منقضی.
- **POS**: اسکن بارکد، انتخاب Batch/قیمت (HYBRID/FIFO/FEFO)، Checkout اتمیک، Void، Return، سود واقعی Batch.
- **گزارش**: داشبورد (فروش/سود/موجودی/انقضا/تعارض قیمت)، گزارش سود Batch، گردش کالا.
- **سخت‌افزار**: لایه انتزاعی پرینتر/کشو، تشخیص اسکنر بر اساس زمان‌بندی، تست چاپ/کشو.
- **رزولورها**: بیکد/تصویر/قیمت بازار با ترتیب محلی → کش → خارجی → دستی (بدون داده جعلی).
- **پنل وب**: SPA فارسی/RTL (داشبورد، POS، کالا، ورود، انبار، فاکتور، گزارش، سخت‌افزار، کاربر، تنظیمات، لاگ).
- **زیرساخت**: مهاجرت Alembic (۲۹ جدول)، seed دمو، backup آنلاین SQLite، ۲۱ تست خودکار.
- **مستندات**: README، ARCHITECTURE، API، INSTALL.

### Security
- بدون Hard-Code کردن اعتبارنامه‌ها؛ همه از متغیرهای محیطی/تنظیمات رمزنگاری‌شده.
