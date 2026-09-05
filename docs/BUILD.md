# Build & Packaging — فاز ۶ (v0.4.0)

این سند روش رسمی ساخت بسته‌های نصبی و وضعیت تست‌شدگی هر مسیر را شرح می‌دهد.
اصل پروژه (Master Prompt): هر مسیری که در sandbox قابل تست نبوده، صادقانه
**UNTESTED** علامت می‌خورد؛ ادعای غیرواقعی ممنوع.

## معماری بسته نصبی

```
installer/
├── windows/
│   ├── run_supermarket.py   ← لانچر مشترک (frozen و dev) — منطق یکسان
│   ├── app.spec             ← spec پکی‌جینگ PyInstaller (onefile)
│   ├── setup.iss            ← اسکریپت Inno Setup (Setup.exe ویندوزی)
│   ├── BUILD-SETUP.bat      ← ورودی یک‌کلیک (دابل‌کلیک = ساخت نصب‌کننده)
│   ├── build.ps1            ← اسکریپت ساخت واقعی (پیش‌پرواز + چک هر مرحله)
│   ├── README.md            ← راهنمای فارسی + عیب‌یابی
│   └── icon.ico             ← آیکون (ساخته‌شده از frontend/icons/icon-512.png)
└── standalone/
    └── setup.py             ← بیلد cx_Freeze (برای تست frozen در لینوکس)
```

**لانچر (`run_supermarket.py`) — رفتار:**
- پورت آزاد تصادفی روی `127.0.0.1` انتخاب می‌کند (بدون تداخل با IIS/سرویس‌های دیگر).
- دادهٔ کاربر در `%USERPROFILE%\SupermarketSystem` (لینوکس: `~/SupermarketSystem`):
  `supermarket.db` + `logs/supermarket.log` + `secret.key`.
  حذف/به‌روزرسانی برنامه داده را پاک **نمی‌کند**.
- `SECRET_KEY` اگر در محیط نباشد، یک‌بار تولید و در `secret.key` ذخیره می‌شود →
  توکن‌های JWT پس از ری‌استارت معتبر می‌مانند (ریشه‌ای، نه وصله).
- مرورگر فقط بعد از پاسخ 200 از `/health` باز می‌شود (آماده‌به‌کار واقعی، نه فقط TCP).
- در حالت frozen، `ENVIRONMENT=production` پیش‌فرض می‌شود.

## مسیر ویندوز (Setup.exe) — آماده، ساخت در sandbox ممکن نبود

روی ویندوز 10/11 با Python 3.11+:

ساده‌ترین راه: دابل‌کلیک روی `installer\windows\BUILD-SETUP.bat`
(یا از خط فرمان: `powershell -NoProfile -ExecutionPolicy Bypass -File build.ps1`)

خروجی:
- `installer\output\SupermarketSystem-0.4.0-portable.exe` (همیشه — بدون نیاز به Inno)
- `installer\output\SupermarketSystem-Setup-0.4.0.exe` (اگر Inno Setup 6 نصب باشد)

مراحل build.ps1: (1) venv + نصب `requirements.txt` و pyinstaller،
(2) `pyinstaller --clean app.spec` → onefile با frontend و icon،
(3) `ISCC setup.iss` → Setup.exe با Start-Menu/Desktop shortcut،
حذف امن (دیتای کاربر دست‌نخورده) و اجرای پس از نصب.

> **UNTESTED (ویندوز واقعی):** sandbox لینوکسی است؛ بیلد PyInstaller ویندوزی،
> امضای دیجیتال، SmartScreen و رفتار Inno Setup در ویندوز **آزمایش نشده**.
> spec/اسکریپت‌ها برای کاهش ریسک بررسی syntax و منطق شده‌اند و لانچرِ مشترک
> به‌صورت frozen در لینوکس boot-test کامل شده (بند بعد).

## مسیر لینوکس (تست‌شده در sandbox) — cx_Freeze

چرا cx_Freeze؟ پایتون sandbox استاتیک است (بدون `libpython3.11.so.1.0`) و
`apt` شکسته؛ PyInstaller به libpython مشترک نیاز دارد، cx_Freeze نداشت.

```bash
cd installer/standalone
../../backend/.venv/bin/python setup.py build
# خروجی: build/exe.linux-x86_64-3.11/SupermarketSystem
```

**نتیجهٔ Boot-Test واقعی (2026-09-04، HOME جدا: `/tmp/fz-home`):**

| بررسی | نتیجه |
|---|---|
| بوت frozen، پورت تصادفی | ✅ `/health` = 200 در ~۳ ثانیه |
| ورود admin (فارغ از دیتای dev) | ✅ JWT صادر شد |
| پنل `/` و موبایل `/mobile/` و manifest | ✅ هر سه 200 (frontend باندل شده) |
| API واقعی (`/api/products`) | ✅ پاسخ JSON (دیتابیس خالی جدید: درست) |
| دیتای کاربر | ✅ `supermarket.db` با 29 جدول + bootstrap admin، `logs/`، `secret.key` |
| ری‌استارت دوم | ✅ health 200، ورود مجدد OK، `secret.key` بدون تغییر (توکن‌ها پایدار) |
| اجرای همان لانچر در حالت dev (غیر frozen) | ✅ health 200 |

نکتهٔ ریشه‌ای که در همین تست پیدا و رفع شد: SQLAlchemy دیالکت sqlite را از
entry-point ها لود می‌کند → در frozen باید `sqlalchemy.dialects.sqlite` صریحاً
باندل شود (در `setup.py` آمده).

## اسکرین‌شات‌ها (خروجی واقعی از UI)

`scripts/shoot.py` با PySide6 WebEngine کاملاً offscreen (بدون X/GPU) صفحات
واقعی سرور را رندر و در `docs/screenshots/` ذخیره می‌کند (توضیح کامل و
پیش‌نیاز stublibs: `scripts/make_qt_stublibs.py`). خروجی فعلی: 21 تصویر PNG
از همهٔ بخش‌ها + PDF گزارش‌ها/موبایل — شرح فارسی هر بخش: `docs/SCREENSHOTS.md`.
