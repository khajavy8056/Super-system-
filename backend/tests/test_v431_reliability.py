"""v4.3.1 — the reliability round, locked down as tests.

Owner round 9 (from his message + the parts of the screenshots he described):
  1. Android: after the model downloads + verifies, the ENGINE never starts —
     pressing start it just says «مدل در حال بارگذاریه» forever;
  2. a touched/corrupt model must never auto re-download; stop/resume must
     exist during download;
  3. Windows: a «لوما سرور» window appeared after install (llama-server's
     console) — the owner did not know what it was;
  4. the Windows chat hung on «در حال بررسی داده‌های فروشگاه…» forever;
  5. "Cannot set properties of null (setting 'innerHTML')" killed pages;
  6. the boot loading screen must prepare everything — after entering the app
     NO page should still be loading;
  7. the model must introduce itself fluently: who it is, what it can do, and
     that its creator is محمد صدیق خواجوی.
"""
from __future__ import annotations

import inspect
import io
import sys
import urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

ANDROID = ROOT / "mobile-android" / "app" / "src" / "main" / "java" / "ir" / "khajavy" / "supermarket"


# ---------------------------------------------------------------- Windows engine
def test_llama_server_console_window_is_hidden():
    """The «لوما سرور» black console the owner saw: llama-server must spawn
    with CREATE_NO_WINDOW on Windows — it is an internal engine, not a window."""
    from app.services.business_brain import runtime
    src = inspect.getsource(runtime.LlamaCppProvider.load)
    assert "CREATE_NO_WINDOW" in src
    assert 'os.name == "nt"' in src


def test_health_knows_loading_from_down():
    """503 + {"status":"loading model"} is PROGRESS (llama-server's own health
    contract), not failure — the old code spawned a duplicate server on the
    same port while the first was still loading."""
    from app.services.business_brain import runtime

    prov = runtime.LlamaCppProvider.__new__(runtime.LlamaCppProvider)
    prov.host, prov.port = "127.0.0.1", 18999

    def fake_urlopen(url, timeout=2.0):
        raise urllib.error.HTTPError(url, 503, "Service Unavailable", {}, io.BytesIO(b'{"status":"loading model"}'))

    orig = runtime.urllib.request.urlopen
    runtime.urllib.request.urlopen = fake_urlopen
    try:
        assert prov._health_status() == "loading"
        assert prov._healthy() is False
    finally:
        runtime.urllib.request.urlopen = orig


def test_chat_timeout_is_bounded():
    """180 s made the chat look dead on slow shop CPUs; 75 s bounds it and the
    planner then falls back to the deterministic answer with MODEL_FAILED."""
    from app.services.business_brain import runtime
    src = inspect.getsource(runtime.LlamaCppProvider.chat)
    assert "timeout=75" in src
    assert "timeout=180" not in src


def test_load_adopts_a_loading_server():
    from app.services.business_brain import runtime
    src = inspect.getsource(runtime.LlamaCppProvider.load)
    assert '== "loading"' in src            # wait for it instead of double-spawn


# ---------------------------------------------------------------- identity
def test_identity_answer_names_the_creator():
    from app.services.business_brain.planner import _identity_answer
    for q in ("تو کی هستی؟", "چه کارهایی می‌تونی انجام بدی؟", "سازندهٔ تو کیست؟", "اسمت چیه"):
        a = _identity_answer(q)
        assert a is not None, q
        assert "سوپری‌من" in a and "محمد صدیق خواجوی" in a
    # a shop question is NOT identity
    assert _identity_answer("فروش امروز چقدر بود؟") is None
    assert _identity_answer("موجودی شیر کاله چقدر مونده؟") is None


def test_system_prompt_carries_the_identity():
    from app.services.business_brain import prompts
    assert "محمد صدیق خواجوی" in prompts.SYSTEM_PROMPT
    assert "سوپری‌من" in prompts.SYSTEM_PROMPT
    android = (ANDROID / "BrainEngine.java").read_text(encoding="utf-8")
    assert "محمد صدیق خواجوی" in android and "سوپری‌من" in android


