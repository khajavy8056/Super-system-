"""Barcode validation — GS1 checksum (GTIN-13/EAN-13/EAN-8/UPC-A/UPC-E).

A scanned code that fails its checksum is a mis-scan, not a product —
querying external sources with it wastes API calls and returns garbage.
"""
from __future__ import annotations

SUPPORTED_FORMATS = ("GTIN-13/EAN-13", "EAN-8", "UPC-A", "GTIN-14")


def _luhn_gs1(digits: str) -> bool:
    """GS1 modulo-10: from the right, weights alternate 1 (check digit), 3, 1, 3…"""
    total = 0
    for i, ch in enumerate(reversed(digits)):
        n = int(ch)
        if i % 2 == 1:
            n *= 3
        total += n
    return total % 10 == 0


def validate(barcode: str) -> tuple[bool, str | None]:
    """Return (ok, format). Empty/None/non-digit/checksum-fail -> (False, None)."""
    if not barcode or not barcode.isdigit():
        return False, None
    length = len(barcode)
    if length in (13, 14, 12) and _luhn_gs1(barcode):
        fmt = {13: "GTIN-13/EAN-13", 14: "GTIN-14/ITF", 12: "UPC-A"}.get(length)
        return True, fmt
    if length == 8 and _luhn_gs1(barcode):
        return True, "EAN-8"
    # EAN-8 leading-zero form (08...) collapses to a zero-padded UPC — treat as valid
    if length == 12 and _luhn_gs1(barcode):
        return True, "UPC-A"
    return False, None


def normalize(barcode: str) -> str:
    return (barcode or "").strip()
