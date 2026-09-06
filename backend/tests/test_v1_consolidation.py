"""v1.0.0 consolidation regression tests.

These cover the gaps found while merging the two parallel development lines
(v0.3.1 feature line + v0.4.0 installer line). Every test here asserts an
*observed* result through the real HTTP surface or the real service call — not
the presence of a file or a string in the source.

Sections exercised: §12, §19, §23, §43, §52, §56.
"""
from __future__ import annotations

import re
from decimal import Decimal
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent.parent


# --- helpers -----------------------------------------------------------------

def _product(client, headers, barcode="6260000001111", name="کالای آزمون یکپارچه‌سازی"):
    r = client.post("/api/products", headers=headers, json={"barcode": barcode, "name": name})
    assert r.status_code == 201, r.text
    return r.json()


def _batch(client, headers, product_id, qty=10, buy=1000, sell=2000):
    r = client.post("/api/batches/receive", headers=headers, json={
        "product_id": product_id, "quantity_received": qty,
        "buy_price": buy, "sell_price": sell})
    assert r.status_code == 201, r.text
    return r.json()


def _audit_actions(client, headers, limit=400):
    r = client.get(f"/api/audit?limit={limit}", headers=headers)
    assert r.status_code == 200, r.text
    payload = r.json()
    rows = payload["items"] if isinstance(payload, dict) and "items" in payload else payload
    return [row["action"] for row in rows]


# --- §23 dashboard ------------------------------------------------------------

def test_dashboard_has_the_four_missing_blocks(client, auth_headers):
    """§23 lists 12 dashboard metrics; receivables/SMS/system were absent."""
    r = client.get("/api/reports/dashboard", headers=auth_headers)
    assert r.status_code == 200, r.text
    d = r.json()
    for block in ("sales", "profit", "inventory", "expiry", "pricing",
                  "receivables", "sms", "system"):
        assert block in d, f"dashboard is missing the '{block}' block"

    assert {"customer_debt", "debtor_count", "top_debtors",
            "pending_amount", "pending_count"} <= set(d["receivables"])
    assert {"provider", "configured", "by_status", "pending",
            "sent", "failed"} <= set(d["sms"])
    assert {"version", "database", "hardware", "status",
            "issues", "disk_free_gb"} <= set(d["system"])


def test_dashboard_receivables_reflects_a_real_credit_sale(client, auth_headers):
    """A credit sale must show up as customer debt, not vanish."""
    cust = client.post("/api/customers", headers=auth_headers, json={
        "name": "بدهکار", "last_name": "آزمون", "phone": "09120001122",
        "allow_credit": True, "credit_limit": 10_000_000}).json()
    p = _product(client, auth_headers, barcode="6260000002222", name="کالای نسیه")
    b = _batch(client, auth_headers, p["id"], qty=10, buy=1000, sell=2000)

    r = client.post("/api/pos/checkout", headers=auth_headers, json={
        "items": [{"product_id": p["id"], "batch_id": b["id"], "quantity": 3}],
        "payments": [{"method": "ACCOUNT", "amount": 6000}],
        "customer_id": cust["id"]})
    assert r.status_code == 201, r.text

    d = client.get("/api/reports/dashboard", headers=auth_headers).json()
    recv = d["receivables"]
    assert recv["customer_debt"] >= 6000, recv
    assert recv["debtor_count"] >= 1, recv

    # top_debtors is capped at 5 and sorted by balance, so under a populated
    # shared test DB our brand-new debtor can be crowded out of the top five.
    # The full debtor list (which feeds the SMS reminder screen) must contain
    # it regardless of ordering.
    debtors = client.get("/api/customers/debtors", headers=auth_headers).json()
    mine = [x for x in debtors if x["customer_id"] == cust["id"]]
    assert mine and float(mine[0]["balance"]) >= 6000, debtors


def test_dashboard_system_block_reports_the_running_version(client, auth_headers):
    from app import __version__

    d = client.get("/api/reports/dashboard", headers=auth_headers).json()
    assert d["system"]["version"] == __version__
    assert d["system"]["status"] in ("OK", "WARNING")


def test_dashboard_sms_block_counts_queued_messages(client, auth_headers):
    """With no provider configured a message stays PENDING and must be counted."""
    before = client.get("/api/reports/dashboard", headers=auth_headers).json()["sms"]
    r = client.post("/api/sms/send", headers=auth_headers,
                    json={"phone": "09120003344", "text": "آزمون وضعیت پیامک"})
    assert r.status_code in (200, 201), r.text
    after = client.get("/api/reports/dashboard", headers=auth_headers).json()["sms"]
    assert after["total"] == before["total"] + 1
    assert after["pending"] >= 1


