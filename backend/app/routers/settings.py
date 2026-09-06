from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings as app_settings
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


# ---------------------------------------------------------------------------
# Store profile (§25) — grouped accessor so the UI and the receipt printer do
# not each hand-assemble a dozen `store.*` keys.
# ---------------------------------------------------------------------------
_STORE_FIELDS = [
    "name", "legal_name", "phone", "mobile", "address", "city",
    "postal_code", "tax_id", "logo_path", "receipt_note",
]


def _get(db: Session, key: str, default: str = "") -> str:
    row = db.execute(
        select(SystemSetting).where(SystemSetting.key == key)
    ).scalar_one_or_none()
    return row.value if row and row.value is not None else default


class StoreProfileIn(BaseModel):
    name: str | None = None
    legal_name: str | None = None
    phone: str | None = None
    mobile: str | None = None
    address: str | None = None
    city: str | None = None
    postal_code: str | None = None
    tax_id: str | None = None
    logo_path: str | None = None
    receipt_note: str | None = None


@router.get("/store-profile")
def get_store_profile(db: Session = Depends(get_db),
                      _: User = Depends(get_current_user)):
    """Readable by any signed-in user: the POS and receipts need it."""
    return {f: _get(db, f"store.{f}") for f in _STORE_FIELDS}


@router.put("/store-profile")
def put_store_profile(body: StoreProfileIn, db: Session = Depends(get_db),
                      user: User = Depends(require_permission("settings.manage"))):
    changes = body.model_dump(exclude_unset=True)
    for field, value in changes.items():
        key = f"store.{field}"
        row = db.execute(
            select(SystemSetting).where(SystemSetting.key == key)
        ).scalar_one_or_none()
        if row is None:
            row = SystemSetting(key=key, value=value or "", is_secret=False)
            db.add(row)
        else:
            row.value = value or ""
    write_audit(db, action="STORE_PROFILE_UPDATE", user_id=user.id,
                entity_type="SystemSetting", after=changes)
    db.commit()
    return {f: _get(db, f"store.{f}") for f in _STORE_FIELDS}


_LOGO_TYPES = {"image/png": ".png", "image/jpeg": ".jpg", "image/svg+xml": ".svg", "image/webp": ".webp"}
_LOGO_MAX = 2 * 1024 * 1024


def _set(db: Session, key: str, value: str) -> None:
    row = db.execute(select(SystemSetting).where(SystemSetting.key == key)).scalar_one_or_none()
    if row is None:
        db.add(SystemSetting(key=key, value=value, is_secret=False))
    else:
        row.value = value


@router.post("/store-profile/logo")
async def upload_store_logo(file: UploadFile = File(...), db: Session = Depends(get_db),
                            user: User = Depends(require_permission("settings.manage"))):
    """Store logo (§214): PNG/JPEG/SVG/WebP ≤ 2 MB, served from /media and used
    on receipts, the sidebar and the About page."""
    ext = _LOGO_TYPES.get((file.content_type or "").lower())
    if ext is None:
        raise HTTPException(status_code=400, detail={
            "code": "UNSUPPORTED_TYPE",
            "message": "فرمت لوگو باید PNG، JPEG، SVG یا WebP باشد."})
    data = await file.read()
    if len(data) > _LOGO_MAX:
        raise HTTPException(status_code=413, detail={
            "code": "TOO_LARGE", "message": "حجم لوگو نباید بیش از ۲ مگابایت باشد."})
    if not data:
        raise HTTPException(status_code=400, detail={"code": "EMPTY", "message": "فایل خالی است."})
    if ext == ".png" and not data.startswith(b"\x89PNG"):
        raise HTTPException(status_code=400, detail={"code": "CORRUPT", "message": "فایل PNG معتبر نیست."})
    if ext == ".jpg" and not data.startswith(b"\xff\xd8"):
        raise HTTPException(status_code=400, detail={"code": "CORRUPT", "message": "فایل JPEG معتبر نیست."})
    media = Path(app_settings.MEDIA_DIR)
    media.mkdir(parents=True, exist_ok=True)
    for old in media.glob("store-logo.*"):
        try:
            old.unlink()
        except OSError:
            pass
    dest = media / f"store-logo{ext}"
    dest.write_bytes(data)
    import time as _t
    url = f"/media/{dest.name}?v={int(_t.time())}"
    before = _get(db, "store.logo_path")
    _set(db, "store.logo_path", url)
    write_audit(db, action="STORE_LOGO_UPDATED", user_id=user.id, entity_type="SystemSetting",
                before={"logo_path": before}, after={"logo_path": url, "bytes": len(data)})
    db.commit()
    return {"logo_path": url, "bytes": len(data)}


