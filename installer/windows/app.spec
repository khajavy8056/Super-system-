# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec — builds a single-file Windows executable.
# Usage:  pyinstaller --clean app.spec
import os
from pathlib import Path

ROOT = Path(os.path.abspath(SPECPATH)).parent.parent.parent  # repo root

a = Analysis(
    [str(ROOT / "installer" / "windows" / "run_supermarket.py")],
    pathex=[str(ROOT / "backend")],
    binaries=[],
    datas=[
        (str(ROOT / "frontend"), "frontend"),
    ],
    hiddenimports=[
        "uvicorn.logging", "uvicorn.loops", "uvicorn.loops.auto",
        "uvicorn.protocols", "uvicorn.protocols.http", "uvicorn.protocols.http.auto",
        "uvicorn.protocols.websockets", "uvicorn.protocols.websockets.auto",
        "uvicorn.lifespan", "uvicorn.lifespan.on",
        "app", "app.main", "app.database", "app.config", "app.security", "app.bootstrap",
        "app.models", "app.models.catalog", "app.models.inventory", "app.models.sales",
        "app.models.pricing", "app.models.external", "app.models.system", "app.models.user",
        "app.services", "app.services.audit", "app.services.catalog", "app.services.inventory",
        "app.services.pricing", "app.services.pos", "app.services.expiry",
        "app.services.reports", "app.services.resolvers", "app.services.hardware",
        "app.services.notifications",
        "app.routers", "app.routers.auth", "app.routers.products", "app.routers.batches",
        "app.routers.inventory", "app.routers.pricing", "app.routers.pos", "app.routers.invoices",
        "app.routers.returns", "app.routers.resolvers", "app.routers.sms", "app.routers.hardware",
        "app.routers.reports", "app.routers.users", "app.routers.audit", "app.routers.settings",
        "app.routers.system",
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="SupermarketSystem",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,  # keep console for logs; set False for a windowed app
    disable_windowed_traceback=False,
)