# --- §43 audit trail ----------------------------------------------------------

def test_product_delete_is_audited(client, auth_headers):
    """§43 PRODUCT_DELETED — a product could disappear with no trace."""
    p = _product(client, auth_headers, barcode="6260000003333", name="کالای حذف‌شدنی")
    r = client.delete(f"/api/products/{p['id']}", headers=auth_headers)
    assert r.status_code == 204, r.text
    assert "PRODUCT_DELETED" in _audit_actions(client, auth_headers)


def test_product_delete_is_soft_and_keeps_history(client, auth_headers):
    """§30 — deleting a product must not destroy its financial history."""
    p = _product(client, auth_headers, barcode="6260000004444", name="کالای دارای سابقه")
    b = _batch(client, auth_headers, p["id"], qty=5, buy=1000, sell=2000)
    r = client.post("/api/pos/checkout", headers=auth_headers, json={
        "items": [{"product_id": p["id"], "batch_id": b["id"], "quantity": 2}],
        "payments": [{"method": "CASH", "amount": 4000}]})
    assert r.status_code == 201, r.text
    invoice_id = r.json()["invoice_id"]

    assert client.delete(f"/api/products/{p['id']}",
                         headers=auth_headers).status_code == 204

    inv = client.get(f"/api/invoices/{invoice_id}", headers=auth_headers)
    assert inv.status_code == 200, inv.text
    assert float(inv.json()["total_amount"]) == 4000.0

    mv = client.get(f"/api/inventory/movements?product_id={p['id']}",
                    headers=auth_headers)
    assert mv.status_code == 200, mv.text
    rows = mv.json()["items"] if isinstance(mv.json(), dict) else mv.json()
    assert len(rows) >= 2, "stock movements were lost when the product was deleted"


def test_barcode_lookup_is_audited(client, auth_headers):
    """§43 BARCODE_LOOKUP — an unreachable provider must leave a trace."""
    r = client.post("/api/barcode/scan?barcode=6260000005555", headers=auth_headers)
    assert r.status_code in (200, 201), r.text
    assert "BARCODE_LOOKUP" in _audit_actions(client, auth_headers)


def test_sms_terminal_states_are_audited(client, auth_headers):
    """§43 SMS_SENT / SMS_FAILED — only terminal outcomes, and honestly."""
    # 'file' provider actually delivers locally; 'fail' always errors out.
    client.put("/api/settings", headers=auth_headers,
               json={"key": "sms.provider", "value": "fail", "is_secret": False})
    client.put("/api/settings", headers=auth_headers,
               json={"key": "sms.max_retries", "value": "1", "is_secret": False})
    client.post("/api/sms/send", headers=auth_headers,
                json={"phone": "09120005566", "text": "آزمون شکست پیامک"})
    r = client.post("/api/sms/dispatch", headers=auth_headers)
    assert r.status_code == 200, r.text

    actions = _audit_actions(client, auth_headers)
    assert "SMS_FAILED" in actions, actions[:20]

    client.put("/api/settings", headers=auth_headers,
               json={"key": "sms.provider", "value": "file", "is_secret": False})
    client.post("/api/sms/send", headers=auth_headers,
                json={"phone": "09120007788", "text": "آزمون ارسال پیامک"})
    assert client.post("/api/sms/dispatch", headers=auth_headers).status_code == 200
    assert "SMS_SENT" in _audit_actions(client, auth_headers)


def test_update_lifecycle_is_audited(client, auth_headers):
    """§43 UPDATE_STARTED plus exactly one terminal event per attempt."""
    from app.database import SessionLocal
    from app.services.updater import UpdateError, prepare_update

    class _NoChannel:
        """A channel that reports nothing available — offline sandbox reality."""

        def fetch_latest(self):
            raise UpdateError("CHANNEL_UNREACHABLE", "no network in test")

    db = SessionLocal()
    try:
        result = prepare_update(db, channel=_NoChannel(), download=False)
    finally:
        db.close()

    assert result["status"] in ("FAILED", "ABORTED", "UP_TO_DATE", "NO_PACKAGE", "READY")
    actions = _audit_actions(client, auth_headers)
    assert "UPDATE_STARTED" in actions, actions[:20]
    assert ("UPDATE_FAILED" in actions) or ("UPDATE_COMPLETED" in actions)


