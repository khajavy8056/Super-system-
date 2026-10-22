"""Desktop UI dependencies — build-498: the Windows app is a NATIVE Qt (PySide6)
application. The old WebView2/pywebview shell is gone entirely (دستورالعمل §۶):
no browser, no embedded web renderer, no cookies, no web cache.
"""
from __future__ import annotations

import importlib.util
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_core_requirements_do_not_pin_desktop_ui_libs():
    core = (ROOT / "backend" / "requirements.txt").read_text(encoding="utf-8")
    assert not re.search(r"^\s*pywebview", core, re.M)
    assert not re.search(r"^\s*pythonnet", core, re.M)
    assert not re.search(r"^\s*PySide6", core, re.M), "UI نیتیو فقط در requirements-desktop است"
    desktop = (ROOT / "backend" / "requirements-desktop.txt").read_text(encoding="utf-8")
    assert re.search(r"^\s*PySide6", desktop, re.M), "رابط نیتیو ویندوز = PySide6"
    assert "pywebview" not in desktop and "pythonnet" not in desktop


def test_builder_installs_the_native_ui_requirements():
    ps = (ROOT / "installer" / "windows" / "builder-lib.ps1").read_text(encoding="utf-8-sig")
    assert "requirements-desktop.txt" in ps
    assert "--retries" in ps and "--timeout" in ps
    assert "--find-links" in ps and "wheels" in ps
    assert ps.count("--index-url") >= 1 and "runflare" in ps
    block = ps[ps.index("# A desktop build without"): ps.index("# A desktop build without") + 650]
    assert "required desktop shell" in block
    assert "try {" not in block and "catch" not in block
    assert "$Script:NativeWindow = $true" in block


def test_launcher_opens_the_native_app_and_never_a_webview(monkeypatch, tmp_path):
    """When the native UI package cannot import, the launcher fails loudly with
    repair instructions — it never degrades to a browser (no fallback)."""
    import builtins
    import logging

    spec = importlib.util.spec_from_file_location("run_supermarket", ROOT / "installer" / "windows" / "run_supermarket.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    real_import = builtins.__import__

    def fake_import(name, *a, **k):
        if name == "desktop.main" or name.startswith("desktop."):
            raise ModuleNotFoundError("No module named 'desktop'")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    ok = mod.open_native_app(tmp_path, logging.getLogger("t"))
    assert ok is False  # repair instructions; never a browser/webview fallback
