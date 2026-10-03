# -*- coding: utf-8 -*-
"""build-489 — گزارش مالک: داشبورد نقش‌محور، بستن نشت دید، تولتیپ نقش‌ها، «تاثیر» صادقانه.

ریشه‌هایی که این تست‌ها نگه می‌دارند:
  ۱. /hr/widgets باید `card` بدهد و کارت‌های غیرمجاز را در `hide_cards` — وگرنه چیدمان
     هرگز اعمال نمی‌شد و داشبورد صندوق‌دار = داشبورد مدیر (نشت دید).
  ۲. تخفیف‌ها و کمپین‌ها دسترسی خودش را دارد؛ صندوق‌دار نبیند.
  ۳. هوش فروشگاه شغل‌محور: پیشنهادهای مالی/قیمت/پرسنلی فقط با دسترسی خودشان.
  ۴. /users/permissions برای تولتیپ نقش‌ها باید به‌روز باشد.
"""
from app.models import Insight
from app.services.widgets import WIDGETS
from tests.test_v488_people import _login, _mkuser

PW = "pass1234"  # قرارداد _mkuser در test_v488_people


# _login از test_v488_people خودش dict هدر کامل برمی‌گرداند


def test_widget_compose_carries_cards_and_hide_list(client, auth_headers):
    d = client.get("/api/hr/widgets", headers=auth_headers).json()
    by_id = {w["id"]: w for w in d["all_allowed"]}
    assert by_id.get("sales.today", {}).get("card") == ".og-kpis", "فیلد card باید در all_allowed باشد"
    assert "hide_cards" in d and isinstance(d["hide_cards"], list)
    assert ".og-kpis" not in d["hide_cards"]  # admin به همه دسترسی دارد


def test_cashier_dashboard_is_not_the_admin_dashboard(client, auth_headers):
    _mkuser(client, auth_headers, "w489_cash", ["Cashier"])
    hdrs = _login(client, "w489_cash", PW)
    d = client.get("/api/hr/widgets", headers=hdrs).json()
    allowed = {w["id"] for w in d["all_allowed"]}
    assert "sales.today" in allowed  # reports.view دارد
    # هر کارتی که Widget آن مجاز نیست باید در hide_cards باشد (نشت دید ممنوع)
    for wid, meta in WIDGETS.items():
        if meta["card"] and wid not in allowed:
            assert meta["card"] in d["hide_cards"], wid
    assert d["hide_cards"], "برای صندوق‌دار باید کارت‌های غیرمجاز مخفی شوند"
    # ذخیرهٔ چیدمان برای ویجت غیرمجاز باید رد شود (§۸)
    r = client.put("/api/hr/widgets/layout", headers=hdrs,
                   json={"order": ["mgmt.pnl"], "pinned": [], "hidden": [], "sizes": {}})
    assert r.status_code in (400, 403), r.text  # رد شود — کد دقیق قرارداد router است


def test_marketing_hidden_from_cashier_but_open_for_manager(client, auth_headers):
    _mkuser(client, auth_headers, "w489_cash2", ["Cashier"])
    hdrs = _login(client, "w489_cash2", PW)
    assert client.get("/api/marketing/campaigns", headers=hdrs).status_code == 403
    assert client.get("/api/marketing/stats", headers=hdrs).status_code == 403
    # ولی صندوق‌دار باید کوپن را هنگام فروش اعتبارسنجی کند (pos.sell — نه marketing)
    assert client.post("/api/marketing/coupons/validate", headers=hdrs,
                       json={"code": "NOPE"}).status_code in (200, 400, 404, 422)
    _mkuser(client, auth_headers, "w489_mgr", ["Manager"])
    mhdrs = _login(client, "w489_mgr", PW)
    assert client.get("/api/marketing/campaigns", headers=mhdrs).status_code == 200


def test_insights_are_job_filtered(client, auth_headers, db_session=None):
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        rows = [
            Insight(kind="CASHFLOW", title="جریان نقدی", body="مالی", status="NEW",
                    priority=3, expected_gain=0, dedupe_key="w489:cashflow"),
            Insight(kind="CUST_FAVORITE", title="مشتری وفادار", body="مشتری", status="NEW",
                    priority=3, expected_gain=0, dedupe_key="w489:custfav"),
        ]
        for r in rows:
            db.add(r)
        db.flush()
        ids = [r.id for r in rows]
    finally:
        db.commit()
        db.close()

    _mkuser(client, auth_headers, "w489_cash3", ["Cashier"])
    hdrs = _login(client, "w489_cash3", PW)
    got = client.get("/api/insights?status=NEW&limit=300", headers=hdrs).json()
    kinds = {x["kind"] for x in got if x["id"] in ids}
    assert "CUST_FAVORITE" in kinds
    assert "CASHFLOW" not in kinds, "صندوق‌دار نباید پیشنهاد مالی ببیند"

    atok = auth_headers["Authorization"].split()[-1]
    allg = client.get(f"/api/insights?status=NEW&limit=300", headers=auth_headers).json()
    akinds = {x["kind"] for x in allg if x["id"] in ids}
    assert {"CASHFLOW", "CUST_FAVORITE"} <= akinds


def test_roles_expose_permissions_for_tooltips(client, auth_headers):
    roles = client.get("/api/users/roles", headers=auth_headers).json()
    cashier = next((r for r in roles if r["name"] == "Cashier"), None)
    assert cashier and "permissions" in cashier
    assert "pos.sell" in cashier["permissions"]


def test_ui_guards_are_pinned():
    """نگهبان‌های UI (منبع) — الگوی نشت نباید دوباره برگردد."""
    import pathlib
    app_js = pathlib.Path(__file__).resolve().parents[2].joinpath("frontend", "app.js").read_text(encoding="utf-8")
    assert '"marketing", "تخفیف‌ها و کمپین‌ها", "marketing.view"' in app_js
    assert "hide_cards" in app_js and "wLocked" in app_js
    assert 'localStorage.getItem("m_token")' not in app_js  # نشت نشست بین حساب‌ها ممنوع
    assert 'can("inventory.stocktake")' in app_js
    ins = pathlib.Path(__file__).resolve().parents[2].joinpath("frontend", "insights.js").read_text(encoding="utf-8")
    assert "MISSED_OPPORTUNITY" in ins and "ضرر نیست" in ins
    assert "ضرر واقعی (مستند)" in ins
