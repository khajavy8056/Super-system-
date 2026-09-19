"""v1.7 — Cloud relay sync over the internet (Google Drive, appDataFolder).

Why: the phone and the PC are not always on the same Wi-Fi. When both are
signed in to the same Google account, Drive's hidden *appDataFolder* is used
as a mailbox:

  PC  → uploads  ``snapshot.json``      (products / batches / customers)
                 ``backup-latest.db``   (encrypted-at-rest by Google; optional)
  Phone → uploads ``ops-<device>-<ts>.json`` (queued sales / receipts / counts …)
  PC  ← downloads every ``ops-*`` file, applies it through the SAME code path
        as LAN sync (``routers.mobile._apply`` → idempotent by op id), deletes it.
  Phone ← downloads ``snapshot.json`` to refresh its offline cache.

Auth: OAuth 2.0 *limited-input device* flow (no redirect URI, works from a
desktop app and inside the Android WebView). The owner creates a free OAuth
client (type "TVs and Limited Input devices") once and pastes client id +
secret in Settings → همگام‌سازی ابری. Scope: ``drive.appdata`` only — the app
can never see the user's own Drive files.

Everything is optional: nothing here runs unless configured. All endpoints are
overridable (system_settings ``cloud.*_url``) so the test-suite drives a stub.
"""
from __future__ import annotations

import base64
import json
import logging
import threading
import time
from datetime import datetime

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Customer, Product, ProductBatch, SystemSetting, User

log = logging.getLogger("supermarket.cloud")

SCOPE = "https://www.googleapis.com/auth/drive.appdata"
DEFAULTS = {
    "cloud.device_url": "https://oauth2.googleapis.com/device/code",
    "cloud.token_url": "https://oauth2.googleapis.com/token",
    "cloud.api_url": "https://www.googleapis.com/drive/v3",
    "cloud.upload_url": "https://www.googleapis.com/upload/drive/v3",
    "cloud.userinfo_url": "https://www.googleapis.com/oauth2/v3/userinfo",
}
PROVIDER_LABEL = "Google Drive"


class CloudError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


# --- settings -------------------------------------------------------------------------
def _get(db: Session, key: str, default: str = "") -> str:
    row = db.execute(select(SystemSetting).where(SystemSetting.key == key)).scalar_one_or_none()
    if row and row.value not in (None, ""):
        return row.value
    return DEFAULTS.get(key, default)


def _set(db: Session, key: str, value: str, secret: bool = False) -> None:
    row = db.execute(select(SystemSetting).where(SystemSetting.key == key)).scalar_one_or_none()
    if row is None:
        db.add(SystemSetting(key=key, value=value, is_secret=secret, description="Cloud sync"))
    else:
        row.value = value


def config(db: Session) -> dict:
    return {
        "client_id": _get(db, "cloud.client_id"),
        "client_secret": _get(db, "cloud.client_secret"),
        "refresh_token": _get(db, "cloud.refresh_token"),
        "account": _get(db, "cloud.account"),
        "enabled": _get(db, "cloud.enabled", "0") == "1",
        "device_url": _get(db, "cloud.device_url"),
        "token_url": _get(db, "cloud.token_url"),
        "api_url": _get(db, "cloud.api_url").rstrip("/"),
        "upload_url": _get(db, "cloud.upload_url").rstrip("/"),
        "userinfo_url": _get(db, "cloud.userinfo_url"),
    }


def connected(db: Session) -> bool:
    c = config(db)
    return bool(c["client_id"] and c["client_secret"] and c["refresh_token"])


def status(db: Session) -> dict:
    c = config(db)
    return {
        "provider": "google-drive", "provider_label": PROVIDER_LABEL,
        "configured": bool(c["client_id"] and c["client_secret"]),
        "connected": connected(db), "enabled": c["enabled"] and connected(db),
        "account": c["account"] or None,
        "last_push_at": _get(db, "cloud.last_push_at") or None,
        "last_pull_at": _get(db, "cloud.last_pull_at") or None,
        "last_error": _get(db, "cloud.last_error") or None,
        "applied_total": int(_get(db, "cloud.applied_total", "0") or 0),
    }


