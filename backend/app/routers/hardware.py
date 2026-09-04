from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import HardwareDevice, User
from ..security import get_current_user, require_permission
from ..services import hardware as hw

router = APIRouter(prefix="/hardware", tags=["hardware"])


class DeviceIn(BaseModel):
    device_type: str
    name: str
    vendor: str | None = None
    model: str | None = None
    connection: str | None = None
    status: str = "UNKNOWN"
    paper_width_mm: int | None = None
    is_enabled: bool = True


class ScanDetectIn(BaseModel):
    intervals_ms: list[float]
    threshold_ms: float | None = None


@router.get("")
def list_devices(db: Session = Depends(get_db), _: User = Depends(require_permission("settings.manage"))):
    return [
        {"id": d.id, "device_type": d.device_type, "name": d.name, "status": d.status,
         "connection": d.connection, "is_enabled": d.is_enabled}
        for d in db.execute(select(HardwareDevice)).scalars()
    ]


@router.post("", status_code=201)
def register_device(body: DeviceIn, db: Session = Depends(get_db),
                    user: User = Depends(require_permission("settings.manage"))):
    d = HardwareDevice(**body.model_dump())
    db.add(d)
    db.commit()
    return {"id": d.id, "name": d.name, "device_type": d.device_type, "status": d.status}


@router.get("/health")
def health(db: Session = Depends(get_db), _: User = Depends(require_permission("settings.manage"))):
    devices = list(db.execute(select(HardwareDevice)).scalars())
    return {
        "printer": next((d.status for d in devices if d.device_type == "PRINTER" and d.is_enabled), "DISCONNECTED"),
        "scanner": next((d.status for d in devices if d.device_type == "BARCODE_SCANNER" and d.is_enabled), "DISCONNECTED"),
        "cash_drawer": next((d.status for d in devices if d.device_type == "CASH_DRAWER" and d.is_enabled), "DISCONNECTED"),
    }


@router.post("/test/print")
def test_print(db: Session = Depends(get_db), _: User = Depends(require_permission("settings.manage"))):
    text = "Supermarket System\n--- TEST PRINT ---\n" + "x" * 32 + "\n" + "y" * 24 + "\n"
    device = hw._printer(db)
    if device and device.connection and device.connection.startswith("file://"):
        with open(device.connection[len("file://"):], "w", encoding="utf-8") as f:
            f.write(text)
        return {"ok": True, "message": "test receipt written"}
    return {"ok": device is not None, "message": "PRINTER_OFFLINE" if device is None else "connected"}


@router.post("/test/drawer")
def test_drawer(db: Session = Depends(get_db), _: User = Depends(require_permission("settings.manage"))):
    ok, msg = hw.open_cash_drawer(db)
    return {"ok": ok, "message": msg}


@router.post("/scanner/detect")
def scanner_detect(body: ScanDetectIn, _: User = Depends(require_permission("settings.manage"))):
    return {"is_scanner": hw.detect_scanner(body.intervals_ms, body.threshold_ms)}
