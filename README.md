# 🛒 Supermarket System — سیستم مدیریت سوپرمارکت

**Supermarket ERP / Smart Inventory / POS** — یک نرم‌افزار واقعی، مستقل و قابل نصب روی Windows برای مدیریت کامل چرخه عملیاتی فروشگاه: کالا، Batch، موجودی، قیمت قدیم/جدید، انقضا، انبارگردانی، صندوق فروشگاهی (POS)، سود واقعی، پرینتر حرارتی، پیامک و کار آفلاین.

این پروژه پیاده‌سازی سند «Master Blueprint» است (فایل `نقشه_و_بلوپرینت.txt`). اصل بنیادی:

> سیستم نباید چیزی را که از نظر فیزیکی نمی‌تواند تشخیص دهد، به‌عنوان واقعیت قطعی ثبت کند.

بنابراین تفکیک دقیقی بین **موجودی سیستمی / فیزیکی**، **Batch**، **قیمت خرید تاریخی**، **قیمت فروش با تاریخچه**، **تاریخ انقضا** و **فروش** برقرار شده است.

---

## ✨ امکانات (نسخهٔ 1.2.0 — وضعیت تک‌به‌تک ۳۵۰ قابلیت: [`docs/FEATURE_CHECKLIST_350.md`](docs/FEATURE_CHECKLIST_350.md))

| حوزه | امکانات |
|---|---|
| **کالا** | ثبت با بارکد، دسته‌بندی، برند، واحد، حداقل موجودی |
| **Batch** | ورود کالا → Batch جدید (بدون بازنویسی)، قیمت خرید/مصرف‌کننده/فروش، تاریخ تولید/انقضا |
| **قیمت** | Price Version با تاریخچه کامل؛ قیمت قدیم/جدید هم‌زمان قابل فروش |
| **موجودی** | موجودی Product = Σ Batch؛ Stock Movement برای هر تغییر؛ Waste / Adjustment |
| **انبارگردانی** | Stocktaking + تطبیق فیزیکی/سیستمی + Audit |
| **انقضا** | موتور Expiry با سطل‌های قابل تنظیم؛ مسدودسازی فروش کالای منقضی |
| **POS** | اسکن بارکد، انتخاب Batch/قیمت، سود واقعی بر اساس Batch، Checkout تراکنشی، Void، Return |
| **صندوق** | FEFO/FIFO/Hybrid پیشنهاد Batch؛ فروش ترکیبی از چند Batch |
| **گزارش** | داشبورد، فروش، سود Batch، گردش کالا، قیمت قدیم، کم‌موجودی |
| **سخت‌افزار** | درایور ESC/POS واقعی (`tcp://`, USB, اسپولر ویندوز)، رسید فارسی cp1256 با لوگو، کشوی پول `ESC p`، تشخیص اسکنر — [`docs/HARDWARE.md`](docs/HARDWARE.md) |
| **پیامک** | ملی‌پیامک (REST رسمی، خط/الگو) و کاوه‌نگار؛ صف، Retry، فاکتور/بدهی/کوپن/هشدار انبار/گزارش مدیریت — [`docs/SMS.md`](docs/SMS.md) |
| **مشتری و بازاریابی** | مشتری آزاد/ثبت‌شده، حساب دفتری با تسویهٔ جزئی/کامل، جشنواره، کوپن شرطی، تخفیف سطری/فاکتور |
| **چند انبار** | انبارها، محل نگهداری، انتقال موجودی (`TRANSFER`) |
| **بانک کالا** | ۱۹۱ کالای رایج در ۱۳ دسته/۳۰ زیردسته با موجودی صفر + ورود CSV فروشگاه |
| **موبایل** | PWA انبارگردانی با دوربین و صف آفلاین + پروژهٔ اندروید بومی (`mobile-android/`) |
| **به‌روزرسانی** | GitHub یا سرور داخلی، رمز مدیر، پشتیبان خودکار، SHA-256، Rollback — [`docs/UPDATE.md`](docs/UPDATE.md) |
| **امنیت** | JWT، نقش/مجوز گرانولار، Audit Log، تنظیمات رمزنگاری‌شده (بدون Hard-Code) |
| **آفلاین** | پایگاه‌داده محلی SQLite (WAL)، POS بدون اینترنت کار می‌کند |

---

## 🧱 معماری

```
Frontend (Web Panel)  →  REST API (FastAPI)  →  Application Services  →  Domain
        ↓                                          (کسب‌وکار)           (مدل‌ها)
   POS / Dashboard / Inventory                                            ↓
                                                                      Repositories
                                                                          ↓
                                                          Database (SQLite/PostgreSQL)
                                                                          ↓
                                                     External Services / Hardware
```

