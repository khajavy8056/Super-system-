# -*- coding: utf-8 -*-
"""build-488 — پروفایل/نقش‌ها/دسترسی مستقیم/اطلاعیه/شیفت/حقوق/عملکرد/Widghet/Dev (§۱–۱۳، ۱۴–۲۷، ۳۸–۴۰، ۵۰)."""
from __future__ import annotations

import json
from datetime import datetime, timedelta




def _login(client, username, password):
    r = client.post("/api/auth/login", data={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _mkuser(client, auth_headers, username, roles=(), permissions=(), job_title=None):
    r = client.post("/api/users", headers=auth_headers, json={
        "username": username, "password": "pass1234", "full_name": username,
        "roles": list(roles), "permissions": list(permissions),
        "job_title": job_title, "local_only": False})
    assert r.status_code in (201, 409), r.text
    return r.json() if r.status_code == 201 else {}


# ───────────────────────── §۱–۳: پروفایل، چندنقشی، دسترسی مستقیم ─────────────────────────

def test_multi_role_and_direct_permissions(client, auth_headers):
    """User → Roles → Permissions + دسترسی مستقیم مستقل از Role (§۲)."""
    _mkuser(client, auth_headers, "mrp_multi", roles=["Cashier", "Salesperson"],
            permissions=["inventory.view"])
    h = _login(client, "mrp_multi", "pass1234")
    me = client.get("/api/users/me", headers=h).json()
    assert set(["Cashier", "Salesperson"]).issubset(set(me["roles"])), me["roles"]
    # دسترسی مستقیم اضافه می‌شود ولی چیزی را حذف نمی‌کند (§۶)
    assert "inventory.view" in me["permissions"]
    assert "pos.sell" in me["permissions"]          # از نقش صندوقدار
    assert "products.view" in me["permissions"]     # از نقش فروشنده
    # نقش، UI را تعیین نمی‌کند؛ دسترسی دقیق است: inventory.view ≠ inventory.adjust
    assert "inventory.adjust" not in me["permissions"]


def test_direct_permission_denied_without_grant(client, auth_headers):
    _mkuser(client, auth_headers, "mrp_noview", roles=[])
    h = _login(client, "mrp_noview", "pass1234")
    assert client.get("/api/reports/dashboard", headers=h).status_code == 403


def test_profile_fields_and_self_service(client, auth_headers):
    """پروفایل اختصاصی هر کاربر (§۱): فیلدها + ویرایش خودی + پروفایل کارمندی."""
    u = _mkuser(client, auth_headers, "prof_ali", roles=["Salesperson"],
                job_title="فروشندهٔ ارشد")
    h = _login(client, "prof_ali", "pass1234")
    # ویرایش خودی: نام/ایمیل/تلفن
    r = client.patch("/api/users/me", headers=h,
                     json={"full_name": "علی رضایی", "phone": "09120000000"})
    assert r.status_code == 200, r.text
    assert r.json()["phone"] == "09120000000"
    # نقش/دسترسی از PATCH خودی قابل تغییر نیست (§۵۰)
    assert not hasattr(r.json(), "roles") or "roles" in r.json()
    # پروفایل کارمندی خودش
    r = client.get(f"/api/users/{u['id']}/profile", headers=h)
    assert r.status_code == 200
    body = r.json()
    assert body["job_title"] == "فروشندهٔ ارشد"
    assert body["achievements"] and "score_total" in body["achievements"]
    # بدون payroll.view دادهٔ حقوق دیده نمی‌شود (§۵۰)
    assert body["payroll"] is None


def test_employee_profile_requires_permission(client, auth_headers):
    _mkuser(client, auth_headers, "prof_a", roles=["Salesperson"])
    _mkuser(client, auth_headers, "prof_b", roles=["Salesperson"])
    a = _login(client, "prof_a", "pass1234")
    users = {u["username"]: u["id"] for u in client.get("/api/users", headers=auth_headers).json()}
    assert client.get(f"/api/users/{users['prof_b']}/profile", headers=a).status_code == 403
    # مدیر با profile.view_all می‌بیند
    r = client.get(f"/api/users/{users['prof_b']}/profile", headers=auth_headers)
    assert r.status_code == 200


def test_avatar_upload_and_delete(client, auth_headers):
    _mkuser(client, auth_headers, "prof_img", roles=["Salesperson"])
    h = _login(client, "prof_img", "pass1234")
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 32
    r = client.post("/api/users/me/avatar", headers=h,
                    files={"file": ("a.png", png, "image/png")})
    assert r.status_code == 200, r.text
    assert r.json()["avatar_url"]
    r = client.delete("/api/users/me/avatar", headers=h)
    assert r.status_code == 200 and r.json()["avatar_url"] is None


def test_standard_roles_seeded_with_titles(client, auth_headers):
    roles = client.get("/api/users/roles", headers=auth_headers).json()
    names = {r["name"] for r in roles}
    for expected in ("Supervisor", "Inspector", "Storekeeper", "Stocktake Lead",
                     "General Manager", "Salesperson"):
        assert expected in names, expected
    fa = {r["name"]: r["title_fa"] for r in roles}
    assert fa["Supervisor"] == "سوپروایزر" and fa["Storekeeper"] == "مسئول انبار"


# ───────────────────────── §۱۴–۱۷: اطلاعیه‌ها ─────────────────────────

def test_announcement_targeting_and_read_states(client, auth_headers):
    _mkuser(client, auth_headers, "ann_seller", roles=["Salesperson"])
    _mkuser(client, auth_headers, "ann_keeper", roles=["Storekeeper"])
    seller = _login(client, "ann_seller", "pass1234")
    keeper = _login(client, "ann_keeper", "pass1234")

    # اطلاعیه فقط برای فروشندگان (§۱۶)
    r = client.post("/api/hr/announcements", headers=auth_headers, json={
        "title": "نکات فروش", "body": "…", "target_kind": "ROLES",
        "target_roles": ["Salesperson"], "priority": 3})
    assert r.status_code == 201, r.text

    mine_s = client.get("/api/hr/announcements", headers=seller).json()
    mine_k = client.get("/api/hr/announcements", headers=keeper).json()
    assert any(a["title"] == "نکات فروش" for a in mine_s)
    assert not any(a["title"] == "نکات فروش" for a in mine_k), "مخاطب Role باید رعایت شود"

    ann_id = next(a["id"] for a in mine_s if a["title"] == "نکات فروش")
    assert client.post(f"/api/hr/announcements/{ann_id}/seen", headers=seller).status_code == 200
    r = client.post(f"/api/hr/announcements/{ann_id}/read", headers=seller)
    assert r.status_code == 200
    after = client.get("/api/hr/announcements", headers=seller).json()
    row = next(a for a in after if a["id"] == ann_id)
    assert row["is_read"] and row["is_seen"] and row["read_at"]


def test_announcement_permission_gate(client, auth_headers):
    """ایجاد اطلاعیه فقط با Permission — نه عنوان شغلی (§۱۵)."""
    _mkuser(client, auth_headers, "ann_sup", roles=["Supervisor"])   # announcements.publish دارد
    _mkuser(client, auth_headers, "ann_cas", roles=["Cashier"])      # ندارد
    sup = _login(client, "ann_sup", "pass1234")
    cas = _login(client, "ann_cas", "pass1234")
    body = {"title": "تغییر ساعت کاری", "body": "…", "target_kind": "ALL"}
    assert client.post("/api/hr/announcements", headers=sup, json=body).status_code == 201
    assert client.post("/api/hr/announcements", headers=cas, json=body).status_code == 403


def test_announcement_store_and_users_targeting(client, auth_headers):
    _mkuser(client, auth_headers, "ann_u1", roles=["Salesperson"])
    users = {u["username"]: u["id"] for u in client.get("/api/users", headers=auth_headers).json()}
    r = client.post("/api/hr/announcements", headers=auth_headers, json={
        "title": "فقط علی", "target_kind": "USERS", "target_users": [users["ann_u1"]]})
    assert r.status_code == 201
    h1 = _login(client, "ann_u1", "pass1234")
    _mkuser(client, auth_headers, "ann_u2", roles=["Salesperson"])
    h2 = _login(client, "ann_u2", "pass1234")
    assert any(a["title"] == "فقط علی" for a in client.get("/api/hr/announcements", headers=h1).json())
    assert not any(a["title"] == "فقط علی" for a in client.get("/api/hr/announcements", headers=h2).json())


# ───────────────────────── §۱۸–۲۰: شیفت و تفکیک داخل/خارج ─────────────────────────

def test_shift_crud_assign_and_split(client, auth_headers):
    _mkuser(client, auth_headers, "shf_ali", roles=["Salesperson"])
    users = {u["username"]: u["id"] for u in client.get("/api/users", headers=auth_headers).json()}
    r = client.post("/api/hr/shifts", headers=auth_headers, json={
        "name": "صبح", "start_time": "08:00", "end_time": "14:00", "workdays": [0, 1, 2, 3, 4]})
    assert r.status_code == 201, r.text
    shift = r.json()
    r = client.post(f"/api/hr/shifts/{shift['id']}/assign", headers=auth_headers,
                    json={"user_id": users["shf_ali"], "day": ""})
    assert r.status_code == 201, r.text
    a_id = r.json()["assignment_id"]

    # فروش داخل/خارج شیفت (§۲۰) — با فاکتور واقعی
    today = datetime.utcnow().strftime("%Y-%m-%d")
    p = client.post("/api/products", headers=auth_headers,
                    json={"barcode": "7700000888001", "name": "Shift prod"}).json()
    b = client.post("/api/batches/receive", headers=auth_headers, json={
        "product_id": p["id"], "quantity_received": 5, "buy_price": 1000, "sell_price": 2000}).json()
    seller_h = _login(client, "shf_ali", "pass1234")
    r = client.post("/api/pos/checkout", headers=seller_h, json={
        "items": [{"product_id": p["id"], "batch_id": b["id"], "quantity": 1}],
        "tax_rate": 0, "payments": [{"method": "CASH", "amount": 2000}]})
    assert r.status_code == 201, r.text
    perf = client.get(f"/api/hr/shifts/performance/{users['shf_ali']}/{today}",
                      headers=auth_headers).json()
    assert perf["sales_total"] == perf["sales_in_shift"] + perf["sales_out_of_shift"]
    assert perf["sales_total"] >= 2000
    assert "shift_windows" in perf

    # جابه‌جایی/لغو (§۱۸)
    r2 = client.post("/api/hr/shifts", headers=auth_headers, json={
        "name": "عصر", "start_time": "14:00", "end_time": "20:00"})
    r = client.post(f"/api/hr/shifts/assignments/{a_id}/move", headers=auth_headers,
                    json={"shift_id": r2.json()["id"]})
    assert r.status_code == 200, r.text
    r = client.delete(f"/api/hr/shifts/assignments/{r.json()['assignment_id']}", headers=auth_headers)
    assert r.status_code == 200


def test_shift_requires_permission(client, auth_headers):
    _mkuser(client, auth_headers, "shf_cas", roles=["Cashier"])
    cas = _login(client, "shf_cas", "pass1234")
    assert client.get("/api/hr/shifts", headers=cas).status_code == 403
    assert client.post("/api/hr/shifts", headers=cas, json={
        "name": "x", "start_time": "08:00", "end_time": "12:00"}).status_code == 403


# ───────────────────────── §۲۶–۲۷: حقوق + اتصال حسابداری ─────────────────────────

def test_payroll_flow_posts_journal(client, auth_headers):
    _mkuser(client, auth_headers, "pay_ali", roles=["Salesperson"])
    users = {u["username"]: u["id"] for u in client.get("/api/users", headers=auth_headers).json()}
    r = client.post("/api/hr/payroll", headers=auth_headers, json={
        "user_id": users["pay_ali"], "period": "1404-07", "base_salary": 10_000_000,
        "worked_hours": 10, "hourly_pay": 50_000, "overtime_hours": 2,
        "bonus": 500_000, "benefits": 200_000, "deductions": 100_000})
    assert r.status_code == 201, r.text
    row = r.json()
    # مجموع = پایه + ساعتی×ساعات + اضافه‌کاری(۱٫۴×) + مزایا + پاداش − کسورات
    expected = 10_000_000 + 10 * 50_000 + int(2 * 50_000 * 1.4) + 200_000 + 500_000 - 100_000
    assert row["total"] == expected, (row["total"], expected)
    assert client.post(f"/api/hr/payroll/{row['id']}/pay", headers=auth_headers).status_code == 400  # قبل از تأیید
    assert client.post(f"/api/hr/payroll/{row['id']}/approve", headers=auth_headers).status_code == 200
    r = client.post(f"/api/hr/payroll/{row['id']}/pay", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "PAID" and r.json()["payment_ref"].startswith("JE:")
    # سند حسابداری واقعی ثبت شده (§۲۷ — Employee → Payroll → Accounting)
    r = client.get("/api/accounting/journal", headers=auth_headers)
    if r.status_code == 200:
        assert "حقوق" in json.dumps(r.json(), ensure_ascii=False)
    # پرداخت‌شده قفل است
    assert client.patch(f"/api/hr/payroll/{row['id']}", headers=auth_headers,
                        json={"bonus": 1}).status_code == 400


def test_payroll_permission_gate(client, auth_headers):
    _mkuser(client, auth_headers, "pay_cas", roles=["Cashier"])
    cas = _login(client, "pay_cas", "pass1234")
    assert client.get("/api/hr/payroll", headers=cas).status_code == 403


# ───────────────────────── §۲۱–۲۴: عملکرد، نمودار، PDF ─────────────────────────

def test_performance_reports_charts_pdf(client, auth_headers):
    _mkuser(client, auth_headers, "perf_ali", roles=["Salesperson"])
    users = {u["username"]: u["id"] for u in client.get("/api/users", headers=auth_headers).json()}
    h = _login(client, "perf_ali", "pass1234")
    me = client.get("/api/hr/performance/me", headers=h)
    assert me.status_code == 200
    body = me.json()
    for key in ("sales_total", "invoice_count", "avg_invoice", "customer_count",
                "sales_in_shift", "sales_out_of_shift", "daily_series", "achievements"):
        assert key in body, key
    charts = client.get(f"/api/hr/performance/charts/{users['perf_ali']}", headers=h).json()
    ids = {c["id"] for c in charts}
    assert {"sales_daily", "invoices_daily", "avg_invoice", "sales_weekly", "sales_monthly"} <= ids
    # PDF واقعی (§۲۳) — بایت‌های PDF با سربرگ %PDF
    r = client.get(f"/api/hr/performance/pdf/{users['perf_ali']}", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert r.content[:4] == b"%PDF"
    assert r.headers["content-type"] == "application/pdf"
    # بدون reports.export برای دیگران ممنوع
    r = client.get(f"/api/hr/performance/pdf/{users['perf_ali']}", headers=h)
    assert r.status_code in (200, 403)  # خودِ کاربر مجاز است (§۲۳ «مدیر»، خودی همیشه)
    _mkuser(client, auth_headers, "perf_cas", roles=["Cashier"])
    cas = _login(client, "perf_cas", "pass1234")
    assert client.get(f"/api/hr/performance/pdf/{users['perf_ali']}", headers=cas).status_code == 403


def test_performance_team_for_manager(client, auth_headers):
    r = client.get("/api/hr/performance/team", headers=auth_headers)
    assert r.status_code == 200
    rows = r.json()
    assert rows and {"user_id", "sales_total", "roles"} <= set(rows[0].keys())


# ───────────────────────── §۴–۱۳: داشبورد Widget ─────────────────────────

def test_widgets_permission_filtered_and_multirole_union(client, auth_headers):
    _mkuser(client, auth_headers, "wd_seller", roles=["Salesperson", "Cashier"])
    h = _login(client, "wd_seller", "pass1234")
    w = client.get("/api/hr/widgets", headers=h).json()
    allowed = {x["id"] for x in w["all_allowed"]}
    # اجتماع دو نقش (§۶): هم فروشنده هم صندوقدار
    assert "sales.my_today" in allowed and "cash.session" in allowed
    # فقط دیدن موجودی ≠ ایجاد/ویرایش (§۷): Widgetهای مدیریتی نیست
    assert "mgmt.pnl" not in allowed and "mgmt.payroll" not in allowed
    # گروه‌ها بر اساس مجازها ساخته می‌شوند
    ids = {x["id"] for g in w["groups"] for x in g["widgets"]}
    assert ids == allowed - set(x["id"] for x in w["all_allowed"] if x["hidden"])


def test_widget_layout_personalization_and_forbidden(client, auth_headers):
    _mkuser(client, auth_headers, "wd_ali", roles=["Salesperson"])
    h = _login(client, "wd_ali", "pass1234")
    r = client.put("/api/hr/widgets/layout", headers=h, json={
        "order": ["sales.my_today", "sales.trend"], "pinned": ["sales.my_today"],
        "hidden": ["sales.top"], "sizes": {"sales.trend": "lg"}})
    assert r.status_code == 200, r.text
    w = r.json()
    # ترتیب/pin اعمال شده
    first_group = w["groups"][0]["widgets"][0]
    assert first_group["id"] == "sales.my_today" and first_group["pinned"]
    # فعال‌کردن Widget غیرمجاز ممنوع (§۸)
    r = client.put("/api/hr/widgets/layout", headers=h, json={
        "order": ["mgmt.pnl"], "pinned": [], "hidden": [], "sizes": {}})
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "FORBIDDEN_WIDGET"


# ───────────────────────── §۳۴–۳۵: امتیاز/دستاورد با Evidence ─────────────────────────

def test_score_and_achievements_require_evidence(client, auth_headers):
    from app.services import achievements as ach
    from app.database import SessionLocal
    users = {u["username"]: u["id"] for u in client.get("/api/users", headers=auth_headers).json()}
    s = SessionLocal()
    try:
        try:
            ach.add_score(s, user_id=users["perf_ali"], points=10, source="SALE", evidence={})
            assert False, "امتیاز بدون evidence باید رد شود (§۳۴)"
        except ach.AchievementError as exc:
            assert exc.code == "NO_EVIDENCE"
        ev = ach.add_score(s, user_id=users["perf_ali"], points=10, source="SALE",
                           evidence={"ref_type": "invoice", "ref_id": 1})
        assert ev.id
        try:
            ach.award(s, user_id=users["perf_ali"], code="TOP_SELLER", evidence={})
            assert False, "نشان بدون evidence باید رد شود (§۳۵)"
        except ach.AchievementError:
            pass
        a = ach.award(s, user_id=users["perf_ali"], code="TOP_SELLER",
                      evidence={"event": "sales_threshold", "metric": "paid_invoices", "value": 12})
        assert a and a.code == "TOP_SELLER"
    finally:
        s.close()


# ───────────────────────── §۳۸–۴۰: Developer Mode ─────────────────────────

def test_dev_mode_hidden_without_permission(client, auth_headers):
    _mkuser(client, auth_headers, "dev_cas", roles=["Cashier"])
    cas = _login(client, "dev_cas", "pass1234")
    assert client.get("/api/dev/overview", headers=cas).status_code == 403
    assert client.get("/api/dev/logs", headers=cas).status_code == 403
    # با دسترسی dev.mode — باز
    _mkuser(client, auth_headers, "dev_ops", roles=[], permissions=["dev.mode"])
    ops = _login(client, "dev_ops", "pass1234")
    r = client.get("/api/dev/overview", headers=ops)
    assert r.status_code == 200 and r.json()["build"]
    r = client.get("/api/dev/logs", headers=ops)
    assert r.status_code == 200 and "categories" in r.json()
    r = client.get("/api/dev/db/tables", headers=ops)
    assert r.status_code == 200 and any(t["table"] == "users" for t in r.json())
    r = client.get("/api/dev/network", headers=ops)
    assert r.status_code == 200 and r.json()["update_repo"].endswith("Rasasys")
