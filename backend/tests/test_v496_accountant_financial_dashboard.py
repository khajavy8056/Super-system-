"""The accountant dashboard carries a permission-scoped financial chart and journal activity."""
from pathlib import Path

from app.services.timeservice import local_today
from tests.test_v488_people import _login, _mkuser


ROOT = Path(__file__).resolve().parents[2]
PW = "pass1234"


def test_accounting_overview_and_dashboard_include_recent_income_expense_and_journal(client, auth_headers, milk, two_batches):
    sale = client.post("/api/pos/checkout", headers=auth_headers, json={
        "items": [{"product_id": milk["id"], "batch_id": two_batches["a"]["id"], "quantity": 1}],
        "payments": [{"method": "CASH", "amount": 60000}],
    })
    assert sale.status_code == 201, sale.text

    categories = client.get("/api/accounting/expense-categories", headers=auth_headers)
    assert categories.status_code == 200, categories.text
    rent = next(category for category in categories.json() if category["account_code"] == "6101")
    expense = client.post("/api/accounting/expenses", headers=auth_headers, json={
        "category_id": rent["id"], "amount": 25000, "paid_from": "CASH", "description": "Dashboard test expense",
    })
    assert expense.status_code == 201, expense.text

    overview = client.get("/api/accounting/overview", headers=auth_headers)
    assert overview.status_code == 200, overview.text
    overview_data = overview.json()
    trend = overview_data["income_expense_trend"]
    assert len(trend) == 7
    assert [point["date"] for point in trend] == sorted(point["date"] for point in trend)
    today = next(point for point in trend if point["date"] == local_today().isoformat())
    assert today["income"] >= sale.json()["total_amount"]
    assert today["expenses"] >= 25000
    assert any(entry["id"] == expense.json()["journal_entry_id"] for entry in overview_data["recent_entries"])

    _mkuser(client, auth_headers, "b496_finance_chart", roles=["Accountant"])
    dashboard = client.get("/api/reports/dashboard", headers=_login(client, "b496_finance_chart", PW))
    assert dashboard.status_code == 200, dashboard.text
    accounting = dashboard.json()["accounting"]
    assert accounting["income_expense_trend"] == trend
    assert accounting["recent_entries"] == overview_data["recent_entries"]


def test_local_and_windows_accountant_dashboards_render_financial_chart_and_ledger():
    web = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    android = (ROOT / "mobile-android/app/src/main/java/ir/khajavy/supermarket/Screens.java").read_text(encoding="utf-8")
    local = (ROOT / "mobile-android/app/src/main/java/ir/khajavy/supermarket/Local.java").read_text(encoding="utf-8")

    assert "incomeExpenseChart(accountingData.income_expense_trend)" in web
    assert "recentLedgerHtml" in web and "role-ledger-entries" in web
    assert "addIncomeExpenseChart(accounts == null ? null : accounts.optJSONArray(\"income_expense_trend\"))" in android
    assert "addRecentLedgerCard(accounts == null ? null : accounts.optJSONArray(\"recent_entries\"))" in android
    assert 'summary.put("income_expense_trend", incomeExpenseTrend())' in local
    assert 'summary.put("recent_entries", recentJournalEntries())' in local
    assert "if (!Screens.can(\"accounting.view\")) d.put(\"accounting\", JSONObject.NULL);" in local
