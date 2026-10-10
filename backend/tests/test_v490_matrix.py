# -*- coding: utf-8 -*-
"""build-490 — دستور جامع: ماتریس نقش‌ها، زنجیرهٔ Role → Permission → Data Scope،
هوش شغل‌محور + تصویر واقعی محصول، و ساختار نسخهٔ Major.Minor.Build.

قراردادهای نگه‌داشته‌شده:
  ۱. صندوقدار/حسابدار/سوپروایزر/مدیر کل فقط مسئولیت خودشان (ROLE_PRESETS).
  ۲. اطلاعات حساس اصلاً به کلاینت نمی‌رود (نه فقط مخفی در UI).
  ۳. هوش: پیشنهاد مالی/قیمت/انباری/پرسنلی فقط با دسترسی خودش؛ تصویر محصول با ID واقعی.
  ۴. نسخه: «1.0.491» (رقم سوم = Build) با سازگاری کامل با «1.0.0-build.489» قدیمی.
"""
import math

from app.services import insights as svc
from app.services import updater
from tests.test_v488_people import _login, _mkuser

PW = "pass1234"


def _hdrs(client, user, pw=PW):
    return _login(client, user, pw)


# ───────────────────────── ۱) ماتریس نقش‌ها ─────────────────────────

def test_role_presets_match_the_directive(client, auth_headers):
    roles = {r["name"]: set(r["permissions"]) for r in client.get("/api/users/roles", headers=auth_headers).json()}
    cashier = roles["Cashier"]
    assert {"pos.sell", "customers.manage", "reports.view"} <= cashier
    for forbidden in ("users.manage", "accounting.view", "settings.manage", "audit.view",
                      "payroll.manage", "performance.view_all", "marketing.view", "reports.view_all"):
        assert forbidden not in cashier, f"صندوقدار نباید {forbidden} داشته باشد"
    acc = roles["Accountant"]
    assert {"accounting.view", "accounting.post", "reports.view_all", "customers.ledger"} <= acc
    for forbidden in ("users.manage", "settings.manage", "pos.sell", "audit.view", "payroll.manage"):
        assert forbidden not in acc, f"حسابدار نباید {forbidden} داشته باشد"
    sup = roles["Supervisor"]
    assert {"batches.manage", "inventory.adjust", "marketing.manage", "reports.view_all", "pos.sell"} <= sup
    # build-491 — تعریف شیفت توسط سوپروایزر یا مدیر (دستور صریح مالک): shifts.manage اضافه شد
    assert "shifts.manage" in sup
    for forbidden in ("users.manage", "settings.manage", "performance.view_all", "payroll.manage",
                      "audit.view"):
        assert forbidden not in sup, f"سوپروایزر نباید {forbidden} داشته باشد"
    gm = roles["General Manager"]
    assert {"users.manage", "settings.manage", "audit.view", "performance.view_all", "dev.mode"} <= gm


# ───────────────────────── ۲) دامنهٔ داده (Data Scope) ─────────────────────────

def test_dashboard_scope_is_self_for_cashier_and_store_for_manager(client, auth_headers):
    _mkuser(client, auth_headers, "w490_cash", ["Cashier"])
    h = _hdrs(client, "w490_cash")
    d = client.get("/api/reports/dashboard", headers=h).json()
    assert d["scope"] == "self"
    assert d["today_by_staff"] == [] or all(r.get("user_id") is not None for r in d["today_by_staff"])
    assert not d.get("receivables"), "دادهٔ مالی نباید برای صندوقدار ارسال شود (§۷)"
    assert not d.get("accounting"), "دادهٔ مالی نباید برای صندوقدار ارسال شود (§۷)"
    assert not d.get("top_products"), "دادهٔ مدیریتی نباید برای صندوقدار ارسال شود (§۷)"
    m = client.get("/api/reports/dashboard", headers=auth_headers).json()
    assert m["scope"] == "store"
    assert isinstance(m.get("today_by_staff"), list)


def test_invoices_are_self_scoped_without_view_all(client, auth_headers):
    _mkuser(client, auth_headers, "w490_cash2", ["Cashier"])
    h = _hdrs(client, "w490_cash2")
    r = client.get("/api/invoices?limit=50", headers=h).json()
    assert "items" in r
    _mkuser(client, auth_headers, "w490_acc", ["Accountant"])
    ah = _hdrs(client, "w490_acc")
    assert client.get("/api/reports/cashiers", headers=ah).status_code == 200  # view_all دارد
    assert client.get("/api/reports/cashiers", headers=h).status_code == 403   # صندوقدار نه


