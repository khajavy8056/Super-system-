"""cx_Freeze build for the standalone launcher (dir-based, not onefile).

Why cx_Freeze here: the Linux sandbox has a static python (no
libpython3.11.so.1.0) and broken apt, so PyInstaller cannot link — while
cx_Freeze bundles the interpreter binary + stdlib directly. This build is used
to TEST the frozen-app boot path end-to-end in the sandbox (launcher logic,
module completeness, static assets, user data dir).

On Windows the shipped installer path stays PyInstaller onefile + Inno Setup
(installer/windows/{app.spec,build.ps1,setup.iss}) — PyInstaller works there
because official Windows builds ship a shared libpython.

Usage:
    cd installer/standalone && ../../backend/.venv/bin/python setup.py build
Output: installer/standalone/build/SupermarketSystem-*/ (run the
SupermarketSystem executable).
"""
from __future__ import annotations

import sys
from pathlib import Path

from cx_Freeze import Executable, setup

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent

sys.path.insert(0, str(ROOT / "backend"))

build_options = {
    "packages": ["app", "app.routers", "app.services", "app.services.providers", "uvicorn", "sqlalchemy.dialects.sqlite"],
    "includes": [
        "uvicorn.logging", "uvicorn.loops", "uvicorn.loops.auto",
        "uvicorn.protocols", "uvicorn.protocols.http",
        "uvicorn.protocols.http.auto", "uvicorn.protocols.websockets",
        "uvicorn.protocols.websockets.auto", "uvicorn.lifespan", "uvicorn.lifespan.on",
        "app.services.providers.openfoodfacts", "app.services.providers.custom_http",
    ],
    "include_files": [
        (str(ROOT / "frontend"), "frontend"),
        # Ship the migration tree so an INSTALLED shop can still upgrade its
        # database on a later release. Without these the frozen app logs
        # "Alembic sync skipped" and silently never migrates.
        (str(ROOT / "backend" / "alembic"), "alembic"),
        (str(ROOT / "backend" / "alembic.ini"), "alembic.ini"),
    ],
    "excludes": ["tkinter", "pytest", "pip", "setuptools", "wheel"],
    "optimize": 1,
}

executables = [
    Executable(
        str(HERE.parent / "windows" / "run_supermarket.py"),
        target_name="SupermarketSystem",
        # console app on purpose: logs visible; installer wraps it nicely
    ),
]

setup(
    name="SupermarketSystem",
    version="1.1.0",
    description="Supermarket ERP / Smart Inventory / POS — standalone server",
    options={"build_exe": build_options},
    executables=executables,
)
