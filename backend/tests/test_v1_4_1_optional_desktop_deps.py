"""Desktop deps stay separate from headless server deps, but are REQUIRED in Windows builds.
The former optional browser fallback was explicitly removed by the desktop contract.
"""
from __future__ import annotations

import builtins
import importlib.util
import logging
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_core_requirements_do_not_pin_pywebview():
    core = (ROOT / "backend" / "requirements.txt").read_text(encoding="utf-8")
    assert not re.search(r"^\s*pywebview", core, re.M)
    assert not re.search(r"^\s*pythonnet", core, re.M)
    desktop = (ROOT / "backend" / "requirements-desktop.txt").read_text(encoding="utf-8")
    assert "pywebview" in desktop and 'sys_platform == "win32"' in desktop


def test_builder_requires_desktop_deps_with_mirrors():
    ps = (ROOT / "installer" / "windows" / "builder-lib.ps1").read_text(encoding="utf-8-sig")
    assert "requirements-desktop.txt" in ps
    assert "--retries" in ps and "--timeout" in ps
    assert "--find-links" in ps and "wheels" in ps
    assert ps.count("--index-url") >= 1 and "runflare" in ps
    block = ps[ps.index("# A desktop build without"): ps.index("# A desktop build without") + 650]
    assert "required desktop shell" in block
    assert "try {" not in block and "catch" not in block
    assert "$Script:NativeWindow = $true" in block



def test_launcher_reports_failure_when_pywebview_missing(monkeypatch, tmp_path):
    spec = importlib.util.spec_from_file_location("run_supermarket", ROOT / "installer" / "windows" / "run_supermarket.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    real_import = builtins.__import__

    def fake_import(name, *a, **k):
        if name == "webview":
            raise ModuleNotFoundError("No module named 'webview'")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    monkeypatch.delenv("SUPERMARKET_BROWSER_MODE", raising=False)
    ok = mod.open_native_window("http://127.0.0.1:1/", tmp_path, logging.getLogger("t"), lambda *_: None)
    assert ok is False  # caller shows repair instructions; never opens a browser
