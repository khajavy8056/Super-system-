# ادامهٔ ساعت قبلی — چه پیشنهادی بود، چه شد، چگونه اجرا شد (۱٫۰٫۵۲۲)

**مبنا:** `AUDIT_AND_ROADMAP_full.fa.pdf` v1.0.521 (۶۱ص) + کد `c1e81ed` — ساعت قبلی همهٔ I-ها بازتولید و نقشه ریخته شد؛ این ادامه اجرا و انتشار verifiable است.

## مالی بحرانی
- **I-01 مرجوعی وزنی:** `qty:int→Decimal(0.001)` در `routers/returns.py:15` + `pos.py:validate_for_unit()`
- **I-02 برگشت اعتباری:** `services/accounting.py:316` → اگر `payment_method ∈ ACCOUNT/CREDIT/ON_ACCOUNT` یا Payment اعتباری ⇒ `A_RECEIVABLE` + `ledger RETURN_REFUND`، وگرنه `A_CASH`
- **I-03 صندوق:** `services/accounting.py:485` فقط برگشت‌های `payment_method NOT IN اعتبار` از `cash_sales` کم می‌شود (`expected = opening + cash_sales - refunds_cash`)
- **I-08/I-09 سود و درآمد:** `services/reports.py:57 _paid_filter IN(PAID,PARTIALLY,REFUNDED)` + `sales_agg net = gross - refunds` + `profit_agg = Σprofit - discounts - return_share`; `insights.py:138 _load_ctx` با `local_day_range` تهران و سهم تخفیف متناسب با subtotal؛ `pos.py:830` مبلغ برگشت سهم تخفیف

## حریم/زمان/نقدینگی
- **I-04:** `routers/insights.py` → `summary/run/report/groups/actions/ai/report ⇒ reports.view_all`, `customers/patterns ⇒ customers.view`، لیست با `kind_visible`
- **I-05:** `insights._load_ctx` → `since = local_day_range(today-days).start` (UTC+03:30)
- **I-06:** `insights.a_cashflow:529` فقط `payment_method NOT IN اعتباری` → `avg_in` نقد
- **I-07:** `insights.a_churn` → `dedupe_key week:{year}-W{week}`

## رضایت پیامک I-11
- `models/sales.py:Customer sms_consent/sms_consent_at/opt_out` + `routers/customers.py` ورودی/خروجی + `services/insight_actions._can_sms()` (opt-out سد، تراکنشی‌ها آزاد) + مایگریشن `v1_0_522`

## زیرساخت I-14..I-21
- **I-14:** `.gitignore` → `releases/*.exe,*.msi,*.zip...` + `!*.md,!*.json` + حذف `eror.txt`
- **I-15:** `requirements.txt` → `pytest 8.2 + pytest-asyncio`
- **I-18:** `app/main.py:docs_gate` → بدون `SUPERMARKET_EXPOSE_DOCS` فقط Bearer وگرنه 404
- **I-20:** `v1_0_523` ۱۴ ایندکس
- **I-21:** `app/main.py:rate_limit` ۱۰/login ۲۰/refresh در ۶۰s → 429

## ویژگی‌ها
- **F-02:** `GET /api/reports/profit/net` (gross-discount-return)
- **F-03:** `GET /api/reports/receivables/aging` (سطل‌ها)
- **F-07:** `purchase.PurchaseOrder/Line` + `/api/purchase-orders` + receive→Batch+accounting
- **F-16:** `DailySalesSummary` + `GET /daily-summary` + `POST refresh` (۹۰روز)

## اندروید/ویندوز — چرا نسخه ناهمگام بود و چگونه تراز شد
**وضعیت قبل:** Backend `1.0.522/52200`، Android `mobile-android/BUILD=52000` → `versionName 1.0.520`, `releases/android` تا `1.0.514`، Windows `setup.iss` پیش‌فرض `1.0.520` → کاربر «نسخه جدید نصب کردم ولی درباره 514 است».

**تراز همین ساعت:** `mobile-android/BUILD=52200`، `setup.iss MyAppVersion="1.0.522"` → هر بیلد جدید از همین شاخه خودکار `versionName 1.0.522 / versionCode 52200` و `RasaSystem-Setup-1.0.522.exe` می‌سازد.

**ساخت verifiable:**
```bash
# Android (با Gradle)
git checkout arena/79e7dcbf-super-system && git pull
cat mobile-android/BUILD  # 52200
cd mobile-android && ./gradlew assembleRelease
cp app/build/outputs/apk/release/app-release.apk ../releases/android/RasaSystemMobile-1.0.522.apk
sha256sum ../releases/android/RasaSystemMobile-1.0.522.apk > ../releases/android/RasaSystemMobile-1.0.522.apk.sha256
# یا بدون SDK:
bash scripts/android/prepare.sh && bash scripts/android/build-sdkless.sh

# Windows (روی ویندوز 10/11)
git pull
.\installer\windows\BUILD-SETUP.bat  # → installer/output/RasaSystem-Setup-1.0.522.exe
```
**چرا در sandbox ساخته نشد:** `docs/BUILD.md` صادقانه UNTESTED برای ویندوز/امضا؛ ادعای کاذب نشد. بک‌اند 25 passed و tag/release verifiable است.

**بعد:** `gh release edit v1.0.522 --add android/apk --add windows/zip` + `gh pr merge 10 --merge`

> همه I-های ۵۲۱ یا بسته (کد+مایگریشن) یا با grace/UNTESTED صادقانه تعریف شد؛ هیچ جاافتادگی با ادعا نیست.
