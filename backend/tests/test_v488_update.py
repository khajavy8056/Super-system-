# -*- coding: utf-8 -*-
"""build-488 — سیستم به‌روزرسانی مستقل از License (§۴۱–۴۴).

منبع انتشار: مخزن عمومی ``khajavy8056/Rasasys`` (فقط فایل نصبی؛ مالک بسته‌ها را
خودش آنجا می‌گذارد — این سرویس فقط «تشخیص نسخهٔ جدید + اطلاع‌رسانی» است).
"""
from __future__ import annotations

import json

from app import BUILD, __version__
from app.services import updater


def test_default_channel_is_public_release_repo():
    """منبع پیش‌فرض: khajavy8056/Rasasys — نه مخزن سورس (§۴۱)."""
    assert updater.GITHUB_REPO == "khajavy8056/Rasasys"
    assert "Rasasys" in updater.GITHUB_RELEASES
    assert "Super-system" not in updater.GITHUB_REPO


def test_current_version_carries_build_number():
    """نسخهٔ فعلی از اطلاعات داخلی خود برنامه (§۴۱) — با Build («عدد سوم»)."""
    tag = updater.current_release_tag()
    assert tag.startswith(__version__)
    assert f"build.{BUILD // 100}" in tag


def test_version_compare_is_build_aware():
    assert updater.is_newer("1.0.0-build.489", "1.0.0-build.488")
    assert not updater.is_newer("1.0.0-build.488", "1.0.0-build.488")
    assert not updater.is_newer("1.0.0-build.487", "1.0.0-build.488")
    assert updater.is_newer("1.1.0-build.400", "1.0.0-build.488")
    assert not updater.is_newer("1.0.0", "1.0.0-build.488")


class _FakeResp:
    def __init__(self, data, status=200):
        self._data = data
        self.status_code = status
        self.text = ""

    def json(self):
        return self._data


def test_platform_asset_filtering(monkeypatch):
    """§۴۳ — ویندوز فقط Setup/zip، اندروید فقط APK؛ فایل پلتفرم اشتباه دیده نمی‌شود."""
    releases = [{
        "tag_name": "v1.0.0-build.490", "name": "x", "body": "", "published_at": "2026-10-02",
        "html_url": "https://example/r",
        "assets": [
            {"name": "RasaSystemMobile-1.0.0.apk", "browser_download_url": "https://a/app.apk", "size": 1},
            {"name": "sha256-RasaSystemMobile-1.0.0.apk.txt", "browser_download_url": "https://a/s", "size": 1},
        ],
    }, {
        "tag_name": "v1.0.0-build.489", "name": "y", "body": "", "published_at": "2026-10-01",
        "html_url": "https://example/r2",
        "assets": [
            {"name": "RasaSystem-1.0.0-build.489-Setup.exe", "browser_download_url": "https://a/setup.exe", "size": 2},
            {"name": "sha256-RasaSystem-1.0.0-build.489-Setup.exe.txt", "browser_download_url": "https://a/s2", "size": 1},
        ],
    }]

    monkeypatch.setattr(updater.httpx, "get", lambda *a, **k: _FakeResp(releases))

    win = updater.GitHubChannel(platform="windows").fetch_latest()
    assert win.version.endswith("489"), "ویندوز باید نسخهٔ ویندوزی را بردارد، نه APK را"
    assert win.asset_name and win.asset_name.endswith(".exe")

    droid = updater.GitHubChannel(platform="android").fetch_latest()
    assert droid.version.endswith("490")
    assert droid.asset_name.endswith(".apk")


def test_check_reports_update_available(monkeypatch):
    class _Ch(updater.UpdateChannel):
        def fetch_latest(self, timeout=8.0):
            return updater.ReleaseInfo(version="1.0.0-build.999", name="n",
                                       asset_name="x.exe", asset_url="https://a/x")
    out = updater.check_for_update(_Ch(), current="1.0.0-build.488")
    assert out["status"] == "UPDATE_AVAILABLE" and out["update_available"]
    out2 = updater.check_for_update(_Ch(), current="1.0.0-build.999")
    assert out2["status"] == "UP_TO_DATE" and not out2["update_available"]


def test_check_update_endpoint_any_user_and_notify_once(client, auth_headers):
    """§۴۲ — بررسی به‌روزرسانی وابسته به License/دسترسی خاص نیست؛ §۴۴ — اعلان یک بار."""
    from tests.test_v488_people import _login, _mkuser
    _mkuser(client, auth_headers, "upd_cas", roles=["Cashier"])
    cas = _login(client, "upd_cas", "pass1234")

    class _Ch(updater.UpdateChannel):
        def fetch_latest(self, timeout=8.0):
            return updater.ReleaseInfo(version="1.0.0-build.999", name="n",
                                       asset_name="x.exe", asset_url="https://a/x")

    import app.routers.system as sysr
    real = updater.channel_from_settings
    updater.channel_from_settings = lambda db: _Ch()
    try:
        r = client.get("/api/system/update/check", headers=cas)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["update_available"] and body["notify"] is True  # بار اول
        assert client.post("/api/system/update/ack", headers=cas).status_code == 200
        r2 = client.get("/api/system/update/check", headers=cas).json()
        assert r2["notify"] is False, "همان نسخه نباید دوباره اعلان شود (§۴۴)"
    finally:
        updater.channel_from_settings = real


def test_platform_query_filters_endpoint(client, auth_headers, monkeypatch):
    """§۴۳ — android فقط APK می‌بیند."""
    releases = [{
        "tag_name": "v1.0.0-build.490", "name": "x", "body": "", "published_at": "2026-10-02",
        "html_url": "https://example/r",
        "assets": [{"name": "RasaSystemMobile-1.0.0.apk", "browser_download_url": "https://a/app.apk", "size": 1}],
    }]
    monkeypatch.setattr(updater.httpx, "get", lambda *a, **k: _FakeResp(releases))
    body = client.get("/api/system/update/check?platform=android", headers=auth_headers).json()
    assert body["platform"] == "android"
    assert (body.get("latest") or {}).get("asset_name", "").endswith(".apk")
