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
from ..models import SupportMessage, SupportTicket, SystemSetting
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
        f"🎫 درخواست پشتیبانی جدید — {_ticket_ref(db, t)}",
        f"🆔 کد فروشگاه: {install_code(db)}   (برای پاسخ: روی همین پیام Reply بزنید یا پیام را با «{_ticket_ref(db, t)}» شروع کنید)",
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


def install_id() -> str:
    """8 hex chars, stable per machine (derived from the licence HWID)."""
    import hashlib
    from .license import hwid
    return hashlib.sha1(hwid().encode()).hexdigest()[:8].upper()


def install_code(db: Session) -> str:
    """Short, stable, human-readable id of THIS installation (hundreds of stores
    may talk to the same support inbox — every message carries it)."""
    name = _get(db, "store.name") or "فروشگاه"
    return f"{name} #{install_id()}"


def _ticket_ref(db: Session, t: SupportTicket) -> str:
    """Globally unique thread key: TCK-000001@HWID8 — used in the message text
    so a reply can be routed even when the operator does not use Reply."""
    return f"{t.number}@{install_id()}"


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
    if mid:
        ticket.relay_ref = str(mid)
    # attachments recorded as OUT messages without text are sent as files
    for m in db.execute(select(SupportMessage).where(SupportMessage.ticket_id == ticket.id, SupportMessage.direction == "OUT",
                                                     SupportMessage.status.in_(("NEW", "FAILED")))).scalars().all():
        try:
            _send_out_message(db, ticket, m, inbox, url, token)
        except Exception as exc:  # noqa: BLE001
            m.status = "FAILED"; m.last_error = str(exc)[:500]
    return {"message_id": mid}


# ---------------------------------------------------------------------------
# v1.7.1 — two-way conversation + attachments
# ---------------------------------------------------------------------------
_FILE_TYPES = {".jpg": "Image", ".jpeg": "Image", ".png": "Image", ".gif": "Image", ".webp": "Image", ".mp4": "Video", ".mp3": "Music"}


def _upload_file(url: str, token: str, path: str, name: str) -> str:
    import os
    ext = os.path.splitext(name)[1].lower()
    ftype = _FILE_TYPES.get(ext, "File")
    r = _post(f"{url}/{token}/requestSendFile", {"type": ftype})
    up = (r.get("data") or {}).get("upload_url")
    if not up:
        raise RelayError("UPLOAD_URL_MISSING")
    with open(path, "rb") as fh, httpx.Client(timeout=120) as c:
        rr = c.post(up, files={"file": (name, fh)})
    try:
        data = rr.json()
    except ValueError:
        data = {}
    fid = (data.get("data") or {}).get("file_id") or data.get("file_id")
    if rr.status_code >= 400 or not fid:
        raise RelayError(f"UPLOAD_FAILED: HTTP {rr.status_code}")
    return fid


def _send_out_message(db: Session, t: SupportTicket, m: SupportMessage, inbox: str, url: str, token: str) -> None:
    head = f"💬 {_ticket_ref(db, t)} — {install_code(db)}\n"
    payload = {"chat_id": inbox, "text": head + (m.text or "")}
    if t.relay_ref:
        payload["reply_to_message_id"] = t.relay_ref
    if m.attachment_path:
        import os
        full = os.path.join(settings.MEDIA_DIR, m.attachment_path)
        fid = _upload_file(url, token, full, m.attachment_name or os.path.basename(full))
        payload["file_id"] = fid
        res = _post(f"{url}/{token}/sendFile", payload)
    else:
        res = _post(f"{url}/{token}/sendMessage", payload)
    m.relay_message_id = str(((res.get("data") or {}).get("message_id")) or "")
    m.status = "SENT"; m.last_error = None
    db.flush()


