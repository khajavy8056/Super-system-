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
