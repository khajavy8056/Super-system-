# به‌روزرسانی سامانه (§266–§276, §331)

> صداقت (§57): منطق کامل و با `tests/test_phase9_update.py` + `test_update_server_channel_check_and_checksum`
> (سرور شبیه‌ساز + بستهٔ واقعی + SHA-256) تأیید شده. دانلود زندهٔ GitHub و اجرای Setup روی ویندوز → **NOT VERIFIED**.

## ۱. کانال‌ها (`update.channel`)

| کانال | منبع | پیکربندی |
|---|---|---|
| `github` (پیش‌فرض) | آخرین Release مخزن؛ asset `SupermarketSystem-Setup-<ver>.exe` + فایل `SHA256SUMS*` | بدون تنظیم |
| `server` | سرور داخلی فروشگاه/شرکت: `GET update.server_url` → JSON | `update.server_url`, `update.server_token` (اختیاری، Bearer) |

قرارداد JSON سرور:
```json
{"version":"1.2.0","name":"v1.2.0","notes":"...","published_at":"2026-09-06T12:00:00Z",
 "asset_name":"SupermarketSystem-Setup-1.2.0.exe","asset_url":"https://updates.example.ir/1.2.0/Setup.exe",
 "asset_size":41234567,"sha256":"<hex>"}
```

## ۲. جریان امن (`services/updater.py::prepare_update`)

```
1 بررسی نسخه (check_for_update)              → UP_TO_DATE | نسخهٔ جدید
2 تأیید مدیر: رمز مدیر الزامی (§209, §272)   → 401 ADMIN_PASSWORD_REQUIRED
3 پشتیبان‌گیری پایگاه‌داده (SQLite online backup) → شکست ⇒ ABORTED (هیچ تغییری)
4 دانلود بسته (stream, follow redirects)      → updates/<asset_name>
5 اعتبارسنجی: اندازه + SHA-256 + امضای PE (MZ) → شکست ⇒ FAILED و حذف فایل
6 آماده (PREPARED): مسیر Setup برای اجرا     → اجرای نصب توسط مدیر؛ داده‌ها در %USERPROFILE%\SupermarketSystem می‌مانند
7 پس از نصب: Alembic migration افزودنی (§274) ; Rollback = بازگردانی backup از تنظیمات ← پشتیبان‌گیری (§276)
```

هر مرحله در `UpdatePlan.steps` و Audit (`UPDATE_CHECK`, `UPDATE_PREPARED`, `UPDATE_FAILED`, `UPDATE_ABORTED`) ثبت می‌شود.

## ۳. API

| مسیر | توضیح |
|---|---|
| `GET /api/system/update/check` | فقط‌خواندنی؛ `status`: `UP_TO_DATE`/`UPDATE_AVAILABLE`/`UNAVAILABLE`/`CONFIG_MISSING`، فیلد `channel` |
| `POST /api/system/update/prepare` | `{password, download}` → پلن مرحله‌ای |
| `GET /api/system/backups`, `POST /backup`, `POST /restore` | پشتیبان/بازگردانی اعتبارسنجی‌شده |

## ۴. انتشار نسخهٔ جدید (Release Engineer)

1. `__version__` در `backend/app/__init__.py` (منبع واحد نسخه برای installer، APK و About).
2. `CHANGELOG.md` + `docs/FEATURE_CHECKLIST_350.md`.
3. `git tag vX.Y.Z && git push --tags` → workflow `release-windows.yml` (Setup.exe + `.sha256`) و
   `release-android.yml` (APK) روی GitHub Actions اجرا و به Release ضمیمه می‌شوند
   (فعال‌سازی یک‌باره: `scripts/activate-ci.sh`).
4. فایل `SHA256SUMS.txt` را کنار asset بگذارید؛ کلاینت آن را برای تطبیق می‌خواند.
