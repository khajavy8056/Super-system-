from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Role, User
from ..security import get_current_user, hash_password, require_permission

router = APIRouter(prefix="/users", tags=["users"])


class UserIn(BaseModel):
    username: str
    password: str
    full_name: str = ""
    email: str | None = None
    roles: list[str] = []


class UserPatch(BaseModel):
    full_name: str | None = None
    email: str | None = None
    password: str | None = None
    is_active: bool | None = None
    roles: list[str] | None = None


def _out(u: User) -> dict:
    return {"id": u.id, "username": u.username, "full_name": u.full_name,
            "email": u.email, "is_active": u.is_active, "roles": [r.name for r in u.roles]}


@router.get("")
def list_users(db: Session = Depends(get_db), _: User = Depends(require_permission("users.manage"))):
    return [_out(u) for u in db.execute(select(User)).scalars()]


@router.get("/roles")
def list_roles(db: Session = Depends(get_db), _: User = Depends(require_permission("users.manage"))):
    return [{"id": r.id, "name": r.name, "permissions": [p.code for p in r.permissions]}
            for r in db.execute(select(Role)).scalars()]


@router.post("", status_code=201)
def create_user(body: UserIn, db: Session = Depends(get_db), _: User = Depends(require_permission("users.manage"))):
    if db.execute(select(User).where(User.username == body.username)).scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Username already exists")
    roles = db.execute(select(Role).where(Role.name.in_(body.roles))).scalars().all() if body.roles else []
    u = User(username=body.username, full_name=body.full_name, email=body.email,
             password_hash=hash_password(body.password), roles=list(roles))
    db.add(u)
    db.commit()
    return _out(u)


@router.patch("/{user_id}")
def update_user(user_id: int, body: UserPatch, db: Session = Depends(get_db),
                _: User = Depends(require_permission("users.manage"))):
    u = db.get(User, user_id)
    if not u:
        raise HTTPException(status_code=404, detail="USER_NOT_FOUND")
    if body.password:
        u.password_hash = hash_password(body.password)
    for f in ("full_name", "email", "is_active"):
        v = getattr(body, f)
        if v is not None:
            setattr(u, f, v)
    if body.roles is not None:
        u.roles = list(db.execute(select(Role).where(Role.name.in_(body.roles))).scalars().all())
    db.commit()
    return _out(u)
