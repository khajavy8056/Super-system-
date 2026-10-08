# -*- coding: utf-8 -*-
"""build-496 (دور دوم ممیزی) — «یک شبیه‌ساز، یک مسیر».

ریشهٔ باگی که این فایل نگه می‌دارد: نوت‌بوک کولب (`tools/colab_year_simulator.ipynb`)
یک‌بار منطق شبیه‌سازی را *درون خودش* بازنویسی کرده بود (فاز شیفت‌بندی با سرویس
`app.services.shifts` داخل سلول). نتیجه:

  • تست `test_v47_pos_suggestions.py::test_colab_notebook_is_valid_and_runs_the_real_project`
    (قاعدهٔ «شبیه‌ساز واقعی را اجرا کن، نه بازپیاده‌سازی») قرمز شد؛
  • فایلی که به دست فروشنده می‌رسد از مسیری می‌آمد که هیچ تستی پوشش نمی‌داد.

اصلاح: فاز شیفت‌بندی/حضور به خودِ شبیه‌ساز مخزن منتقل شد
(`demo_store._simulate_hr_shifts` + `hr_shifts=True`) و نوت‌بوک فقط
`tools/simulate_year.py` را اجرا می‌کند. این تست‌ها همان مرز را نگه می‌دارند.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
NOTEBOOK = ROOT / "tools" / "colab_year_simulator.ipynb"
SIMULATOR = ROOT / "tools" / "simulate_year.py"


def _notebook() -> dict:
    return json.loads(NOTEBOOK.read_text(encoding="utf-8"))


def _code(nb: dict) -> str:
    return "\n".join("".join(c["source"]) for c in nb["cells"] if c["cell_type"] == "code")


def test_notebook_runs_the_repo_simulator_and_implements_no_simulation_itself():
    nb = _notebook()
    code = _code(nb)
    assert "khajavy8056/Super-system-" in code, "نوت‌بوک باید کد را از مخزن واقعی بگیرد"
    assert "simulate_year" in code, "نوت‌بوک باید همان شبیه‌ساز مخزن را اجرا کند"
    assert "simulate_year.main" in code or "generate_backup_file" in code
    # «بازپیاده‌سازی ممنوع»: هیچ منطق شبیه‌سازی داخل نوت‌بوک نمانده باشد.
    for forbidden in ("from app.services import", "import demo_store", "shift_specs",
                      "generate_backup_file(", "clock_in(", "create_shift("):
        assert forbidden not in code, f"منطق شبیه‌سازی دوباره داخل نوت‌بوک آمده: {forbidden}"
    assert "files.download" in code, "فایل پشتیبان باید در پایان دانلود شود"
    md = "\n".join("".join(c["source"]) for c in nb["cells"] if c["cell_type"] == "markdown")
    assert "GPU" in md, "توضیح صادقانهٔ GPU (شبیه‌سازی فقط CPU است) باید بماند"


def test_notebook_pins_a_branch_that_exists_and_verifies_the_version():
    """برچسب نسخهٔ `v1.0.496` هرگز روی GitHub ساخته نشد؛ pin به آن یعنی اجرای خراب."""
    code = _code(_notebook())
    assert 'SOURCE_BRANCH = "main"' in code
    assert "SOURCE_TAG" not in code, "pin به برچسبی که ساخته نشده، اجرای کولب را می‌شکند"
    assert "__version__" in code and "APP_VERSION" in code, "نسخهٔ کد باید بررسی شود"


def test_cli_exposes_the_hr_phase_and_prints_it():
    src = SIMULATOR.read_text(encoding="utf-8")
    assert "--no-hr-shifts" in src and "hr_shifts=not args.no_hr_shifts" in src
    assert "hr_shifts" in src, "خلاصهٔ شیفت‌ها باید در خروجی شبیه‌ساز دیده شود"
    # بنر نسخه از خودِ کد خوانده می‌شود؛ رشتهٔ ثابتِ کهنه («v4.8.0») دوباره برنگردد.
    assert "شبیه‌ساز فروشگاه — سوپری‌من" not in src
    assert '__version__\\s*=\\s*"([^"]+)"' in src and "رسا سیستم {version}" in src


def test_demo_store_owns_the_shift_phase_and_uses_the_real_service():
    src = (ROOT / "backend" / "app" / "services" / "demo_store.py").read_text(encoding="utf-8")
    assert "def _simulate_hr_shifts(" in src
    assert "from . import shifts as shift_svc" in src, "شیفت‌ها باید از سرویس رسمی ثبت شوند"
    for call in ("shift_svc.assign(", "shift_svc.clock_in(", "shift_svc.clock_out("):
        assert call in src, call
    assert "hr_shifts: bool = True" in src, "فاز شیفت باید پارامتر رسمی شبیه‌ساز باشد"


def test_generated_backup_really_contains_shifts_and_attendance(tmp_path):
    """ادعای «شیفت‌ها در فایل هستند» فقط با شمارش رکوردها پذیرفته می‌شود."""
    import sqlite3
    import gzip

    from app.services import demo_store

    out = tmp_path / "build496_shifts.db.gz"
    summary = demo_store.generate_backup_file(out, days=2, seed=7, invoices_per_day=6,
                                              compress=True, full_catalog=False)
    assert out.exists() and out.stat().st_size > 1000
    hr = summary.get("hr_shifts") or {}
    assert not summary.get("hr_shifts_error"), summary.get("hr_shifts_error")
    assert hr.get("definitions", 0) >= 3, hr
    assert hr.get("attendance_records", 0) >= 2 * 2, hr

    raw = gzip.decompress(out.read_bytes())
    con = sqlite3.connect("file::memory:?cache=shared", uri=True)
    try:
        con.deserialize(raw)
        rows = con.execute("SELECT COUNT(*), SUM(late_minutes IS NOT NULL) FROM hr_shift_attendance").fetchone()
        assert rows[0] == hr["attendance_records"], "خلاصه و پایگاه یکی نیستند"
        assignments = con.execute("SELECT COUNT(*) FROM hr_shift_assignments").fetchone()[0]
        assert assignments == hr["daily_assignments"] >= 2 * 2
        shifts = con.execute("SELECT COUNT(*) FROM hr_shifts").fetchone()[0]
        assert shifts == hr["definitions"] == 3
    finally:
        con.close()


def test_hr_phase_can_be_switched_off_for_a_fast_backup(tmp_path):
    from app.services import demo_store

    out = tmp_path / "build496_noshifts.db.gz"
    summary = demo_store.generate_backup_file(out, days=2, seed=7, invoices_per_day=6,
                                              compress=True, full_catalog=False, hr_shifts=False)
    assert out.exists()
    assert not summary.get("hr_shifts")
    assert not summary.get("hr_shifts_error")
