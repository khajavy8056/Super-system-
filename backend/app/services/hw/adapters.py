# -*- coding: utf-8 -*-
"""The six first-party adapters: printer, drawer, scanner, display, label, scale.

Each adapter is deliberately small: it knows ONE protocol family and reports
honest health. A device family that is not registered here is NOT silently
skipped — adapter_for() raises UnsupportedDeviceError and the manager maps it
to an UNSUPPORTED_DEVICE answer with guidance.
"""
from __future__ import annotations

import re

from sqlalchemy.orm import Session

from .base import (AdapterBase, Capability, DeviceHealth, DriverMissingError,
                   UnsupportedDeviceError)
from .detection import probe_tcp
from .transports import MockTransport, Transport, transport_for

ADAPTERS: list["AdapterBase"] = []


def _register(cls):
    ADAPTERS.append(cls())
    return cls


def adapter_for(device_type: str) -> AdapterBase:
    # The legacy registry stores PRINTER/BARCODE_SCANNER/CASH_DRAWER; the layer
    # works case-insensitively so old and new rows resolve identically.
    key = (device_type or "").strip().lower()
    for a in ADAPTERS:
        if key in a.device_types:
            return a
    known = sorted({t for a in ADAPTERS for t in a.device_types})
    raise UnsupportedDeviceError(
        f"device_type {device_type!r} is not supported by any adapter "
        f"(known: {', '.join(known)}). To add it, write one AdapterBase "
        f"subclass and register it in services/hw/adapters.py.")


def _transport(db: Session, device, test_transport: Transport | None = None) -> Transport:
    """Resolve the device's transport. Tests may inject one (mock/file)."""
    if test_transport is not None:
        return test_transport
    return transport_for(getattr(device, "connection", None))


def _driver_versions(required: dict[str, tuple[str, str]]) -> tuple[str, dict]:
    """Check adapter driver imports. Returns (name, report)."""
    import importlib
    for import_name, (pip_name, _ver) in required.items():
        try:
            importlib.import_module(import_name)
        except ImportError:
            return import_name, {"ok": False, "pip": pip_name}
    name = next(iter(required), "")
    return name, {"ok": True}


# ---------------------------------------------------------------- printer ---
@_register
class ReceiptPrinterAdapter(AdapterBase):
    device_types = ("printer", "receipt_printer", "thermal_printer")
    guidance = ("Connect an ESC/POS thermal printer over TCP (tcp://host:9100), "
                "USB-serial (serial:///dev/ttyUSB0) or USB (pyusb).")
    required_packages = {}

    @property
    def capabilities(self):
        return [Capability.PRINT_RECEIPT]

    def probe(self, db: Session, device) -> DeviceHealth:
        conn = (getattr(device, "connection", None) or "")
        if conn.startswith("tcp://"):
            hostport = conn[6:]
            host, _, port = hostport.rpartition(":")
            rep = probe_tcp(host, int(port or 9100))
            if rep["reachable"]:
                return DeviceHealth(status="CONNECTED", detail=rep["detail"],
                                    capabilities=[c.value for c in self.capabilities])
            return DeviceHealth(status="DISCONNECTED", detail=rep["detail"])
        if conn.startswith("mock://") or conn.startswith("file://"):
            return DeviceHealth(status="CONNECTED", detail=f"{conn} sink is writable (no physical check)",
                                capabilities=[c.value for c in self.capabilities])
        if conn.startswith("serial://"):
            return DeviceHealth(status="UNKNOWN",
                                detail="serial printers cannot be probed without sending bytes; run self-test",
                                capabilities=[c.value for c in self.capabilities])
        return DeviceHealth(status="DISCONNECTED", detail=f"no usable connection: {conn!r}. {self.guidance}")

    def self_test(self, db: Session, device, **kwargs) -> dict:
        """Probe + optional test page (print_test_page=True spends paper)."""
        health = self.probe(db, device)
        report = {"health": health.as_dict(), "test_page": "skipped"}
        if not kwargs.get("print_test_page"):
            return report
        if health.status == "DISCONNECTED":
            return {**report, "test_page": "refused: device unreachable"}
        try:
            transport = _transport(db, device, kwargs.get("test_transport"))
        except ValueError as exc:
            return {**report, "test_page": f"refused: {exc}"}
        from .. import hardware as legacy
        payload = legacy.build_receipt_payload(
            kwargs.get("shop_name", "TEST"), ["*** SELF TEST ***"],
            kwargs.get("total") or "0", footer="hardware layer v3.8")
        ok, msg = transport.write(payload)
        return {**report, "test_page": ("sent" if ok else f"failed: {msg}"),
                "bytes": len(payload), "transport": transport.label}


