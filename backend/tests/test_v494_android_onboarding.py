"""Regression guards for the Android first-run startup path in build 494."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
ANDROID = ROOT / "mobile-android" / "app" / "src" / "main"
JAVA = ANDROID / "java" / "ir" / "khajavy" / "supermarket"


def test_first_run_opens_after_local_schema_not_after_catalogue_timer():
    setup = (JAVA / "SetupActivity.java").read_text(encoding="utf-8")
    app = (JAVA / "AppActivity.java").read_text(encoding="utf-8")
    db = (JAVA / "Db.java").read_text(encoding="utf-8")
    recovery = (JAVA / "InstallRecovery.java").read_text(encoding="utf-8")
    stock = (JAVA / "StockScreens.java").read_text(encoding="utf-8")
    sales = (JAVA / "SalesScreens.java").read_text(encoding="utf-8")
    manifest = (ANDROID / "AndroidManifest.xml").read_text(encoding="utf-8")

    # The former 45-minute wait and foreground installer are the reported startup blocker.
    assert "45L * 60L * 1000L" not in setup
    assert "InstallService.start" not in setup
    assert "<service android:name=\".InstallService\"" not in manifest
    assert "Db.db();" in setup
    assert "loadingScreen(() -> finishSetup(true))" in setup

    # The optional catalogue starts only after setup and authentication.
    assert "Api.bg(() -> {" in app and "Db.bootstrap(appContext)" in app
    assert app.index("if (Session.expired())") < app.index("Db.bootstrap(appContext)")
    assert '"0".equals(starterChoice)' in db
    assert 'Prefs.set("install_t0", "")' in recovery
    assert 'Prefs.set("setup_done", "1")' in recovery
    assert 'Prefs.set("first_loading_done", "1")' in recovery
    assert "کاتالوگ خالی انتخاب شده است" in stock
    assert "فهرست پیش‌فرض هنوز در پس‌زمینه" in sales
    assert "active instanceof StockScreens.Products" in app


def test_setup_catalogue_count_matches_the_bundled_asset():
    setup = (JAVA / "SetupActivity.java").read_text(encoding="utf-8")
    catalog = ANDROID / "assets" / "default_catalog.csv"
    rows = len(catalog.read_text(encoding="utf-8").splitlines()) - 1
    assert rows == 16953
    assert "۱۶٬۹۵۳ کالا" in setup


def test_android_is_native_and_does_not_depend_on_the_removed_installer_service():
    manifest = (ANDROID / "AndroidManifest.xml").read_text(encoding="utf-8")
    source = "\n".join(path.read_text(encoding="utf-8") for path in JAVA.glob("*.java"))
    readme = (ROOT / "mobile-android" / "README.md").read_text(encoding="utf-8")
    assert "android.webkit.WebView" not in source
    assert "new WebView" not in source
    assert "InstallService" not in source
    assert ".InstallService" not in manifest
    assert "از WebView" in readme
