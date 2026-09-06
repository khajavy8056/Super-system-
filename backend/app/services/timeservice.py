"""Trusted time + Persian (Jalali) calendar (§22).

Two separate concerns, deliberately kept apart:

1. **Trust.** Every financial record is timestamped in UTC from the machine
   clock. A cashier PC with a wrong clock silently mis-dates invoices, so we
   query NTP and report the *drift*. We do NOT quietly rewrite timestamps with
   network time: a hidden correction is worse than a visible warning. The
   drift is surfaced in diagnostics so a human fixes the clock.

2. **Display.** Iranian users read Jalali dates. Storage stays UTC ISO-8601;
   conversion happens only at the presentation boundary.

The Jalali conversion is implemented here (≈40 lines, exact for 1178–1633 SH)
rather than adding a dependency, keeping the offline Windows installer small.
No third-party call is required to render a date.
"""
from __future__ import annotations

import socket
import struct
from datetime import date as _date
from datetime import datetime, timezone

# NTP epoch (1900-01-01) to Unix epoch (1970-01-01)
_NTP_DELTA = 2_208_988_800

_PERSIAN_MONTHS = [
    "فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور",
    "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند",
]
_PERSIAN_WEEKDAYS = [
    "دوشنبه", "سه‌شنبه", "چهارشنبه", "پنج‌شنبه", "جمعه", "شنبه", "یکشنبه",
]
_PERSIAN_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")


# ---------------------------------------------------------------------------
# Jalali conversion (Gregorian <-> Jalali), via Julian Day Number
# ---------------------------------------------------------------------------
def _div(a: int, b: int) -> int:
    return a // b


#: JDN of proleptic-Gregorian 0001-01-01 minus 1, so that
#: JDN = date.toordinal() + _JDN_ORDINAL_OFFSET.
#: Python's `date.toordinal()` is exact and already in the standard library,
#: so we lean on it instead of hand-rolled civil-calendar arithmetic — an
#: earlier hand-transcribed version was silently off by 365 days for some
#: dates, which is exactly the kind of bug that mis-dates invoices.
_JDN_ORDINAL_OFFSET = 1_721_425


def _gregorian_to_jdn(gy: int, gm: int, gd: int) -> int:
    """Julian Day Number for a proleptic Gregorian date."""
    return _date(gy, gm, gd).toordinal() + _JDN_ORDINAL_OFFSET


def _jdn_to_gregorian(jdn: int) -> tuple[int, int, int]:
    d = _date.fromordinal(jdn - _JDN_ORDINAL_OFFSET)
    return d.year, d.month, d.day


#: Year boundaries of the 33-year leap cycles of the Iranian calendar.
#: This is the standard `breaks` table (Borkowski); it makes the conversion
#: EXACT for Jalali years 1178–1633 SH, which covers every date this system
#: will ever store. An approximate 2820-year formula was tried first and put
#: Nowruz 1400 one day late — hence the table.
_BREAKS = [-61, 9, 38, 199, 426, 686, 756, 818, 1111, 1181, 1210,
           1635, 2060, 2097, 2192, 2262, 2324, 2394, 2456, 3178]


def _jal_cal(jy: int) -> tuple[int, int, int]:
    """Return (leap, gy, march) for a Jalali year.

    `leap` = 0 if `jy` is a leap year, otherwise the years since the last one;
    `march` = the Gregorian day in March of `gy` that is 1 Farvardin `jy`.
    """
    gy = jy + 621
    leap_j = -14
    jp = _BREAKS[0]
    if jy < jp or jy >= _BREAKS[-1]:
        raise ValueError(f"Jalali year out of supported range: {jy}")

    jump = 0
    for jm in _BREAKS[1:]:
        jump = jm - jp
        if jy < jm:
            break
        leap_j += _div(jump, 33) * 8 + _div(jump % 33, 4)
        jp = jm

    n = jy - jp
    leap_j += _div(n, 33) * 8 + _div(n % 33 + 3, 4)
    if jump % 33 == 4 and jump - n == 4:
        leap_j += 1

    leap_g = _div(gy, 4) - _div((_div(gy, 100) + 1) * 3, 4) - 150
    march = 20 + leap_j - leap_g

    if jump - n < 6:
        n = n - jump + _div(jump + 4, 33) * 33
    leap = ((n + 1) % 33 - 1) % 4
    if leap == -1:
        leap = 4
    return leap, gy, march


def _jalali_leap(jy: int) -> bool:
    return _jal_cal(jy)[0] == 0


def _jalali_to_jdn(jy: int, jm: int, jd: int) -> int:
    _, gy, march = _jal_cal(jy)
    return (_gregorian_to_jdn(gy, 3, march) + (jm - 1) * 31
            - _div(jm, 7) * (jm - 7) + jd - 1)


