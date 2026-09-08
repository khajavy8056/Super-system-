"""v1.7 — /api/support: درخواست پشتیبانی (تیکت)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import SupportTicket, User
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
    }


@router.get("/types")
def types(_: User = Depends(get_current_user)):
    return {"types": [{"id": k, "label": v} for k, v in svc.TICKET_TYPES.items()],
            "priorities": [{"id": k, "label": v} for k, v in svc.PRIORITIES.items()]}


@router.get("/tickets")
def list_tickets(limit: int = Query(default=50, ge=1, le=500), db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    rows = db.execute(select(SupportTicket).order_by(SupportTicket.id.desc()).limit(limit)).scalars().all()
    return [_out(t) for t in rows]


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
def resend(ticket_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    t = db.get(SupportTicket, ticket_id)
    if t is None:
        raise HTTPException(status_code=404, detail="درخواست یافت نشد")
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


@router.get("/status")
def relay_status(db: Session = Depends(get_db), _: User = Depends(require_permission("settings.manage"))):
    url, token, inbox = svc.relay_config(db)
    pending = db.execute(select(SupportTicket).where(SupportTicket.status.in_(("NEW", "FAILED")))).scalars().all()
    return {"configured": bool(url and token), "inbox_ready": bool(inbox or svc.discover_inbox(db)), "pending": len(pending)}
