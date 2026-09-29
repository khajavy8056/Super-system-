# -*- coding: utf-8 -*-
"""v1.0.0 (RASA) — «پشتیبانی» پشت دروازهٔ لایسنس حبس نمی‌شود.

باگ گزارش‌شدهٔ مالک: «از ویندوز تیکت پشتیبانی ثبت نمی‌شود» — و روی اندروید سالم بود.
ریشه: دروازهٔ لایسنس *همهٔ* مسیرهای `/api` را با ۴۰۲ می‌بست، از جمله
`GET /api/support/types`. پس در فروشگاهی که لایسنسش فعال نبود:

  ۱. فهرست «نوع درخواست» خالی برمی‌گشت (`meta.types = []`)،
  ۲. ارسال با پیام «نوع درخواست نامعتبر است» رد می‌شد،
  ۳. و تیکت هرگز ساخته نمی‌شد — دقیقاً وقتی که فروشگاه بیش از هر وقت دیگر به
     پشتیبانی نیاز داشت (برای فعال‌سازی همان لایسنس).

گوشی به این مشکل نمی‌خورد چون حالت مستقل اندروید تیکت را مستقیم به رله می‌فرستد
و از بک‌اند عبور نمی‌کند؛ برای همین مشکل «فقط ویندوزی» به‌نظر می‌رسید.

اصلاح: پشتیبانی (و ورود، چون بدون نشست هیچ کاری ممکن نیست) از دروازه آزاد شد،
به‌شرط آنکه سطح حمله باز نشود — مسیر بدون‌نشست فقط تیکت نوع «لایسنس» را می‌پذیرد
و سقف نرخ دارد. این ماژول همان قراردادها را قفل می‌کند.
"""
from __future__ import annotations

import pytest

from app.database import SessionLocal
from app.models import SupportTicket, User
from app.routers import support as support_router
from sqlalchemy import select


@pytest.fixture(autouse=True)
def _reset_locked_limits():
    support_router._LOCKED_HITS.clear()
    yield
    support_router._LOCKED_HITS.clear()


def _lock_the_licence():
    """The licence gate refuses every licensed feature (see test_v1_5)."""
    from app.services import license as lic
    with SessionLocal() as db:
        lic.clear(db)
        db.commit()
    return lic


def test_locked_licence_still_blocks_the_shop_features(client, auth_headers, monkeypatch):
    """قابلیت‌های واقعی فروشگاه همچنان بسته‌اند — اصلاح، دروازه را شُل نکرده."""
    import app.main as m
    monkeypatch.setattr(m, "_LICENSE_GATE_ENABLED", True)
    _lock_the_licence()
    for path in ("/api/products", "/api/invoices", "/api/reports/dashboard", "/api/customers"):
        r = client.get(path, headers=auth_headers)
        assert r.status_code == 402, f"{path} → {r.status_code}"
        assert r.json()["detail"]["code"] == "LICENSE_REQUIRED"


def test_support_and_login_stay_reachable_on_a_locked_licence(client, auth_headers, monkeypatch):
    """راه کمک گرفتن بسته نیست: ورود و پشتیبانی کار می‌کنند."""
    import app.main as m
    monkeypatch.setattr(m, "_LICENSE_GATE_ENABLED", True)
    _lock_the_licence()

    assert client.get("/api/support/types").status_code == 401, "بدون توکن باید احراز هویت بخواهد، نه ۴۰۲"
    r = client.get("/api/support/types", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert len(r.json()["types"]) >= 5 and r.json()["priorities"], "فهرست نوع/اولویت باید پر باشد"
    assert client.get("/api/support/tickets", headers=auth_headers).status_code == 200


def test_ticket_can_be_filed_from_the_lock_screen_without_a_session(client, monkeypatch):
    """صفحهٔ قفل: بدون نشست هم می‌توان «کمک لایسنس» خواست (فقط همان نوع)."""
    import app.main as m
    monkeypatch.setattr(m, "_LICENSE_GATE_ENABLED", True)
    _lock_the_licence()

    body = {"description": "کلید را وارد می‌کنم ولی «لایسنس فعال نیست» می‌دهد؛ از صفحهٔ قفل ثبت شد.",
            "contact": "09120000000", "device": "Windows"}
    r = client.post("/api/support/locked-ticket", json=body)
    assert r.status_code == 201, r.text
    out = r.json()
    assert out["type"] == "LICENSE" and out["number"].startswith("TCK-")
    with SessionLocal() as db:
        t = db.execute(select(SupportTicket).order_by(SupportTicket.id.desc())).scalars().first()
        assert t is not None and t.type == "LICENSE"
        assert "شناسهٔ دستگاه" in (t.description or ""), "تیکت باید شناسهٔ سخت‌افزار را همراه داشته باشد"
        assert t.created_by is not None, "به اولین کاربر فروشگاه نسبت داده می‌شود تا پاسخ به جایی برسد"


def test_lock_screen_ticket_is_validated_and_rate_limited(client, monkeypatch):
    """سطح حمله باز نمی‌شود: ورودی معتبر + سقف نرخ برای هر نصب و هر IP."""
    import app.main as m
    monkeypatch.setattr(m, "_LICENSE_GATE_ENABLED", True)
    _lock_the_licence()

    assert client.post("/api/support/locked-ticket", json={"description": "کوتاه"}).status_code == 422
    ok_count = 0
    for i in range(support_router._LOCKED_MAX_PER_INSTALL_HOUR + 2):
        r = client.post("/api/support/locked-ticket",
                        json={"description": f"درخواست شماره {i} برای بررسی سقف نرخ ثبت تیکت قفل"})
        if r.status_code == 201:
            ok_count += 1
        else:
            assert r.status_code == 429, r.text
            assert r.json()["detail"]["code"] == "TOO_MANY"
            break
    assert ok_count == support_router._LOCKED_MAX_PER_INSTALL_HOUR, f"سقف نرخ کار نکرد ({ok_count})"


def test_geo_permission_is_open_for_our_own_origin_only(client):
    """سیاست امنیتی: دوربین/میکروفن بسته، موقعیت مکانی فقط برای خودِ پنل."""
    policy = client.get("/health").headers.get("Permissions-Policy", "")
    assert "camera=()" in policy and "microphone=()" in policy
    assert "geolocation=(self)" in policy, policy
    assert "geolocation=()" not in policy
