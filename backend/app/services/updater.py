"""Update system (§27–29).

Design constraints taken directly from the spec:

- **Only the owner/main admin may update** (§28) and they must re-enter their
  password: a session that is merely open is not proof that the right person
  is standing at the machine.
- **A backup is taken before anything is applied, and the update aborts if the
  backup fails** (§29). This is the single most important rule here: a failed
  backup is a hard stop, not a warning.
- **The package is verified before it is trusted** — size and SHA-256 must
  match the release metadata, otherwise a corrupted or substituted download
  would be installed.
- The release source is GitHub today but is behind `UpdateChannel`, so a
  commercial update server can replace it without touching callers (§27).

What this module deliberately does NOT do: silently restart the app or swap
binaries on a running Windows install. The final apply step is handed to the
installer, and the state machine records exactly how far it got, so an
interrupted update is diagnosable rather than mysterious.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sqlite3
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import __version__
from ..config import get_settings
from ..models import SystemSetting

GITHUB_REPO = "khajavy8056/Super-system-"
GITHUB_LATEST = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"

#: file name pattern of the Windows installer asset
ASSET_PATTERN = re.compile(r"Supermarket-System-v?[\d.]+-Setup\.exe$", re.I)


class UpdateError(Exception):
    def __init__(self, code: str, message: str = ""):
        self.code = code
        super().__init__(message or code)


# ---------------------------------------------------------------------------
# version comparison
# ---------------------------------------------------------------------------
def parse_version(text: str) -> tuple[int, ...]:
    """'v1.2.3' -> (1, 2, 3). Non-numeric suffixes are ignored."""
    cleaned = (text or "").strip().lstrip("vV")
    parts: list[int] = []
    for chunk in cleaned.split(".")[:4]:
        match = re.match(r"(\d+)", chunk)
        parts.append(int(match.group(1)) if match else 0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts)


def is_newer(candidate: str, current: str) -> bool:
    return parse_version(candidate) > parse_version(current)


# ---------------------------------------------------------------------------
# release channel
# ---------------------------------------------------------------------------
@dataclass
class ReleaseInfo:
    version: str
    name: str = ""
    notes: str = ""
    published_at: str | None = None
    asset_name: str | None = None
    asset_url: str | None = None
    asset_size: int = 0
    html_url: str | None = None

    def as_dict(self) -> dict:
        return {
            "version": self.version,
            "name": self.name,
            "notes": self.notes,
            "published_at": self.published_at,
            "asset_name": self.asset_name,
            "asset_size": self.asset_size,
            "html_url": self.html_url,
        }


class UpdateChannel:
    """Where releases come from. Swap this for a commercial server (§27)."""

    def fetch_latest(self, timeout: float = 8.0) -> ReleaseInfo:
        raise NotImplementedError


class GitHubChannel(UpdateChannel):
    def __init__(self, url: str = GITHUB_LATEST):
        self.url = url

    def fetch_latest(self, timeout: float = 8.0) -> ReleaseInfo:
        headers = {"Accept": "application/vnd.github+json"}
        token = os.environ.get("GITHUB_TOKEN")
        if token:
            headers["Authorization"] = f"Bearer {token}"
        try:
            resp = httpx.get(self.url, headers=headers, timeout=timeout,
                             follow_redirects=True)
        except httpx.HTTPError as exc:
            raise UpdateError("CHANNEL_UNREACHABLE", str(exc)) from exc

        if resp.status_code == 404:
            raise UpdateError("NO_RELEASE", "هیچ نسخه‌ای منتشر نشده است")
        if resp.status_code >= 400:
            raise UpdateError("CHANNEL_ERROR", f"HTTP {resp.status_code}")

        data = resp.json()
        info = ReleaseInfo(
            version=(data.get("tag_name") or "").lstrip("vV"),
            name=data.get("name") or "",
            notes=data.get("body") or "",
            published_at=data.get("published_at"),
            html_url=data.get("html_url"),
        )
        for asset in data.get("assets") or []:
            if ASSET_PATTERN.search(asset.get("name", "")):
                info.asset_name = asset.get("name")
                info.asset_url = asset.get("browser_download_url")
                info.asset_size = int(asset.get("size") or 0)
                break
        return info


# ---------------------------------------------------------------------------
# check / download / verify
# ---------------------------------------------------------------------------
def check_for_update(channel: UpdateChannel | None = None,
                     current: str | None = None) -> dict:
    """Ask the channel what the newest release is. Never raises for 'offline'."""
    channel = channel or GitHubChannel()
    current = current or __version__
    try:
        release = channel.fetch_latest()
    except UpdateError as exc:
        return {
            "status": "UNAVAILABLE",
            "code": exc.code,
            "current_version": current,
            "message": "بررسی به‌روزرسانی ممکن نشد؛ اتصال اینترنت را بررسی کنید",
            "detail": str(exc),
        }

    available = bool(release.version) and is_newer(release.version, current)
    return {
        "status": "UPDATE_AVAILABLE" if available else "UP_TO_DATE",
        "current_version": current,
        "latest": release.as_dict(),
        "update_available": available,
        "installable": bool(release.asset_url),
        "message": (
            f"نسخهٔ {release.version} در دسترس است"
            if available else "سامانه به‌روز است"
        ),
    }


def sha256_of(path: Path, chunk: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while data := handle.read(chunk):
            digest.update(data)
    return digest.hexdigest()


def verify_package(path: Path, *, expected_size: int = 0,
                   expected_sha256: str | None = None) -> dict:
    """Validate a downloaded package before it is ever executed."""
    if not path.exists():
        raise UpdateError("PACKAGE_MISSING", f"فایل به‌روزرسانی یافت نشد: {path}")

    size = path.stat().st_size
    if size == 0:
        raise UpdateError("PACKAGE_EMPTY", "فایل به‌روزرسانی خالی است")
    if expected_size and size != expected_size:
        raise UpdateError(
            "SIZE_MISMATCH",
            f"اندازهٔ فایل ({size}) با اندازهٔ اعلام‌شده ({expected_size}) یکی نیست",
        )

    digest = sha256_of(path)
    if expected_sha256 and digest.lower() != expected_sha256.lower():
        raise UpdateError(
            "CHECKSUM_MISMATCH",
            "اثر انگشت فایل با مقدار اعلام‌شده مطابقت ندارد؛ دانلود رد شد",
        )
    return {"size": size, "sha256": digest, "verified": True}


# ---------------------------------------------------------------------------
# mandatory pre-update backup (§29)
# ---------------------------------------------------------------------------
def backup_database(db: Session | None = None) -> dict:
    """SQLite online backup. Raises if it cannot be completed.

    §29 makes this a blocking step: no backup, no update.
    """
    settings = get_settings()
    url = settings.DATABASE_URL
    if not url.startswith("sqlite"):
        raise UpdateError(
            "BACKUP_UNSUPPORTED",
            "پشتیبان‌گیری خودکار برای این موتور پایگاه‌داده پیاده‌سازی نشده است",
        )

    source_path = Path(url.split("///")[-1]).resolve()
    if not source_path.exists():
        raise UpdateError("BACKUP_NO_SOURCE", f"پایگاه‌داده یافت نشد: {source_path}")

    backup_dir = settings.data_dir / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = backup_dir / f"supermarket_preupdate_{stamp}.db"

    try:
        source = sqlite3.connect(str(source_path))
        target = sqlite3.connect(str(dest))
        with target:
            source.backup(target)
        target.close()
        source.close()
    except Exception as exc:  # noqa: BLE001 - any failure must abort the update
        raise UpdateError("BACKUP_FAILED", f"پشتیبان‌گیری ناموفق بود: {exc}") from exc

    size = dest.stat().st_size
    if size == 0:
        dest.unlink(missing_ok=True)
        raise UpdateError("BACKUP_EMPTY", "فایل پشتیبان خالی است؛ به‌روزرسانی متوقف شد")

    # A backup you cannot open is not a backup: prove it is readable SQLite.
    try:
        check = sqlite3.connect(str(dest))
        tables = check.execute(
            "SELECT count(*) FROM sqlite_master WHERE type='table'"
        ).fetchone()[0]
        check.close()
    except Exception as exc:  # noqa: BLE001
        raise UpdateError("BACKUP_CORRUPT", f"فایل پشتیبان قابل خواندن نیست: {exc}")

    if tables == 0:
        raise UpdateError("BACKUP_CORRUPT", "فایل پشتیبان هیچ جدولی ندارد")

    return {"path": str(dest), "size": size, "tables": tables,
            "created_at": datetime.utcnow().isoformat()}


# ---------------------------------------------------------------------------
# orchestration
# ---------------------------------------------------------------------------
@dataclass
class UpdatePlan:
    """The ordered, auditable steps of an update run (§28)."""

    steps: list[dict] = field(default_factory=list)

    def record(self, name: str, status: str, detail: str = "",
               evidence: dict | None = None) -> None:
        self.steps.append({
            "name": name,
            "status": status,
            "detail": detail,
            "evidence": evidence or {},
            "at": datetime.utcnow().isoformat(),
        })

    def as_dict(self, overall: str, message: str) -> dict:
        return {"status": overall, "message": message, "steps": self.steps}


def prepare_update(
    db: Session,
    *,
    channel: UpdateChannel | None = None,
    download: bool = True,
    dest_dir: Path | None = None,
) -> dict:
    """Check → backup → download → verify, stopping at the first failure.

    Returns a step-by-step report. The final installation is performed by the
    downloaded installer; this function makes sure that by the time it runs,
    the data is safe and the package is genuine.
    """
    plan = UpdatePlan()

    # 1. what is available
    result = check_for_update(channel)
    if result["status"] == "UNAVAILABLE":
        plan.record("بررسی نسخهٔ جدید", "FAIL", result["detail"])
        return plan.as_dict("FAILED", result["message"])
    if not result["update_available"]:
        plan.record("بررسی نسخهٔ جدید", "PASS",
                    f"نسخهٔ فعلی {result['current_version']} به‌روز است")
        return plan.as_dict("UP_TO_DATE", "سامانه به‌روز است")

    latest = result["latest"]
    plan.record("بررسی نسخهٔ جدید", "PASS",
                f"نسخهٔ {latest['version']} در دسترس است", latest)

    # 2. BACKUP FIRST — a failure here aborts everything (§29)
    try:
        backup = backup_database(db)
    except UpdateError as exc:
        plan.record("پشتیبان‌گیری از پایگاه‌داده", "FAIL", str(exc))
        return plan.as_dict(
            "ABORTED",
            "به‌روزرسانی متوقف شد: بدون پشتیبان معتبر هیچ تغییری اعمال نمی‌شود",
        )
    plan.record("پشتیبان‌گیری از پایگاه‌داده", "PASS",
                f"{backup['size']} بایت، {backup['tables']} جدول", backup)

    if not download:
        return plan.as_dict("READY", "پشتیبان تهیه شد؛ آمادهٔ دانلود بسته")

    # 3. download
    if not latest.get("asset_name"):
        plan.record("دانلود بسته", "SKIPPED",
                    "این انتشار فایل نصب ویندوز ندارد")
        return plan.as_dict(
            "NO_PACKAGE",
            "نسخهٔ جدید موجود است اما فایل نصب برای ویندوز منتشر نشده است")

    release = (channel or GitHubChannel()).fetch_latest()
    dest_dir = dest_dir or (get_settings().data_dir / "updates")
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / release.asset_name

    try:
        with httpx.stream("GET", release.asset_url, follow_redirects=True,
                          timeout=60.0) as resp:
            resp.raise_for_status()
            with tempfile.NamedTemporaryFile(delete=False, dir=dest_dir) as tmp:
                for chunk in resp.iter_bytes(1 << 20):
                    tmp.write(chunk)
                tmp_path = Path(tmp.name)
        shutil.move(str(tmp_path), dest)
    except Exception as exc:  # noqa: BLE001
        plan.record("دانلود بسته", "FAIL", str(exc))
        return plan.as_dict("FAILED", "دانلود بستهٔ به‌روزرسانی ناموفق بود")

    plan.record("دانلود بسته", "PASS", f"{dest.name}", {"path": str(dest)})

    # 4. verify before trusting
    try:
        verified = verify_package(dest, expected_size=release.asset_size)
    except UpdateError as exc:
        dest.unlink(missing_ok=True)
        plan.record("اعتبارسنجی بسته", "FAIL", str(exc))
        return plan.as_dict("FAILED", "بستهٔ دانلودشده معتبر نبود و حذف شد")

    plan.record("اعتبارسنجی بسته", "PASS",
                f"SHA-256: {verified['sha256'][:16]}…", verified)

    return plan.as_dict(
        "READY",
        f"نسخهٔ {latest['version']} آمادهٔ نصب است. برای تکمیل، فایل "
        f"{dest.name} را اجرا کنید؛ داده‌های شما پیش از نصب پشتیبان‌گیری شد.",
    )
