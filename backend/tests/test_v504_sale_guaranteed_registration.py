# -*- coding: utf-8 -*-
"""build-504 — بازسازی ساختاری ثبت فروش در موتور محلی (پایان وصله‌کاری).

قرارداد ساختاری جدید `/pos/checkout` محلی — هر مورد با تست قفل می‌شود:
۱) فاز ۰: کل بارِ فروش ابتدا با sanitizePayload بازگشتی پاک می‌شود؛ پس از آن هیچ
   سریالایزی (toString/put) روی دادهٔ نشسته نمی‌تواند «Forbidden numeric value» بدهد.
۲) فاز ۲: شکست «فنی» راستی‌آزمایی کوپن/جشنواره هرگز فروش را نمی‌بندد — با اعداد خود
   صندوق ادامه می‌یابد (فقط خطای قاعده‌ای ApiError واقعی است).
۳) فاز ۳: شکست نوشتن با کد SALE_WRITE و پیام فارسی مشخص، جدا از بقیهٔ خطاها.
۴) فاز ۴: اگر ساخت پاسخ (invoiceOut) به هر دلیلی شکست بخورد، فاکتورِ ثبت‌شده با
   پاسخ مینیمال برمی‌گردد — فروش هرگز قربانی JSON‌سازی پاسخ نمی‌شود.
۵) rows(): سلول REAL نامعتبر (Infinity ذخیره‌شدهٔ قدیمی) صفر می‌شود، نه ورود به JSON.
۶) catch-all موتور: محل خطا (کلاس:خط) در خود پیام می‌آید — پایان خطاهای بی‌نشانی.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
JAVA = ROOT / "mobile-android" / "app" / "src" / "main" / "java" / "ir" / "khajavy" / "supermarket"


def _local() -> str:
    return (JAVA / "Local.java").read_text(encoding="utf-8")


def test_checkout_is_phased_and_sanitized_before_anything():
    local = _local()
    start = local.index('if ("checkout".equals(seg[1])) {')
    block = local[start:local.index('if ("kiosk".equals(seg[1])) {', start)]
    # فاز ۰ پیش از هر محاسبه/JSON
    assert block.index("sanitizePayload(b)") < block.index("double gross"), "پاک‌سازی عمیق قبل از هر چیز"
    assert "EMPTY_CART" in block
    # فاز ۲: خطای فنی مزایا مسدودکننده نیست
    assert "coupon revalidation skipped" in block and "campaign revalidation skipped" in block
    assert 'couponDiscount = Math.max(0, fin(safe.optDouble("coupon_discount", 0)))' in block
    assert 'campaignDiscount = Math.max(0, fin(safe.optDouble("campaign_discount", 0)))' in block
    # فاز ۳: شکست نوشتن کد مستقل دارد
    assert "SALE_WRITE" in block and "نوشتن فروش در حافظهٔ گوشی ناموفق بود" in block
    # فاز ۴: پاسخ مینیمال در صورت شکست invoiceOut — فاکتور می‌ماند
    assert "invoiceOut degraded response" in block and '"local_no", no, "invoice_number", no' in block


def test_rows_never_feeds_nonfinite_reals_into_the_engine_json():
    local = _local()
    rows = local[local.index("public static List<JSONObject> rows(String sql, Object... a) {"):]
    rows = rows[:rows.index("public static JSONObject one(")]
    assert "Double.isFinite(dv) ? dv : 0" in rows, "سلول REAL نامعتبر صفر می‌شود"


def test_engine_errors_carry_source_location():
    """catch-all: پیام = علت + «@ کلاس:خط» — دیگر خطای بی‌نشانی ممکن نیست."""
    local = _local()
    assert "getStackTrace()" in local and '" @ "' in local, "شناسنامهٔ محل خطا"


def test_business_rules_are_still_enforced():
    """قواعد واقعی کسب‌وکار سرِ جایشان‌اند — ضدرسنه به معنای بی‌قاعده‌بودن نیست."""
    local = _local()
    block = local[local.index('if ("checkout".equals(seg[1])) {'):]
    block = block[:block.index('if ("kiosk".equals(seg[1])) {')]
    for rule in ("INVALID_DISCOUNT", "COUPON_INVALID", "CAMPAIGN_INVALID", "CAMPAIGN_NOT_STACKABLE", "PAYMENT_MISMATCH", "BAD_TOTAL"):
        assert rule in block, f"قاعدهٔ {rule} حفظ شده باشد"
