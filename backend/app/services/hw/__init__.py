# -*- coding: utf-8 -*-
"""v3.8 — Hardware Integration Layer.

One standard, extensible layer for every attachable device (printer, barcode
scanner, cash drawer, customer display, label printer, scale, …). Adding a new
device family means writing ONE adapter class and registering it — the core
(detector, health tracking, reconnect backoff, API) never changes.

Honesty rules (same as the rest of the system):
* an unknown device is reported UNSUPPORTED_DEVICE with guidance — never a crash,
* a missing driver is reported DRIVER_MISSING with the exact install command —
  never a fake success,
* no anonymous binary/driver is ever downloaded or executed; the only
  automatic installation is pinned PyPI packages behind an explicit setting,
  verified after install and written to the audit log,
* physical-device behaviour (real USB/Bluetooth/print/scan) is NOT claimed by
  tests: those paths are MANUAL_ACCEPTANCE_REQUIRED (see RELEASE_AUDIT).
"""
from .adapters import ADAPTERS, adapter_for
from .base import (
    AdapterBase,
    Capability,
    DeviceHealth,
    DriverMissingError,
    UnsupportedDeviceError,
)
from .detection import detect_usb_devices, probe_tcp
from .drivers import DriverManager
from .manager import (
    detect_and_register,
    device_status,
    ensure_connected,
    test_device,
)
from .transports import (
    FileTransport,
    MockTransport,
    SerialTransport,
    TcpTransport,
    Transport,
)

__all__ = [
    "ADAPTERS", "adapter_for", "AdapterBase", "Capability", "DeviceHealth",
    "DriverMissingError", "UnsupportedDeviceError", "detect_usb_devices",
    "probe_tcp", "DriverManager", "detect_and_register", "device_status",
    "ensure_connected", "test_device", "FileTransport", "MockTransport",
    "SerialTransport", "TcpTransport", "Transport",
]
