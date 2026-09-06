"""Hardware abstraction layer (blueprint §71–74, §19–20).

Business logic never touches hardware directly. In a headless/test environment
there is no physical device, so every call is honest about that fact: a printer
failure marks ``print_status=FAILED`` (never rolls back the sale) and a text
receipt is always renderable for preview/reprint.
"""
from __future__ import annotations

import math
import socket
from datetime import datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import HardwareDevice, Invoice, SystemSetting
from .audit import write_audit


def get_setting(db: Session, key: str, default: str) -> str:
    row = db.execute(select(SystemSetting).where(SystemSetting.key == key)).scalar_one_or_none()
    return row.value if row else default


_RECEIPT_TZ: dict = {}


def _fa_date(dt) -> str:
    """Jalali date/time for the receipt (falls back to ISO)."""
    if not dt:
        return "-"
    try:
        from datetime import timezone as _tz
        from zoneinfo import ZoneInfo
        from .timeservice import format_jalali
        # timestamps are stored naive-UTC; the receipt must show shop local time
        tzname = _RECEIPT_TZ.get("name") or "Asia/Tehran"
        try:
            local = (dt.replace(tzinfo=_tz.utc) if dt.tzinfo is None else dt).astimezone(ZoneInfo(tzname))
        except Exception:
            local = dt
        return format_jalali(local, with_time=True)
    except Exception:
        return dt.strftime("%Y-%m-%d %H:%M")


def receipt_text(invoice: Invoice, *, header: str = "", footer: str = "",
                 columns: int = 32, store: dict | None = None,
                 currency_label: str = "تومان") -> str:
    """Persian thermal receipt (§17, §243). ``columns`` follows the paper width
    (§180): 32 for 58 mm, 42 for 76 mm, 48 for 80 mm."""
    W = max(24, int(columns))
    store = store or {}
    lines: list[str] = []
    sep = "-" * W

    def kv(label: str, value: str) -> str:
        pad = W - len(label) - len(value)
        return f"{label}{' ' * max(1, pad)}{value}"

    if store.get("name"):
        lines.append(store["name"].center(W))
    if header:
        lines.append(header.center(W))
    for k in ("address", "phone"):
        if store.get(k):
            lines.append(str(store[k]).center(W))
    lines.append(sep)
    lines.append(kv("فاکتور:", invoice.invoice_number))
    lines.append(kv("تاریخ:", _fa_date(invoice.created_at)))
    if invoice.customer is not None:
        lines.append(kv("مشتری:", (invoice.customer.name or "")[: W - 8]))
    lines.append(sep)
    for it in invoice.items:
        name = (it.product.name if it.product else f"#{it.product_id}")[: W - 2]
        lines.append(name)
        lines.append(kv(f"  {it.qty:g} × {it.unit_sell_price:,.0f}", f"{it.subtotal:,.0f}"))
        if it.discount:
            lines.append(kv("  تخفیف خط", f"-{it.discount:,.0f}"))
    lines.append(sep)
    lines.append(kv("جمع کل:", f"{invoice.subtotal:,.0f}"))
    if invoice.discount:
        lines.append(kv("تخفیف:", f"-{invoice.discount:,.0f}"))
    if invoice.tax:
        lines.append(kv("مالیات:", f"{invoice.tax:,.0f}"))
    lines.append(kv("قابل پرداخت:", f"{invoice.total_amount:,.0f} {currency_label}"))
    method = {"CASH": "نقدی", "CARD": "کارت", "ACCOUNT": "نسیه (حساب دفتری)",
              "MIXED": "ترکیبی"}.get(invoice.payment_method, invoice.payment_method)
    lines.append(kv("روش پرداخت:", method))
    lines.append(sep)
    if footer:
        lines.append(footer.center(W))
    lines.append("از خرید شما سپاسگزاریم".center(W))
    return "\n".join(lines)


def printer_profile(db: Session) -> dict:
    """Resolved printer settings (§180–§182)."""
    from .escpos_driver import columns_for_width
    width = int(get_setting(db, "printer.paper_width_mm", "80") or 80)
    cur = get_setting(db, "pos.currency", "IRT")
    return {
        "paper_width_mm": width,
        "columns": columns_for_width(width),
        "cut": get_setting(db, "printer.cut", "true").lower() == "true",
        "drawer_enabled": get_setting(db, "printer.drawer.enabled", "true").lower() == "true",
        "drawer_pin": int(get_setting(db, "printer.drawer.pin", "2") or 2),
        "header": get_setting(db, "printer.header", ""),
        "footer": get_setting(db, "printer.footer", ""),
        "store": {"name": get_setting(db, "store.name", ""),
                  "address": get_setting(db, "store.address", ""),
                  "phone": get_setting(db, "store.phone", "")},
        "currency_label": "ریال" if cur == "IRR" else "تومان",
        "logo_file": _logo_file(get_setting(db, "store.logo_path", "")),
    }


