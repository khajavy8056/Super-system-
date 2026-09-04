"""First-run bootstrap: permissions, roles, admin user, default settings.

Idempotent — safe to run on every startup.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .models import Permission, Role, SystemSetting, User
from .security import PERMISSIONS, ROLE_PRESETS, hash_password

DEFAULT_SETTINGS: dict[str, tuple[str, str]] = {
    "pos.tax_rate": ("0", "Tax rate in percent applied at checkout"),
    "pos.allocation_policy": ("HYBRID", "Allocation policy: FIFO | FEFO | MANUAL | HYBRID"),
    "pos.batch_selection_mode": ("HYBRID", "Batch selection mode: AUTO | MANUAL | HYBRID"),
    "pos.currency": ("IRR", "Display currency code"),
    "pos.allow_negative_stock": ("false", "Allow negative stock (requires permission + audit)"),
    "expiry.block_sale": ("true", "Block sale of expired batches"),
    "expiry.days.today": ("0", "Threshold (days) for 'expiring today' bucket"),
    "expiry.days.three": ("3", "Threshold (days) for 'expiring in 3 days' bucket"),
    "expiry.days.seven": ("7", "Threshold (days) for 'expiring in 7 days' bucket"),
    "expiry.days.thirty": ("30", "Threshold (days) for 'expiring in 30 days' bucket"),
    "barcode.scanner.min_interval_ms": ("30", "Minimum inter-keystroke interval to detect a scanner"),
    "sms.provider": ("", "SMS provider code (e.g. melipayamak)"),
    "sms.username": ("", "SMS provider username"),
    "sms.password": ("", "SMS provider password"),
    "printer.paper_width_mm": ("80", "Thermal printer paper width in mm"),
    "printer.header": ("", "Receipt header text"),
    "printer.footer": ("", "Receipt footer text"),
}


def bootstrap(db: Session) -> None:
    # 1. Permissions
    existing = {p.code for p in db.execute(select(Permission)).scalars()}
    for code, desc in PERMISSIONS.items():
        if code not in existing:
            db.add(Permission(code=code, description=desc))
    db.flush()  # ensure newly added permissions are visible to the next query

    # 2. Roles + permission mapping
    perm_map = {p.code: p for p in db.execute(select(Permission)).scalars()}
    roles = {r.name: r for r in db.execute(select(Role)).scalars()}
    for role_name, codes in ROLE_PRESETS.items():
        role = roles.get(role_name)
        if role is None:
            role = Role(name=role_name, description=role_name, is_system=True)
            db.add(role)
            db.flush()
            roles[role_name] = role
        role.permissions = [perm_map[c] for c in codes if c in perm_map]

    # 3. Admin user
    admin = db.execute(select(User).where(User.username == settings.ADMIN_USERNAME)).scalar_one_or_none()
    if admin is None:
        admin = User(
            username=settings.ADMIN_USERNAME,
            full_name="Administrator",
            password_hash=hash_password(settings.ADMIN_PASSWORD),
            is_active=True,
        )
        db.add(admin)
        db.flush()
    if roles.get("Administrator") and roles["Administrator"] not in admin.roles:
        admin.roles.append(roles["Administrator"])

    # 4. Default settings (only create, never overwrite user changes)
    current_keys = {s.key for s in db.execute(select(SystemSetting)).scalars()}
    for key, (value, desc) in DEFAULT_SETTINGS.items():
        if key not in current_keys:
            db.add(SystemSetting(key=key, value=value, description=desc))

    db.commit()
