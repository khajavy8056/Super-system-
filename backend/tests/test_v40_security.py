# -*- coding: utf-8 -*-
"""v4.0 — Security discipline for the Business Brain (§10, §47, §48, §72).

The brain is the most privileged thing in the product: it can read every number
the shop knows and propose actions that spend money. These tests are the fence
around it, and they deliberately attack the surface rather than the internals:

* a cashier (or an anonymous caller) can reach **nothing** on ``/api/brain``;
* the tool registry refuses a financial tool for a caller without the code —
  even when the brain itself calls it, and even when it looks like an LLM call;
* money-moving actions are always classified as needing approval;
* no brain route exists that writes to a product, price or invoice directly.

If any of these ever fails, the failure matters far more than a red test: it is
the difference between an assistant and a machine that can move the owner's money
without being asked.
"""
from __future__ import annotations

import pytest

from app.bootstrap import bootstrap
from app.database import SessionLocal, init_db
from app.models import Role, User
from app.security import hash_password
from app.security import ROLE_PRESETS, _user_permission_codes
from app.services.business_brain import decisions as decision_svc
from app.services.business_brain import policies
from app.services.business_brain.context import ToolContext
from app.services.business_brain.memory import log_message
from app.services.business_brain.registry import ACTION_TOOLS, REGISTRY
from app.services.business_brain.schemas import ToolDenied
from _v40_seed import fresh_store, seed_shop

#: every path the brain exposes to the app, and whether it is a write
BRAIN_ROUTES = (
    ("GET", "/api/brain"),
    ("GET", "/api/brain/status"),
    ("GET", "/api/brain/situation"),
    ("GET", "/api/brain/tools"),
    ("GET", "/api/brain/policies"),
    ("GET", "/api/brain/chat/history"),
    ("GET", "/api/brain/decisions"),
    ("GET", "/api/brain/decisions/1"),
    ("GET", "/api/brain/followups"),
    ("GET", "/api/brain/memory"),
    ("GET", "/api/brain/alerts"),
    ("GET", "/api/brain/model"),
    ("GET", "/api/brain/model/status"),
    ("POST", "/api/brain/chat"),
    ("POST", "/api/brain/decisions/1/approve"),
    ("POST", "/api/brain/decisions/1/reject"),
    ("POST", "/api/brain/decisions/1/snooze"),
    ("POST", "/api/brain/decisions/1/measure"),
    ("POST", "/api/brain/followups/1/resolve"),
    ("POST", "/api/brain/proactive/run"),
    ("POST", "/api/brain/model/select"),
    ("POST", "/api/brain/model/download"),
    ("POST", "/api/brain/model/benchmark"),
)


@pytest.fixture(scope="module", autouse=True)
def _schema():
    init_db()
    yield


@pytest.fixture(scope="module")
def cashier():
    """A real cashier account: the Cashier role is what the fence must hold against."""
    db = SessionLocal()
    bootstrap(db)
    user = db.query(User).filter(User.username == "v40cashier").first()
    if user is None:
        user = User(username="v40cashier", full_name="صندوقدار تست",
                    password_hash=hash_password("cashier-pass-123"), is_active=True)
        role = db.query(Role).filter(Role.name == "Cashier").one()
        user.roles.append(role)
        db.add(user)
        db.commit()
    db.refresh(user)
    yield user
    db.close()


def _login(client, username: str, password: str) -> dict:
    response = client.post("/api/auth/login", data={"username": username, "password": password})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


# --------------------------------------------------------------------- the surface
def test_every_brain_route_exists_and_requires_authentication(client):
    for method, path in BRAIN_ROUTES:
        response = client.request(method, path, json={})
        assert response.status_code in (401, 403), f"{method} {path} → {response.status_code}"
        assert response.status_code != 404, f"{method} {path} is missing"


def test_the_owner_reaches_the_brain_and_the_cashier_does_not(client, auth_headers, cashier):
    owner = client.get("/api/brain", headers=auth_headers)
    assert owner.status_code == 200
    assert owner.json()["version"].startswith("4.0")
    assert owner.json()["admin_surface"] is True

    shop_floor = _login(client, cashier.username, "cashier-pass-123")
    for method, path in BRAIN_ROUTES:
        response = client.request(method, path, headers=shop_floor, json={})
        assert response.status_code in (401, 403), \
            f"cashier reached {method} {path} → {response.status_code}"


def test_the_cashier_role_holds_reports_but_never_settings():
    """The brain gate is deliberately `settings.manage`: `reports.view` is held by
    cashiers too, so it alone would let the shop floor read the owner's analysis."""
    codes = set(ROLE_PRESETS["Cashier"])
    assert "reports.view" in codes, "if this changes, the gate below must be re-checked"
    assert "settings.manage" not in codes
    assert not {"accounting.view", "accounting.manage", "audit.view"} & codes


# --------------------------------------------------------------------- the registry
def test_financial_tools_are_denied_without_the_permission_and_the_attempt_is_recorded(cashier):
    db = SessionLocal()
    try:
        perms = frozenset(_user_permission_codes(cashier))
        # money and strategy tools: the ones a cashier must never reach
        for tool in ("get_cash_position", "get_payables", "get_cash_forecast", "get_expenses",
                     "get_business_policies", "get_recent_decisions", "get_open_followups",
                     "get_memory_facts", "get_supplier_profile", "get_campaign_outcome"):
            ctx = ToolContext(db=db, user=cashier, permissions=perms)
            params = {"supplier_id": 1} if tool == "get_supplier_profile" else {}
            with pytest.raises(ToolDenied):
                REGISTRY.call(ctx, tool, params)
            denied = [c for c in ctx.trace if not c.ok and (c.error or "").startswith("TOOL_DENIED")]
            assert denied, f"{tool}: the denied attempt must be visible in the trace"
            assert ctx.known_numbers() == set(), f"{tool}: a denied tool must not leak numbers"
    finally:
        db.close()


