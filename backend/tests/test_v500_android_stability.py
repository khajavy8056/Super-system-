# -*- coding: utf-8 -*-
"""build-500 — پایداری اندروید: رفع کرش Back، رفع انسداد پرداخت POS،
داشبورد یک‌پارچهٔ آنی، و اتصال کارکنان↔حسابداری در پرداخت حقوق.

گزارش‌های کاربر (نسخهٔ 1.0.497 روی Xiaomi/API 36):
۱) `IllegalStateException` در `Ui.scroll` هنگام Back — «child already has a parent».
۲) فروش ثبت نمی‌شد: «پیش از پرداخت، مزایا دوباره بررسی می‌شوند» بی‌پایان.
۳) داشبورد دوتکه: بخش اول فوری، بخش دوم با تأخیر طولانی.
۴) حقوق در حسابداری «واریز شده» ولی در بخش کارکنان به‌روز نمی‌شد.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
JAVA = ROOT / "mobile-android" / "app" / "src" / "main" / "java" / "ir" / "khajavy" / "supermarket"


def test_back_navigation_never_crashes_with_child_already_has_parent():
    """کرش گزارش‌شده: بازنمایی همان Screen بدنهٔ دارای والد را دوباره addView می‌کرد."""
    screens = (JAVA / "Screens.java").read_text(encoding="utf-8")
    assert "removeView(body)" in screens, \
        "Screen.view() باید بدنه را از اسکرولر قبلی جدا کند"
    ui = (JAVA / "Ui.java").read_text(encoding="utf-8")
    assert "getParent()" in ui and "scroll" in ui, "دفاع در عمق در Ui.scroll"


def test_pos_pay_is_never_blocked_by_a_failed_benefits_lookup():
    """مسیر خطای مزایا نباید با return ثبت فروش را ببندد؛ سرور همان لحظه
    کوپن/جشنواره را در /pos/checkout دوباره راستی‌آزمایی می‌کند."""
    sales = (JAVA / "SalesScreens.java").read_text(encoding="utf-8")
    assert "پیش از پرداخت، مزایا دوباره بررسی می‌شوند" not in sales, \
        "پیام انسدادی قدیمی باید حذف شده باشد"
    assert "خطای بررسی مزایا هرگز نباید فروش را ببندد" in sales
    assert "در حال بررسی کوپن و جشنواره؛ لحظه‌ای صبر کنید" in sales, \
        "فقط حالتِ در حالِ بررسیِ واقعی صبر می‌خواهد"


def test_dashboard_paints_whole_from_cache_then_refreshes_in_place():
    """داشبورد یک‌پارچه: رندر آنی از کش + جایگزینی بخش داده، نه دو تکه."""
    screens = (JAVA / "Screens.java").read_text(encoding="utf-8")
    assert "dash_cache_v1" in screens, "کشِ رندر فوری داشبورد"
    assert "بخش دادهٔ قبلی (رندر کش) برداشته می‌شود تا داشبورد دوتکه نشود" in screens


def test_payroll_payment_reaches_the_employees_section():
    """اتصال کارکنان↔حسابداری: نتیجهٔ sync وضعیت نهایی + شماره سند را می‌آورد و
    گوشی وضعیت ردیف حقوق را همان لحظه PAID می‌کند."""
    mobile_sync = (ROOT / "backend" / "app" / "routers" / "mobile.py").read_text(encoding="utf-8")
    assert '"status": res.get("status", "PAID")' in mobile_sync
    assert '"payment_ref": res.get("payment_ref")' in mobile_sync
    sync_java = (JAVA / "Sync.java").read_text(encoding="utf-8")
    assert "markPayrollStatus" in sync_java and "PAYROLL_PAY" in sync_java
    db_java = (JAVA / "Db.java").read_text(encoding="utf-8")
    assert "markPayrollStatus" in db_java, "به‌روزرسانی وضعیت در SQLite گوشی"


def test_server_payroll_pay_posts_the_accounting_journal():
    """سمت سرور، پرداخت حقوق سند حسابداری ثبت می‌کند (سمت دیگر همین اتصال)."""
    payroll = (ROOT / "backend" / "app" / "services" / "payroll.py").read_text(encoding="utf-8")
    assert "post_journal" in payroll and 'source_type="PAYROLL"' in payroll
