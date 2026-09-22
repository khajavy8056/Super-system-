# -*- coding: utf-8 -*-
"""v4.0 — Business Brain reasoning, tools and the acceptance scenarios.

The point of these tests is not that the brain *answers*, but that it answers
**from the shop's own numbers**: the cash plan names the cheque dates and the
expected collections, the same question asked about two different shops produces
two different plans, and a shop with broken data refuses to give a financial
instruction instead of guessing.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest

from app.database import SessionLocal
from app.models import AuditLog, Customer, Invoice, InvoiceItem, Product, ProductBatch, SystemSetting
from app.services import accounting as acc
from app.services import ledger as ledger_svc
from app.services.business_brain import decision_helpers as dh
from app.services.business_brain import (planner, policies, proactive,
                                         situation as situation_svc)
from app.services.business_brain.context import ToolContext
from app.services.business_brain.registry import REGISTRY
from app.services.business_brain.schemas import ToolDenied
from _v40_seed import fresh_store

M = Decimal(1_000_000)
TAG = "v40"


@pytest.fixture(scope="module", autouse=True)
def _schema(tmp_path_factory):
    """A private database for this whole module.

    The brain's job is to read *one* shop and answer from its numbers, so a
    suite that has already filled the shared test database with hundreds of
    other shops would make these assertions meaningless (and slow). This fixture
    gives the module its own file, its own engine and its own session maker, and
    points :data:`app.database.SessionLocal` at it for the duration — so even
    code that opens its own session lands in the same private shop.
    """
    import app.database as database
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    import app.models  # noqa: F401  (registers every table on Base)

    url = f"sqlite:///{tmp_path_factory.mktemp('v40_brain') / 'brain.db'}"
    engine = create_engine(url, future=True, connect_args={"check_same_thread": False})
    database.Base.metadata.create_all(engine)
    maker = sessionmaker(bind=engine, autoflush=False, autocommit=False,
                         expire_on_commit=False, future=True)

    original = database.SessionLocal
    database.SessionLocal = maker
    globals()["SessionLocal"] = maker
    try:
        yield maker
    finally:
        database.SessionLocal = original
        globals()["SessionLocal"] = original
        engine.dispose()


@pytest.fixture(scope="module")
def shop():
    """A shop close to the brief's scenario #1, seeded once for this module."""
    db = SessionLocal()
    acc.ensure_chart(db)
    policies.ensure_defaults(db)
    today = date.today()

    # capital: 180 million in cash
    acc.post(db, kind="OPENING", lines=[acc.Line(acc.A_CASH, debit=Decimal(180) * M),
                                        acc.Line(acc.A_CAPITAL, credit=Decimal(180) * M)],
             description=f"{TAG} capital")
    supplier_a = acc.Supplier(name=f"{TAG} پخش الف", is_active=True)
    supplier_b = acc.Supplier(name=f"{TAG} پخش ب", is_active=True)
    db.add_all([supplier_a, supplier_b])
    db.flush()

    product = Product(name=f"{TAG} برنج ۵ کیلویی", barcode="6260000044010", is_active=True)
    slow_product = Product(name=f"{TAG} روغن آفتابگردان", barcode="6260000044011", is_active=True)
    db.add_all([product, slow_product])
    db.flush()

    for offset, prices in ((10, ("6200000", "7000000")), (5, ("6300000", "7100000"))):
        db.add(ProductBatch(product_id=product.id, batch_number=f"{TAG}-B{offset}", current_qty=40 + offset,
                            quantity_received=60, buy_price=Decimal(prices[0]), sell_price=Decimal(prices[1]),
                            supplier_id=supplier_a.id, status="ACTIVE", received_at=datetime.utcnow(),
                            expiry_date=today + timedelta(days=220)))
    # slow mover that will expire in twelve days
    db.add(ProductBatch(product_id=slow_product.id, batch_number=f"{TAG}-O1", current_qty=12,
                        quantity_received=24, buy_price=Decimal("2500000"), sell_price=Decimal("3200000"),
                        supplier_id=supplier_b.id, status="ACTIVE", received_at=datetime.utcnow(),
                        expiry_date=today + timedelta(days=12)))
    db.flush()

    # fourteen days of sales so velocity/trend have real data
    for day in range(1, 15):
        created = datetime.utcnow() - timedelta(days=day)
        invoice = Invoice(invoice_number=f"{TAG}-S{day}", status="PAID", payment_status="PAID",
                          payment_method="CASH", subtotal=Decimal(3) * M, total_amount=Decimal(3) * M,
                          created_at=created, paid_at=created)
        db.add(invoice)
        db.flush()
        db.add(InvoiceItem(invoice_id=invoice.id, product_id=product.id, qty=2,
                           unit_buy_price=Decimal("6250000"), unit_sell_price=Decimal("7000000"),
                           subtotal=Decimal(14) * M, profit=Decimal("1500000"), created_at=created))

    # two cheques: tomorrow 120M, in three days 80M
    acc.record_cheque(db, direction="ISSUED", number="V40-1001", amount=Decimal(120) * M,
                      due_date=today + timedelta(days=1), bank_name="ملت", party_type="SUPPLIER",
                      party_id=supplier_a.id, party_name=supplier_a.name)
    acc.record_cheque(db, direction="ISSUED", number="V40-1002", amount=Decimal(80) * M,
                      due_date=today + timedelta(days=3), bank_name="ملت", party_type="SUPPLIER",
                      party_id=supplier_b.id, party_name=supplier_b.name)

    # purchases on credit so the payable account is a real liability
    for supplier, amount in ((supplier_a, Decimal(120) * M), (supplier_b, Decimal(80) * M)):
        acc.post(db, kind="PURCHASE", lines=[acc.Line(acc.A_INVENTORY, debit=amount),
                                             acc.Line(acc.A_PAYABLE, credit=amount, party_type="SUPPLIER",
                                                      party_id=supplier.id)],
                 description=f"{TAG} purchase {supplier.name}")

    # receivables: a good payer (with history) and a slow one
    good = Customer(name=f"{TAG} مشتری خوش‌حساب", phone="09120000401", is_active=True, credit_enabled=True)
    slow = Customer(name=f"{TAG} مشتری کند", phone="09120000402", is_active=True, credit_enabled=True)
    db.add_all([good, slow])
    db.flush()
    for customer, amount in ((good, Decimal(90) * M), (slow, Decimal(70) * M)):
        invoice = Invoice(invoice_number=f"{TAG}-C{customer.id}", status="PAID", payment_status="UNPAID",
                          payment_method="ACCOUNT", subtotal=amount, total_amount=amount,
                          customer_id=customer.id, created_at=datetime.utcnow() - timedelta(days=20))
        db.add(invoice)
        db.flush()
        db.add(InvoiceItem(invoice_id=invoice.id, product_id=product.id, qty=1,
                           unit_buy_price=amount * Decimal("0.8"), unit_sell_price=amount,
                           subtotal=amount, profit=amount * Decimal("0.2"),
                           created_at=datetime.utcnow() - timedelta(days=20)))
        ledger_svc.charge_invoice_to_account(db, customer_id=customer.id, invoice=invoice)
        acc.post(db, kind="SALE", lines=[acc.Line(acc.A_RECEIVABLE, debit=amount, party_type="CUSTOMER",
                                                  party_id=customer.id),
                                         acc.Line(acc.A_SALES, credit=amount)],
                 description=f"{TAG} credit sale #{customer.id}")
    for _ in range(3):
        ledger_svc.post_entry(db, customer_id=good.id, entry_type="PAYMENT", amount=Decimal(2) * M,
                              method="CASH")
        acc.post(db, kind="SETTLEMENT", lines=[acc.Line(acc.A_CASH, debit=Decimal(2) * M),
                                               acc.Line(acc.A_RECEIVABLE, credit=Decimal(2) * M,
                                                        party_type="CUSTOMER", party_id=good.id)],
                 description=f"{TAG} settlement")
    db.commit()
    yield {"db": db, "good": good, "slow": slow, "product": product, "slow_product": slow_product,
           "supplier_a": supplier_a, "supplier_b": supplier_b}
    db.close()