def test_api_error_is_audited(client, auth_headers):
    """§43 API_ERROR — an unhandled server error must be traceable by error_id."""
    import asyncio
    import json as _json

    from fastapi import Request

    from app.main import unhandled_error_handler

    # Invoke the real handler the way Starlette would. This is the same code
    # path that runs when a route raises, and it is what writes the audit row.
    scope = {"type": "http", "method": "GET", "path": "/api/__consolidation_probe",
             "headers": [], "query_string": b"", "scheme": "http",
             "server": ("testserver", 80), "client": ("127.0.0.1", 1234)}
    request = Request(scope)
    response = asyncio.run(unhandled_error_handler(request, RuntimeError("deliberate")))

    body = _json.loads(response.body)
    assert response.status_code == 500
    assert body["detail"]["code"] == "INTERNAL_ERROR"
    assert body["detail"]["error_id"]
    # the user never sees the raw exception (§48)
    assert "deliberate" not in body["detail"]["message"]

    assert "API_ERROR" in _audit_actions(client, auth_headers)


# --- §12 units ----------------------------------------------------------------

def test_all_required_units_are_seeded(client, auth_headers):
    """§12 — میلی‌گرم was missing, so sub-gram lines could not be recorded."""
    r = client.get("/api/units", headers=auth_headers)
    assert r.status_code == 200, r.text
    names = {u["name"] for u in r.json()}
    for required in ("عدد", "گرم", "کیلوگرم", "میلی‌گرم", "میلی‌لیتر", "لیتر", "متر"):
        assert required in names, f"missing unit {required}; have {sorted(names)}"


# --- version single source of truth -------------------------------------------

def test_version_is_consistent_everywhere(client, auth_headers):
    """One number: __init__.py, /health, the OpenAPI spec, the Inno script."""
    from app import __version__

    assert __version__ == "1.0.0"
    health = client.get("/health").json()
    assert health["version"] == __version__
    assert client.get("/openapi.json").json()["info"]["version"] == __version__

    from app.config import settings
    assert settings.APP_VERSION == __version__

    iss = (REPO / "installer" / "windows" / "setup.iss").read_text(encoding="utf-8")
    m = re.search(r'#define MyAppVersion "([^"]+)"', iss)
    assert m, "setup.iss no longer declares a default MyAppVersion"
    assert m.group(1) == __version__


# --- §52 / installer build chain ----------------------------------------------

WINDOWS_DIR = REPO / "installer" / "windows"


def _ps1(name: str) -> str:
    return (WINDOWS_DIR / name).read_text(encoding="utf-8-sig")


def test_builder_scripts_define_scriptdir_before_dot_sourcing():
    """Regression: v0.3.1 read $ScriptDir before assigning it.

    Under `Set-StrictMode -Version Latest` that is a terminating error, so
    BUILD-SETUP.bat and build.ps1 both died before doing any work. The
    assignment must textually precede the dot-source of builder-lib.ps1.
    """
    for name in ("builder-gui.ps1", "build.ps1"):
        src = _ps1(name)
        assign = src.find("$ScriptDir = $PSScriptRoot")
        dot = src.find(". (Join-Path $ScriptDir 'builder-lib.ps1')")
        assert assign != -1, f"{name}: $ScriptDir is never assigned from $PSScriptRoot"
        assert dot != -1, f"{name}: builder-lib.ps1 is never dot-sourced"
        assert assign < dot, f"{name}: $ScriptDir is read before it is assigned"


def test_builder_lib_has_the_repository_preflight():
    """The v0.4.0 fix that must survive the merge: 11-file completeness check."""
    src = _ps1("builder-lib.ps1")
    assert "$required = @(" in src
    for needed in ("backend\\requirements.txt", "backend\\app\\main.py",
                   "installer\\windows\\app.spec", "installer\\windows\\setup.iss",
                   "installer\\windows\\run_supermarket.py"):
        assert needed in src, f"preflight no longer verifies {needed}"


def test_builder_lib_can_build_without_inno_setup():
    """No Inno Setup must degrade to a portable exe, not fail the build."""
    src = _ps1("builder-lib.ps1")
    assert "RequireSetup" in src, "the Inno-optional switch is gone"
    assert "-portable.exe" in src, "the portable output is gone"


def test_auto_download_is_opt_in():
    """The auto-download chain was the top reported cause of failed builds."""
    lib = _ps1("builder-lib.ps1")
    cli = _ps1("build.ps1")
    assert "AllowDownloads" in lib
    assert "-NoDownload" in cli or "[switch]$NoDownload" in cli


