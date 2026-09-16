# -*- coding: utf-8 -*-
"""v3.6.1 — one broken analyzer must cost one card, never the whole intelligence screen.

The report was "sometimes it crashes". Three separate ways the engine could take the entire
``هوش فروشگاه`` page down with a 500, all found by reading rather than by waiting for a report:

1. ``run()`` wrapped only ``fn(ctx)`` in its try/except. The upsert loop that *writes* the
   drafts sat outside it, so a failure while persisting escaped.
2. The upsert used ``scalar_one_or_none()`` on ``(kind, dedupe_key)``, but ``dedupe_key`` is
   indexed, not unique — two live rows with one key raised ``MultipleResultsFound``.
3. ``measure_all()`` ran after the commit with no guard, so a measurement bug discarded a run
   that had already succeeded.

Each is pinned below by making it happen on purpose.
"""
import json

import pytest

from app.services import insights


@pytest.fixture
def run_ok(client, auth_headers):
    def _run():
        r = client.post("/api/insights/run", json={}, headers=auth_headers)
        assert r.status_code == 200, f"the engine returned {r.status_code}: {r.text[:400]}"
        return r.json()
    return _run


def _spy_all(monkeypatch):
    """Wrap every analyzer so the test can prove which ones actually got attempted.

    The shared test database usually has no sales in it, so "cards were created" is not a usable
    signal — an empty store legitimately creates nothing. "every other analyzer still ran" is.
    """
    attempted = []
    for k, fn in list(insights.ANALYZERS.items()):
        def wrapped(ctx, _k=k, _fn=fn):
            attempted.append(_k)
            return _fn(ctx)
        monkeypatch.setitem(insights.ANALYZERS, k, wrapped)
    return attempted


def _healthy_kinds(client, auth_headers):
    rows = client.get("/api/insights", params={"status": "ALL", "limit": 500},
                      headers=auth_headers).json()
    return {r["kind"] for r in rows}


def test_analyzer_that_raises_while_computing_does_not_stop_the_run(client, auth_headers, run_ok, monkeypatch):
    attempted = _spy_all(monkeypatch)
    total = len(insights.ANALYZERS)
    before = _healthy_kinds(client, auth_headers)

    def boom(ctx):
        raise RuntimeError("deliberate analyzer failure")

    monkeypatch.setitem(insights.ANALYZERS, "VELOCITY", boom)
    res = run_ok()
    assert "VELOCITY" in res["errors"], "the failure must be reported, not hidden"
    # every analyzer except the one that was made to explode must still have been attempted
    assert set(attempted) == set(insights.ANALYZERS) - {"VELOCITY"}, (
        f"the broken analyzer stopped the run early; never attempted: "
        f"{set(insights.ANALYZERS) - {'VELOCITY'} - set(attempted)}")
    after = _healthy_kinds(client, auth_headers)
    assert after <= before | set(insights.ANALYZERS), "the run produced cards for unknown kinds"
    assert before <= after or not before, "the run wiped insights that were already there"


def test_analyzer_that_fails_while_persisting_does_not_stop_the_run(client, auth_headers, run_ok, monkeypatch):
    """The case the old try/except could not catch: the draft is fine, writing it is not."""
    def bad_draft(ctx):
        return [insights.Draft(
            kind="VELOCITY", dedupe_key="test:unpersistable", title="t", body="b", priority=1,
            evidence={}, actions=[], expected_gain=0.0,
            # a set is not JSON-serialisable, so json.dumps(metric) raises inside the upsert
            metric={"metric": "avg_basket_size", "bad": {1, 2}})]

    attempted = _spy_all(monkeypatch)
    total = len(insights.ANALYZERS)
    monkeypatch.setitem(insights.ANALYZERS, "VELOCITY", bad_draft)
    res = run_ok()
    assert "VELOCITY" in res["errors"], f"the persistence failure was swallowed: {res['errors']}"
    assert set(attempted) == set(insights.ANALYZERS) - {"VELOCITY"}, (
        f"a row that could not be written stopped the run early; never attempted: "
        f"{set(insights.ANALYZERS) - {'VELOCITY'} - set(attempted)}")


