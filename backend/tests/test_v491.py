# -*- coding: utf-8 -*-
"""build-491 — دستور مالک:
۱) شیفت قابل تعریف و «تخصیص به یک شخص مشخص» توسط سوپروایزر/مدیر.
۲) نوار حضور (سبز=حاضر با ساعت دقیقه، قرمز=غایب) در داشبورد و زیر کارت پروفایل.
۳) هیچ dialog پیش‌فرض مرورگر (prompt) در هیچ UI — همه به پنجرهٔ فرم داخلی رفته‌اند.
۴) نسخهٔ build-491."""
from __future__ import annotations

import io
import pathlib
from datetime import date, timedelta

from app.services.timeservice import local_now
from tests.test_v488_people import _login, _mkuser

REPO = pathlib.Path(__file__).resolve().parents[2]
UI_FILES = [
    "frontend/app.js", "frontend/accounting.js", "frontend/pos.js",
    "frontend/reports.js", "frontend/insights.js", "frontend/setup.js",
    "frontend/login.js", "frontend/updater.js", "frontend/main.js",
    "frontend/mobile/app-more.js", "frontend/mobile/app-views.js",
    "frontend/mobile/app.js",
]


# ---------- ۱) تعریف شیفت + تخصیص به شخص مشخص ----------
def test_v491_shift_define_and_assign_specific_person(client, auth_headers):
    day = local_now().date().isoformat()
    # سوپروایزر می‌تواند شیفت تعریف کند (shifts.manage)
    _mkuser(client, auth_headers, "v491_sup", roles=["Supervisor"])
    _mkuser(client, auth_headers, "v491_cash", roles=["Cashier"], job_title="صندوق‌دار")
    sup = _login(client, "v491_sup", "pass1234")
    mgr = auth_headers   # ادمین/مدیر
    r = client.post("/api/hr/shifts", json={"name": "صبح", "start_time": "08:00", "end_time": "14:00"}, headers=sup)
    assert r.status_code in (200, 201), r.text
    sid = r.json()["id"]
    # تخصیص به «شخص مشخص»
    cash = client.get("/api/users", headers=mgr).json()
    cash_id = next(u["id"] for u in cash if u["username"] == "v491_cash")
    r = client.post(f"/api/hr/shifts/{sid}/assign", json={"user_id": cash_id, "day": day}, headers=sup)
    assert r.status_code in (200, 201), r.text
    # در برنامهٔ امروز، roster شامل همان شخص است
    r = client.get(f"/api/hr/shifts/day/{day}", headers=mgr)
    assert r.status_code == 200, r.text
    staff = r.json()["staff"]
    row = next(x for x in staff if x["user_id"] == cash_id)
    assert row["shift_windows"], "پنجرهٔ شیفت شخص باید ثبت شده باشد"
    # مدیر هم می‌تواند تخصیص دهد
    r = client.post(f"/api/hr/shifts/{sid}/assign", json={"user_id": cash_id, "day": (date.today() + timedelta(days=1)).isoformat()}, headers=mgr)
    assert r.status_code in (200, 201), r.text
    # فهرست حداقلی افراد برای تخصیص (بدون اطلاعات حساس)
    r = client.get("/api/hr/roster-users", headers=sup)
    assert r.status_code == 200
    assert any(x["id"] == cash_id for x in r.json())
    assert set(r.json()[0].keys()) <= {"id", "full_name", "job_title"}


