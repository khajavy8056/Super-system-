# پیوست C — ماتریس داده: موجود، استفاده‌شده، استفاده‌نشده

## C.1 داده موجود و وضعیت استفاده

| جدول/داده | کلیدهای تحلیلی | استفاده فعلی | استفاده بالقوه (ارجاع) |
|---|---|---|---|
| invoices + items | created_at, total, discount, customer_id, created_by, status | فروش/سود گزارش‌ها، ctx هوش (فقط PAID — I-09)، سنجش اثر | خالص مرجوعی (I-09)، سود خالص (I-08/F-02)، الگوی created_by (F-11) |
| payments | tender, amount per فاکتور | نمایش رسید، گزارش tender | CASHFLOW واقعی (F-00b)، سهم نقد/کارت/نسیه، هزینه مبادله |
| returns | qty, refund_amount, reason (متن آزاد), created_by | سقف تجمعی، وضعیت فاکتور | نرخ/علت مرجوعی per محصول-کاربر (فصل ۸ ردیف ۵)، کیفیت تامین‌کننده (در SUPPLIER استفاده شده) |
| product_batches | buy_price, received_at, expiry, supplier_id, warehouse_id, current_qty | FEFO، حاشیه، supplier_lead، EXPIRY | lead-time رسمی (F-01)، drift بهای خرید (F-12)، ریسک ناموجودی (F-07) |
| stock_movements | type (SALE/RETURN/WASTE/ADJUSTMENT/…), qty, user_id | دفتر موجودی، DQ یتیم | نرخ آب‌رفت (F-09)، الگوی تعدیل per کاربر (F-11) |
| price_versions | نوع PURCHASE/SALE, effective, ACTIVE | قیمت‌گذاری، elasticity (SALE) | drift خرید (F-12) — نوع PURCHASE امروز تحلیل نمی‌شود |
| customers | phone, credit_limit, created_at | VIP/CHURN/RFM-طور ضمنی، نسیه | بخش‌بندی RFM رسمی (F-06)، consent (نیازمند فیلد) |
| customer_ledger_entries | amount علامت‌دار, created_at, balance_after | صورت‌حساب، LOSS_PREV | سنین‌بندی مطالبات و روزهای وصول (F-03) |
| campaigns + coupons + redemptions | benefit مبلغ, invoice, customer, زمان | آمار کمپین، سقف‌ها | ROI افزایشی (F-05)، اثر کوپن خرید-بعدی بر بازگشت |
| accounts + journal_* | کد حساب, مبلغ, طرف | P&L/تراز، چک‌ها در CASHFLOW | سود خالص از GL (متقاطع با F-02)، کنترل داخلی (unbalanced) |
| expenses + categories + fiscal_periods | مبلغ, دسته, دوره | گزارش هزینه | سهم هزینه در سود خالص (F-02)، روند هزینه per فروش |
| cheques | direction, status, due_date | CASHFLOW (PENDINGها) | ریسک چک برگشتی (نیازمند نتیجه برگشت — ثبت دستی) |
| cash_sessions | opening/closing float, تفاوت, created_by | تسویه صندوق | الگوی مغایرت per کاربر (F-11) — امروز فقط تعدیل می‌خورد |
| shifts + attendance + payroll | ساعت, کاربر, مبلغ | HR عملیاتی | هزینه کار per سود/شیفت (F-10) |
| audit_logs | action, user, entity, before/after | DQ، ops group (ابطال/کشو)، ممیزی | قواعد کنترل داخلی ترکیبی (F-11) |
| insights (خود جدول) | kind, status, expected_gain, measured_gain, baseline/result | چرخه عمر کارت | فرا-تحلیل موتور (فرصت ۹ فصل ۷) |
| stocktakes | شمارش vs سیستم | اصلاح موجودی | دقت موجودی per دسته (اعتماد نقطه سفارش) |
| sms_queue / support_tickets / sync_jobs | وضعیت, زمان | عملیات ارسال/پشتیبانی/sync | نرخ تحویل SMS، الگوی مشکلات پشتیبانی (کم‌ارزش‌تر) |
| achievements / announcements / widgets | تعامل کاربر | HR/UX | سنجش پذیرش قابلیت‌ها (ضعیف) |
| products (gallery, brand, category) | تصویر, برند | نمایش، گروه‌بندی تحلیل‌ها | merchandising تصویرمحور (آینده) |

## C.2 داده موردنیاز برای قابلیت‌های جدید (خلاصه فصل ۸)

| داده | برای | نوع افزودن | هزینه |
|---|---|---|---|
| purchase_orders (+items, وضعیت) | F-01/F-07 | جدول جدید (مهاجرت افزودنی) | متوسط |
| supplier/product lead_time_days | F-01/F-07 | فیلد اختیاری + استخراج fallback | کم |
| customer.sms_consent | F-03/F-06 پیامکی | فیلد bool | کم |
| تقویم تعطیلات/رویداد شمسی | F-17 | seed CSV + CRUD رویداد | کم |
| کد دلیل enum مرجوعی/ضایعات | تحلیل علل | فیلد اختیاری کنار متن آزاد | کم |
| campaign.budget / پنجره شاهد | F-05 | فیلد اختیاری + منطق موتور | کم |
| رویداد shelf-check | planogram (حذف از نسخه بعد) | تسک موبایل | متوسط |
| قیمت رقبا | بنچمارک خارجی PRICE_GAP | ورود دستی | متوسط |
| store_daily / product_daily | همه سری‌های زمانی مقیاس‌پذیر | جداول مشتق + worker | متوسط |
| warehouse_id روی Invoice | F-19 مشروط | تغییر مدل | زیاد |
| رقم قبوض per دوره | دقت F-02 | انضباط ورود expenses | صفر |

## C.3 ارزیابی کیفیت داده (وضع فعلی)

- **نقاط قوت:** DQ gate با ۲۰ بررسی + مسدودسازی روی negative_stock/duplicate_invoice_number؛ ledgerهای balance_after دار؛ snapshot قیمت/کمپین روی فاکتور (تاریخ بازنویسی‌ناپذیر)؛ timeservice با NTP.
- **ریسک‌های کیفیت:** فیلدهای اختیاری پر‌نشدنی در عمل (supplier_id روی بچ — supplier_lead بدون آن خروجی نمی‌دهد؛ expiry تاریخ — نردبان بدون آن risk_only می‌شود؛ دلیل متنی آزاد)؛ تنسیخ تعریف سود (I-08)؛ دوگانگی روز (I-05). جمع‌بندی: **زیرساخت کیفیت داده خوب است، انضباط ورود داده نقطه ضعف عملیاتی است** → پیشنهاد: «امتیاز کامل‌بودن پرونده» per محصول/تامین‌کننده در UI (کدام فیلدهای تحلیلی خالی‌اند و چه قابلیتی را قفل کرده‌اند) — این خود یک کارت DQ جدید است.
