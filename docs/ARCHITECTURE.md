# معماری سیستم

این سند تصمیمات معماری را مطابق «Master Blueprint» مستند می‌کند.

## 1. اصول بنیادی (اجرا شده)

| اصل | پیاده‌سازی |
|---|---|
| **Product ≠ Batch** | `Product` و `ProductBatch` دو جدول جدا؛ یک کالا چند Batch دارد. |
| **قیمت خرید تاریخی overwrite نمی‌شود** | هر ورود → `ProductBatch` جدید؛ `buy_price` Batch قدیمی دست نمی‌خورد. |
| **قیمت فروش تاریخچه دارد** | `PriceVersion` با `effective_from/effective_to`؛ تغییر = بستن نسخه قبل + ساخت نسخه جدید. |
| **FIFO واقعیت فیزیکی نیست** | `services/pos.py` سیاست تخصیص (FIFO/FEFO/HYBRID/MANUAL) را از تنظیمات می‌خواند و فقط *پیشنهاد* می‌دهد. |
| **Batch Stock ≠ Product Stock** | موجودی کالا = Σ(batch.current_qty)؛ تطبیق از طریق Stocktaking. |
| **انقضا مستقل از FIFO** | `services/expiry.py` سطل‌های EXPIRED/TODAY/3/7/30 روز با آستانه قابل تنظیم. |

## 2. لایه‌ها

```
routers/  (HTTP + validation) 
   ↓
services/ (منطق کسب‌وکار — هیچ منطقی در UI نیست)
   ↓
models/   (SQLAlchemy ORM)
   ↓
database  (SQLite WAL؛ قابل تعویض با PostgreSQL)
   ↓
hardware/resolvers (خارج از تراکنش‌ها)
```

## 3. داده‌های کلیدی

- **ProductBatch**: `batch_number`, `quantity_received`, `current_qty`, `buy_price`, `consumer_price`, `sell_price`, `production_date`, `expiry_date`, `status` (ACTIVE/SOLD_OUT/EXPIRED/BLOCKED), `warehouse_id/location_id` (آماده چندشعبه).
- **PriceVersion**: `product_id`, `price_type` (SELL/CONSUMER/SUGGESTED/MARKET), `price`, `effective_from/to`, `source`.
- **StockMovement**: append-only؛ هر تغییر موجودی یک Movement + Audit دارد (`PURCHASE_IN`, `SALE_OUT`, `RETURN_IN/OUT`, `WASTE`, `ADJUSTMENT`, `TRANSFER_*`, `STOCKTAKE`).
- **Invoice / InvoiceItem**: قیمت لحظه فروش Snapshot می‌شود (`unit_buy_price`, `unit_consumer_price`, `unit_sell_price`, `profit`).
- **AuditLog**: `who/what/when/before/after/reference`.

## 4. جریان فروش (Checkout)

```
Cart → validate stock → resolve/confirm batch → calculate totals → payment
  → [DB Transaction: Invoice + Items + Payments + batch deduction
     + StockMovements + profit] → Commit
  → print (غیرمسدودکننده، خطا = print_status=FAILED) → queue SMS
```

## 5. انتخاب Batch در POS

1. Batch فیزیکی انتخاب‌شده توسط صندوق‌دار (اولویت).
2. پیشنهاد سیستم (FEFO: نزدیک‌ترین انقضا؛ FIFO: قدیمی‌ترین ورود).
3. سیاست پیکربندی‌شده (`pos.allocation_policy` = HYBRID پیش‌فرض).

اگر یک Batch موجود باشد → افزودن مستقیم (بدون انتخابگر). اگر چند Batch با قیمت متفاوت باشد → انتخابگر قیمت قدیم/جدید نمایش داده می‌شود.

## 6. محاسبه سود

```
profit(item) = (unit_sell_price − unit_buy_price) × qty − discount
Total profit = Σ profit(InvoiceItems)   # بر اساس Batch واقعی، نه میانگین
```

## 7. یکپارچگی و داده

- حذف فیزیکی ممنوع برای داده مالی/تاریخی → Soft Delete / Archive / Inactive.
- اصلاحات فقط از طریق Adjustment / Correction / Return / Price Version جدید / Batch جدید.
- تراکنش فروش: Commit همه‌چیز با هم؛ Rollback در صورت شکست.
- هیچ داده خارجی بدون `source + timestamp + confidence` و تأیید انسانی وارد سیستم اصلی نمی‌شود.

## 8. تصمیمات فنی (Technology Selection — بخش 6 بلوپرینت)

| معیار | انتخاب |
|---|---|
| Backend | **Python + FastAPI** (پایدار، تایپ‌شده، async، docs خودکار) |
| ORM / Migration | SQLAlchemy 2.0 + Alembic |
| Database | SQLite (WAL) برای نصب محلی/آفلاین؛ قابل تعویض با PostgreSQL |
| Auth | JWT (HS256) + bcrypt |
| Frontend | HTML/CSS/JS بدون فریم‌ورک (بدون build step، سبک برای POS) |
| Installer | PyInstaller + Inno Setup |
| Hardware | لایه انتزاعی؛ ESC/POS استاندارد |

## 9. حسابداری دوطرفه (v1.4.0)

- **اصل**: هر رویداد مالی یک سند متوازن در `acc_journal_entries/acc_journal_lines` می‌سازد؛ سند بدون توازن ذخیره نمی‌شود (سرویس `accounting.post_entry` پیش از commit جمع بدهکار/بستانکار را می‌سنجد و `AccountingError("UNBALANCED")` می‌دهد).
- **منبع حقیقت**: موجودی و فروش همچنان در جداول عملیاتی (batches/invoices) هستند؛ حسابداری «بازتاب» آن‌هاست و در همان تراکنش DB ثبت می‌شود (`services/pos.checkout` → `accounting.record_sale`, `services/batches.receive` → `accounting.record_purchase`) تا ناسازگاری پیش نیاید. خطای حسابداری، فروش را rollback می‌کند.
- **دوره‌ها**: ثبت در تاریخ متعلق به دورهٔ بسته ممنوع است (`PERIOD_CLOSED`). اصلاح فقط با سند برگشت (`/journal/{id}/reverse`)؛ هیچ سندی ویرایش/حذف نمی‌شود (سازگار با اصل تغییرناپذیری تاریخچهٔ قیمت).
- **گزارش‌ها** همگی از ردیف‌های سند محاسبه می‌شوند (تراز آزمایشی، دفتر کل، سود و زیان، ترازنامه) — نه از جداول جداگانه؛ بنابراین همیشه با هم سازگارند.
- **مجوزها**: `accounting.view/post/close` روی نقش‌های Admin/Manager؛ صندوق‌دار فقط شیفت خود.

```
POS checkout ──► invoice ──► record_sale ──► JE: Dr 1101/1102/1103/1201  Cr 4101 (+2201)
                                       └─► JE: Dr 5101 (COGS FIFO)        Cr 1301
Receive batch ─► batch ───► record_purchase ► JE: Dr 1301  Cr 2101 | 1101/1102/1103
Expense ──────────────────► JE: Dr 61xx  Cr 1101/1102/1103
Cheque RECEIVED clear ────► JE: Dr 1102  Cr 1201 ; ISSUED clear ► Dr 2101 Cr 1102
```
