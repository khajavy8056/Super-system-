# -*- coding: utf-8 -*-
"""build-507 — بازیابی فایل شبیه‌ساز نباید بخش کارکنان را گم کند (گزارش مالک).

گزارش: «فایل پشتیبان را بازیابی می‌کنم و موارد کارکنان نمی‌آید.» هر دو سمت بررسی شد:

۱) **فایل پشتیبان** — شبیه‌ساز رسمی (build-505) جدول‌های منابع انسانی را داخل خودِ
   فایل می‌نویسد (hr_shifts / hr_shift_assignments / hr_shift_attendance / hr_payroll /
   announcements / announcement_reads / hr_achievements) → سالم است؛ اینجا دوباره اثبات می‌شود.

۲) **ویندوز** — /restore کل فایل را با API رسمی SQLite جایگزین می‌کند و پس از
   upgrade_schema + heal_schema + bootstrap (افزودنی) سطرهای منابع انسانی سر جایشان
   می‌مانند → تست سرتاسری: همان فایل .gz کولب مستقیم به /restore داده می‌شود.

۳) **اندروید** — مسیر import ویندوز (PcImport.run) جدول‌به‌جدول کپی می‌کرد و
   «همهٔ» جدول‌های منابع انسانی را جا انداخته بود → در build-507 اصلاح شد. تست، SQL
   واقعی را از خود سورس PcImport.java و DDL واقعی گوشی را از Db.java استخراج و اجرا
   می‌کند (بدون شبیه‌سازی دستی) تا هر تغییری که import کارکنان را دوباره بشکند،
   همین‌جا بشکند. نتیجه: پس از بازیابی، شیفت‌ها، تخصیص‌ها، حضور، حقوق، اطلاعیه‌ها و
   وضعیت خواندن — همه روی گوشی هم حاضرند.
"""
from __future__ import annotations

import gzip
import re
import sqlite3
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

# همان مسیر رسمی تست build-505: تولید فایل شبیه‌ساز با سرویس‌های واقعی برنامه
SIM_DAYS, SIM_SEED, SIM_PER_DAY = 12, 7, 6.0


@pytest.fixture(scope="module")
def sim_gz(tmp_path_factory) -> Path:
    """یک فایل پشتیبان شبیه‌ساز واقعی — مشترک بین تست‌های این ماژول."""
    import os
    import sys
    os.environ.pop("DATABASE_URL", None)
    sys_path = str(ROOT / "backend")
    if sys_path not in sys.path:
        sys.path.insert(0, sys_path)
    from app.services.demo_store import generate_backup_file
    out = tmp_path_factory.mktemp("sim507") / "sim.db.gz"
    generate_backup_file(out, days=SIM_DAYS, seed=SIM_SEED, invoices_per_day=SIM_PER_DAY,
                         compress=True, full_catalog=False)
    assert out.is_file() and out.stat().st_size > 0
    return out


def _extract_db(gz: Path, dst: Path) -> Path:
    with gzip.open(gz, "rb") as src, open(dst, "wb") as out:
        out.write(src.read())
    return dst


# ---------------------------------------------------------------------------
# ۱) سمت فایل: پشتیبانِ شبیه‌ساز خودِ داده‌های کارکنان را دارد
# ---------------------------------------------------------------------------

def test_sim_backup_file_contains_all_hr_sections(sim_gz, tmp_path):
    con = sqlite3.connect(_extract_db(sim_gz, tmp_path / "sim.db"))
    try:
        assert con.execute("SELECT COUNT(*) FROM hr_shifts WHERE status='ACTIVE'").fetchone()[0] >= 3
        assert con.execute("SELECT COUNT(*) FROM hr_shift_assignments").fetchone()[0] >= 3
        assert con.execute("SELECT COUNT(*) FROM hr_shift_attendance").fetchone()[0] >= 8
        paid, pending = con.execute(
            "SELECT SUM(status='PAID'), SUM(status='APPROVED') FROM hr_payroll").fetchone()
        assert (paid or 0) > 0 and (pending or 0) > 0, "هم حقوق پرداخت‌شده هم در انتظار"
        assert con.execute("SELECT COUNT(*) FROM announcements").fetchone()[0] >= 1
        assert con.execute("SELECT COUNT(*) FROM users").fetchone()[0] >= 4, "ادمین + کارکنان"
    finally:
        con.close()


# ---------------------------------------------------------------------------
# ۲) سمت ویندوز: /restore همان فایل .gz کولب — کارکنان باید سر جایشان بمانند
# ---------------------------------------------------------------------------

