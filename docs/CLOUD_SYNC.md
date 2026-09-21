# همگام‌سازی اینترنتی اختیاری — Google Drive (v1.7)

**پیش‌فرض: خاموش.** همه‌چیز بدون آن روی LAN کار می‌کند (§ local-first). این ویژگی فقط برای وقتی است که گوشی و رایانه روی یک شبکه نیستند (مثلاً سفارش/شمارش بیرون از فروشگاه).

## اصول
- فقط اسکوپ `https://www.googleapis.com/auth/drive.appdata` (پوشهٔ خصوصی برنامه؛ برنامه هیچ فایل دیگری از Drive را نمی‌بیند).
- اتصال با **OAuth 2.0 Device Authorization Flow**: تنظیمات → «همگام‌سازی ابری» → Client ID/Secret برنامهٔ خودتان (ساخته‌شده در Google Cloud Console، نوع «TVs and Limited Input devices») → کد کوتاه را در `google.com/device` وارد کنید. Refresh token در `system_settings` (کلید `cloud.refresh_token`, محرمانه) ذخیره می‌شود.
- هیچ سرویس پولی/حساب اجباری: حساب Google رایگان و اختیاری است؛ URLهای Google با کلیدهای `cloud.device_url/token_url/api_url/upload_url/userinfo_url` قابل بازنویسی‌اند (برای تست یا سرویس سازگار).

## مدل داده در Drive (appDataFolder)
| فایل | تولیدکننده | محتوا |
|---|---|---|
| `snapshot.json` | رایانه | کالاها/بچ‌ها/مشتری‌ها/واحدها (نسخهٔ سبک برای گوشی) + `generated_at` |
| `ops-<device_id>-<ts>.json` | گوشی | فهرست عملیات آفلاین `{id,type,payload}` — همان فرمت `POST /api/mobile/sync` |
| `backup-latest.db` | رایانه | آخرین بکاپ SQLite (`routers.system.backup`) |

## چرخه
1. **رایانه** (`services/cloud.py: sync_now`, worker هر ۵ دقیقه؛ اولین اجرا با تأخیر یک بازه): فایل‌های `ops-*` را دانلود → هر عملیات را با `routers.mobile._apply` اعمال (idempotent؛ کلید `SyncJob mob:{op.id}`) → فایل را حذف → `snapshot.json` (و در «همگام‌سازی اکنون» بکاپ) را بالا می‌گذارد. `cloud.last_sync_at / last_error / applied_total` در status.
2. **گوشی** (`app.js: cloudSync`): وقتی رایانه در دسترس نیست و در QR جفت‌سازی (`v:2`, فیلد `cloud`) اعتبارنامه آمده باشد: access token با refresh token می‌گیرد، صف `ops` را به‌عنوان `ops-<device>-<ts>.json` بالا می‌گذارد و `snapshot.json` را می‌گیرد (`m_cloud_snap`). تعارض‌ها بعداً در همگام‌سازی LAN با پیام سرور دیده می‌شوند.

## API
- `GET /api/cloud/status` → `{enabled, connected, account, last_sync_at, last_error, applied_total}`
- `POST /api/cloud/connect/start {client_id, client_secret}` → `{user_code, verification_url, interval, expires_in}`
- `POST /api/cloud/connect/poll` → `{status: PENDING|CONNECTED, account}`
- `POST /api/cloud/sync-now` — `POST /api/cloud/disconnect` — `GET /api/cloud/device-credentials` (برای QR)
خطاها: `400 {code, message}` فارسی.

## وضعیت آزمون (§57)
`backend/tests/test_v1_7_cloud.py` (۳ تست) با سرور Drive/OAuth شبیه‌سازی‌شده (`HTTPServer` محلی): device flow → connected، push/pull/apply idempotent، disconnect. اتصال به حساب Google واقعی: **NOT VERIFIED** در سندباکس.
