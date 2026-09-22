# -*- coding: utf-8 -*-
"""Driver (python-package) management with a hard trust boundary.

* Status is always reportable: INSTALLED (with version) or MISSING (with the
  exact install command). No guessing, no fake success.
* Automatic installation happens ONLY when ALL of these hold:
  1. setting ``hw.auto_install_drivers`` is exactly "true" (default: false),
  2. the package is on PINNED_ALLOWLIST (name + exact version),
  3. ``pip`` comes from PyPI over TLS (no URLs, no wheels, no binaries),
  4. the import + version are verified AFTER the install.
* Every automatic install (success or failure) is written to the audit log.
* Anything else — vendor EXEs, USB drivers, firmware blobs — is NEVER
  downloaded or executed by this system; the manager returns vendor guidance
  text for the operator instead.
"""
from __future__ import annotations

import importlib
import subprocess
import sys

from sqlalchemy.orm import Session

#: import-name -> (pip-name, pinned version)
PINNED_ALLOWLIST: dict[str, tuple[str, str]] = {
    "usb": ("pyusb", "1.2.1"),
    "serial": ("pyserial", "3.5"),
}

INSTALL_SETTING = "hw.auto_install_drivers"


def _dist_version(pip_name: str) -> str | None:
    try:
        from importlib.metadata import version
        return version(pip_name)
    except Exception:  # noqa: BLE001 — absent dist, or metadata unreadable
        return None


class DriverManager:
    def __init__(self, db: Session):
        self.db = db

    def _auto_install_enabled(self) -> bool:
        from ...models import SystemSetting
        from sqlalchemy import select
        row = self.db.execute(select(SystemSetting).where(SystemSetting.key == INSTALL_SETTING)).scalar_one_or_none()
        return (row.value if row else "false").strip().lower() == "true"

    def status(self, import_name: str) -> dict:
        """INSTALLED/MISSING report for one driver package."""
        pinned = PINNED_ALLOWLIST.get(import_name)
        try:
            importlib.import_module(import_name)
            installed = True
        except ImportError:
            installed = False
        pip_name, ver = pinned or (import_name, "?")
        return {"package": import_name, "pip": pip_name,
                "status": "INSTALLED" if installed else "MISSING",
                "version": _dist_version(pip_name) if installed else None,
                "pinned_version": ver,
                "install_command": f"{sys.executable} -m pip install {pip_name}=={ver}" if pinned else "",
                "auto_install": self._auto_install_enabled()}

    def ensure(self, import_name: str) -> dict:
        """Make sure the driver is usable: verify installed, or auto-install
        when (and only when) the trust boundary above is satisfied."""
        rep = self.status(import_name)
        if rep["status"] == "INSTALLED":
            return rep
        from ...models import SystemSetting  # noqa: F401  (kept explicit for readers)
        from ..audit import write_audit
        if import_name not in PINNED_ALLOWLIST:
            write_audit(self.db, action="DRIVER_INSTALL_REFUSED", entity_type="System", entity_id=0,
                        after={"package": import_name, "reason": "not on the pinned allowlist"})
            self.db.commit()
            raise ValueError(f"refusing to auto-install {import_name!r}: not on the pinned allowlist")
        if not self._auto_install_enabled():
            return {**rep, "refused": "auto-install is off (set hw.auto_install_drivers=true to allow pinned PyPI installs)"}
        pip_name, ver = PINNED_ALLOWLIST[import_name]
        try:
            proc = subprocess.run([sys.executable, "-m", "pip", "install", f"{pip_name}=={ver}"],
                                  capture_output=True, text=True, timeout=300)
        except Exception as exc:  # noqa: BLE001 — pip itself failed to spawn
            write_audit(self.db, action="DRIVER_INSTALL_FAILED", entity_type="System", entity_id=0,
                        after={"package": pip_name, "error": str(exc)})
            self.db.commit()
            raise ValueError(f"pip failed for {pip_name}: {exc}") from exc
        if proc.returncode != 0:
            write_audit(self.db, action="DRIVER_INSTALL_FAILED", entity_type="System", entity_id=0,
                        after={"package": pip_name, "error": proc.stderr[-500:]})
            self.db.commit()
            raise ValueError(f"pip failed for {pip_name}: {proc.stderr[-300:]}")
        # post-install verification: the import must work and the version match
        try:
            importlib.invalidate_caches()
            importlib.import_module(import_name)
            got = _dist_version(pip_name)
        except ImportError as exc:
            write_audit(self.db, action="DRIVER_INSTALL_FAILED", entity_type="System", entity_id=0,
                        after={"package": pip_name, "error": "installed but not importable"})
            self.db.commit()
            raise ValueError(f"{pip_name} installed but not importable") from exc
        if got != ver:
            write_audit(self.db, action="DRIVER_INSTALL_FAILED", entity_type="System", entity_id=0,
                        after={"package": pip_name, "error": f"version mismatch: want {ver}, got {got}"})
            self.db.commit()
            raise ValueError(f"{pip_name} version mismatch: want {ver}, got {got}")
        write_audit(self.db, action="DRIVER_INSTALLED", entity_type="System", entity_id=0,
                    after={"package": pip_name, "version": ver})
        self.db.commit()
        return self.status(import_name)