# -------------------------------------------------------------- cash drawer --
@_register
class CashDrawerAdapter(AdapterBase):
    device_types = ("cash_drawer", "drawer")
    guidance = ("Cash drawers fire through the receipt printer (ESC/POS pulse) "
                "— point the drawer at the same tcp://host:9100 as the printer, "
                "or use a serial relay.")
    required_packages = {}

    @property
    def capabilities(self):
        return [Capability.OPEN_DRAWER]

    def probe(self, db: Session, device) -> DeviceHealth:
        conn = (getattr(device, "connection", None) or "")
        if conn.startswith("tcp://"):
            hostport = conn[6:]
            host, _, port = hostport.rpartition(":")
            rep = probe_tcp(host, int(port or 9100))
            return DeviceHealth(
                status="CONNECTED" if rep["reachable"] else "DISCONNECTED", detail=rep["detail"],
                capabilities=[c.value for c in self.capabilities])
        if conn.startswith("mock://") or conn.startswith("file://"):
            return DeviceHealth(status="CONNECTED", detail="sink is writable (no physical check)",
                                capabilities=[c.value for c in self.capabilities])
        return DeviceHealth(status="DISCONNECTED", detail=f"no usable connection: {conn!r}. {self.guidance}")

    def pulse(self, db: Session, device, test_transport: Transport | None = None) -> tuple[bool, str]:
        try:
            transport = _transport(db, device, test_transport)
        except ValueError as exc:
            return False, str(exc)
        # ESC p m t1 t2 — open drawer pin 2, 200ms pulse
        return transport.write(b"\x1bp\x00\x19\xfa")

    def self_test(self, db: Session, device, **kwargs) -> dict:
        health = self.probe(db, device)
        # A pulse OPENS the drawer — only on explicit confirmation.
        if not kwargs.get("confirm_open"):
            return {"health": health.as_dict(), "pulse": "skipped (pass confirm_open=true to fire)"}
        if health.status == "DISCONNECTED":
            return {"health": health.as_dict(), "pulse": "refused: device unreachable"}
        ok, msg = self.pulse(db, device, kwargs.get("test_transport"))
        return {"health": health.as_dict(), "pulse": "fired" if ok else f"failed: {msg}"}


# ------------------------------------------------------------------ scanner --
@_register
class ScannerAdapter(AdapterBase):
    device_types = ("scanner", "barcode_scanner")
    guidance = ("USB-HID scanners behave as keyboards — no driver needed, "
                "verification is a manual scan. Serial scanners use "
                "serial:///dev/ttyUSB0@9600.")

    @property
    def capabilities(self):
        return [Capability.SCAN]

    def probe(self, db: Session, device) -> DeviceHealth:
        conn = (getattr(device, "connection", None) or "")
        if conn.startswith("serial://"):
            try:
                import serial  # noqa: F401  (presence check)
            except ImportError:
                return DeviceHealth(status="DRIVER_MISSING",
                                    detail="pyserial is not installed (pip install pyserial==3.5)")
            return DeviceHealth(status="UNKNOWN", detail="serial scanner present (driver ok); "
                                "scan a barcode to verify — see manual acceptance steps")
        if conn.startswith("mock://"):
            return DeviceHealth(status="CONNECTED", detail="mock scanner queue ready",
                                capabilities=[c.value for c in self.capabilities])
        # USB-HID keyboard wedge: reachable by definition, verified by a real scan.
        return DeviceHealth(status="UNKNOWN",
                            detail="USB-HID scanners verify by a real scan only "
                                   "(MANUAL_ACCEPTANCE_REQUIRED for first setup)",
                            capabilities=[c.value for c in self.capabilities])

    def read_one(self, db: Session, device, test_transport: Transport | None = None,
                 timeout: float = 5.0) -> dict:
        transport = _transport(db, device, test_transport)
        ok, line, msg = transport.read_line(timeout=timeout)
        if not ok:
            return {"ok": False, "error": msg}
        return {"ok": True, "code": line.decode("ascii", "replace").strip(), "transport": transport.label}

    def self_test(self, db: Session, device, **kwargs) -> dict:
        health = self.probe(db, device)
        if health.status == "DRIVER_MISSING":
            return {"health": health.as_dict(), "scan": "refused: driver missing"}
        if not kwargs.get("wait_for_scan"):
            return {"health": health.as_dict(), "scan": "skipped (pass wait_for_scan=true and scan a barcode)"}
        return {"health": health.as_dict(),
                "scan": self.read_one(db, device, kwargs.get("test_transport"),
                                      timeout=float(kwargs.get("timeout", 5.0)))}


