# -*- coding: utf-8 -*-
"""build-505 — شبیه‌ساز سال فروشگاه: پوشش کامل بخش‌های برنامه با سرویس‌های واقعی.

گزارش مالک: شبیه‌ساز کولب باید «یک فروشگاه واقعی تا یک سال» باشد — نه فقط فاکتور و فروش:
شیفت‌ها، حضور روزانه، حقوق (پرداخت‌شده و در انتظار)، مدال‌های کارکنان با پاداش مالی
(از مسیر واقعی فیلد bonus حقوق)، اطلاعیهٔ مراسم، و پروفایل عملکرد هر کارمند — همه از
سرویس‌های واقعی برنامه تا هر مشکل برنامه در شبیه‌سازی خودش را نشان دهد.

این تست یک سالِ کوتاه (۱۲ روز) را با همان مسیر رسمی (demo_store.generate → پشتیبان)
می‌سازد و وجود همهٔ بخش‌ها را در خود پایگاه + خلاصه اثبات می‌کند؛ یعنی شبیه‌ساز
برای همیشه با برنامه تست می‌شود، نه فقط نوشته.
"""
from __future__ import annotations

import os
import pytest
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _run_short_sim(tmp_dir: Path) -> tuple[Path, dict]:
    """همان مسیر رسمی CLI: generate_backup_file در ساب‌پروسه با DATABASE_URL مستقل."""
    os.environ.pop("DATABASE_URL", None)   # مسیر رسمی خودش env ساب‌پروسه را می‌سازد
    sys_path = str(ROOT / "backend")
    import sys
    if sys_path not in sys.path:
        sys.path.insert(0, sys_path)
    from app.services.demo_store import generate_backup_file
    out = tmp_dir / "sim_check.db.gz"
    summary = generate_backup_file(out, days=12, seed=7, invoices_per_day=6.0,
                                   compress=True, full_catalog=False)
    return out, summary


def test_year_simulator_covers_the_whole_store_with_real_services(tmp_path):
    out, summary = _run_short_sim(tmp_path)
    # فایل پشتیبان ساخته شد و SQLite معتبر است (همان اعتبارسنجی مسیر restore)
    import gzip
    import sqlite3
    assert out.is_file() and out.stat().st_size > 0
    with gzip.open(out, "rb") as fh:
        assert fh.read(16) == b"SQLite format 3\x00"
    # خلاصهٔ ماشین‌خوان: همهٔ بخش‌های اصلی سال حضور دارند
    for key in ("invoices", "sales", "customers", "cash_sessions", "stocktakes", "insights", "hr"):
        assert key in summary, f"خلاصهٔ شبیه‌سازی {key} ندارد"

    hr = summary["hr"] or {}
    # ---- منابع انسانی: شیفت/حضور/حقوق (پرداخت‌شده + در انتظار) ----
    assert hr.get("shifts", 0) >= 3, "سه شیفت رسمی"
    assert hr.get("attendance_days", 0) >= 8, "حضور روزانهٔ واقعی"
    assert hr.get("payroll_paid", 0) > 0, "حقوق پرداخت‌شده"
    assert hr.get("payroll_pending", 0) > 0, "حقوق در انتظار (بودن/نبودن هر دو)"
    assert hr.get("announcements", 0) >= 1, "اطلاعیهٔ مراسم"
    # ---- مدال کارکنان با پاداش مالی و پروفایل عملکرد ----
    medals = hr.get("medals") or []
    staff = hr.get("staff") or []
    assert len(medals) >= 3 and all(m.get("bonus", 0) > 0 for m in medals), "مدال + پاداش"
    assert len(staff) >= 3, "پروفایل عملکرد همهٔ کارکنان"
    assert all({"username", "full_name", "medal", "invoices", "revenue", "attendance_days"} <= set(x) for x in staff)

    # ---- داخل خود پایگاه پشتیبان (سازگاری با restore برنامه) ----
    import gzip as _gz
    raw_db = tmp_path / "sim_check.db"
    with _gz.open(out, "rb") as src, open(raw_db, "wb") as dst:
        dst.write(src.read())
    con = sqlite3.connect(raw_db)
    try:
        assert con.execute("SELECT COUNT(*) FROM hr_shifts WHERE status='ACTIVE'").fetchone()[0] >= 3
        assert con.execute("SELECT COUNT(*) FROM hr_shift_attendance").fetchone()[0] >= 8
        paid, pending = con.execute(
            "SELECT SUM(status='PAID'), SUM(status='APPROVED') FROM hr_payroll").fetchone()
        assert (paid or 0) > 0 and (pending or 0) > 0, "هم PAID هم APPROVED (پرداخت‌نشده)"
        bonus_rows = con.execute(
            "SELECT COUNT(*) FROM hr_payroll WHERE note LIKE '%پاداش%' AND bonus > 0").fetchone()[0]
        assert bonus_rows >= 1, "پاداش مدال از فیلد واقعی bonus حقوق"
        assert con.execute("SELECT COUNT(*) FROM announcements WHERE title LIKE '%مدال%'").fetchone()[0] >= 1
        # فاکتور/مشتری/انبارگردانی سال هم سر جایشان‌اند
        assert con.execute("SELECT COUNT(*) FROM invoices").fetchone()[0] > 0
        assert con.execute("SELECT COUNT(*) FROM customers").fetchone()[0] > 0
    finally:
        con.close()


