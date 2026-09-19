# -*- coding: utf-8 -*-
"""The pricing rules the intelligence engine is not allowed to break.

Two facts about a real shop, both of which the engine used to ignore:

**1. The consumer price is a ceiling, not a suggestion.**
``قیمت مصرف‌کننده`` is printed on the pack and fixed by law. A shop may sell at that price or
*below* it — never above. So "raise the price to X" is only advice the shop can act on when X
is at or under the printed price. An engine that proposes more than that is not giving advice,
it is doing arithmetic that looks like profit on paper and is impossible at the till.

**2. The buy price of stock you already hold is a fact, not a lever.**
You cannot decide what you paid for goods that are already on the shelf. Telling the shop
"set the buy price to N" is meaningless — the only real levers are:

  * the **sell** price, within the ceiling above;
  * which **supplier** you buy from *next* time;
  * whether you keep stocking the item at all.

So a thin margin has exactly three honest remedies, and the engine must say which one applies
instead of inventing a fourth.

Everything that proposes or writes a price goes through here, and :func:`guard_sell_price` is
enforced by the executor as well, so a mistaken analyzer cannot push an illegal price into the
database even if its own reasoning is wrong.
"""
from __future__ import annotations

from decimal import Decimal

from ..models.inventory import ProductBatch


class PriceLawError(ValueError):
    """Raised when an action would write a price the shop is not allowed to charge."""


def _f(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def ceiling(batch: ProductBatch | None) -> float | None:
    """Highest price this batch may legally be sold at, or ``None`` when no price is printed.

    ``None`` means "unknown", not "unlimited" — callers should say so rather than assume they
    are free to pick any number.
    """
    if batch is None:
        return None
    c = _f(getattr(batch, "consumer_price", 0))
    return c if c > 0 else None


def clamp_sell(batch: ProductBatch | None, wanted: float) -> float:
    """The closest legal price to ``wanted`` — i.e. ``wanted``, capped at the ceiling."""
    c = ceiling(batch)
    return wanted if c is None else min(wanted, c)


def headroom(batch: ProductBatch | None, cost: float) -> dict:
    """What pricing can and cannot do for this batch, given what it cost.

    Returns ``legal_price`` (the best price the shop may charge), the margin at that price, and
    ``verdict`` — one of:

    ``"raise"``       there is room between the current price and the ceiling: raising is legal.
    ``"at_ceiling"``  already at (or above) the ceiling: pricing cannot help any more.
    ``"unprofitable"`` the ceiling is at or below cost: this item cannot be sold profitably at
                      any legal price, so the answer is procurement or delisting, never price.
    ``"unknown"``     no consumer price recorded, so nothing can be asserted.
    """
    c = ceiling(batch)
    sell = _f(getattr(batch, "sell_price", 0))
    if c is None:
        return {"legal_price": sell, "ceiling": None, "margin": None, "verdict": "unknown"}
    legal = min(sell, c) if sell > c else sell
    margin = (legal - cost) / legal if legal > 0 else 0.0
    if c <= cost:
        verdict = "unprofitable"
    elif sell >= c:
        verdict = "at_ceiling"
    else:
        verdict = "raise"
    return {"legal_price": legal, "ceiling": c, "margin": round(margin, 4), "verdict": verdict}


def guard_sell_price(batch: ProductBatch | None, price: float) -> float:
    """Return ``price`` if the shop may charge it; otherwise raise with a reason it can read.

    Called by the executor before writing, so the rule holds even for an insight produced by an
    analyzer that got it wrong or by an older database row.
    """
    c = ceiling(batch)
    if c is not None and price > c + 0.5:
        raise PriceLawError(
            f"قیمت پیشنهادی {_money(price)} از قیمت مصرف‌کنندهٔ درج‌شده ({_money(c)}) بالاتر است؛ "
            "فروش بالاتر از قیمت مصرف‌کننده مجاز نیست. یا قیمت مصرف‌کنندهٔ این کالا در سیستم "
            "اشتباه ثبت شده، یا این کالا در این قیمت خرید سود ندارد و راه‌حلش تأمین‌کنندهٔ "
            "ارزان‌تر یا حذف کالا است، نه افزایش قیمت.")
    return price


def buy_price_is_not_a_lever(batch: ProductBatch | None) -> str:
    """The sentence to use instead of "set the buy price to N".

    Kept in one place so no analyzer can quietly reintroduce advice the shop cannot follow.
    """
    cost = _f(getattr(batch, "buy_price", 0)) if batch is not None else 0.0
    return (f"قیمت خرید این موجودی ({_money(cost)}) یک واقعیت است و قابل تغییر نیست؛ "
            "اهرم‌های واقعی، قیمت فروش در حد قیمت مصرف‌کننده، تأمین‌کنندهٔ خرید بعدی، "
            "یا ادامهٔ موجودی‌کردن این کالا هستند.")


def _money(v) -> str:
    return f"{_f(v):,.0f}"


def money(v) -> str:
    """Public wrapper so analyzers do not have to import the private formatter."""
    return _money(v)


def to_decimal(v: float) -> Decimal:
    return Decimal(str(round(v)))
