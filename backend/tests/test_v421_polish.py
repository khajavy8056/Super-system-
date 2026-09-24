"""v4.2.1 — the owner's follow-up round, locked down as tests.

  1. the false «Setup.exe بدون مدل» destruction of a REAL 1,153.8 MB build
     (verifier searched the wrong place for the Inno signature) — covered in
     test_v42_model_presence.py (real-layout pass + exit-code split);
  2. Android: model download must SHOW progress and SURVIVE app close
     (foreground service + live notification + fixed listener overwrite);
  3. the model is branded «مدل تخصصی سوپری‌من» / «سوپری‌من لایت» everywhere
     the user looks — backend registry, Windows panel, Android;
  4. a proper model icon (Android drawable + web /icons/model-192.png);
  5. chat surface upgraded on BOTH platforms;
  6. the Windows panel wears the Android palette;
  7. the builder streams the model download live (no dead console).
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

ANDROID = ROOT / "mobile-android" / "app" / "src" / "main" / "java" / "ir" / "khajavy" / "supermarket"


# ---------------------------------------------------------------- 1. branding
def test_registry_display_names():
    from app.services.business_brain import model_registry as reg
    q4 = reg.get("qwen2.5-1.5b-instruct-q4_k_m")
    q3 = reg.get("qwen2.5-1.5b-instruct-q3_k_m")
    assert q4.display_name == "مدل تخصصی سوپری‌من"
    assert q3.display_name == "سوپری‌من لایت"
    assert reg.display_name("qwen2.5-1.5b-instruct-q4_k_m") == "مدل تخصصی سوپری‌من"
    assert reg.display_name("unknown-id") == "unknown-id"
    payload = {m["model_id"]: m for m in reg.registry_payload()}
    assert payload["qwen2.5-1.5b-instruct-q3_k_m"]["display_name"] == "سوپری‌من لایت"


def test_manager_status_exposes_active_name():
    import inspect

    from app.services.business_brain import model_manager as mm
    src = inspect.getsource(mm.ModelManager.status)
    assert "active_name" in src
    assert "display_name" in src


def test_android_model_cards_use_brand_not_tech_id():
    t = (ANDROID / "BrainModel.java").read_text(encoding="utf-8")
    assert '"مدل تخصصی سوپری‌من"' in t and '"سوپری‌من لایت"' in t
    screens = (ANDROID / "BrainScreens.java").read_text(encoding="utf-8")
    assert "s.label()" in screens                     # card title is the brand
    assert "Ui.text(c, s.id, 13.5f" not in screens    # the raw id is gone as a title


def test_web_panel_uses_branded_names():
    brain = (ROOT / "frontend" / "brain.js").read_text(encoding="utf-8")
    assert "مدل تخصصی سوپری‌من" in brain and "سوپری‌من لایت" in brain
    assert "BRAND" in brain
    insights = (ROOT / "frontend" / "insights.js").read_text(encoding="utf-8")
    assert "active_name" in insights                  # prefers the server's brand


# ---------------------------------------------------------------- 2. Android download UX
def test_foreground_download_service_exists_and_registered():
    svc = (ANDROID / "BrainModelService.java").read_text(encoding="utf-8")
    assert "extends Service" in svc and "startForeground" in svc
    assert "setProgress(100, pct, false)" in svc      # live progress notification
    manifest = (ROOT / "mobile-android" / "app" / "src" / "main" / "AndroidManifest.xml").read_text(encoding="utf-8")
    assert 'android:name=".BrainModelService"' in manifest
    assert 'foregroundServiceType="dataSync"' in manifest
    assert "FOREGROUND_SERVICE_DATA_SYNC" in manifest  # permission (already there)


def test_download_starts_service_and_notifies_progress():
    t = (ANDROID / "BrainModel.java").read_text(encoding="utf-8")
    assert "BrainModelService.start(appCtx, s.id)" in t
    assert "BrainModelService.progress(ac, id, pct, done, total" in t
    assert "BrainModelService.stop(c)" in t           # anchor released on every exit


def test_listener_overwrite_bug_fixed():
    """v4.2: two model cards, one static listener slot → the second card's
    registration silently killed the first card's progress bar («هیچ خط
    پیشرفت نمیاد»). Now: named listeners in a map."""
    t = (ANDROID / "BrainModel.java").read_text(encoding="utf-8")
    assert "ConcurrentHashMap" in t
    assert 'listen(String owner, Listener l)' in t
    screens = (ANDROID / "BrainScreens.java").read_text(encoding="utf-8")
    assert 'BrainModel.listen("card:" + s.id' in screens


# ---------------------------------------------------------------- 3. icon + chat
def test_model_icon_ships_on_both_platforms():
    d = ROOT / "mobile-android" / "app" / "src" / "main" / "res" / "drawable" / "ic_model.png"
    assert d.exists() and d.stat().st_size > 10_000    # a real icon, not a stub
    web = ROOT / "frontend" / "icons" / "model-192.png"
    assert web.exists() and web.stat().st_size > 5_000
    assert (ROOT / "frontend" / "icons" / "model-512.png").exists()


def test_android_uses_the_icon_and_animated_typing():
    screens = (ANDROID / "BrainScreens.java").read_text(encoding="utf-8")
    assert "R.drawable.ic_model" in screens
    assert "thinkingBubble" in screens                # animated typing dots
    assert "مغز فروشگاه\"" in screens or "مغز فروشگاه" in screens


def test_web_chat_has_bubble_css_and_typing_animation():
    css = (ROOT / "frontend" / "styles.css").read_text(encoding="utf-8")
    assert ".brain-bubble" in css and ".brain-typing" in css
    assert "@keyframes brainDots" in css
    assert "linear-gradient(135deg, var(--primary), var(--primary2))" in css
    brain = (ROOT / "frontend" / "brain.js").read_text(encoding="utf-8")
    assert "typingBubble" in brain
    assert brain.count('src="/icons/model-192.png"') >= 3   # header + avatar + model card


# ---------------------------------------------------------------- 4. Windows theme = Android
def test_windows_panel_wears_the_android_palette():
    pro = (ROOT / "frontend" / "theme-pro.css").read_text(encoding="utf-8")
    base = (ROOT / "frontend" / "styles.css").read_text(encoding="utf-8")
    for css in (pro, base):
        # the Android Ui.java dark palette: bg/card/border + cobalt/violet
        assert "#030b1d" in css.lower() and "#091733" in css.lower()
        assert "#2563eb" in css.lower() and "#9654ff" in css.lower()
    assert "#f2f4ff" in pro.lower()                   # Android light bg


# ---------------------------------------------------------------- 5. builder UX
def test_builder_streams_model_download_live():
    ps = (ROOT / "installer" / "windows" / "builder-lib.ps1").read_text(encoding="utf-8-sig")
    assert "-Stream" in ps                            # live output switch
    assert "Write-Host \"  $line\"" in ps             # the streamed line
    assert "LastNativeExitCode" in ps                 # exit-code split
    assert "بررسی فایل نصب ناموفق بود ولی فایل حفظ شد" in ps   # keep on exit 2
    # the model step itself streams
    i = ps.find("prepare_windows_installer.py")
    assert "-Stream" in ps[i:i + 1200]


def test_download_manager_milestones_are_dense_enough():
    dm = (ROOT / "backend" / "app" / "services" / "business_brain" / "download_manager.py").read_text(encoding="utf-8")
    assert "8.0" in dm and "0.05" in dm               # 8s / 5% milestone cadence


# ---------------------------------------------------------------- 6. versions
def test_versions_consistent_with_backend():
    """Backend __init__.py and setup.iss must always carry the SAME version
    (checked against the live value, not a hardcoded one)."""
    from app import __version__
    assert (ROOT / "backend" / "app" / "__init__.py").read_text(
        encoding="utf-8").count(f'__version__ = "{__version__}"') == 1
    iss = (ROOT / "installer" / "windows" / "setup.iss").read_text(encoding="utf-8-sig")
    assert f'#define MyAppVersion "{__version__}"' in iss