- **Product ≠ Batch** — یک کالا چند Batch دارد؛ هر Batch قیمت خرید/فروش و تاریخ انقضای خودش را دارد.
- **قیمت تاریخی هرگز بازنویسی نمی‌شود** — هر تغییر، Batch یا Price Version جدید می‌سازد.
- **FIFO/FEFO = سیاست تخصیص، نه واقعیت فیزیکی** — صندوق‌دار Batch واقعی را انتخاب می‌کند.
- **InvoiceItem Snapshot** — قیمت لحظه فروش در فاکتور ذخیره می‌شود و هرگز تغییر نمی‌کند.
- **Checkout اتمیک** — فاکتور + آیتم‌ها + کسر Batch + حرکت موجودی + پرداخت + سود، با هم Commit می‌شوند؛ شکست یکی = Rollback.
- **چاپ هرگز فروش را خراب نمی‌کند** — اگر پرینتر خطا داد، فاکتور PAID می‌ماند و `print_status=FAILED` ثبت می‌شود.

مستندات کامل معماری: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)

---

## 🚀 اجرای سریع (توسعه)

پیش‌نیاز: Python 3.11+

```bash
cd backend
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env             # در صورت نیاز ویرایش کنید

python -m scripts.seed_demo      # داده نمونه (اختیاری)
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

سپس در مرورگر: **http://localhost:8000** (پنل وب) و **http://localhost:8000/docs** (Swagger).

**ورود پیش‌فرض (توسعه):** `admin` / `admin123` — بعد از اولین ورود عوض کنید.

### اجرای تست‌ها

```bash
cd backend
.venv/bin/python -m pytest tests/ -q
```

### مهاجرت‌های پایگاه‌داده (Alembic)

```bash
cd backend
.venv/bin/alembic upgrade head        # اعمال مهاجرت‌ها
.venv/bin/alembic revision --autogenerate -m "..."   # مهاجرت جدید
```

---

## 📁 ساختار مخزن

```
supermarket-system/
├── backend/                 # FastAPI + SQLAlchemy + Alembic
│   ├── app/
│   │   ├── models/          # 26 مدل دامنه (Product, Batch, Invoice, ...)
│   │   ├── services/        # منطق کسب‌وکار (POS, Inventory, Pricing, Expiry, ...)
│   │   ├── routers/         # اندپوینت‌های REST
│   │   ├── config.py        # تنظیمات از محیط (بدون Hard-Code)
│   │   ├── security.py      # JWT / bcrypt / مجوزها
│   │   └── main.py          # اپلیکیشن
│   ├── alembic/             # مهاجرت‌ها
│   ├── tests/               # تست‌های خودکار (21 تست)
│   └── scripts/seed_demo.py # داده نمونه
├── frontend/                # پنل وب (HTML/CSS/JS ساده — بدون وابستگی)
├── installer/               # اسکریپت‌های ساخت نصب‌کننده Windows
├── docs/                    # مستندات
├── .env.example
└── نقشه_و_بلوپرینت.txt      # سند اصلی معماری
```

---

## 🪟 نصب روی Windows

نسخه نهایی به‌صورت `Setup.exe` توزیع می‌شود که Runtime و وابستگی‌ها را خودش مدیریت می‌کند (کاربر نیازی به نصب Python ندارد). راهنما: [`docs/INSTALL.md`](docs/INSTALL.md) و [`installer/`](installer/).

---

## 🔗 API

خلاصه اندپوینت‌ها در [`docs/API.md`](docs/API.md) — مستندات تعاملی کامل در `/docs`.

---

## 📜 مجوز

MIT — به `LICENSE` مراجعه کنید.

## 🧭 نقشه راه

- **v1.2.0 (فعلی)** — همهٔ ۳۵۰ قابلیت فهرست پیاده‌سازی و با ۲۷۴ آزمون خودکار + اسموک UI تأیید شده‌اند؛ مواردی که فقط روی سخت‌افزار/ویندوز/اینترنت واقعی قابل اثبات‌اند در چک‌لیست با برچسب NOT VERIFIED مشخص شده‌اند (`CHANGELOG.md`).
- **بعدی** — همگام‌سازی چندشعبه با سرور مرکزی (§255) و دسترسی امن از اینترنت (§260) که در فهرست به‌عنوان «آینده» تعریف شده‌اند؛ hookهای آن (`sync_jobs`, JWT/CORS) آماده است.

مستندات: [`docs/DATABASE.md`](docs/DATABASE.md) · [`docs/RESOLVER.md`](docs/RESOLVER.md) · [`docs/DIAGRAMS.md`](docs/DIAGRAMS.md) · [`docs/SCREENSHOTS.pdf`](docs/SCREENSHOTS.pdf) · [`docs/INSTALL.md`](docs/INSTALL.md)

---

*این سیستم صرفاً یک «فاکتورزن + جدول موجودی» نیست؛ یک POS آگاه از موجودی (Inventory-Aware) است که ارتباط بین Product، Batch، قیمت خرید، قیمت فروش، انقضا، موجودی فیزیکی/سیستمی، فاکتور، سود و انبارگردانی را حفظ می‌کند.*
