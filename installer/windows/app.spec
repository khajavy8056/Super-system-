# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec — builds a single-file Windows executable.
# Usage:  pyinstaller --clean app.spec
import os
from pathlib import Path

ROOT = Path(os.path.abspath(SPECPATH)).parent.parent  # repo root (installer/windows -> repo)

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
        # app's own modules are found by static analysis (no dynamic imports);
        # listed explicitly anyway so a missing file fails the build loudly:
        "app.main", "app.database", "app.bootstrap",
        "app.services.providers", "app.services.providers.openfoodfacts",
        "app.services.providers.custom_http",
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
    icon=str(ROOT / "installer" / "windows" / "icon.ico"),
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,  # keep console for logs; set False for a windowed app
    disable_windowed_traceback=False,
)