def _logo_file(logo_path: str) -> str | None:
    """Map the stored `/media/store-logo.png?v=..` URL to a raster file on disk."""
    if not logo_path or not logo_path.startswith("/media/"):
        return None
    from pathlib import Path
    from ..config import settings as app_settings
    name = logo_path[len("/media/"):].split("?", 1)[0]
    f = Path(app_settings.MEDIA_DIR) / name
    if f.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp") and f.is_file():
        return str(f)
    return None


def render_receipt(db: Session, invoice: Invoice) -> str:
    prof = printer_profile(db)
    _RECEIPT_TZ["name"] = get_setting(db, "time.timezone", "Asia/Tehran") or "Asia/Tehran"
    return receipt_text(invoice, header=prof["header"], footer=prof["footer"],
                        columns=prof["columns"], store=prof["store"],
                        currency_label=prof["currency_label"])


def _printer(db: Session) -> HardwareDevice | None:
    """Latest registered enabled printer (a terminal has ONE active printer)."""
    return db.execute(
        select(HardwareDevice)
        .where(HardwareDevice.device_type == "PRINTER", HardwareDevice.is_enabled.is_(True))
        .order_by(HardwareDevice.id.desc()).limit(1)
    ).scalar_one_or_none()


def print_receipt(db: Session, *, invoice: Invoice, kick_drawer: bool = False) -> tuple[bool, str]:
    """Attempt to print. Returns (ok, message). Never raises for hardware issues.

    Real transports: ``file://`` (test sink), ``tcp://host[:9100]`` (raw
    ESC/POS, pure Python) and ``escpos:`` (python-escpos for USB/Windows).
    SUCCESS is recorded only when bytes were actually delivered."""
    prof = printer_profile(db)
    text = render_receipt(db, invoice)
    device = _printer(db)

    def fail(reason: str, msg: str) -> tuple[bool, str]:
        invoice.print_status = "FAILED"
        write_audit(db, action="PRINT_FAILED", entity_type="Invoice", entity_id=invoice.id, reference=reason)
        return False, msg

    if device is None:
        return fail("No printer configured", "PRINTER_OFFLINE: no printer configured")

    conn = (device.connection or "").strip()
    if conn.startswith("file://"):
        try:
            path = Path(conn[len("file://"):])
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
            invoice.print_status = "SUCCESS"
            write_audit(db, action="PRINT_SUCCESS", entity_type="Invoice", entity_id=invoice.id)
            return True, "printed to file"
        except OSError as e:
            return fail(str(e), f"PRINTER_OFFLINE: {e}")

    if conn.startswith("tcp://") or conn.startswith("escpos:"):
        from .escpos_driver import print_via_escpos
        ok, detail = print_via_escpos(
            conn, text, columns=prof["columns"], cut=prof["cut"],
            kick_drawer=kick_drawer and prof["drawer_enabled"], drawer_pin=prof["drawer_pin"],
            logo_path=prof["logo_file"])
        if ok:
            invoice.print_status = "SUCCESS"
            write_audit(db, action="PRINT_SUCCESS", entity_type="Invoice", entity_id=invoice.id,
                        reference=detail)
            return True, "printed via ESC/POS"
        return fail(detail, detail)

    if device.status != "CONNECTED":
        return fail("Printer disconnected", "PRINTER_OFFLINE: device not connected")
    return fail("NOT_SUPPORTED: no real driver for this connection type",
                "NOT_SUPPORTED: use file://, tcp://host:9100 or escpos:usb:VID:PID")