def test_simulator_cli_documents_hr_and_medals():
    """CLI رسمی خلاصهٔ HR/مدال را چاپ می‌کند (برای دمو و بازاریابی)."""
    src = (ROOT / "tools" / "simulate_year.py").read_text(encoding="utf-8")
    assert "پروفایل عملکرد کارکنان" in src
    assert "مراسم اهدای مدال سال" in src
    assert "حقوق پرداخت‌شده / در انتظار" in src


def test_notebook_runs_the_official_core_and_verifies_hr():
    """نوت‌بوک کولب: هیچ منطق موازی‌ای ندارد؛ نسخه از آخرین Release خودکار می‌آید؛ HR راستی‌آزمایی می‌شود."""
    import json
    nb = json.loads((ROOT / "tools" / "colab_year_simulator.ipynb").read_text(encoding="utf-8"))
    cells = ["".join(c["source"]) for c in nb["cells"]]
    all_src = "\n".join(cells)
    assert "simulate_year" in all_src, "مسیر رسمی CLI"
    assert "releases/latest" in all_src, "نسخهٔ خودکار از آخرین انتشار"
    assert "کولب — شیفت صبح" not in all_src, "ثبت دستی/موازی شیفت حذف شده باشد"
    assert "مراسم اهدای مدال" in all_src and "hr_payroll" in all_src, "راستی‌آزمایی HR/مدال"


def test_memory_trim_covers_all_levels():
    """OOM گزارش‌شده (Binder/Parcel): پله‌های کامل onTrimMemory کش‌ها را خالی می‌کنند."""
    diag = (ROOT / "mobile-android" / "app" / "src" / "main" / "java" / "ir" / "khajavy" / "supermarket" / "Diagnostics.java").read_text(encoding="utf-8")
    assert "TRIM_MEMORY_RUNNING_MODERATE" in diag
    assert "TRIM_MEMORY_RUNNING_LOW" in diag
    assert "tileCacheClear" in diag and "onLowMemory" in diag


@pytest.mark.timeout(600)   # دو اجرای کامل CLI (تازه + ادامه) ~۳ دقیقه
def test_cli_fresh_start_with_resume_dir_then_resume_continues(tmp_path):
    """build-506 — رگرسیون کولب: «شروع تازه» با --resume-dir نباید NO_SIMULATION_TO_RESUME بدهد؛
    و اجرای دوبارهٔ همان پوشه باید از checkpoint ادامه دهد. دقیقاً همان مسیر سلول ۴ کولب."""
    import sys
    sys_path = str(ROOT / "tools")
    if sys_path not in sys.path:
        sys.path.insert(0, sys_path)
    import simulate_year

    out = tmp_path / "sim.db.gz"
    work = tmp_path / "work"
    work.mkdir()
    base = ["--seed", "5", "--out", str(out), "--resume-dir", str(work)]

    # ۱) اجرای اول — شروع تازه در پوشهٔ خالی (قبل از رفع: ValueError NO_SIMULATION_TO_RESUME)
    assert simulate_year.main(["--days", "2", "--per-day", "3"] + base) == 0
    assert out.is_file() and out.stat().st_size > 0

    # ۲) اجرای دوبارهٔ همان پوشه — ادامه از checkpoint (پایگاه کامل است)
    assert simulate_year.main(["--days", "2", "--per-day", "3"] + base) == 0
    assert out.is_file()

    # ۳) پوشهٔ کثیف بدون checkpoint — پیام روشن، نه سکوت
    dirty = tmp_path / "dirty"
    dirty.mkdir()
    (dirty / "stray.txt").write_text("x", encoding="utf-8")
    try:
        simulate_year.main(["--days", "1", "--per-day", "2", "--seed", "5",
                            "--out", str(tmp_path / "x.db.gz"), "--resume-dir", str(dirty)])
        raised = False
    except ValueError as exc:
        raised = "WORK_DIRECTORY_NOT_EMPTY" in str(exc) or "NO_COMPLETED_CHECKPOINT" in str(exc)
    assert raised, "پوشهٔ کثیف باید خطای روشن بدهد"
