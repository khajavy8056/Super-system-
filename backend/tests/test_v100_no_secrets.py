# -*- coding: utf-8 -*-
"""v1.0.0 (RASA) — هیچ رازی در مخزن نیست، و نبود راز هم «موفقیت جعلی» نمی‌سازد.

دو چیز اینجا قفل می‌شود:

۱) **راز در کد نیست.** ماژول `config.py` خودش می‌گوید «No secrets may ever be
   hard-coded in source»؛ ولی تا v4.8.0 توکن کانال پشتیبانی همان‌جا نوشته شده بود
   و در نتیجه در سورس عمومی، نصب‌کنندهٔ ویندوز و APK هم می‌رفت. این ماژول کل
   درخت سورس را اسکن می‌کند؛ هر کلید خصوصی، توکن شبیه‌به‌راز یا `Bearer`
   نوشته‌شده در کد، تست را می‌اندازد.

۲) **بدون توکن، درخواست گم نمی‌شود.** اگر نصب توکن نداشته باشد، تیکت ذخیره
   می‌شود و در صف «ارسال مجدد» می‌ماند (`FAILED` + `last_error`) — نه ۵۰۰، نه
   پیام موفقیت دروغین. دقیقاً همان قراردادی که مالک خواسته بود.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

from app.config import settings
from app.database import SessionLocal
from app.models import SupportTicket
from app.services import support as sup

REPO = Path(__file__).resolve().parents[2]

#: باینری/قفل‌فایل‌ها و سندهای تاریخی راز نیستند (sha512 و نام نسخه در آن‌ها است).
SKIP_SUFFIX = {".png", ".ico", ".jpg", ".jpeg", ".webp", ".woff2", ".gz", ".zip", ".apk",
               ".jks", ".db", ".pdf", ".lock", ".min.js", ".pyc", ".woff", ".ttf", ".otf"}
SKIP_PARTS = ("node_modules/", ".venv/", "releases/", "vendor/", "docs/screenshots/",
              "scripts/package-lock.json", "package-lock.json")

#: الگوهای راز: کلید خصوصی، توکن بلند، Bearer/Api-Key مقداردار.
PATTERNS = [
    ("private key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("long uppercase token", re.compile(r"\b[A-Z0-9]{28,}\b")),
    ("bearer literal", re.compile(r"[Bb]earer\s+[A-Za-z0-9._\-]{24,}")),
    ("api key literal", re.compile(r"(?i)(api[_-]?key|secret[_-]?key|access[_-]?token)\s*[:=]\s*[\"'][A-Za-z0-9._\-]{20,}[\"']")),
]
#: چیزهای بی‌خطر که شبیه راز هستند (نه توکن، نه کلید خصوصی).
ALLOW = re.compile(
    r"(CHANGE[_-]?ME|change-me|REPLACE|replace-with|your[_-]|example|placeholder|"
    r"test-secret-key|DEFAULT_SECRET_KEY|ABCDEFGHIJKLMNOPQRSTUVWXYZ|0123456789)"
)


def _tracked_text_files() -> list[Path]:
    out = subprocess.run(["git", "ls-files"], cwd=REPO, capture_output=True, text=True, check=True).stdout
    files = []
    for rel in out.splitlines():
        if any(rel.endswith(s) for s in SKIP_SUFFIX) or any(p in rel for p in SKIP_PARTS):
            continue
        p = REPO / rel
        if p.is_file():
            files.append(p)
    return files


def test_no_secret_literals_anywhere_in_the_source_tree():
    offenders = []
    for path in _tracked_text_files():
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for label, rx in PATTERNS:
            for m in rx.finditer(text):
                hit = m.group(0)
                if ALLOW.search(hit) or ALLOW.search(text[max(0, m.start() - 60):m.start()]):
                    continue
                offenders.append(f"{path.relative_to(REPO)}: {label}: {hit[:40]}…")
    assert not offenders, "secret-looking literals in the repo:\n  " + "\n  ".join(sorted(set(offenders)))


def test_support_relay_token_has_no_default():
    assert settings.SUPPORT_RELAY_TOKEN == "", "توکن کانال پشتیبانی نباید مقدار پیش‌فرض داشته باشد"
    src = (REPO / "backend" / "app" / "config.py").read_text(encoding="utf-8")
    line = [l for l in src.splitlines() if l.strip().startswith("SUPPORT_RELAY_TOKEN")][0]
    assert line.strip().endswith('""'), line


def test_relay_config_prefers_the_installation_over_the_environment(client):
    """اولویت: مقدار هر نصب (system_settings) → متغیر محیطی. تنظیمات عمومی است."""
    from app.models import SystemSetting
    with SessionLocal() as db:
        db.add(SystemSetting(key="support.relay_token", value="install-token-value",
                             description="test", is_secret=True))
        db.add(SystemSetting(key="support.relay_url", value="https://relay.example.test/v1",
                             description="test", is_secret=False))
        db.commit()
        try:
            url, token, _ = sup.relay_config(db)
            assert url == "https://relay.example.test/v1" and token == "install-token-value"
        finally:
            for key in ("support.relay_token", "support.relay_url"):
                row = db.execute(__import__("sqlalchemy").select(SystemSetting).where(SystemSetting.key == key)).scalar_one_or_none()
                if row is not None:
                    db.delete(row)
            db.commit()


def test_a_ticket_without_a_relay_channel_is_kept_and_queued_not_faked(client, auth_headers, monkeypatch):
    """هیچ توکنی نیست → تیکت ثبت می‌شود، در صف می‌ماند، و هیچ موفقیت جعلی نشان داده نمی‌شود."""
    monkeypatch.setattr(sup, "relay_config", lambda db: ("", "", ""))

    body = {"type": "QUESTION", "priority": "NORMAL", "subject": "تست صف بدون کانال",
            "description": "نصب هیچ توکن رله‌ای ندارد؛ درخواست باید ذخیره شود و برای ارسال مجدد در صف بماند."}
    r = client.post("/api/support/tickets", json=body, headers=auth_headers)
    assert r.status_code in (200, 201), r.text
    out = r.json()
    assert out["number"].startswith("TCK-")
    assert out["status"] == "FAILED", out           # «در انتظار ارسال مجدد» — نه SENT دروغین
    assert out.get("sent_at") in (None, ""), "تیکت ارسال‌نشده نباید زمان ارسال داشته باشد"

    with SessionLocal() as db:
        t = db.get(SupportTicket, out["id"])
        assert t is not None and t.status == "FAILED"
        from app.models import SyncJob
        from sqlalchemy import select
        job = db.execute(select(SyncJob).where(SyncJob.idempotency_key == f"ticket:{t.id}")).scalar_one_or_none()
        assert job is not None and job.status in ("PENDING", "RETRY", "FAILED"), "کارِ ارسال باید در صف بماند"
        assert job.max_attempts >= 10, "تلاش‌ها باید تا وصل‌شدن کانال ادامه یابد"

    # و همان وضعیت باید از API هم به کاربر گفته شود (نه «ارسال شد»)
    listed = client.get("/api/support/tickets?limit=5", headers=auth_headers).json()
    row = next(t for t in listed if t["id"] == out["id"])
    assert row["status"] == "FAILED" and row["status_label"] == "در انتظار ارسال مجدد", row
    assert sup.STATUSES["FAILED"] == "در انتظار ارسال مجدد"
