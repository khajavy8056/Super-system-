@echo off
chcp 65001 >nul
setlocal EnableExtensions EnableDelayedExpansion

REM ============================================================================
REM  ساخت فایل بکاپ پرفشار — یک سال فروشگاه بزرگ و شلوغ
REM  Stress-backup builder: a full year of a big, busy supermarket.
REM
REM  چه چیزی می‌سازد:
REM    * کل کاتالوگ پیش‌فرض (۱۳٬۵۷۰ کالا، همهٔ بارکدها)
REM    * به‌طور میانگین یک فاکتور هر ۱۰ دقیقه برای یک سال (~۵۲٬۵۶۰ فاکتور)
REM    * ورودی/بچ/حرکت موجودی برای همهٔ کالاها، از ۱۵ تأمین‌کننده
REM    * چک صادره و وصول‌شده، هزینه، مرجوعی، ابطال، فروش نسیه
REM    * اجرای مدل هوش روی سالِ کامل، اجرای پیشنهادها و سنجش اثرشان
REM
REM  حجم فایل هرچه باشد مشکلی ندارد — هدف فشار روی دیتاست.
REM  نوار پیشرفت واقعی است؛ با پایان آن فایل آماده است.
REM
REM  استفاده:
REM    make-stress-backup.bat                    ساخت کامل یک‌ساله
REM    make-stress-backup.bat --smoke            تست سریع ۳۰ روزه
REM    make-stress-backup.bat --out D:\stress.db.gz
REM    make-stress-backup.bat --days 365 --per-day 144
REM    make-stress-backup.bat --python C:\Python312\python.exe   اجبار به استفاده از یک پایتون مشخص
REM  هر آرگومان دیگری مستقیم به اسکریپت پایتون پاس داده می‌شود.
REM ============================================================================

set "SCRIPT_DIR=%~dp0"
if "%SCRIPT_DIR:~-1%"=="\" set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"

REM ---- locate the backend package -----------------------------------------
set "BACKEND=%SCRIPT_DIR%\backend"
if not exist "%BACKEND%\app\main.py" set "BACKEND=%SCRIPT_DIR%\..\backend"
if not exist "%BACKEND%\app\main.py" (
  echo [خطا] پوشهٔ backend پیدا نشد.
  echo       این فایل باید داخل پوشهٔ پروژه باشد ^(کنار پوشهٔ backend^).
  echo       مسیر فعلی: %SCRIPT_DIR%
  pause
  exit /b 1
)
set "PYTHONPATH=%BACKEND%;%PYTHONPATH%"

REM ---- find a Python 3.9+ --------------------------------------------------
set "PY="
if exist "%BACKEND%\.venv\Scripts\python.exe" set "PY=%BACKEND%\.venv\Scripts\python.exe"
if not defined PY if exist "%SCRIPT_DIR%\.venv\Scripts\python.exe" set "PY=%SCRIPT_DIR%\.venv\Scripts\python.exe"
if not defined PY (
  where py >nul 2>&1
  if not errorlevel 1 (
    py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3,9) else 1)" >nul 2>&1
    if not errorlevel 1 set "PY=py -3"
  )
)
if not defined PY (
  where python >nul 2>&1
  if not errorlevel 1 (
    python -c "import sys; sys.exit(0 if sys.version_info >= (3,9) else 1)" >nul 2>&1
    if not errorlevel 1 set "PY=python"
  )
)
if not defined PY (
  echo [خطا] پایتون ۳.۹ یا جدیدتر پیدا نشد.
  echo       پایتون را از https://python.org نصب کنید و تیک "Add to PATH" را بزنید.
  pause
  exit /b 1
)

REM ---- the build itself ----------------------------------------------------
echo.
echo پایتون: %PY%
echo بک‌اند: %BACKEND%
echo.
echo نکته: اگر کتابخانه‌های لازم نصب نباشند، خود برنامه یک بار آن‌ها را در
echo       پوشهٔ tools\.venv نصب می‌کند و بعد ساخت را شروع می‌کند. برای این کار
echo       به اینترنت نیاز دارد؛ بارهای بعدی بدون نصب اجرا می‌شود.
echo.

%PY% "%SCRIPT_DIR%\make_stress_backup.py" %*
set "RC=%ERRORLEVEL%"

echo.
if "%RC%"=="0" (
  echo فایل بکاپ آماده است.
) else if "%RC%"=="4" (
  echo ساخت انجام نشد: کتابخانه‌های لازم نصب نیستند و نصب خودکار هم ممکن نشد.
  echo دستورهای بالا را در CMD اجرا کنید و دوباره امتحان کنید.
) else (
  echo ساخت با کد %RC% ناموفق بود. متن خطا را در بالا ببینید.
)
echo.
pause
exit /b %RC%
