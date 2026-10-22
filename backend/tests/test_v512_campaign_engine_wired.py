# -*- coding: utf-8 -*-
"""build-512 — «جشنوارهٔ مستقل اندروید باز هم کار نمی‌کند» — ریشه‌های قطعی این نسخه.

۱) صدور خودکار کوپن خرید بعدی روی اندروید «کد مرده» بود: `issueLocalAutoCoupons`
   تعریف شده بود ولی **هیچ‌جا فراخوانی نمی‌شد** — عامل اصلی «خرید بالای ۱۰ میلیون
   هیچ کوپنی نمی‌دهد». حالا به فاز ثبت فروشِ موتور محلی وصل شده (با پیامک دوخطی
   توضیحی برای مشتری) و شکستش هرگز ثبت فروش را نمی‌بندد.
۲) «جشنوارهٔ واجد شرایطی نیست» جعبهٔ سیاه بود: حالا وقتی هیچ جشنواره‌ای جمع نمی‌شود،
   پاسخ `rejections` دارد (دلیل دقیق هر جشنوارهٔ فعال) و صندوق شیت دلایل را باز
   می‌کند — هم در موتور محلی اندروید و هم در بک‌اند (پارتی با هر دو سکو).
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
import app as _app  # noqa: E402

VERSION = _app.__version__
BUILD = _app.BUILD

ANDROID = ROOT / "mobile-android/app/src/main/java/ir/khajavy/supermarket"
LOCAL = (ANDROID / "Local.java").read_text("utf-8")
SALES = (ANDROID / "SalesScreens.java").read_text("utf-8")
ROUTER = (ROOT / "backend/app/routers/pos.py").read_text("utf-8")
SVC = (ROOT / "backend/app/services/coupons.py").read_text("utf-8")


def test_android_auto_issue_is_wired_into_checkout():
    assert "issueLocalAutoCoupons(saleRow, no, total);" in LOCAL, \
        "صدور خودکار کوپن باید در ثبت فروشِ موتور محلی فراخوانی شود (کد مرده بود)"
    assert "فاز ۳٫۵" in LOCAL
    # پیامک دوخطی توضیحی داخل خود صدور
    assert "هدیهٔ خرید شما از جشنوارهٔ" in LOCAL and "SmsLocal.enqueueAndSend" in LOCAL
    assert "کد تخفیف خرید بعدی: " in LOCAL and "به صندوق‌دار بگویید" in LOCAL
    # شکست پاداش هرگز ثبت فروش را نمی‌بندد
    assert "auto coupon issue skipped" in LOCAL


def test_eligible_rejections_on_both_engines():
    assert "static JSONArray evaluateCampaigns(JSONObject request, JSONArray rejections)" in LOCAL
    assert '"rejections", rejections' in LOCAL, "پاسخ محلی باید rejections بدهد"
    for reason in ("حداقل خرید ", "خارج از بازهٔ زمانی", "سقف دفعات استفاده", "اولین خرید"):
        assert reason in LOCAL, f"دلیل «{reason}» در موتور محلی باید باشد"
    assert "rejected: list[dict] | None = None" in SVC
    assert "\"rejections\": rejections" in ROUTER, "بک‌اند هم باید rejections بدهد"
    assert "هیچ جشنواره‌ای با این سبد جمع نشد" in SALES, "صندوق باید شیت دلایل را باز کند"


def test_local_eligible_returns_issue_banner_fields():
    assert '"issue_on_checkout", hints' in LOCAL


def test_backend_eligible_returns_rejections_when_empty(client, auth_headers):
    h = auth_headers
    body = {"name": "دستنیافتنی ۵۱۲", "discount_type": "PERCENT", "discount_value": 10,
            "min_purchase": 900_000_000}
    r = client.post("/api/marketing/campaigns", headers=h, json=body)
    assert r.status_code == 201, r.text
    el = client.post("/api/pos/campaigns/eligible", headers=h,
                     json={"amount": 10_740_000, "product_ids": [], "include_auto_apply": False})
    assert el.status_code == 200, el.text
    data = el.json()
    assert "rejections" in data, "وقتی سبد جشنواره‌ای نگرفت باید دلایل بیاید"
    row = next((x for x in data["rejections"] if x["name"] == "دستنیافتنی ۵۱۲"), None)
    assert row and "حداقل خرید" in row["reason"], data.get("rejections")


def test_version_pins_current():
    web = (ROOT / "frontend/app.js").read_text("utf-8")
    idx = (ROOT / "frontend/index.html").read_text("utf-8")
    assert f"const UI_BUILD = {BUILD // 100};" in web
    assert f"?v={VERSION}" in idx
