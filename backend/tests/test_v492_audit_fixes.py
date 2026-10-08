# -*- coding: utf-8 -*-
"""build-492 — تست جامع استانداردسازی، رفع خطاهای زمان اجرا، منبع واحد مجوزها و سیستم شیفت هوشمند."""
from __future__ import annotations

import pathlib
from datetime import date, timedelta

from app.services.timeservice import local_now
from tests.test_v488_people import _login, _mkuser

REPO = pathlib.Path(__file__).resolve().parents[2]


def test_v492_single_source_of_truth_permissions_and_allowed_views(client, auth_headers):
    """هر نقش فقط نماهای مجاز خود را در /api/auth/me دریافت می‌کند و صندوقدار به شیفت‌های کل فروشگاه دسترسی ندارد."""
    _mkuser(client, auth_headers, "v492_cash", roles=["Cashier"])
    _mkuser(client, auth_headers, "v492_sup", roles=["Supervisor"])
    _mkuser(client, auth_headers, "v492_acc", roles=["Accountant"])

    cash_h = _login(client, "v492_cash", "pass1234")
    sup_h = _login(client, "v492_sup", "pass1234")
    acc_h = _login(client, "v492_acc", "pass1234")

    me_cash = client.get("/api/auth/me", headers=cash_h).json()
    assert "shifts.view" not in me_cash["permissions"]
    assert "shifts.manage" not in me_cash["permissions"]
    assert "staff" not in me_cash["allowed_views"]
    assert "reports" not in me_cash["allowed_views"]
    assert "marketing" not in me_cash["allowed_views"]
    assert "accounting" not in me_cash["allowed_views"]
    assert set(me_cash["allowed_views"]) >= {"dashboard", "pos", "invoices", "customers", "profile", "support"}

    # صندوقدار نباید بتواند شیفت‌های کل فروشگاه را ببیند، اما شیفت‌های خودش (/api/hr/shifts/my) را می‌بیند
    assert client.get("/api/hr/shifts", headers=cash_h).status_code == 403
    my_sh = client.get("/api/hr/shifts/my", headers=cash_h)
    assert my_sh.status_code == 200
    assert "status" in my_sh.json() and "assignments" in my_sh.json()

    me_sup = client.get("/api/auth/me", headers=sup_h).json()
    assert "shifts.manage" in me_sup["permissions"]
    assert "staff" in me_sup["allowed_views"]
    assert "marketing" in me_sup["allowed_views"]
    assert "users" not in me_sup["allowed_views"]
    assert "settings" not in me_sup["allowed_views"]

    me_acc = client.get("/api/auth/me", headers=acc_h).json()
    assert "accounting" in me_acc["allowed_views"]
    assert "pos" not in me_acc["allowed_views"]
    assert "staff" not in me_acc["allowed_views"]