# ------------------------------------------------------------------ display --
@_register
class CustomerDisplayAdapter(AdapterBase):
    device_types = ("display", "customer_display", "pole_display")
    guidance = "ESC/POS line displays over TCP (tcp://host:9100) or serial."

    @property
    def capabilities(self):
        return [Capability.SHOW_TEXT]

    def build_lines(self, line1: str, line2: str = "", width: int = 20) -> bytes:
        def fit(s: str) -> bytes:
            return s[:width].ljust(width).encode("ascii", "replace")
        # FF = clear, then two lines
        return b"\x0c" + fit(line1) + b"\r\n" + (fit(line2) if line2 else b"")

    def probe(self, db: Session, device) -> DeviceHealth:
        conn = (getattr(device, "connection", None) or "")
        if conn.startswith("tcp://"):
            hostport = conn[6:]
            host, _, port = hostport.rpartition(":")
            rep = probe_tcp(host, int(port or 9100))
            return DeviceHealth(status="CONNECTED" if rep["reachable"] else "DISCONNECTED",
                                detail=rep["detail"], capabilities=[c.value for c in self.capabilities])
        if conn.startswith("mock://") or conn.startswith("file://"):
            return DeviceHealth(status="CONNECTED", detail="sink is writable (no physical check)",
                                capabilities=[c.value for c in self.capabilities])
        return DeviceHealth(status="UNKNOWN", detail=f"cannot probe {conn!r} without sending bytes; run self-test")

    def self_test(self, db: Session, device, **kwargs) -> dict:
        health = self.probe(db, device)
        if health.status == "DISCONNECTED":
            return {"health": health.as_dict(), "show": "refused: device unreachable"}
        try:
            transport = _transport(db, device, kwargs.get("test_transport"))
        except ValueError as exc:
            return {"health": health.as_dict(), "show": f"refused: {exc}"}
        payload = self.build_lines(kwargs.get("line1", "*** TEST ***"), kwargs.get("line2", "v3.8"))
        ok, msg = transport.write(payload)
        return {"health": health.as_dict(), "show": "sent" if ok else f"failed: {msg}",
                "transport": transport.label}


# -------------------------------------------------------------------- label --
@_register
class LabelPrinterAdapter(AdapterBase):
    device_types = ("label_printer", "label")
    guidance = "TSPL2 label printers (Godex/Argox/TSC) over TCP tcp://host:9100 or serial."

    @property
    def capabilities(self):
        return [Capability.PRINT_LABEL]

    def build_label(self, text: str, barcode: str = "", width_mm: int = 50,
                    height_mm: int = 30, copies: int = 1) -> bytes:
        dots_per_mm = 8  # 203 dpi
        cmds = [f"SIZE {width_mm} mm,{height_mm} mm", "GAP 2 mm,0", "CLS",
                f'TEXT 20,20,"2",0,1,1,"{text[:40]}"']
        if barcode:
            cmds.append(f'BARCODE 20,60,"128",60,1,0,2,2,"{barcode[:30]}"')
        cmds.append(f"PRINT {max(1, copies)}")
        return ("\r\n".join(cmds) + "\r\n").encode("ascii", "replace")

    def probe(self, db: Session, device) -> DeviceHealth:
        conn = (getattr(device, "connection", None) or "")
        if conn.startswith("tcp://"):
            hostport = conn[6:]
            host, _, port = hostport.rpartition(":")
            rep = probe_tcp(host, int(port or 9100))
            return DeviceHealth(status="CONNECTED" if rep["reachable"] else "DISCONNECTED",
                                detail=rep["detail"], capabilities=[c.value for c in self.capabilities])
        if conn.startswith("mock://") or conn.startswith("file://"):
            return DeviceHealth(status="CONNECTED", detail="sink is writable (no physical check)",
                                capabilities=[c.value for c in self.capabilities])
        return DeviceHealth(status="UNKNOWN", detail=f"cannot probe {conn!r} without sending bytes; run self-test")

    def self_test(self, db: Session, device, **kwargs) -> dict:
        health = self.probe(db, device)
        if not kwargs.get("print_test_label"):
            return {"health": health.as_dict(), "label": "skipped (pass print_test_label=true; spends one label)"}
        if health.status == "DISCONNECTED":
            return {"health": health.as_dict(), "label": "refused: device unreachable"}
        try:
            transport = _transport(db, device, kwargs.get("test_transport"))
        except ValueError as exc:
            return {"health": health.as_dict(), "label": f"refused: {exc}"}
        payload = self.build_label(kwargs.get("text", "TEST"), kwargs.get("barcode", "123456"))
        ok, msg = transport.write(payload)
        return {"health": health.as_dict(), "label": "sent" if ok else f"failed: {msg}",
                "transport": transport.label}


