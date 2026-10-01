# -*- coding: utf-8 -*-
"""v4.0.1 — the Windows build scripts must stay parseable by Windows PowerShell.

Windows PowerShell 5.1 reads a ``.ps1`` without a UTF-8 BOM as ANSI, so every
Persian string in the build scripts turns into mojibake tokens and the whole
installer build dies with "Unexpected token" errors — exactly what happened to
the owner's machine after an edit stripped the BOM (2026-09-23). This test pins
the encoding so that regression can never ship again: every PowerShell script
under ``installer/`` must start with the UTF-8 BOM and decode as UTF-8.
"""
from __future__ import annotations

from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
BOM = b"\xef\xbb\xbf"

#: scripts that PowerShell 5.1 parses — all of them must carry the BOM
PS1_FILES = sorted((REPO / "installer").rglob("*.ps1"))


def test_installer_ps1_files_exist():
    assert PS1_FILES, "installer/*.ps1 not found — wrong repo layout?"


@pytest.mark.parametrize("script", PS1_FILES, ids=lambda p: p.name)
def test_ps1_has_utf8_bom_and_valid_utf8(script: Path):
    data = script.read_bytes()
    assert data.startswith(BOM), (
        f"{script.name} lost its UTF-8 BOM — Windows PowerShell 5.1 will read it as "
        "ANSI and fail to parse the Persian strings (this exact regression broke the "
        "owner's build on 2026-09-23). Re-save the file as UTF-8 **with BOM**.")
    data[len(BOM):].decode("utf-8")           # raises if it is not valid UTF-8


@pytest.mark.parametrize("script", PS1_FILES, ids=lambda p: p.name)
def test_ps1_line_endings_are_consistent(script: Path):
    data = script.read_bytes()
    lf = data.count(b"\n")
    crlf = data.count(b"\r\n")
    assert crlf == lf, (
        f"{script.name} mixes CRLF and LF line endings "
        f"({crlf} CRLF vs {lf} LF) — normalize to CRLF")


def test_build_bat_files_are_not_utf16_or_bommed():
    """cmd.exe parses .bat files byte-wise; a UTF-8/UTF-16 BOM breaks the first
    command line ("@echo off" must be the literal first bytes)."""
    for bat in sorted((REPO / "installer").rglob("*.bat")):
        data = bat.read_bytes()
        assert not data.startswith((BOM, b"\xff\xfe", b"\xfe\xff")), \
            f"{bat.name} must not start with a BOM"


def test_builder_lib_has_no_model_step():
    """v4.6.0 — the owner removed the local AI model: the builder must NOT
    download or verify any model any more, and the honest UTF-8 rule for
    Python output must survive."""
    text = (REPO / "installer" / "windows" / "builder-lib.ps1").read_text(encoding="utf-8-sig")
    assert "prepare_windows_installer" not in text and "verify_setup" not in text
    assert "آماده‌سازی مدل هوش محلی" not in text, "the model step is removed"
    assert "PYTHONUTF8" in text, "Python output must be forced to UTF-8 on Windows"


# ---------------------------------------------------------------------------
# build-485 — «نصبی جدید، ظاهر قدیمی»: قرارداد تازگی رابط کاربری در زنجیرهٔ ساخت.
# ---------------------------------------------------------------------------
def test_ui_build_marker_matches_build_file():
    """تک‌منبع بودن شمارهٔ بیلد: نشان ui-build در app.js باید از mobile-android/BUILD
    مشتق شده باشد (صدم بیلد) و سازندهٔ ویندوز همان را راستی‌آزمایی کند."""
    build = (REPO / "mobile-android" / "BUILD").read_text(encoding="utf-8").strip()
    assert build.isdigit(), build
    ui = int(build) // 100
    app_js = (REPO / "frontend" / "app.js").read_text(encoding="utf-8")
    assert f"ui-build-{ui}" in app_js, "نشان ساخت UI در app.js نیست یا کهنه است"
    assert f"const UI_BUILD = {ui};" in app_js
    lib = (REPO / "installer" / "windows" / "builder-lib.ps1").read_text(encoding="utf-8-sig")
    assert "ui-build-" in lib, "سازنده باید نشان UI را راستی‌آزمایی کند"
    assert "نسخهٔ رابط کاربری کهنه است" in lib, "پیام خطای نسخهٔ کهنه باید وجود داشته باشد"
    assert "/DMyAppBuild=" in lib, "شمارهٔ بیلد باید به Inno Setup برود"


def test_setup_shows_build_number_and_ui_is_never_stale_cached():
    """setup.iss باید بیلد را نشان دهد و سرور پاسخ‌های UI را کش طولانی نکند
    ( WebView2 پیش از این فایل‌های JS قدیمی را نگه می‌داشت)."""
    setup = (REPO / "installer" / "windows" / "setup.iss").read_text(encoding="utf-8-sig")
    assert "MyAppBuild" in setup
    assert "build {#MyAppBuild}" in setup
    main_py = (REPO / "backend" / "app" / "main.py").read_text(encoding="utf-8")
    assert "ui_no_cache" in main_py and "Cache-Control" in main_py


def test_verify_ui_in_exe_never_falsely_blocks(tmp_path):
    """build-486 — بازرسِ داخل exe نباید هرگز خطای مثبت کاذب بدهد (باگ مالک:
    «تم جدید داخل exe نیست» در حالی که داخل بود و Setup ساخته نشد). قرارداد:
    فقط «اثبات کهنگی» قطع می‌کند؛ بازرسی ناممکن ← UNCERTAIN (2) و ادامهٔ ساخت."""
    import importlib.util
    mod_path = REPO / "installer" / "windows" / "verify_ui_in_exe.py"
    spec = importlib.util.spec_from_file_location("verify_ui_in_exe", mod_path)
    v = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(v)

    assert v.find_frontend_entry({"frontend/app.js": (1, 2, 3)}) == "frontend/app.js"
    assert v.find_frontend_entry([("x",), ("y",), ("z", "frontend\\app.js")]) == "frontend\\app.js"
    assert v.find_frontend_entry({"other": 1}) is None

    assert v.marker_in_bytes(b"xx ui-build-486 yy", "ui-build-486")
    assert not v.marker_in_bytes(b"xx ui-build-485 yy", "ui-build-486")

    # فایل آشغال = آرشیو ناشناخته → باید UNCERTAIN (2) برگردد، نه STALE (1)
    junk = tmp_path / "not-an-exe.bin"
    junk.write_bytes(b"this is not a pyinstaller archive at all")
    assert v.inspect(str(junk), "ui-build-486") == 2, "بازرس ناممکن نباید ساخت را متوقف کند"

    # فایل خالی/غایب هم نباید ساختار را بشکند
    assert v.main(["x"]) == 2


def test_builder_uses_verifier_instead_of_raw_byte_scan():
    """سازنده باید از verify_ui_in_exe.py استفاده کند و منطق بایت خام حذف شده باشد."""
    lib = (REPO / "installer" / "windows" / "builder-lib.ps1").read_text(encoding="utf-8-sig")
    assert "verify_ui_in_exe.py" in lib
    assert "ReadAllBytes" not in lib.split("verify_ui_in_exe.py")[1], "اسکن بایت خام باید حذف شده باشد"
    assert (REPO / "installer" / "windows" / "verify_ui_in_exe.py").exists()
