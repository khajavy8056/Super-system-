# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec — builds a single-file Windows executable.
# Usage:  pyinstaller --clean app.spec
#
# SELF-CONTAINMENT (this is the whole point of the deliverable):
# PyInstaller embeds the CPython interpreter itself plus every third-party
# package from backend/requirements.txt into the one .exe produced here. The
# frontend, the mobile PWA and the Alembic migrations ride along as `datas`.
# Therefore the machine the Setup.exe is installed on needs NO Python, no pip,
# no Node and no database engine — SQLite is part of the Python standard
# library. Everything is downloaded once, on the BUILD machine, by
# BUILD-SETUP.bat, and baked in here.
import os
from pathlib import Path

ROOT = Path(os.path.abspath(SPECPATH)).parent.parent  # repo root (installer/windows -> repo)

a = Analysis(
    [str(ROOT / "installer" / "windows" / "run_supermarket.py")],
    pathex=[str(ROOT / "backend")],
    binaries=[],
    datas=[
        (str(ROOT / "frontend"), "frontend"),
        # Migrations must travel with the installed app (see setup.py note).
        (str(ROOT / "backend" / "alembic"), "alembic"),
        (str(ROOT / "backend" / "alembic.ini"), "."),
        # §80–82 bundled zero-stock starter catalog (read at runtime via __file__).
        (str(ROOT / "backend" / "app" / "data"), "app/data"),
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
        # CRITICAL (found by the cx_Freeze frozen boot test): SQLAlchemy loads
        # the sqlite dialect via entry points -> frozen apps miss it without this
        "sqlalchemy.dialects.sqlite",
        # starlette imports the multipart parser lazily on first form POST
        "multipart", "python_multipart",
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
    # No console window: the end user gets the graphical panel in their
    # browser, and a stray black cmd window reads as "something is broken".
    # All logs still go to %USERPROFILE%\SupermarketSystem\logs\.
    console=False,
    disable_windowed_traceback=False,
)