def _jdn_to_jalali(jdn: int) -> tuple[int, int, int]:
    gy = _jdn_to_gregorian(jdn)[0]
    jy = gy - 621
    leap, _, march = _jal_cal(jy)
    jdn1f = _gregorian_to_jdn(gy, 3, march)
    k = jdn - jdn1f
    if k >= 0:
        if k <= 185:
            return jy, 1 + _div(k, 31), (k % 31) + 1
        k -= 186
    else:
        # Previous Jalali year. NOTE: the leap flag must be the one computed
        # for the ORIGINAL jy above, not for the decremented year — checking it
        # after the decrement shifted every Dey/Bahman/Esfand date by one day.
        jy -= 1
        k += 179
        if leap == 1:
            k += 1
    return jy, 7 + _div(k, 30), (k % 30) + 1


def to_jalali(dt: datetime) -> tuple[int, int, int]:
    """Convert a datetime's calendar date to a Jalali (year, month, day)."""
    return _jdn_to_jalali(_gregorian_to_jdn(dt.year, dt.month, dt.day))


def from_jalali(jy: int, jm: int, jd: int) -> tuple[int, int, int]:
    """Convert a Jalali date back to a Gregorian (year, month, day)."""
    return _jdn_to_gregorian(_jalali_to_jdn(jy, jm, jd))


def format_jalali(dt: datetime, *, with_time: bool = True,
                  persian_digits: bool = True) -> str:
    """Render '۱۴ شهریور ۱۴۰۵ — ۱۴:۳۰' style output for the UI/receipt."""
    jy, jm, jd = to_jalali(dt)
    text = f"{jd} {_PERSIAN_MONTHS[jm - 1]} {jy}"
    if with_time:
        text += f" — {dt.hour:02d}:{dt.minute:02d}"
    return text.translate(_PERSIAN_DIGITS) if persian_digits else text


# ---------------------------------------------------------------------------
# trusted time
# ---------------------------------------------------------------------------
def query_ntp(server: str, timeout: float = 3.0) -> datetime:
    """Return the UTC time reported by an NTP server. Raises on failure."""
    packet = b"\x1b" + 47 * b"\0"
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.settimeout(timeout)
        sock.sendto(packet, (server, 123))
        data, _ = sock.recvfrom(48)
    finally:
        sock.close()
    if len(data) < 48:
        raise OSError(f"short NTP response from {server}")
    seconds = struct.unpack("!12I", data)[10]
    if seconds == 0:
        raise OSError(f"invalid NTP response from {server}")
    return datetime.fromtimestamp(seconds - _NTP_DELTA, tz=timezone.utc)


def check_time_sync(servers: list[str], max_drift_seconds: int = 120,
                    timeout: float = 3.0) -> dict:
    """Compare the local clock against trusted time.

    Returns an honest verdict. If no server is reachable the status is
    ``UNVERIFIED`` — never ``PASS`` — because an unreachable time source
    proves nothing about the local clock.
    """
    local = datetime.now(timezone.utc)
    errors: list[str] = []

    for server in servers:
        server = server.strip()
        if not server:
            continue
        try:
            network = query_ntp(server, timeout=timeout)
        except Exception as exc:  # noqa: BLE001 - report, never crash
            errors.append(f"{server}: {exc.__class__.__name__}")
            continue

        drift = (network - local).total_seconds()
        ok = abs(drift) <= max_drift_seconds
        return {
            "status": "PASS" if ok else "WARNING",
            "source": server,
            "network_utc": network.isoformat(),
            "local_utc": local.isoformat(),
            "drift_seconds": round(drift, 3),
            "max_drift_seconds": max_drift_seconds,
            "message": (
                f"ساعت سیستم با زمان مرجع هماهنگ است (اختلاف {drift:.1f} ثانیه)"
                if ok else
                f"اختلاف ساعت سیستم با زمان مرجع {drift:.1f} ثانیه است؛ "
                f"ساعت ویندوز را تصحیح کنید"
            ),
        }

    return {
        "status": "UNVERIFIED",
        "source": None,
        "network_utc": None,
        "local_utc": local.isoformat(),
        "drift_seconds": None,
        "max_drift_seconds": max_drift_seconds,
        "message": (
            "هیچ سرور زمان در دسترس نبود؛ زمان محلی سیستم استفاده می‌شود "
            "(قابل اعتماد بودن آن تأیید نشد)"
        ),
        "errors": errors,
    }


def now_utc() -> datetime:
    """The single source of truth for record timestamps."""
    return datetime.now(timezone.utc)


def describe_now(timezone_name: str = "Asia/Tehran",
                 calendar: str = "jalali") -> dict:
    """Everything the status bar (§21) needs in one payload."""
    utc = now_utc()
    try:
        from zoneinfo import ZoneInfo

        local = utc.astimezone(ZoneInfo(timezone_name))
        tz_ok = True
    except Exception:  # noqa: BLE001 - unknown tz must not break the UI
        local = utc
        timezone_name = "UTC"
        tz_ok = False

    return {
        "utc": utc.isoformat(),
        "local": local.isoformat(),
        "timezone": timezone_name,
        "timezone_resolved": tz_ok,
        "calendar": calendar,
        "jalali": format_jalali(local),
        "jalali_date": format_jalali(local, with_time=False),
        "gregorian": local.strftime("%Y-%m-%d %H:%M"),
        "weekday": _PERSIAN_WEEKDAYS[local.weekday()],
    }
