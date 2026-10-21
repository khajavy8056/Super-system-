# تداوم نسخه 1.0.523 — رفع رگرسیون ورود

این مدرک همگامی سه‌کانالهٔ نسخهٔ نصب‌شده را اثبات می‌کند.

| لایه | نسخه | منبع حقیقت |
|------|------|-------------|
| بک‌اند | **1.0.523 / BUILD 52300** | `backend/app/__init__.py: __version__, BUILD` |
| اندروید | **versionCode 52300 / versionName 1.0.523** | `mobile-android/BUILD` → `app/build.gradle` ↔ `backend/app/__init__.py` |
| ویندوز | **1.0.523** | `installer/windows/setup.iss: #define MyAppVersion` |
| APK | `RasaSystemMobile-1.0.523.apk` — 1,521,115 بایت — SHA-256 `b31a36a2c7d123dc6a61faacea3d3d88bcb5413b973bc64ccba4186c234cb6f9` — aapt2 `versionCode='52300' versionName='1.0.523'` | `installer/output/` + `releases/android/` |

رفع: `auth.py` پیام فارسی، `Api.java:errorFrom` حفظ پیام سرور برای 401/403/429، `main.py` حد ورود `30/60s`، `SetupActivity` PBKDF2.

ساخت: `scripts/android/build-apk.sh` با `/tmp/atools` (aapt2, ecj, d8, apksigner, android.jar 34) — 6/6 گام + preflight PASS + امضای CN=Khajavy Supermarket SHA-256 `18b4ab18…` (بایگانی `mobile-android/keystore/supery-release.jks`).

تأیید:
```bash
/tmp/atools/aapt2 dump badging releases/android/RasaSystemMobile-1.0.523.apk | grep version
# package: name='ir.khajavy.supermarket' versionCode='52300' versionName='1.0.523' ...
sha256sum releases/android/RasaSystemMobile-1.0.523.apk
# b31a36a2c7d123dc6a61faacea3d3d88bcb5413b973bc64ccba4186c234cb6f9
PYTHONPATH=backend pytest backend/tests/test_auth.py -v  # 4 passed
```
