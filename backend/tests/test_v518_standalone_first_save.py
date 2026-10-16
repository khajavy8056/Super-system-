# -*- coding: utf-8 -*-
"""build-518 — «چرا برنامه به رایانه نیاز داشته باشد؟» — معماری مستقل، ذخیرهٔ محلی-اول.

فرمان صریح مالک: «نسخهٔ اندروید ما کاملاً مستقله؛ نسخهٔ ویندوز هم کاملاً مستقل؛
وقتی مچ می‌شوند فقط اطلاعات را رد و بدل می‌کنند. هیچ‌کدام نیاز به دیگری ندارد —
مخصوصاً الان که در حالت مستقل هستم.» پس در بخش جشنواره‌ها:
۱) ذخیره همیشه و اول روی خود گوشی (فوری، حتی در پرواز/قطع کامل).
۲) انتقال به رایانه فقط «همگام‌سازیِ به‌ترین‌تلاشِ» پس‌زمینه است — شکستش خطا نیست.
۳) هیچ پیام «اتصال به رایانه را بررسی کنید» در مسیر ذخیره مجاز نیست.
۴) فهرست جشنواره‌ها/کوپن‌ها/آمار در نبود رایانه از حافظهٔ خود گوشی می‌آید.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
import app as _app  # noqa: E402

ANDROID = ROOT / "mobile-android/app/src/main/java/ir/khajavy/supermarket"
SALES = (ANDROID / "SalesScreens.java").read_text("utf-8")
LOCAL = (ANDROID / "Local.java").read_text("utf-8")


def test_save_is_local_first_never_pc_dependent():
    i_local = SALES.index("Object res = Local.handle(method, path, req.toString());")
    i_push = SALES.index('Api.post("/marketing/campaigns", req, r -> {', i_local)
    assert i_local < i_push, "اول ذخیرهٔ محلی، بعد (در صورت دسترس) انتقال"
    # مستقل ⇒ فقط ذخیرهٔ محلی و تمام؛ هیچ تماس شبکه‌ای
    assert "if (Api.standalone() || localRow == 0) { wStep = 8; wRender(); return; }" in SALES
    # شکست انتقال = یادآوری، نه خطا
    assert SALES.count('"روی گوشی ذخیره شد؛ همگام‌سازی با رایانه بعد از اتصال انجام می‌شود"') == 2
    # ممنوعیت پیام اتصال در کل مسیر ذخیرهٔ جادوگر
    assert "اتصال به رایانه را بررسی کنید" not in SALES
    assert "wSaveFallback" not in SALES


def test_lists_work_offline():
    assert "void getWithOffline(String path, java.util.function.Consumer<Object> cb)" in SALES
    for path in ("/marketing/campaigns", "/marketing/coupons", "/marketing/stats"):
        assert f'getWithOffline("{path}"' in SALES
    assert 'Local.handle("GET", path, "{}")' in SALES, "خواندن از حافظهٔ خود گوشی"


def test_standalone_boolean_fix_survives():
    assert 'v.put("reward_next_only", offerFlag(b, "reward_next_only") ? 1 : 0);' in LOCAL


def test_version_pins():
    assert _app.__version__ == "1.0.521" and _app.BUILD == 52100
    assert (ROOT / "mobile-android/BUILD").read_text().strip() == "52100"
    assert "const UI_BUILD = 521;" in (ROOT / "frontend/app.js").read_text("utf-8")
    assert "?v=1.0.521" in (ROOT / "frontend/index.html").read_text("utf-8")
