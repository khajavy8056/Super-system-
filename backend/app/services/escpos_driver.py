"""Optional ESC/POS driver bridge (python-escpos).

Connection string format:
  escpos:usb:VID:PID            e.g. escpos:usb:0416:5011
  escpos:net:HOST:PORT          e.g. escpos:net:192.168.1.87:9100
  escpos:win:PRINTER_NAME       Windows spooler via win32print

This module is only imported when an ``escpos:`` printer is actually used, so
the base install has no hard dependency. REAL printing (and therefore a PASS
in TEST_REPORT) requires physical hardware — see the honest hardware test
table. Without hardware, behaviour is classified DRIVER_UNAVAILABLE / device
errors, never fake success.
"""
from __future__ import annotations


def _parse(conn: str):
    # conn arrives as "escpos:usb:0416:5011" etc.
    parts = conn.split(":", 2)
    if len(parts) < 2:
        raise ValueError("bad escpos connection string")
    kind = parts[1]
    rest = parts[2] if len(parts) > 2 else ""
    return kind, rest


def print_via_escpos(conn: str, text: str) -> tuple[bool, str]:
    try:
        return _print_via_escpos(conn, text)
    except ImportError:
        return False, "DRIVER_UNAVAILABLE: python-escpos not installed (requirements-hardware.txt)"
    except Exception as exc:  # device errors are reported, never faked
        return False, f"PRINTER_ERROR: {type(exc).__name__}: {exc}"


def _print_via_escpos(conn: str, text: str) -> tuple[bool, str]:
    kind, rest = _parse(conn)
    if kind == "usb":
        vid, pid = rest.split(":")
        from escpos.printer import Usb  # type: ignore
        p = Usb(int(vid, 16), int(pid, 16))
    elif kind == "net":
        host, port = rest.rsplit(":", 1)
        from escpos.printer import Network  # type: ignore
        p = Network(host, int(port))
    elif kind == "win":
        from escpos.printer import Win32Raw  # type: ignore
        p = Win32Raw(rest)
    else:
        return False, f"unknown escpos target: {kind}"
    try:
        p.text(text)
        p.cut()
    finally:
        try:
            p.close()
        except Exception:
            pass
    return True, "ok"