# ---------- ۲) نوار حضور: ساعت دقیقه + سبز/قرمز ----------
def test_v491_presence_minute_precision_clocking(client, auth_headers):
    day = local_now().date().isoformat()
    _mkuser(client, auth_headers, "v491_psup", roles=["Supervisor"])
    _mkuser(client, auth_headers, "v491_pcash", roles=["Cashier"])
    sup = _login(client, "v491_psup", "pass1234")
    cash_h = _login(client, "v491_pcash", "pass1234")
    users = client.get("/api/users", headers=auth_headers).json()
    cid = next(u["id"] for u in users if u["username"] == "v491_pcash")
    r = client.post("/api/hr/shifts", json={"name": "عصر", "start_time": "14:00", "end_time": "20:00"}, headers=sup)
    sid = r.json()["id"]
    client.post(f"/api/hr/shifts/{sid}/assign", json={"user_id": cid, "day": day}, headers=sup)
    # وضعیت قبل از حضور: غایب
    st = client.get("/api/hr/attendance/status", headers=cash_h).json()
    assert st["has_shift"] is True and st["present"] is False
    # ثبت حضور → سبز + ساعت دقیقه
    r = client.post("/api/hr/attendance/clock-in", headers=cash_h)
    assert r.status_code in (200, 201), r.text
    st = client.get("/api/hr/attendance/status", headers=cash_h).json()
    assert st["present"] is True
    assert st["since"] and st["minutes"] is not None      # دقت دقیقه
    # فهرست تیم برای نوار حضور
    rows = client.get("/api/hr/attendance/today", headers=sup).json()
    row = next(x for x in rows if x["user_id"] == cid)
    assert row["present"] is True
    # ثبت خروج
    assert client.post("/api/hr/attendance/clock-out", headers=cash_h).status_code in (200, 201)
    st = client.get("/api/hr/attendance/status", headers=cash_h).json()
    assert st["present"] is False and st["ended_at"]
    # دوباره حضور در همان روز ممنوع
    assert client.post("/api/hr/attendance/clock-in", headers=cash_h).status_code == 400


# ---------- ۳) هیچ dialog پیش‌فرض مرورگر (prompt) در هیچ UI ----------
def test_v491_no_browser_prompt_dialogs_anywhere():
    for rel in UI_FILES:
        p = REPO / rel
        if not p.exists():
            continue
        src = io.open(p, encoding="utf-8").read()
        for i, line in enumerate(src.splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("//") or stripped.startswith("*") or stripped.startswith("/*"):
                continue
            if "نباید وجود" in stripped or stripped.startswith("چرا"):
                continue
            assert "prompt(" not in line, f"{rel}:{i} هنوز prompt() مرورگر دارد: {stripped[:90]}"
    # جایگزین‌ها باید وجود داشته باشند
    appjs = io.open(REPO / "frontend/app.js", encoding="utf-8").read()
    assert "openShiftCreate" in appjs and "openShiftAssign" in appjs
    assert 'id="pe-name"' in appjs       # فرم ویرایش پروفایل
    assert 'id="an-title"' in appjs      # فرم اطلاعیه
    acc = io.open(REPO / "frontend/accounting.js", encoding="utf-8").read()
    assert 'id="rev-reason"' in acc      # فرم دلیل برگشت سند


# ---------- ۴) نوار حضور در هر دو جای داشبورد/نوار بالا ----------
def test_v491_presence_bar_in_dashboard_and_topbar():
    html = io.open(REPO / "frontend/index.html", encoding="utf-8").read()
    assert 'id="tb-presence"' in html                 # زیر کارت پروفایل
    assert "topbar-user-wrap" in html
    appjs = io.open(REPO / "frontend/app.js", encoding="utf-8").read()
    assert "updatePresence" in appjs and "presenceHtml" in appjs
    assert "pres-on" in appjs and "pres-off" in appjs  # سبز/قرمز
    assert "presenceClock" in appjs                    # ساعت با دقت دقیقه
    assert "pres-in-card" in appjs                     # داشبورد «من» + دکمهٔ ثبت حضور


# ---------- ۵) نسخهٔ build-491 ----------
def test_v491_version_pins():
    from app import __version__
    build = int((REPO / "mobile-android/BUILD").read_text().strip())
    assert __version__ >= "1.0.491"
    assert build >= 49100
    appjs = io.open(REPO / "frontend/app.js", encoding="utf-8").read()
    assert "const UI_BUILD = 50" in appjs
    assert 'state.version || "1.0.50' in appjs
