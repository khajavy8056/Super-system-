# API Reference

Base URL: `http://localhost:8000/api` — مستندات تعاملی: `/docs`

احراز هویت: `Authorization: Bearer <token>` (از `POST /api/auth/login`).

## Auth
- `POST /auth/login` — فرم `username/password` → token
- `GET  /auth/me` — کاربر جاری

## Products
- `GET /products` — لیست (فیلتر `q`، صفحه‌بندی)
- `GET /products/{id}` / `GET /products/barcode/{barcode}`
- `POST /products` — ثبت کالا
- `PATCH /products/{id}` / `DELETE /products/{id}` (soft delete)

## Batches (ورود کالا)
- `GET /batches` / `GET /batches/{id}`
- `POST /batches/receive` — ورود → Batch جدید + PURCHASE_IN
- `DELETE /batches/{id}` — فقط Batch خالی

## Inventory
- `GET /inventory/stock` — موجودی کل به تفکیک Batch
- `POST /inventory/adjust` / `POST /inventory/waste`
- `GET /inventory/movements`
- `POST /inventory/stocktakes` / `GET /inventory/stocktakes[/{id}]`
- `POST /inventory/stocktakes/count` / `POST /inventory/stocktakes/{id}/complete`

## Pricing
- `POST /prices` — نسخه قیمت جدید (بستن نسخه قبل)
- `GET /prices/history/{product_id}` / `GET /prices/active/{product_id}`
- `POST /prices/suggest` — قیمت پیشنهادی (هزینه + مارجین + بازار)
- `GET /prices/market/{product_id}`

## POS
- `GET /pos/batch-options/{product_id}` — Batch های قابل فروش + پیشنهاد سیستم
- `POST /pos/cart/validate` — اعتبارسنجی سبد (بدون ثبت)
- `POST /pos/checkout` — فروش تراکنشی

## Invoices / Returns
- `GET /invoices[/{id}]`
- `POST /invoices/{id}/void`
- `POST /invoices/{id}/print`
- `POST /returns`

## Resolvers
- `GET /barcode/resolve/{barcode}` — محلی → کش → خارجی → دستی
- `GET /barcode/images/{barcode}` / `GET /barcode/prices/{barcode}`

## Reports / Dashboard
- `GET /reports/dashboard`
- `GET /reports/sales?start=&end=` / `GET /reports/profit`
- `GET /reports/batches` / `GET /reports/low-stock` / `GET /reports/movements`

## System
- `GET /health`
- `GET /settings` / `PUT /settings`
- `GET /users` / `POST /users` / `GET /users/roles`
- `GET /audit`
- `GET /hardware` / `POST /hardware` / `GET /hardware/health`
- `POST /sms/send`
- `POST /jobs/expiry-scan` / `POST /backup`

## کدهای خطا (بخش 102)
`PRODUCT_NOT_FOUND`, `BATCH_NOT_FOUND`, `INSUFFICIENT_STOCK`, `BATCH_EXPIRED`, `PRICE_NOT_AVAILABLE`, `PRINTER_OFFLINE`, `SMS_PROVIDER_ERROR`, `EXTERNAL_API_TIMEOUT`, `DATABASE_ERROR`

## Phase 11 — product identity, per-batch pricing (v0.3.0)

### `GET /api/products/{id}/detail`
One product identity plus **every** batch that ever belonged to it.

```json
{
  "product": { "id": 1, "barcode": "INT-000001", "has_own_barcode": false },
  "total_stock": 35.5,
  "active_batches":   [ { "batch_number": "B-20260905-000002", "buy_price": 105000, "supplier_price": 107000, "sell_price": 140000, "discount": 0, "tax": 9450 } ],
  "depleted_batches": [ ],
  "batch_count": 2
}
```

Depleted batches are returned, not hidden: they are the purchase-price history
and deleting them would erase the margin record (§5).

### `POST /api/products/check-duplicate`
Advisory duplicate warning (§33). Never blocks and never auto-merges — barcode
equality is the only hard identity rule (§32).

Request `{"name": "...", "barcode": "...", "brand_id": 1}` →
`{"exact_barcode_match": {...}|null, "possible_duplicates": [{"product_id":1,"confidence":0.9,"reason":"نام یکسان"}], "has_warning": true}`

Name comparison folds Arabic/Persian variants (ي→ی، ك→ک، آ→ا) and
Eastern-Arabic digits, so «آب معدني» and «اب معدنی» match.

### `GET|POST /api/products/brands`, `GET|POST /api/products/categories`
Idempotent taxonomy CRUD — re-posting an existing name returns that row.
Required for §18 brand search.

### `POST /api/batches/receive` — new optional fields
`supplier_price`, `discount`, `tax`. All per batch; never written to Product.