# --- OAuth device flow ----------------------------------------------------------------
def device_start(db: Session, client_id: str | None = None, client_secret: str | None = None) -> dict:
    if client_id:
        _set(db, "cloud.client_id", client_id.strip())
    if client_secret:
        _set(db, "cloud.client_secret", client_secret.strip(), secret=True)
    db.commit()
    c = config(db)
    if not (c["client_id"] and c["client_secret"]):
        raise CloudError("CONFIG_MISSING", "شناسه و کلید سرویس ابری وارد نشده است")
    r = httpx.post(c["device_url"], data={"client_id": c["client_id"], "scope": SCOPE}, timeout=15)
    data = r.json()
    if r.status_code >= 400 or "device_code" not in data:
        raise CloudError("DEVICE_START_FAILED", data.get("error_description") or data.get("error") or r.text[:200])
    _set(db, "cloud.device_code", data["device_code"], secret=True)
    db.commit()
    return {"user_code": data["user_code"], "verification_url": data.get("verification_url") or data.get("verification_uri"),
            "expires_in": data.get("expires_in", 1800), "interval": data.get("interval", 5)}


def device_poll(db: Session) -> dict:
    """Call repeatedly until the owner has approved on google.com/device."""
    c = config(db)
    code = _get(db, "cloud.device_code")
    if not code:
        raise CloudError("NO_PENDING", "ابتدا فرایند اتصال را شروع کنید")
    r = httpx.post(c["token_url"], data={"client_id": c["client_id"], "client_secret": c["client_secret"],
                                         "device_code": code, "grant_type": "urn:ietf:params:oauth:grant-type:device_code"}, timeout=15)
    data = r.json()
    if "access_token" in data:
        _set(db, "cloud.refresh_token", data.get("refresh_token", ""), secret=True)
        _set(db, "cloud.access_token", data["access_token"], secret=True)
        _set(db, "cloud.access_exp", str(time.time() + int(data.get("expires_in", 3600)) - 60))
        _set(db, "cloud.device_code", "")
        _set(db, "cloud.enabled", "1")
        try:
            ui = httpx.get(c["userinfo_url"], headers={"Authorization": "Bearer " + data["access_token"]}, timeout=10).json()
            _set(db, "cloud.account", ui.get("email") or ui.get("name") or "")
        except Exception:  # noqa: BLE001
            pass
        db.commit()
        return {"status": "CONNECTED", "account": _get(db, "cloud.account")}
    err = data.get("error", "")
    if err in ("authorization_pending", "slow_down"):
        return {"status": "PENDING"}
    _set(db, "cloud.device_code", ""); db.commit()
    raise CloudError("DEVICE_DENIED", data.get("error_description") or err or "رد شد")


# --- v2.1: in-app sign-in (authorization code + PKCE, loopback redirect) -------------------
# The Windows app runs in the local browser, so Google can send the browser straight
# back to http://127.0.0.1:<port>/api/cloud/oauth/callback — the owner picks the Google
# account on Google's own page and lands back inside the app. No code to copy, no
# second device. (Embedded WebView logins are forbidden by Google; this is the
# sanctioned native flow, RFC 8252.)
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"