@router.delete("/store-profile/logo")
def delete_store_logo(db: Session = Depends(get_db),
                      user: User = Depends(require_permission("settings.manage"))):
    media = Path(app_settings.MEDIA_DIR)
    for old in media.glob("store-logo.*"):
        try:
            old.unlink()
        except OSError:
            pass
    before = _get(db, "store.logo_path")
    _set(db, "store.logo_path", "")
    write_audit(db, action="STORE_LOGO_REMOVED", user_id=user.id, entity_type="SystemSetting",
                before={"logo_path": before}, after={"logo_path": ""})
    db.commit()
    return {"logo_path": ""}


# ---------------------------------------------------------------------------
# Appearance (§23)
# ---------------------------------------------------------------------------
class ThemeIn(BaseModel):
    theme: str
    light_at: str | None = None
    dark_at: str | None = None


@router.get("/theme")
def get_theme(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    """Theme preference + the schedule used when the mode is `auto`.

    `resolved` is what the client should apply right now, so the schedule is
    evaluated in one place instead of being reimplemented per client.
    """
    from datetime import datetime

    mode = (_get(db, "ui.theme", "auto") or "auto").lower()
    light_at = _get(db, "ui.theme_light_at", "07:00")
    dark_at = _get(db, "ui.theme_dark_at", "19:00")

    resolved = mode
    if mode == "auto":
        now = datetime.now().strftime("%H:%M")
        # light between light_at and dark_at, dark otherwise (handles wrap-around)
        if light_at <= dark_at:
            resolved = "light" if light_at <= now < dark_at else "dark"
        else:
            resolved = "light" if (now >= light_at or now < dark_at) else "dark"

    return {"theme": mode, "light_at": light_at, "dark_at": dark_at,
            "resolved": resolved}


@router.put("/theme")
def put_theme(body: ThemeIn, db: Session = Depends(get_db),
              user: User = Depends(get_current_user)):
    mode = (body.theme or "auto").lower()
    if mode not in ("auto", "light", "dark"):
        raise HTTPException(status_code=422, detail={
            "code": "INVALID_THEME", "message": "theme must be auto|light|dark"})

    updates = {"ui.theme": mode}
    if body.light_at:
        updates["ui.theme_light_at"] = body.light_at
    if body.dark_at:
        updates["ui.theme_dark_at"] = body.dark_at

    for key, value in updates.items():
        row = db.execute(
            select(SystemSetting).where(SystemSetting.key == key)
        ).scalar_one_or_none()
        if row is None:
            db.add(SystemSetting(key=key, value=value, is_secret=False))
        else:
            row.value = value
    db.commit()
    return get_theme(db=db, _=user)


# ---------------------------------------------------------------------------
# Time, calendar and trusted-time verification (§22)
# ---------------------------------------------------------------------------
@router.get("/time")
def get_time(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    """Current server time in both calendars — powers the status bar (§21)."""
    from ..services.timeservice import describe_now

    return describe_now(
        timezone_name=_get(db, "time.timezone", "Asia/Tehran"),
        calendar=_get(db, "time.calendar", "jalali"),
    )


@router.post("/time/verify")
def verify_time(db: Session = Depends(get_db),
                _: User = Depends(require_permission("settings.manage"))):
    """Query NTP and report the drift.

    Deliberately never rewrites the system clock: a silent correction would
    hide a broken machine. UNVERIFIED is returned when no server is reachable.
    """
    from ..services.timeservice import check_time_sync

    servers = [s for s in _get(
        db, "time.ntp_servers", "pool.ntp.org").split(",") if s.strip()]
    try:
        max_drift = int(_get(db, "time.max_drift_seconds", "120") or 120)
    except ValueError:
        max_drift = 120
    return check_time_sync(servers, max_drift_seconds=max_drift)


# ---------------------------------------------------------------------------
# About (§59)
# ---------------------------------------------------------------------------
@router.get("/about")
def about(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    from .. import __version__

    return {
        "app_name": "سامانه جامع مدیریت سوپرمارکت",
        "app_name_en": "Supermarket Smart Management System",
        "version": __version__,
        "developer": "خواجوی",
        "developer_en": "Khajavy",
        "description": (
            "سامانهٔ یکپارچهٔ صندوق فروش، انبارداری، انبارگردانی و باشگاه "
            "مشتریان، با معماری Local-First و اپ موبایل PWA."
        ),
        "store_name": _get(db, "store.name", ""),
    }
