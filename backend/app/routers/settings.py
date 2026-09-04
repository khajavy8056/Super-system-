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


# --- Currency (§39) ------------------------------------------------------------

@router.get("/currency")
def get_currency(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    """Base currency used for BOTH storage and display.

    Changing it never rewrites stored amounts — that would silently multiply
    every historical figure by 10. The API therefore reports the base unit and
    the UI formats accordingly.
    """
    from ..services.units import currency_config

    return currency_config(db)


class CurrencyIn(BaseModel):
    code: str


@router.put("/currency")
def set_currency(body: CurrencyIn, db: Session = Depends(get_db),
                 user: User = Depends(require_permission("settings.manage"))):
    from ..models import Invoice
    from ..services.units import CURRENCIES

    code = body.code.strip().upper()
    if code not in CURRENCIES:
        raise HTTPException(status_code=422, detail="UNSUPPORTED_CURRENCY")
    row = db.execute(select(SystemSetting).where(SystemSetting.key == "pos.currency")).scalar_one_or_none()
    old = row.value if row else None
    has_data = db.execute(select(Invoice.id).limit(1)).scalar_one_or_none() is not None
    if row is None:
        db.add(SystemSetting(key="pos.currency", value=code,
                             description="Base currency", is_secret=False))
    else:
        row.value = code
    write_audit(db, action="CURRENCY_CHANGED", user_id=user.id,
                entity_type="SystemSetting", entity_id=None,
                before={"currency": old}, after={"currency": code})
    db.commit()
    return {"code": code, "changed_from": old,
            "warning": ("فاکتورهای ثبت‌شده وجود دارد؛ مقادیر ذخیره‌شده تبدیل نمی‌شوند "
                        "و فقط واحد نمایش تغییر می‌کند." if has_data and old != code else None)}
