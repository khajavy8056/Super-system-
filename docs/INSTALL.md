# راهنمای نصب و اجرا

## ۱) اجرای توسعه (Linux / macOS / Windows)

پیش‌نیاز: Python 3.11+ و Git.

```bash
git clone <repo-url>
cd supermarket-system/backend
python -m venv .venv
# Linux/macOS:
source .venv/bin/activate
# Windows:
.venv\Scripts\activate

pip install -r requirements.txt
cp .env.example .env

# داده نمونه (اختیاری):
python -m scripts.seed_demo

uvicorn app.main:app --host 0.0.0.0 --port 8000
```

مرورگر → `http://localhost:8000`

ورود: `admin` / `admin123`

## ۲) نصب روی Windows (Setup.exe)

هدف نهایی: کاربر بدون نصب دستی Python/Node/runtime فقط `Setup.exe` را اجرا می‌کند.

### ساخت با PyInstaller + Inno Setup (روی ویندوز)

```powershell
cd installer\windows
.\build.ps1
```

خروجی: `installer\output\SupermarketSystem-Setup.exe`

اسکریپت `build.ps1`:
1. وابستگی‌های backend را نصب می‌کند.
2. با PyInstaller یک executable واحد می‌سازد (`run_supermarket.exe`).
3. با Inno Setup نصب‌کننده‌ای می‌سازد که:
   - فایل‌ها را در `Program Files` نصب می‌کند،
   - دیتابیس را در پوشه داده کاربر Initialize می‌کند،
   - میانبر روی دسکتاپ/منوی استارت می‌سازد،
   - سرویس پس‌زمینه و Uninstaller دارد.

### اجرای دستی بدون نصب‌کننده

```powershell
cd installer\windows
python run_supermarket.py
```

این اسکریپت backend را روی یک پورت آزاد اجرا کرده و مرورگر را باز می‌کند.

## ۳) پایگاه‌داده

- پیش‌فرض: SQLite در `backend/data/supermarket.db` (حالت WAL برای POS).
- مهاجرت: `alembic upgrade head`.
- برای سرور مرکزی: `DATABASE_URL=postgresql+psycopg://...` در `.env`.

## ۴) Backup / Restore

```bash
curl -X POST http://localhost:8000/api/backup -H "Authorization: Bearer $TOKEN"
```

فایل‌ها در `backend/data/backups/` (روش backup آنلاین sqlite3، نه کپی خام).

## ۵) عیب‌یابی

| مشکل | راه‌حل |
|---|---|
| `ModuleNotFoundError` | مطمئن شوید در `backend/` هستید و venv فعال است |
| 401 در API | token منقضی — دوباره لاگین کنید |
| 403 Missing permission | نقش کاربر مجوز لازم را ندارد |
| پرینتر OFFLINE | در بخش سخت‌افزار دستگاه PRINTER ثبت/فعال کنید |
