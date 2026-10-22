# -*- coding: utf-8 -*-
"""v3.8 — LLM/economic separation proof (user order §2).

The model may explain, hypothesize and suggest — but no number it writes ever
becomes a persisted economic figure. expected_gain stays 0, the raw claim is
kept in the evidence as an unverified CLAIM, and the drop is audited.
"""
from __future__ import annotations

import json


def test_llm_economic_numbers_never_persisted(client, auth_headers, monkeypatch):
    from app.services import ai_narrator
    fake = {"summary": "s", "suggestions": [
        {"title": "t1", "why": "w", "steps": [], "priority": 1,
         "expected_gain_toman_month": 987654321,
         "action": {"type": "note", "params": {}}},
    ]}
    monkeypatch.setattr(ai_narrator, "_chat",
                        lambda db, messages, max_tokens=400: json.dumps(fake, ensure_ascii=False))
    client.post("/api/insights/ai/preset", headers=auth_headers,
                json={"preset": "openrouter", "api_key": "k"})
    r = client.post("/api/insights/ai/advise", headers=auth_headers)
    assert r.status_code == 200, r.text
    row = client.get(f"/api/insights/{r.json()['ids'][0]}", headers=auth_headers).json()
    assert float(row["expected_gain"]) == 0.0
    assert row["evidence"]["llm_claimed_gain_toman_month"] == 987654321
    assert "dropped" in row["evidence"]["llm_economic_numbers"]
    from app.database import SessionLocal
    from app.models import AuditLog
    from sqlalchemy import func, select
    s = SessionLocal()
    try:
        n = s.execute(select(func.count(AuditLog.id))
                      .where(AuditLog.action == "AI_LLM_NUMBERS_DROPPED")).scalar_one()
        assert n >= 1
    finally:
        s.close()
