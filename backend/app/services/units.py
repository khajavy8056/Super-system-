"""Quantity + currency helpers (§25, §39).

Quantities are ``Decimal`` with 3 decimal places everywhere (12.500 Kg is a
first-class value). Integer-only units are enforced at the service boundary so
"2.5 bottles" is still rejected.

Currency: amounts are ALWAYS stored in the base unit configured once at install
time (``pos.currency``: IRR or IRT). No implicit conversion ever happens on
write — the display layer only formats. This removes the rial/toman ambiguity
that otherwise silently multiplies every number by 10.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from sqlalchemy import select
from sqlalchemy.orm import Session

QTY_EXP = Decimal("0.001")
ZERO = Decimal("0")

#: seed units — (name, symbol, allow_decimal, decimals)
DEFAULT_UNITS: list[tuple[str, str, bool, int]] = [
    ("عدد", "pcs", False, 0),
    ("بسته", "pack", False, 0),
    ("کارتن", "box", False, 0),
    ("کیلوگرم", "kg", True, 3),
    ("گرم", "g", True, 0),
    ("لیتر", "L", True, 3),
    ("میلی‌لیتر", "ml", False, 0),
    ("متر", "m", True, 2),
]


class QuantityError(ValueError):
    pass


def to_qty(value) -> Decimal:
    """Coerce anything numeric to a 3-decimal Decimal quantity."""
    if isinstance(value, Decimal):
        d = value
    else:
        try:
            d = Decimal(str(value))
        except (InvalidOperation, TypeError):
            raise QuantityError(f"Invalid quantity: {value!r}")
    return d.quantize(QTY_EXP, ROUND_HALF_UP)


def validate_for_unit(db: Session, product, qty: Decimal) -> Decimal:
    """Reject fractional quantities for units that are not divisible (§25)."""
    from ..models import Unit

    qty = to_qty(qty)
    unit = db.get(Unit, product.unit_id) if getattr(product, "unit_id", None) else None
    if unit is not None and not unit.allow_decimal and qty != qty.to_integral_value():
        raise QuantityError(
            f"واحد «{unit.name}» اعشاری نیست؛ مقدار {fmt_qty(qty)} مجاز نیست"
        )
    return qty


def fmt_qty(qty: Decimal | float | int, decimals: int = 3) -> str:
    d = to_qty(qty)
    if d == d.to_integral_value():
        return str(int(d))
    return f"{d:.{decimals}f}".rstrip("0").rstrip(".")


def ensure_units(db: Session) -> int:
    """Idempotently seed the default unit table. Returns rows created."""
    from ..models import Unit

    existing = {u.name for u in db.execute(select(Unit)).scalars()}
    created = 0
    for name, symbol, allow_decimal, decimals in DEFAULT_UNITS:
        if name in existing:
            continue
        db.add(Unit(name=name, symbol=symbol, allow_decimal=allow_decimal, decimals=decimals))
        created += 1
    if created:
        db.flush()
    return created


# --- currency ----------------------------------------------------------------

CURRENCIES = {
    "IRR": {"code": "IRR", "label": "ریال", "decimals": 0, "step": 1000},
    "IRT": {"code": "IRT", "label": "تومان", "decimals": 0, "step": 100},
}


def currency_config(db: Session) -> dict:
    from ..models import SystemSetting

    row = db.execute(
        select(SystemSetting).where(SystemSetting.key == "pos.currency")
    ).scalar_one_or_none()
    code = (row.value if row else "IRT").upper()
    cfg = dict(CURRENCIES.get(code, CURRENCIES["IRT"]))
    cfg["note"] = (
        "All monetary values are stored in this unit. Changing it does NOT "
        "convert existing data."
    )
    return cfg
