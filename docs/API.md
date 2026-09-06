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
