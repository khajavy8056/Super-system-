# Resolver — شناسایی خودکار کالا از بارکد (§52–§66, §329)

> صداقت (§57): خط لوله با منابع mock در `tests/test_resolvers.py` تأیید شده؛ فراخوانی زندهٔ
> اینترنت از این محیط ممکن نبود → **NOT VERIFIED online**. تنها منبع پیش‌فرض
> OpenFoodFacts (ODbL، بدون کلید و بدون هزینه) است — هیچ منبع نیازمند حساب/پرداخت به‌عنوان
> وابستگی سخت وجود ندارد (قید کاربر).

## ۱. جریان (`services/resolvers.py::resolve_barcode`)

```
بارکد ورودی
 ├─ normalize + validate (checksum EAN-8/13, UPC-A, INT-)       ✗ → «بارکد نامعتبر» (need_manual)
 ├─ ۱) پایگاه محلی  products.barcode                            ✓ → origin=local
 ├─ ۲) کش تأییدشده product_resolver_results (status=APPROVED)   ✓ → origin=cache
 ├─ ۳) منابع فعال external_sources به ترتیب priority (کم = اول)
 │      هر منبع: timeout مستقل، خطا ⇒ SourceOutcome(error) و ادامهٔ بعدی
 ├─ ۴) نرمال‌سازی فیلدها (name, brand, category, image, size)
 ├─ ۵) ادغام: توافق ≥۲ منبع → HIGH؛ یک منبع → MEDIUM؛ اختلاف → رأی اکثریت/اولویت → LOW
 └─ ۶) ذخیرهٔ کاندیدا با status=PENDING → کاربر در فرم «ثبت کالا» تأیید/ویرایش می‌کند
```

* داده‌های بیرونی **هرگز مستقیم** به `products` نمی‌روند؛ همیشه با تأیید کاربر (§55).
* هر نتیجه در `product_resolver_results` با `source_code`, `confidence`, `raw_payload` نگه‌داری می‌شود (قابل ممیزی).

## ۲. منابع (`external_sources`)

| code | نوع | priority | مجوز | نکته |
|---|---|---|---|---|
| `openfoodfacts` | PRODUCT | 10 | ODbL, keyless | نام/برند/دسته/اندازه |
| `openfoodfacts_img` | IMAGE | 10 | ODbL | تصویر → دانلود در `MEDIA_DIR` (§66) |

افزودن منبع جدید: ردیف جدید در `external_sources` (`base_url` با `{barcode}`) + یک parser در
`resolvers.py::_PARSERS`. غیرفعال‌سازی: `is_active=false` (تصمیم اپراتور پس از ری‌استارت حفظ می‌شود).

## ۳. تصویر و قیمت بازار

* `resolve_image()` — دانلود به `data/media/products/<barcode>.<ext>`، ثبت در `image_assets`؛ آفلاین ⇒ بدون تصویر، بدون خطا.
* `resolve_market_price()` — جدول `market_prices` صرفاً **مرجع**؛ قیمت فروش همیشه از Batch (§Product≠Batch).

## ۴. API

| مسیر | توضیح |
|---|---|
| `GET`/`POST /api/resolvers/resolve/{barcode}` | اجرای کامل خط لوله |
| `POST /api/resolvers/images/{barcode}`, `POST /prices/{barcode}` | تصویر / قیمت بازار |
| `GET/POST /api/resolvers/sources`, `PATCH/DELETE /sources/{id}`, `GET /sources/providers` | مدیریت منابع و اولویت |
| `POST /api/resolvers/results/{id}/review` | تأیید/رد کاندیدا → کش |

## ۵. رفتار آفلاین

بدون اینترنت: مرحلهٔ ۳ در چند ثانیه با `SourceOutcome.error` تمام می‌شود و فرم با
`need_manual=true` باز می‌ماند؛ ثبت دستی همیشه ممکن است (§65).