# --------------------------------------------------------------------- scale --
_WEIGHT_RE = re.compile(r"([-+]?\d+(?:\.\d+)?)\s*(kg|g|lb|oz)\b", re.IGNORECASE)


def parse_scale_line(line: bytes) -> dict:
    """Parse one ASCII scale telegram. Best-effort for documented line
    protocols (CAS/DIGI-style ``ST,GS,  12.340kg``); unknown lines come back
    UNPARSEABLE with the raw text — a missing weight is never returned as 0."""
    try:
        text = line.decode("ascii", "replace").strip()
    except Exception:  # noqa: BLE001 — never crash on wire bytes
        return {"ok": False, "error": "UNPARSEABLE", "raw": repr(line)}
    m = _WEIGHT_RE.search(text)
    if not m:
        return {"ok": False, "error": "UNPARSEABLE", "raw": text}
    value, unit = float(m.group(1)), m.group(2).lower()
    grams = {"g": 1.0, "kg": 1000.0, "lb": 453.59237, "oz": 28.349523125}[unit]
    upper = text.upper()
    stable = upper.startswith("ST") or "ST," in upper
    return {"ok": True, "weight_g": round(value * grams, 3),
            "stable": stable, "unit": unit, "raw": text}


@_register
class ScaleAdapter(AdapterBase):
    device_types = ("scale", "weighing_scale")
    guidance = ("Serial/USB-serial scales streaming ASCII telegrams "
                "(serial:///dev/ttyUSB0@9600). Verify with a known test mass — "
                "see manual acceptance steps.")

    @property
    def capabilities(self):
        return [Capability.WEIGH]

    def probe(self, db: Session, device) -> DeviceHealth:
        try:
            import serial  # noqa: F401  (presence check)
        except ImportError:
            if (getattr(device, "connection", "") or "").startswith("mock://"):
                return DeviceHealth(status="CONNECTED", detail="mock scale queue ready",
                                    capabilities=[c.value for c in self.capabilities])
            return DeviceHealth(status="DRIVER_MISSING",
                                detail="pyserial is not installed (pip install pyserial==3.5)")
        return DeviceHealth(status="UNKNOWN",
                            detail="serial scale driver ok; weight verified by a real read only",
                            capabilities=[c.value for c in self.capabilities])

    def read_weight(self, db: Session, device, test_transport: Transport | None = None,
                    timeout: float = 5.0) -> dict:
        transport = _transport(db, device, test_transport)
        ok, line, msg = transport.read_line(timeout=timeout)
        if not ok:
            return {"ok": False, "error": msg}
        rep = parse_scale_line(line)
        rep["transport"] = transport.label
        return rep

    def self_test(self, db: Session, device, **kwargs) -> dict:
        health = self.probe(db, device)
        if health.status == "DRIVER_MISSING":
            return {"health": health.as_dict(), "weigh": "refused: driver missing"}
        if not kwargs.get("wait_for_weight"):
            return {"health": health.as_dict(), "weigh": "skipped (pass wait_for_weight=true and put a mass on the scale)"}
        return {"health": health.as_dict(),
                "weigh": self.read_weight(db, device, kwargs.get("test_transport"),
                                          timeout=float(kwargs.get("timeout", 5.0)))}
