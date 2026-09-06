"""ESC/POS thermal printer + cash drawer driver (§17, §19, §178–§182).

Two transports, both REAL — nothing here ever returns a fake success:

* ``tcp://HOST[:PORT]``  — raw JetDirect socket (port 9100). This is how the
  vast majority of Ethernet/Wi-Fi receipt printers (Epson TM-T20/T88, Xprinter,
  Rongta, Bixolon, HPRT…) are driven. Pure Python, no extra package.
* ``escpos:usb:VID:PID`` / ``escpos:net:HOST:PORT`` / ``escpos:win:NAME`` —
  delegates to the optional ``python-escpos`` package (USB and the Windows
  spooler need it; see requirements-hardware.txt).
* ``file://PATH`` is handled by services/hardware.py as a test sink.

ESC/POS byte sequences (Epson ESC/POS Application Programming Guide):

  ESC @            1B 40           initialise
  ESC t n          1B 74 n         select code page (n=0x1E / 30 = Windows-1256
                                   Arabic on most Epson-compatible firmware)
  ESC a n          1B 61 n         justification 0=left 1=centre 2=right
  ESC E n          1B 45 n         bold on/off
  GS ! n           1D 21 n         character size (0x11 = double w+h)
  GS V m           1D 56 m         cut: 0/48 full, 1/49 partial
  GS V 66 n        1D 56 42 n      feed n then partial cut (most common)
  ESC d n          1B 64 n         feed n lines
  ESC p m t1 t2    1B 70 m t1 t2   cash-drawer kick: pin m (0=pin2, 1=pin5),
                                   on-time t1*2ms, off-time t2*2ms

Persian text: thermal firmware does not shape Arabic script. We render each
line as *visually ordered* text (reversed logical order per line, digits kept
LTR) and right-justify it, then encode with cp1256. Printers whose firmware
lacks cp1256 still receive well-formed bytes (chars they cannot map become
'?') — the layout, numbers and totals remain readable.
"""
from __future__ import annotations

import re
import socket
from dataclasses import dataclass

ESC = b"\x1b"
GS = b"\x1d"

INIT = ESC + b"@"
CODEPAGE_CP1256 = ESC + b"t" + bytes([30])
ALIGN_LEFT = ESC + b"a\x00"
ALIGN_CENTER = ESC + b"a\x01"
ALIGN_RIGHT = ESC + b"a\x02"
BOLD_ON = ESC + b"E\x01"
BOLD_OFF = ESC + b"E\x00"
DOUBLE_ON = GS + b"!\x11"
DOUBLE_OFF = GS + b"!\x00"


def cut_command(full: bool = False, feed_lines: int = 3) -> bytes:
    """GS V 66 n: feed then partial cut (universal); full cut when asked."""
    return GS + b"V" + (b"\x00" if full else b"B" + bytes([max(0, min(feed_lines, 255))]))