def test_support_tickets_are_isolated(client, auth_headers):
    _mkuser(client, auth_headers, "w490_cash3", ["Cashier"])
    h = _hdrs(client, "w490_cash3")
    t = client.post("/api/support/tickets", headers=h, json={
        "type": "BUG", "priority": "NORMAL", "subject": "w490-ticket-iso", "description": "x"}).json()
    assert t.get("number")
    r = client.get("/api/support/tickets", headers=h)
    assert r.status_code == 200, r.text
    mine = r.json()
    assert isinstance(mine, list) and mine, "فهرست تیکت‌های خودِ کاربر"
    assert all(x["subject"] == "w490-ticket-iso" for x in mine), "تیکت دیگران نباید دیده شود (§۷)"
    # مدیر میز پشتیبانی همه را می‌بیند
    admin = client.get("/api/support/tickets", headers=auth_headers).json()
    assert any(x["number"] == t["number"] for x in admin)


# ───────────────────────── ۳) هوش شغل‌محور + تصویر محصول ─────────────────────────

def test_insights_are_job_scoped_and_carry_product_images(client, auth_headers):
    from app.database import SessionLocal
    from app.models import Insight, Product
    db = SessionLocal()
    try:
        p = db.query(Product).filter(Product.deleted_at.is_(None)).first()
        pid = p.id if p else None
        rows = [
            Insight(kind="CASHFLOW", title="w490-cashflow", body="m", status="NEW", priority=3,
                    expected_gain=0, dedupe_key="w490:cf", metric='{"metric":"product_units"}'),
            Insight(kind="DEAD_STOCK", title="w490-dead", body="s", status="NEW", priority=3,
                    expected_gain=0, dedupe_key="w490:dead",
                    metric='{"metric":"product_units","product_id":%s}' % pid if pid else "{}"),
            Insight(kind="CUST_FAVORITE", title="w490-cust", body="c", status="NEW", priority=3,
                    expected_gain=0, dedupe_key="w490:cust"),
        ]
        for r in rows:
            db.add(r)
        db.flush()
        ids = [r.id for r in rows]
    finally:
        db.commit()
        db.close()

    _mkuser(client, auth_headers, "w490_cash4", ["Cashier"])
    h = _hdrs(client, "w490_cash4")
    got = client.get("/api/insights?status=NEW&limit=300", headers=h).json()
    mine = {x["id"]: x for x in got if x["id"] in ids}
    assert ids[2] in mine, "پیشنهاد مشتری باید برای صندوقدار باشد"
    assert ids[0] not in mine, "صندوق‌دار نباید پیشنهاد مالی ببیند (§۵)"
    assert ids[1] not in mine, "صندوق‌دار نباید پیشنهاد انباری ببیند (§۵ — گروه stock)"

    ah = auth_headers
    allg = {x["id"]: x for x in client.get("/api/insights?status=NEW&limit=300", headers=ah).json() if x["id"] in ids}
    assert {ids[0], ids[1], ids[2]} <= set(allg)
    if pid:
        assert allg[ids[1]].get("product_ids") == [pid], "product_ids باید از metric استخراج شود (§۶)"
        prods = allg[ids[1]].get("products") or []
        assert prods and prods[0]["id"] == pid, "تصویر محصول باید با شناسهٔ واقعی ضمیمه شود (§۶)"
    # دسترسی مستقیم URL به Insight غیرمجاز → 404 (§۲/§۷)
    assert client.get(f"/api/insights/{ids[0]}", headers=h).status_code == 404


# ───────────────────────── ۴) نسخه: Major.Minor.Build + سازگاری قدیمی ─────────────────────────

def test_version_scheme_and_cross_format_compare():
    from app import BUILD, __version__
    assert __version__ >= "1.0.491", __version__
    assert BUILD >= 49100
    assert updater.current_release_tag() == __version__
    assert updater.parse_version("1.0.491") == (1, 0, 491)
    assert updater.parse_version("1.0.0-build.489") == (1, 0, 489)   # قدیمی نرمال می‌شود
    assert updater.parse_version("1.0.0-build489") == (1, 0, 489)
    assert updater.is_newer("1.0.492", "1.0.491")
    assert updater.is_newer("1.0.491", "1.0.0-build.489")            # بین‌ساختاری
    assert updater.is_newer("1.0.0-build.490", "1.0.489")            # بین‌ساختاری
    assert not updater.is_newer("1.0.0-build.489", "1.0.491")
    assert not updater.is_newer("1.0.491", "1.0.491")


def test_ui_and_android_pins():
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[2]
    app_js = (root / "frontend" / "app.js").read_text(encoding="utf-8")
    assert "const UI_BUILD = 50" in app_js
    assert '["reports", "گزارش‌ها", "reports.view_all"' in app_js
    assert "inventory.adjust||inventory.stocktake" in app_js
    ins = (root / "frontend" / "insights.js").read_text(encoding="utf-8").replace(" ", "")
    assert "prodImgs" in ins and "ins-prod-img" in ins
    assert "1.0.50" in (root / "backend" / "app" / "__init__.py").read_text(encoding="utf-8")
