"""Authentication & authorization helpers.

- Passwords hashed with bcrypt.
- Stateless JWT access tokens (HS256).
- Granular permission checks (blueprint §83–84).
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Annotated
from uuid import uuid4

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
    "inventory.approve_stocktake": "Approve stocktaking results and apply adjustments",
    "inventory.view": "View stock",
    "pricing.manage": "Change prices",
    "pricing.view_cost": "View buy costs",
    "pos.sell": "Operate the POS / sell",
    "pos.void_unpaid": "Void unpaid invoices",
    "pos.void_paid": "Void paid invoices",
    "pos.return": "Process returns",
    "customers.manage": "Create / update customers",
    "customers.ledger": "View customer account statements",
    "customers.settle": "Record payments / settle customer debt",
    "reports.view": "View reports & dashboard",
    "accounting.view": "View ledgers, journal and financial statements",
    "accounting.post": "Post manual journal entries, expenses, cheques",
    "accounting.close": "Close fiscal periods / cash sessions",
    "settings.manage": "Manage system settings",
    # build-489 — تخفیف‌ها و کمپین‌ها بخش مستقل‌اند (§۳): صندوق‌دار نباید ببیند
    "marketing.view": "مشاهدهٔ تخفیف‌ها و کمپین‌ها",
    "marketing.manage": "ساخت و ادارهٔ تخفیف‌ها و کمپین‌ها",
    "users.manage": "Manage users & roles",
    "audit.view": "View audit logs",
    # ── build-488 — دسترسی‌های ریزدانهٔ بخش‌های جدید (§۲)؛ فقط افزودنی ──
    "profile.view_all": "View employee profiles (phone, job title, hire date)",
    "announcements.publish": "Create & publish announcements",
    "announcements.manage": "Edit / cancel / delete any announcement",
    "shifts.view": "View shift schedules",
    "shifts.manage": "Define shifts, assign staff, manage attendance",
    "performance.view": "View own / team performance reports",
    "performance.view_all": "View every employee's performance + export",
    "payroll.view": "View payroll rows",
    "payroll.manage": "Create / edit / approve payroll and post payments",
    "reports.export": "Export reports (PDF / CSV)",
    "dev.mode": "Developer Mode (diagnostics, logs, hardware, API/DB tools)",
}

ROLE_PRESETS: dict[str, list[str]] = {
    "Administrator": list(PERMISSIONS.keys()),
    "Manager": [
        "products.manage", "products.view", "batches.manage", "inventory.adjust",
        "inventory.stocktake", "inventory.approve_stocktake", "inventory.view",
        "pricing.manage", "pricing.view_cost",
        "pos.sell", "pos.void_unpaid", "pos.void_paid", "pos.return",
        "customers.manage", "customers.ledger", "customers.settle",
        "reports.view", "settings.manage", "audit.view",
        "marketing.view", "marketing.manage",
        "accounting.view", "accounting.post", "accounting.close",
    ],
    "Cashier": [
        "products.view", "inventory.view", "pos.sell", "pos.void_unpaid",
        "customers.manage", "customers.ledger", "customers.settle", "reports.view",
    ],
    "Inventory Operator": [
        "products.view", "batches.manage", "inventory.adjust", "inventory.stocktake",
        "inventory.view", "pricing.view_cost", "reports.view",
    ],
    "Viewer": ["products.view", "inventory.view", "reports.view"],
    # ── build-488 — عناوین استاندارد فروشگاه (§۳)؛ Role فقط مجموعهٔ Permission می‌سازد ──
    "Supervisor": [
        "products.view", "inventory.view", "pos.sell", "pos.void_unpaid", "pos.return",
        "customers.manage", "customers.ledger",
        "reports.view", "announcements.publish", "shifts.view", "shifts.manage",
        "performance.view", "audit.view",
    ],
    "Inspector": ["products.view", "inventory.view", "reports.view", "audit.view"],
    "Storekeeper": [
        "products.view", "batches.manage", "batches.delete", "inventory.adjust",
        "inventory.stocktake", "inventory.view", "reports.view", "shifts.view",
    ],
    "Stocktake Lead": [
        "products.view", "inventory.view", "inventory.stocktake",
        "inventory.approve_stocktake", "inventory.adjust", "reports.view", "shifts.view",
    ],
    "Salesperson": [
        "products.view", "inventory.view", "pos.sell", "pos.void_unpaid",
        "customers.manage", "reports.view", "shifts.view", "performance.view",
    ],
    "General Manager": [
        "products.manage", "products.view", "batches.manage", "inventory.adjust",
        "inventory.stocktake", "inventory.approve_stocktake", "inventory.view",
        "pricing.manage", "pricing.view_cost",
        "pos.sell", "pos.void_unpaid", "pos.void_paid", "pos.return",
        "customers.manage", "customers.ledger", "customers.settle",
        "reports.view", "reports.export", "settings.manage", "audit.view",
        "accounting.view", "accounting.post", "accounting.close",
        "users.manage", "profile.view_all",
        "announcements.publish", "announcements.manage",
        "shifts.view", "shifts.manage", "performance.view", "performance.view_all",
        "payroll.view", "payroll.manage",
        "marketing.view", "marketing.manage"],
}

#: عنوان نمایشی فارسی هر Role (§۳) — فقط برای نمایش؛ UI هرگز از Role تصمیم نمی‌گیرد
#: و همیشه از Permission استفاده می‌کند.
ROLE_TITLES_FA: dict[str, str] = {
    "Administrator": "مدیر کل",
    "General Manager": "مدیر کل",
    "Manager": "مدیر فروشگاه",
    "Supervisor": "سوپروایزر",
    "Inspector": "بازرس",
    "Salesperson": "فروشنده",
    "Cashier": "صندوقدار",
    "Storekeeper": "مسئول انبار",
    "Stocktake Lead": "مسئول انبارگردانی",
    "Inventory Operator": "انباردار",
    "Accountant": "حسابدار",
    "Viewer": "ناظر",
}


def role_title_fa(name: str) -> str:
    return ROLE_TITLES_FA.get(name, name)


def ensure_standard_roles(db) -> list:
    """نقش‌های استاندارد فروشگاه را در صورت نبود می‌سازد (idempotent)."""
    from .models import Permission, Role
    created = []
    for name, codes in ROLE_PRESETS.items():
        role = db.query(Role).filter(Role.name == name).one_or_none()
        if role is None:
            role = Role(name=name, description=role_title_fa(name), is_system=True)
            db.add(role)
            created.append(role)
        perms = db.query(Permission).filter(Permission.code.in_(codes)).all()
        have = {p.code for p in role.permissions}
        for p in perms:
            if p.code not in have:
                role.permissions.append(p)
    if created:
        db.commit()
    return created


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except ValueError:
        return False


def create_access_token(subject: str, extra: dict | None = None) -> str:
    payload = {"sub": subject, "exp": datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES), "jti": uuid4().hex}
    if extra:
        payload.update(extra)
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


# --- Token revocation (logout) -------------------------------------------------
# In-memory blocklist of revoked token ids until their natural expiry.
_REVOKED: dict[str, float] = {}


def revoke_token(token: str) -> None:
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    except jwt.PyJWTError:
        return
    exp = payload.get("exp")
    if exp:
        _REVOKED[payload.get("jti", token)] = float(exp)


def _prune_revoked() -> None:
    now = time.time()
    for jti, exp in list(_REVOKED.items()):
        if exp <= now:
            _REVOKED.pop(jti, None)


def is_revoked(token: str) -> bool:
    _prune_revoked()
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    except jwt.PyJWTError:
        return True
    return payload.get("jti") in _REVOKED


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    except jwt.PyJWTError:
        raise _CREDENTIAL_EXC


def _user_permission_codes(user: User) -> set[str]:
    codes: set[str] = set()
    for role in user.roles:
        codes.update(p.code for p in role.permissions)
    # build-488 — دسترسی مستقیم مستقل از Role (§۲): User → Permissions
    codes.update(p.code for p in user.direct_permissions)
    return codes


def get_current_user(token: Annotated[str, Depends(oauth2_scheme)], db: Annotated[Session, Depends(get_db)]) -> User:
    if is_revoked(token):
        raise _CREDENTIAL_EXC
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


def is_admin(user: User) -> bool:
    """The main admin (role «Administrator») — always allowed to work standalone
    (phone without the PC, outside the shop network). Everyone else is governed
    by ``users.local_only`` («دسترسی فقط به صورت بومی»)."""
    return any(r.name == "Administrator" for r in user.roles)