def test_windows_restore_keeps_hr_sections_end_to_end(client, auth_headers, sim_gz, tmp_path):
    with open(sim_gz, "rb") as f:  # عیناً فایل فشردهٔ خروجی کولب، نه دیتابیس باز‌شده
        rs = client.post("/restore", headers=auth_headers,
                         files={"file": ("store.db.gz", f, "application/octet-stream")})
    assert rs.status_code == 200, rs.text

    from app.database import SessionLocal
    from sqlalchemy import text
    s = SessionLocal()
    try:
        q = lambda sql: s.execute(text(sql)).scalar()  # noqa: E731
        assert q("SELECT COUNT(*) FROM users") >= 4, "کاربران (ادمین + کارکنان) بازیابی شد"
        assert q("SELECT COUNT(*) FROM hr_shifts WHERE status='ACTIVE'") >= 3, "شیفت‌ها"
        assert q("SELECT COUNT(*) FROM hr_shift_assignments") >= 3, "تخصیص شیفت‌ها"
        assert q("SELECT COUNT(*) FROM hr_shift_attendance") >= 8, "حضور و غیاب"
        paid, pending = s.execute(text(
            "SELECT SUM(status='PAID'), SUM(status='APPROVED') FROM hr_payroll")).fetchone()
        assert (paid or 0) > 0 and (pending or 0) > 0, "حقوق پرداخت‌شده + در انتظار"
        bonus_rows = q("SELECT COUNT(*) FROM hr_payroll WHERE bonus > 0 AND note LIKE '%پاداش%'")
        assert bonus_rows >= 1, "پاداش مدال از مسیر واقعی حقوق"
        assert q("SELECT COUNT(*) FROM announcements") >= 1, "اطلاعیهٔ مراسم مدال"
        assert q("SELECT COUNT(*) FROM invoices") > 0, "فاکتورهای سال"
        assert q("SELECT COUNT(*) FROM products") > 0, "کالاها"
    finally:
        s.close()
    # برنامه پس از بازیابی سالم است (مسیر کامل: upgrade_schema → heal_schema → bootstrap)
    assert client.get("/api/products", headers=auth_headers).status_code == 200


# ---------------------------------------------------------------------------
# ۳) سمت اندروید: SQL واقعی PcImport.java × DDL واقعی Db.java × فایل شبیه‌ساز واقعی
# ---------------------------------------------------------------------------

_PHONE_TABLES = ("local_shifts", "local_shift_assignments", "local_attendance",
                 "local_payroll", "local_announcements", "local_announcement_reads")


def _phone_ddl_from_db_java() -> list[str]:
    """DDL واقعی جدول‌های local_* را از خود Db.java می‌خواند — اگر کسی اسکیمای گوشی را
    عوض کند، این تست با نسخهٔ جدید تست می‌شود؛ اگر جدولی حذف شود، می‌شکند."""
    src = (ROOT / "mobile-android/app/src/main/java/ir/khajavy/supermarket/Db.java").read_text("utf-8")
    ddl = []
    for t in _PHONE_TABLES:
        m = re.search(r'"(CREATE TABLE IF NOT EXISTS ' + t + r'\([^"]*\))"', src)
        assert m, f"DDL جدول {t} در Db.java پیدا نشد"
        ddl.append(m.group(1))
    return ddl


def _pcimport_hr_sql() -> list[str]:
    """دستورهای import منابع انسانی را از خود PcImport.java استخراج می‌کند
    (رشته‌های چندخطی جاوا را به هم می‌چسباند) — همان SQLی که روی گوشی اجرا می‌شود."""
    src = (ROOT / "mobile-android/app/src/main/java/ir/khajavy/supermarket/PcImport.java").read_text("utf-8")
    out = []
    # فقط فراخوانی‌هایی که بدنه‌شان الحاقِ رشته‌های literal است (import جدول‌به‌جدول)؛
    # فراخوان‌های با آرگومان پارامتری مثل ATTACH/کاونترها الگو را نمی‌گیرند.
    for m in re.finditer(r'd\.execSQL\(\s*((?:"[^"]*"\s*\+?\s*)+)\);\s*\}\s*catch', src):
        sql = "".join(re.findall(r'"([^"]*)"', m.group(1)))
        if any("INTO " + t + "(" in sql for t in _PHONE_TABLES):
            assert " FROM pc." in sql, f"دستور import باید از جدول pc بخواند: {sql[:80]}"
            out.append(sql)
    assert len(out) == len(_PHONE_TABLES), (
        f"انتظار {len(_PHONE_TABLES)} دستور import منابع انسانی، {len(out)} پیدا شد — "
        "import کارکنان در PcImport.java ناقص است (گزارش build-507)")
    return out


