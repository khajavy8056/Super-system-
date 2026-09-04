"""FastAPI application entrypoint."""
from __future__ import annotations

import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import __version__
from .config import settings
from .database import init_db
from .routers import (
    audit,
    auth,
    batches,
    hardware,
    inventory,
    invoices,
    pos,
    pricing,
    products,
    reports,
    resolvers,
    returns,
    settings as settings_router,
    sms,
    system,
    users,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(
    title=settings.APP_NAME,
    version=__version__,
    description="Supermarket ERP / Smart Inventory / POS — batch-aware, offline-first.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

API = "/api"
for r in (
    auth.router, products.router, batches.router, inventory.router, pricing.router,
    pos.router, invoices.router, returns.router, resolvers.router, sms.router,
    hardware.router, reports.router, users.router, audit.router, settings_router.router,
):
    app.include_router(r, prefix=API)

# system router is intentionally unprefixed for /health
app.include_router(system.router)


# Serve the web panel (frontend/) from the same origin when present.
def _find_frontend_dir() -> Path | None:
    candidates = [
        os.environ.get("FRONTEND_DIR"),
        str(Path(getattr(sys, "_MEIPASS", "")) / "frontend"),
        str(Path(__file__).resolve().parent.parent.parent / "frontend"),
        str(Path(__file__).resolve().parent / "frontend"),
    ]
    for c in candidates:
        if c and Path(c).exists():
            return Path(c)
    return None


_FRONTEND_DIR = _find_frontend_dir()
if _FRONTEND_DIR is not None:
    from fastapi.staticfiles import StaticFiles
    app.mount("/", StaticFiles(directory=str(_FRONTEND_DIR), html=True), name="frontend")
