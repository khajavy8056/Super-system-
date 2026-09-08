"""v1.5 — Online licence activation & periodic re-validation.

Contract with the licence server (Cloudflare Worker supplied by the owner)::

    GET {server}?api_action=validate&key={KEY}&hwid={HWID}
    -> {"status":"SUCCESS","type":"FULL","owner":"Demo","expires":"2026-09-30"}
    -> {"status":"INVALID","message":"لایسنس یافت نشد"}
    -> {"status":"MAX_DEVICES_REACHED","message":"سقف تعداد دستگاه مجاز تکمیل شده است"}

Rules (agreed with the owner):
* The app never opens without an activated licence (gate in ``main.py``).
* The result is cached in ``system_settings`` so the check is NOT repeated on
  every start; it is re-validated online every 24 h (background thread + on
  every login "loading" screen).
* A definite server verdict (INVALID / EXPIRED / MAX_DEVICES_REACHED / …)
  revokes the cached activation. A *network* failure keeps the cached state:
  v1.6 — the first successful activation told us the expiry date, so while the
  server is unreachable the licence stays valid **until that date** (not a fixed
  7-day window). Without a known expiry date the 7-day grace applies.
* When the app locks (expired / revoked) the shop's data is preserved: the
  database is archived into an AES-encrypted ZIP (``vault/``) — see
  ``lock_vault``. Nothing is deleted.
"""
from __future__ import annotations

import hashlib
import logging
import platform
import threading
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import SystemSetting

log = logging.getLogger("supermarket.license")

DEFAULT_SERVER = "https://soft-hat-4eba.khajavi8056.workers.dev/"
RECHECK_HOURS = 24
OFFLINE_GRACE_DAYS = 7
TIMEOUT = 12.0

KEYS = ("key", "status", "type", "owner", "expires", "message", "checked_at",
        "activated_at", "hwid", "last_error", "server_url", "vault_at", "vault_path")


class LicenseError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


# --- settings helpers ---------------------------------------------------------
def _get(db: Session, key: str, default: str = "") -> str:
    row = db.execute(select(SystemSetting).where(SystemSetting.key == f"license.{key}")).scalar_one_or_none()
    return row.value if row and row.value is not None else default


def _set(db: Session, key: str, value: str, secret: bool = False) -> None:
    row = db.execute(select(SystemSetting).where(SystemSetting.key == f"license.{key}")).scalar_one_or_none()
    if row is None:
        db.add(SystemSetting(key=f"license.{key}", value=value, is_secret=secret,
                             description="Licence (managed by the activation wizard)"))
    else:
        row.value = value


def server_url(db: Session) -> str:
    """Owner's worker by default; SUPERMARKET_LICENSE_SERVER overrides (used by
    UI smoke tests that run a local stub — never set in production)."""
    import os
    return os.environ.get("SUPERMARKET_LICENSE_SERVER") or _get(db, "server_url", "") or DEFAULT_SERVER


# --- hardware id --------------------------------------------------------------
_HWID: str | None = None


def hwid() -> str:
    """Stable per-machine id: Windows MachineGuid → /etc/machine-id → MAC; hashed."""
    global _HWID
    if _HWID:
        return _HWID
    raw = ""
    try:
        if platform.system() == "Windows":
            import winreg  # type: ignore

            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography",
                                0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as k:
                raw = str(winreg.QueryValueEx(k, "MachineGuid")[0])
    except Exception:  # noqa: BLE001
        raw = ""
    if not raw:
        for p in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
            try:
                raw = Path(p).read_text().strip()
                if raw:
                    break
            except Exception:  # noqa: BLE001
                continue
    if not raw:
        raw = f"{uuid.getnode():012x}"
    digest = hashlib.sha256(("supermarket|" + raw).encode()).hexdigest().upper()
    _HWID = "-".join(digest[i:i + 4] for i in range(0, 16, 4))  # XXXX-XXXX-XXXX-XXXX
    return _HWID


# --- remote call ----------------------------------------------------------------
def fetch_remote(url: str, key: str, hw: str) -> dict:
    """Single HTTP round-trip. Raises LicenseError('NETWORK', …) when unreachable.
    Kept tiny and module-level so tests can monkeypatch it."""
    try:
        r = httpx.get(url, params={"api_action": "validate", "key": key, "hwid": hw}, timeout=TIMEOUT,
                      headers={"User-Agent": "SupermarketSystem-License/1.5"})
        r.raise_for_status()
        data = r.json()
        if not isinstance(data, dict):
            raise ValueError("not an object")
        return data
    except (httpx.HTTPError, ValueError) as exc:
        raise LicenseError("NETWORK", f"ارتباط با سرور لایسنس برقرار نشد ({type(exc).__name__})") from exc


