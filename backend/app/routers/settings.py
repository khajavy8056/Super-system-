from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import SystemSetting, User
from ..security import get_current_user, require_permission
from ..services.audit import write_audit

router = APIRouter(prefix="/settings", tags=["settings"])


class SettingIn(BaseModel):
    key: str
    value: str
    description: str | None = None
    is_secret: bool = False


@router.get("")
def list_settings(db: Session = Depends(get_db), _: User = Depends(require_permission("settings.manage"))):
    rows = db.execute(select(SystemSetting).order_by(SystemSetting.key)).scalars().all()
    return [
        {"key": s.key, "value": s.value, "description": s.description,
         "is_secret": s.is_secret, "value_masked": s.is_secret}
        for s in rows
    ]


@router.put("")
def upsert_setting(body: SettingIn, db: Session = Depends(get_db),
                   user: User = Depends(require_permission("settings.manage"))):
    s = db.execute(select(SystemSetting).where(SystemSetting.key == body.key)).scalar_one_or_none()
    if s is None:
        s = SystemSetting(key=body.key, value=body.value, description=body.description,
                          is_secret=body.is_secret)
        db.add(s)
    else:
        s.value = body.value
        if body.description is not None:
            s.description = body.description
    write_audit(db, action="SETTINGS_CHANGED", user_id=user.id, entity_type="SystemSetting",
                entity_id=None, after={"key": body.key, "value": body.value if not body.is_secret else "***"})
    db.commit()
    return {"key": s.key, "value": s.value, "is_secret": s.is_secret}
