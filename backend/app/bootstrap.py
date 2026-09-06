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
    "sms.sender": ("", "Sender line number (melipayamak, line mode)", False),
    "sms.melipayamak_mode": ("line", "melipayamak mode: line (SendSMS from own line) | pattern (BaseServiceNumber / خط خدماتی)", False),
    "sms.melipayamak_body_id": ("", "melipayamak pattern (bodyId) for pattern mode", False),
    "sms.melipayamak_url": ("", "Override REST base URL (proxy/testing); empty = official", False),
    "sms.file_path": ("data/sms_out.log", "Output file for the 'file' provider (dev/test)", False),
    "sms.template.debt_reminder": (
        "{customer} گرامی، مانده بدهی شما نزد {store} مبلغ {amount} {currency} است. با تشکر.",
        "Debt reminder SMS template. Placeholders: {customer} {store} {amount} {currency}",
        False),
    "sms.template.invoice": (
        "{store} | فاکتور {invoice} | مبلغ {amount} {currency}{coupon_line}\nاز خرید شما سپاسگزاریم",
        "Invoice SMS template. Placeholders: {store} {invoice} {amount} {currency} {coupon_line}", False),
    "sms.template.coupon": (
        "{store} | کد تخفیف شما: {code} | تا {until} معتبر است",
        "Coupon SMS template. Placeholders: {store} {code} {until}", False),
    "sms.template.low_stock": (
        "{store} | هشدار انبار: {count} کالا زیر حداقل موجودی است: {items}",
        "Low-stock alert SMS template. Placeholders: {store} {count} {items}", False),
    "sms.template.daily_report": (
        "{store} | گزارش {date}: {invoices} فاکتور | فروش {sales} {currency} | سود {profit} {currency} | بدهی مشتریان {debt} {currency}",
        "Management report SMS template. Placeholders: {store} {date} {invoices} {sales} {profit} {debt} {currency}", False),
    "sms.admin_phone": ("", "Manager mobile for alerts / daily report (falls back to store.mobile)", False),
    "sms.low_stock_alert": ("false", "Send a low-stock alert SMS to the manager after the expiry/stock scan", False),
    "sms.send_invoice": ("true", "Send an invoice SMS to registered customers after checkout", False),
    "sms.max_retries": ("5", "Max delivery attempts before FAILED", False),
    "sms.worker_interval_seconds": ("10", "Background dispatch interval (seconds)", False),
    "printer.paper_width_mm": ("80", "Thermal printer paper width in mm", False),
    "printer.cut": ("true", "Send a paper-cut command after each receipt (ESC/POS)", False),
    "printer.drawer.enabled": ("true", "Pulse the cash drawer on cash sales", False),
    "printer.drawer.pin": ("2", "Cash drawer kick pin (2 or 5)", False),
    # --- inventory / products (§217–§218) ---
    "inventory.default_min_stock": ("5", "Default minimum stock for new products", False),
    "inventory.low_stock_alert": ("true", "Show low-stock alerts on the dashboard", False),
    "products.autofill_requires_confirm": ("true", "Auto-fill data must be confirmed by a human before saving", False),
    "pricing.default_margin_percent": ("20", "Default margin used to suggest a sell price", False),
    "pricing.round_to": ("1000", "Round suggested sell prices to this step", False),
    # --- customers / ledger (§221–§222) ---
    "customers.default_credit_limit": ("0", "Default credit limit for new customers (0 = unlimited)", False),
    "ledger.block_over_limit": ("true", "Block a credit sale that would exceed the customer's limit", False),
    # --- marketing (§223–§224) ---
    "marketing.coupon_prefix": ("SM", "Prefix for generated coupon codes", False),
    "marketing.max_discount_percent": ("50", "Ceiling for percent coupons created in the UI", False),
    # --- network / security (§228–§229) ---
    "network.lan_port": ("8000", "Port the local server listens on for LAN / mobile clients", False),
    "security.session_minutes": ("720", "Session lifetime in minutes", False),
    "security.require_admin_for_void_paid": ("true", "Voiding a PAID invoice requires admin password confirmation", False),
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
    # --- updates (§269/§270) ---
    "update.channel": ("github", "Update channel: github | server", False),
    "update.server_url": ("", "Update server manifest URL (JSON: version, asset_url, sha256 ...)", False),
    "update.server_token": ("", "Bearer token for the update server (optional)", True),
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

    # 6. Default product-resolver sources (§9-§11)
    #
    # Without at least one registered source the whole multi-source resolver is
    # dead code on a fresh install: scanning an unknown barcode returned
    # origin="none" with an empty `sources` list, so "add product by scan"
    # silently degraded to fully manual entry. Providers existed; nothing was
    # ever wired to them.
    #
    # OpenFoodFacts is the one source we can ship enabled by default and still
    # respect the licensing rule: the data is community-owned and published
    # under the Open Database License (ODbL), the API is public and keyless,
    # and it explicitly permits reuse with attribution. Commercial Iranian
    # catalogues (Holoo and friends) are deliberately NOT shipped — copying
    # them is exactly what the brief forbids. A shop that holds its own licence
    # for such a service can add it at runtime as a `custom_http` source
    # without any code change.
    ensure_default_sources(db)

    db.commit()


#: Sources registered on first boot. Only openly-licensed, keyless services.
DEFAULT_SOURCES: list[dict] = [
    {
        "code": "openfoodfacts",
        "name": "OpenFoodFacts (ODbL, public, keyless)",
        "source_type": "PRODUCT",
        "priority": 10,
        "base_url": "https://world.openfoodfacts.org/api/v2/product/{barcode}.json",
        "is_active": True,
    },
    {
        # Same upstream, registered separately so the IMAGE pipeline has a
        # source of its own and can be disabled independently of name/brand
        # lookups (a shop may want text but not pictures, or vice versa).
        "code": "openfoodfacts_img",
        "name": "OpenFoodFacts Images (ODbL)",
        "source_type": "IMAGE",
        "priority": 10,
        "base_url": "https://world.openfoodfacts.org/api/v2/product/{barcode}.json",
        "is_active": True,
    },
]


def ensure_default_sources(db: Session) -> None:
    """Register the built-in resolver sources (idempotent).

    Existing rows are never modified: if an operator disabled or re-pointed a
    source, that decision must survive a restart.
    """
    from .models import ExternalSource

    existing = {s.code for s in db.execute(select(ExternalSource)).scalars()}
    for spec in DEFAULT_SOURCES:
        if spec["code"] in existing:
            continue
        db.add(ExternalSource(**spec))
    db.flush()
