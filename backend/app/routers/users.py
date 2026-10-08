from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..database import get_db
from ..models import Permission, Role, User
from ..security import (get_current_user, hash_password, require_permission,
                        role_title_fa)
from ..services.audit import write_audit

router = APIRouter(prefix="/users", tags=["users"])


class UserIn(BaseModel):
    username: str
    password: str
    full_name: str = ""
    email: str | None = None
    roles: list[str] = []
    # «دسترسی فقط به صورت بومی» — default ON for non-admin users; it restricts
    # online sign-in to the shop's local network. It does not grant/revoke cached
    # sign-in with no network; offline_allowed is the separate opt-in below.
    local_only: bool = True
    # Offline-first is opt-in for non-admin users; this is distinct from LAN-only access.
    offline_allowed: bool = False
    # build-488 (§۱–۲) — پروفایل + دسترسی مستقیم مستقل از Role
    phone: str | None = None
    job_title: str | None = None
    store: str | None = None
    hire_date: datetime | None = None
    permissions: list[str] = []


class UserPatch(BaseModel):
    full_name: str | None = None
    email: str | None = None
    password: str | None = None
    is_active: bool | None = None
    roles: list[str] | None = None
    local_only: bool | None = None
    offline_allowed: bool | None = None
    phone: str | None = None
    job_title: str | None = None
    store: str | None = None
    hire_date: datetime | None = None
    permissions: list[str] | None = None


class ProfilePatch(BaseModel):
    """ویرایش خودِ کاربر روی پروفایل شخصی — فقط فیلدهای امن (§۱)."""
    full_name: str | None = None
    email: str | None = None
    phone: str | None = None


def _effective_codes(u: User) -> list[str]:
    codes = {p.code for p in u.direct_permissions}
    for r in u.roles:
        codes.update(p.code for p in r.permissions)
    return sorted(codes)


def _out(u: User) -> dict:
    return {"id": u.id, "username": u.username, "full_name": u.full_name,
            "email": u.email, "is_active": u.is_active, "roles": [r.name for r in u.roles],
            "roles_titles": [role_title_fa(r.name) for r in u.roles],
            "local_only": bool(u.local_only),
            "offline_allowed": bool(u.offline_allowed),
            # build-488 — پروفایل (§۱) + دسترسی مستقیم (§۲)
            "phone": u.phone, "job_title": u.job_title, "store": u.store,
            "avatar_url": f"/media/{u.avatar_path}" if u.avatar_path else None,
            "hire_date": u.hire_date.isoformat() if u.hire_date else None,
            "last_login_at": u.last_login_at.isoformat() if u.last_login_at else None,
            "created_at": u.created_at.isoformat() if getattr(u, "created_at", None) else None,
            "permissions": _effective_codes(u),
            "direct_permissions": [p.code for p in u.direct_permissions]}


def _set_direct_permissions(db: Session, u: User, codes: list[str]) -> None:
    perms = db.execute(select(Permission).where(Permission.code.in_(codes))).scalars().all() if codes else []
    missing = set(codes) - {p.code for p in perms}
    if missing:
        raise HTTPException(status_code=400, detail={"code": "UNKNOWN_PERMISSION",
                                                     "message": f"دسترسی ناشناخته: {sorted(missing)}"})
    u.direct_permissions = list(perms)


def _media_dir() -> Path:
    d = Path(get_settings().MEDIA_DIR)
    d.mkdir(parents=True, exist_ok=True)
    return d


@router.get("")
def list_users(db: Session = Depends(get_db), _: User = Depends(require_permission("users.manage"))):
    return [_out(u) for u in db.execute(select(User)).scalars()]


@router.get("/roles")
def list_roles(db: Session = Depends(get_db), _: User = Depends(require_permission("users.manage"))):
    from ..security import ensure_standard_roles
    ensure_standard_roles(db)  # نقش‌های استاندارد فروشگاه (§۳) — idempotent
    return [{"id": r.id, "name": r.name, "title_fa": role_title_fa(r.name),
             "description": r.description, "permissions": [p.code for p in r.permissions]}
            for r in db.execute(select(Role)).scalars()]


@router.get("/permissions")
def list_permissions(db: Session = Depends(get_db), _: User = Depends(require_permission("users.manage"))):
    from ..security import PERMISSIONS
    return [{"code": code, "description": desc} for code, desc in PERMISSIONS.items()]


@router.post("", status_code=201)
def create_user(body: UserIn, db: Session = Depends(get_db), _: User = Depends(require_permission("users.manage"))):
    if db.execute(select(User).where(User.username == body.username)).scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Username already exists")
    roles = db.execute(select(Role).where(Role.name.in_(body.roles))).scalars().all() if body.roles else []
    u = User(username=body.username, full_name=body.full_name, email=body.email,
             password_hash=hash_password(body.password), roles=list(roles),
             local_only=body.local_only, offline_allowed=body.offline_allowed,
             phone=body.phone, job_title=body.job_title, store=body.store,
             hire_date=body.hire_date)
    db.add(u)
    db.flush()
    _set_direct_permissions(db, u, body.permissions or [])
    write_audit(db, action="USER_CREATED", user_id=u.id, entity_type="User", entity_id=u.id,
                after={"username": u.username, "roles": body.roles,
                       "permissions": body.permissions or [], "local_only": u.local_only,
                       "offline_allowed": u.offline_allowed})
    db.commit()
    return _out(u)