def test_duplicate_dedupe_keys_do_not_take_the_page_down(client, auth_headers, run_ok, monkeypatch):
    """The actual 500 that was reported: two live rows sharing one dedupe_key.

    The duplicate only bites when an analyzer emits that same key, so the analyzer is made to do
    exactly that — otherwise the lookup never happens and the test would pass for nothing.
    """
    from datetime import datetime

    from app.database import SessionLocal
    from app.models import Insight
    from sqlalchemy import select

    with SessionLocal() as db:
        for i in range(2):
            db.add(Insight(kind="VELOCITY", dedupe_key="dup:probe", title=f"twin {i}", body="b",
                           priority=1, status="NEW", evidence="{}", actions="[]", metric="{}",
                           expected_gain=0, last_seen_at=datetime.utcnow()))
        db.commit()

    monkeypatch.setitem(insights.ANALYZERS, "VELOCITY", lambda ctx: [insights.Draft(
        kind="VELOCITY", dedupe_key="dup:probe", title="t", body="b", priority=1,
        evidence={}, actions=[], expected_gain=0.0, metric={"metric": "avg_basket_size"})])

    # Before the fix this raised MultipleResultsFound inside run() and returned 500.
    run_ok()

    with SessionLocal() as db:
        twins = db.execute(select(Insight).where(Insight.dedupe_key == "dup:probe",
                                                 Insight.status.in_(["NEW", "SNOOZED", "ACCEPTED"]))).scalars().all()
    assert len(twins) <= 1, (
        f"{len(twins)} live rows still share one dedupe_key — the feed shows the same card twice "
        "and the next run can trip over them again")


def test_a_broken_measurement_does_not_discard_a_successful_run(client, auth_headers, monkeypatch):
    from app.services import insights as ins

    def boom(db):
        raise RuntimeError("measurement exploded")

    monkeypatch.setattr(ins, "measure_all", boom)
    r = client.post("/api/insights/run", json={}, headers=auth_headers)
    assert r.status_code == 200, f"a measurement bug must not lose the run: {r.status_code} {r.text[:300]}"
    assert r.json()["created"] + r.json()["refreshed"] >= 0


def test_android_group_mirror_matches_the_backend():
    """The app hard-codes a copy of insights.GROUPS to pick card icons.

    A kind missing from that copy does not crash — it silently gets the wrong group icon, which
    is exactly the sort of drift nobody notices. Cheap to check, so check it.
    """
    import pathlib
    import re

    java = (pathlib.Path(__file__).resolve().parents[2] / "mobile-android" / "app" / "src" /
            "main" / "java" / "ir" / "khajavy" / "supermarket" / "InsightScreens.java").read_text(encoding="utf-8")
    block = java[java.index("static final String[][] GROUPS"):java.index("static String group(")]
    mirror = {}
    for g, kinds in re.findall(r'\{"(\w+)", "[^"]*", "([^"]+)"\}', block):
        mirror[g] = set(kinds.split(","))
    assert mirror, "could not read the Java GROUPS mirror — the guard would be vacuous"

    backend = {g: set(ks) for g, (_, ks) in insights.GROUPS.items()}
    for g, kinds in backend.items():
        assert g in mirror, f"group {g!r} exists in the backend but not in the app"
        missing = kinds - mirror[g]
        assert not missing, (
            f"the app's {g} group is missing {sorted(missing)} — those cards get the wrong icon. "
            "Keep InsightScreens.GROUPS in step with insights_pro.GROUPS.")


def test_model_guide_documents_every_analyzer():
    """docs/model-guide.fa.md is a user-facing deliverable, so it must not fall behind the code.

    A new analyzer that never reaches the guide is invisible to the shop owner, which defeats the
    point of writing it. Cheap to enforce, so enforce it.
    """
    import pathlib

    guide = (pathlib.Path(__file__).resolve().parents[2] / "docs" / "model-guide.fa.md").read_text(encoding="utf-8")
    undocumented = [k for k in insights.ANALYZERS if f"`{k}`" not in guide]
    assert not undocumented, (
        f"{len(undocumented)} analyzer(s) are missing from docs/model-guide.fa.md: {undocumented}")
    # and the headline claim in the header must match reality, not a stale number
    assert f"**{len(insights.ANALYZERS)} روش تحلیل**" in guide, (
        "the guide's analyzer count no longer matches insights.ANALYZERS")
