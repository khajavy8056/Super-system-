"""v1.7 — Support requests (تیکت پشتیبانی).

The shop registers a request (خرابی / درخواست امکان / سؤال / …). It is stored
locally (works offline) and relayed to the vendor's support inbox through the
configured *relay channel* by the background queue (retry with back-off). The
UI only ever talks about «ارسال به پشتیبانی»; the transport is an internal
detail (``SUPPORT_RELAY_URL`` / ``SUPPORT_RELAY_TOKEN`` in config).

Message content: type, subject, description, store profile (name / phone /
address / city), app version + HWID, reporter, device (Windows / Android),
and — when the device shared it — the exact geolocation (also sent as a map
pin so it opens directly in the inbox).
"""
from __future__ import annotations

import json
import logging
from datetime import datetime

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import __version__
from ..config import settings
from ..models import SupportTicket, SystemSetting
from . import sync as sync_svc

log = logging.getLogger("supermarket.support")

TICKET_TYPES = {
    "BUG": "ثبت خرابی / اشکال",
    "FEATURE": "درخواست افزودن امکان ویژه",
    "QUESTION": "سؤال / راهنمایی",
    "HARDWARE": "مشکل سخت‌افزار (چاپگر، اسکنر، صندوق)",
    "LICENSE": "لایسنس و فعال‌سازی",
    "TRAINING": "آموزش / راه‌اندازی",
    "OTHER": "سایر",
}
PRIORITIES = {"LOW": "کم", "NORMAL": "عادی", "HIGH": "زیاد", "URGENT": "فوری"}
STATUSES = {"NEW": "ثبت‌شده", "SENT": "ارسال‌شده به پشتیبانی", "FAILED": "در انتظار ارسال مجدد", "CLOSED": "بسته‌شده"}


def _get(db: Session, key: str, default: str = "") -> str:
    row = db.execute(select(SystemSetting).where(SystemSetting.key == key)).scalar_one_or_none()
    return row.value if row and row.value is not None else default


def relay_config(db: Session) -> tuple[str, str, str]:
    """(base_url, token, inbox_id) — DB override first, then environment."""
    url = _get(db, "support.relay_url") or settings.SUPPORT_RELAY_URL
    token = _get(db, "support.relay_token") or settings.SUPPORT_RELAY_TOKEN
    inbox = _get(db, "support.inbox_id") or settings.SUPPORT_INBOX_ID
    return url.rstrip("/"), token, inbox


def _fa_type(t: str) -> str:
    return TICKET_TYPES.get(t, t)


def ticket_number(db: Session) -> str:
    n = db.execute(select(SupportTicket).order_by(SupportTicket.id.desc()).limit(1)).scalar_one_or_none()
    return f"TCK-{(n.id if n else 0) + 1:06d}"


def compose_message(db: Session, t: SupportTicket) -> str:
    store = {f: _get(db, f"store.{f}") for f in ("name", "legal_name", "phone", "mobile", "address", "city", "postal_code")}
    from .license import hwid, state as lic_state
    try:
        lic = lic_state(db)
    except Exception:  # noqa: BLE001
        lic = {}
    lines = [
        f"🎫 درخواست پشتیبانی جدید — {t.number}",
        f"نوع: {_fa_type(t.type)}   |   اولویت: {PRIORITIES.get(t.priority, t.priority)}",
        f"موضوع: {t.subject}",
        "",
        t.description or "—",
        "",
        "🏪 فروشگاه: " + (store["name"] or "—") + (f" ({store['legal_name']})" if store["legal_name"] else ""),
        "📞 تلفن: " + (store["phone"] or "—") + (f" / همراه: {store['mobile']}" if store["mobile"] else ""),
        "📍 نشانی: " + " ، ".join(x for x in (store["city"], store["address"], store["postal_code"]) if x) or "📍 نشانی: —",
        f"👤 ثبت‌کننده: {t.reporter_name or '—'}" + (f" — تماس: {t.contact}" if t.contact else ""),
        f"🖥 دستگاه: {t.device or '—'}   |   نسخه: {t.app_version or __version__}",
        f"🔑 لایسنس: {lic.get('key_masked') or '—'} ({lic.get('type') or '—'}) · HWID: {hwid()[:12]}",
    ]
    if t.latitude is not None and t.longitude is not None:
        acc = f" (±{int(t.accuracy_m)} متر)" if t.accuracy_m else ""
        lines.append(f"🗺 موقعیت: {t.latitude:.6f}, {t.longitude:.6f}{acc}")
        lines.append(f"https://maps.google.com/?q={t.latitude:.6f},{t.longitude:.6f}")
    if t.attachments:
        lines.append("📎 پیوست: " + t.attachments)
    lines.append(f"🕒 {t.created_at.isoformat(timespec='minutes')}")
    return "\n".join(lines)


