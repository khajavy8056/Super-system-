# ساخت و انتشار فایل‌های Release

این workflow **هر دو** خروجی را می‌سازد و به Release پیوست می‌کند:
`SupermarketSystem-Setup-0.2.0.exe` (ویندوز) و
`SupermarketSystem-0.2.0-linux-x86_64.tar.gz` (لینوکس).

## چرا این فایل اینجاست و نه در `.github/workflows/`

توکن رباتی که این تغییرات را ثبت کرده مجوز `workflows` ندارد و GitHub اجازهٔ
push روی مسیر `.github/workflows/` را نمی‌دهد. فایل آمادهٔ استفاده است و فقط
باید یک‌بار توسط شما جابه‌جا شود:

```bash
mkdir -p .github/workflows
git mv installer/ci/release-windows.yml .github/workflows/release-windows.yml
git commit -m "ci: add the Windows installer workflow"
git push
```

سپس در تب **Actions** گزینهٔ «Build and publish release assets» را با
`tag = v0.2.0` اجرا کنید (یا یک تگ `v*` جدید push کنید). خروجی‌ها به‌صورت
خودکار به همان Release پیوست می‌شوند.

## چرا فایل‌ها از محیط توسعه آپلود نشدند

دو دلیل مستقل:

۱. **دسترسی شبکه**: آن محیط به `uploads.github.com` دسترسی ندارد (خارج از
   allowlist). ساخت Release و ویرایش آن از طریق `api.github.com` کار کرد،
   اما آپلود فایل از اساس ممکن نبود.
۲. **ناسازگاری سکو**: (ادامه در پایین)

## چرا Setup.exe در این محیط ساخته نشد

محیط توسعه لینوکس است. PyInstaller **کراس‌کامپایل نمی‌کند** و Inno Setup هم
ابزار ویندوزی است. بنابراین تولید یک فایل `.exe` در اینجا یا غیرممکن است یا
نتیجه‌ای تست‌نشده به دست می‌دهد؛ طبق قاعدهٔ «هیچ چیز تست‌نشده‌ای production-ready
گزارش نمی‌شود»، به‌جای آن مسیر ساخت روی سخت‌افزار واقعی ویندوز تعریف شده است.

## آنچه workflow انجام می‌دهد

۱. نصب وابستگی‌ها روی `windows-latest`
۲. اجرای کل سوئیت تست
۳. بسته‌بندی با PyInstaller (`installer/windows/app.spec`)
۴. **boot واقعی فایل اجرایی** و اطمینان از اینکه پنل را سرو می‌کند
   (اگر بالا نیاید، build شکست می‌خورد — نه اینکه بی‌صدا رد شود)
۵. ساخت `SupermarketSystem-Setup-0.2.0.exe` با Inno Setup
۶. محاسبهٔ SHA256 و پیوست به Release

## ساخت دستی روی ویندوز

```powershell
powershell -ExecutionPolicy Bypass -File installer\windows\build.ps1
```

پیش‌نیازها: Python 3.11+ و [Inno Setup 6](https://jrsoftware.org/isdl.php).
جزئیات در `docs/BUILD.md`.

## وضعیت تست‌شدگی (صادقانه)

| مورد | وضعیت |
|------|-------|
| منطق لانچر، مسیر دادهٔ کاربر، health-probe | ✅ تست‌شده (build فریزشدهٔ لینوکس، boot واقعی) |
| مهاجرت پایگاه‌داده در حالت فریزشده | ✅ تست‌شده — `a1c93f4d7e10` مهر خورد |
| `/m` روی موبایل بدون اسلش پایانی | ✅ تست‌شده — ۳۰۷ به `/m/` |
| اسکن بارکد + ذخیرهٔ تصویر در build فریزشده | ✅ تست‌شده — ۴ فیلد + PNG ۴۰۰×۴۰۰ |
| بسته‌بندی PyInstaller روی ویندوز | ⏳ روی runner ویندوز اجرا می‌شود |
| اجرای Setup.exe روی ویندوز واقعی | ⏳ نیازمند تست دستی روی دستگاه فیزیکی |
