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
