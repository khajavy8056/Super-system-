from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import SmsMessage, User
from ..security import get_current_user, require_permission
from ..services import sms as sms_svc
from ..services.audit import write_audit

router = APIRouter(prefix="/sms", tags=["sms"])


class SmsIn(BaseModel):
    phone: str
    text: str


@router.post("/send", status_code=201)
def send(body: SmsIn, db: Session = Depends(get_db),
         user: User = Depends(require_permission("pos.sell"))):
    """Queue an SMS job. Delivery happens out-of-band (never blocks POS, §68)."""
    if not body.phone.strip() or not body.text.strip():
        from fastapi import HTTPException
        raise HTTPException(status_code=422, detail="phone and text are required")
    msg = SmsMessage(phone=body.phone.strip(), text=body.text.strip(), status="PENDING",
                     created_at=datetime.utcnow())
    db.add(msg)
    write_audit(db, action="SMS_QUEUED", user_id=user.id if user else None,
                entity_type="SmsMessage", entity_id=None,
                after={"phone": body.phone, "chars": len(body.text)})
    db.commit()
    return {"id": msg.id, "status": msg.status}


@router.post("/dispatch")
def dispatch(db: Session = Depends(get_db),
             _: User = Depends(require_permission("settings.manage"))):
    """Manually trigger one dispatch pass (also used by the worker + tests)."""
    return sms_svc.dispatch_pending(db)


@router.get("")
def list_sms(db: Session = Depends(get_db), _: User = Depends(require_permission("settings.manage"))):
    rows = db.execute(select(SmsMessage).order_by(SmsMessage.created_at.desc()).limit(100)).scalars().all()
    return [
        {"id": m.id, "phone": m.phone, "text": m.text, "status": m.status,
         "retry_count": m.retry_count, "error_message": m.error_message,
         "sent_at": m.sent_at.isoformat() if m.sent_at else None}
        for m in rows
    ]


@router.post("/{sms_id}/retry")
def retry(sms_id: int, db: Session = Depends(get_db),
          user: User = Depends(require_permission("settings.manage"))):
    """§171 — re-queue a FAILED message; the worker/dispatch delivers it."""
    from fastapi import HTTPException
    try:
        msg = sms_svc.retry_message(db, sms_id)
    except sms_svc.SmsProviderError as e:
        raise HTTPException(status_code=409 if e.kind == "ALREADY_SENT" else 404,
                            detail={"code": e.kind, "message": e.detail})
    write_audit(db, action="SMS_RETRY_REQUESTED", user_id=user.id, entity_type="SmsMessage",
                entity_id=msg.id)
    db.commit()
    return {"id": msg.id, "status": msg.status}


@router.post("/test-connection")
def test_connection(db: Session = Depends(get_db),
                    _: User = Depends(require_permission("settings.manage"))):
    """§177 — provider connectivity check (no customer SMS is sent)."""
    return sms_svc.test_connection(db)


@router.post("/daily-report", status_code=201)
def daily_report(db: Session = Depends(get_db),
                 user: User = Depends(require_permission("reports.view"))):
    """§175 — queue the management summary SMS to the admin phone."""
    from fastapi import HTTPException
    try:
        msg = sms_svc.queue_daily_report(db)
    except sms_svc.SmsProviderError as e:
        raise HTTPException(status_code=422, detail={"code": e.kind, "message": e.detail})
    write_audit(db, action="SMS_QUEUED", user_id=user.id, entity_type="SmsMessage", entity_id=msg.id,
                after={"kind": "daily_report"})
    db.commit()
    return {"id": msg.id, "status": msg.status, "text": msg.text}


@router.get("/templates")
def templates(db: Session = Depends(get_db), _: User = Depends(require_permission("settings.manage"))):
    """§166 — the editable SMS patterns and their placeholders."""
    out = []
    for kind, (key, default) in sms_svc.TEMPLATE_KEYS.items():
        import re as _re
        out.append({"kind": kind, "key": key, "default": default,
                    "value": sms_svc.get_setting(db, key, default),
                    "placeholders": sorted(set(_re.findall(r"{(\w+)}", default)))})
    return out
