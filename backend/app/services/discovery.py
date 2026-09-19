"""v2.1 — LAN discovery beacon (گوشی ↔ رایانه بدون وابستگی به IP).

DHCP may give the shop PC a different address tomorrow. Instead of storing an
IP forever, the phone remembers the installation's *link key* (12 hex chars,
minted once, delivered inside the pairing QR / code). When the saved address
stops answering — or as soon as the phone joins any Wi-Fi — it broadcasts
``SMKT-FIND <link_key>`` on UDP port 48765; only the PC holding that key
replies ``SMKT-HERE <port> <store>`` and the phone re-points itself to the
sender's current address. No mDNS, no router configuration, no internet.
"""
from __future__ import annotations

import logging
import socket
import threading

log = logging.getLogger("supermarket.discovery")

PORT = 48765
_thread: threading.Thread | None = None
_stop = threading.Event()


def _serve(session_factory, http_port: int) -> None:
    import os
    http_port = int(os.environ.get("PORT", http_port) or http_port)  # v2.3: the launcher exports the real listening port
    from sqlalchemy import select

    from ..models import SystemSetting
    from ..routers.mobile import link_key

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)  # type: ignore[attr-defined]
    except (AttributeError, OSError):
        pass
    sock.settimeout(1.0)
    try:
        sock.bind(("", PORT))
    except OSError as exc:
        log.warning("discovery beacon disabled: %s", exc)
        return
    log.info("LAN discovery beacon listening on udp/%s", PORT)
    while not _stop.is_set():
        try:
            data, addr = sock.recvfrom(256)
        except socket.timeout:
            continue
        except OSError:
            break
        try:
            text = data.decode("utf-8", "ignore").strip()
            if not text.startswith("SMKT-FIND"):
                continue
            asked = text.split(" ", 1)[1].strip().upper() if " " in text else ""
            with session_factory() as db:
                key = link_key(db)
                store = db.execute(select(SystemSetting).where(SystemSetting.key == "store.name")).scalar_one_or_none()
                name = (store.value if store else "") or ""
            if asked and asked != key:
                continue  # someone else's shop
            sock.sendto(f"SMKT-HERE {http_port} {key} {name}".encode("utf-8"), addr)
        except Exception as exc:  # noqa: BLE001
            log.debug("discovery reply failed: %s", exc)
    sock.close()


def start(session_factory, http_port: int) -> None:
    global _thread
    if _thread and _thread.is_alive():
        return
    _stop.clear()
    _thread = threading.Thread(target=_serve, args=(session_factory, http_port), name="lan-discovery", daemon=True)
    _thread.start()


def stop() -> None:
    _stop.set()