def test_v492_shift_per_user_and_automatic_presence_detection(client, auth_headers):
    """تعریف شیفت برای کاربر مشخص + تشخیص خودکار حضور در بازهٔ شیفت، خارج از بازه، چند شیفت و تکمیل شیفت."""
    day = local_now().date().isoformat()
    _mkuser(client, auth_headers, "v492_shsup", roles=["Supervisor"])
    _mkuser(client, auth_headers, "v492_shuser1", roles=["Cashier"])
    _mkuser(client, auth_headers, "v492_shuser2", roles=["Cashier"])
    _mkuser(client, auth_headers, "v492_shuser3", roles=["Cashier"])

    sup_h = _login(client, "v492_shsup", "pass1234")
    u1_h = _login(client, "v492_shuser1", "pass1234")
    u2_h = _login(client, "v492_shuser2", "pass1234")
    u3_h = _login(client, "v492_shuser3", "pass1234")

    users = client.get("/api/users", headers=auth_headers).json()
    u1_id = next(u["id"] for u in users if u["username"] == "v492_shuser1")
    u2_id = next(u["id"] for u in users if u["username"] == "v492_shuser2")

    # ۱) کاربر بدون شیفت
    st3 = client.post("/api/hr/attendance/enter", headers=u3_h).json()
    assert st3["has_shift"] is False
    assert st3["present"] is False
    assert st3["shift_state"] == "NO_SHIFT"

    # ۲) تعریف شیفت تمام‌روز (00:00 تا 23:59) با تخصیص مستقیم به کاربر ۱ در زمان ایجاد
    r = client.post(
        "/api/hr/shifts",
        json={"name": "شیفت فعال تمام‌روز", "start_time": "00:00", "end_time": "23:59", "user_id": u1_id, "day": day},
        headers=sup_h,
    )
    assert r.status_code in (200, 201), r.text
    assert r.json().get("assigned_user_id") == u1_id

    # اضافه کردن شیفت دوم در همان روز برای تست پشتیبانی از چند شیفت در یک روز
    r2 = client.post(
        "/api/hr/shifts",
        json={"name": "شیفت مکمل", "start_time": "23:58", "end_time": "23:59", "user_id": u1_id, "day": day},
        headers=sup_h,
    )
    assert r2.status_code in (200, 201)

    # ورود کاربر ۱ به برنامه → تشخیص خودکار شیفت فعال و ثبت حضور بدون کلیک دستی
    st1 = client.post("/api/hr/attendance/enter", headers=u1_h).json()
    assert st1["has_shift"] is True
    assert len(st1["shift_windows"]) == 2
    assert st1["in_shift_window"] is True
    assert st1["present"] is True
    assert st1["auto_entered"] is True
    assert st1["shift_state"] in ("IN_SHIFT", "ACTIVE")
    assert st1["active_shift"]["name"] == "شیفت فعال تمام‌روز"

    # ثبت خروج دستی → وضعیت شیفت به COMPLETED تغییر می‌کند و ورود مجدد آن را دوباره باز نمی‌کند
    out1 = client.post("/api/hr/attendance/clock-out", headers=u1_h)
    assert out1.status_code in (200, 201)
    st1_after = client.post("/api/hr/attendance/enter", headers=u1_h).json()
    assert st1_after["present"] is False
    assert st1_after["shift_state"] == "COMPLETED"

    # ۳) تعریف شیفت ۱ دقیقه‌ای خارج از زمان فعلی برای کاربر ۲ (تست ورود خارج از ساعت شیفت)
    from app.services import timeservice
    now = timeservice.local_now().replace(tzinfo=None)
    # یک بازهٔ ۱ دقیقه‌ای که ۲ ساعت با الان فاصله دارد
    off_h = (now.hour + 2) % 24
    s_str = f"{off_h:02d}:00"
    e_str = f"{off_h:02d}:01"
    r3 = client.post(
        "/api/hr/shifts",
        json={"name": "شیفت خارج از ساعت", "start_time": s_str, "end_time": e_str, "user_id": u2_id, "day": day},
        headers=sup_h,
    )
    assert r3.status_code in (200, 201)
    st2 = client.post("/api/hr/attendance/enter", headers=u2_h).json()
    assert st2["has_shift"] is True
    assert st2["in_shift_window"] is False
    assert st2["present"] is False
    assert st2["shift_state"] in ("OUT_OF_SHIFT", "UPCOMING", "OUT_OF_HOURS")