def test_planner_short_circuits_identity_without_the_model():
    from app.services.business_brain import planner
    src = inspect.getsource(planner.respond)
    assert "_identity_answer(question)" in src
    assert "prefer_llm = False" in src     # instant answer, no model wait


# ---------------------------------------------------------------- Windows UX
def test_boot_warms_the_data_during_loading():
    """The owner's rule: the boot loading PREPARES the environment — after it,
    no page starts from an empty loader. The warm cache is filled during boot
    and served one-shot by api()."""
    js = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    assert "async function warmup()" in js
    assert "await warmup();" in js                       # during boot, before showApp
    for key in ("/reports/dashboard", "/products?limit=1000", "/inventory/stock",
                "/reports/expiry", "/insights/summary", "/brain/status"):
        assert f'"{key}"' in js                          # the REAL view endpoints
    assert "hasOwnProperty.call(warm, path)" in js       # api() serves one-shot


def test_display_error_shield_exists():
    """'Cannot set properties of null (setting 'innerHTML')' must never leave a
    dead page: errors are caught, logged and reported once in Persian."""
    js = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    assert 'window.addEventListener("error"' in js
    assert "unhandledrejection" in js
    assert "خطای نمایشی" in js


# ---------------------------------------------------------------- Android engine
def test_android_engine_adopts_a_surviving_server():
    """A llama-server that outlived the app still owns port 8081 — the old code
    spawned a second one (bind fail → «کار نمی‌کنه»); now it is adopted."""
    t = (ANDROID / "BrainEngine.java").read_text(encoding="utf-8")
    assert "healthy(1200)" in t and "پذیرفته شد" in t


def test_android_engine_keeps_its_output_for_diagnosis():
    """The output drain discarded everything — a failure had NO reason. Now the
    last lines are kept and shown (Java-side + UI)."""
    eng = (ANDROID / "BrainEngine.java").read_text(encoding="utf-8")
    assert "pushTail" in eng and "public static String tail()" in eng
    assert "آخرین پیام موتور" in eng            # live progress + failure reason
    scr = (ANDROID / "BrainScreens.java").read_text(encoding="utf-8")
    assert "BrainEngine.tail()" in scr          # the FAILED card shows them


def test_android_engine_runs_the_ready_model():
    """start() used recommended() blindly — if the user had fetched the OTHER
    model, the engine refused although a model was ready."""
    m = (ANDROID / "BrainModel.java").read_text(encoding="utf-8")
    assert "public static Spec readySpec(Context c)" in m
    s = (ANDROID / "BrainScreens.java").read_text(encoding="utf-8")
    assert "BrainModel.readySpec(c)" in s       # engine start + standalone chat


def test_android_download_never_auto_repeats_and_resumes():
    """Corrupt/touched model → manual retry only; a paused download quietly
    continues on Wi-Fi; fresh installs are the only auto-download case."""
    m = (ANDROID / "BrainModel.java").read_text(encoding="utf-8")
    assert "anyState()" in m
    assert "PAUSED.equals(stateOf(s.id))" in m       # auto-resume branch
    s = (ANDROID / "BrainScreens.java").read_text(encoding="utf-8")
    assert "دریافت مجدد (فقط با خواست شما)" in s
    assert "خودکار تکرار نمی‌شود" in s


def test_android_engine_timeout_raised_with_progress():
    eng = (ANDROID / "BrainEngine.java").read_text(encoding="utf-8")
    assert "240_000" in eng      # was 120 s of silence on slow storage
    assert "ثانیه" in eng        # live progress notes while loading


# ---------------------------------------------------------------- versions
def test_versions_consistent():
    from app import __version__
    assert __version__ == "4.3.1"
    iss = (ROOT / "installer" / "windows" / "setup.iss").read_text(encoding="utf-8-sig")
    assert '#define MyAppVersion "4.3.1"' in iss
