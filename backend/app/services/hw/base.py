# -*- coding: utf-8 -*-
"""Contracts of the Hardware Integration Layer: capabilities, health, adapters."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from sqlalchemy.orm import Session


class Capability(str, Enum):
    PRINT_RECEIPT = "PRINT_RECEIPT"
    OPEN_DRAWER = "OPEN_DRAWER"
    SCAN = "SCAN"
    SHOW_TEXT = "SHOW_TEXT"
    PRINT_LABEL = "PRINT_LABEL"
    WEIGH = "WEIGH"


class UnsupportedDeviceError(ValueError):
    """Raised when no adapter handles a device — the caller reports
    UNSUPPORTED_DEVICE with guidance instead of crashing."""


class DriverMissingError(ValueError):
    """Raised when the adapter's driver package is not installed."""


@dataclass
class DeviceHealth:
    #: CONNECTED | DEGRADED | DISCONNECTED | UNKNOWN | UNSUPPORTED_DEVICE | DRIVER_MISSING
    status: str
    detail: str = ""
    capabilities: list[str] = field(default_factory=list)
    driver: str = ""
    driver_version: str | None = None
    checked_at: str = ""

    def __post_init__(self) -> None:
        if not self.checked_at:
            self.checked_at = datetime.utcnow().isoformat(timespec="seconds")

    def as_dict(self) -> dict:
        return {"status": self.status, "detail": self.detail,
                "capabilities": self.capabilities, "driver": self.driver,
                "driver_version": self.driver_version, "checked_at": self.checked_at}


class AdapterBase(ABC):
    """One adapter per device family. makan: pure logic, no global state."""

    #: device_type values (HardwareDevice.device_type) this adapter serves
    device_types: tuple[str, ...] = ()
    #: human guidance shown when detection meets this family but cannot use it
    guidance: str = ""
    #: pip packages the adapter needs: {import_name: (pip_name, pinned_version)}
    required_packages: dict[str, tuple[str, str]] = {}

    @property
    @abstractmethod
    def capabilities(self) -> list[Capability]:
        ...

    @abstractmethod
    def probe(self, db: Session, device) -> DeviceHealth:
        """Cheap liveness check. Must never raise for transport errors —
        return DISCONNECTED/DRIVER_MISSING instead."""

    @abstractmethod
    def self_test(self, db: Session, device, **kwargs) -> dict:
        """Explicit user-triggered test. May send bytes (a test print needs
        paper); returns a JSON-serializable report, never raises."""