def _ask(question: str, **kw) -> dict:
    db = SessionLocal()
    try:
        return planner.respond(db, question=question, user=None, prefer_llm=False, **kw)
    finally:
        db.close()


def _option_ids(answer: dict) -> list[str]:
    return [o["id"] for o in (answer.get("meta") or {}).get("options", [])]


# --------------------------------------------------------------- tool registry
def test_registry_declares_every_required_capability():
    names = set(REGISTRY.names())
    required = {"get_store_profile", "get_cash_position", "get_upcoming_cheques", "get_payables",
                "get_receivables", "get_expected_collections", "get_supplier_profile",
                "get_supplier_history", "get_inventory_summary", "get_expiry_risk", "get_overstock",
                "get_stockout_risk", "get_sales_trend", "get_product_sales", "get_customer_behavior",
                "get_customer_segment", "get_price_history", "run_existing_analyzer",
                "get_active_campaigns", "get_recent_decisions", "get_business_policies",
                "get_open_followups", "search_web", "create_task", "measure_action"}
    missing = required - names
    assert not missing, f"missing tools: {sorted(missing)}"
    assert len(names) == 37


def test_every_tool_declares_its_contract():
    for name in REGISTRY.names():
        spec = REGISTRY.get(name)
        assert spec.description.strip(), name
        assert spec.permissions, f"{name} must declare a permission"
        assert spec.risk_level in ("none", "low", "medium", "high"), name
        if not spec.read_only:
            assert spec.side_effects is True, f"{name} writes but is not declared as writing"
            assert spec.action_class in ("AUTO", "APPROVAL", "HIGH_RISK")


