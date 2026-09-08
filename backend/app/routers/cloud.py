"""v1.7 — /api/cloud: internet sync through the owner's Google Drive (appDataFolder)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import User
from ..security import get_current_user, require_permission
from ..services import cloud as svc
from ..services.audit import write_audit

router = APIRouter(prefix="/cloud", tags=["cloud"])


def _raise(exc: svc.CloudError):
    raise HTTPException(status_code=400, detail={"code": exc.code, "message": str(exc)})


class ConnectIn(BaseModel):
    client_id: str
    client_secret: str


@router.get("/status")
def status(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    return svc.status(db)


@router.post("/connect/start")
def connect_start(body: ConnectIn, db: Session = Depends(get_db), user: User = Depends(require_permission("settings.manage"))):
    try:
        out = svc.device_start(db, body.client_id, body.client_secret)
    except svc.CloudError as exc:
        _raise(exc)
    write_audit(db, action="CLOUD_CONNECT_STARTED", user_id=user.id, entity_type="Cloud"); db.commit()
    return out


@router.post("/connect/poll")
def connect_poll(db: Session = Depends(get_db), user: User = Depends(require_permission("settings.manage"))):
    try:
        out = svc.device_poll(db)
    except svc.CloudError as exc:
        _raise(exc)
    if out.get("status") == "CONNECTED":
        write_audit(db, action="CLOUD_CONNECTED", user_id=user.id, entity_type="Cloud", reference=out.get("account")); db.commit()
    return out


@router.post("/disconnect")
def disconnect(db: Session = Depends(get_db), user: User = Depends(require_permission("settings.manage"))):
    svc.disconnect(db)
    write_audit(db, action="CLOUD_DISCONNECTED", user_id=user.id, entity_type="Cloud"); db.commit()
    return {"ok": True}


@router.post("/sync-now")
def sync_now(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    try:
        return svc.sync_now(db)
    except svc.CloudError as exc:
        _raise(exc)


@router.get("/device-credentials")
def device_credentials(db: Session = Depends(get_db), _: User = Depends(require_permission("settings.manage"))):
    """Handed to a paired phone (inside the QR) so it can reach the same mailbox."""
    return svc.credentials_for_device(db) or {}