def test_android_pcimport_source_has_all_hr_tables():
    src = (ROOT / "mobile-android/app/src/main/java/ir/khajavy/supermarket/PcImport.java").read_text("utf-8")
    for pc_table in ("pc.hr_shifts", "pc.hr_shift_assignments", "pc.hr_shift_attendance",
                     "pc.hr_payroll", "pc.announcements", "pc.announcement_reads"):
        assert pc_table in src, f"PcImport.java دیگر {pc_table} را import نمی‌کند"


def test_android_pcimport_imports_hr_from_real_sim_file(sim_gz, tmp_path):
    pc = _extract_db(sim_gz, tmp_path / "pc.db")
    # شبیه‌ساز «وضعیت خواندن» نمی‌سازد؛ برای آزمودن مسیر import آن، یک سطر واقعی‌نما
    # با همان اسکیمای فایل PC می‌کاریم (اولین کاربر × اولین اطلاعیه).
    pcon = sqlite3.connect(pc)
    try:
        ann = pcon.execute("SELECT id FROM announcements LIMIT 1").fetchone()
        usr = pcon.execute("SELECT id FROM users WHERE username<>'admin' LIMIT 1").fetchone()
        assert ann and usr
        pcon.execute("INSERT INTO announcement_reads(id,announcement_id,user_id,delivered_at,seen_at,read_at) "
                     "VALUES(900001,?,?,datetime('now'),datetime('now'),NULL)", (ann[0], usr[0]))
        pcon.commit()
    finally:
        pcon.close()
    phone_path = tmp_path / "phone.db"
    d = sqlite3.connect(phone_path)
    try:
        for stmt in _phone_ddl_from_db_java():
            d.execute(stmt)
        d.execute(f"ATTACH DATABASE '{pc}' AS pc")
        for stmt in _pcimport_hr_sql():  # همان SQL production — ترتیب خود فایل
            d.execute(stmt)
        d.commit()

        one = lambda sql: d.execute(sql).fetchone()[0]  # noqa: E731
        assert one("SELECT COUNT(*) FROM local_shifts") >= 3, "شیفت‌ها وارد شد"
        row = d.execute("SELECT name,start_time,end_time,workdays,status FROM local_shifts LIMIT 1").fetchone()
        assert row[0] and row[1] and row[2], "نام و ساعت شیفت"
        assert row[4] == "ACTIVE"
        assert one("SELECT COUNT(*) FROM local_shift_assignments") >= 3, "تخصیص‌ها وارد شد"
        assert one("SELECT COUNT(*) FROM local_attendance") >= 8, "حضور وارد شد"
        att = d.execute("SELECT day,late_minutes,started_at FROM local_attendance WHERE started_at IS NOT NULL LIMIT 1").fetchone()
        assert att and att[0] and "T" in att[2], f"زمان به قالب گوشی تبدیل شد: {att}"
        paid = one("SELECT COUNT(*) FROM local_payroll WHERE status='PAID'")
        pending = one("SELECT COUNT(*) FROM local_payroll WHERE status='APPROVED'")
        assert paid > 0 and pending > 0, "حقوق پرداخت‌شده + در انتظار وارد شد"
        pr = d.execute("SELECT period,total,bonus FROM local_payroll WHERE bonus>0 LIMIT 1").fetchone()
        assert pr and pr[1] > 0 and pr[2] > 0, "مبلغ و پاداش حقوق سالم کپی شد"
        assert one("SELECT COUNT(*) FROM local_announcements") >= 1, "اطلاعیه وارد شد"
        title = d.execute("SELECT title FROM local_announcements LIMIT 1").fetchone()[0]
        assert title, "عنوان اطلاعیه"
        assert one("SELECT COUNT(*) FROM local_announcement_reads") >= 1, "وضعیت خواندن وارد شد"
        rd = d.execute("SELECT user_id,delivered_at FROM local_announcement_reads LIMIT 1").fetchone()
        assert rd[0] > 0 and ("T" in rd[1] or rd[1] is None), "خوانندهٔ اطلاعیه با زمان تبدیل‌شده"
        # شناسه‌ها حفظ شده‌اند تا همگام‌سازی بعدی دوباره نسازد (pc_id = id، ریموت)
        sft = d.execute("SELECT id,pc_id,is_local FROM local_shifts LIMIT 1").fetchone()
        assert sft[0] > 0 and sft[1] == sft[0] and sft[2] == 0
    finally:
        try:
            d.execute("DETACH DATABASE pc")
        except Exception:
            pass
        d.close()