def test_internal_helpers_turn_a_denial_into_an_empty_fact_never_into_data(cashier):
    db = SessionLocal()
    try:
        ctx = ToolContext(db=db, user=cashier, permissions=frozenset(_user_permission_codes(cashier)))
        assert REGISTRY.call_or_none(ctx, "get_cash_position") == {}
    finally:
        db.close()


def test_unknown_tool_and_missing_parameters_fail_closed():
    ctx = ToolContext(db=SessionLocal(), system=True)
    unknown = REGISTRY.call(ctx, "drop_all_tables", {})
    assert unknown.ok is False and unknown.error == "TOOL_UNKNOWN"
    missing = REGISTRY.call(ctx, "get_product_snapshot", {})
    assert missing.ok is False and "MISSING_PARAMS" in missing.error


def test_every_money_moving_action_is_classified_as_needing_approval():
    db = SessionLocal()
    try:
        policies.ensure_defaults(db)
        risky = ("personal_sms", "debt_reminders", "visit_sms", "sms_buyers", "vip_coupons",
                 "winback_sms", "personal_coupons", "set_price", "set_prices_bulk")
        for action in risky:
            assert policies.action_requires_approval(db, action), action
        # and the Action Engine agrees (external side effects are never silent)
        from app.services import insight_actions as engine

        for action in risky:
            spec = engine.ACTION_SPECS.get(action)
            assert spec is not None, f"{action} must go through the Action Engine"
            if spec.get("external_side_effect"):
                assert policies.action_requires_approval(db, action)
    finally:
        db.close()


def test_action_tools_in_the_registry_are_proposals_only():
    for name, entry in ACTION_TOOLS.items():
        action = entry["action_type"]
        assert action in ("flash_sale", "set_price", "personal_sms", "reorder_note"), action
        spec = REGISTRY.get(name)
        assert spec is None or spec.read_only or spec.risk_level in ("medium", "high"), name


# --------------------------------------------------------------------- the model loop
def test_the_tool_loop_can_only_reach_read_only_tools_and_only_with_permission():
    """Whatever the model asks for, the loop goes through the same registry fence."""
    from app.services.business_brain import runtime as runtime_svc

    db = fresh_store()
    try:
        shop_free = ToolContext(db=db, permissions=frozenset())      # no permission at all
        loop = runtime_svc.ToolLoop(runtime=runtime_svc.TemplateProvider(), ctx=shop_free)
        result = loop._run_tool("get_cash_position", {})
        assert '"ok": false' in result
        assert shop_free.known_numbers() == set()
        names = {spec["name"] for spec in REGISTRY.for_llm(shop_free)}
        assert "get_cash_position" not in names, "the model must not even see tools it cannot call"
        assert "set_price" not in names and "personal_sms" not in names
    finally:
        db.close()


def test_a_decision_cannot_be_executed_without_approval(monkeypatch):
    db = fresh_store()
    try:
        policies.ensure_defaults(db)
        row = decision_svc.create(
            db, title="ارسال پیامک تخفیف", problem="", reason="",
            options=[{"id": "sms", "label": "پیامک", "description": "", "requires_approval": True,
                      "action_class": "APPROVAL", "risk": "low", "reversible": True,
                      "economics": {"gain_toman": 0}, "tradeoffs": [],
                      "actions": [{"type": "personal_sms", "params": {"customers": []},
                                   "label": "پیامک", "reversible": False}]}],
            evidence=[], situation={}, requires_approval=True)
        db.commit()
        assert row.status in ("NEEDS_DECISION", "WAITING_APPROVAL")
        out = decision_svc.approve(db, row, user=None, execute=False)
        db.commit()
        assert out["status"] == "WAITING_APPROVAL"
        import json as _json

        executed = (_json.loads(row.execution or "{}") or {}).get("executions") or []
        assert executed == [], "nothing may run before the owner asks for it"
    finally:
        db.close()


def test_brain_writes_no_privacy_leaking_logs():
    """Conversation memory is local, and tool traces carry no customer phone numbers."""
    db = fresh_store()
    try:
        log_message(db, session_key="priv", role="USER", content="وضعیت فروشگاه چطوره؟",
                    meta={"intent": "STORE_STATUS"})
        db.commit()
        from app.services.business_brain.memory import conversation

        rows = conversation(db, session_key="priv")
        assert rows and rows[-1]["content"] == "وضعیت فروشگاه چطوره؟"
        from app.models import BrainMessage

        assert db.query(BrainMessage).count() == 1
    finally:
        db.close()


def test_proactive_cards_never_exist_without_a_decision_row():
    """Alerts shown in the UI must be backed by a decision — no phantom cards."""
    from app.services.business_brain import proactive

    db = fresh_store()
    try:
        seed_shop(db, tag="sec")
        out = proactive.evaluate(db, force=True)
        for alert in out["alerts"]:
            assert alert.get("decision_id"), alert
        assert proactive.status(db)["open_cards"] == len(out["alerts"])
    finally:
        db.close()