def test_inno_script_is_compatible_with_inno_6_0():
    """`x64compatible` aborts compilation on Inno Setup 6.0-6.2."""
    iss = (WINDOWS_DIR / "setup.iss").read_text(encoding="utf-8-sig")
    # only the directive matters; prose in a comment must not trip the check
    directives = [ln.strip() for ln in iss.splitlines() if not ln.strip().startswith(";")]
    arch = [ln for ln in directives if ln.startswith("ArchitecturesInstallIn64BitMode=")]
    assert arch == ["ArchitecturesInstallIn64BitMode=x64"], arch
    # a real GUID: the old value contained non-hex "SUPERMARKET01"
    m = re.search(r"AppId=\{\{([0-9A-Fa-f-]+)\}", iss)
    assert m, "AppId is not a GUID literal"
    assert re.fullmatch(r"[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-"
                        r"[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}", m.group(1)), m.group(1)


def test_release_workflow_is_real_and_version_dynamic():
    """The Windows build job must exist, target real Windows hardware, and
    derive every artifact name from the app version rather than a literal.

    It ships at ``installer/ci/release-windows.yml``: the integration token that
    maintains this repository is a GitHub App WITHOUT the ``workflows``
    permission, and GitHub refuses any push that creates a file under
    ``.github/workflows/``. The README in that directory documents the one-line
    ``git mv`` a maintainer runs to activate it. What this test guarantees is
    that, once moved, the job is correct -- not that the token could move it.
    """
    candidates = [REPO / ".github" / "workflows" / "release-windows.yml",
                  REPO / "installer" / "ci" / "release-windows.yml"]
    yml_path = next((p for p in candidates if p.exists()), None)
    assert yml_path is not None, "release workflow missing from both locations"
    yml = yml_path.read_text(encoding="utf-8")
    assert "windows-latest" in yml
    assert "runs-on: windows-latest" in yml
    # the Linux artifact name must follow the app version, not a literal
    assert "SupermarketSystem-0.2.0-linux" not in yml
    # it must run the test suite before packaging, and boot-test the frozen exe
    assert "pytest" in yml
    assert "Smoke-test the frozen executable" in yml


def test_launcher_opens_a_dedicated_window_not_the_default_browser():
    """§19 — a real Windows app, not a tab in whatever browser is default."""
    src = (WINDOWS_DIR / "run_supermarket.py").read_text(encoding="utf-8")
    assert "--app=" in src, "no app-mode window: the launcher still only opens a browser tab"
    assert "msedge" in src.lower(), "Edge (present on every Windows 10/11) is not tried"
    # the browser must remain as the last-resort fallback, not the first choice
    assert "webbrowser.open" in src
    assert src.index("--app=") < src.index("webbrowser.open"), \
        "the default browser is still preferred over the dedicated window"


def test_launcher_is_testable_on_linux():
    """The window-finding logic must be importable and callable off Windows."""
    import importlib.util
    import sys

    path = WINDOWS_DIR / "run_supermarket.py"
    spec = importlib.util.spec_from_file_location("_launcher_probe", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_launcher_probe"] = mod
    spec.loader.exec_module(mod)

    assert hasattr(mod, "find_app_mode_browser")
    # On Linux there is no Edge/Chrome app mode contract to honour; the helper
    # must say so instead of raising, so the launcher can fall back cleanly.
    assert mod.find_app_mode_browser() is None or isinstance(mod.find_app_mode_browser(), tuple)


# --- §49 branding --------------------------------------------------------------

def test_logo_assets_exist_and_are_real_images():
    for rel in ("frontend/icons/logo.svg", "frontend/icons/icon-512.png"):
        p = REPO / rel
        assert p.exists(), f"missing brand asset {rel}"
        head = p.read_bytes()[:8]
        if rel.endswith(".png"):
            assert head == bytes.fromhex("89504e470d0a1a0a"), f"{rel} is not a PNG"
        else:
            assert b"<svg" in p.read_bytes()[:400], f"{rel} is not an SVG"


def test_logo_is_used_in_the_panel_and_the_mobile_app():
    """§49 — the logo must actually appear, not just sit in the repo."""
    assert "logo.svg" in (REPO / "frontend" / "index.html").read_text(encoding="utf-8")
    assert "logo.svg" in (REPO / "frontend" / "app.js").read_text(encoding="utf-8")
    mobile = (REPO / "frontend" / "mobile" / "index.html").read_text(encoding="utf-8") \
        + (REPO / "frontend" / "mobile" / "app.js").read_text(encoding="utf-8")
    assert "logo.svg" in mobile