def add_message(db: Session, ticket: SupportTicket, *, user_id: int | None, text: str | None,
                attachment: tuple[str, str, int] | None = None) -> SupportMessage:
    """Store an outgoing message (text and/or file) and try to relay it now."""
    m = SupportMessage(ticket_id=ticket.id, direction="OUT", text=text, status="NEW", created_by=user_id, is_read=True)
    if attachment:
        m.attachment_path, m.attachment_name, m.attachment_size = attachment
    db.add(m); db.flush()
    if ticket.status == "CLOSED":
        ticket.status = "SENT"
    try:
        url, token, _ = relay_config(db)
        inbox = discover_inbox(db)
        if not (url and token and inbox):
            raise RelayError("INBOX_UNKNOWN")
        if not ticket.relay_ref:  # ticket itself never left → send it first
            relay(db, ticket); ticket.status = "SENT"; ticket.sent_at = datetime.utcnow()
        if m.status != "SENT":
            _send_out_message(db, ticket, m, inbox, url, token)
    except Exception as exc:  # noqa: BLE001
        m.status = "FAILED"; m.last_error = str(exc)[:500]
        log.info("support message %s queued: %s", m.id, exc)
    db.flush()
    return m


def resend_pending_messages(db: Session) -> int:
    """Retry OUT messages that could not be relayed yet (called by the poller)."""
    url, token, _ = relay_config(db)
    inbox = discover_inbox(db) if url and token else None
    if not inbox:
        return 0
    n = 0
    rows = db.execute(select(SupportMessage).where(SupportMessage.direction == "OUT", SupportMessage.status.in_(("NEW", "FAILED")))).scalars().all()
    for m in rows:
        t = db.get(SupportTicket, m.ticket_id)
        if t is None:
            continue
        try:
            if not t.relay_ref:
                relay(db, t); t.status = "SENT"; t.sent_at = datetime.utcnow()
            if m.status != "SENT":
                _send_out_message(db, t, m, inbox, url, token)
            n += 1
        except Exception as exc:  # noqa: BLE001
            m.status = "FAILED"; m.last_error = str(exc)[:500]
    db.commit()
    return n


_REF_RE = None


def _match_ticket(db: Session, msg: dict) -> SupportTicket | None:
    """Route an inbound support message to OUR ticket.

    1. Reply to a message this install sent (reply_to_message_id == ticket.relay_ref
       or one of its messages' relay ids) — the safe path with hundreds of stores.
    2. Text starts with / contains ``TCK-000123@HWID8`` (our own hwid only).
    Anything else is ignored: it belongs to another store."""
    import re
    global _REF_RE
    mine = install_id()
    rid = msg.get("reply_to_message_id")
    if rid:
        t = db.execute(select(SupportTicket).where(SupportTicket.relay_ref == str(rid))).scalar_one_or_none()
        if t:
            return t
        m = db.execute(select(SupportMessage).where(SupportMessage.relay_message_id == str(rid))).scalar_one_or_none()
        if m:
            return db.get(SupportTicket, m.ticket_id)
    text = msg.get("text") or ""
    if _REF_RE is None:
        _REF_RE = re.compile(r"(TCK-\d{6})@([0-9A-F]{8})", re.I)
    for num, hw in _REF_RE.findall(text):
        if hw.upper() == mine:
            t = db.execute(select(SupportTicket).where(SupportTicket.number == num.upper())).scalar_one_or_none()
            if t:
                return t
    return None


def _download_file(url: str, token: str, file_id: str, name: str) -> tuple[str, str, int] | None:
    import os, re as _re, uuid
    r = _post(f"{url}/{token}/getFile", {"file_id": file_id})
    dl = (r.get("data") or {}).get("download_url")
    if not dl:
        return None
    safe = _re.sub(r"[^\w.\-]+", "_", name or "file")[:80] or "file"
    rel = os.path.join("support", f"{uuid.uuid4().hex[:12]}_{safe}")
    full = os.path.join(settings.MEDIA_DIR, rel)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with httpx.Client(timeout=120, follow_redirects=True) as c, open(full, "wb") as fh:
        with c.stream("GET", dl) as resp:
            size = 0
            for chunk in resp.iter_bytes():
                fh.write(chunk); size += len(chunk)
                if size > 60 * 1024 * 1024:
                    break
    return rel.replace(os.sep, "/"), safe, size


