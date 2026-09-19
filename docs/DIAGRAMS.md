# نقشه‌ها و نمودارهای سامانه (§334–§341)

همهٔ نمودارها Mermaid هستند و در GitHub/VS Code مستقیم رندر می‌شوند. نمودار ER کامل در `DATABASE.md`.

## ۱. معماری کلی (§334)

```mermaid
flowchart LR
  subgraph Store["رایانهٔ فروشگاه (Windows)"]
    EXE["SupermarketSystem.exe<br/>(PyInstaller + پنجرهٔ اختصاصی)"]
    API["FastAPI backend<br/>:8000 — bind 0.0.0.0"]
    DB[("SQLite<br/>data/supermarket.db")]
    MEDIA["data/media<br/>(تصاویر، لوگو)"]
    WEB["پنل وب دسکتاپ<br/>frontend/ (PWA)"]
    WORKER["Workerهای پس‌زمینه<br/>SMS · اسکن انقضا · پشتیبان"]
    EXE --> API --> DB
    API --> MEDIA
    API --> WEB
    API --> WORKER
  end
  subgraph LAN["شبکهٔ داخلی"]
    MOB["موبایل انبارگردانی<br/>/mobile/ PWA یا APK اندروید"]
    PRN["پرینتر حرارتی<br/>tcp://:9100 / USB"]
    DRW["کشوی پول (ESC p)"]
    SCN["بارکدخوان keyboard-wedge"]
  end
  MOB <-->|HTTP JSON + JWT| API
  API -->|ESC/POS| PRN --> DRW
  SCN --> WEB
  subgraph Ext["سرویس‌های بیرونی (اختیاری، قابل قطع)"]
    OFF["OpenFoodFacts (ODbL)"]
    SMS["ملی‌پیامک / کاوه‌نگار"]
    GH["GitHub Releases / Update Server"]
    NTP["NTP / زمان"]
  end
  API -.-> OFF
  WORKER -.-> SMS
  API -.-> GH
  API -.-> NTP
```

## ۲. جریان داده (§335)

```mermaid
flowchart TD
  A[ورود کالا: رسید خرید] -->|POST /batches| B[(product_batches)]
  B -->|IN| M[(stock_movements)]
  C[فروش POS] -->|POST /pos/checkout| I[(invoices / invoice_items / payments)]
  I -->|SALE_OUT| M
  R[مرجوعی] -->|RETURN_IN| M
  W[ضایعات / اصلاح / انتقال] -->|WASTE · ADJUSTMENT · TRANSFER| M
  M --> S{موجودی Batch = Σ حرکات}
  S --> D[داشبورد ۱۲ بلوک]
  S --> L[هشدار کم‌موجود → اعلان + SMS]
  I --> LED[(customer_ledger_entries)]
  I --> AUD[(audit_logs)]
  I --> PRT[چاپ رسید ESC/POS]
  I --> SMSQ[(sms_messages)]
```

## ۳. جریان فروش (§339)

```mermaid
sequenceDiagram
  participant K as صندوق‌دار
  participant UI as POS UI
  participant API as /api/pos
  participant DB as SQLite
  participant HW as پرینتر/کشو
  K->>UI: اسکن بارکد / جستجو
  UI->>API: GET /products/barcode/{b}
  API-->>UI: کالا + Batchهای فعال (FIFO پیشنهادی)
  K->>UI: انتخاب Batch (اگر چند قیمت) · تعداد · تخفیف
  UI->>API: POST /pos/cart/validate
  API-->>UI: جمع، تخفیف سطری/فاکتور/کوپن، کمبود موجودی
  K->>UI: پرداخت (نقد/کارت/دفتری/ترکیبی) F2
  UI->>API: POST /pos/checkout
  API->>DB: invoice + items + payments + SALE_OUT + ledger + audit (تراکنش واحد)
  API->>HW: print_receipt(kick_drawer = پرداخت نقدی)
  HW-->>API: SUCCESS / PRINTER_OFFLINE (صادقانه)
  API-->>UI: invoice_id, totals, print_status, drawer.ok
  UI-->>K: رسید + امکان چاپ مجدد
```

## ۴. ثبت محصول و Resolver (§340)

```mermaid
flowchart LR
  S[اسکن بارکد در فرم ثبت کالا] --> V{checksum معتبر؟}
  V -->|خیر| MAN[ثبت دستی]
  V -->|بله| LOC{در پایگاه محلی؟}
  LOC -->|بله| EX[نمایش کالای موجود]
  LOC -->|خیر| CACHE{در کش تأییدشده؟}
  CACHE -->|بله| PRE[پیش‌پر کردن فرم]
  CACHE -->|خیر| SRC[منابع بیرونی به ترتیب priority]
  SRC --> MERGE[ادغام + اعتماد HIGH/MEDIUM/LOW]
  MERGE --> PEND[(product_resolver_results: PENDING)]
  PEND --> CONF{تأیید کاربر}
  CONF -->|تأیید| P[(products)]
  CONF -->|ویرایش/رد| MAN --> P
  P --> INT[بدون GTIN؟ → INT-NNNNNN]
```

## ۵. انبارگردانی موبایل ↔ دسکتاپ (§337, §338)

```mermaid
sequenceDiagram
  participant M as موبایل (PWA/APK)
  participant SW as Service Worker + صف آفلاین
  participant API as /api/inventory/stocktakes
  participant D as دسکتاپ مدیر
  D->>API: POST /stocktakes (شروع، انبار، محدوده)
  M->>API: GET /stocktakes/open
  loop هر قفسه
    M->>M: اسکن با دوربین (BarcodeDetector) یا تایپ
    M->>SW: ثبت شمارش (client_key یکتا)
    alt آنلاین
      SW->>API: POST /stocktakes/{id}/items (idempotent)
    else آفلاین
      SW->>SW: ذخیره در IndexedDB، بنر «آفلاین»
      SW-->>API: همگام‌سازی خودکار پس از اتصال
    end
  end
  D->>API: GET /stocktakes/{id} (پیشرفت لحظه‌ای، اختلاف‌ها)
  D->>API: POST /stocktakes/{id}/finalize → ADJUSTMENT movements
```

## ۶. سرویس‌های خارجی و رفتار قطع (§341)

```mermaid
flowchart TB
  subgraph Local["همیشه کار می‌کند (Local-First)"]
    POS[فروش] --- INV[انبار] --- REP[گزارش] --- USR[کاربران] --- BK[پشتیبان]
  end
  subgraph Degrade["با قطع اینترنت: کاهش تدریجی، بدون خطای مسدودکننده"]
    RES[Resolver → need_manual]
    SM[SMS → در صف، Retry]
    UP[Update → UNAVAILABLE]
    TM[زمان → ساعت سیستم + هشدار]
    IMG[تصویر → بدون تصویر]
  end
  Local --> Degrade
```

## ۷. به‌روزرسانی امن (§266–§276)

```mermaid
stateDiagram-v2
  [*] --> CHECK: GET /update/check
  CHECK --> UP_TO_DATE
  CHECK --> AVAILABLE
  AVAILABLE --> AUTH: رمز مدیر
  AUTH --> BACKUP
  BACKUP --> ABORTED: شکست پشتیبان
  BACKUP --> DOWNLOAD
  DOWNLOAD --> VERIFY: اندازه + SHA-256 + PE
  VERIFY --> FAILED: عدم تطابق
  VERIFY --> PREPARED
  PREPARED --> INSTALL: اجرای Setup.exe
  INSTALL --> MIGRATE: Alembic افزودنی
  MIGRATE --> [*]
  FAILED --> ROLLBACK: بازگردانی backup
```
