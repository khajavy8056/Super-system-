# -*- coding: utf-8 -*-
"""build-502 — پایان مطلق کلاس خطای «Forbidden numeric value: NaN» در ثبت فروش.

گزارش کاربر روی v1.0.501 (همان گوشی): فروش سادهٔ نقدی هنوز شکست می‌خورد. ریشهٔ دوم:
``issueLocalAutoCoupons`` پس از «هر» فروش، کوپن خودکار جشنواره‌ها را می‌نویسد و
``optDouble`` تک‌آرگومان روی ستون‌های NULL (discount_value/min_purchase) → NaN →
bind دیتابیس → rollback کل فروش. هر دو منبع (خواندن و نوشتن) باید برای همیشه بسته باشند.

قراردادهای این فایل:
۱) در هر چهار فایل زنجیرهٔ فروش/حقوق، هیچ ``optDouble("key")`` تک‌آرگومانی مجاز نیست —
   تست با regex کل فایل‌ها را می‌کَند؛ یعنی هیچ NaN جدیدی نمی‌تواند وارد این مسیرها شود.
۲) سد نهایی: ``Db.localSale`` کل بارِ فروش را با ``Local.sanitizePayload`` بازگشتی پاک می‌کند
   (هر دو مسیر: موتور محلی و ارسال مستقیم).
۳) شکست صدور کوپن خودکار هرگز فروش را rollback نمی‌کند.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
JAVA = ROOT / "mobile-android" / "app" / "src" / "main" / "java" / "ir" / "khajavy" / "supermarket"
SALE_CHAIN = ["Local.java", "Db.java", "SalesScreens.java", "HrLocal.java"]
_SINGLE_ARG = re.compile(r'optDouble\("([a-zA-Z_0-9]+)"\)')


def _java(name: str) -> str:
    return (JAVA / name).read_text(encoding="utf-8")


def test_no_single_arg_optdouble_anywhere_in_the_sale_chain():
    """هیچ خوانش عددیِ بی‌پیش‌فرضی در زنجیرهٔ فروش مجاز نیست — به‌ازای هر کلید، پیش‌فرض امن."""
    offenders = []
    for name in SALE_CHAIN:
        for match in _SINGLE_ARG.finditer(_java(name)):
            offenders.append(f"{name}: optDouble(\"{match.group(1)}\") بدون پیش‌فرض")
    assert not offenders, "خوانش‌های NaN-زا: " + "؛ ".join(offenders)


def test_auto_coupon_issue_is_null_safe_and_never_blocks_a_sale():
    """ریشهٔ دومِ ۵۰۱: نوشتن کوپن خودکار با مقدار NaN → rollback فروش."""
    local = _java("Local.java")
    issue = local[local.index("static JSONObject issueLocalAutoCoupons"):]
    issue = issue[:issue.index("static String issuedCouponCodesForInvoice")]
    assert 'campaign.optDouble("discount_value", 0)' in issue
    assert 'campaign.optDouble("min_purchase", 0)' in issue
    db = _java("Db.java")
    assert "auto-coupon issue skipped" in db, "شکست کوپن خودکار نباید فروش را بیندازد"
    assert "try { issuedCodes = Local.issueLocalAutoCoupons" in db


def test_localsale_sanitizes_the_whole_payload_recursively():
    """سد نهایی: هر دو مسیر ثبت فروش از پاک‌ساز بازگشتی می‌گذرند."""
    local = _java("Local.java")
    assert "static JSONObject sanitizePayload(" in local
    assert "static JSONArray sanitizeArray(" in local
    assert "instanceof Double" in local and "Double.isFinite" in local
    db = _java("Db.java")
    sale = db[db.index("public static String localSale("):]
    sale = sale[:sale.index("public static JSONObject localInvoicePayload")]
    assert "payload = Local.sanitizePayload(payload)" in sale
    assert "مبلغ فاکتور نامعتبر است" in sale  # گارد total (build-501، حفظ می‌شود)


def test_cart_total_math_is_default_safe():
    """محاسبهٔ جمع سبد و نمایش‌های POS با پیش‌فرض امن — NaN دیگر به total()/payableTotal() نمی‌رسد."""
    sales = _java("SalesScreens.java")
    amount = sales[sales.index("double amountBeforeBenefits()"):]
    amount = amount[:amount.index("JSONObject campaignRequest()")]
    assert 'optDouble("quantity", 0)' in amount
    assert 'optDouble("price", 0)' in amount
    assert 'optDouble("discount", 0)' in amount