def oauth_start(db: Session, redirect_uri: str, client_id: str | None = None, client_secret: str | None = None) -> dict:
    import hashlib
    import secrets
    from urllib.parse import urlencode
    if client_id:
        _set(db, "cloud.client_id", client_id.strip())
    if client_secret:
        _set(db, "cloud.client_secret", client_secret.strip(), secret=True)
    db.commit()
    c = config(db)
    if not (c["client_id"] and c["client_secret"]):
        raise CloudError("CONFIG_MISSING", "شناسه و کلید سرویس ابری وارد نشده است")
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    state = secrets.token_urlsafe(24)
    _set(db, "cloud.oauth_state", state, secret=True)
    _set(db, "cloud.oauth_verifier", verifier, secret=True)
    _set(db, "cloud.oauth_redirect", redirect_uri)
    db.commit()
    q = {"client_id": c["client_id"], "redirect_uri": redirect_uri, "response_type": "code", "scope": SCOPE + " openid email",
         "access_type": "offline", "prompt": "consent select_account", "state": state, "code_challenge": challenge, "code_challenge_method": "S256"}
    return {"url": f"{_get(db, 'cloud.auth_url', AUTH_URL)}?{urlencode(q)}", "state": state}


def oauth_finish(db: Session, code: str, state: str) -> dict:
    c = config(db)
    if not state or state != _get(db, "cloud.oauth_state"):
        raise CloudError("STATE_MISMATCH", "درخواست ورود معتبر نیست؛ دوباره تلاش کنید")
    r = httpx.post(c["token_url"], data={"client_id": c["client_id"], "client_secret": c["client_secret"], "code": code,
                                         "code_verifier": _get(db, "cloud.oauth_verifier"), "redirect_uri": _get(db, "cloud.oauth_redirect"),
                                         "grant_type": "authorization_code"}, timeout=20)
    data = r.json()
    if "access_token" not in data:
        raise CloudError("TOKEN_EXCHANGE_FAILED", data.get("error_description") or data.get("error") or r.text[:200])
    _set(db, "cloud.refresh_token", data.get("refresh_token", ""), secret=True)
    _set(db, "cloud.access_token", data["access_token"], secret=True)
    _set(db, "cloud.access_exp", str(time.time() + int(data.get("expires_in", 3600)) - 60))
    _set(db, "cloud.oauth_state", ""); _set(db, "cloud.oauth_verifier", "")
    _set(db, "cloud.enabled", "1")
    try:
        ui = httpx.get(c["userinfo_url"], headers={"Authorization": "Bearer " + data["access_token"]}, timeout=10).json()
        _set(db, "cloud.account", ui.get("email") or ui.get("name") or "")
    except Exception:  # noqa: BLE001
        pass
    db.commit()
    return {"status": "CONNECTED", "account": _get(db, "cloud.account")}


def disconnect(db: Session) -> None:
    for k in ("cloud.refresh_token", "cloud.access_token", "cloud.access_exp", "cloud.device_code", "cloud.account"):
        _set(db, k, "")
    _set(db, "cloud.enabled", "0")
    db.commit()


def access_token(db: Session) -> str:
    c = config(db)
    tok, exp = _get(db, "cloud.access_token"), float(_get(db, "cloud.access_exp", "0") or 0)
    if tok and exp > time.time():
        return tok
    if not c["refresh_token"]:
        raise CloudError("NOT_CONNECTED", "حساب ابری متصل نیست")
    r = httpx.post(c["token_url"], data={"client_id": c["client_id"], "client_secret": c["client_secret"],
                                         "refresh_token": c["refresh_token"], "grant_type": "refresh_token"}, timeout=15)
    data = r.json()
    if "access_token" not in data:
        raise CloudError("TOKEN_REFRESH_FAILED", data.get("error_description") or data.get("error") or r.text[:200])
    _set(db, "cloud.access_token", data["access_token"], secret=True)
    _set(db, "cloud.access_exp", str(time.time() + int(data.get("expires_in", 3600)) - 60))
    db.commit()
    return data["access_token"]


def credentials_for_device(db: Session) -> dict | None:
    """What the phone needs to talk to Drive itself (embedded in the pairing QR
    when cloud sync is on). Same account, same appDataFolder."""
    c = config(db)
    if not (c["enabled"] and connected(db)):
        return None
    return {"client_id": c["client_id"], "client_secret": c["client_secret"], "refresh_token": c["refresh_token"],
            "token_url": c["token_url"], "api_url": c["api_url"], "upload_url": c["upload_url"], "account": c["account"]}


