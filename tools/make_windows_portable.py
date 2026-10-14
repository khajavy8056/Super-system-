# -*- coding: utf-8 -*-
"""build-511 — بستهٔ پرتابل ویندوز: پایانِ «برای به‌روزرسانی باید Setup بسازی».

تا حالا تنها دارایی ویندوزی Releaseها، «رونویسی UI» بود؛ یعنی بک‌اندِ نصب‌شدهٔ
کاربر هرگز به‌روز نمی‌شد و امکان‌های تازه (پرفروش‌ها، جشنواره‌ها، کوپن خرید
بعدی) هرگز اجرا نمی‌شدند. این بسته **کل سیستم فعلی** (بک‌اند + رابط نیتیو Qt +
سرور همگام‌سازی اندروید) را می‌دهد و RUN.bat در اولین اجرا فقط یک بار محیط
پایتونِ خودش را روی سیستم کاربر می‌سازد (نیازمند اینترنت، از PyPI رسمی).

خروجی: releases/windows/RasaSystem-Windows-Portable-<ver>.zip
"""
from __future__ import annotations

import hashlib
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "releases/windows"

RUN_BAT = r"""@echo off
REM ============================================================================
REM  Rasa System - PORTABLE RUNNER (one click)
REM  First run: creates a local Python environment (needs internet, from PyPI).
REM  Then: starts the native Qt desktop app + local sync server for Android.
REM  Your data lives in %USERPROFILE%\RasaSystem and is never touched by this file.
REM ============================================================================
setlocal EnableExtensions
cd /d "%~dp0"

set "PY="
py -3.12 -c "import sys" >nul 2>nul && set "PY=py -3.12"
if not defined PY py -3.11 -c "import sys" >nul 2>nul && set "PY=py -3.11"
if not defined PY py -3.13 -c "import sys" >nul 2>nul && set "PY=py -3.13"
if not defined PY python -c "import sys" >nul 2>nul && set "PY=python"
if not defined PY (
  echo Python 3.11+ was not found on this PC.
  echo Install it once with:   winget install -e --id Python.Python.3.12
  echo or download from:       https://www.python.org/downloads/
  echo (check "Add python.exe to PATH" in the installer), then run this file again.
  start "" "https://www.python.org/downloads/"
  pause
  exit /b 1
)

if not exist ".venv-local\Scripts\python.exe" (
  echo First run: preparing the local environment ^(2-3 minutes, needs internet^)...
  %PY% -m venv .venv-local
  if errorlevel 1 ( echo Could not create the environment. & pause & exit /b 1 )
  ".venv-local\Scripts\python.exe" -m pip install --upgrade pip -q
  ".venv-local\Scripts\python.exe" -m pip install -q -r "backend\requirements.txt" -r "backend\requirements-desktop.txt"
  if errorlevel 1 (
    echo Installation failed - check your internet connection and run again.
    pause
    exit /b 1
  )
  echo Environment is ready.
)

echo Starting Rasa System ...
".venv-local\Scripts\python.exe" "installer\windows\run_supermarket.py"
if errorlevel 1 pause
"""

README_FA = """# رسا سیستم — بستهٔ پرتابل ویندوز (نسخهٔ {version} · بیلد {build})

این بسته **کل برنامهٔ فعلی** است: بک‌اند + رابط دسکتاپ نیتیو (بدون مرورگر، بدون کش وب) + سرورِ همگام‌سازی برای اپ اندروید.

## اجرا — فقط دو قدم
۱. کل ZIP را در یک پوشهٔ دائمی استخراج کنید (مثلاً `C:\\RasaSystem`).
۲. **RUN.bat** را دوبار کلیک کنید.

- اجرای اول: محیط پایتونِ خودش را می‌سازد (۲ تا ۳ دقیقه، اینترنت لازم دارد). اگر پایتون نصب نباشد، خودش راهنمایی و صفحهٔ دانلود را باز می‌کند — یک بار `Python 3.12` را نصب کنید و دوباره RUN.bat را بزنید.
- از اجرای دوم به بعد: مستقیم بالا می‌آید.
- اطلاعات شما در پوشهٔ `RasaSystem` داخل پوشهٔ کاربری ویندوز ذخیره می‌شود؛ اگر نسخهٔ قبلی (`SupermarketSystem`) را داشته باشید، همان‌جا در جای خودش برداشته می‌شود و چیزی از دست نمی‌رود.

## چرا این بسته؟
تا نسخه‌های قبل، تنها فایل ویندوزیِ انتشار، «رونویسی ظاهر» بود و بک‌اندِ نصب‌شده به‌روز نمی‌شد؛ برای همین امکان‌های تازه (نوار پرفروش‌ها، جشنواره‌ها، کوپن خرید بعدی) دیده نمی‌شدند. این بسته بک‌اند و رابط را **با هم** به آخرین نسخه می‌رساند.

## اندروید
اپ گوشی (APK همین نسخه) را نصب کنید و در حالت جفت‌سازی، به همین کامپیوتر وصل شود؛ آدرس/بارکد جفت‌سازی داخل برنامه نمایش داده می‌شود.

## به‌روزرسانی بعدی
ZIP نسخهٔ جدید را در همان پوشه استخراج کنید (روی قبلی) — پوشهٔ `.venv-local` و اطلاعات دست‌نخورده می‌مانند.
"""


def build(version: str) -> Path:
    build_no = int(version.split(".")[2]) * 100
    OUT.mkdir(parents=True, exist_ok=True)
    out = OUT / f"RasaSystem-Windows-Portable-{version}.zip"
    include = [
        ("desktop", "desktop"),
        ("backend/app", "backend/app"),
        ("backend/alembic", "backend/alembic"),
        ("backend/requirements.txt", "backend/requirements.txt"),
        ("backend/requirements-desktop.txt", "backend/requirements-desktop.txt"),
        ("frontend", "frontend"),
        ("installer/windows", "installer/windows"),
        ("tools/windows-ui", "tools/windows-ui"),
    ]
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for src, arc in include:
            p = ROOT / src
            if p.is_file():
                z.write(p, arc)
                continue
            for f in sorted(p.rglob("*")):
                if f.is_file() and "__pycache__" not in str(f):
                    z.write(f, f"{arc}/{f.relative_to(p)}".replace("\\", "/"))
        z.writestr("RUN.bat", RUN_BAT.replace("\n", "\r\n"))
        z.writestr("README-WINDOWS.fa.md", README_FA.format(version=version, build=build_no))
    digest = hashlib.sha256(out.read_bytes()).hexdigest()
    out.with_suffix(".zip.sha256").write_text(digest + "  " + out.name + "\n")
    print(out, f"{out.stat().st_size:,} bytes", digest)
    return out


if __name__ == "__main__":
    if len(sys.argv) > 1:
        build(sys.argv[1])
    else:
        sys.path.insert(0, str(ROOT / "backend"))
        import app as _app
        build(_app.__version__)