def poll_replies(db: Session, limit: int = 100) -> int:
    """Fetch the relay feed and file support replies under the right ticket.
    Uses ``support.offset_id`` so every update is examined once."""
    url, token, inbox = relay_config(db)
    if not (url and token):
        return 0
    inbox = inbox or discover_inbox(db)
    offset = _get(db, "support.offset_id")
    payload = {"limit": limit}
    if offset:
        payload["offset_id"] = offset
    try:
        data = _post(f"{url}/{token}/getUpdates", payload)
    except Exception as exc:  # noqa: BLE001
        log.debug("support poll failed: %s", exc)
        return 0
    d = data.get("data") or {}
    got = 0
    from .notifications import notify
    for u in d.get("updates") or []:
        msg = u.get("new_message") or {}
        if not msg or (inbox and str(u.get("chat_id") or "") != str(inbox)):
            continue
        mid = str(msg.get("message_id") or "")
        if msg.get("sender_type") == "Bot":
            continue
        if mid and db.execute(select(SupportMessage.id).where(SupportMessage.relay_message_id == mid, SupportMessage.direction == "IN")).first():
            continue
        t = _match_ticket(db, msg)
        if t is None:
            continue
        text = msg.get("text") or ""
        # strip our own routing prefix if the operator typed it
        import re
        text = re.sub(r"^\s*TCK-\d{6}@[0-9A-Fa-f]{8}\s*[:\-—]?\s*", "", text)
        m = SupportMessage(ticket_id=t.id, direction="IN", text=text or None, relay_message_id=mid or None, status="RECEIVED", is_read=False)
        f = msg.get("file") or {}
        if f.get("file_id"):
            try:
                att = _download_file(url, token, f["file_id"], f.get("file_name") or "file")
                if att:
                    m.attachment_path, m.attachment_name, m.attachment_size = att
            except Exception as exc:  # noqa: BLE001
                m.text = (m.text or "") + f"\n[پیوست دریافت نشد: {exc}]"
        db.add(m); db.flush()
        if t.status in ("NEW", "FAILED"):
            t.status = "SENT"
        notify(db, type="SUPPORT_REPLY", title=f"پاسخ پشتیبانی — {t.number}", body=(text or "پیوست")[:200],
               severity="INFO", reference_type="SupportTicket", reference_id=t.id)
        got += 1
    nxt = d.get("next_offset_id")
    if nxt:
        row = db.execute(select(SystemSetting).where(SystemSetting.key == "support.offset_id")).scalar_one_or_none()
        if row is None:
            db.add(SystemSetting(key="support.offset_id", value=str(nxt), is_secret=False, description="Support relay feed cursor"))
        else:
            row.value = str(nxt)
    db.commit()
    return got


import threading as _threading
_poll_stop = _threading.Event()
_poll_thread = None


def start_poller(session_factory, interval: int = 20) -> None:
    global _poll_thread
    if _poll_thread and _poll_thread.is_alive():
        return
    _poll_stop.clear()

    def run():
        _poll_stop.wait(interval)
        while not _poll_stop.is_set():
            try:
                db = session_factory()
                try:
                    resend_pending_messages(db)
                    poll_replies(db)
                finally:
                    db.close()
            except Exception as exc:  # noqa: BLE001
                log.debug("support poller tick failed: %s", exc)
            _poll_stop.wait(interval)

    _poll_thread = _threading.Thread(target=run, name="support-poller", daemon=True)
    _poll_thread.start()


def stop_poller() -> None:
    _poll_stop.set()


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
