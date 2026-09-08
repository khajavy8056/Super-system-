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


def _optional_desktop_hiddenimports():
    """pywebview (native WebView2 window) is optional since v1.4.1; only ask
    PyInstaller for its modules when the package is actually installed."""
    import importlib.util
    if importlib.util.find_spec("webview") is None:
        return []
    mods = ["webview", "webview.platforms.edgechromium", "webview.platforms.winforms",
            "bottle", "proxy_tools"]
    for m in ("clr", "clr_loader", "pythonnet"):
        if importlib.util.find_spec(m) is not None:
            mods.append(m)
    return mods

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
        # v1.3 native window icon (WebView2 window title bar / taskbar)
        (str(ROOT / "installer" / "windows" / "icon.ico"), "."),
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
        # v1.7 pairing QR PNG fallback (qrcode + Pillow PNG plugin)
        "qrcode", "qrcode.image.pil", "PIL", "PIL.Image", "PIL.PngImagePlugin",
        # v1.3 native desktop window (pywebview on WebView2). pythonnet/clr
        # is loaded dynamically by pywebview's edgechromium backend.
    ] + _optional_desktop_hiddenimports(),
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

# pywebview ships the WebView2 loader DLLs as package data; make sure they
# travel with the exe. OPTIONAL since v1.4.1 (requirements-desktop.txt): when
# the package is not installed nothing is added and the app opens in Edge
# app-mode instead.
#
# v1.4.2 FIX: collect_data_files()/collect_dynamic_libs() return the 2-tuple
# hook format (src, dest_dir). After Analysis, a.datas / a.binaries are TOC
# lists of 3-tuples (dest_name, src_path, typecode). Appending 2-tuples made
# EXE() fail with "ValueError: not enough values to unpack (expected 3, got 2)".
# Convert to proper TOC entries before extending.
def _as_toc(entries, typecode):
    toc = []
    for src, dest_dir in entries:
        dest = os.path.join(dest_dir, os.path.basename(src)) if dest_dir not in ("", ".") else os.path.basename(src)
        toc.append((dest, src, typecode))
    return toc

import importlib.util as _ilu
if _ilu.find_spec("webview") is not None:
    from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs
    a.datas += _as_toc(collect_data_files("webview"), "DATA")
    a.binaries += _as_toc(collect_dynamic_libs("webview"), "BINARY")
    if _ilu.find_spec("clr_loader") is not None:
        a.datas += _as_toc(collect_data_files("clr_loader"), "DATA")

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