def test_write_tools_are_action_tools_or_brain_owned_and_nothing_else():
    writable = {spec["name"] for spec in REGISTRY.write_tools()}
    assert writable == {"set_policy", "create_task", "create_followup", "record_memory_fact",
                        "measure_action"}
    # price/SMS/campaign execution is proposed to the Action Engine, not called here
    llm_surface = {spec["name"] for spec in REGISTRY.for_llm(ToolContext(db=None, system=True))}
    assert "create_campaign" not in llm_surface
    assert "send_sms" not in llm_surface


def test_tool_without_required_params_returns_an_error_instead_of_raising():
    ctx = ToolContext(db=SessionLocal(), system=True)
    call = REGISTRY.call(ctx, "get_product_snapshot", {})
    assert call.ok is False and "MISSING_PARAMS" in (call.error or "")


def test_financial_tool_is_denied_for_a_cashier_context(shop):
    from app.security import ROLE_PRESETS

    cashier_perms = frozenset(ROLE_PRESETS["Cashier"])
    ctx = ToolContext(db=shop["db"], permissions=cashier_perms)
    with pytest.raises(ToolDenied):
        REGISTRY.call(ctx, "get_cash_position")
    denied = [c for c in ctx.trace if not c.ok and (c.error or "").startswith("TOOL_DENIED")]
    assert denied, "the denied attempt must still be recorded in the trace"


# --------------------------------------------------------------- situation & flags
def test_situation_reports_the_real_cash_pressure(shop):
    situation = situation_svc.build(shop["db"], ToolContext(db=shop["db"], system=True), light=True)
    numbers = situation.cash["numbers"]
    assert numbers["cash_cash"] > 0
    assert (situation.obligations["numbers"])["issued_next_7d"] == pytest.approx(200_000_000, rel=0.001)
    receivables = situation.receivables["numbers"]
    assert receivables["total"] > 0 and receivables["high_confidence"] > 0


# --------------------------------------------------------------- the cash plan
def test_cash_question_produces_a_specific_plan(shop):
    answer = _ask("وضعیت نقدینگی چطوره؟ چه کار کنم؟")
    assert answer["intent"] == "CASH_CRISIS"
    # the colloquial way of asking the same thing must land on the same intent
    colloquial = _ask("فردا چقدر پول لازم دارم؟")
    assert colloquial["intent"] == "CASH_CRISIS", colloquial["intent"]
    text = answer["text"]
    assert "چک" in text and "مطالبات" in text
    assert "V40-1001" in text or "1001" in text, "the plan must name the cheque that is due"
    assert _option_ids(answer)[0] in ("chase_receivable", "negotiate_supplier_terms")
    assert answer["mode"] == "deterministic"
    assert "{" not in text and "<think" not in text, "raw tool JSON / reasoning must never be shown"


