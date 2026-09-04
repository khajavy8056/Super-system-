"""Authentication & authorization helpers.

- Passwords hashed with bcrypt.
- Stateless JWT access tokens (HS256).
- Granular permission checks (blueprint §83–84).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Annotated

import bcrypt
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from .config import settings
from .database import get_db
from .models import Permission, Role, User

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")

_CREDENTIAL_EXC = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Invalid credentials",
    headers={"WWW-Authenticate": "Bearer"},
)

# --- Permission codes (blueprint §84) -------------------------------------
PERMISSIONS: dict[str, str] = {
    "products.manage": "Create / update / delete products",
    "products.view": "View products",
    "batches.manage": "Create / update batches (receiving)",
    "batches.delete": "Delete a batch",
    "inventory.adjust": "Manual stock adjustment",
    "inventory.stocktake": "Run stocktaking",
    "inventory.view": "View stock",
    "pricing.manage": "Change prices",
    "pricing.view_cost": "View buy costs",
    "pos.sell": "Operate the POS / sell",
    "pos.void_unpaid": "Void unpaid invoices",
    "pos.void_paid": "Void paid invoices",
    "pos.return": "Process returns",
    "reports.view": "View reports & dashboard",
    "settings.manage": "Manage system settings",
    "users.manage": "Manage users & roles",
    "audit.view": "View audit logs",
}

ROLE_PRESETS: dict[str, list[str]] = {
    "Administrator": list(PERMISSIONS.keys()),
    "Manager": [
        "products.manage", "products.view", "batches.manage", "inventory.adjust",
        "inventory.stocktake", "inventory.view", "pricing.manage", "pricing.view_cost",
        "pos.sell", "pos.void_unpaid", "pos.void_paid", "pos.return",
        "reports.view", "settings.manage", "audit.view",
    ],
    "Cashier": ["products.view", "inventory.view", "pos.sell", "pos.void_unpaid", "reports.view"],
    "Inventory Operator": [
        "products.view", "batches.manage", "inventory.adjust", "inventory.stocktake",
        "inventory.view", "pricing.view_cost", "reports.view",
    ],
    "Viewer": ["products.view", "inventory.view", "reports.view"],
}


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except ValueError:
        return False


def create_access_token(subject: str, extra: dict | None = None) -> str:
    payload = {"sub": subject, "exp": datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)}
    if extra:
        payload.update(extra)
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    except jwt.PyJWTError:
        raise _CREDENTIAL_EXC


def _user_permission_codes(user: User) -> set[str]:
    codes: set[str] = set()
    for role in user.roles:
        codes.update(p.code for p in role.permissions)
    return codes


def get_current_user(token: Annotated[str, Depends(oauth2_scheme)], db: Annotated[Session, Depends(get_db)]) -> User:
    payload = decode_token(token)
    user = db.get(User, int(payload["sub"]))
    if not user or not user.is_active:
        raise _CREDENTIAL_EXC
    return user


def require_permission(code: str):
    """Dependency factory enforcing a granular permission."""

    def _checker(current_user: Annotated[User, Depends(get_current_user)]) -> User:
        if code not in _user_permission_codes(current_user):
            raise HTTPException(status_code=403, detail=f"Missing permission: {code}")
        return current_user

    return _checker


def has_permission(user: User, code: str) -> bool:
    return code in _user_permission_codes(user)
