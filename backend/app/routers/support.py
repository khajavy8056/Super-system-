"""v1.7 — /api/support: درخواست پشتیبانی (تیکت)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import SupportMessage, SupportTicket, User
from ..security import get_current_user, require_permission
from ..services import support as svc
from ..services.audit import write_audit

router = APIRouter(prefix="/support", tags=["support"])


class TicketIn(BaseModel):
    type: str = Field(default="BUG")
    priority: str = Field(default="NORMAL")
    subject: str = Field(min_length=3, max_length=160)
    description: str | None = Field(default=None, max_length=4000)
    contact: str | None = Field(default=None, max_length=120)
    device: str | None = Field(default=None, max_length=64)
    latitude: float | None = None
    longitude: float | None = None
    accuracy_m: float | None = None
    attachments: str | None = Field(default=None, max_length=2000)


def _out(t: SupportTicket) -> dict:
    return {
        "id": t.id, "number": t.number, "type": t.type, "type_label": svc.TICKET_TYPES.get(t.type, t.type),
        "priority": t.priority, "priority_label": svc.PRIORITIES.get(t.priority, t.priority),
        "subject": t.subject, "description": t.description, "contact": t.contact, "device": t.device,
        "reporter_name": t.reporter_name, "app_version": t.app_version,
        "latitude": t.latitude, "longitude": t.longitude, "accuracy_m": t.accuracy_m,
        "status": t.status, "status_label": svc.STATUSES.get(t.status, t.status),
        "sent_at": t.sent_at.isoformat() if t.sent_at else None,
        "created_at": t.created_at.isoformat() if t.created_at else None,
        "last_error": None if t.status == "SENT" else (("ارسال هنوز انجام نشده؛ به‌صورت خودکار تلاش می‌شود") if t.last_error else None),
        "unread": getattr(t, "_unread", 0),
    }


def _msg_out(m: SupportMessage) -> dict:
    return {"id": m.id, "ticket_id": m.ticket_id, "direction": m.direction, "text": m.text,
            "attachment_url": f"/media/{m.attachment_path}" if m.attachment_path else None,
            "attachment_name": m.attachment_name, "attachment_size": m.attachment_size,
            "status": m.status, "status_label": {"NEW": "در صف ارسال", "SENT": "ارسال شد", "FAILED": "در انتظار ارسال مجدد", "RECEIVED": "دریافت شد"}.get(m.status, m.status),
            "is_read": m.is_read, "created_at": m.created_at.isoformat() if m.created_at else None}


@router.get("/types")
def types(_: User = Depends(get_current_user)):
    return {"types": [{"id": k, "label": v} for k, v in svc.TICKET_TYPES.items()],
            "priorities": [{"id": k, "label": v} for k, v in svc.PRIORITIES.items()]}


def _support_desk(user) -> bool:
    """build-490 (§۱/§۷) — میز پشتیبانی (دیدن همهٔ تیکت‌ها) برای مدیریت؛ بقیه فقط تیکت‌های خودشان."""
    from ..security import has_permission
    return has_permission(user, "settings.manage") or has_permission(user, "users.manage")


@router.get("/tickets")
def list_tickets(limit: int = Query(default=50, ge=1, le=500), db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    q = select(SupportTicket).order_by(SupportTicket.id.desc())
    if not _support_desk(user):
        q = q.where(SupportTicket.created_by == user.id)   # نشت تیکت‌های دیگران ممنوع
    rows = db.execute(q.limit(limit)).scalars().all()
    from sqlalchemy import func
    unread = dict(db.execute(select(SupportMessage.ticket_id, func.count(SupportMessage.id))
                             .where(SupportMessage.direction == "IN", SupportMessage.is_read.is_(False))
                             .group_by(SupportMessage.ticket_id)).all())
    for t in rows:
        t._unread = int(unread.get(t.id, 0))
    return [_out(t) for t in rows]


# ---------------------------------------------------------------------------
# v1.0.0 (RASA) — «درخواست پشتیبانی از صفحهٔ قفل»
# ---------------------------------------------------------------------------
# چرا این مسیر وجود دارد: دروازهٔ لایسنس همهٔ /api را با ۴۰۲ می‌بندد تا فروشگاه
# بدون لایسنس کار نکند — و پیش از این «پشتیبانی» را هم می‌بست. نتیجه: فروشگاهی
# که لایسنسش فعال نمی‌شد، نه می‌توانست کلید بگیرد و نه می‌توانست بگوید کلید کار
# نمی‌کند (باگ گزارش‌شدهٔ مالک: «از ویندوز تیکت ثبت نمی‌شود»). روی گوشی این
# مشکل دیده نمی‌شد چون حالت مستقل گوشی مستقیم به رله وصل می‌شود.
#
# این مسیر عمداً بدون نشست کار می‌کند (روی صفحهٔ قفل، کاربر وارد نشده است) اما
# سه محدودیت سخت دارد تا سطح حمله باز نشود:
#   ۱) فقط نوع LICENSE — هیچ تیکت دلخواهی از این راه ثبت نمی‌شود؛
#   ۲) سقف تعداد در ساعت برای هر نصب (۵) و برای هر IP (۱۰)؛
#   ۳) همان رلهٔ خودِ فروشگاه؛ مقصد پیام تغییر نمی‌کند.
# اگر کاربر وارد شده باشد، مسیر معمولی `/tickets` استفاده می‌شود.
_LOCKED_MAX_PER_INSTALL_HOUR = 5
_LOCKED_MAX_PER_IP_HOUR = 10
_LOCKED_HITS: dict[str, list[float]] = {}


def _locked_rate_ok(key: str, limit: int) -> bool:
    import time as _t
    now = _t.time()
    hits = [x for x in _LOCKED_HITS.get(key, []) if now - x < 3600]
    if len(hits) >= limit:
        _LOCKED_HITS[key] = hits
        return False
    hits.append(now)
    _LOCKED_HITS[key] = hits
    return True


class LockedTicketIn(BaseModel):
    """حداقلِ لازم برای اینکه پشتیبانی بتواند کمک کند — بدون هیچ دادهٔ فروش."""

    description: str = Field(min_length=10, max_length=2000)
    contact: str | None = Field(default=None, max_length=120)
    device: str | None = Field(default=None, max_length=64)


@router.post("/locked-ticket", status_code=201)
def create_locked_ticket(body: LockedTicketIn, request: Request,
                         db: Session = Depends(get_db)):
    """درخواست کمک از صفحهٔ قفل لایسنس (بدون نشست، فقط نوع «لایسنس»)."""
    from ..services.license import hwid
    ip = (request.client.host if request.client else "?") or "?"
    if not _locked_rate_ok(f"ip:{ip}", _LOCKED_MAX_PER_IP_HOUR) or \
       not _locked_rate_ok(f"hw:{hwid()}", _LOCKED_MAX_PER_INSTALL_HOUR):
        raise HTTPException(status_code=429, detail={"code": "TOO_MANY",
                                                     "message": "درخواست‌های زیادی ثبت شد؛ کمی بعد دوباره تلاش کنید یا با شمارهٔ پشتیبانی تماس بگیرید"})
    try:
        from ..services import license as lic_svc  # noqa: WPS433 — the lock screen's own view
        lic = lic_svc.state(db)
    except Exception:  # noqa: BLE001 — the licence state is context, never a blocker
        lic = {}
    who = db.execute(select(User).order_by(User.id)).scalars().first()
    extra = ["", f"🆔 شناسهٔ دستگاه: {hwid()}"]
    if lic:
        extra.append(f"وضعیت لایسنس: {lic.get('status') or '—'} · فعال: {'بله' if lic.get('activated') else 'خیر'}"
                     f" · دلیل: {lic.get('reason') or '—'}")
    t = svc.submit(db, user_id=who.id if who else None, reporter_name=(who.full_name or who.username) if who else None,
                   type="LICENSE", priority="HIGH", subject="مشکل لایسنس — درخواست کمک از صفحهٔ قفل",
                   description=body.description + "\n".join(extra), contact=body.contact,
                   device=(body.device or "Windows") + " (قفل لایسنس)")
    write_audit(db, action="SUPPORT_TICKET_CREATED", user_id=who.id if who else None,
                entity_type="SupportTicket", entity_id=t.id, reference=t.number)
    db.commit()
    db.refresh(t)
    return _out(t)


@router.post("/tickets", status_code=201)
def create_ticket(body: TicketIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if body.type not in svc.TICKET_TYPES:
        raise HTTPException(status_code=422, detail={"code": "BAD_TYPE", "message": "نوع درخواست نامعتبر است"})
    if body.priority not in svc.PRIORITIES:
        raise HTTPException(status_code=422, detail={"code": "BAD_PRIORITY", "message": "اولویت نامعتبر است"})
    t = svc.submit(db, user_id=user.id, reporter_name=user.full_name or user.username, **body.model_dump())
    write_audit(db, action="SUPPORT_TICKET_CREATED", user_id=user.id, entity_type="SupportTicket", entity_id=t.id, reference=t.number)
    db.commit()
    db.refresh(t)
    return _out(t)


@router.post("/tickets/{ticket_id}/resend")
def resend(ticket_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    t = db.get(SupportTicket, ticket_id)
    if t is None or (not _support_desk(user) and t.created_by != user.id):
        raise HTTPException(status_code=404, detail="درخواست یافت نشد")   # build-490
    try:
        svc._handle_ticket(db, {"ticket_id": t.id})
        db.commit()
    except Exception:  # noqa: BLE001
        db.commit()
    db.refresh(t)
    return _out(t)


@router.post("/tickets/{ticket_id}/close")
def close(ticket_id: int, db: Session = Depends(get_db), user: User = Depends(require_permission("settings.manage"))):
    t = db.get(SupportTicket, ticket_id)
    if t is None:
        raise HTTPException(status_code=404, detail="درخواست یافت نشد")
    t.status = "CLOSED"
    write_audit(db, action="SUPPORT_TICKET_CLOSED", user_id=user.id, entity_type="SupportTicket", entity_id=t.id, reference=t.number)
    db.commit()
    return _out(t)


@router.get("/tickets/{ticket_id}/messages")
def messages(ticket_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    t = db.get(SupportTicket, ticket_id)
    if t is None or (not _support_desk(user) and t.created_by != user.id):
        raise HTTPException(status_code=404, detail="درخواست یافت نشد")   # build-490 — تیکت دیگران دیده نمی‌شود
    rows = db.execute(select(SupportMessage).where(SupportMessage.ticket_id == ticket_id).order_by(SupportMessage.id.asc())).scalars().all()
    for m in rows:
        if m.direction == "IN" and not m.is_read:
            m.is_read = True
    db.commit()
    return {"ticket": _out(t), "messages": [_msg_out(m) for m in rows]}


_MAX_ATTACH = 50 * 1024 * 1024


@router.post("/tickets/{ticket_id}/messages", status_code=201)
async def post_message(ticket_id: int, text: str | None = Form(default=None), file: UploadFile | None = File(default=None),
                       db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Store-side reply / follow-up: text and/or ONE attachment (≤50 MB; images, PDF, logs, zip…)."""
    t = db.get(SupportTicket, ticket_id)
    if t is None:
        raise HTTPException(status_code=404, detail="درخواست یافت نشد")
    text = (text or "").strip() or None
    att = None
    if file is not None and file.filename:
        import os, re, uuid
        from ..config import settings as _cfg
        safe = re.sub(r"[^\w.\-]+", "_", file.filename)[:80] or "file"
        rel = os.path.join("support", f"{uuid.uuid4().hex[:12]}_{safe}")
        full = os.path.join(_cfg.MEDIA_DIR, rel)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        size = 0
        with open(full, "wb") as fh:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > _MAX_ATTACH:
                    fh.close(); os.remove(full)
                    raise HTTPException(status_code=413, detail={"code": "TOO_LARGE", "message": "حجم پیوست حداکثر ۵۰ مگابایت است"})
                fh.write(chunk)
        att = (rel.replace(os.sep, "/"), safe, size)
    if not text and not att:
        raise HTTPException(status_code=422, detail={"code": "EMPTY", "message": "متن یا پیوست لازم است"})
    m = svc.add_message(db, t, user_id=user.id, text=text, attachment=att)
    write_audit(db, action="SUPPORT_MESSAGE_SENT", user_id=user.id, entity_type="SupportTicket", entity_id=t.id, reference=t.number)
    db.commit(); db.refresh(m)
    return _msg_out(m)


@router.post("/poll")
def poll_now(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    """Manual «check for replies» (the background poller does this every 20 s)."""
    n = svc.resend_pending_messages(db)
    got = svc.poll_replies(db)
    return {"sent": n, "received": got}


@router.get("/unread")
def unread(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    from sqlalchemy import func
    n = db.execute(select(func.count(SupportMessage.id)).where(SupportMessage.direction == "IN", SupportMessage.is_read.is_(False))).scalar_one()
    return {"unread": int(n)}


@router.get("/status")
def relay_status(db: Session = Depends(get_db), _: User = Depends(require_permission("settings.manage"))):
    url, token, inbox = svc.relay_config(db)
    pending = db.execute(select(SupportTicket).where(SupportTicket.status.in_(("NEW", "FAILED")))).scalars().all()
    return {"configured": bool(url and token), "inbox_ready": bool(inbox or svc.discover_inbox(db)), "pending": len(pending)}