# --- Drive helpers ---------------------------------------------------------------------
class Drive:
    def __init__(self, db: Session):
        self.c = config(db)
        self.h = {"Authorization": "Bearer " + access_token(db)}

    def list(self, q: str) -> list[dict]:
        r = httpx.get(f"{self.c['api_url']}/files", params={"spaces": "appDataFolder", "q": q, "fields": "files(id,name,modifiedTime,size)", "pageSize": 200},
                      headers=self.h, timeout=20)
        if r.status_code >= 400:
            raise CloudError("DRIVE_LIST", r.text[:200])
        return r.json().get("files", [])

    def find(self, name: str) -> dict | None:
        files = self.list(f"name = '{name}' and trashed = false")
        return files[0] if files else None

    def upload(self, name: str, content: bytes, mime: str = "application/json") -> str:
        existing = self.find(name)
        boundary = "smkt-boundary-7f3a"
        meta = {"name": name} if existing else {"name": name, "parents": ["appDataFolder"]}
        body = (f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n{json.dumps(meta)}\r\n"
                f"--{boundary}\r\nContent-Type: {mime}\r\n\r\n").encode() + content + f"\r\n--{boundary}--".encode()
        hdr = {**self.h, "Content-Type": f"multipart/related; boundary={boundary}"}
        if existing:
            r = httpx.patch(f"{self.c['upload_url']}/files/{existing['id']}", params={"uploadType": "multipart"}, content=body, headers=hdr, timeout=60)
        else:
            r = httpx.post(f"{self.c['upload_url']}/files", params={"uploadType": "multipart"}, content=body, headers=hdr, timeout=60)
        if r.status_code >= 400:
            raise CloudError("DRIVE_UPLOAD", r.text[:200])
        return r.json().get("id", "")

    def download(self, file_id: str) -> bytes:
        r = httpx.get(f"{self.c['api_url']}/files/{file_id}", params={"alt": "media"}, headers=self.h, timeout=60)
        if r.status_code >= 400:
            raise CloudError("DRIVE_DOWNLOAD", r.text[:200])
        return r.content

    def delete(self, file_id: str) -> None:
        httpx.delete(f"{self.c['api_url']}/files/{file_id}", headers=self.h, timeout=20)


# --- sync ---------------------------------------------------------------------------------
def build_snapshot(db: Session) -> dict:
    prods = db.execute(select(Product)).scalars().all()
    batches = db.execute(select(ProductBatch).where(ProductBatch.current_qty > 0)).scalars().all()
    custs = db.execute(select(Customer)).scalars().all()
    return {
        "generated_at": datetime.utcnow().isoformat(timespec="seconds"),
        "products": [{"id": p.id, "name": p.name, "sku": p.sku, "barcode": p.barcode, "unit_id": p.unit_id, "category_id": p.category_id,
                      "is_active": p.is_active, "updated_at": p.updated_at.isoformat()} for p in prods],
        "batches": [{"id": b.id, "product_id": b.product_id, "batch_number": b.batch_number, "expiry_date": b.expiry_date.isoformat() if b.expiry_date else None,
                     "current_qty": float(b.current_qty or 0), "unit_sell_price": float(b.sell_price or 0), "status": b.status} for b in batches],
        "customers": [{"id": c.id, "name": c.name, "phone": c.phone} for c in custs],
    }


