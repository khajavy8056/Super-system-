# سیستم پیامک (§164–§177, §330)

> صداقت (§57): ارسال زنده از این محیط ممکن نبود (خروجی اینترنت بسته است). پیاده‌سازی
> ملی‌پیامک مطابق **کلاینت رسمی** ([`Melipayamak/melipayamak-python`](https://github.com/Melipayamak/melipayamak-python))
> است و با یک **سرور شبیه‌ساز** در آزمون خودکار (`test_melipayamak_line_mode_success_and_credit`,
> `test_melipayamak_pattern_mode_error_codes`) تأیید شده: فرم ارسالی، تفسیر `RetStatus`
> و متن خطاهای فارسی. ارسال واقعی → **NOT VERIFIED**.

## ۱. معماری

```
رویداد (checkout / بدهی / کوپن / اسکن انبار / گزارش روزانه)
   └─► services.sms.queue_sms()  → جدول sms_messages (status=QUEUED)
             └─► worker پس‌زمینه هر sms.worker_interval_seconds ثانیه
                    └─► dispatch_pending() → provider
                          ├─ melipayamak  (REST رسمی)
                          ├─ kavenegar    (REST)
                          ├─ file         (لاگ محلی — توسعه/آزمون)
                          └─ (خالی)       غیرفعال؛ پیام با FAILED/DISABLED ثبت می‌شود
```

هیچ ارسالی مسیر درخواست HTTP کاربر را کند نمی‌کند؛ صف + Retry (`sms.max_retries`) + Audit.

## ۲. ملی‌پیامک

* Base: `https://rest.payamak-panel.com/api/SendSMS/{method}` — `POST` فرم (`application/x-www-form-urlencoded`)
  همیشه با `username` و `password` (رمز می‌تواند API key باشد).
* **حالت line** (`sms.melipayamak_mode=line`): `SendSMS` با `{to, from=sms.sender, text, isFlash=false}`.
* **حالت pattern / خط خدماتی** (`pattern`): `BaseServiceNumber` با `{to, bodyId=sms.melipayamak_body_id, text}` —
  متن الگو با `;` بین آرگومان‌ها؛ سیستم خطوط قالب را با `;` می‌پیوندد.
* پاسخ: `{"Value": "<RecId یا کد خطا>", "RetStatus": 1, "StrRetStatus": "Ok"}`؛ `RetStatus != 1` → خطای فارسی
  از جدول `MELIPAYAMAK_STATUS` (مثلاً «اعتبار کافی نیست»).
* اعتبار: `GetCredit` → در `تست اتصال سرویس پیامک` و عیب‌یابی نمایش داده می‌شود.
* وضعیت تحویل: `GetDeliveries2 {recId}` → `services.sms.melipayamak_delivery`.
* `sms.melipayamak_url` فقط برای پروکسی/آزمون؛ خالی = آدرس رسمی.

## ۳. کلیدهای تنظیمات (تب «پیامک»)

| کلید | توضیح |
|---|---|
| `sms.provider` | `melipayamak` / `kavenegar` / `file` / خالی |
| `sms.username`, `sms.password`, `sms.api_key` | محرمانه (write-only در UI) |
| `sms.sender` | شمارهٔ خط ارسال (حالت line) |
| `sms.melipayamak_mode`, `sms.melipayamak_body_id`, `sms.melipayamak_url` | حالت الگو/خط خدماتی |
| `sms.admin_phone` | شمارهٔ مدیر برای هشدار/گزارش (پیش‌فرض `store.mobile`) |
| `sms.send_invoice` | ارسال پیامک فاکتور به مشتری ثبت‌شده |
| `sms.low_stock_alert` | هشدار کمبود موجودی پس از اسکن انبار (§176) |
| `sms.max_retries`, `sms.worker_interval_seconds` | صف |
| `sms.template.*` | الگوهای فارسی: `invoice`, `debt_reminder`, `coupon`, `low_stock`, `daily_report` (§166) |

## ۴. APIها

| مسیر | کار |
|---|---|
| `GET /api/sms` | لاگ پیام‌ها با وضعیت/تلاش/خطا |
| `POST /api/sms/send` | ارسال دستی (صف) |
| `POST /api/sms/dispatch` | اجرای فوری صف |
| `POST /api/sms/{id}/retry` | تلاش مجدد پیام FAILED |
| `GET /api/sms/templates` | الگوها و متغیرها |
| `POST /api/sms/daily-report` | پیامک گزارش مدیریت (§175) |
| `POST /api/sms/test-connection` | تست اتصال (ملی‌پیامک: `GetCredit`) |

## ۵. رخدادهای Audit

`SMS_QUEUED`, `SMS_SENT`, `SMS_FAILED`, `SMS_RETRY`, `SMS_TEST_CONNECTION`.

## ۶. خطاهای رایج و پیام فارسی

| RetStatus / وضعیت | پیام |
|---|---|
| `-1` | نام کاربری یا رمز عبور اشتباه است |
| `-2` | اعتبار کافی نیست |
| `-3` | محدودیت در ارسال روزانه |
| `-7` | شمارهٔ گیرنده نامعتبر است |
| `-10` | کاربر غیرفعال است |
| timeout / DNS | «سرویس پیامک در دسترس نیست» → پیام در صف می‌ماند و Retry می‌شود |
