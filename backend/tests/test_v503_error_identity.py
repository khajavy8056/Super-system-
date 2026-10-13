# -*- coding: utf-8 -*-
"""build-503 — شناسنامهٔ خطا: پایان ابهام نسخه/علت در گزارش‌های کاربر.

گزارش تکراری کاربر نشان داد پیام‌های مبهم («مبلغی در سبد نامعتبر است») نمی‌گویند
کدام نسخه روی گوشی است و کدام مقدار مشکل داشته. اکنون:
۱) هر خطای ثبت فروش، شمارهٔ نسخهٔ دقیق + نام استثنا + پیام فنی واقعی را نشان می‌دهد؛
۲) شمارهٔ نسخه روی خودِ داشبورد (هیرو) دیده می‌شود — بدون کندن در تنظیمات.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
JAVA = ROOT / "mobile-android" / "app" / "src" / "main" / "java" / "ir" / "khajavy" / "supermarket"


def _java(name: str) -> str:
    return (JAVA / name).read_text(encoding="utf-8")


def test_checkout_errors_carry_version_and_true_cause():
    """توست خطای فروش = [نسخه] + نام استثنا + پیام واقعی؛ دیگر پیام مبهم عمومی ممنوع."""
    sales = (JAVA / "SalesScreens.java").read_text(encoding="utf-8")
    start = sales.index("void checkout(String method, double paidAmt, double total)")
    catch_block = sales[start:sales.index("/* ---------------- Held invoices")]
    assert "Version.NAME" in catch_block, "شناسهٔ نسخه در توست خطا"
    assert "getClass().getSimpleName()" in catch_block, "نام واقعی استثنا"
    assert "Log.e(\"POS\", \"checkout failed\", e)" in catch_block, "ثبت کامل خطا در logcat"
    assert "مبلغی در سبد نامعتبر است" not in catch_block, "پیام مبهم قدیمی حذف شود"


def test_dashboard_hero_shows_the_exact_version():
    """نسخهٔ نصب‌شده روی خود داشبورد دیده می‌شود (رفع ابهام «کدام نسخه نصب است؟»)."""
    screens = _java("Screens.java")
    assert "نسخهٔ \" + Ui.fa(Version.NAME)" in screens


def test_build_503_version_pins_are_consistent():
    from importlib import import_module
    import sys
    sys.path.insert(0, str(ROOT / "backend"))
    app = import_module("app")
    assert app.__version__ == "1.0.509"
    assert app.BUILD == 50900
    build = (ROOT / "mobile-android" / "BUILD").read_text().strip()
    assert build == "50900", build
