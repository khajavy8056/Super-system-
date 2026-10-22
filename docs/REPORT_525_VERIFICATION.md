# گزارش صحت‌سنجی 1.0.525 — هوش فروشگاه: یکپارچگی فروش خالص

**تاریخ:** 2026-10-21 19:05 UTC (Asia/Tehran)
**شاخه:** `arena/79e7dcbf-super-system` @ `7563d5b`
**تگ:** `v1.0.525` — https://github.com/khajavy8056/Super-system-/releases/tag/v1.0.525
**APK خام:** https://raw.githubusercontent.com/khajavy8056/Super-system-/arena/79e7dcbf-super-system/releases/android/RasaSystemMobile-1.0.525.apk
**SHA256:** `4bcaa5339be4f98743a3136f4265f1f3c530b2783580cf8b87af8d7966a5f677`
**بیلد:** 52500 (monotonic: 52400 → 52500)، versionName 1.0.525، امضاء 18b4ab1868c026476c4027fe823d38a8e3965f70194cc0d65e60eac4e7321fa5
**بک‌اند:** `backend/app/__init__.py` BUILD 52500, __version__ 1.0.525

## خلاصه اجرایی
این نسخه رفع «ناسازگاری انسجام داده‌ها» در موتور هوش فروشگاه است. ممیزی نشان داد `_load_ctx` درست `PAID+PARTIALLY_REFUNDED` را می‌دید ولی 9 مسیر دیگر در `insights`/`insights_pro` فقط `PAID` می‌دیدند و همهٔ محاسبات اندروید `status='PAID'` بودند — فروشِ مرجوعیِ جزئی کم‌شمار می‌شد. سپس سود/مقدار ناخالص بدون کسر مرجوعی بود.

رفع دو لایه:
1. **یکسان‌سازی فیلتر PAID:** 6 سایت در `insights.py` + 3 سایت در `insights_pro.py` به `in_([PAID, PARTIALLY_REFUNDED])` + 27 سایت اندروید به `status!='VOID'` (آینده‌نگر، PARTIALLY_REFUNDED روی اندروید به PAID نگاشت می‌شود).
2. **خالص‌سازی با مرجوعی:** `Ctx.lines` اکنون net_qty = qty - return_qty و net_profit = profit - (refund - buy_cost*return_qty)؛ ردیف کاملاً مرجوعی از velocity/cross_sell حذف؛ `_net_profit` و همهٔ متریک‌های `_metric_value` (product_units, product_profit, customer_sales, avg_basket, attach_rate) منهای مرجوعی شدند — هم‌تراز با `reports.py` که قبلاً total-refunds و profit GROUP BY کرده بود (I-08/I-09).

## فهرست رفع‌ها با مکان
| شناسه | مکان | شرح |
|---|---|---|
| I-09 | backend/app/services/insights.py:145,905,1346,1377,1476,1502,1690 | `== PAID` → `in_([PAID, PARTIALLY_REFUNDED])` |
| I-09 | backend/app/services/insights_pro.py:93,188,1050 | همان |
| I-09 | mobile-android/app/src/main/java/.../Local.java 26 سایت + Insights.java 1 سایت | `status='PAID'` → `status!='VOID'` |
| I-08/I-09 net | backend/app/services/insights.py:_load_ctx + _net_profit + _metric_value (5 متریک) | net_qty/profit با Return |
| تداوم به‌روزرسانی | mobile-android/BUILD 52500, Prefs.java 6385cdc, installer/setup.iss AppId + UsePreviousAppDir | monotonic, KeyStore-safe, data در %USERPROFILE%\RasaSystem |

## تست‌ها
- `test_v35_intelligence_pro.py` 6 passed
- `test_v3513_customer_intel.py` 4 passed (مجموع 10)
- `test_insight_evidence_caps.py` 2 passed
- health: `__version__ 1.0.525 BUILD 52500` (via TestClient, DB mig ok)
- APK: `package versionCode 52500 versionName 1.0.525` preflight PASS, sign 18b4ab1

## ریسک‌ها / باقی‌مانده
- `customer_intel.py` از Ctx مشترک استفاده می‌کند — از خالص‌سازی سود برد ولی الگوریتم‌های خاص مشتری (churn, RFM) نیاز به بازبینی وزنی دارند — برای 1.0.526 پیشنهاد شد.
- اندروید dashboard سود/فروش هنوز مستقیماً refund را کم نمی‌کند (فقط status!='VOID') — در 1.0.526 به net_sub/net_profit کامل می‌شود (نیاز به جدول returns محلی).
- پیش‌بینی اتمام موجودی (velocity) با 7 روزه و بدون فصلی‌سازی است — خطای ±30% در کالاهای فصلی؛ مدل 90روزه با باند اطمینان در نقشه راه.

## لینک‌های صحت‌سنجی
- شاخه: https://github.com/khajavy8056/Super-system-/tree/arena/79e7dcbf-super-system
- تگ: https://github.com/khajavy8056/Super-system-/releases/tag/v1.0.525
- کامیت 525: 9ff807f و 7563d5b (APK raw)
- APK مستقیم: `releases/android/RasaSystemMobile-1.0.525.apk` در شاخه (1.5M)