def _parse_expires(v) -> date | None:
    if not v:
        return None
    try:
        return date.fromisoformat(str(v)[:10])
    except ValueError:
        return None


# --- activation / validation ---------------------------------------------------
def activate(db: Session, key: str) -> dict:
    """Validate ``key`` online for this machine and cache the verdict.
    Raises LicenseError on any non-SUCCESS answer (nothing cached as active)."""
    key = (key or "").strip().upper()
    if len(key) < 8:
        raise LicenseError("INVALID_FORMAT", "کلید لایسنس نامعتبر است.")
    hw = hwid()
    data = fetch_remote(server_url(db), key, hw)
    status = str(data.get("status", "")).upper()
    now = datetime.utcnow().isoformat(timespec="seconds")
    if status != "SUCCESS":
        msg = data.get("message") or {
            "INVALID": "لایسنس یافت نشد",
            "EXPIRED": "مدت اعتبار لایسنس به پایان رسیده است",
            "MAX_DEVICES_REACHED": "سقف تعداد دستگاه مجاز تکمیل شده است",
            "DISABLED": "این لایسنس غیرفعال شده است",
        }.get(status, f"پاسخ سرور: {status or 'نامشخص'}")
        _set(db, "last_error", f"{now} {status}: {msg}")
        db.flush()
        raise LicenseError(status or "REJECTED", msg)
    exp = _parse_expires(data.get("expires"))
    if exp and exp < date.today():
        raise LicenseError("EXPIRED", f"مدت اعتبار لایسنس در {exp.isoformat()} به پایان رسیده است")
    _set(db, "key", key, secret=True)
    _set(db, "status", "ACTIVE")
    _set(db, "type", str(data.get("type") or "FULL").upper())
    _set(db, "owner", str(data.get("owner") or ""))
    _set(db, "expires", exp.isoformat() if exp else "")
    _set(db, "message", str(data.get("message") or ""))
    _set(db, "checked_at", now)
    _set(db, "hwid", hw)
    _set(db, "last_error", "")
    if not _get(db, "activated_at"):
        _set(db, "activated_at", now)
    db.flush()
    return state(db)


def recheck(db: Session, *, force: bool = False) -> dict:
    """Periodic online re-validation of the cached key (every 24 h).
    Definite rejection → status REVOKED; network problem → keep cached state
    (offline grace handled by ``state``)."""
    key = _get(db, "key")
    if not key:
        return state(db)
    if not force and not is_recheck_due(db):
        return state(db)
    try:
        activate(db, key)
    except LicenseError as exc:
        if exc.code == "NETWORK":
            _set(db, "last_error", f"{datetime.utcnow().isoformat(timespec='seconds')} NETWORK: {exc.message}")
        else:
            _set(db, "status", "REVOKED")
            _set(db, "message", exc.message)
            _set(db, "checked_at", datetime.utcnow().isoformat(timespec="seconds"))
        db.flush()
    return state(db)


def is_recheck_due(db: Session) -> bool:
    chk = _get(db, "checked_at")
    if not chk:
        return True
    try:
        return datetime.utcnow() - datetime.fromisoformat(chk) >= timedelta(hours=RECHECK_HOURS)
    except ValueError:
        return True


