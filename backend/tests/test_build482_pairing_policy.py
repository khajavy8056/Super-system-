"""بیلد ۴۸۲ — pairing permanence + «دسترسی فقط به صورت بومی».

ریشهٔ مشکلی که این تست‌ها نگه می‌دارند: گوشی جفت‌شده نباید هرگز دوباره بارکد
اسکن کند؛ همان کاربر/رمز باید بیرون از شبکه هم (طبق سیاست) وارد شود و سیاست
«فقط بومی» باید از رایانه به گوشی برسد.
"""

from __future__ import annotations

from pathlib import Path


def _login(client, username, password):
    r = client.post("/api/auth/login", data={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_new_user_defaults_to_local_only_and_admin_can_toggle(client, auth_headers):
    r = client.post("/api/users", json={"username": "u_local1", "password": "secret99",
                                        "full_name": "کاربر تست", "roles": ["Cashier"]},
                    headers=auth_headers)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["local_only"] is True          # پیش‌فرض: فقط داخل شبکهٔ فروشگاه

    r = client.patch(f"/api/users/{body['id']}", json={"local_only": False}, headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["local_only"] is False      # ادمین تیک را بردارد → کار بیرون از شبکه آزاد

    r = client.get("/api/users", headers=auth_headers)
    row = next(u for u in r.json() if u["username"] == "u_local1")
    assert row["local_only"] is False


def test_me_exposes_policy_for_phone_cache(client, auth_headers):
    r = client.get("/api/auth/me", headers=auth_headers)
    assert r.status_code == 200
    me = r.json()
    assert me["is_admin"] is True               # ادمین اصلی → دسترسی مستقل پیش‌فرض روشن
    assert isinstance(me["local_only"], bool)

    client.post("/api/users", json={"username": "u_local2", "password": "secret99",
                                    "roles": ["Cashier"]}, headers=auth_headers)
    me2 = client.get("/api/auth/me", headers=_login(client, "u_local2", "secret99")).json()
    assert me2["is_admin"] is False
    assert me2["local_only"] is True


def test_known_device_remints_token_with_password_only(client, auth_headers):
    # ادمین یک بار دستگاه را جفت می‌کند
    r = client.post("/api/mobile/pair/token",
                    json={"name": "گوشی فروشگاه", "days": 365, "device_id": "dev-known-1"},
                    headers=auth_headers)
    assert r.status_code == 200, r.text
    assert r.json()["device_id"] == "dev-known-1"

    client.post("/api/users", json={"username": "u_local3", "password": "secret99",
                                    "roles": ["Cashier"]}, headers=auth_headers)
    cashier = _login(client, "u_local3", "secret99")

    # کاربر عادی، بدون «settings.manage»، برای همان دستگاه آشنا دوباره توکن می‌گیرد
    # (پس از انقضای توکن/ری‌استارت/تغییر IP) — بدون نیاز به بارکد یا کد جفت‌شدن.
    r = client.post("/api/mobile/pair/token",
                    json={"name": "گوشی فروشگاه", "days": 365, "device_id": "dev-known-1"},
                    headers=cashier)
    assert r.status_code == 200, r.text
    assert r.json()["device_id"] == "dev-known-1"
    assert r.json()["token"]

    # اما معرفی «دستگاه تازه» همچنان فقط با دسترسی مدیر انجام می‌شود.
    r = client.post("/api/mobile/pair/token",
                    json={"name": "گوشی دیگر", "days": 365, "device_id": "dev-brand-new"},
                    headers=cashier)
    assert r.status_code == 403


def test_sync_pull_carries_users_without_password_hashes(client, auth_headers):
    client.post("/api/users", json={"username": "u_local4", "password": "secret99",
                                    "full_name": "همگام", "roles": ["Cashier"],
                                    "local_only": False}, headers=auth_headers)
    r = client.post("/api/mobile/sync",
                    json={"device_id": "dev-known-1", "push": [], "pull": True, "limit": 2000},
                    headers=auth_headers)
    assert r.status_code == 200, r.text
    users = r.json()["pull"]["users"]
    assert users, "pull must include the users table so offline sign-in policy stays current"
    hit = next(u for u in users if u["username"] == "u_local4")
    assert hit["local_only"] is False
    assert hit["is_active"] is True
    assert "Cashier" in hit["roles"]
    for banned in ("password_hash", "pass_hash", "password", "hash"):
        assert banned not in hit


# --- Android/Windows sources (Java cannot run here; pin the shipped code) --------
JAVA = Path(__file__).resolve().parents[2] / "mobile-android" / "app" / "src" / "main" / "java" / "ir" / "khajavy" / "supermarket"
FRONT = Path(__file__).resolve().parents[2] / "frontend"


def test_android_offline_signin_needs_no_rescan_and_keeps_pairing():
    login = (JAVA / "LoginActivity.java").read_text(encoding="utf-8")
    # همان کاربر/رمز بدون رایانه: ورود آفلاین با حساب ذخیره‌شده
    assert "offlineLogin" in login and 'Local.handle("POST", "/auth/login"' in login
    # تغییر IP/راه‌اندازی رایانه: بازیابی خودکار از راه کلید اتصال — بدون بارکد
    assert "Discovery.find" in login and 'Prefs.get("link_key"' in login
    # توکن دستگاه برای دستگاه آشنا تازه می‌شود، با همان device_id (بدون QR)
    assert 'dev.put("device_id", knownId)' in login and "/mobile/pair/token" in login
    # سیاست «دسترسی فقط به صورت بومی»
    assert "policyAllows" in login and "local_only" in login and "is_admin" in login
    # حساب روی گوشی ذخیره می‌شود تا ورود بعدی مستقل با همان رمز ممکن باشد
    assert "cacheMe" in login
    local = (JAVA / "Local.java").read_text(encoding="utf-8")
    assert "cacheUser" in local and 'sha(un + "|" + password)' in local
    db = (JAVA / "Db.java").read_text(encoding="utf-8")
    assert "putUserMeta" in db and "local_only" in db and "from_pc" in db
    # رمزسنج ذخیره‌شدهٔ گوشی نباید با pull پاک شود
    meta = db.split("putUserMeta", 2)[1]
    assert 'up.put("pass_hash"' not in meta, "the sync pull must never touch the cached password verifier"


def test_android_updates_run_in_background_without_page_refresh():
    app = (JAVA / "AppActivity.java").read_text(encoding="utf-8")
    # ضربان قلب ۲۰ ثانیه‌ای دیگر صفحه را بازسازی نمی‌کند (ریشهٔ «هی صفحه ریفرش می‌شه»)
    assert "quietRefresh" in app and "Ui.interacting()" in app
    assert "s.autoRefresh()) s.refresh()" not in app, "the heartbeat must not rebuild the current screen"
    ins = (JAVA / "InsightScreens.java").read_text(encoding="utf-8")
    # به‌روزرسانی بی‌صدا: محتوای فعلی تا رسیدن دادهٔ تازه می‌ماند
    assert "@Override public void refresh() { fetch(); }" in ins


def test_android_button_rows_wrap_instead_of_breaking_the_page():
    ui = (JAVA / "Ui.java").read_text(encoding="utf-8")
    assert "class Flow extends ViewGroup" in ui and "public static Flow wrap(" in ui
    screens = (JAVA / "Screens.java").read_text(encoding="utf-8")
    assert "Ui.wrap(c)" in screens, "the shared tabs() must use the wrapping flow row"
    ins = (JAVA / "InsightScreens.java").read_text(encoding="utf-8")
    assert "Ui.Flow gl = Ui.wrap(c)" in ins, "the insights group strip must wrap on every screen size"
    css = (FRONT / "desktop.css").read_text(encoding="utf-8")
    assert ".ins-groups" in css and "flex-wrap: wrap" in css


def test_windows_users_ui_has_local_only_checkbox():
    appjs = (FRONT / "app.js").read_text(encoding="utf-8")
    assert "u-local-only" in appjs and "local_only" in appjs and "دسترسی فقط به صورت بومی" in appjs
    launcher = (Path(__file__).resolve().parents[2] / "installer" / "windows" / "run_supermarket.py").read_text(encoding="utf-8")
    assert 'os.environ.get("SUPERMARKET_KIOSK", "1")' in launcher, "the POS program must open full screen by default"
