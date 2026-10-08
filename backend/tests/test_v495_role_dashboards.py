"""Build 495: distinct role dashboards consume the permission-scoped report API."""
from pathlib import Path

from tests.test_v488_people import _login, _mkuser


ROOT = Path(__file__).resolve().parents[2]


PW = "pass1234"


def test_dashboard_profile_is_selected_from_effective_permissions(client, auth_headers):
    cases = [
        ("b495_seller", "Salesperson", "seller"),
        ("b495_cashier", "Cashier", "seller"),
        ("b495_accountant", "Accountant", "accountant"),
        ("b495_supervisor", "Supervisor", "supervisor"),
        ("b495_manager", "Manager", "manager"),
        ("b495_inventory", "Inventory Operator", "operations"),
    ]
    for username, role, expected in cases:
        _mkuser(client, auth_headers, username, roles=[role])
        headers = _login(client, username, PW)
        response = client.get("/api/reports/dashboard", headers=headers)
        assert response.status_code == 200, response.text
        assert response.json()["dashboard_profile"] == expected

    # The account with the full permission set gets the administrator presentation;
    # that label does not change authorization or the data scope policy.
    admin = client.get("/api/reports/dashboard", headers=auth_headers)
    assert admin.status_code == 200, admin.text
    assert admin.json()["dashboard_profile"] == "administrator"
    assert admin.json()["scope"] == "store"

    # A direct permission grant, without a named role, must resolve the same profile.
    _mkuser(client, auth_headers, "b495_direct", roles=[], permissions=["reports.view", "pos.sell"])
    direct = client.get("/api/reports/dashboard", headers=_login(client, "b495_direct", PW))
    assert direct.status_code == 200, direct.text
    assert direct.json()["dashboard_profile"] == "seller"
    assert direct.json()["scope"] == "self"
    assert isinstance(direct.json()["today_by_payment"], list)

    inventory_user = client.get("/api/reports/dashboard", headers=_login(client, "b495_inventory", PW))
    assert inventory_user.status_code == 200, inventory_user.text
    assert inventory_user.json()["accounting"] is None
    assert isinstance(inventory_user.json()["profit"], dict)  # cost permission is separate


def test_seller_profile_stays_self_scoped_and_accountant_keeps_financial_scope(client, auth_headers):
    _mkuser(client, auth_headers, "b495_self", roles=["Salesperson"])
    seller = client.get("/api/reports/dashboard", headers=_login(client, "b495_self", PW))
    assert seller.status_code == 200, seller.text
    body = seller.json()
    assert body["dashboard_profile"] == "seller"
    assert body["scope"] == "self"
    assert body["accounting"] is None
    assert body["today_by_staff"] == []

    _mkuser(client, auth_headers, "b495_finance", roles=["Accountant"])
    accountant = client.get("/api/reports/dashboard", headers=_login(client, "b495_finance", PW))
    assert accountant.status_code == 200, accountant.text
    body = accountant.json()
    assert body["dashboard_profile"] == "accountant"
    assert body["scope"] == "store"
    assert isinstance(body["accounting"], dict)


def test_no_scope_dashboard_does_not_leak_store_sales_and_accounting_is_independent(client, auth_headers, milk, two_batches):
    sale = client.post("/api/pos/checkout", headers=auth_headers, json={
        "items": [{"product_id": milk["id"], "batch_id": two_batches["a"]["id"], "quantity": 1}],
        "tax_rate": 0, "payments": [{"method": "CASH", "amount": 60000}],
    })
    assert sale.status_code == 201, sale.text

    _mkuser(client, auth_headers, "b495_no_scope", roles=[], permissions=["reports.view"])
    no_scope = client.get("/api/reports/dashboard", headers=_login(client, "b495_no_scope", PW))
    assert no_scope.status_code == 200, no_scope.text
    body = no_scope.json()
    assert body["scope"] == "none"
    assert body["sales"]["today"] == 0
    assert body["sales"]["month"] == 0
    assert body["recent_invoices"] == []
    assert body["today_by_payment"] == []
    assert body["accounting"] is None

    _mkuser(client, auth_headers, "b495_finance_only", roles=[],
            permissions=["reports.view", "accounting.view"])
    finance = client.get("/api/reports/dashboard", headers=_login(client, "b495_finance_only", PW))
    assert finance.status_code == 200, finance.text
    body = finance.json()
    assert body["dashboard_profile"] == "accountant"
    assert body["scope"] == "none"
    assert body["sales"]["today"] == 0
    assert body["recent_invoices"] == []
    assert isinstance(body["accounting"], dict)
    assert body["profit"] is None  # accounting.view does not grant pricing.view_cost


def test_role_dashboard_contract_is_present_in_windows_and_native_android():
    app_js = (ROOT / "frontend/app.js").read_text(encoding="utf-8")
    assert "function dashboardProfileFromPermissions(" in app_js
    assert 'if (profile === "seller")' in app_js
    assert 'if (profile === "accountant")' in app_js
    assert "dashboard-profile--" in app_js
    assert 'viewEl.dataset.customDashboard !== "1"' in app_js

    java_dir = ROOT / "mobile-android/app/src/main/java/ir/khajavy/supermarket"
    screens = (java_dir / "Screens.java").read_text(encoding="utf-8")
    local = (java_dir / "Local.java").read_text(encoding="utf-8")
    assert "dashboardProfileFromPermissions" in screens
    assert "dashboard_profile" in screens
    assert "renderManagementActions(profile)" in screens
    assert "redactDashboardPermissions(d)" in local
    assert "status='PAID' AND user_id=?" in local
    assert 'Long userId = Screens.can("reports.view_all") ? null : Db.localUserId();' in local
    assert 'AND i.user_id=?' in local
    assert 'accountingDashboard(Jalali.daysAgoIso(30))' in local
    assert 'v.classList.remove("dashboard-profile--" + oldProfile)' in app_js
