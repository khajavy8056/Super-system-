"""v4.3.2 — the Android engine RAM gate was calibrated for PCs, not phones.

Owner round 10: «همچنان در اندروید مدل کار نمیکنه و روشن نمیشه».

Root cause this round: ``BrainEngine.start()`` refused to even TRY when the
phone's total RAM was below the registry's ``minRamMb`` (q3_k_m = 3584 MB — a
number written for "4 GB" Windows machines that report 3.8 GB). The owner's
phone (the 32-bit ARMv7 device from the 4.1.1 install saga) has 2-3 GB, so
pressing «روشن‌کردن موتور» always failed with a memory message before any
attempt. The real requirement is the model file + overhead; on a phone that
is model-MB + ~400 MB.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

ANDROID = ROOT / "mobile-android" / "app" / "src" / "main" / "java" / "ir" / "khajavy" / "supermarket"


# ---------------------------------------------------------------- the RAM math
def test_needed_ram_is_model_plus_overhead_not_the_pc_number():
    """neededRamMb = weights + 400 MB overhead — NOT the registry's minRamMb."""
    from app.services.business_brain import model_registry as reg
    src = (ANDROID / "BrainEngine.java").read_text(encoding="utf-8")
    assert "public static long neededRamMb(BrainModel.Spec s)" in src
    assert "s.bytes / (1024 * 1024) + 400" in src
    q3 = reg.get("qwen2.5-1.5b-instruct-q3_k_m")
    assert q3.file_size_bytes // (1024 * 1024) + 400 == 1281      # 881 + 400
    q4 = reg.get("qwen2.5-1.5b-instruct-q4_k_m")
    assert q4.file_size_bytes // (1024 * 1024) + 400 == 1465
    # both are far below the old PC gate that refused 2-3 GB phones:
    assert q3.min_ram_mb == 3584 and 1281 < 3584


def test_start_no_longer_refuses_with_the_pc_number():
    src = (ANDROID / "BrainEngine.java").read_text(encoding="utf-8")
    start = src[src.find("public static synchronized void start"):src.find("public static synchronized void stop")]
    # the old hard gate is gone…
    assert "fitsRam(c, s))" not in start
    assert "مگابایت رم لازم است" not in start
    # …replaced by the honest attempt gate with real numbers + the alternative
    assert "long ram = totalRamMb(c), need = neededRamMb(s);" in start
    assert "ram < need" in start
    assert "رم گوشی:" in start and "رایانهٔ وصل‌شده کامل در دسترس است" in start


def test_economy_context_when_ram_is_tight():
    """Half the context window when RAM is tight — the KV cache must fit."""
    src = (ANDROID / "BrainEngine.java").read_text(encoding="utf-8")
    assert "public static boolean tightRam(Context c, BrainModel.Spec s)" in src
    assert "final int ctx = tight ? 1024 : CONTEXT;" in src
    assert '"-c", String.valueOf(ctx)' in src
    assert "حالت اقتصادی رم با زمینهٔ متن کوچک‌تر" in src


def test_engine_note_shows_real_numbers_and_the_alternative():
    scr = (ANDROID / "BrainScreens.java").read_text(encoding="utf-8")
    assert "BrainEngine.canRun(c, run)" in scr
    assert "BrainEngine.neededRamMb(run)" in scr
    assert "ظرفیت ندارد" in scr and "مغز روی رایانهٔ وصل‌شده کامل در دسترس است" in scr


def test_oom_death_message_has_numbers_and_advice():
    src = (ANDROID / "BrainEngine.java").read_text(encoding="utf-8")
    assert "موتور بسته شد — رم گوشی:" in src
    assert "اگر اندروید آن را بست (کمبود رم)" in src


# ---------------------------------------------------------------- diagnosis hand-off
def test_copy_engine_report_button():
    """The owner cannot screenshot-paste reliably; one tap copies the full
    engine report (state + note + RAM + llama-server output) for support."""
    scr = (ANDROID / "BrainScreens.java").read_text(encoding="utf-8")
    assert "کپی گزارش موتور برای پشتیبانی" in scr
    assert "ClipboardManager" in scr
    assert "BrainEngine.tail())" in scr


# ---------------------------------------------------------------- versions
def test_versions_consistent():
    from app import __version__
    iss = (ROOT / "installer" / "windows" / "setup.iss").read_text(encoding="utf-8-sig")
    assert f'#define MyAppVersion "{__version__}"' in iss
