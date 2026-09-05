"""SMS service — real providers + background dispatch worker (BUG-015).

Providers (configurable via settings):
- ``melipayamak``: Iranian SMS panel (username/password/sender) — REST API.
- ``kavenegar``:  Iranian SMS panel (api_key) — REST API.
- ``file``:       dev/test sink — writes messages to a file (honest, no network).
- ``fail``:       test provider that always fails (retry/FAILED path).

Honesty rules:
- No provider configured -> messages stay PENDING (never faked as SENT).
- Failures are classified, stored (error_message) and retried up to
  ``sms.max_retries`` with the RETRYING status; then FAILED.
- Live delivery to melipayamak/kavenegar requires internet egress; in this
  sandbox that was NOT possible, so those adapters are implemented but marked
  UNTESTED-LIVE in TEST_REPORT (no fake success claimed).
"""
from __future__ import annotations

import json
import threading
from datetime import datetime
from pathlib import Path

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings as app_settings
from ..models import SmsMessage, SystemSetting

_worker: threading.Thread | None = None
_stop = threading.Event()


class SmsProviderError(Exception):
    def __init__(self, kind: str, detail: str = ""):
        super().__init__(f"{kind}: {detail}")
        self.kind = kind
        self.detail = detail


def get_setting(db: Session, key: str, default: str) -> str:
    row = db.execute(select(SystemSetting).where(SystemSetting.key == key)).scalar_one_or_none()
    return row.value if row else default


# --- Providers ----------------------------------------------------------------

def _send_melipayamak(db: Session, phone: str, text: str) -> str:
    username = get_setting(db, "sms.username", "")
    password = get_setting(db, "sms.password", "")
    sender = get_setting(db, "sms.sender", "")
    if not (username and password and sender):
        raise SmsProviderError("CONFIG_MISSING", "sms.username/sms.password/sms.sender required")
    try:
        resp = httpx.post(
            "https://rest.payamak-panel.com/api/SendSMS/SendSMS",
            json={"username": username, "password": password, "to": phone,
                  "from": sender, "text": text},
            timeout=app_settings.EXTERNAL_TIMEOUT_SECONDS,
        )
    except httpx.HTTPError as exc:
        raise SmsProviderError("NETWORK", type(exc).__name__) from exc
    if resp.status_code != 200:
        raise SmsProviderError(f"HTTP_{resp.status_code}", resp.text[:200])
    try:
        body = resp.json()
    except ValueError as exc:
        raise SmsProviderError("INVALID_RESPONSE", str(exc)) from exc
    # Melipayamak returns Value==1 (or RetStatus/Status codes) on success
    value = body.get("Value") if isinstance(body, dict) else None
    if value not in (1, "1"):
        raise SmsProviderError("PROVIDER_REJECTED", json.dumps(body, ensure_ascii=False)[:200])
    return json.dumps(body, ensure_ascii=False)


def _send_kavenegar(db: Session, phone: str, text: str) -> str:
    api_key = get_setting(db, "sms.api_key", "")
    if not api_key:
        raise SmsProviderError("CONFIG_MISSING", "sms.api_key required")
    try:
        resp = httpx.get(
            f"https://api.kavenegar.com/v1/{api_key}/sms/send.json",
            params={"receptor": phone, "message": text},
            timeout=app_settings.EXTERNAL_TIMEOUT_SECONDS,
        )
    except httpx.HTTPError as exc:
        raise SmsProviderError("NETWORK", type(exc).__name__) from exc
    if resp.status_code == 429:
        raise SmsProviderError("RATE_LIMITED", resp.text[:200])
    if resp.status_code != 200:
        raise SmsProviderError(f"HTTP_{resp.status_code}", resp.text[:200])
    return resp.text[:500]


def _send_file(db: Session, phone: str, text: str) -> str:
    """Deterministic dev/test sink — proves the whole pipeline without network."""
    path = get_setting(db, "sms.file_path", "data/sms_out.log")
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps({"phone": phone, "text": text,
                            "at": datetime.utcnow().isoformat()}, ensure_ascii=False) + "\n")
    return f"file:{p}"


def _send_fail(db: Session, phone: str, text: str) -> str:
    raise SmsProviderError("ALWAYS_FAIL", "test provider")


PROVIDERS = {
    "melipayamak": _send_melipayamak,
    "kavenegar": _send_kavenegar,
    "file": _send_file,
    "fail": _send_fail,
}


# --- Dispatcher ----------------------------------------------------------------

def dispatch_pending(db: Session, *, limit: int = 20) -> dict:
    """Process PENDING/RETRYING messages once. Returns an honest summary."""
    provider_code = get_setting(db, "sms.provider", "").strip()
    max_retries = int(get_setting(db, "sms.max_retries", "5") or 5)

    stmt = select(SmsMessage).where(
        SmsMessage.status.in_(["PENDING", "RETRYING"])
    ).order_by(SmsMessage.id.asc()).limit(limit)
    messages = list(db.execute(stmt).scalars())

    summary = {"provider": provider_code or None, "sent": 0, "retrying": 0,
               "failed": 0, "skipped": 0}

    if not provider_code:
        # No provider configured — do NOT touch the messages (stay PENDING).
        summary["skipped"] = len(messages)
        summary["reason"] = "NO_PROVIDER_CONFIGURED"
        return summary

    sender = PROVIDERS.get(provider_code)
    if sender is None:
        summary["skipped"] = len(messages)
        summary["reason"] = f"UNKNOWN_PROVIDER:{provider_code}"
        return summary

    for msg in messages:
        try:
            response = sender(db, msg.phone, msg.text)
            msg.status = "SENT"
            msg.sent_at = datetime.utcnow()
            msg.provider_response = response
            msg.error_message = None
            summary["sent"] += 1
        except SmsProviderError as exc:
            msg.retry_count = (msg.retry_count or 0) + 1
            msg.error_message = f"{exc.kind}: {exc.detail}"[:500]
            if msg.retry_count >= max_retries:
                msg.status = "FAILED"
                summary["failed"] += 1
            else:
                msg.status = "RETRYING"
                summary["retrying"] += 1
    db.commit()
    return summary


# --- Background worker -----------------------------------------------------------

def start_worker(session_factory) -> None:
    """Start the background dispatch thread (idempotent)."""
    global _worker
    if _worker and _worker.is_alive():
        return
    _stop.clear()

    def run():
        while not _stop.is_set():
            try:
                db = session_factory()
                try:
                    interval = int(get_setting(db, "sms.worker_interval_seconds", "10") or 10)
                    dispatch_pending(db)
                finally:
                    db.close()
            except Exception:  # never let the worker die silently
                import logging
                logging.getLogger("supermarket.sms").exception("sms worker tick failed")
                interval = 10
            _stop.wait(max(3, min(interval, 300)))

    _worker = threading.Thread(target=run, name="sms-worker", daemon=True)
    _worker.start()


def stop_worker() -> None:
    _stop.set()