def state(db: Session) -> dict:
    """Public, non-secret licence state + the single ``allowed`` verdict."""
    key = _get(db, "key")
    status = _get(db, "status")
    exp = _parse_expires(_get(db, "expires"))
    checked = _get(db, "checked_at")
    today = date.today()
    days_left = (exp - today).days if exp else None
    allowed, reason = True, ""
    if not key or status != "ACTIVE":
        allowed, reason = False, (_get(db, "message") or "لایسنس فعال نیست")
    elif exp and exp < today:
        allowed, reason = False, f"مدت اعتبار لایسنس در {exp.isoformat()} به پایان رسیده است"
    else:
        try:
            age = datetime.utcnow() - datetime.fromisoformat(checked)
        except ValueError:
            age = timedelta(days=999)
        # v1.6: a known expiry date is the offline horizon; otherwise 7 days
        if exp is None and age > timedelta(days=OFFLINE_GRACE_DAYS):
            allowed, reason = False, ("بیش از ۷ روز است که لایسنس به‌صورت آنلاین تأیید نشده؛ "
                                      "برای ادامه، دستگاه را به اینترنت متصل کنید.")
    masked = (key[:4].rstrip("-") + "-****-****-" + key[-4:]) if len(key) >= 8 else ""
    return {
        "activated": bool(key) and status == "ACTIVE",
        "allowed": allowed,
        "reason": reason,
        "status": status or "NONE",
        "type": _get(db, "type"),
        "owner": _get(db, "owner"),
        "expires": exp.isoformat() if exp else None,
        "days_left": days_left,
        "checked_at": checked or None,
        "activated_at": _get(db, "activated_at") or None,
        "recheck_due": is_recheck_due(db) if key else False,
        "hwid": hwid(),
        "key_masked": masked,
        "last_error": _get(db, "last_error") or None,
        "server": server_url(db),
        "offline_until": exp.isoformat() if exp else None,   # v1.6: offline validity horizon
        "vault_path": _get(db, "vault_path") or None,
    }


# --- encrypted vault on lock (v1.6) -------------------------------------------------
def vault_dir() -> Path:
    from ..config import settings
    p = settings.data_dir / "vault"
    p.mkdir(parents=True, exist_ok=True)
    return p


def vault_password() -> str:
    """Derived from the per-install secret + HWID; never stored in clear."""
    from ..config import settings
    return hashlib.sha256(f"vault|{settings.SECRET_KEY}|{hwid()}".encode()).hexdigest()[:40]


def lock_vault(db: Session, *, force: bool = False) -> dict | None:
    """When the licence blocks the app, archive the SQLite database into an
    AES-256 encrypted ZIP so the owner's data is preserved (and portable) while
    the app is locked. At most one archive per day unless ``force``.
    Returns {"path", "size"} or None when nothing was done."""
    from ..config import settings
    if not settings.DATABASE_URL.startswith("sqlite:///"):
        return None
    db_path = Path(settings.DATABASE_URL.split("///")[-1])
    if not db_path.exists() or str(db_path) == ":memory:":
        return None
    last = _get(db, "vault_at")
    if last and not force:
        try:
            if datetime.utcnow() - datetime.fromisoformat(last) < timedelta(days=1):
                return None
        except ValueError:
            pass
    import io
    import json
    import sqlite3
    import pyzipper

    buf = io.BytesIO()
    src = sqlite3.connect(str(db_path))
    tmp = vault_dir() / ".snapshot.db"
    dst = sqlite3.connect(str(tmp))
    with dst:
        src.backup(dst)
    src.close(); dst.close()
    stamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    out = vault_dir() / f"supermarket_locked_{stamp}.zip"
    meta = {"created_at": datetime.utcnow().isoformat(timespec="seconds"), "hwid": hwid(),
            "license_status": _get(db, "status"), "expires": _get(db, "expires"), "reason": state(db)["reason"]}
    with pyzipper.AESZipFile(str(out), "w", compression=pyzipper.ZIP_DEFLATED, encryption=pyzipper.WZ_AES) as z:
        z.setpassword(vault_password().encode())
        z.write(str(tmp), "supermarket.db")
        z.writestr("vault.json", json.dumps(meta, ensure_ascii=False, indent=2))
    try:
        tmp.unlink()
    except OSError:
        pass
    _set(db, "vault_at", datetime.utcnow().isoformat(timespec="seconds"))
    _set(db, "vault_path", str(out))
    db.flush()
    log.warning("licence lock: data archived to encrypted vault %s", out)
    return {"path": str(out), "size": out.stat().st_size}


def clear(db: Session) -> None:
    for k in KEYS:
        if k != "server_url":
            _set(db, k, "")
    db.flush()


# --- background 24h re-check ----------------------------------------------------
_stop = threading.Event()
_thread: threading.Thread | None = None


def start_worker(session_factory, interval_seconds: int = 3600) -> None:
    global _thread
    if _thread and _thread.is_alive():
        return
    _stop.clear()

    def run():
        while not _stop.is_set():
            try:
                db = session_factory()
                try:
                    if _get(db, "key") and is_recheck_due(db):
                        recheck(db)
                        db.commit()
                finally:
                    db.close()
            except Exception:  # noqa: BLE001 — never die
                log.exception("license recheck tick failed")
            _stop.wait(interval_seconds)

    _thread = threading.Thread(target=run, name="license-worker", daemon=True)
    _thread.start()


def stop_worker() -> None:
    _stop.set()