def test_cheque_conflict_is_answered_with_the_collection_route(shop):
    answer = _ask("چیکار کنم که فردا چک پاس نشه؟")
    assert answer["intent"] == "CHEQUE_MANAGEMENT"
    top = _option_ids(answer)[0]
    assert top == "chase_receivable", _option_ids(answer)
    option = next(o for o in answer["meta"]["options"] if o["id"] == top)
    assert option["economics"]["gain_toman"] > 0
    assert option["requires_approval"] is True, "sending SMS to customers always needs the owner's consent"


def test_collection_beats_discount_when_customers_owe_money(shop):
    """§22 — money already owed is the cheapest source of cash."""
    answer = _ask("برای پرداخت چک چه کار کنم؟")
    ids = _option_ids(answer)
    assert "chase_receivable" in ids
    if "liquidate_slow_stock" in ids:
        assert ids.index("chase_receivable") < ids.index("liquidate_slow_stock")


def test_same_question_different_shop_gives_a_different_plan(shop):
    """Acceptance #2 — identical answers for different shops are a failure."""
    before = _ask("وضعیت فروشگاه چطوره؟ چه پیشنهادی داری؟")
    db = SessionLocal()
    try:
        # store B: plenty of cash, and the expiring batch is the only problem
        acc.post(db, kind="OPENING", lines=[acc.Line(acc.A_CASH, debit=Decimal(900) * M),
                                            acc.Line(acc.A_CAPITAL, credit=Decimal(900) * M)],
                 description="v40 store B capital")
        for cheque in db.query(acc.Cheque).filter(acc.Cheque.number.like("V40-%")).all():
            cheque.status = "CLEARED"
        db.commit()
    finally:
        db.close()
    after = _ask("وضعیت فروشگاه چطوره؟ چه پیشنهادی داری؟")
    assert _option_ids(before) != _option_ids(after), "the same plan for a different shop is a fail"
    assert _option_ids(after), "store B still has an expiring batch to talk about"


# --------------------------------------------------------------- discipline
def test_grounding_rejects_a_number_no_tool_produced(monkeypatch):
    class LyingProvider:
        name = "fake"
        model_id = "fake-1"
        calls = 0

        def available(self):
            return True

        def chat(self, messages, **kw):
            self.calls += 1
            return ('{"answer": "سود فروشگاه ۹۸۷٬۶۵۴٬۳۲۱ تومان است و همه چیز عالی است."}')

        def tool_call(self, prompt, tools):
            return None

    lie = LyingProvider()
    monkeypatch.setattr("app.services.business_brain.runtime.get_runtime", lambda *a, **k: lie)

    db = SessionLocal()
    try:
        answer = planner.respond(db, question="سود فروشگاه چقدر بوده؟", user=None)
        assert answer["mode"] == "deterministic"
        assert "NUMBER_REJECTED" in answer["warnings"]
        assert "۹۸۷٬۶۵۴٬۳۲۱" not in answer["text"]
        events = db.query(AuditLog).filter(AuditLog.action == "BRAIN_NUMBER_REJECTED").all()
        assert events, "a rejected number must be auditable"
    finally:
        db.close()


def test_unknown_metric_never_becomes_a_number(shop):
    from app.services.business_brain import decisions as decision_svc

    contract = decision_svc.build_measurement(metric="totally_unknown_metric", window_days=14)
    assert contract["known_metric"] is False
    known = decision_svc.build_measurement(metric="avg_basket_size", window_days=14)
    assert known["known_metric"] is True and known["metric"] == "avg_basket_size"


def test_contradiction_between_inventory_and_finance_is_detected():
    from app.services.business_brain.schemas import Evidence, Situation

    evidence = [Evidence(domain="inventory", summary="", flags=["STOCKOUT_RISK"]),
                Evidence(domain="finance", summary="", flags=["CASH_PRESSURE_HIGH"], numbers={})]
    situation = Situation(generated_at=datetime.utcnow(), flags=["STOCKOUT_RISK", "CASH_PRESSURE_HIGH"])
    found = dh.contradictions(evidence, situation)
    assert any(item["kind"] == "BUY_WITHOUT_CASH" for item in found)


def test_option_scoring_is_deterministic(shop):
    first = _ask("وضعیت نقدینگی چطوره؟")
    second = _ask("وضعیت نقدینگی چطوره؟")
    assert _option_ids(first) == _option_ids(second)


