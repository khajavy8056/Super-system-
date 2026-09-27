# -*- coding: utf-8 -*-
"""Round 15 (v4.7.0) — the owner's three rules for پای صندوق + the one-year simulator.

1. POS suggestions (پیشنهاد پای صندوق) must be HONEST:
   - never an item without stock («موجود نداریم نباید پیشنهاد بده»);
   - never an item whose remaining batches are past expiry — the named bug was
     exactly a nudge advertising a dead item;
   - items whose expiry is APPROACHING («نزدیک شدیم نه عبور کرده») come FIRST,
     as an extra selling criterion.
2. The suggestions must be reachable from BOTH POS surfaces (the API gate the
   Android app calls, manual rules included in the honesty contract).
3. The one-year simulator must add cashier shifts (cash sessions) and several
   stocktakes to the year, and ship as a Colab notebook in tools/.
"""
import gzip
import importlib.util
import json
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select

from app.database import SessionLocal
from app.models import Product, ProductBatch, SystemSetting
from app.models.insights import Insight
from app.services import insights

ROOT = Path(__file__).resolve().parents[2]


# --------------------------------------------------------------------------- helpers
def _accept_basket_rules(db, rules):
    row = Insight(kind="BASKET_NUDGE", dedupe_key=f"v47-{datetime.utcnow().timestamp()}", title="t", body="b",
                  status="ACCEPTED", accepted_at=datetime(2099, 1, 1),
                  evidence=json.dumps({"rules": rules}))
    db.add(row)
    db.flush()
    return row


def _make_product(client, auth_headers, name, qty=10, expiry_days=None):
    import uuid
    r = client.post("/api/products", headers=auth_headers,
                    json={"barcode": f"V47{uuid.uuid4().hex[:10]}", "name": name})
    assert r.status_code == 201, r.text
    pid = r.json()["id"]
    body = {"product_id": pid, "quantity_received": qty, "buy_price": 1000, "sell_price": 1500}
    if expiry_days is not None:
        body["expiry_date"] = (date.today() + timedelta(days=expiry_days)).isoformat()
    rr = client.post("/api/batches/receive", headers=auth_headers, json=body)
    assert rr.status_code == 201, rr.text
    return pid


# --------------------------------------------------------------------------- rule 1: honesty
def test_named_bug_expired_batch_is_never_suggested_even_with_block_sale_off(client, auth_headers, milk, two_batches):
    """The exact bug the owner reported: an expired item was suggested.

    ``pos.sellable_batches`` only excludes expired batches when the store's
    ``expiry.block_sale`` policy is ON; the nudge must be honest regardless of
    that policy, so the filter lives in the suggestion itself.
    """
    with SessionLocal() as db:
        product = db.get(Product, milk["id"])
        for b in db.scalars(select(ProductBatch).where(ProductBatch.product_id == product.id)):
            b.expiry_date = date.today() - timedelta(days=2)   # عبور کرده — باید سکوت کند
        setting = db.execute(select(SystemSetting).where(SystemSetting.key == "expiry.block_sale")).scalar_one_or_none()
        if setting:
            setting.value = "false"
        else:
            db.add(SystemSetting(key="expiry.block_sale", value="false"))
        db.flush()
        _accept_basket_rules(db, [{"if": -100, "then": product.id, "if_name": "شیر",
                                   "then_name": product.name, "confidence": 0.9, "lift": 2.5}])
        assert insights.nudges(db, [-100]) == []
        db.rollback()


def test_out_of_stock_is_never_suggested(client, auth_headers):
    with SessionLocal() as db:
        pid = _make_product(client, auth_headers, "قفسه خالی تست")
        for b in db.scalars(select(ProductBatch).where(ProductBatch.product_id == pid)):
            b.current_qty = 0
        db.flush()
        _accept_basket_rules(db, [{"if": -100, "then": pid, "if_name": "خرید", "then_name": "خالی", "confidence": 0.9}])
        assert insights.nudges(db, [-100]) == []
        db.rollback()


