from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import User
from ..security import create_access_token, get_current_user, verify_password
from ..services.audit import write_audit

router = APIRouter(prefix="/auth", tags=["auth"])


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserOut(BaseModel):
    id: int
    username: str
    full_name: str
    roles: list[str]

    model_config = {"from_attributes": True}


@router.post("/login", response_model=TokenOut)
def login(form: Annotated[OAuth2PasswordRequestForm, Depends()], db: Session = Depends(get_db)):
    user = db.execute(select(User).where(User.username == form.username)).scalar_one_or_none()
    if not user or not verify_password(form.password, user.password_hash) or not user.is_active:
        raise HTTPException(status_code=401, detail="Invalid username or password")
    user.last_login_at = datetime.utcnow()
    write_audit(db, action="USER_LOGIN", user_id=user.id, entity_type="User", entity_id=user.id)
    db.commit()
    return TokenOut(access_token=create_access_token(str(user.id), {"username": user.username}))


@router.get("/me", response_model=UserOut)
def me(current_user: Annotated[User, Depends(get_current_user)]):
    return UserOut(
        id=current_user.id, username=current_user.username,
        full_name=current_user.full_name, roles=[r.name for r in current_user.roles],
    )
