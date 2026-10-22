# -*- coding: utf-8 -*-
"""v3.8 — Data Quality gating proof (user order §1).

* CRITICAL corruption (negative stock, duplicate invoice numbers) ⇒ the
  intelligence run returns BLOCKED and writes nothing.
* Lesser findings degrade confidence and ride along in the evidence.
* The verdict transition is audited exactly once (no per-run spam).
* GET /api/insights/data-quality exposes the live report.
* Invalid economic numbers never reach the DB (draft validation gate).
"""
from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal

from app.database import SessionLocal
from app.models import AuditLog, Product, ProductBatch
from app.services import data_quality as dq
from app.services import insights as svc
from sqlalchemy import func, select


_bc = 0


def _neg_stock_batch():
    global _bc
    _bc += 1
    s = SessionLocal()
    try:
        p = Product(barcode=f"77000009998{_bc:02d}", name="V38 DQ prod")
        s.add(p)
        s.flush()
        s.add(ProductBatch(product_id=p.id, batch_number="V38NEG",
                           quantity_received=Decimal(5), current_qty=Decimal(-2),
                           buy_price=Decimal(100), sell_price=Decimal(200),
                           consumer_price=Decimal(200),
                           received_at=datetime.utcnow(), status="ACTIVE"))
        s.commit()
        return p.id
    finally:
        s.close()


def _fix_stock(pid):
    s = SessionLocal()
    try:
        b = s.execute(select(ProductBatch).where(ProductBatch.product_id == pid)).scalar_one()
        b.current_qty = Decimal(3)
        s.commit()
    finally:
        s.close()


def test_critical_blocks_and_lesser_degrades(client, auth_headers):
    pid = _neg_stock_batch()
    try:
        s = SessionLocal()
        try:
            rep = dq.run_all(s)
            assert rep["verdict"] == "BLOCKED" and rep["blocks_intelligence"] is True
            assert "negative_stock" in [c["id"] for c in rep["checks"]]
        finally:
            s.close()
        r = client.post("/api/insights/run", headers=auth_headers)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "BLOCKED"
        assert body["created"] == 0 and body["refreshed"] == 0
    finally:
        _fix_stock(pid)


def test_dq_verdict_change_audited_once(client, auth_headers):
    from app.models import SystemSetting
    s = SessionLocal()
    try:  # self-contained: forget any verdict left by earlier tests
        row = s.execute(select(SystemSetting).where(SystemSetting.key == "dq.last_verdict")).scalar_one_or_none()
        if row is not None:
            s.delete(row)
            s.commit()
    finally:
        s.close()
    s = SessionLocal()
    try:
        before = s.execute(select(func.count(AuditLog.id))
                           .where(AuditLog.action == "DQ_VERDICT_CHANGED")).scalar_one()
    finally:
        s.close()
    pid = _neg_stock_batch()
    try:
        client.post("/api/insights/run", headers=auth_headers)  # → BLOCKED (audit)
        client.post("/api/insights/run", headers=auth_headers)  # still BLOCKED (silent)
    finally:
        _fix_stock(pid)
    client.post("/api/insights/run", headers=auth_headers)  # → DEGRADED/OK (audit)
    s = SessionLocal()
    try:
        after = s.execute(select(func.count(AuditLog.id))
                          .where(AuditLog.action == "DQ_VERDICT_CHANGED")).scalar_one()
    finally:
        s.close()
    assert after - before == 2, "exactly one audit row per verdict transition"


def test_data_quality_api(client, auth_headers):
    r = client.get("/api/insights/data-quality", headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["verdict"] in ("OK", "DEGRADED", "BLOCKED")
    assert set(body["summary"]) == {"CRITICAL", "HIGH", "MEDIUM", "LOW"}
    assert isinstance(body["checks"], list)


def test_evidence_carries_dq_and_downgraded_confidence(client, auth_headers):
    """A degraded run stamps every card with its dq report (dead stock ⇒ card)."""
    from datetime import timedelta
    s = SessionLocal()
    try:  # deterministic trigger: 60-day-old stock worth 200k, zero sales
        p = Product(barcode="7700000999777", name="V38 DQ dead")
        s.add(p)
        s.flush()
        s.add(ProductBatch(product_id=p.id, batch_number="V38DEAD",
                           quantity_received=Decimal(10), current_qty=Decimal(10),
                           buy_price=Decimal(20000), sell_price=Decimal(30000),
                           consumer_price=Decimal(30000),
                           received_at=datetime.utcnow() - timedelta(days=60),
                           status="ACTIVE"))
        s.commit()
    finally:
        s.close()
    r = client.post("/api/insights/run", headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "DEGRADED", body  # LOW findings exist, nothing blocks
    assert body["created"] + body["refreshed"] >= 1
    s = SessionLocal()
    try:
        from app.models import Insight
        rows = s.execute(select(Insight).where(Insight.status == "NEW",
                                                Insight.kind == "DEAD_STOCK")
                         .order_by(Insight.id.desc())).scalars().all()
        assert rows, "a degraded run must still produce advice"
        ev = json.loads(rows[0].evidence or "{}")
        assert "dq" in ev, "cards must disclose the dq findings behind them"
        assert ev["forecast"].get("dq_degraded") is True
        assert ev["forecast"]["confidence"] in ("low", "medium", "n/a")
    finally:
        s.close()


def test_safe_gain_gate():
    assert svc._safe_gain(None)[0] == 0.0 and svc._safe_gain(None)[1]
    assert svc._safe_gain(float("nan"))[1] and svc._safe_gain(float("inf"))[1]
    assert svc._safe_gain("abc")[0] == 0.0
    assert svc._safe_gain(True)[1]  # bools are not money
    v, issue = svc._safe_gain("123.5")
    assert (v, issue) == (123.5, None)