def drawer_kick_command(pin: int = 2, on_ms: int = 120, off_ms: int = 240) -> bytes:
    """ESC p m t1 t2 — pin 2 (m=0) or pin 5 (m=1), times in 2 ms units."""
    m = 1 if int(pin) == 5 else 0
    t1 = max(1, min(255, int(on_ms) // 2))
    t2 = max(1, min(255, int(off_ms) // 2))
    return ESC + b"p" + bytes([m, t1, t2])


def columns_for_width(paper_width_mm: int | None) -> int:
    """Characters per line at Font A (12 dots/char, 203 dpi ≈ 8 dots/mm)."""
    w = int(paper_width_mm or 80)
    if w <= 58:
        return 32
    if w <= 76:
        return 42
    return 48


_RTL_RE = re.compile(r"[\u0600-\u06FF\u0750-\u077F\uFB50-\uFDFF\uFE70-\uFEFF]")


def has_rtl(text: str) -> bool:
    return bool(_RTL_RE.search(text))


def visual_rtl(line: str) -> str:
    """Reverse a logical RTL line into visual order for a printer that has no
    bidi engine, keeping runs of digits/latin in their natural LTR order."""
    if not has_rtl(line):
        return line
    tokens = re.findall(r"[0-9A-Za-z.,:/%\-]+|\s+|.", line)
    return "".join(reversed(tokens))


def encode_line(line: str) -> bytes:
    return visual_rtl(line).encode("cp1256", errors="replace")


@dataclass
class ReceiptJob:
    lines: list[str]
    columns: int = 48
    cut: bool = True
    kick_drawer: bool = False
    drawer_pin: int = 2
    title: str | None = None  # printed double-size, centred
    logo_path: str | None = None  # PNG/JPEG rasterised at the top (§214)


def raster_image(path: str, max_width_px: int = 384) -> bytes:
    """Encode a logo as a GS v 0 raster bit image (§214 logo on receipt).

    Uses Pillow when available; returns b"" for SVG/unsupported/missing files
    so the caller can silently skip the logo (never fail a print over a logo).
    """
    try:
        from PIL import Image  # optional at runtime, present in requirements
    except Exception:
        return b""
    try:
        im = Image.open(path)
        im.load()
    except Exception:
        return b""
    if im.mode in ("RGBA", "LA", "P"):
        bg = Image.new("RGBA", im.size, (255, 255, 255, 255))
        bg.alpha_composite(im.convert("RGBA"))
        im = bg
    im = im.convert("L")
    if im.width > max_width_px:
        im = im.resize((max_width_px, max(1, round(im.height * max_width_px / im.width))))
    im = im.point(lambda v: 0 if v < 160 else 255, mode="1")
    width_bytes = (im.width + 7) // 8
    rows = bytearray()
    px = im.load()
    for y in range(im.height):
        for bx in range(width_bytes):
            byte = 0
            for bit in range(8):
                x = bx * 8 + bit
                if x < im.width and px[x, y] == 0:
                    byte |= 0x80 >> bit
            rows.append(byte)
    xl, xh = width_bytes & 0xFF, width_bytes >> 8
    yl, yh = im.height & 0xFF, im.height >> 8
    return ALIGN_CENTER + GS + b"v0" + bytes([0, xl, xh, yl, yh]) + bytes(rows) + b"\n" + ALIGN_LEFT


def build_escpos(job: ReceiptJob) -> bytes:
    out = bytearray(INIT + CODEPAGE_CP1256)
    if job.logo_path:
        out += raster_image(job.logo_path, max_width_px=8 * job.columns)
    if job.title:
        out += ALIGN_CENTER + DOUBLE_ON + BOLD_ON + encode_line(job.title) + b"\n" + BOLD_OFF + DOUBLE_OFF
    for raw in job.lines:
        line = raw.rstrip("\n")
        if has_rtl(line):
            out += ALIGN_RIGHT
        else:
            out += ALIGN_LEFT
        out += encode_line(line[: job.columns]) + b"\n"
    out += ALIGN_LEFT + ESC + b"d\x02"
    if job.cut:
        out += cut_command()
    if job.kick_drawer:
        out += drawer_kick_command(job.drawer_pin)
    return bytes(out)


# --- transports ----------------------------------------------------------------

def _parse_tcp(conn: str) -> tuple[str, int]:
    rest = conn[len("tcp://"):]
    host, _, port = rest.partition(":")
    return host.strip(), int(port or 9100)


def send_raw_tcp(conn: str, payload: bytes, timeout: float = 5.0) -> tuple[bool, str]:
    host, port = _parse_tcp(conn)
    try:
        with socket.create_connection((host, port), timeout=timeout) as s:
            s.sendall(payload)
        return True, f"sent {len(payload)} bytes to {host}:{port}"
    except (OSError, ValueError) as exc:
        return False, f"PRINTER_ERROR: {type(exc).__name__}: {exc}"


def _parse_escpos(conn: str):
    parts = conn.split(":", 2)
    if len(parts) < 2:
        raise ValueError("bad escpos connection string")
    return parts[1], parts[2] if len(parts) > 2 else ""


def _open_python_escpos(conn: str):
    kind, rest = _parse_escpos(conn)
    if kind == "usb":
        vid, pid = rest.split(":")
        from escpos.printer import Usb  # type: ignore
        return Usb(int(vid, 16), int(pid, 16))
    if kind == "net":
        host, port = rest.rsplit(":", 1)
        from escpos.printer import Network  # type: ignore
        return Network(host, int(port))
    if kind == "win":
        from escpos.printer import Win32Raw  # type: ignore
        return Win32Raw(rest)
    raise ValueError(f"unknown escpos target: {kind}")


def send_payload(conn: str, payload: bytes) -> tuple[bool, str]:
    """Deliver raw ESC/POS bytes over whichever transport ``conn`` names."""
    conn = (conn or "").strip()
    if conn.startswith("tcp://"):
        return send_raw_tcp(conn, payload)
    if conn.startswith("escpos:"):
        try:
            p = _open_python_escpos(conn)
        except ImportError:
            return False, "DRIVER_UNAVAILABLE: python-escpos not installed (requirements-hardware.txt)"
        except Exception as exc:
            return False, f"PRINTER_ERROR: {type(exc).__name__}: {exc}"
        try:
            p._raw(payload)
            return True, f"sent {len(payload)} bytes via python-escpos"
        except Exception as exc:
            return False, f"PRINTER_ERROR: {type(exc).__name__}: {exc}"
        finally:
            try:
                p.close()
            except Exception:
                pass
    return False, "NOT_SUPPORTED: unknown connection scheme (use tcp://, escpos:, or file://)"


def print_via_escpos(conn: str, text: str, *, columns: int = 48, cut: bool = True,
                     kick_drawer: bool = False, drawer_pin: int = 2,
                     logo_path: str | None = None) -> tuple[bool, str]:
    payload = build_escpos(ReceiptJob(lines=text.split("\n"), columns=columns, cut=cut,
                                      kick_drawer=kick_drawer, drawer_pin=drawer_pin,
                                      logo_path=logo_path))
    return send_payload(conn, payload)


def kick_drawer(conn: str, pin: int = 2) -> tuple[bool, str]:
    """Send ONLY the drawer pulse (no paper feed)."""
    return send_payload(conn, INIT + drawer_kick_command(pin))


def probe_escpos(conn: str) -> tuple[bool, str]:
    """Reachability probe: TCP connect for network targets; device open for
    python-escpos targets. Nothing is printed."""
    conn = (conn or "").strip()
    if conn.startswith("tcp://"):
        host, port = _parse_tcp(conn)
        try:
            with socket.create_connection((host, port), timeout=3):
                return True, f"printer reachable at {host}:{port}"
        except (OSError, ValueError) as exc:
            return False, f"printer unreachable: {exc}"
    if conn.startswith("escpos:"):
        try:
            p = _open_python_escpos(conn)
        except ImportError:
            return False, "DRIVER_UNAVAILABLE: python-escpos not installed"
        except Exception as exc:
            return False, f"device open failed: {type(exc).__name__}: {exc}"
        try:
            p.close()
        except Exception:
            pass
        return True, f"device opened: {conn}"
    return False, "NOT_SUPPORTED: unknown connection scheme"