def test_near_expiry_is_ranked_first_and_explains_itself(client, auth_headers):
    with SessionLocal() as db:
        near = _make_product(client, auth_headers, "ماست نزدیک انقضا", qty=8, expiry_days=10)
        fresh = _make_product(client, auth_headers, "تن ماهی تازه", qty=8, expiry_days=300)
        # `fresh` has the STRONGER rule — near-expiry must still come first.
        _accept_basket_rules(db, [
            {"if": -100, "then": fresh, "if_name": "نان", "then_name": "تازه", "confidence": 0.99, "lift": 3.0},
            {"if": -100, "then": near, "if_name": "نان", "then_name": "نزدیک", "confidence": 0.4, "lift": 1.9},
        ])
        out = insights.nudges(db, [-100])
        assert len(out) == 2
        assert out[0]["product_id"] == near, "near-expiry must outrank the stronger fresh rule"
        assert out[0]["purpose"] == "sell_before_expiry"
        assert out[0]["days_left"] == 10
        assert "تاریخ" in out[0]["reason"] and "۱۰" not in out[0]["reason"]  # reason present, latin digits fine
        assert out[1]["product_id"] == fresh and out[1]["purpose"] == "sell_now"
        db.rollback()


def test_no_expiry_dates_at_all_does_not_crash(client, auth_headers):
    """A shelf staple with no expiry dates anywhere — min() over an empty set
    used to raise ValueError and take the whole POS nudge endpoint down."""
    with SessionLocal() as db:
        pid = _make_product(client, auth_headers, "کالای بدون تاریخ")   # no expiry_date
        _accept_basket_rules(db, [{"if": -100, "then": pid, "if_name": "سبد", "then_name": "بی‌تاریخ", "confidence": 0.9}])
        out = insights.nudges(db, [-100])
        assert out and out[0]["product_id"] == pid
        assert out[0]["days_left"] is None and out[0]["near_expiry"] is False
        db.rollback()


def test_nudges_need_an_accepted_insight(client, auth_headers):
    with SessionLocal() as db:
        pid = _make_product(client, auth_headers, "بدون بینش")
        _accept_basket_rules(db, [{"if": -100, "then": pid, "if_name": "a", "then_name": "b", "confidence": 0.9}])
        db.flush()
        db.execute(select(Insight).where(Insight.kind == "BASKET_NUDGE"))  # exists — but check the empty case below
        # the no-accepted-insight case: delete every accepted row for this moment
        from sqlalchemy import delete
        db.execute(delete(Insight).where(Insight.kind == "BASKET_NUDGE"))
        db.flush()
        assert insights.nudges(db, [-100]) == []
        db.rollback()


def _set_setting(db, key, value):
    row = db.execute(select(SystemSetting).where(SystemSetting.key == key)).scalar_one_or_none()
    if row:
        row.value = value
    else:
        db.add(SystemSetting(key=key, value=value))


def test_manual_rules_are_honest_too(client, auth_headers):
    """The /insights/nudges router merges `insights.manual_rules` AFTER the
    engine's rules — those must pass the same honesty check (out-of-stock and
    expired items are filtered there too)."""
    with SessionLocal() as db:
        pid = _make_product(client, auth_headers, "قانون دستی منقضی")
        for b in db.scalars(select(ProductBatch).where(ProductBatch.product_id == pid)):
            b.expiry_date = date.today() - timedelta(days=1)
        db.flush()
        _set_setting(db, "insights.pos_nudges", "true")
        _set_setting(db, "insights.manual_rules", json.dumps(
            [{"if": -100, "then": pid, "if_name": "نان", "then_name": "منقضی", "confidence": 0.9}]))
        db.commit()
    r = client.post("/api/insights/nudges", headers=auth_headers, json={"product_ids": [-100]})
    assert r.status_code == 200, r.text
    assert r.json() == [], "an expired item must not slip in through manual rules"
    # the honest twin: a manual rule for an IN-STOCK item DOES come through
    with SessionLocal() as db:
        pid2 = _make_product(client, auth_headers, "قانون دستی سالم")
        _set_setting(db, "insights.manual_rules", json.dumps(
            [{"if": -100, "then": pid2, "if_name": "نان", "then_name": "سالم", "confidence": 0.9}]))
        db.commit()
    r2 = client.post("/api/insights/nudges", headers=auth_headers, json={"product_ids": [-100]})
    assert r2.status_code == 200, r2.text
    assert [x["product_id"] for x in r2.json()] == [pid2]
    with SessionLocal() as db:
        for k in ("insights.pos_nudges", "insights.manual_rules"):
            db.query(SystemSetting).filter(SystemSetting.key == k).delete()
        db.commit()


