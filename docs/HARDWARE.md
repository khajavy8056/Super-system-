# سخت‌افزار — پرینتر حرارتی، کشوی پول، بارکدخوان (§178–§190, §328)

> وضعیت صداقت (§57): درایور ESC/POS با یک **شبیه‌ساز پرینتر شبکه (پورت 9100)** در
> آزمون خودکار تأیید شده است (`test_escpos_tcp_receipt_cut_and_drawer`): بایت‌های
> init/کدپیج، برش کاغذ و پالس کشو دقیقاً همان چیزی است که پرینتر واقعی دریافت می‌کند.
> اجرا روی پرینتر فیزیکی در این محیط ممکن نبود → **NOT VERIFIED on device**.

## ۱. معماری

```
POS checkout ──► services/hardware.print_receipt(db, invoice, kick_drawer)
                     │  render_receipt()  ← printer_profile(db)  ← system_settings (printer.*, store.*)
                     │  receipt_text()  → متن فارسی ۳۲/۴۲/۴۸ ستونی
                     ▼
              transport بر اساس HardwareDevice.connection
   ┌─────────────┬──────────────────┬──────────────────────┬──────────────────┐
   │ file://path │ tcp://host:9100  │ escpos:usb:VID:PID   │ escpos:win:NAME  │
   │ (سینک متن)  │ raw JetDirect    │ python-escpos (opt.) │ Windows spooler  │
   └─────────────┴──────────────────┴──────────────────────┴──────────────────┘
                                ▼
                escpos_driver.build_escpos()  → بایت‌های ESC/POS
```

* `backend/app/services/escpos_driver.py` — ساخت بایت‌ها و ارسال؛ بدون وابستگی اجباری.
* `backend/app/services/hardware.py` — پروفایل پرینتر، رندر رسید فارسی، ثبت وضعیت چاپ و Audit.
* `backend/app/routers/hardware.py` — `GET/POST /api/hardware`, `GET /health`,
  `POST /test/print`, `POST /test/drawer`, `POST /scanner/detect`.

## ۲. ثبت دستگاه

| device_type | connection | توضیح |
|---|---|---|
| `PRINTER` | `tcp://192.168.1.50:9100` | پرینتر شبکه (اکثر پرینترهای ۸۰mm)؛ بدون درایور |
| `PRINTER` | `escpos:usb:04b8:0e15` | USB مستقیم؛ نیازمند `pip install -r backend/requirements-hardware.txt` (python-escpos) |
| `PRINTER` | `escpos:win:POS-80` | نام پرینتر در Windows (چاپ RAW از طریق spooler) |
| `PRINTER` | `file:///C:/pos/receipt.txt` | سینک متنی برای آزمایش/بایگانی |
| `CASH_DRAWER` | (خالی) | کشو **از طریق پرینتر** با فرمان `ESC p` باز می‌شود |
| `SCANNER` | (خالی) | بارکدخوان keyboard-wedge؛ تشخیص با فاصلهٔ کلیدها (`barcode.scanner.min_interval_ms`) |

## ۳. تنظیمات مؤثر (`تنظیمات ← پرینتر حرارتی / کشوی پول`)

| کلید | پیش‌فرض | اثر |
|---|---|---|
| `printer.paper_width_mm` | `80` | ۵۸→۳۲ ستون، ۷۶→۴۲، ۸۰→۴۸ (Font A) |
| `printer.cut` | `true` | `GS V 66 n` برش جزئی پس از هر رسید |
| `printer.header` / `printer.footer` | خالی | متن بالا/پایین رسید |
| `printer.drawer.enabled` | `true` | پالس کشو در فروش نقدی |
| `printer.drawer.pin` | `2` | پین ۲ (`m=0`) یا پین ۵ (`m=1`) |
| `store.name/address/phone` | — | سربرگ رسید |
| `store.logo_path` | — | لوگوی PNG/JPEG به‌صورت raster (`GS v 0`) بالای رسید؛ SVG چاپ نمی‌شود |
| `pos.currency` | `IRT` | برچسب «تومان/ریال» |

## ۴. توالی ESC/POS تولیدشده

```
ESC @              init
ESC t 30           code page 1256 (عربی/فارسی ویندوز)
[GS v 0 ...]       لوگو (اختیاری)
ESC a 2 / ESC a 0  راست‌چین برای خطوط فارسی، چپ‌چین برای لاتین
<خطوط رسید>        هر خط با visual_rtl() معکوس بصری و cp1256 کدگذاری می‌شود
ESC d 2            دو خط تغذیه
GS V 66 3          برش جزئی (اگر printer.cut)
ESC p m 60 120     پالس کشو (اگر فروش نقدی و drawer.enabled)
```

پرینترهایی که cp1256 ندارند، اعداد/جداکننده‌ها را درست و حروف فارسی را `?` چاپ می‌کنند —
سیستم هرگز به‌جای خطا، «موفق» گزارش نمی‌کند.

## ۵. مسیرهای خطا (صادقانه)

| وضعیت | معنا | نمایش |
|---|---|---|
| `PRINTER_NOT_CONFIGURED` | هیچ پرینتری با connection ثبت نشده | فاکتور ثبت می‌شود، `print_status=FAILED`, دکمهٔ «چاپ مجدد» |
| `PRINTER_OFFLINE` / `PRINTER_ERROR` | اتصال TCP/USB برقرار نشد | Toast قرمز + Audit `PRINT_FAILED` |
| `NOT_SUPPORTED` | اسکیم ناشناخته | راهنما در فرم ثبت دستگاه |
| `CASH_DRAWER_UNAVAILABLE` | پرینتری برای ارسال پالس نیست | در پاسخ checkout: `drawer.ok=false` |

## ۶. عیب‌یابی

* `تنظیمات ← عیب‌یابی ← اجرای کامل`: بررسی «Thermal printer» با probe واقعی (TCP connect یا وجود فایل).
* `POST /api/hardware/test/print` یک رسید آزمایشی با پروفایل جاری چاپ می‌کند.
* لاگ: `logs/supermarket.log` و Audit با action های `PRINT_SUCCESS`, `PRINT_FAILED`,
  `DRAWER_OPENED`, `DRAWER_FAILED`.

## ۷. آزمون‌ها

`backend/tests/test_v1_1_features.py` — `test_escpos_tcp_receipt_cut_and_drawer`,
`test_escpos_unreachable_printer_is_reported`, `test_visual_rtl_and_columns`,
`test_store_logo_upload_serves_and_reaches_receipt`; `tests/test_phase3.py` (سینک فایل).
