"""Stock report routes require both report scope and inventory visibility."""
from tests.test_v488_people import _login, _mkuser


PW = "pass1234"


def test_stock_reports_require_reports_and_inventory_or_storewide_reports(client, auth_headers):
    cases = [
        ("b496_inventory_only", ["inventory.view"], 403),
        ("b496_reports_only", ["reports.view"], 403),
        ("b496_both_scopes", ["reports.view", "inventory.view"], 200),
        ("b496_storewide_reports", ["reports.view_all"], 200),
    ]
    for username, permissions, expected in cases:
        _mkuser(client, auth_headers, username, roles=[], permissions=permissions)
        response = client.get("/api/reports/inventory", headers=_login(client, username, PW))
        assert response.status_code == expected, (username, response.status_code, response.text)
