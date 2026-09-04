"""First-run bootstrap: permissions, roles, admin user, default settings.

Idempotent — safe to run on every startup.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .models import Permission, Role, SystemSetting, User
from .security import PERMISSIONS, ROLE_PRESETS, hash_password

DEFAULT_SETTINGS: dict[str, tuple[str, str, bool]] = {
    "pos.tax_rate": ("0", "Tax rate in percent applied at checkout", False),
    "pos.allocation_policy": ("HYBRID", "Allocation policy: FIFO | FEFO | MANUAL | HYBRID", False),
    "pos.batch_selection_mode": ("HYBRID", "Batch selection mode: AUTO | MANUAL | HYBRID", False),
    "pos.currency": ("IRT", "Base currency: IRT (تومان) | IRR (ریال). Amounts are STORED in this unit.", False),
    "pos.coupon_enabled": ("true", "Enable coupon entry at the POS", False),
    "pos.print_after_checkout": ("true", "Automatically print the receipt after checkout", False),
    "pos.allow_negative_stock": ("false", "Allow negative stock (requires permission + audit)", False),
    "pos.kiosk_shortcut": ("Ctrl+Shift+L", "POS kiosk/lock mode keyboard shortcut", False),
    "expiry.block_sale": ("true", "Block sale of expired batches", False),
    "expiry.days.today": ("0", "Threshold (days) for 'expiring today' bucket", False),
    "expiry.days.three": ("3", "Threshold (days) for 'expiring in 3 days' bucket", False),
    "expiry.days.seven": ("7", "Threshold (days) for 'expiring in 7 days' bucket", False),
    "expiry.days.thirty": ("30", "Threshold (days) for 'expiring in 30 days' bucket", False),
    "barcode.scanner.min_interval_ms": ("30", "Minimum inter-keystroke interval to detect a scanner", False),
    "sms.provider": ("", "SMS provider code: melipayamak | kavenegar | file | (empty=disabled)", False),
    "sms.username": ("", "SMS provider username", True),
    "sms.password": ("", "SMS provider password", True),
    "sms.api_key": ("", "SMS provider API key (kavenegar)", True),
    "sms.sender": ("", "Sender line number (melipayamak)", False),
    "sms.file_path": ("data/sms_out.log", "Output file for the 'file' provider (dev/test)", False),
    "sms.max_retries": ("5", "Max delivery attempts before FAILED", False),
    "sms.worker_interval_seconds": ("10", "Background dispatch interval (seconds)", False),
    "printer.paper_width_mm": ("80", "Thermal printer paper width in mm", False),
    "backup.keep": ("10", "Number of backup files to retain (rotation)", False),
    "printer.header": ("", "Receipt header text", False),
    "printer.footer": ("", "Receipt footer text", False),
    "sync.worker_interval_seconds": ("15", "Offline sync queue drain interval (seconds)", False),
    "stocktake.require_approval": ("true", "Stock adjustments need manager approval", False),
    # --- store profile (§25) — printed on receipts and shown in the UI ---
    "store.name": ("فروشگاه من", "Store name (receipt header, UI title)", False),
    "store.legal_name": ("", "Registered legal name", False),
    "store.phone": ("", "Store phone number", False),
    "store.mobile": ("", "Store mobile number", False),
    "store.address": ("", "Store address (printed on the receipt)", False),
    "store.city": ("", "City", False),
    "store.postal_code": ("", "Postal code", False),
    "store.tax_id": ("", "Tax / economic ID", False),
    "store.logo_path": ("", "Relative path of the store logo under MEDIA_DIR", False),
    "store.receipt_note": ("از خرید شما سپاسگزاریم", "Footer note on the receipt", False),
    # --- time & calendar (§22) ---
    "time.timezone": ("Asia/Tehran", "IANA timezone for display and reports", False),
    "time.calendar": ("jalali", "Display calendar: jalali | gregorian", False),
    "time.ntp_enabled": ("true", "Check trusted network time at startup", False),
    "time.ntp_servers": ("pool.ntp.org,time.google.com",
                         "Comma-separated NTP servers (trusted time source)", False),
    "time.max_drift_seconds": ("120",
                               "Warn when local clock drifts more than this from NTP", False),
    # --- appearance (§23) ---
    "ui.theme": ("auto", "Theme: auto | light | dark", False),
    "ui.theme_light_at": ("07:00", "Local time to switch to the light theme", False),
    "ui.theme_dark_at": ("19:00", "Local time to switch to the dark theme", False),
}


def bootstrap(db: Session) -> None:
    from .services.units import ensure_units

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
    for key, (value, desc, is_secret) in DEFAULT_SETTINGS.items():
        if key not in current_keys:
            db.add(SystemSetting(key=key, value=value, description=desc, is_secret=is_secret))

    # 5. Default measurement units (§25 — piece / kg / gram / liter ...)
    ensure_units(db)

    db.commit()
