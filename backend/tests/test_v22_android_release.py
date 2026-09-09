"""v2.2 — Android-only release: stable signing key, notifications, sounds, redesigned shell."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ANDROID = ROOT / "mobile-android" / "app" / "src" / "main"
JAVA = ANDROID / "java" / "ir" / "khajavy" / "supermarket"


def test_signing_key_is_persistent_so_updates_install_over_old_versions():
    ks = ROOT / "mobile-android" / "keystore" / "supery-release.jks"
    assert ks.exists() and ks.stat().st_size > 1000
    build = (ROOT / "scripts" / "android" / "build-apk.sh").read_text(encoding="utf-8")
    assert "mobile-android/keystore/supery-release.jks" in build
    assert "installer/output/supermarket-release.jks" not in build
    # the keystore directory must not be ignored by git
    gi = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "keystore" not in gi and "*.jks" not in gi


def test_notifications_and_sounds_exist():
    manifest = (ANDROID / "AndroidManifest.xml").read_text(encoding="utf-8")
    assert "android.permission.POST_NOTIFICATIONS" in manifest
    assert "RECEIVE_BOOT_COMPLETED" in manifest and ".Notify$Checker" in manifest
    notify = (JAVA / "Notify.java").read_text(encoding="utf-8")
    for k in ("NotificationChannel", "setInexactRepeating", "supportReply", "checkLocal", "expiringNames", "lowStockNames", "syncProblem"):
        assert k in notify, k
    sfx = (JAVA / "Sfx.java").read_text(encoding="utf-8")
    for k in ('"success"', '"add"', '"error"', '"void"', '"hold"', '"resume"', '"welcome"', "AudioTrack"):
        assert k in sfx, k
    sales = (JAVA / "SalesScreens.java").read_text(encoding="utf-8")
    assert 'Sfx.play("success")' in sales and 'Sfx.play("void")' in sales and 'Sfx.play("hold")' in sales
    screens = (JAVA / "Screens.java").read_text(encoding="utf-8")
    assert 'case "notifications":' in screens


def test_redesigned_shell_matches_reference_mockups():
    ui = (JAVA / "Ui.java").read_text(encoding="utf-8")
    for k in ("gradient(", "surface(", "hero(", "tile(", "spark(", "avatar(", "cta(", "pill("):
        assert k in ui, k
    assert "0xFF1B2536" in ui  # deep navy dark background
    app = (JAVA / "AppActivity.java").read_text(encoding="utf-8")
    assert "openGroups" in app and "Ui.avatar(" in app and "android.widget.Switch" in app
    for grp in ("فروش و مشتری", "فاکتورها", "کالا و موجودی", "جشنواره و کوپن"):
        assert grp in app, grp
    assert "خروج از حساب" in app
    for tab in ("خانه", "فروش", "کالاها", "انبار", "بیشتر"):
        assert f'"{tab}"' in app
    home = (JAVA / "Screens.java").read_text(encoding="utf-8")
    assert "Ui.hero(c)" in home and "Ui.tile(c" in home and "حالت مستقل" in home
    pos = (JAVA / "SalesScreens.java").read_text(encoding="utf-8")
    assert "Ui.cta(c, \"پرداخت" in pos and "Ui.pill(c" in pos
