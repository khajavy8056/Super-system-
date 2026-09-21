# ساخت و انتشار فایل‌های Release

workflow در همین پوشه قرار دارد:

```
installer/ci/release-windows.yml
```

> **چرا نه در `.github/workflows/`؟** توکن خودکاری که این مخزن را نگهداری می‌کند
> یک GitHub App است که مجوز `workflows` **ندارد** و GitHub هر push ای را که
> فایلی زیر `.github/workflows/` بسازد رد می‌کند (پیام:
> `refusing to allow a GitHub App to create or update workflow ... without
> workflows permission`). بنابراین workflow در این مسیر نگهداری می‌شود تا قابل
> push باشد و یک‌بار باید توسط یک نگهدارندهٔ دارای مجوز فعال شود:
>
> ```bash
> git mv installer/ci/release-windows.yml .github/workflows/release-windows.yml
> git commit -m "ci: activate the Windows release workflow"
> git push
> ```
>
> پس از این جابه‌جایی، هر push روی تگ `v*` به‌صورت خودکار Setup.exe ویندوز و
> بستهٔ لینوکس را می‌سازد و به Release پیوست می‌کند. تا پیش از آن، وضعیت این
> بخش **NOT VERIFIED on real hardware** است (سند صداقت).

این workflow **هر دو** خروجی را می‌سازد و به Release پیوست می‌کند:
`SupermarketSystem-Setup-<version>.exe` (ویندوز) و
`SupermarketSystem-<version>-linux-x86_64.tar.gz` (لینوکس).
عدد نسخه از `backend/app/__init__.py` خوانده می‌شود، نه از مقدار سخت‌کدشده.

## اجرا

هر push روی تگ `v*` به‌صورت خودکار workflow را اجرا می‌کند. اجرای دستی هم از
تب **Actions** ممکن است: گزینهٔ «Build and publish release assets» را با
`tag = v1.0.0` اجرا کنید. خروجی‌ها به‌صورت خودکار به همان Release پیوست
می‌شوند.

## چرا Setup.exe در محیط توسعهٔ لینوکسی ساخته نمی‌شود

محیط توسعه لینوکس است. PyInstaller **کراس‌کامپایل نمی‌کند** و Inno Setup هم
ابزار ویندوزی است. بنابراین تولید یک فایل `.exe` در اینجا یا غیرممکن است یا
نتیجه‌ای تست‌نشده به دست می‌دهد؛ طبق قاعدهٔ «هیچ چیز تست‌نشده‌ای
production-ready گزارش نمی‌شود»، مسیر ساخت روی سخت‌افزار واقعی ویندوز تعریف
شده است. به‌جای آن، بستهٔ فریزشدهٔ لینوکس با cx_Freeze ساخته و **بوت واقعی**
می‌شود تا منطق لانچر، مهاجرت‌ها و سرو پنل اثبات شود.

## آنچه workflow انجام می‌دهد

۱. نصب وابستگی‌ها روی `windows-latest`
۲. sanity-check اینکه `app.main` import می‌شود
۳. اجرای کل سوئیت تست
۴. بسته‌بندی با PyInstaller (`installer/windows/app.spec`)
۵. **boot واقعی فایل اجرایی** و اطمینان از اینکه پنل را سرو می‌کند
   (اگر بالا نیاید، build شکست می‌خورد — نه اینکه بی‌صدا رد شود)
۶. ساخت `SupermarketSystem-Setup-<version>.exe` با Inno Setup
۷. محاسبهٔ SHA256 و پیوست به Release
۸. job جداگانهٔ لینوکس: ساخت، بوت واقعی، tar.gz + checksum

## ساخت دستی روی ویندوز

دو نقطهٔ ورود، **یک موتور مشترک** (`builder-lib.ps1`):

| فایل | رفتار |
|---|---|
| `ساخت-فایل-نصب.bat` (ریشهٔ پروژه) | → `installer\windows\BUILD-SETUP.bat` |
| `installer\windows\BUILD-SETUP.bat` | **توصیه‌شده.** کنسول، بدون WPF، خطاها را چاپ می‌کند |
| `installer\windows\BUILD-SETUP-GUI.bat` | همان موتور، با پنجرهٔ گرافیکی و نوار پیشرفت |
| `installer\windows\build.ps1` | همان موتور از خط فرمان؛ `-NoDownload` دانلود خودکار را خاموش می‌کند |

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File installer\windows\build.ps1
```

خروجی‌ها:

```
installer\windows\dist\SupermarketSystem.exe
installer\output\SupermarketSystem-<version>-portable.exe   ← همیشه ساخته می‌شود
installer\output\SupermarketSystem-Setup-<version>.exe      ← نیازمند Inno Setup 6
```

پیش‌نیازها: Python 3.11+ و [Inno Setup 6](https://jrsoftware.org/isdl.php).
جزئیات در `docs/BUILD.md`.

## وضعیت تست‌شدگی (صادقانه)

| مورد | وضعیت |
|------|-------|
| منطق لانچر، مسیر دادهٔ کاربر، health-probe | ✅ تست‌شده (build فریزشدهٔ لینوکس، boot واقعی) |
| مهاجرت پایگاه‌داده در حالت فریزشده | ✅ تست‌شده |
| `/m` روی موبایل بدون اسلش پایانی | ✅ تست‌شده — ۳۰۷ به `/m/` |
| اسکن بارکد + ذخیرهٔ تصویر در build فریزشده | ✅ تست‌شده |
| سوئیت تست کامل | ✅ ۲۲۸ آزمون روی لینوکس |
| اجرای `build.ps1` / `builder-lib.ps1` روی ویندوز | ⏳ NOT VERIFIED — محیط توسعه لینوکس است و PowerShell در آن نیست؛ کد بازبینی ایستا شد |
| بسته‌بندی PyInstaller روی ویندوز | ⏳ روی runner ویندوز اجرا می‌شود |
| اجرای Setup.exe روی ویندوز واقعی | ⏳ نیازمند تست دستی روی دستگاه فیزیکی |
