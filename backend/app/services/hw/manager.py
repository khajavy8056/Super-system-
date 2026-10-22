# -*- coding: utf-8 -*-
"""Manager: detection→registry, health tracking, reconnect backoff, self-tests.

Health model per device: every probe writes status/last_seen/last_error plus a
consecutive-failure counter. Reconnects are automatic but polite: a failing
device is re-probed at most on an exponential backoff
(5s, 10s, 20s, … capped at 5 min) so a dead printer cannot DOS the server.
A single good probe resets the counter — that IS the auto-recovery.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .adapters import ADAPTERS, adapter_for
from .base import DeviceHealth, UnsupportedDeviceError
from .detection import detect_usb_devices

RECONNECT_BASE_S = 5
RECONNECT_CAP_S = 300


def _model():
    from ...models import HardwareDevice
    return HardwareDevice


def detect_and_register(db: Session, auto_create: bool = False) -> dict:
    """Run USB discovery and reconcile with the registry.

    Returns the raw discovery report plus, per USB device, either the matched
    registry row or (auto_create=True) the newly created DISABLED row awaiting
    operator configuration. Unknown USB kinds are reported with guidance and
    the UNSUPPORTED_DEVICE flag — never silently dropped.
    """
    HardwareDevice = _model()
    rep = detect_usb_devices()
    if not rep.get("available"):
        return {**rep, "matched": []}
    matched: list[dict] = []
    for usb in rep["devices"]:
        serial = usb.get("serial_number")
        q = select(HardwareDevice)
        if serial:
            q = q.where(HardwareDevice.serial_number == serial)
        else:
            q = q.where(HardwareDevice.vendor_id == usb["vid"],
                        HardwareDevice.product_id == usb["pid"])
        row = db.execute(q).scalars().first()
        kinds = {t for a in ADAPTERS for t in a.device_types}
        entry = {"usb": usb, "registry_id": row.id if row else None,
                 "supported": usb["kind"] in kinds or usb["kind"] == "unknown"}
        if usb["kind"] == "unknown" and not row:
            entry["supported"] = False
            entry["verdict"] = "UNSUPPORTED_DEVICE"
            entry["guidance"] = ("No adapter claims this USB device. Check the manual's "
                                 "hardware compatibility list or add an adapter (see "
                                 "services/hw/adapters.py).")
        if not row and auto_create and entry["supported"]:
            row = HardwareDevice(name=usb["label"], device_type=usb["kind"],
                                 vendor_id=usb["vid"], product_id=usb["pid"],
                                 serial_number=serial, status="DISABLED")
            db.add(row)
            db.flush()
            entry["registry_id"] = row.id
            entry["created"] = True
        matched.append(entry)
    db.commit()
    return {**rep, "matched": matched}


def device_status(db: Session, device) -> dict:
    """Full status row for one device: registry fields + adapter + health."""
    try:
        adapter = adapter_for(device.device_type)
        adapter_name = type(adapter).__name__
        caps = [c.value for c in adapter.capabilities]
        verdict = None
    except UnsupportedDeviceError as exc:
        adapter_name, caps, verdict = None, [], str(exc)
    try:
        stored_caps = json.loads(device.capabilities) if device.capabilities else []
    except (ValueError, TypeError):
        stored_caps = []
    return {"id": device.id, "name": device.name, "device_type": device.device_type,
            "status": getattr(device, "status", "UNKNOWN"),
            "connection": getattr(device, "connection", None),
            "is_enabled": getattr(device, "is_enabled", True),
            "stored_capabilities": stored_caps,
            "health": getattr(device, "health", None),
            "last_seen_at": (lambda v: v.isoformat() if v else None)(getattr(device, "last_seen_at", None)),
            "last_error": getattr(device, "last_error", None),
            "consecutive_failures": getattr(device, "consecutive_failures", 0),
            "adapter": adapter_name, "capabilities": caps,
            "verdict": verdict or getattr(device, "health", None)}


def ensure_connected(db: Session, device, force: bool = False) -> DeviceHealth:
    """Probe the device (backoff-gated unless force) and persist the result.

    Returns the fresh (or throttled) DeviceHealth. Throttled answers carry
    status == previous status and detail noting the backoff wait.
    """
    try:
        adapter = adapter_for(device.device_type)
    except UnsupportedDeviceError as exc:
        health = DeviceHealth(status="UNSUPPORTED_DEVICE", detail=str(exc))
        _persist(db, device, health)
        return health
    failures = getattr(device, "consecutive_failures", 0) or 0
    if failures and not force:
        wait = min(RECONNECT_CAP_S, RECONNECT_BASE_S * 2 ** (failures - 1))
        last_err_at = getattr(device, "updated_at", None)
        if last_err_at and datetime.utcnow() - last_err_at < timedelta(seconds=wait):
            return DeviceHealth(status=getattr(device, "health", None) or "UNKNOWN",
                                detail=f"reconnect backing off ({failures} failures, retry in ~{wait}s)",
                                capabilities=[c.value for c in adapter.capabilities])
    try:
        health = adapter.probe(db, device)
    except Exception as exc:  # noqa: BLE001 — a probe must never crash the manager
        health = DeviceHealth(status="UNKNOWN", detail=f"probe crashed (adapter bug): {exc}")
    _persist(db, device, health)
    return health


def _persist(db: Session, device, health: DeviceHealth) -> None:
    device.health = health.status
    device.last_error = None if health.status == "CONNECTED" else (health.detail or None)
    if health.status == "CONNECTED":
        device.last_seen_at = datetime.utcnow()
        device.consecutive_failures = 0
    elif health.status in ("DISCONNECTED", "UNKNOWN", "DRIVER_MISSING"):
        device.consecutive_failures = (getattr(device, "consecutive_failures", 0) or 0) + 1
    # UNSUPPORTED_DEVICE is a verdict, not a failure: no counter change.
    device.capabilities = json.dumps(health.capabilities)
    db.add(device)
    db.commit()


def test_device(db: Session, device_id: int, test_transport=None, **kwargs) -> dict:
    """Run the adapter self-test for one registry row (explicit user action)."""
    HardwareDevice = _model()
    device = db.get(HardwareDevice, device_id)
    if device is None:
        return {"ok": False, "error": f"no HardwareDevice id={device_id}"}
    try:
        adapter = adapter_for(device.device_type)
    except UnsupportedDeviceError as exc:
        return {"ok": False, "error": "UNSUPPORTED_DEVICE", "detail": str(exc)}
    try:
        report = adapter.self_test(db, device, test_transport=test_transport, **kwargs)
    except Exception as exc:  # noqa: BLE001 — self-tests report, never crash
        return {"ok": False, "error": f"self-test crashed (adapter bug): {exc}"}
    health = report.get("health")
    if isinstance(health, DeviceHealth):
        _persist(db, device, health)
        report["health"] = health.as_dict()
    from ..audit import write_audit
    write_audit(db, action="HW_SELF_TEST", entity_type="HardwareDevice", entity_id=device.id,
                after={"report": str(report)[:2000]})
    db.commit()
    return {"ok": True, "device_id": device.id, "report": report}