def test_v492_no_cache_headers_and_frontend_contracts(client):
    """هدرهای ضدکش روی فایل‌های UI، حذف تایمر جعلی لاگین، حذف کش سرویس‌ورکر و نرمال‌سازی داشبورد."""
    res = client.get("/app.js")
    assert res.status_code == 200
    assert "no-store" in res.headers.get("cache-control", "")

    app_js = (REPO / "frontend/app.js").read_text(encoding="utf-8")
    assert "const UI_BUILD = 497;" in app_js
    assert "function normalizeDashboardData(" in app_js
    assert "const VIEW_PERMS =" in app_js
    assert "function canView(" in app_js
    assert "initAuthenticatedSession" in app_js
    assert "/hr/attendance/status" in app_js and "auto=1" in app_js
    assert "/hr/shifts/my" in app_js

    onb_js = (REPO / "frontend/onboarding.js").read_text(encoding="utf-8")
    assert "120000" not in onb_js
    assert "45 * 60 * 1000" not in onb_js

    sw_js = (REPO / "frontend/sw.js").read_text(encoding="utf-8")
    assert "no-sw-v496" in sw_js
    assert "self.registration.unregister()" in sw_js

    run_py = (REPO / "installer/windows/run_supermarket.py").read_text(encoding="utf-8")
    assert "purge_stale_webview_cache" in run_py

    from app import BUILD, __version__
    assert __version__ == "1.0.497"
    assert BUILD == 49700
    assert int((REPO / "mobile-android/BUILD").read_text().strip()) == 49700


def test_v492_mobile_sync_user_isolation_and_attendance_summary(client, auth_headers):
    """همگام‌سازی پایدار موبایل با رایانه + جداسازی کامل نشست کاربران و گزارش ساعات موظفی/حضور."""
    day = local_now().date().isoformat()
    _mkuser(client, auth_headers, "v492_mob_cash", roles=["Cashier"])
    _mkuser(client, auth_headers, "v492_mob_sup", roles=["Supervisor"])
    cash_h = _login(client, "v492_mob_cash", "pass1234")
    sup_h = _login(client, "v492_mob_sup", "pass1234")

    users = client.get("/api/users", headers=auth_headers).json()
    cid = next(u["id"] for u in users if u["username"] == "v492_mob_cash")

    # تعریف شیفت برای صندوقدار و ثبت ورود خودکار از طریق موبایل
    client.post(
        "/api/hr/shifts",
        json={"name": "شیفت موبایل", "start_time": "00:00", "end_time": "23:59", "user_id": cid, "day": day},
        headers=sup_h,
    )
    sync_res = client.post(
        "/api/mobile/sync",
        json={"device_id": "dev-v492", "push": [], "pull": True, "limit": 200},
        headers=cash_h,
    )
    assert sync_res.status_code == 200, sync_res.text
    sbody = sync_res.json()
    assert sbody["current_user"]["username"] == "v492_mob_cash"
    assert "pos" in sbody["current_user"]["allowed_views"]
    assert "staff" not in sbody["current_user"]["allowed_views"]
    assert sbody["shift_status"]["present"] is True

    # گزارش مقایسهٔ ساعات حضور واقعی با ساعات موظفی (شخصی و تیمی)
    my_sum = client.get(f"/api/hr/attendance/my-summary?start={day}&end={day}", headers=cash_h)
    assert my_sum.status_code == 200
    assert my_sum.json()["planned_minutes"] > 0
    assert my_sum.json()["days_present"] == 1

    team_sum = client.get(f"/api/hr/attendance/summary?start={day}&end={day}&user_id={cid}", headers=sup_h)
    assert team_sum.status_code == 200
    assert team_sum.json()[0]["user_id"] == cid

    # بررسی کد اندروید برای عدم بازنویسی توکن کاربر جدید با توکن کاربر قبلی هنگام سوئیچ حساب
    login_java = (REPO / "mobile-android/app/src/main/java/ir/khajavy/supermarket/LoginActivity.java").read_text(encoding="utf-8")
    assert "token = tok;" in login_java
    assert "if (held != null && !held.isEmpty()) token = held;" not in login_java
    app_java = (REPO / "mobile-android/app/src/main/java/ir/khajavy/supermarket/AppActivity.java").read_text(encoding="utf-8")
    assert 'Prefs.set("device_token", "")' in app_java
    assert 'Prefs.set("bio_token", "")' in app_java
    local_java = (REPO / "mobile-android/app/src/main/java/ir/khajavy/supermarket/Local.java").read_text(encoding="utf-8")
    assert '"Supervisor"' in local_java and '"Accountant"' in local_java