def _apply_ops_file(db: Session, payload: dict) -> int:
    """Replays a phone's ops file through the LAN sync code (idempotent)."""
    from ..routers import mobile as mobile_router
    from ..security import decode_token
    from ..services import sync as sync_svc
    user = None
    tok = payload.get("token")
    if tok:
        try:
            username = decode_token(tok).get("sub")
            user = db.execute(select(User).where(User.username == username)).scalar_one_or_none()
        except Exception:  # noqa: BLE001
            user = None
    if user is None:
        user = db.execute(select(User).where(User.is_active.is_(True)).order_by(User.id.asc())).scalars().first()
    body = mobile_router.SyncIn(device_id=payload.get("device_id"), push=[mobile_router.SyncOp(**o) for o in payload.get("push", [])], pull=False)
    applied = 0
    for op in body.push:
        existing = db.execute(select(sync_svc.SyncJob).where(sync_svc.SyncJob.idempotency_key == f"mob:{op.id}")).scalar_one_or_none()
        if existing is not None:
            continue
        res = mobile_router._apply(db, user, op)
        db.add(sync_svc.SyncJob(job_type=f"CLOUD_{op.type.upper()}", payload=json.dumps(op.payload, ensure_ascii=False, default=str),
                                status="COMPLETED" if res["status"] == "APPLIED" else "FAILED", attempts=1, max_attempts=1,
                                idempotency_key=f"mob:{op.id}", reference_type="CloudDevice", created_by=user.id if user else None,
                                last_error=json.dumps(res.get("result") or res.get("error"), ensure_ascii=False), completed_at=datetime.utcnow()))
        db.commit()
        applied += 1 if res["status"] == "APPLIED" else 0
    return applied


def sync_now(db: Session, *, push_backup: bool = True) -> dict:
    """PC side: pull & apply phone ops, then publish a fresh snapshot (+ DB backup)."""
    if not connected(db):
        raise CloudError("NOT_CONNECTED", "حساب ابری متصل نیست")
    out = {"applied": 0, "files": 0, "snapshot": False, "backup": False}
    try:
        d = Drive(db)
        for f in d.list("name contains 'ops-' and trashed = false"):
            try:
                payload = json.loads(d.download(f["id"]).decode("utf-8"))
                out["applied"] += _apply_ops_file(db, payload)
                out["files"] += 1
                d.delete(f["id"])
            except Exception as exc:  # noqa: BLE001 — a bad file must not block the rest
                log.warning("cloud ops file %s failed: %s", f.get("name"), exc)
        _set(db, "cloud.last_pull_at", datetime.utcnow().isoformat(timespec="seconds"))
        d.upload("snapshot.json", json.dumps(build_snapshot(db), ensure_ascii=False).encode("utf-8"))
        out["snapshot"] = True
        if push_backup:
            try:
                from ..routers.system import backup as make_backup
                info = make_backup(db)  # type: ignore[call-arg]
                path = info.get("path") if isinstance(info, dict) else None
                if path:
                    with open(path, "rb") as fh:
                        d.upload("backup-latest.db", fh.read(), "application/octet-stream")
                    out["backup"] = True
            except Exception as exc:  # noqa: BLE001
                log.info("cloud backup upload skipped: %s", exc)
        _set(db, "cloud.last_push_at", datetime.utcnow().isoformat(timespec="seconds"))
        _set(db, "cloud.applied_total", str(int(_get(db, "cloud.applied_total", "0") or 0) + out["applied"]))
        _set(db, "cloud.last_error", "")
        db.commit()
    except CloudError as exc:
        _set(db, "cloud.last_error", f"{exc.code}: {exc}"); db.commit()
        raise
    return out


# --- background worker -------------------------------------------------------------------
_stop = threading.Event()
_thread: threading.Thread | None = None


def start_worker(session_factory, interval: int = 300) -> None:
    global _thread
    if _thread and _thread.is_alive():
        return
    _stop.clear()

    def run():
        # first tick after one interval: startup stays fast and the DB is never
        # touched from a second thread while the app is still initialising
        _stop.wait(interval)
        while not _stop.is_set():
            try:
                db = session_factory()
                try:
                    if config(db)["enabled"] and connected(db):
                        sync_now(db, push_backup=False)
                finally:
                    db.close()
            except Exception as exc:  # noqa: BLE001
                log.warning("cloud sync tick failed: %s", exc)
            _stop.wait(interval)

    _thread = threading.Thread(target=run, name="cloud-sync", daemon=True)
    _thread.start()


def stop_worker() -> None:
    _stop.set()
