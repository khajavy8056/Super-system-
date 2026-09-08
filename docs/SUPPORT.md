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
