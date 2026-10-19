# پیوست B — فهرست کامل قابلیت‌ها (ویژگی‌های تفصیلی)

> مکمل فصل ۳. برای هر حوزه: نقطه ورود (API/UI)، سطح دسترسی، مدل داده اصلی، محدودیت/مسئله مرتبط. شاهد مسیرها در فصل ۳ آمده و اینجا تکرار نمی‌شود مگر لازم. وضعیت‌ها: فعال / فعال-مشروط / خفته / جزئی.

## B.1 فروش و POS

| قابلیت | نقطه ورود | دسترسی | داده | محدودیت |
|---|---|---|---|---|
| checkout (تخفیف، tender ترکیبی، کوپن، کمپین، نسیه) | `POST /pos/checkout` + UI وب/اندروید/دسکتاپ | pos.sell | invoices, invoice_items, payments, price_versions, batches | سود خط بدون تخفیف فاکتور (I-08) |
| ابطال فاکتور | `POST /invoices/{id}/void` | pos.void | + stock_movements, journal, ledger | — |
| مرجوعی | `POST /returns` | pos.return | returns, batches | I-01/I-02/I-09 |
| رسید PDF/ESC-POS | endpoints رسید + درایور | pos.sell | printer settings | مشروط به سخت‌افزار |
| پیشنهاد پای صندوق | `GET /insights/nudges` | هر کاربر احراز شده | insights (BASKET_NUDGE پذیرفته‌شده) | فقط کالای موجود |
| شیفت خودکار | ضمن `POST /auth/login` | — | shifts | — |
| شماره فاکتور اتمی | داخلی checkout | — | invoice_numbers | کلید روز UTC (I-20) |

## B.2 انبار

| قابلیت | نقطه ورود | دسترسی | داده | محدودیت |
|---|---|---|---|---|
| ورود بچ (خرید) | `POST /batches` | inventory.manage | product_batches (+journal) | بدون سند خرید رسمی (I-22) |
| مصرف FIFO/FEFO/HYBRID | داخلی checkout (تنظیم استراتژی) | — | batches | — |
| تعدیل/ضایعات + سند GL | `POST /inventory/adjust` و waste | inventory.adjust | stock_movements, journal | دلیل = متن آزاد (فصل ۸ ردیف ۵) |
| انبارگردانی | stocktake endpoints | inventory.adjust | stocktakes | — |
| اسکن انقضا + نردبان | worker روزانه + `POST /system/jobs/expiry-scan` | settings.manage (دستی) | batches, insights | — |
| چند انبار | warehouses CRUD | inventory.manage | warehouses | فروش به انبار مقید نیست (I-23) |

## B.3 مشتری و اعتبار

| قابلیت | نقطه ورود | دسترسی | داده | محدودیت |
|---|---|---|---|---|
| پرونده مشتری | customers CRUD | customers.manage | customers | بدون consent/تولد (فصل ۸) |
| ledger نسیه + صورت‌حساب | `GET /customers/{id}/ledger` | customers.view | customer_ledger_entries | وصول در گزارش خالص نیست (F-03) |
| پرداخت/وصول | accounting payment endpoints | accounting.manage | journal, ledger | — |
| سقف اعتبار | فیلد customer | — | — | اعمال در checkout فعال است |
| الگوی مراجعه | `GET /insights/customers/patterns` | reports.view (باید سخت شود) | invoices | I-04/I-05 |

## B.4 بازاریابی

| قابلیت | نقطه ورود | دسترسی | داده | محدودیت |
|---|---|---|---|---|
| CRUD کمپین + قواعد سرور | marketing endpoints + ویزارد اندروید ۸ مرحله + صفحه Qt | marketing.manage | campaigns | بدون بودجه رسمی (فصل ۸ ردیف ۶) |
| کوپن (سقف، مسدودسازی، شمارشی) | coupons endpoints | marketing.manage | coupons, redemptions | — |
| آمار کمپین | `GET /marketing/stats` | marketing.manage | redemptions, invoices | فروش دوره ≠ افزایشی (F-05) |
| آزمایش A/B | **ندارد** | — | experiments | خفته (I-10) |

## B.5 حسابداری

| قابلیت | نقطه ورود | دسترسی | داده | محدودیت |
|---|---|---|---|---|
| GL دوبل + COA | داخلی سرویس‌ها + endpoints دفتر | accounting.view | accounts, journal_* | I-02 در مرجوعی |
| چک‌ها | cheque endpoints | accounting.manage | cheques | در CASHFLOW استفاده می‌شود |
| جلسه صندوق | open/close endpoints | accounting.manage | cash_sessions | I-03 |
| هزینه/دسته/دوره مالی | expenses endpoints | accounting.manage | expenses, fiscal_periods | در «سود» گزارش نیست (F-02) |
| تامین‌کننده | suppliers CRUD | accounting.manage | acc_suppliers | ۵ فیلد؛ بدون lead-time (I-22) |
| گزارش تراز/مغایرت | accounting reports | accounting.view | journal | — |