def test_pos_nudges_gate_off_by_default(client, auth_headers):
    with SessionLocal() as db:
        db.query(SystemSetting).filter(SystemSetting.key == "insights.pos_nudges").delete()
        db.commit()
    r = client.post("/api/insights/nudges", headers=auth_headers, json={"product_ids": [-100]})
    assert r.status_code == 200
    assert r.json() == []


# --------------------------------------------------------------------------- rule 3: the year simulator
def test_demo_year_now_contains_shifts_and_stocktakes(tmp_path):
    """The Colab one-year simulator must simulate cashier SHIFTS (cash sessions
    with opening float, counted cash, small human difference) and several
    STOCKTAKES through the real complete→approve service path. A short 8-day
    window (≥ a full week, so a Thursday close always falls inside it) proves
    both paths; the 365-day Colab run is the same code with more days."""
    from app.services import demo_store
    out = tmp_path / "v47_sim.db.gz"
    summary = demo_store.generate_backup_file(out, days=8, seed=11, invoices_per_day=10,
                                              compress=True, full_catalog=False)
    assert out.exists() and out.stat().st_size > 1000
    assert summary.get("cash_sessions", 0) >= 1, "no cashier shift was simulated"
    assert summary.get("stocktakes", 0) >= 1, "no stocktake was simulated"
    import sqlite3
    raw = gzip.decompress(out.read_bytes())
    con = sqlite3.connect(f"file:{len(raw)}memory?mode=memory&cache=shared".replace(f"file:{len(raw)}memory", "file::memory:"), uri=True)
    try:
        con.deserialize(raw)
        sessions = con.execute("SELECT COUNT(*), SUM(status='CLOSED'), SUM(difference IS NOT NULL) FROM acc_cash_sessions").fetchone()
        assert sessions[0] >= 1 and sessions[1] == sessions[0], "every simulated shift must be CLOSED with a counted difference"
        st = con.execute("SELECT COUNT(*), SUM(status='ADJUSTED') FROM stocktakes").fetchone()
        assert st[0] >= 1 and st[1] == st[0], "every simulated stocktake must be approved & applied"
        items = con.execute("SELECT COUNT(*) FROM stocktake_items WHERE status IN ('ADJUSTED','VERIFIED')").fetchone()[0]
        assert items >= 20, "a stocktake without counted items proves nothing"
        mv = con.execute("SELECT COUNT(*) FROM stock_movements WHERE movement_type='STOCKTAKE'").fetchone()[0]
        assert mv >= 1, "approved stocktakes must leave STOCKTAKE movements"
        audit = con.execute("SELECT COUNT(*) FROM audit_logs WHERE action IN ('STOCKTAKE_COMPLETED','STOCKTAKE_APPROVED')").fetchone()[0]
        assert audit >= 2
    finally:
        con.close()


def test_colab_notebook_is_valid_and_runs_the_real_project():
    nb_path = ROOT / "tools" / "colab_year_simulator.ipynb"
    assert nb_path.exists(), "the Colab notebook must live in tools/ on GitHub"
    nb = json.loads(nb_path.read_text(encoding="utf-8"))
    assert nb["nbformat"] == 4
    code_cells = ["".join(c["source"]) for c in nb["cells"] if c["cell_type"] == "code"]
    joined = "\n".join(code_cells)
    assert "khajavy8056/Super-system-" in joined, "must clone the real project from GitHub"
    assert "simulate_year" in joined, "must run the repo's simulator, not a re-implementation"
    assert "generate_backup_file" in joined or "simulate_year.main" in joined
    assert "files.download" in joined, "must auto-download the backup at the end"
    md = "\n".join("".join(c["source"]) for c in nb["cells"] if c["cell_type"] == "markdown")
    assert "GPU" in md, "must state the honest GPU note (CPU-bound simulation)"


def test_simulate_year_cli_exists_and_is_runnable():
    script = ROOT / "tools" / "simulate_year.py"
    assert script.exists()
    r = subprocess.run([sys.executable, str(script), "--help"], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    assert "--per-day" in r.stdout and "--resume-dir" in r.stdout
