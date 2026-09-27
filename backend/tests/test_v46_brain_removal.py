# -*- coding: utf-8 -*-
"""v4.6.0 — round-14 decisions, locked down as tests.

1. The Business Brain (local LLM) is REMOVED everywhere, by the owner's
   explicit decision: «بخش مدل زبانی (مغز فروشگاه) را کلا حذف کنید چه در
   اندروید چه ویندوز — فعلاً همان هوش فروشگاه کافی بود».
   - no brain code, routes, tables, model files, engine binaries or build steps
   - the migration history drops the six brain_* tables at head (reversible)
2. هوش فروشگاه is THE advisor now, and every suggestion explains itself so
   ANYONE understands it: a complete plain-language guide per kind
   (definition, why it matters here, exact steps, cost of ignoring, example)
   — «کاربر چه می‌داند مشتری VIP چیست، چه فرقی با سایر مشتریان دارد».
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

ANDROID = ROOT / "mobile-android" / "app" / "src" / "main" / "java" / "ir" / "khajavy" / "supermarket"
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"
INSTALLER = ROOT / "installer" / "windows"


# --------------------------------------------------------------- 1) removal
def test_no_brain_code_left():
    """The brain package, router, models and services are gone for good."""
    assert not (BACKEND / "app" / "services" / "business_brain").exists()
    assert not (BACKEND / "app" / "routers" / "brain.py").exists()
    assert not (BACKEND / "app" / "models" / "brain.py").exists()
    main_py = (BACKEND / "app" / "main.py").read_text(encoding="utf-8")
    assert "business_brain" not in main_py and "brain.router" not in main_py
    assert "_start_brain" not in main_py, "autostart/worker must be gone"
    models_init = (BACKEND / "app" / "models" / "__init__.py").read_text(encoding="utf-8")
    assert "Brain" not in models_init


def test_no_brain_routes_on_the_api(client, auth_headers):
    """Every /api/brain/* path must be gone (404), not 500 — a removed layer
    must never leave broken endpoints behind."""
    for path in ("/api/brain/chat", "/api/brain/status", "/api/brain/briefing",
                 "/api/brain/reminders/due", "/api/brain/decisions"):
        r = client.get(path, headers=auth_headers)
        assert r.status_code == 404, f"{path} must not exist"


def test_android_brain_is_gone():
    for name in ("BrainScreens.java", "BrainModel.java", "BrainModelService.java",
                 "BrainEngine.java", "BrainVoice.java", "ReminderRx.java"):
        assert not (ANDROID / name).exists(), f"{name} must be deleted"
    # no brain engine binaries ship in the APK any more
    jni = ROOT / "mobile-android" / "app" / "src" / "main" / "jniLibs"
    assert not jni.exists() or not any(jni.glob("*/*.so")), \
        "no libllamaserver.so may ship — the model/engine is removed"
    # navigation: no brain routes, no brain drawer entry
    screens = (ANDROID / "Screens.java").read_text(encoding="utf-8")
    assert '"brain"' not in screens and '"brainChat"' not in screens
    app = (ANDROID / "AppActivity.java").read_text(encoding="utf-8")
    assert "مغز فروشگاه" not in app and "BrainVoice" not in app and "BrainEngine" not in app
    manifest = (ROOT / "mobile-android" / "app" / "src" / "main" / "AndroidManifest.xml").read_text(encoding="utf-8")
    assert "RECORD_AUDIO" not in manifest, "the mic permission existed only for the brain's voice chat"
    assert "BrainModelService" not in manifest and "ReminderRx" not in manifest


def test_windows_installer_has_no_model_step():
    """The builder neither downloads a model nor verifies one — and the Inno
    script no longer includes any model payload."""
    lib = (INSTALLER / "builder-lib.ps1").read_text(encoding="utf-8-sig")
    assert "prepare_windows_installer" not in lib and "verify_setup" not in lib
    assert "آماده‌سازی مدل هوش محلی" not in lib
    iss = (INSTALLER / "setup.iss").read_text(encoding="utf-8-sig")
    assert "model_payload" not in iss
    assert not (ROOT / "scripts" / "model").exists(), "scripts/model/ is deleted"


def test_web_panel_has_no_brain_view():
    assert not (FRONTEND / "brain.js").exists()
    index = (FRONTEND / "index.html").read_text(encoding="utf-8")
    assert "brain.js" not in index
    for f in ("app.js", "insights.js"):
        src = (FRONTEND / f).read_text(encoding="utf-8")
        assert "/brain/" not in src and 'go("brain")' not in src, f"{f} still calls the brain API"


