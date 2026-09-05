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

# Sentinel the UI sends back when the user did not change a secret value
# (the real value is never sent to the client — BUG-010).
SECRET_MASK = "__KEEP__"


class SettingIn(BaseModel):
    key: str
    value: str
    description: str | None = None
    is_secret: bool = False


def _out(s: SystemSetting) -> dict:
    return {
        "key": s.key,
        "value": "" if s.is_secret else s.value,  # secrets are write-only
        "has_value": bool(s.value),
        "description": s.description,
        "is_secret": s.is_secret,
    }


@router.get("")
def list_settings(db: Session = Depends(get_db), _: User = Depends(require_permission("settings.manage"))):
    return [_out(s) for s in db.execute(select(SystemSetting).order_by(SystemSetting.key)).scalars()]


@router.put("")
def upsert_setting(body: SettingIn, db: Session = Depends(get_db),
                   user: User = Depends(require_permission("settings.manage"))):
    s = db.execute(select(SystemSetting).where(SystemSetting.key == body.key)).scalar_one_or_none()
    keep_old_value = body.is_secret and body.value == SECRET_MASK
    if s is None:
        if keep_old_value:
            raise HTTPException(status_code=400, detail="Cannot keep a value for a non-existent setting")
        s = SystemSetting(key=body.key, value=body.value, description=body.description,
                          is_secret=body.is_secret)
        db.add(s)
    else:
        if not keep_old_value:
            s.value = body.value
        if body.description is not None:
            s.description = body.description
        s.is_secret = body.is_secret  # BUG-010: the flag was never updated before
    write_audit(db, action="SETTINGS_CHANGED", user_id=user.id, entity_type="SystemSetting",
                entity_id=None, after={"key": body.key,
                                       "value": "***" if body.is_secret else body.value})
    db.commit()
    return {"key": s.key, "value": "" if s.is_secret else s.value, "is_secret": s.is_secret}
