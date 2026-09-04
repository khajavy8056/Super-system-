from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import SmsMessage, User
from ..security import get_current_user, require_permission
from ..services.audit import write_audit

router = APIRouter(prefix="/sms", tags=["sms"])


class SmsIn(BaseModel):
    phone: str
    text: str


@router.post("/send", status_code=201)
def send(body: SmsIn, db: Session = Depends(get_db), _: User = Depends(require_permission("settings.manage"))):
    """Queue an SMS job. Delivery happens out-of-band (never blocks POS, §68)."""
    msg = SmsMessage(phone=body.phone, text=body.text, status="PENDING",
                     created_at=datetime.utcnow())
    db.add(msg)
    write_audit(db, action="SMS_QUEUED", entity_type="SmsMessage", entity_id=None)
    db.commit()
    return {"id": msg.id, "status": msg.status}


@router.get("")
def list_sms(db: Session = Depends(get_db), _: User = Depends(require_permission("settings.manage"))):
    rows = db.execute(select(SmsMessage).order_by(SmsMessage.created_at.desc()).limit(100)).scalars().all()
    return [
        {"id": m.id, "phone": m.phone, "status": m.status, "retry_count": m.retry_count,
         "error_message": m.error_message, "sent_at": m.sent_at.isoformat() if m.sent_at else None}
        for m in rows
    ]
