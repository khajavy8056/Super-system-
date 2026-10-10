# -*- coding: utf-8 -*-
"""build-501 — گزارش‌های نسخهٔ 1.0.500 روی Xiaomi/API 36:

۱) فروش ثبت نمی‌شد: toast «خطای داخلی گوشی: Forbidden numeric value: NaN» —
   ریشه: ستون‌های NULL جشنواره/کوپن در SQLite موتور محلی با ``optDouble`` تک‌آرگومان
   خوانده می‌شد → NaN از همهٔ گاردهای مقایسه‌ای عبور می‌کرد → binding دیتابیس می‌ترکید.
۲) کرش OOM در ``Pos.pickCustomer`` → ``Ui.item`` → ``Icons.view``.
۳) داشبورد هنوز خلاف تصاویر مرجع (ترتیب کارت‌ها) بود.

این تست‌ها هر سه قرارداد را در هر دو سمت (جاوا و سرور) قفل می‌کنند.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
JAVA = ROOT / "mobile-android" / "app" / "src" / "main" / "java" / "ir" / "khajavy" / "supermarket"


def _java(name: str) -> str:
    return (JAVA / name).read_text(encoding="utf-8")


# --- ۱) NaN در زنجیرهٔ فروش محلی خنثی می‌شود -----------------------------------

def test_local_engine_sanitizes_every_campaign_and_coupon_number():
    """ریشهٔ «Forbidden numeric value: NaN»: خواندن ستون‌های NULL با optDouble تک‌آرگومان."""
    local = _java("Local.java")
    assert "static double fin(double v)" in local, "هلپر NaN→۰ در موتور محلی"
    assert "static double optFin(" in local, "خوانندهٔ مصون optDouble"
    # سازندهٔ آفر جشنواره‌ها و اعتبارسنج کوپن دیگر عدد NULL را خام نمی‌خوانند
    assert 'optFin(campaign, "discount_value", 0)' in local
    assert 'optFin(campaign, "max_discount", 0)' in local
    assert 'optFin(coupon, "discount_value", 0)' in local
    assert 'optFin(coupon, "max_discount", 0)' in local
    assert 'optFin(coupon, "min_purchase", 0)' in local
    # offerDiscount خودش ورودی‌ها را مصون می‌کند (دفاع در مبدأ محاسبه)
    offer = local[local.index("static double offerDiscount"):local.index("static boolean offerFlag")]
    assert "value = fin(value); max = fin(max); amount = fin(amount);" in offer


def test_pos_checkout_never_binds_nonfinite_numbers_to_sqlite():
    """گارد نهایی پیش از Db.localSale: NaN دیگر «خطای داخلی گوشی» نمی‌سازد."""
    local = _java("Local.java")
    checkout = local[local.index('if ("checkout".equals(seg[1]))'):]
    checkout = checkout[:checkout.index('if ("kiosk".equals(seg[1]))')]
    assert "BAD_TOTAL" in checkout and "Double.isFinite(total)" in checkout, "گارد مبلغ نهایی ۴۲۲"
    assert 'fin(item.optDouble("price", 0))' in checkout, "قیمت ردیف مصون"
    assert 'fin(coupon.optDouble("discount", 0))' in checkout, "تخفیف کوپن مصون"
    assert 'fin(chosenCampaign.optDouble("discount", 0))' in checkout, "تخفیف جشنواره مصون"
    assert 'optDouble("amount", 0)' in checkout, "پرداخت‌ها با پیش‌فرض امن"
    db = _java("Db.java")
    assert "مبلغ فاکتور نامعتبر است" in db, "دفاع در عمق Db.localSale"


def test_client_side_benefits_are_nan_proof_and_errors_are_persian():
    """کلاینت: تخفیف کوپن/جشنواره هرگز NaN نمی‌شود و پیام خام org.json نمایش داده نمی‌شود."""
    sales = _java("SalesScreens.java")
    assert "static double finBenefit(" in sales
    assert 'finBenefit(selected.optDouble("discount", 0))' in sales
    assert 'finBenefit(auto.optDouble("discount", 0))' in sales
    assert 'finBenefit(validation.optDouble("discount", 0))' in sales
    assert "Forbidden numeric" in sales, "پیام خام به فارسیِ مفهوم ترجمه می‌شود"


# --- ۲) OOM در انتخاب مشتری ------------------------------------------------------

def test_customer_picker_is_bounded_and_memory_resilient():
    """بازسازی کل دفترچه در هر حرف تایپ → OOM؛ اکنون debounce + سقف + تخلیهٔ کش."""
    sales = _java("SalesScreens.java")
    pick = sales[sales.index("void pickCustomer()"):]
    pick = pick[:pick.index("void newCustomer(")]
    assert "postDelayed" in pick and "removeCallbacks" in pick, "debounce ورودی جست‌وجو"
    assert "Math.min(30, found.size())" in pick, "سقف ۳۰ ردیف"
    assert "OutOfMemoryError" in pick and "evictAll" in pick, "آزادسازی کش در فشار حافظه"
    ui = _java("Ui.java")
    assert "TILES" in ui and "tileCacheClear" in ui, "کش کاشی حرف"
    manifest = (ROOT / "mobile-android" / "app" / "src" / "main" / "AndroidManifest.xml").read_text(encoding="utf-8")
    assert 'android:largeHeap="true"' in manifest
    images = _java("Images.java")
    assert "RGB_565" in images, "نصف‌شدن حافظهٔ بیت‌مپ‌های کاتالوگ"


# --- ۳) داشبورد مطابق تصاویر مرجع ------------------------------------------------

def test_dashboard_reference_order_kpis_actions_charts_invoices():
    """ترتیب مرجع: KPI → عملیات سریع → نمودار خطی → دونات+پرفروش‌ها → فاکتورها؛ اطلاعیه/سامانه در انتها."""
    screens = _java("Screens.java")
    render = screens[screens.index("private void render(JSONObject d, double[] loc) {"):]
    render = render[:render.index("addSalesLineChart(String title")]
    i_kpi = render.index('Ui.tile(c, "trend", Ui.GREEN, "فروش امروز"')
    i_actions = render.index('renderManagementActions(profile);')
    i_line = render.index("addSalesLineChart(")
    i_donut = render.index("dailySalesDonutCard(")
    i_invoices = render.index("addRecentInvoiceCard(")
    i_ann = render.index("addAnnouncementsAndUpdates();")
    assert i_kpi < i_actions < i_line < i_donut < i_invoices < i_ann, "ترتیب مرجع"
    assert "عملیات سریع فروشگاه" in screens, "کارت اکشن‌های مرجع"
    assert "گزارش فروش روزانه" in screens and "Chart.donut" in screens, "دونات روزانه"
    assert "محبوب‌ترین محصولات" in screens, "پرفروش‌ترین‌ها"
    # دو تیکه نبودن: بخش دادهٔ قبلی حذف و یک‌جا جایگزین می‌شود (build-500 حفظ می‌شود)
    assert "dash_cache_v1" in screens


# --- ۴) سرور: NaN در ورودی تسویه‌حساب ۴۲۲ است، نه ۵۰۰ ------------------------------

def test_checkout_with_nan_numbers_is_rejected_not_crashed(client, auth_headers, milk):
    """پیشنهاد متقابل: JSON حاوی NaN (پایتون آن را parse می‌کند) باید ۴۲۲ بدهد نه ۵۰۰."""
    body = {
        "items": [{"product_id": milk["id"], "quantity": float("nan"), "discount": 0}],
        "payments": [{"method": "CASH", "amount": float("inf")}],
        "open_drawer": False,
    }
    r = client.post("/api/pos/checkout", headers={**auth_headers, "Content-Type": "application/json"},
                    content=json.dumps(body, allow_nan=True).encode("utf-8"))
    assert r.status_code == 422, f"NaN باید ۴۲۲ شود، نه {r.status_code}: {r.text[:200]}"


def test_dashboard_payload_has_reference_contract_keys(client, auth_headers):
    """کلیدهایی که UI مرجعِ موبایل می‌خواند همیشه در /reports/dashboard حاضرند."""
    r = client.get("/api/reports/dashboard", headers=auth_headers)
    assert r.status_code == 200, r.text
    data = r.json()
    for key in ("sales", "trend", "top_products", "recent_invoices", "today_by_payment", "inventory"):
        assert key in data, f"کلید داشبورد {key} غایب است"
    # هیچ NaN در خروجی داشبورد سریالایز نمی‌شود (JSON سالم برای گوشی)
    raw = r.text
    assert "NaN" not in raw and "Infinity" not in raw
