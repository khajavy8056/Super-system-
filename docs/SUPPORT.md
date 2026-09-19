# درخواست پشتیبانی داخل برنامه (v1.7)

مسیر: ویندوز → منوی کناری «درخواست پشتیبانی»؛ گوشی → «بیشتر → پشتیبانی».

## چه چیزی ارسال می‌شود
| فیلد | توضیح |
|---|---|
| نوع | `BUG` ثبت خرابی، `FEATURE` درخواست امکان ویژه، `QUESTION`، `HARDWARE`، `LICENSE`، `TRAINING`، `OTHER` |
| اولویت | `LOW / NORMAL / HIGH / URGENT` |
| موضوع / شرح / راه تماس | متن آزاد (موضوع ۳–۱۶۰ حرف) |
| موقعیت مکانی | فقط با تیک «ارسال موقعیت مکانی دقیق»؛ `latitude/longitude/accuracy_m` از Geolocation API (ویندوز: WebView2؛ اندروید: `ACCESS_FINE_LOCATION` هنگام نیاز) |
| مشخصات | نسخهٔ برنامه، نام فروشگاه، شناسهٔ سخت‌افزار لایسنس، دستگاه (`Windows`/`Android`)، کاربر ثبت‌کننده |

## چرخهٔ عمر تیکت
1. `POST /api/support/tickets` → تیکت **همیشه** در جدول `support_tickets` ذخیره می‌شود (شمارهٔ `SUP-000001`, رویداد ممیزی `SUPPORT_TICKET_CREATED`). وضعیت اولیه `NEW`.
2. صف پس‌زمینه (`services/support.py`) با تلاش مجدد و back-off تیکت را از طریق **کانال رله** (`SUPPORT_RELAY_URL` + `SUPPORT_RELAY_TOKEN` در `config.py`/`.env`) به صندوق پشتیبانی تولیدکننده می‌فرستد (`sendMessage` متن + `sendLocation` در صورت وجود مختصات). موفق → `SENT`؛ ناموفق → `FAILED` («در انتظار ارسال مجدد») و دوباره تلاش می‌شود؛ دکمهٔ «ارسال دوباره» = `POST /api/support/tickets/{id}/resend`.
3. `POST /api/support/tickets/{id}/close` → `CLOSED`.
4. گوشی بدون دسترسی به رایانه: درخواست در صف آفلاین (IndexedDB `ops`, نوع `SUPPORT_TICKET`) می‌ماند و با اولین اتصال LAN از طریق `POST /api/mobile/sync` ثبت می‌شود (idempotent با شناسهٔ عملیات).

## API
- `GET /api/support/types` → `{types:[{id,label}], priorities:[…]}`
- `GET /api/support/tickets?limit=` (جدیدترین اول) — `POST /api/support/tickets` (201)
- `POST /api/support/tickets/{id}/resend` — `POST /api/support/tickets/{id}/close`
- `GET /api/support/status` → وضعیت صف/آخرین خطا

## حریم خصوصی
هیچ داده‌ای بدون اقدام کاربر ارسال نمی‌شود؛ موقعیت مکانی اختیاری است؛ محتوای فاکتورها/مشتری‌ها هرگز در تیکت گنجانده نمی‌شود.

## وضعیت آزمون (§57)
- `backend/tests/test_v1_7_support.py` (۵ تست؛ رله با `HTTPServer` محلی شبیه‌سازی می‌شود: ثبت، ارسال، شکست→FAILED→resend، بستن، replay از صف گوشی).
- `scripts/uitest/smoke-v1_7.js`, `smoke-android.js`: فرم ویندوز و گوشی با موقعیت مکانی شبیه‌سازی‌شده.
- تحویل روی کانال رلهٔ واقعی: **NOT VERIFIED** در سندباکس.

## گفتگوی دوطرفه (v1.8)

**پاسخ دادن از داخل ربات پشتیبانی** — هر تیکت با این سرآیند به صندوق پشتیبانی می‌رسد:

```
🎫 درخواست پشتیبانی جدید — TCK-000123@3F9A1C2B
🆔 کد فروشگاه: سوپرمارکت رضا #3F9A1C2B   (برای پاسخ: روی همین پیام Reply بزنید یا پیام را با «TCK-000123@3F9A1C2B» شروع کنید)
```

`3F9A1C2B` شناسهٔ ۸ رقمی پایدار همان نصب است (SHA-1 از HWID). دو راه پاسخ:

1. **Reply** روی پیام تیکت یا هر پیام بعدی همان رشته (برنامه `reply_to_message_id` را با `relay_ref` تیکت / `relay_message_id` پیام‌ها تطبیق می‌دهد).
2. متن را با `TCK-000123@3F9A1C2B` شروع کنید (بدون Reply). پیشوند در برنامه حذف می‌شود.

پیام‌هایی که به هیچ‌کدام نخورند یا شناسهٔ نصب دیگری داشته باشند **نادیده گرفته می‌شوند** (صدها فروشگاه یک صندوق مشترک دارند). فایل همراه پاسخ با `getFile` دانلود و در `media/support/` ذخیره می‌شود.

**سمت فروشگاه**: مودال گفتگو (ویندوز: «مشاهده / پاسخ»، گوشی: 💬) پیام‌ها را زمان‌بندی‌شده نشان می‌دهد؛ پاسخ متنی و **یک پیوست تا ۵۰ مگابایت** (`requestSendFile` → آپلود → `sendFile` با `reply_to_message_id`) در همان رشته می‌رود. پیام‌های نرسیده در وضعیت «در انتظار ارسال مجدد» می‌مانند و poller (هر ۲۰ ثانیه) دوباره تلاش می‌کند. پاسخ جدید = اعلان `SUPPORT_REPLY` + نشان قرمز روی منو.

API: `GET /api/support/tickets/{id}/messages` (خواندن = علامت خوانده‌شده)، `POST …/messages` (multipart `text`/`file`)، `POST /api/support/poll`، `GET /api/support/unread`.

آزمون: `tests/test_v1_7_support.py::test_two_way_conversation_routes_replies_to_the_right_store` و `::test_store_reply_with_attachment_is_uploaded_and_threaded` (رلهٔ شبیه‌سازی‌شده با `requestSendFile/upload/sendFile/getFile/getUpdates`).