# ── پروفایل شخصی (§۱) — هر کاربر مالک پروفایل خودش است ─────────────────────


@router.get("/me")
def my_profile(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return _out(user)


@router.patch("/me")
def update_my_profile(body: ProfilePatch, db: Session = Depends(get_db),
                      user: User = Depends(get_current_user)):
    for f in ("full_name", "email", "phone"):
        v = getattr(body, f)
        if v is not None:
            setattr(user, f, v)
    db.commit()
    return _out(user)


@router.post("/me/avatar")
async def upload_avatar(file: UploadFile = File(...), db: Session = Depends(get_db),
                        user: User = Depends(get_current_user)):
    """انتخاب/تغییر تصویر پروفایل (§۱). حذف: DELETE /users/me/avatar."""
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in (".png", ".jpg", ".jpeg", ".webp"):
        raise HTTPException(status_code=400, detail={"code": "BAD_TYPE",
                                                     "message": "فرمت تصویر باید png/jpg/webp باشد"})
    data = await file.read()
    if len(data) > 2 * 1024 * 1024:
        raise HTTPException(status_code=400, detail={"code": "TOO_LARGE",
                                                     "message": "حجم تصویر نباید بیش از ۲ مگابایت باشد"})
    rel = f"avatars/user-{user.id}-{int(datetime.utcnow().timestamp())}{ext}"
    path = _media_dir() / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    user.avatar_path = rel
    db.commit()
    return _out(user)


@router.delete("/me/avatar")
def delete_avatar(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if user.avatar_path:
        try:
            (_media_dir() / user.avatar_path).unlink(missing_ok=True)
        except Exception:
            pass
        user.avatar_path = None
        db.commit()
    return _out(user)


@router.get("/{user_id}/profile")
def employee_profile(user_id: int, db: Session = Depends(get_db),
                     viewer: User = Depends(get_current_user)):
    """پروفایل کامل کارمند (§۱) — خودِ کاربر یا profile.view_all.
    حقوق فقط با payroll.view (§۵۰)."""
    from ..security import has_permission
    u = db.get(User, user_id)
    if not u:
        raise HTTPException(status_code=404, detail="USER_NOT_FOUND")
    if viewer.id != user_id and not has_permission(viewer, "profile.view_all"):
        raise HTTPException(status_code=403, detail={"code": "MISSING_PERMISSION",
                                                     "message": "دیدن پروفایل دیگران نیازمند profile.view_all است"})
    out = _out(u)
    # وضعیت فعال/غیرفعال و اطلاعات حساب بخشی از همین خروجی است (§۱)
    if has_permission(viewer, "payroll.view"):
        from ..models import PayrollEntry
        rows = db.execute(select(PayrollEntry).where(PayrollEntry.user_id == user_id)
                          .order_by(PayrollEntry.period.desc()).limit(12)).scalars().all()
        out["payroll"] = [{"period": r.period, "total": float(r.total or 0),
                           "status": r.status} for r in rows]
    else:
        # §۱ — حقوق فقط با Permission لازم؛ حتی برای خودِ کاربر. نه داده، نه
        # آرایهٔ خالی گمراه‌کننده.
        out["payroll"] = None
    from ..services.achievements import summary as ach_summary
    out["achievements"] = ach_summary(db, user_id)
    return out


@router.patch("/{user_id}")
def update_user(user_id: int, body: UserPatch, db: Session = Depends(get_db),
                _: User = Depends(require_permission("users.manage"))):
    u = db.get(User, user_id)
    if not u:
        raise HTTPException(status_code=404, detail="USER_NOT_FOUND")
    before = {"roles": [r.name for r in u.roles],
              "direct_permissions": [p.code for p in u.direct_permissions],
              "is_active": u.is_active, "local_only": u.local_only,
              "offline_allowed": u.offline_allowed}
    if body.password:
        u.password_hash = hash_password(body.password)
    for f in ("full_name", "email", "is_active", "local_only", "offline_allowed", "phone", "job_title", "store", "hire_date"):
        v = getattr(body, f)
        if v is not None:
            setattr(u, f, v)
    if body.roles is not None:
        u.roles = list(db.execute(select(Role).where(Role.name.in_(body.roles))).scalars().all())
    if body.permissions is not None:
        _set_direct_permissions(db, u, body.permissions)
    write_audit(db, action="USER_UPDATED", user_id=u.id, entity_type="User", entity_id=u.id,
                before=before,
                after={"roles": [r.name for r in u.roles],
                       "direct_permissions": [p.code for p in u.direct_permissions],
                       "is_active": u.is_active, "local_only": u.local_only,
                       "offline_allowed": u.offline_allowed})
    db.commit()
    return _out(u)
