"""v4.0 — Number grounding (§22, §46, §89).

The rule this module enforces: **if a language model writes a number, that
number must already exist in a deterministic tool result.** Not "look plausible"
— exist. Otherwise the sentence is rejected and the deterministic answer is used
instead, and the rejection is audited.

This is deliberately stricter than a plausibility check. A hallucinated
«۱۲ میلیون سود» is not caught by range checks (12 million is a perfectly normal
profit), only by provenance. So the tool registry registers every numeric leaf
it returns, and the prose is scanned for numbers that are not in that set.
"""
from __future__ import annotations

import re

#: Persian and ASCII digits, with optional thousand separators and decimals
_NUM_RE = re.compile(r"[۰-۹0-9][۰-۹0-9٬,٫.٫]*(?:\s*(?:میلیون|میلیارد|هزار|تومان|درصد|٪))?")
_FA2EN = str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")
_MULT = {"میلیون": 1_000_000, "میلیارد": 1_000_000_000, "هزار": 1_000}

#: small integers that appear in ordinary prose ("۳ روز", "۲ گزینه") and are not
#: economic claims; they are allowed without a tool result.
TRIVIAL_MAX = 31

#: money/profit/percent words that make a number an *economic claim*
CLAIM_WORDS = ("سود", "تومان", "ریال", "درآمد", "فروش", "حاشیه", "تخفیف", "نقدینگی", "طلب",
               "بدهی", "چک", "موجودی", "ارزش", "هزینه", "درصد", "٪", "میلیون", "میلیارد")


def _to_number(token: str) -> float | None:
    raw = token.strip().translate(_FA2EN).replace("٬", "").replace(",", "").replace("٫", ".")
    mult = 1
    for word, factor in _MULT.items():
        if word in raw:
            mult = factor
            raw = raw.replace(word, "").strip()
    raw = raw.replace("تومان", "").replace("درصد", "").replace("٪", "").strip()
    raw = raw.rstrip(".").strip()
    if not raw:
        return None
    try:
        return float(raw) * mult
    except ValueError:
        return None


def _close(value: float, known: set[float], rel: float = 0.02, abs_tol: float = 1.0) -> bool:
    for candidate in known:
        if abs(value - candidate) <= max(abs_tol, abs(candidate) * rel):
            return True
    return False


def extract_numbers(text: str) -> list[tuple[str, float]]:
    out: list[tuple[str, float]] = []
    for match in _NUM_RE.finditer(text or ""):
        value = _to_number(match.group(0))
        if value is not None:
            out.append((match.group(0).strip(), value))
    return out


def verify(text: str, known: set[float], *, context: str = "") -> dict:
    """Return ``{ok, offending:[...], checked:int}``.

    A number is accepted when it matches a tool-produced value (2 % tolerance),
    is a trivial small integer, or is a "structural" number the prompt itself
    supplied (dates, counts of options). Everything else is an offence.
    """
    offenders: list[str] = []
    checked = 0
    for token, value in extract_numbers(text):
        checked += 1
        if abs(value) <= TRIVIAL_MAX and value == int(value):
            continue
        if _close(value, known):
            continue
        window = _window(text, token)
        if any(word in window for word in CLAIM_WORDS) or _looks_like_money(token, window):
            offenders.append(token)
    return {"ok": not offenders, "offending": offenders[:8], "checked": checked, "context": context}


def _window(text: str, token: str, span: int = 40) -> str:
    index = text.find(token)
    if index < 0:
        return token
    return text[max(0, index - span): index + len(token) + span]


def _looks_like_money(token: str, window: str) -> bool:
    digits = re.sub(r"[^0-9]", "", token.translate(_FA2EN))
    return len(digits) >= 6 or "میلیون" in window or "میلیارد" in window


ALLOWED_SOURCES = ("tool", "policy", "situation", "deterministic")


def assert_grounded(text: str, known: set[float], *, context: str = "") -> str:
    """Raise ``ValueError`` when the text carries an unverifiable economic claim."""
    result = verify(text, known, context=context)
    if not result["ok"]:
        raise ValueError(f"ungrounded numbers: {result['offending']}")
    return text


def scrub(text: str, known: set[float]) -> str:
    """Replace unverifiable numeric tokens with «—» (last-resort fallback)."""
    result = verify(text, known)
    for token in result["offending"]:
        text = text.replace(token, "—")
    return text