def open_cash_drawer(db: Session) -> tuple[bool, str]:
    """§19/§182 — kick the drawer through the receipt printer (ESC p).

    A drawer has no port of its own; it is wired to the printer's DK
    connector. So the pulse goes to the *printer* connection. Honest result:
    True only when the bytes were delivered."""
    prof = printer_profile(db)
    if not prof["drawer_enabled"]:
        return False, "CASH_DRAWER_DISABLED"
    drawer = db.execute(
        select(HardwareDevice)
        .where(HardwareDevice.device_type == "CASH_DRAWER", HardwareDevice.is_enabled.is_(True))
        .order_by(HardwareDevice.id.desc()).limit(1)
    ).scalar_one_or_none()
    printer = _printer(db)
    conn = ((drawer.connection if drawer and drawer.connection else None)
            or (printer.connection if printer else "") or "").strip()
    if not drawer and not printer:
        return False, "CASH_DRAWER_UNAVAILABLE"
    if conn.startswith("file://"):
        try:
            with open(conn[len("file://"):], "a", encoding="utf-8") as f:
                f.write("\n[ESC p] cash drawer kick\n")
            write_audit(db, action="DRAWER_OPENED", entity_type="HardwareDevice",
                        entity_id=drawer.id if drawer else None, reference="file sink")
            return True, "drawer pulse written (file sink)"
        except OSError as e:
            return False, f"CASH_DRAWER_UNAVAILABLE: {e}"
    if conn.startswith("tcp://") or conn.startswith("escpos:"):
        from .escpos_driver import kick_drawer
        ok, detail = kick_drawer(conn, prof["drawer_pin"])
        write_audit(db, action="DRAWER_OPENED" if ok else "DRAWER_FAILED",
                    entity_type="HardwareDevice", entity_id=drawer.id if drawer else None,
                    reference=detail)
        return ok, ("drawer pulse sent" if ok else f"CASH_DRAWER_UNAVAILABLE: {detail}")
    return False, "CASH_DRAWER_UNAVAILABLE"


def detect_scanner(intervals_ms: list[float], threshold_ms: float | None = None,
                   setting_default: float = 30.0) -> bool:
    """Timing-based barcode scanner detection (blueprint §10).

    A scanner types a burst of characters with very small, uniform inter-key
    intervals; a human does not. The threshold is configurable, not a hard-coded
    architectural truth.
    """
    if not intervals_ms:
        return False
    threshold = threshold_ms if threshold_ms is not None else setting_default
    return max(intervals_ms) <= threshold and (len(intervals_ms) >= 3 or max(intervals_ms) <= threshold / 2)


# --- Diagnostic probes (§43) ---------------------------------------------------

def probe_printer(db: Session, device: HardwareDevice) -> tuple[bool, str]:
    """Real reachability probe for a printer. Never fakes a success."""
    conn = (device.connection or "").strip()
    if conn.startswith("file://"):
        path = Path(conn[len("file://"):])
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "a", encoding="utf-8"):
                pass
            return True, f"file sink writable: {path}"
        except OSError as e:
            return False, f"file sink not writable: {e}"
    if conn.startswith("escpos:"):
        try:
            from .escpos_driver import probe_escpos
        except ImportError:
            return False, "DRIVER_UNAVAILABLE: python-escpos not installed"
        return probe_escpos(conn)
    if conn.startswith("tcp://"):
        host_port = conn[len("tcp://"):]
        host, _, port = host_port.partition(":")
        try:
            with socket.create_connection((host, int(port or 9100)), timeout=3):
                return True, f"TCP printer reachable at {host}:{port or 9100}"
        except (OSError, ValueError) as e:
            return False, f"TCP printer unreachable: {e}"
    return False, "NOT_SUPPORTED: unknown connection scheme (use file://, tcp:// or escpos:)"


def probe_drawer(db: Session, device: HardwareDevice) -> tuple[bool, str]:
    """A cash drawer is pulsed through the printer — probe that path."""
    printer = _printer(db)
    if printer is None:
        return False, "Cash drawer needs a configured printer to send the pulse"
    ok, detail = probe_printer(db, printer)
    return ok, ("drawer pulse path available via printer — " + detail) if ok else detail


def probe_scanner(db: Session, device: HardwareDevice) -> tuple[bool, str]:
    """USB-HID scanners present as keyboards: no port to open. We verify the
    device record and the detection threshold instead, and say so honestly."""
    threshold = get_setting(db, "barcode.scanner.min_interval_ms", "30")
    conn = (device.connection or "HID").strip()
    if conn.startswith("tcp://"):
        host, _, port = conn[len("tcp://"):].partition(":")
        try:
            with socket.create_connection((host, int(port or 9100)), timeout=3):
                return True, f"network scanner reachable at {host}:{port}"
        except (OSError, ValueError) as e:
            return False, f"network scanner unreachable: {e}"
    return True, (f"HID keyboard-wedge scanner registered; timing detection active "
                  f"(threshold {threshold} ms). A physical scan is required for "
                  f"end-to-end confirmation.")
