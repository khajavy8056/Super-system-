"""v1.5 — First-run setup wizard, licence activation and bottom alerts.

Public (unauthenticated) surface, deliberately minimal:
  GET  /api/setup/status            → {setup_done, license:{allowed,…}, first_login_done}
  POST /api/setup/license/activate  → validate key online for this HWID
  GET  /api/setup/license           → licence state (no secret)
  POST /api/setup/complete          → store profile / currency / theme / admin
                                      credentials / optional starter catalog.
                                      Only allowed while setup is NOT done
                                      (afterwards these live behind settings.manage).
  POST /api/setup/logo              → store logo during the wizard (same rule)

Authenticated:
  GET  /api/setup/alerts            → expiring batches + licence days-left for
                                      the bottom notification stack.
  POST /api/setup/loading-done      → marks first "heavy install" loading done.
  POST /api/setup/license/recheck   → force online re-validation (login loading).
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings as app_settings
from ..database import get_db
from ..models import ProductBatch, SystemSetting, User
from ..security import get_current_user, hash_password, require_permission
from ..services import expiry as expiry_svc
from ..services import license as lic
from ..services.audit import write_audit

router = APIRouter(prefix="/setup", tags=["setup"])

SETUP_KEYS = {"done": "setup.done", "done_at": "setup.done_at", "loading_done": "setup.first_loading_done",
              "starter": "setup.starter_imported"}


def _get(db: Session, key: str, default: str = "") -> str:
    row = db.execute(select(SystemSetting).where(SystemSetting.key == key)).scalar_one_or_none()
    return row.value if row and row.value is not None else default


def _set(db: Session, key: str, value: str) -> None:
    row = db.execute(select(SystemSetting).where(SystemSetting.key == key)).scalar_one_or_none()
    if row is None:
        db.add(SystemSetting(key=key, value=value, is_secret=False, description="Setup wizard"))
    else:
        row.value = value


def setup_done(db: Session) -> bool:
    return _get(db, SETUP_KEYS["done"]) == "1"


def _require_setup_open(db: Session) -> None:
    if setup_done(db):
        raise HTTPException(status_code=409, detail={
            "code": "SETUP_DONE", "message": "راه‌اندازی اولیه قبلاً انجام شده است؛ از بخش تنظیمات استفاده کنید."})


# --- status ------------------------------------------------------------------------
@router.get("/status")
def status(db: Session = Depends(get_db)):
    st = lic.state(db)
    return {
        "setup_done": setup_done(db),
        "setup_done_at": _get(db, SETUP_KEYS["done_at"]) or None,
        "first_loading_done": _get(db, SETUP_KEYS["loading_done"]) == "1",
        "license": st,
        "store_name": _get(db, "store.name"),
        "logo_path": _get(db, "store.logo_path"),
        # the UI shows the long "installing" loading only once, then a short one
        "loading_seconds": 45 * 60 if _get(db, SETUP_KEYS["loading_done"]) != "1" else 2 * 60,
    }


# --- licence -----------------------------------------------------------------------
class LicenseIn(BaseModel):
    key: str = Field(min_length=8, max_length=64)


@router.get("/license")
def license_state(db: Session = Depends(get_db)):
    return lic.state(db)


@router.post("/license/activate")
def license_activate(body: LicenseIn, db: Session = Depends(get_db)):
    try:
        st = lic.activate(db, body.key)
    except lic.LicenseError as exc:
        db.commit()
        code = 503 if exc.code == "NETWORK" else 422
        raise HTTPException(status_code=code, detail={"code": exc.code, "message": exc.message})
    write_audit(db, action="LICENSE_ACTIVATED", entity_type="License",
                after={"type": st["type"], "owner": st["owner"], "expires": st["expires"], "hwid": st["hwid"]})
    db.commit()
    return st


@router.post("/license/recheck")
def license_recheck(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    st = lic.recheck(db, force=True)
    db.commit()
    return st


@router.delete("/license")
def license_clear(db: Session = Depends(get_db), user: User = Depends(require_permission("settings.manage"))):
    lic.clear(db)
    write_audit(db, action="LICENSE_CLEARED", user_id=user.id, entity_type="License")
    db.commit()
    return {"ok": True}


# --- wizard completion -----------------------------------------------------------------
class SetupIn(BaseModel):
    store_name: str | None = None
    legal_name: str | None = None
    phone: str | None = None
    mobile: str | None = None
    address: str | None = None
    city: str | None = None
    postal_code: str | None = None
    tax_id: str | None = None
    receipt_note: str | None = None
    currency: str | None = None            # IRT | IRR
    theme: str | None = None               # auto | light | dark
    printer_width_mm: int | None = None    # 58 | 76 | 80
    import_starter_catalog: bool = False
    admin_username: str | None = None
    admin_password: str | None = None
    admin_full_name: str | None = None


_USERNAME_RE = re.compile(r"^[A-Za-z0-9_.-]{3,32}$")


@router.post("/complete")
def complete(body: SetupIn, db: Session = Depends(get_db)):
    _require_setup_open(db)
    if not lic.state(db)["allowed"]:
        raise HTTPException(status_code=402, detail={"code": "LICENSE_REQUIRED",
                                                     "message": "ابتدا لایسنس را فعال کنید."})
    from ..services.units import CURRENCIES

    profile = {k: v for k, v in body.model_dump().items()
               if k in ("legal_name", "phone", "mobile", "address", "city", "postal_code", "tax_id", "receipt_note")
               and v is not None}
    if body.store_name is not None:
        profile["name"] = body.store_name
    for f, v in profile.items():
        _set(db, f"store.{f}", (v or "").strip())

    if body.currency:
        code = body.currency.strip().upper()
        if code not in CURRENCIES:
            raise HTTPException(status_code=422, detail={"code": "UNSUPPORTED_CURRENCY", "message": "واحد پول نامعتبر"})
        _set(db, "pos.currency", code)
    if body.theme:
        if body.theme not in ("auto", "light", "dark"):
            raise HTTPException(status_code=422, detail={"code": "BAD_THEME", "message": "تم نامعتبر"})
        _set(db, "ui.theme", body.theme)
    if body.printer_width_mm:
        if body.printer_width_mm not in (58, 76, 80):
            raise HTTPException(status_code=422, detail={"code": "BAD_PAPER", "message": "عرض کاغذ نامعتبر"})
        _set(db, "printer.paper_width_mm", str(body.printer_width_mm))

    # Admin credentials — set during the wizard, replaces the bootstrap default.
    if body.admin_username or body.admin_password:
        if not (body.admin_username and body.admin_password):
            raise HTTPException(status_code=422, detail={"code": "ADMIN_INCOMPLETE",
                                                         "message": "نام کاربری و رمز عبور مدیر هر دو لازم است."})
        if not _USERNAME_RE.match(body.admin_username):
            raise HTTPException(status_code=422, detail={"code": "BAD_USERNAME",
                                                         "message": "نام کاربری: ۳ تا ۳۲ حرف انگلیسی/عدد/._-"})
        if len(body.admin_password) < 6:
            raise HTTPException(status_code=422, detail={"code": "WEAK_PASSWORD",
                                                         "message": "رمز عبور باید حداقل ۶ کاراکتر باشد."})
        admin = db.execute(select(User).where(User.username == app_settings.ADMIN_USERNAME)).scalar_one_or_none()
        if admin is None:  # bootstrap admin renamed earlier — take the first Administrator
            admin = db.execute(select(User).order_by(User.id)).scalars().first()
        taken = db.execute(select(User).where(User.username == body.admin_username)).scalar_one_or_none()
        if taken and taken.id != admin.id:
            raise HTTPException(status_code=422, detail={"code": "USERNAME_TAKEN", "message": "این نام کاربری قبلاً استفاده شده."})
        admin.username = body.admin_username
        admin.password_hash = hash_password(body.admin_password)
        if body.admin_full_name:
            admin.full_name = body.admin_full_name.strip()
        admin.is_active = True

    starter = None
    if body.import_starter_catalog and _get(db, SETUP_KEYS["starter"]) != "1":
        from ..services.starter_catalog import import_csv
        starter = import_csv(db)
        _set(db, SETUP_KEYS["starter"], "1")

    _set(db, SETUP_KEYS["done"], "1")
    _set(db, SETUP_KEYS["done_at"], datetime.utcnow().isoformat(timespec="seconds"))
    write_audit(db, action="SETUP_COMPLETED", entity_type="System",
                after={"store": profile.get("name"), "currency": body.currency, "theme": body.theme,
                       "starter": bool(starter), "admin_renamed": bool(body.admin_username)})
    db.commit()
    return {"ok": True, "setup_done": True, "starter": starter,
            "admin_username": body.admin_username or app_settings.ADMIN_USERNAME}


_LOGO_TYPES = {"image/png": ".png", "image/jpeg": ".jpg", "image/svg+xml": ".svg", "image/webp": ".webp"}


@router.post("/logo")
async def wizard_logo(file: UploadFile = File(...), db: Session = Depends(get_db)):
    _require_setup_open(db)
    ext = _LOGO_TYPES.get((file.content_type or "").lower())
    if ext is None:
        raise HTTPException(status_code=400, detail={"code": "UNSUPPORTED_TYPE",
                                                     "message": "فرمت لوگو باید PNG، JPEG، SVG یا WebP باشد."})
    data = await file.read()
    if not data or len(data) > 2 * 1024 * 1024:
        raise HTTPException(status_code=413, detail={"code": "TOO_LARGE", "message": "حجم لوگو باید بین ۱ بایت و ۲ مگابایت باشد."})
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
    _set(db, "store.logo_path", url)
    db.commit()
    return {"logo_path": url}


# --- first-run loading -----------------------------------------------------------------
@router.post("/loading-done")
def loading_done(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    _set(db, SETUP_KEYS["loading_done"], "1")
    db.commit()
    return {"ok": True}


# --- bottom alerts ---------------------------------------------------------------------
@router.get("/alerts")
def alerts(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    """Near-expiry batches (hours/days left) + licence countdown, newest-critical first."""
    today = date.today()
    now = datetime.now()
    th = expiry_svc.get_thresholds(db)
    horizon = today + timedelta(days=max(th.values()) if th else 30)
    rows = db.execute(
        select(ProductBatch).where(ProductBatch.status == "ACTIVE", ProductBatch.expiry_date.isnot(None),
                                   ProductBatch.expiry_date <= horizon, ProductBatch.current_qty > 0)
        .order_by(ProductBatch.expiry_date.asc()).limit(50)
    ).scalars().all()
    def _pf(n):  # Persian digits for counts (batch numbers stay Latin)
        return str(n).translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹"))

    items = []
    for b in rows:
        days = (b.expiry_date - today).days
        end_of_day = datetime.combine(b.expiry_date, datetime.max.time())
        hours = max(0, int((end_of_day - now).total_seconds() // 3600))
        if days < 0:
            sev, txt = "CRITICAL", "منقضی شده"
        elif days == 0:
            sev, txt = "CRITICAL", f"{_pf(hours)} ساعت مانده"
        elif days <= 3:
            sev, txt = "WARNING", f"{_pf(days)} روز مانده"
        else:
            sev, txt = "INFO", f"{_pf(days)} روز مانده"
        items.append({"kind": "EXPIRY", "severity": sev, "id": f"exp-{b.id}",
                      "title": b.product.name if b.product else f"بچ {b.batch_number}",
                      "body": f"{txt} · بچ {b.batch_number} · موجودی {_pf(f'{float(b.current_qty):g}')}",
                      "days_left": days, "hours_left": hours, "batch_id": b.id, "product_id": b.product_id})
    st = lic.state(db)
    if st.get("days_left") is not None and st["days_left"] <= 14:
        d = st["days_left"]
        items.insert(0, {"kind": "LICENSE", "severity": "CRITICAL" if d <= 3 else "WARNING", "id": "lic",
                         "title": "اعتبار لایسنس", "days_left": d,
                         "body": ("امروز به پایان می‌رسد" if d == 0 else (f"{_pf(-d)} روز پیش تمام شده" if d < 0 else f"{_pf(d)} روز مانده"))
                                 + f" · نوع {st.get('type') or '-'}"})
    if not st["allowed"]:
        items.insert(0, {"kind": "LICENSE", "severity": "CRITICAL", "id": "lic-blocked",
                         "title": "لایسنس", "body": st["reason"], "days_left": None})
    return {"items": items, "generated_at": now.isoformat(timespec="seconds"),
            "expiring_count": sum(1 for i in items if i["kind"] == "EXPIRY")}