### `POST /api/barcode/apply` — behaviour change (§31)
An existing barcode is now **updated** instead of rejected with 409. The
response carries `"created": true|false`. Omitted/blank fields never overwrite
existing local data, and omitting `min_stock_alert` no longer resets it.

### `GET /api/pos/search`
Now also matches **brand name** in addition to barcode, product name, SKU and
model (§18).

### §16 internal barcodes
`POST /api/products` accepts a product with no `barcode`. The server mints
`INT-000001` via an atomic counter and sets `has_own_barcode: false`, marking
the code as meaningless to external catalogues.


## افزوده‌های v1.1.0

### انبارها و انتقال (§109, §130, §131)
| Method | Path | مجوز | توضیح |
|---|---|---|---|
| GET | `/api/warehouses` | inventory.view | فهرست انبارها + محل‌ها + موجودی/ارزش هر انبار (انبار پیش‌فرض خودکار ساخته می‌شود) |
| POST | `/api/warehouses` | inventory.adjust | `{name, code?, address?, is_default?}` |
| PATCH | `/api/warehouses/{id}` | inventory.adjust | ویرایش / غیرفعال‌سازی |
| POST | `/api/warehouses/{id}/locations` | inventory.adjust | `{name, code?}` محل نگهداری |
| POST | `/api/warehouses/transfer` | inventory.adjust | `{batch_id, quantity, to_warehouse_id, to_location_id?, reason?}` → جفت حرکت `TRANSFER_OUT/IN` |

### POS
- `POST /api/pos/checkout` و `POST /api/pos/cart/validate`: فیلد جدید `invoice_discount` (مبلغ، §12). پاسخ checkout شامل `invoice_discount` و `drawer: {ok, message}` (§19) است.
- `POST /api/invoices/{id}/void`: برای فاکتور `PAID` فیلد `admin_password` الزامی است (§209؛ قابل غیرفعال‌سازی با `security.require_admin_for_void_paid=false`). خطا: `401 ADMIN_PASSWORD_REQUIRED`.

### پیامک
| Method | Path | توضیح |
|---|---|---|
| GET | `/api/sms/templates` | الگوهای قابل ویرایش و placeholderها (§166) |
| POST | `/api/sms/{id}/retry` | بازگرداندن پیامک FAILED به صف (§171) |
| POST | `/api/sms/test-connection` | تست اتصال سرویس (§177) |
| POST | `/api/sms/daily-report` | پیامک گزارش مدیریت به `sms.admin_phone` (§175) |

### دسته‌بندی
- `POST /api/products/categories` فیلد `parent_id?` (§79)؛ `GET` فیلدهای `parent_id`, `parent_name`, `path`.

## افزوده‌های v1.2.0

### بانک اولیهٔ کالا / ورود CSV (§80–82)
- `GET /api/products/import/starter` — خلاصهٔ بانک بسته‌بندی‌شده (تعداد کالا/دسته/زیردسته، ستون‌ها).
- `POST /api/products/import/starter?dry_run=false` — ورود idempotent با موجودی صفر؛ پاسخ `{created, skipped, errors[], stock_note}`.
- `POST /api/products/import/csv` (multipart `file`, UTF-8; ستون‌ها `category,subcategory,name,brand,unit,min_stock_alert,barcode`) — `400 BAD_HEADER` / `BAD_ENCODING`.

### لوگوی فروشگاه (§214)
- `POST /api/settings/store-profile/logo` (multipart `file`, PNG/JPEG/SVG/WebP ≤ 2MB) → `{logo_path: "/media/store-logo.png?v=…"}`؛ خطاها `UNSUPPORTED_TYPE`, `TOO_LARGE`, `CORRUPT`.
- `DELETE /api/settings/store-profile/logo` → لوگوی پیش‌فرض.

### گزارش فروش (§137–138)
- `GET /api/reports/sales?start&end&group=daily|weekly|monthly|product` — `monthly`/`weekly` گروه‌های شمسی `{period, first_day, last_day, invoice_count, total}`.

### به‌روزرسانی (§270)
- `GET /api/system/update/check` اکنون فیلد `channel` (`github` | `updateserver`) و وضعیت `CONFIG_MISSING` دارد. تنظیمات: `update.channel`, `update.server_url`, `update.server_token`.

### سخت‌افزار (§178–182)
- `POST /api/hardware` با `connection` یکی از `tcp://host:9100`, `escpos:usb:VID:PID`, `escpos:win:NAME`, `file:///path`.
- `POST /api/hardware/test/print` — با پروفایل واقعی (`printer.*`, لوگو)؛ در نبود دستگاه `PRINTER_NOT_CONFIGURED`.

### پیامک (§164–165)
- `POST /api/sms/test-connection` برای ملی‌پیامک اعتبار واقعی (`GetCredit`) را برمی‌گرداند؛ حالت‌های `sms.melipayamak_mode=line|pattern`.
