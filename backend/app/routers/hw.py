# -*- coding: utf-8 -*-
"""v3.8 Hardware Integration Layer API ( additive — legacy /hardware stays)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import HardwareDevice, User
from ..security import require_permission
from ..services.hw import (DriverManager, adapter_for, detect_and_register,
                           device_status, ensure_connected, test_device)
from ..services.hw.base import UnsupportedDeviceError

router = APIRouter(prefix="/hardware", tags=["hardware-v2"])


class DetectIn(BaseModel):
    auto_create: bool = False


class SelfTestIn(BaseModel):
    print_test_page: bool = False
    confirm_open: bool = False
    wait_for_scan: bool = False
    wait_for_weight: bool = False
    print_test_label: bool = False
    timeout: float = 5.0


class DriverEnsureIn(BaseModel):
    package: str


@router.post("/detect")
def detect(body: DetectIn, db: Session = Depends(get_db),
           _: User = Depends(require_permission("settings.manage"))):
    """Run USB discovery and reconcile with the registry."""
    return detect_and_register(db, auto_create=body.auto_create)


@router.get("/devices/{device_id}/status")
def status(device_id: int, db: Session = Depends(get_db),
           _: User = Depends(require_permission("settings.manage"))):
    device = db.get(HardwareDevice, device_id)
    if device is None:
        raise HTTPException(status_code=404, detail=f"no HardwareDevice id={device_id}")
    return device_status(db, device)


@router.post("/devices/{device_id}/probe")
def probe(device_id: int, force: bool = False, db: Session = Depends(get_db),
          _: User = Depends(require_permission("settings.manage"))):
    """Probe the device now (backoff-gated unless force) and persist health."""
    device = db.get(HardwareDevice, device_id)
    if device is None:
        raise HTTPException(status_code=404, detail=f"no HardwareDevice id={device_id}")
    return ensure_connected(db, device, force=force).as_dict()


@router.post("/devices/{device_id}/test")
def self_test(device_id: int, body: SelfTestIn, db: Session = Depends(get_db),
              _: User = Depends(require_permission("settings.manage"))):
    """Explicit operator self-test. Paper/pulse/scan/weight actions only run
    with their confirmation flag — otherwise they report 'skipped'."""
    rep = test_device(db, device_id, **body.model_dump())
    if not rep.get("ok"):
        raise HTTPException(status_code=422, detail=rep)
    return rep


@router.get("/adapters")
def adapters(_: User = Depends(require_permission("settings.manage"))):
    """Which device families the layer supports (extensibility proof)."""
    from ..services.hw import ADAPTERS
    return {"adapters": [{"name": type(a).__name__, "device_types": list(a.device_types),
                          "capabilities": [c.value for c in a.capabilities],
                          "guidance": a.guidance} for a in ADAPTERS]}


@router.get("/drivers")
def drivers(db: Session = Depends(get_db),
            _: User = Depends(require_permission("settings.manage"))):
    mgr = DriverManager(db)
    from ..services.hw.drivers import PINNED_ALLOWLIST
    return {"drivers": [mgr.status(pkg) for pkg in PINNED_ALLOWLIST]}


@router.post("/drivers/ensure")
def driver_ensure(body: DriverEnsureIn, db: Session = Depends(get_db),
                  _: User = Depends(require_permission("settings.manage"))):
    """Verify a driver, auto-installing only pinned PyPI packages when the
    hw.auto_install_drivers setting explicitly allows it."""
    try:
        return DriverManager(db).ensure(body.package)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.get("/devices/{device_id}/adapter")
def adapter_of(device_id: int, db: Session = Depends(get_db),
               _: User = Depends(require_permission("settings.manage"))):
    device = db.get(HardwareDevice, device_id)
    if device is None:
        raise HTTPException(status_code=404, detail=f"no HardwareDevice id={device_id}")
    try:
        adapter = adapter_for(device.device_type)
    except UnsupportedDeviceError as exc:
        raise HTTPException(status_code=422, detail={"verdict": "UNSUPPORTED_DEVICE", "detail": str(exc)})
    return {"adapter": type(adapter).__name__, "device_types": list(adapter.device_types),
            "capabilities": [c.value for c in adapter.capabilities]}
