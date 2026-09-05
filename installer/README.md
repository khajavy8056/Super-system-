# Windows Installer

هدف (بخش 113–116 بلوپرینت): کاربر `Setup.exe` را اجرا کند و بدون نصب دستی
Python/Node/runtime، برنامه آماده باشد.

## ساخت

روی ویندوز (با Python 3.11+ و Inno Setup 6):

```powershell
cd installer\windows
.\build.ps1
```

خروجی: `installer\output\SupermarketSystem-Setup-0.2.0.exe`

مراحل:
1. وابستگی‌های backend نصب می‌شود.
2. `pyinstaller app.spec` یک executable واحد (`SupermarketSystem.exe`) می‌سازد
   که frontend را داخل خودش دارد.
3. `setup.iss` با Inno Setup نصب‌کننده می‌سازد (فایل‌ها + میانبر + uninstaller).

## رفتار پس از نصب

- دیتابیس در `%USERPROFILE%\SupermarketSystem\supermarket.db` ساخته می‌شود
  (بیرون از پوشه نصب، تا آپدیت داده را پاک نکند — بخش 116).
- اجرای برنامه → backend محلی → باز شدن مرورگر روی پنل وب.

## یادداشت‌ها

- `console=True` در spec برای دیباگ؛ برای اپلیکیشن بی‌صدا آن را `False` کنید.
- در نسخه فعلی hardware/drivers واقعی (ESC/POS ویندوز، درگاه سریال کشو) هنوز
  در لایه انتزاعی قرار دارند؛ اتصال واقعی در نسخه بعدی اضافه می‌شود (بخش 152:
  hardware بدون تست واقعی «تأییدشده» اعلام نمی‌شود).
