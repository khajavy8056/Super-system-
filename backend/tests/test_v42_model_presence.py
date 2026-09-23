"""v4.2 «مدل کجاست؟» — regression tests: the model must really be there.

Owner complaints this suite locks down:
  * a 56 MB Setup.exe shipped with no model inside  -> verify_setup must FAIL it
  * the brain was «در دسترس نیست» after install     -> autostart + live-status
  * cloud/GPT settings still visible                -> none left in the frontend
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))          # for scripts.model.verify_setup


# ---------------------------------------------------------------- helpers
def _write_iss(tmp_path: Path, model_id: str, gguf_bytes: int) -> Path:
    installer_dir = tmp_path / "installer" / "windows"
    model_dir = installer_dir / "model" / model_id
    model_dir.mkdir(parents=True)
    (installer_dir / "model_payload.iss").write_text(
        f'[Files]\nSource: "model\\{model_id}\\{model_id}.gguf"; '
        f'DestDir: "{{userappdata}}\\SupermarketSystem\\models\\{model_id}"; '
        "Flags: ignoreversion\n", encoding="utf-8")
    gguf = model_dir / f"{model_id}.gguf"
    gguf.write_bytes(b"\0" * gguf_bytes)
    (model_dir / "seed.json").write_text(
        json.dumps({"model_id": model_id, "sha256": "a" * 64}), encoding="utf-8")
    return installer_dir


def _write_setup(tmp_path: Path, mb: float, with_marker: bool = True) -> Path:
    """Real Inno layout (v4.2.1): MZ stub PE, then the 64-byte 'Inno Setup Setup
    Data (x.y.z)' record at the START of the embedded setup-0 block — several
    hundred KiB into the file, NOT at the end (that v4.2.0 mistake destroyed
    the owner's real 1,153.8 MB Setup.exe after 8 minutes of ISCC compression)."""
    setup = tmp_path / "Setup.exe"
    stub = b"MZ" + b"x" * 700_000                      # ~the Inno stub PE size
    sig = (b"Inno Setup Setup Data (6.7.0)" + b"\x00" * 64)[:64]
    body = b"z" * max(0, int(mb * 1e6) - len(stub) - 64)
    blob = (stub + sig + body) if with_marker else (b"MZ" + b"x" * int(mb * 1e6))
    setup.write_bytes(blob)
    return setup


# ---------------------------------------------------------------- verify_setup
def test_verify_setup_passes_with_embedded_model(tmp_path):
    from scripts.model import verify_setup as vs
    installer_dir = _write_iss(tmp_path, "test-model-q4", gguf_bytes=100 * 1_000_000)
    setup = _write_setup(tmp_path, mb=98)                      # ≈ the GGUF, not 56 MB
    ok, problems, _info, _code = vs.verify(setup, installer_dir)
    assert ok, problems


@pytest.mark.parametrize("mb", [56, 59])                        # the owner's real case
def test_verify_setup_rejects_modelless_setup(tmp_path, mb):
    from scripts.model import verify_setup as vs
    installer_dir = _write_iss(tmp_path, "test-model-q4", gguf_bytes=100 * 1_000_000)
    setup = _write_setup(tmp_path, mb=mb)
    ok, problems, _info, _code = vs.verify(setup, installer_dir)
    assert not ok
    assert any("مدل" in p for p in problems)


def test_verify_setup_rejects_missing_payload(tmp_path):
    from scripts.model import verify_setup as vs
    installer_dir = tmp_path / "installer" / "windows"
    installer_dir.mkdir(parents=True)                           # no model_payload.iss
    setup = _write_setup(tmp_path, mb=56)
    ok, problems, _info, _code = vs.verify(setup, installer_dir)
    assert not ok and problems


def test_verify_setup_rejects_non_inno_file(tmp_path):
    from scripts.model import verify_setup as vs
    installer_dir = _write_iss(tmp_path, "test-model-q4", gguf_bytes=100 * 1_000_000)
    setup = _write_setup(tmp_path, mb=10, with_marker=False)   # tiny AND markerless
    ok, problems, info, code = vs.verify(setup, installer_dir)
    assert not ok
    assert any("مدل" in p or "Inno" in p for p in problems)


def test_verify_setup_cli_exit_codes(tmp_path, capsys, monkeypatch):
    from scripts.model import verify_setup as vs
    installer_dir = _write_iss(tmp_path, "test-model-q4", gguf_bytes=100 * 1_000_000)
    setup = _write_setup(tmp_path, mb=56)
    monkeypatch.chdir(ROOT)
    # exit 1 = model really missing → the builder deletes the setup
    assert vs.main([str(setup), "--installer-dir", str(installer_dir)]) == 1
    assert "PASS" not in capsys.readouterr().out


def test_verify_setup_marker_suspicion_keeps_file_exit_2(tmp_path):
    """v4.2.1: payload fine but no Inno signature → exit 2 (builder keeps the
    file), never exit 1 (which would delete an 8-minute ISCC build)."""
    from scripts.model import verify_setup as vs
    installer_dir = _write_iss(tmp_path, "test-model-q4", gguf_bytes=100 * 1_000_000)
    setup = _write_setup(tmp_path, mb=98, with_marker=False)
    ok, problems, info, code = vs.verify(setup, installer_dir)
    assert not ok and code == 2
    assert any("Inno" in p for p in problems)


def test_verify_setup_real_inno_layout_passes(tmp_path):
    """The owner's exact v4.2.0 failure: a REAL Inno Setup.exe (signature after
    the stub, ~700 KiB in) WITH the model inside must PASS."""
    from scripts.model import verify_setup as vs
    installer_dir = _write_iss(tmp_path, "test-model-q4", gguf_bytes=100 * 1_000_000)
    setup = _write_setup(tmp_path, mb=103.0)     # app + model, Inno layout
    ok, problems, _info, code = vs.verify(setup, installer_dir)
    assert ok, problems
    assert code == 0


# ---------------------------------------------------------------- builder wiring
def test_builder_gates_on_verify_setup():
    """The PowerShell builder must run verify_setup and delete a bad Setup.exe."""
    ps = (ROOT / "installer" / "windows" / "builder-lib.ps1").read_text(encoding="utf-8-sig")
    assert "verify_setup.py" in ps
    assert "Remove-Item $setup" in ps          # a modelless setup is thrown away, not shipped


# ---------------------------------------------------------------- brain autostart
def test_lifespan_starts_brain_autostart():
    import inspect

    from app.main import _start_brain_autostart, lifespan
    src = inspect.getsource(lifespan)
    assert "_start_brain_autostart" in src
    body = inspect.getsource(_start_brain_autostart)
    assert "adopt_preinstalled" in body        # adopts the installer's verified seed
    assert "get_runtime(db).load()" in body    # warm-starts llama-server
    assert "daemon=True" in body               # never blocks app startup


def test_autostart_kill_switch(monkeypatch):
    from app import main as app_main
    monkeypatch.setenv("SUPERMARKET_BRAIN_AUTOSTART", "0")
    app_main._start_brain_autostart()          # must return instantly, no thread
    assert True


# ---------------------------------------------------------------- cloud UI removal
def test_frontend_has_no_cloud_narrative_settings():
    js = (ROOT / "frontend" / "insights.js").read_text(encoding="utf-8")
    for gone in ("OpenRouter", "Groq", "Gemini", "narrative_provider", "narrative_base_url",
                 "narrative_api_key", "narrative_model"):
        assert gone not in js, f"{gone} must be gone from insights.js (v4.2: no cloud settings)"
    assert "/brain/model/status" in js          # replaced by the local-model status KPI


def test_brain_status_reports_backend_version():
    """status() must report the real product version, not a hardcoded 4.0.0."""
    import inspect

    from app.services.business_brain import brain as brain_mod
    from app import __version__
    cls = next(v for v in vars(brain_mod).values()
               if inspect.isclass(v) and "status" in vars(v)
               and v.__module__ == brain_mod.__name__)
    src = inspect.getsource(cls.status)
    assert '"4.0.0"' not in src
    assert "__version__" in src
    assert __version__ == "4.2.1"


# ---------------------------------------------------------------- Android sources
def test_android_chat_prefers_local_model():
    java = (ROOT / "mobile-android" / "app" / "src" / "main" / "java" / "ir" / "khajavy"
            / "supermarket" / "BrainScreens.java").read_text(encoding="utf-8")
    assert 'b.put("prefer_llm", true)' in java


def test_android_self_setup_on_first_open():
    model_java = (ROOT / "mobile-android" / "app" / "src" / "main" / "java" / "ir" / "khajavy"
                  / "supermarket" / "BrainModel.java").read_text(encoding="utf-8")
    screens_java = (ROOT / "mobile-android" / "app" / "src" / "main" / "java" / "ir" / "khajavy"
                    / "supermarket" / "BrainScreens.java").read_text(encoding="utf-8")
    assert "autoSetup" in model_java and "unmetered" in model_java
    assert "BrainModel.autoSetup(c)" in screens_java      # hooked into Center.load()
    assert "renderStandalone" in screens_java             # PC-off fallback screen


def test_android_version_follows_backend():
    """build.gradle derives versionName/versionCode from backend __init__.py —
    so bumping the backend to 4.2.0 automatically gives versionCode 40200."""
    gradle = (ROOT / "mobile-android" / "app" / "build.gradle").read_text(encoding="utf-8")
    assert 'versionName appVersion' in gradle and "versionCode code" in gradle
    assert (ROOT / "backend" / "app" / "__init__.py").read_text(
        encoding="utf-8").count('__version__ = "4.2.1"') == 1
    code = 4 * 10000 + 2 * 100 + 0
    assert code == 40200