def test_empty_store_says_so_instead_of_inventing_a_recommendation():
    """No data must produce an honest «no recommendation», not a template card."""
    db = fresh_store()
    try:
        answer = planner.respond(db, question="چه پیشنهادی برای افزایش فروش داری؟",
                                 user=None, prefer_llm=False)
        assert answer["decision"] is None or answer["decision"]["status"] == "NO_ACTION"
        assert "{" not in answer["text"] and "None" not in answer["text"]
        assert any(word in answer["text"] for word in ("داده", "اطلاعاتی", "ثبت نشده"))
        # the situation still renders, and it says what is missing instead of zeros
        digest = situation_svc.build(db, ToolContext(db=db, system=True), light=True).digest()
        assert "None" not in digest
        # and the proactive engine stays quiet: zero is a valid answer
        out = proactive.evaluate(db, force=True)
        assert out["alerts"] == []
    finally:
        db.close()


def test_three_turn_continuity_keeps_the_subject(shop):
    """Acceptance #5 — «این کالا» → «۵ روز» → «اجراش کن» must stay about the same product."""
    product = shop["slow_product"]
    first = _ask(f"وضعیت {product.name} چطوره؟")
    entities = (first.get("meta") or {}).get("entities") or {}
    assert entities.get("product_id") == product.id or entities.get("product_name") == product.name

    second = _ask("چند روز دیگه باید تخفیف بزنیم؟")
    assert second["text"], "the follow-up must be answered, not dropped"
    assert (second.get("meta") or {}).get("entities", {}).get("product_id") == product.id, \
        "the second turn must remember which product the manager meant"

    third = _ask("اجراش کن")
    third_entities = (third.get("meta") or {}).get("entities") or {}
    assert "{" not in third["text"] and "}" not in third["text"]
    assert third_entities.get("product_id") == product.id or \
        (third.get("meta") or {}).get("entities", {}).get("percent"), \
        "«اجراش کن» must still know what is being executed"
    assert third["followups"] != [] or third["decision"] is None


def test_a_real_campaign_outcome_is_answered_with_real_numbers(shop):
    """Acceptance #6 — «جشنوارهٔ قبلی جواب داد؟» must reach the actual comparison.

    The interesting half is the negative case: when no campaign was ever run the
    brain must say so, because «فروش ۰ تومان در برابر ۰ تومان» looks exactly like a
    measured zero and is a completely different claim.
    """
    from app.models import Campaign

    db = SessionLocal()
    try:
        # nothing was ever run → an honest «no campaign», never a zero comparison
        before = _ask("جشنواره قبلی جواب داد؟")
        assert before["intent"] == "CAMPAIGN_FOLLOWUP"
        assert "کمپینی در فروشگاه ثبت نشده" in before["text"], before["text"]
        assert "در برابر" not in before["text"]

        # a real festival, a week long, ending today
        today = datetime.utcnow()
        campaign = Campaign(name=f"{TAG} جشنواره پاییز", discount_type="PERCENT",
                            discount_value=Decimal(10), status="ENDED",
                            valid_from=today - timedelta(days=7), valid_until=today)
        db.add(campaign)
        db.commit()
    finally:
        db.close()

    after = _ask("جشنواره قبلی جواب داد؟")
    text = after["text"]
    assert "کمپینی در فروشگاه ثبت نشده" not in text, "a campaign exists; the answer must use it"
    assert "بازهٔ اجرا" in text and "بازهٔ قبل" in text, "the real before/during comparison is required"
    # …and the numbers in it come from the invoices, not from a template
    assert "۱۸٬۰۰۰٬۰۰۰" in text and "۲۱٬۰۰۰٬۰۰۰" in text, text
    assert "-۱۴.۳" in text or "۱۴.۳" in text, text


def test_colloquial_expiry_question_reaches_the_expiry_answer(shop):
    """«کدوم کالا داره خراب می‌شه؟» is how an owner asks about expiry.

    The intent patterns used to know only the formal words («انقضا», «منقضی»), so the
    most natural question in the shop got a generic store summary back.
    """
    for question in ("کدوم کالا داره خراب می‌شه؟", "چه کالایی داره فاسد می‌شه؟", "تاریخ انقضای کدام کالا نزدیک است؟"):
        answer = _ask(question)
        assert answer["intent"] == "EXPIRY", (question, answer["intent"])
        assert "انقضا" in answer["text"], answer["text"]
        assert "{" not in answer["text"]
