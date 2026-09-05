from __future__ import annotations

import time
from collections import defaultdict
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import User
from ..security import create_access_token, get_current_user, verify_password
from ..services.audit import write_audit

router = APIRouter(prefix="/auth", tags=["auth"])

# --- Login throttling (BUG-011) ------------------------------------------------
# In-memory per username+IP counters: 5 failures -> 5 minute lockout.
# Adequate for the single-machine deployment (ADR-003); for a multi-terminal
# server this moves to the shared store (documented in DEPLOYMENT).
MAX_FAILURES = 5
LOCKOUT_SECONDS = 5 * 60
_failures: dict[str, list[float]] = defaultdict(list)
_locks: dict[str, float] = {}


def _client_key(request: Request, username: str) -> str:
    ip = request.client.host if request.client else "?"
    return f"{username}|{ip}"


def _register_failure(key: str) -> None:
    now = time.time()
    _failures[key] = [t for t in _failures[key] if now - t < LOCKOUT_SECONDS]
    _failures[key].append(now)
    if len(_failures[key]) >= MAX_FAILURES:
        _locks[key] = now + LOCKOUT_SECONDS


def _is_locked(key: str) -> bool:
    until = _locks.get(key)
    if until and until > time.time():
        return True
    _locks.pop(key, None)
    return False


def _clear_failures(key: str) -> None:
    _failures.pop(key, None)
    _locks.pop(key, None)


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserOut(BaseModel):
    id: int
    username: str
    full_name: str
    roles: list[str]
    permissions: list[str] = []

    model_config = {"from_attributes": True}


@router.post("/login", response_model=TokenOut)
def login(form: Annotated[OAuth2PasswordRequestForm, Depends()],
          request: Request, db: Session = Depends(get_db)):
    key = _client_key(request, form.username)
    if _is_locked(key):
        raise HTTPException(
            status_code=429,
            detail="تلاش‌های ناموفق زیاد؛ حساب برای ۵ دقیقه قفل شد.",
        )
    user = db.execute(select(User).where(User.username == form.username)).scalar_one_or_none()
    if not user or not verify_password(form.password, user.password_hash) or not user.is_active:
        _register_failure(key)
        write_audit(db, action="USER_LOGIN_FAILED", entity_type="User",
                    reference=form.username, ip_address=request.client.host if request.client else None)
        db.commit()
        raise HTTPException(status_code=401, detail="Invalid username or password")

    _clear_failures(key)
    user.last_login_at = datetime.utcnow()
    write_audit(db, action="USER_LOGIN", user_id=user.id, entity_type="User", entity_id=user.id,
                ip_address=request.client.host if request.client else None)
    db.commit()
    return TokenOut(access_token=create_access_token(str(user.id), {"username": user.username}))


@router.post("/logout")
def logout(current_user: Annotated[User, Depends(get_current_user)],
           request: Request, db: Session = Depends(get_db)):
    """Revoke the presented token (in-memory blocklist until its expiry) + audit.

    Limitation (documented honestly): the blocklist is per-process; it covers
    the single-machine deployment. A persistent revocation table comes with the
    multi-terminal server phase.
    """
    from ..security import revoke_token
    auth = request.headers.get("authorization", "")
    token = auth.removeprefix("Bearer ").strip()
    if token:
        revoke_token(token)
    write_audit(db, action="USER_LOGOUT", user_id=current_user.id,
                entity_type="User", entity_id=current_user.id)
    db.commit()
    return {"ok": True, "detail": "خروج انجام شد؛ توکن باطل شد."}


@router.get("/me", response_model=UserOut)
def me(current_user: Annotated[User, Depends(get_current_user)]):
    from ..security import _user_permission_codes
    return UserOut(
        id=current_user.id, username=current_user.username,
        full_name=current_user.full_name, roles=[r.name for r in current_user.roles],
        permissions=sorted(_user_permission_codes(current_user)),
    )
