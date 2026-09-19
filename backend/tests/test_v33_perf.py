"""v3.3 — big-store performance & crash-proof Android restore (static + DB checks)."""
from pathlib import Path

from sqlalchemy import inspect

from app.database import PERF_INDEXES, engine

ROOT = Path(__file__).resolve().parents[2]
J = ROOT / "mobile-android/app/src/main/java/ir/khajavy/supermarket"


def test_pc_perf_indexes_exist():
    insp = inspect(engine)
    tables = set(insp.get_table_names())
    for name, table, _cols in PERF_INDEXES:
        if table in tables:
            assert name in {i["name"] for i in insp.get_indexes(table)}, name


def test_android_restore_builds_fresh_file_and_swaps():
    src = (J / "PcImport.java").read_text(encoding="utf8")
    assert "openOrCreateDatabase(fresh" in src and "Db.schema(d)" in src
    assert "renameTo(live)" in src and "Db.swapping = true" in src
    assert "json_object(" in src                      # per-row snapshots built in SQL
    assert "INSERT INTO journal_lines" in src        # posting lines pre-aggregated
    assert "CREATE TEMP TABLE cg" in src             # COGS aggregated once (no correlated subquery per invoice)
    assert "OutOfMemoryError" in src


def test_android_indexes_and_set_based_dashboard():
    db = (J / "Db.java").read_text(encoding="utf8")
    for ix in ("ix_inv_at", "ix_inv_status_at", "ix_ii_pid", "ix_b_p_status", "ix_jl_code", "ix_led_cust"):
        assert ix in db, ix
    assert "enableWriteAheadLogging" in db and "journal_lines" in db
    loc = (J / "Local.java").read_text(encoding="utf8")
    assert "substr(at,1,10)=?" not in loc and "substr(i.at,1,10)=?" not in loc
    assert "FROM journal_lines l JOIN journal j" in loc      # acc() is one SQL SUM now
    assert "expiryBuckets(40)" in loc
    scr = (J / "Screens.java").read_text(encoding="utf8")
    assert "داشبورد آماده نشد" in scr and "تلاش دوباره" in scr   # never an endless spinner
    ins = (J / "InsightScreens.java").read_text(encoding="utf8")
    assert "Notify.progress(" in ins and "new Thread(" in ins
