# -*- coding: utf-8 -*-
"""build-519 — ریشه‌ای: «no such column: min_purchase_count» دیگر در هیچ مسیری ممکن نیست.

گزارش مالک (اسکرین‌شات خطای واقعی روی گوشی): ذخیرهٔ جشنواره fail می‌شد با
«خطای داخلی گوشی: no such column: min_purchase_count». ریشه: ستون‌های جادوگر
داخل بلوک ارتقای v12 گره خورده بودند؛ دیتابیسی که از قبل در نسخهٔ ۱۲ بود
(کاربری که از ۵۱۴ ارتقا داده بود) هرگز آن بلوک را اجرا نمی‌کند.

قفل‌های ساختاری:
۱) بلوک ارتقای مستقل v13 + ارتقای نسخهٔ دیتابیس ۱۲→۱۳.
۲) خودترمیمی در onOpen — هر باز شدن دیتابیس ستون‌ها را ایدمپوتنت تضمین می‌کند
   (ارتقای جاافتاده، restore فایل قدیمی، هر مسیر آینده).
۳) CREATE TABLE تازه‌نصب هم ستون‌ها را از روز اول دارد.
۴) v12 دیگر ستون جادوگر ندارد (گره خوردن به بلوک‌های قدیمی ممنوع).
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
import app as _app  # noqa: E402

ANDROID = ROOT / "mobile-android/app/src/main/java/ir/khajavy/supermarket"
DBJ = (ANDROID / "Db.java").read_text("utf-8")


def _v13_block() -> str:
    start = DBJ.index("static void v13CampaignWizard(SQLiteDatabase d) {")
    return DBJ[start:DBJ.index("}", DBJ.index("reward_next_only", start))]


def test_upgrade_block_v13_independent():
    assert "static void v13CampaignWizard(SQLiteDatabase d)" in DBJ
    block = _v13_block()
    assert 'addColumn(d, "campaigns", "min_purchase_count INTEGER NOT NULL DEFAULT 0");' in block
    assert 'addColumn(d, "campaigns", "reward_next_only INTEGER NOT NULL DEFAULT 0");' in block
    assert "static final int VERSION = 13;" in DBJ
    assert "if (a < 13) v13CampaignWizard(d);" in DBJ
    # ستون‌های جادوگر دیگر در بلوک قدیمی v12 نیستند (تا شروع کامنت v13)
    v12_start = DBJ.index("static void v12PosAutoIssue(SQLiteDatabase d) {")
    v12 = DBJ[v12_start:DBJ.index("/** build-519")]
    assert "min_purchase_count" not in v12 and "reward_next_only" not in v12


def test_onopen_self_heal_runs_on_every_open():
    onopen = DBJ[DBJ.index("public void onOpen(SQLiteDatabase d) {"):]
    onopen = onopen[:onopen.index("\n    }")]
    assert "try { v13CampaignWizard(d); } catch (Exception ignore) {}" in onopen, \
        "هر باز شدن دیتابیس باید ستون‌ها را تضمین کند"


def test_fresh_create_table_has_wizard_columns():
    create = DBJ[DBJ.index('"CREATE TABLE IF NOT EXISTS campaigns('):]
    create = create[:create.index('",')]
    assert "min_purchase_count INTEGER DEFAULT 0" in create
    assert "reward_next_only INTEGER DEFAULT 0" in create


def test_version_pins():
    assert _app.__version__ == "1.0.520" and _app.BUILD == 52000
    assert (ROOT / "mobile-android/BUILD").read_text().strip() == "52000"
    assert "const UI_BUILD = 520;" in (ROOT / "frontend/app.js").read_text("utf-8")
    assert "?v=1.0.520" in (ROOT / "frontend/index.html").read_text("utf-8")
