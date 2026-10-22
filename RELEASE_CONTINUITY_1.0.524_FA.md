# تداوم نسخه 1.0.524 — بازگشت به پایهٔ ۱٫۰٫۵۲۱ و اجرای کامل ممیزی بدون رگرسیون

این مدرک همگامی سه‌کانالهٔ نسخهٔ نصب‌شده را اثبات می‌کند.

| لایه | نسخه | منبع حقیقت |
|------|------|-------------|
| بک‌اند | **1.0.524 / BUILD 52400** | `backend/app/__init__.py: __version__, BUILD` |
| اندروید | **versionCode 52400 / versionName 1.0.524** | `mobile-android/BUILD` → `scripts/android/build-apk.sh` ↔ `backend/app/__init__.py` |
| ویندوز | **1.0.524** | `installer/windows/setup.iss: #define MyAppVersion` ↔ `backend/app/__init__.py` |
| فرانت | **UI_BUILD 524** | `frontend/app.js: UI_BUILD` ↔ `mobile-android/BUILD` |
| APK | `RasaSystemMobile-1.0.524.apk` — 1,521,115 بایت — SHA-256 `065487452abe87bdfca9d58fe9a782ee798b37280f6d1f31b2ca5d98dc5a3ecc` — aapt2 `versionCode='52400' versionName='1.0.524'` | `releases/android/` + `installer/output/` |
| تگ | `v1.0.524` e685305 | `git tag -a v1.0.524` |
| Release | https://github.com/khajavy8056/Super-system-/releases/tag/v1.0.524 | GitHub Releases |

**مبدا:** c1e81ed (v1.0.520) = 16b01499 (v1.0.521 audit baseline) backend nil diff — بازگشت کامل.

**اصلاحات ممیزی I-01..I-25 (بدون رگرسیون):**
- I-01 `routers/returns.py: qty Decimal + allow_decimal guard (validate_for_unit)` — مرجوعی وزنی 0.5kg پذیرفته، 0.5 عدد رد.
- I-02 `services/accounting.py:post_sale_return` tender-aware (ACCOUNT→1201 + ledger RETURN_REFUND، CASH→1101/CARD/…)
- I-03 `services/accounting.py:session_summary` فقط برگشتی نقدی (Invoice.payment_method CASH-ish)
- I-04 `routers/reports.py` profit/PII gated (pricing.view_cost/accounting.view + scope store/self/none) — قبلاً درست بود، حفظ شد
- I-05 `services/pos.py:_next_invoice_number` local_today (Tehran) نه UTC؛ `services/insights.py:_load_ctx` شامل PARTIALLY_REFUNDED؛ `reports._day_range` local_day_range
- I-06 `services/insights.py:a_cashflow` فقط CASH inflow + opening از CashSession
- I-07 `services/insights.py:a_churn` dedupe `year-Wweek` (قبلاً week-only)
- I-08 `services/reports.py:_profit_agg` net of invoice_level discount + return profit (per-invoice group)
- I-09 `services/reports.py:_paid_filter` PARTIALLY_REFUNDED + `_net_refunds` + `_sales_agg` net؛ `insights._load_ctx` شامل جزئی
- I-18 `routers/insights.py:/run requires reports.view_all`
- I-20 شمارنده با کلید روز محلی (I-20 = I-05 برای فاکتور)
- I-22 `models/purchase.py` FK صحیح `acc_suppliers.id` + `daily_sales_summary`؛ `alembic/20261020_v1_0_522` handle wrong FK
- I-24 `models/sales.py:Customer.sms_consent*` (قبلاً موجود)
- I-15 `backend/requirements.txt: pytest`، I-14 `.gitignore releases/*.apk` + `eror.txt`، I-21 `data_quality.py` dead code حذف
- I-16 CI مستند مسدود (GitHub App بدون workflows permission — راهنما در docs)

**ورود (گزارش 523 «با رمز درست اشتباه است»):**
ریشه چندگانه روی هر سه سطح:
1. `backend/app/routers/auth.py:98` — `detail="نام کاربری یا رمز اشتباه است"` (قبلاً انگلیسی `Invalid...` → کلاینت به «نشست منقضی» می‌نگاشت)
2. `mobile-android/app/src/main/java/ir/khajavy/supermarket/Api.java: errorFrom` — 401/403/429 پیام سرور حفظ (قبلاً هر 401→«نشست منقضی»)
3. `backend/app/main.py: _RATE_LIMITS /api/auth/login 30/60` — قبلاً 10/60 برای NAT سختگیر → 429 با رمز درست
4. `mobile-android/app/src/main/java/ir/khajavy/supermarket/SetupActivity.java: install()` — PBKDF2 verifier + SHA fallback (قبلاً sha)
5. `frontend/app.js: login` — object detail handling (قبلاً [object Object] برای 429)
- تأیید: `TestClient /api/auth/login` فارسی 401، rate-limit 30→429 با detail string، `Local.java: passOk` PBKDF2/sha/legacy + migration، `metadata sortable` OK.

ساخت: `scripts/android/build-apk.sh` با `/tmp/atools` (aapt2, ecj, d8, apksigner, android.jar 34) — 6/6 گام + preflight PASS + امضای CN=Khajavy Supermarket SHA-256 `18b4ab18…`.

تأیید:
```bash
/tmp/atools/aapt2 dump badging releases/android/RasaSystemMobile-1.0.524.apk | grep version
# package: name='ir.khajavy.supermarket' versionCode='52400' versionName='1.0.524' ...

sha256sum releases/android/RasaSystemMobile-1.0.524.apk
# 065487452abe87bdfca9d58fe9a782ee798b37280f6d1f31b2ca5d98dc5a3ecc

PYTHONPATH=backend pytest backend/tests/test_auth.py backend/tests/test_pos.py backend/tests/test_inventory.py -q
# 15 passed

PYTHONPATH=backend python -m pytest -k "test_login"  # Persian 401, lockout 429, rate 30/60
# Persian detail OK, lockout after 5, rate limited at 30 string message
```