def test_migration_drops_brain_tables_and_is_reversible():
    """Head drops the six brain_* tables; one step down they come back;
    shop data is never touched."""
    import tempfile

    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, inspect

    d = tempfile.mkdtemp(prefix="v46mig_")
    url = f"sqlite:///{d}/x.db"
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")
    tables = set(inspect(create_engine(url)).get_table_names())
    for t in ("brain_decisions", "brain_followups", "brain_messages",
              "brain_policies", "brain_model_installs", "brain_memory_facts"):
        assert t not in tables, f"{t} must be dropped at head"
    command.downgrade(cfg, "-1")
    tables = set(inspect(create_engine(url)).get_table_names())
    for t in ("brain_decisions", "brain_followups"):
        assert t in tables, "downgrade recreates the brain tables (reversible)"
    command.upgrade(cfg, "head")
    tables = set(inspect(create_engine(url)).get_table_names())
    assert "brain_decisions" not in tables


def test_the_app_boots_without_the_brain(client, auth_headers):
    """The intelligence system — the product's advisor now — works fully."""
    r = client.post("/api/insights/run", headers=auth_headers)
    assert r.status_code == 200, r.text
    r = client.get("/api/insights?status=NEW&limit=5", headers=auth_headers)
    assert r.status_code == 200
    for item in r.json():
        assert "guide" in item, "every insight carries its plain-language guide"


# --------------------------------------------------------------- 2) guides
def test_every_kind_has_a_complete_guide():
    from app.services.insight_guides import _GUIDES, guide_for

    for kind in ("VIP", "CHURN", "CROSS_SELL", "EXPIRY_LADDER", "DEAD_STOCK", "VELOCITY",
                 "CASHFLOW", "PRICE_GAP", "LOSS_PREV", "SEASON", "SUPPLIER",
                 "BASKET_NUDGE", "VISIT_PATTERN"):
        g = guide_for(kind)
        assert g["what"] and len(g["what"]) > 80, f"{kind}: definition too thin"
        assert g["why"] and len(g["why"]) > 60, f"{kind}: why too thin"
        assert len(g["how"]) >= 3, f"{kind}: needs at least 3 concrete steps"
        assert g["if_ignored"] and g["example"], f"{kind}: consequences/example missing"


def test_the_vip_guide_answers_the_owners_exact_question():
    """«کاربر چه می‌داند مشتری VIP چیست، چه فرقی با سایر مشتریان دارد» — the
    guide must DEFINE the term and DIFFERENTIATE it from ordinary customers."""
    from app.services.insight_guides import guide_for

    g = guide_for("VIP")
    assert "VIP" in g["what"] or "مشتری بسیار مهم" in g["what"]
    assert "فرق" in g["what"], "must spell out the difference from ordinary customers"
    assert "معمولی" in g["what"]
    assert "پیامک" in " ".join(g["how"]), "the steps must be concrete (SMS, name, priority service)"


def test_unknown_kinds_get_an_honest_generic_guide():
    from app.services.insight_guides import guide_for

    g = guide_for("SOMETHING_PRO_NEW")
    assert g["what"] and g["how"] and len(g["how"]) >= 3
    assert "هیچ پیشنهادی از دادهٔ فروشگاه دیگری" in g["example"]


def test_guide_is_wired_into_both_uis():
    android = (ANDROID / "InsightScreens.java").read_text(encoding="utf-8")
    assert "guideCard" in android and "این پیشنهاد یعنی چه؟" in android
    assert "تعریف" in android and "اگر انجام نشود چه می‌شود؟" in android
    web = (FRONTEND / "insights.js").read_text(encoding="utf-8")
    assert "guideBlock" in web and "این پیشنهاد یعنی چه؟" in web
    assert "گام‌به‌گام" in web


def test_the_guides_are_deterministic_no_model_no_network():
    """The brain/LLM is gone: guides are static text — the module imports no
    app service, no model, no network; and the same kind always returns the
    exact same guide."""
    import app.services.insight_guides as ig

    src = Path(ig.__file__).read_text(encoding="utf-8")
    for banned in ("business_brain", "runtime", "requests", "urllib", "httpx", "get_runtime"):
        assert banned not in src, f"guides must stay deterministic — found {banned}"
    assert ig.guide_for("VIP") == ig.guide_for("VIP")
    assert ig.guide_for("VIP") != ig.guide_for("CHURN")
