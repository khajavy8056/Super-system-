# ساخت فایل نصبی ویندوز — راهنمای گام‌به‌گام

> **خلاصهٔ یک‌خطی:** کل مخزن را دانلود کنید (Code → Download ZIP یا clone)،
> وارد پوشهٔ `installer\windows` شوید و روی **`BUILD-SETUP.bat` دابل‌کلیک کنید.**
> همین!

## پیش‌نیازها

| پیش‌نیاز | الزام | توضیح |
|---|---|---|
| ویندوز | 10 یا 11 | 64-bit |
| **Python** | 3.9+ (پیشنهادی 3.11+) | از [python.org](https://www.python.org/downloads/) نصب کنید و حتماً تیک **«Add python.exe to PATH»** را موقع نصب بزنید |
| **Inno Setup 6** | *اختیاری* | فقط برای ساخت `Setup.exe` کلاسیک — از [jrsoftware.org](https://jrsoftware.org/isdl.php). اگر نباشد، خروجی **Portable** (تک‌فایل اجرایی بدون نیاز به نصب) ساخته می‌شود |

اتصال اینترنت برای بار اول لازم است (نصب وابستگی‌ها).

## خروجی‌ها

| فایل | مسیر | توضیح |
|---|---|---|
| `SupermarketSystem-Setup-0.4.0.exe` | `installer\output\` | نصب‌کنندهٔ کلاسیک (نیاز به Inno Setup) |
| `SupermarketSystem-0.4.0-portable.exe` | `installer\output\` | تک‌فایل قابل اجرا بدون نصب — همیشه ساخته می‌شود |
| `SupermarketSystem.exe` | `installer\windows\dist\` | همان فایل portable قبل از کپی |
| `build.log` | `installer\windows\` | لاگ کامل ساخت |

**داده‌های برنامه** (دیتابیس، لاگ‌ها، کلید) در `%USERPROFILE%\SupermarketSystem`
ساخته می‌شوند — حذف یا به‌روزرسانی برنامه آن‌ها را پاک نمی‌کند.

## ساخت پشت‌صحنهٔ BUILD-SETUP.bat چه می‌کند؟

1. **بررسی کامل بودن مخزن** — وجود ۱۰ فایل حیاتی (backend، frontend، spec، icon و…).
2. پیدا کردن Python (از PATH یا `py` launcher) + بررسی نسخه.
3. ساخت venv در `backend\.venv` و نصب `requirements.txt` + PyInstaller.
4. ساخت اجرایی تک‌فایل با PyInstaller (`app.spec`) — صحت ساخت چک می‌شود.
5. کپی خروجی Portable به `installer\output\`.
6. اگر Inno Setup 6 نصب باشد: ساخت `Setup.exe` با `setup.iss` — و صحت فایل چک می‌شود.

هر مرحله اگر شکست بخورد، **دلیل دقیق و قابل‌اقدام** چاپ و با کد 1 خارج می‌شود؛
لاگ کامل در `build.log` هست.

## عیب‌یابی خطاهای رایج

| خطا / علامت | ریشه | راه‌حل |
|---|---|---|
| `project files are missing` / «فایل‌های پروژه نبوده» | مخزن ناقص کپی شده — BUILD-SETUP.bat بیرون از مخزن اجرا شده | کل مخزن را دانلود کنید (Code → Download ZIP از شاخهٔ درست) و فایل را جابه‌جا نکنید |
| خطاهای «کامپایلری» با شمارهٔ خطوط مختلف + کد 1 | نسخهٔ قدیمی/شاخهٔ اشتباه پروژه (فایل‌های builder قدیمی) | از شاخهٔ به‌روزشده بسازید؛ فایل‌های سازندهٔ قدیمی (`builder-gui.ps1` و…) حذف شده‌اند و جای آن‌ها `BUILD-SETUP.bat` + `build.ps1` ساده و تست‌شده است |
| `Python not found` | پایتون نصب نیست یا در PATH نیست | python.org → نصب با تیک «Add python.exe to PATH» → دوباره اجرا |
| پنجره بسته می‌شود و چیزی نمی‌بینید | اجرای مستقیم ps1 بدون کنسول | از `BUILD-SETUP.bat` اجرا کنید (خودش کنسول را نگه می‌دارد) |
| `Inno Setup 6 not found` | Inno نصب نیست | لازم نیست! Portable ساخته شده؛ برای Setup.exe آن را نصب کنید و دوباره بیلد بگیرید |
| SmartScreen هنگام اجرای exe | فایل امضای دیجیتال ندارد (عادی است) | More info → Run anyway |
| آنتی‌ویروس exe را می‌گیرد | PyInstaller onefile گاهی false-positive می‌دهد | استثنا گذاشتن یا استفاده از نسخهٔ portable در پوشهٔ خود پروژه |

## اجرای دستی (بدون فایل bat)

```powershell
cd installer\windows
powershell -NoProfile -ExecutionPolicy Bypass -File build.ps1
```

## اجرای برنامه بدون ساخت نصب‌کننده (توسعه)

```powershell
cd backend
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python ..\installer\windows\run_supermarket.py
```

مرورگر بعد از آماده‌شدن سرور (`/health` = 200) خودش باز می‌شود.
ورود پیش‌فرض: `admin` / `admin123` (در اولین اجرا عوض کنید).

## وضعیت تست‌شدگی (شفافیت کامل)

- منطق لانچرِ frozen (همان `run_supermarket.py`) روی لینوکس با cx_Freeze بیلد و
  **به‌صورت کامل بوت‌تست شده**: health 200، ورود JWT، سرو پنل/موبایل، ساخت DB
  با ۲۹ جدول، پایداری کلید بین ری‌استارت‌ها (جزئیات: `docs/BUILD.md`).
- ساختِ PyInstaller روی ویندوز + Setup.exeٔ Inno: اسکریپت‌ها ساده و دفاعی
  نوشته شده‌اند اما چون sandbox ویندوز ندارد، **UNTESTED روی ویندوز واقعی** ثبت
  شده — به همین دلیل هر مرحله خروجی‌اش چک می‌شود و پیام خطا دقیق می‌دهد.
