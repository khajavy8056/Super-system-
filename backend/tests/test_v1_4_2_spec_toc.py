"""v1.4.2 — app.spec must extend Analysis TOCs with 3-tuples (dest, src, typecode).
Regression for: ValueError: not enough values to unpack (expected 3, got 2) in EXE()."""
from __future__ import annotations

import re
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = ROOT / "installer" / "windows" / "app.spec"


def _load_helpers():
    """Execute only the helper definitions of app.spec (not Analysis/EXE)."""
    src = SPEC.read_text(encoding="utf-8")
    helper = src[src.index("def _as_toc"):src.index("import importlib.util as _ilu")]
    ns = {"os": __import__("os")}
    exec(helper, ns)
    hidden = src[src.index("def _optional_desktop_hiddenimports"):src.index("a = Analysis(")]
    exec(hidden, ns)
    return ns


def test_as_toc_converts_hook_tuples_to_toc_entries(tmp_path):
    ns = _load_helpers()
    f = tmp_path / "WebView2Loader.dll"; f.write_bytes(b"x")
    out = ns["_as_toc"]([(str(f), "webview/lib"), (str(f), ".")], "BINARY")
    assert all(len(t) == 3 for t in out)
    assert out[0] == ("webview/lib/WebView2Loader.dll".replace("/", __import__("os").sep), str(f), "BINARY")
    assert out[1] == ("WebView2Loader.dll", str(f), "BINARY")
    # the exact unpack PyInstaller's normalize_toc performs
    for dest_name, src_name, typecode in out:
        assert dest_name and src_name and typecode in ("DATA", "BINARY")


def test_spec_never_appends_raw_hook_tuples():
    src = SPEC.read_text(encoding="utf-8")
    assert not re.search(r"a\.(datas|binaries)\s*\+=\s*collect_", src)
    assert "_as_toc(collect_data_files" in src and "_as_toc(collect_dynamic_libs" in src


def test_optional_hiddenimports_empty_without_pywebview(monkeypatch):
    ns = _load_helpers()
    import importlib.util
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: None)
    assert ns["_optional_desktop_hiddenimports"]() == []


def test_optional_hiddenimports_with_pywebview(monkeypatch):
    ns = _load_helpers()
    import importlib.util
    present = {"webview", "clr_loader", "bottle"}
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: object() if name in present else None)
    mods = ns["_optional_desktop_hiddenimports"]()
    assert "webview.platforms.edgechromium" in mods and "clr_loader" in mods and "clr" not in mods


def test_real_pyinstaller_hook_output_is_two_tuples_and_normalizes_after_conversion(tmp_path):
    """With the real PyInstaller installed, prove the conversion feeds normalize_toc cleanly."""
    pytest.importorskip("PyInstaller")
    from PyInstaller.building.datastruct import normalize_toc
    ns = _load_helpers()
    f = tmp_path / "x.bin"; f.write_bytes(b"x")
    raw = [(str(f), "pkg")]                       # 2-tuple hook format (what broke v1.4.1)
    with pytest.raises(ValueError):
        normalize_toc(raw)
    assert normalize_toc(ns["_as_toc"](raw, "DATA"))
