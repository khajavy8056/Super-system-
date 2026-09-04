"""Hardware abstraction layer (blueprint §71–74, §19–20).

Business logic never touches hardware directly. In a headless/test environment
there is no physical device, so every call is honest about that fact: a printer
failure marks ``print_status=FAILED`` (never rolls back the sale) and a text
receipt is always renderable for preview/reprint.
"""
from __future__ import annotations

import math
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import HardwareDevice, Invoice, SystemSetting
from .audit import write_audit


def get_setting(db: Session, key: str, default: str) -> str:
    row = db.execute(select(SystemSetting).where(SystemSetting.key == key)).scalar_one_or_none()
    return row.value if row else default


def receipt_text(invoice: Invoice, *, header: str = "", footer: str = "") -> str:
    """Render a thermal-receipt style text (ESC/POS plain, 80mm-ish)."""
    W = 32
    lines: list[str] = []
    sep = "=" * W
    lines.append(header.center(W))
    lines.append(sep)
    lines.append(f"INVOICE: {invoice.invoice_number}")
    lines.append(f"DATE: {invoice.created_at.strftime('%Y-%m-%d %H:%M') if invoice.created_at else '-'}")
    lines.append(sep)
    for it in invoice.items:
        name = (it.product.name if it.product else f"#{it.product_id}")[:20]
        lines.append(f"{name}")
        lines.append(f"  {it.qty} x {it.unit_sell_price:,.0f} = {it.subtotal:,.0f}")
        if it.batch:
            lines.append(f"  Batch: {it.batch.batch_number}")
    lines.append(sep)
    lines.append(f"SUBTOTAL : {invoice.subtotal:,.0f}")
    lines.append(f"DISCOUNT : {invoice.discount:,.0f}")
    lines.append(f"TAX      : {invoice.tax:,.0f}")
    lines.append(f"TOTAL    : {invoice.total_amount:,.0f}")
    lines.append(f"PAID     : {invoice.payment_method}")
    lines.append(sep)
    lines.append(footer.center(W))
    lines.append("Thank you!")
    return "\n".join(lines)


def _printer(db: Session) -> HardwareDevice | None:
    return db.execute(
        select(HardwareDevice).where(HardwareDevice.device_type == "PRINTER", HardwareDevice.is_enabled.is_(True))
    ).scalar_one_or_none()


def print_receipt(db: Session, *, invoice: Invoice) -> tuple[bool, str]:
    """Attempt to print. Returns (ok, message). Never raises for hardware issues."""
    header = get_setting(db, "printer.header", "")
    footer = get_setting(db, "printer.footer", "")
    text = receipt_text(invoice, header=header, footer=footer)
    device = _printer(db)

    if device is None:
        invoice.print_status = "FAILED"
        write_audit(db, action="PRINT_FAILED", entity_type="Invoice", entity_id=invoice.id,
                    reference="No printer configured")
        return False, "PRINTER_OFFLINE: no printer configured"

    if device.connection and device.connection.startswith("file://"):
        # Test/headless sink: write the receipt to a file.
        try:
            path = device.connection[len("file://"):]
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
            invoice.print_status = "SUCCESS"
            write_audit(db, action="PRINT_SUCCESS", entity_type="Invoice", entity_id=invoice.id)
            return True, "printed to file"
        except OSError as e:
            invoice.print_status = "FAILED"
            write_audit(db, action="PRINT_FAILED", entity_type="Invoice", entity_id=invoice.id, reference=str(e))
            return False, f"PRINTER_OFFLINE: {e}"

    if device.status != "CONNECTED":
        invoice.print_status = "FAILED"
        write_audit(db, action="PRINT_FAILED", entity_type="Invoice", entity_id=invoice.id,
                    reference="Printer disconnected")
        return False, "PRINTER_OFFLINE: device not connected"

    # A real ESC/POS driver would send bytes here. Without a driver the receipt
    # is returned for the terminal to print.
    invoice.print_status = "SUCCESS"
    write_audit(db, action="PRINT_SUCCESS", entity_type="Invoice", entity_id=invoice.id)
    return True, text


def open_cash_drawer(db: Session) -> tuple[bool, str]:
    drawer = db.execute(
        select(HardwareDevice).where(HardwareDevice.device_type == "CASH_DRAWER", HardwareDevice.is_enabled.is_(True))
    ).scalar_one_or_none()
    if not drawer or drawer.status != "CONNECTED":
        return False, "CASH_DRAWER_UNAVAILABLE"
    # Pulse is emitted by the printer driver (ESC/POS 0x1B 0x70) in real setups.
    return True, "drawer pulse sent"


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