class RelayError(RuntimeError):
    pass


def _post(url: str, payload: dict, timeout: float = 15.0) -> dict:
    with httpx.Client(timeout=timeout) as c:
        r = c.post(url, json=payload, headers={"Content-Type": "application/json"})
    try:
        data = r.json()
    except ValueError:
        data = {"raw": r.text[:500]}
    if r.status_code >= 400 or (isinstance(data, dict) and data.get("status") not in (None, "OK")):
        raise RelayError(f"HTTP {r.status_code}: {json.dumps(data, ensure_ascii=False)[:300]}")
    return data


def discover_inbox(db: Session) -> str | None:
    """The inbox id is learned from the relay's update feed the first time the
    owner sends anything to the support bot; cached in system_settings."""
    url, token, inbox = relay_config(db)
    if inbox:
        return inbox
    if not (url and token):
        return None
    try:
        data = _post(f"{url}/{token}/getUpdates", {"limit": 100})
    except Exception as exc:  # noqa: BLE001
        log.warning("support relay inbox discovery failed: %s", exc)
        return None
    owner = (settings.SUPPORT_OWNER_USERNAME or "").lower().lstrip("@")
    found = None
    for u in (data.get("data") or {}).get("updates") or []:
        msg = u.get("new_message") or u.get("updated_message") or {}
        chat_id = u.get("chat_id") or msg.get("chat_id")
        if not chat_id:
            continue
        found = found or chat_id
        sender = (msg.get("sender_username") or msg.get("username") or "").lower().lstrip("@")
        if owner and sender == owner:
            found = chat_id
            break
    if found:
        row = db.execute(select(SystemSetting).where(SystemSetting.key == "support.inbox_id")).scalar_one_or_none()
        if row is None:
            db.add(SystemSetting(key="support.inbox_id", value=found, is_secret=True, description="Support relay inbox"))
        else:
            row.value = found
        db.commit()
    return found


def relay(db: Session, ticket: SupportTicket) -> dict:
    url, token, _ = relay_config(db)
    if not (url and token):
        raise RelayError("CONFIG_MISSING: support relay not configured")
    inbox = discover_inbox(db)
    if not inbox:
        raise RelayError("INBOX_UNKNOWN: support inbox not initialised yet")
    text = compose_message(db, ticket)
    res = _post(f"{url}/{token}/sendMessage", {"chat_id": inbox, "text": text})
    mid = ((res.get("data") or {}).get("message_id")) if isinstance(res, dict) else None
    if ticket.latitude is not None and ticket.longitude is not None:
        try:
            _post(f"{url}/{token}/sendLocation", {"chat_id": inbox, "latitude": f"{ticket.latitude:.6f}",
                                                  "longitude": f"{ticket.longitude:.6f}"})
        except Exception as exc:  # noqa: BLE001 — pin is a bonus; text already carries coordinates
            log.warning("support relay location failed: %s", exc)
    return {"message_id": mid}


@sync_svc.register("SUPPORT_TICKET")
def _handle_ticket(db: Session, payload: dict) -> None:
    t = db.get(SupportTicket, int(payload["ticket_id"]))
    if t is None or t.status in ("SENT", "CLOSED"):
        return
    try:
        res = relay(db, t)
    except Exception as exc:
        t.status = "FAILED"
        t.last_error = str(exc)[:1000]
        db.flush()
        raise
    t.status = "SENT"
    t.sent_at = datetime.utcnow()
    t.relay_ref = str(res.get("message_id") or "")
    t.last_error = None
    db.flush()


def submit(db: Session, *, user_id: int | None, **fields) -> SupportTicket:
    t = SupportTicket(number=ticket_number(db), status="NEW", app_version=__version__, created_by=user_id, **fields)
    db.add(t)
    db.flush()
    sync_svc.enqueue(db, job_type="SUPPORT_TICKET", payload={"ticket_id": t.id}, max_attempts=20,
                     reference_type="SupportTicket", reference_id=t.id, idempotency_key=f"ticket:{t.id}", user_id=user_id)
    # try right away (online case) — failures simply stay in the queue
    try:
        _handle_ticket(db, {"ticket_id": t.id})
        job = db.execute(select(sync_svc.SyncJob).where(sync_svc.SyncJob.idempotency_key == f"ticket:{t.id}")).scalar_one_or_none()
        if job is not None:
            job.status = "COMPLETED"; job.completed_at = datetime.utcnow(); job.attempts = 1
    except Exception as exc:  # noqa: BLE001
        log.info("ticket %s queued for retry: %s", t.number, exc)
    return t