## B.6 هوش فروشگاه

| قابلیت | نقطه ورود | دسترسی | داده | محدودیت |
|---|---|---|---|---|
| ۷۸ تحلیل‌گر (۶ گروه) | worker ۱۵دقیقه + `POST /insights/run` | run: reports.view (باید سخت شود I-18) | همه دامنه‌ها | I-05/06/08/09/19 |
| کارت‌ها + چرخه عمر | `GET /insights` (+filters) | reports.view + KIND_PERMS | insights | I-04 برای انواع حساس |
| accept/snooze/dismiss | endpoints مربوطه | settings.manage | insights | — |
| ۲۴ action اجرایی | ضمن accept | settings.manage | مقصد هر action | بدون PO (I-22) |
| سنجش اثر + health_scan | `POST /insights/{id}/measure`, health | reports.view / settings.manage | insights, invoices | observational (تا F-08) |
| plan/impact/summary | `GET /insights/plan`, `/summary` | reports.view (باید سخت شود) | forecast, insights | I-04 |
| پیش‌بینی/کالیبراسیون | داخلی + `/plan/learn` | reports.view | insights نتایج | سری تجمیعی فقط (F-04) |
| کیفیت داده + دروازه | `POST /insights/health-scan`, داخلی run | settings.manage | ۲۰ بررسی | شکاف‌های §۴٫۷ |
| guides | `GET /insights/kinds/{k}/guide` | reports.view | insight_guides | ۱۳/۷۹ (I-11) |
| گزارش/مشاور AI | `GET /insights/ai/report`, `POST /insights/ai/advise` | reports.view / settings.manage | ai_narrator + LLM بیرونی | اختیاری؛ اعداد LLM دور ریخته می‌شود |
| NEXT_BEST_ACTION | کارت opportunity | reports.view | opportunity.py | آستانه ۱۰۰k/ماه |
| موتور اندروید | بومی (offline) | — | ai_insights محلی | ۳۴/۷۸ (I-12) |

## B.7 گزارش‌ها و داشبورد

| قابلیت | نقطه ورود | دسترسی | داده | محدودیت |
|---|---|---|---|---|
| KPI داشبورد (روز تهران) | `GET /reports/dashboard` | reports.view | invoices | I-08/I-09 |
| گزارش فروش/سود per کاربر | reports endpoints | reports.view + دامنه view_all | invoices | I-08/I-09 |
| سود per بچ / کالاهای برتر | reports endpoints | reports.view (+سانسور بها با pricing.view_cost) | batches, items | I-08 |
| عملکرد صندوق‌دار | reports/performance | reports.view_all | audit, invoices | انصاف پرسنلی (§۵٫۳) |
| ویجت‌های per-user | widgets endpoints | احراز شده | widgets | — |

## B.8 سیستم/امنیت/ارتباطات

| قابلیت | نقطه ورود | دسترسی | داده | محدودیت |
|---|---|---|---|---|
| کاربران/نقش‌ها | users/roles endpoints | users.manage | users, roles | — |
| ورود/throttle/blocklist | auth endpoints | عمومی (throttle دارد) | users | I-17 |
| ممیزی عملیات | `GET /audit` | audit.view | audit_logs | — |
| بکاپ/بازیابی/factory reset | system endpoints | settings.manage | فایل DB | — |
| به‌روزرسانی نرم‌افزار | update endpoints | settings.manage | updater + سرور/GitHub | مشروط شبکه |
| لایسنس | setup/license endpoints | عمومی تا فعال‌سازی | license vault + HWID | مشروط سرور لایسنس |
| اعلان‌ها | notifications endpoints | احراز شده | notifications | — |
| sync LAN/ابر | mobile/cloud endpoints | settings.manage (ابر) | sync_jobs, Drive appData | opt-in؛ redaction دارد |
| SMS | sms endpoints + worker | sms.send | sms_queue | بدون consent (I-24) |
| پشتیبانی/تیکت/رله | support endpoints + worker | احراز شده | support_tickets | مشروط رله |
| diagnostics/dev mode | endpoints مربوطه | diagnostics.view / dev.mode | — | dev پشت permission |
| ویزارد راه‌اندازی | setup endpoints | عمومی تا setup_done | system_settings | قفل ۴۰۹ پس از اتمام |
| حالت دمو | `POST /system/demo/load` | settings.manage | demo_store | نگهبان‌های مقیاس |
