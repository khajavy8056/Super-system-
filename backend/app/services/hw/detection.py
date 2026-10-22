# -*- coding: utf-8 -*-
"""Device discovery: USB enumeration (pyusb when installed) + TCP probes.

Without pyusb there is no silent empty list — the detector says DRIVER_MISSING
and names the install command. Unknown VID/PID pairs are reported with kind
"unknown" so the caller can answer UNSUPPORTED_DEVICE with guidance.
"""
from __future__ import annotations


# Well-known POS VID/PID pairs; unknown devices still surface as kind="unknown".
KNOWN_USB: dict[tuple[int, int], tuple[str, str]] = {
    # (vid, pid): (kind, label)
    (0x04B8, 0x0202): ("printer", "Epson TM series (USB)"),
    (0x0519, 0x0001): ("printer", "Star TSP100 (USB)"),
    (0x05E0, 0x1200): ("scanner", "Symbol barcode scanner (USB-HID)"),
}


def detect_usb_devices() -> dict:
    """Enumerate USB devices. Returns {"available": bool, "devices": [...]}
    or {"available": False, "reason": "DRIVER_MISSING:...", ...}."""
    try:
        import usb.core  # type: ignore
    except ImportError:
        return {"available": False, "reason": "DRIVER_MISSING:pyusb",
                "hint": "install the USB driver first: pip install pyusb==1.2.1 "
                        "(or enable hw.auto_install_drivers), then retry"}
    try:
        found = list(usb.core.find(find_all=True) or [])
    except Exception as exc:  # noqa: BLE001 — libusb/backend errors surface as text
        return {"available": False, "reason": f"USB_BACKEND_ERROR: {exc}",
                "hint": "check libusb on this machine and the device cable"}
    devices: list[dict] = []
    for d in found:
        try:
            vid, pid = int(d.idVendor), int(d.idProduct)
        except Exception:  # noqa: BLE001 — defensive: odd descriptors
            continue
        kind, label = KNOWN_USB.get((vid, pid), ("unknown", "unknown USB device"))
        entry: dict = {"vid": f"{vid:04x}", "pid": f"{pid:04x}", "kind": kind, "label": label}
        for attr in ("manufacturer", "product", "serial_number"):
            try:
                entry[attr] = getattr(d, attr, None)
            except Exception:  # noqa: BLE001 — string descriptors may fail
                entry[attr] = None
        devices.append(entry)
    return {"available": True, "devices": devices, "count": len(devices)}


def probe_tcp(host: str, port: int, timeout: float = 2.0) -> dict:
    """Cheap TCP reachability check: {"reachable": bool, "detail": str}."""
    import socket
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return {"reachable": True, "detail": f"{host}:{port} accepts TCP connections"}
    except OSError as exc:
        return {"reachable": False, "detail": f"{host}:{port}: {exc}"}
