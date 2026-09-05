"""FastAPI application entrypoint."""
from __future__ import annotations

import logging
import os
import sys
import threading
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from . import __version__
from .config import settings
from .database import init_db
from .routers import (
    audit,
    auth,
    batches,
    customers,
    diagnostics,
    hardware,
    inventory,
    invoices,
    marketing,
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

logger = logging.getLogger("supermarket.errors")
logger.setLevel(logging.ERROR)
if not logger.handlers:  # avoid duplicate handlers under test reloads
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter("%(asctime)s ERROR %(message)s"))
    logger.addHandler(_h)


# --- offline sync worker ------------------------------------------------------
_sync_stop = threading.Event()
_sync_thread: threading.Thread | None = None


def _start_sync_worker(session_factory) -> None:
    global _sync_thread
    if _sync_thread and _sync_thread.is_alive():
        return
    _sync_stop.clear()

    def run():
        from .services import sync as sync_svc

        while not _sync_stop.is_set():
            try:
                db = session_factory()
                try:
                    sync_svc.run_once(db)
                finally:
                    db.close()
            except Exception:  # the queue worker must never die
                logging.getLogger("supermarket.sync").exception("sync worker tick failed")
            _sync_stop.wait(15)

    _sync_thread = threading.Thread(target=run, name="sync-worker", daemon=True)
    _sync_thread.start()


def _stop_sync_worker() -> None:
    _sync_stop.set()


@asynccontextmanager
async def lifespan(app: FastAPI):
    from .database import SessionLocal
    from .services import sms as sms_svc

    from .services import sync as sync_svc

    init_db()
    sms_svc.start_worker(SessionLocal)  # background SMS dispatch (§68)
    _start_sync_worker(SessionLocal)    # offline job queue drain (§49)
    yield
    sms_svc.stop_worker()
    _stop_sync_worker()


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
    auth.router, products.router, products.unit_router, batches.router, customers.router,
    inventory.router, pricing.router,
    pos.router, invoices.router, returns.router, resolvers.router, sms.router,
    hardware.router, reports.router, users.router, audit.router, settings_router.router,
    marketing.router, diagnostics.router,
):
    app.include_router(r, prefix=API)

# system router is intentionally unprefixed for /health
app.include_router(system.router)
# ...but the update endpoints belong on the normal authenticated API surface
app.include_router(system.update_router, prefix="/api")


# --- Error handling (BUG-020): users never see raw stack/SQL traces ----------
def _error_response(exc: Exception, request: Request, code: str, status: int) -> JSONResponse:
    error_id = uuid.uuid4().hex[:12]
    logger.error(
        "ErrorID=%s %s %s -> %s: %s",
        error_id, request.method, request.url.path, type(exc).__name__, exc,
    )
    message = {
        500: "خطای داخلی سرور. لطفاً عملیات را تکرار کنید و در صورت تکرار، کد خطا را به پشتیبانی گزارش دهید.",
        503: "سرویس به‌طور موقت در دسترس نیست. لطفاً بعداً تلاش کنید.",
    }.get(status, "خطای غیرمنتظره.")
    return JSONResponse(
        status_code=status,
        content={"detail": {"code": code, "message": message, "error_id": error_id}},
    )


@app.exception_handler(SQLAlchemyError)
async def sqlalchemy_error_handler(request: Request, exc: SQLAlchemyError) -> JSONResponse:
    return _error_response(exc, request, "DATABASE_ERROR", 500)


@app.exception_handler(Exception)
async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    return _error_response(exc, request, "INTERNAL_ERROR", 500)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    # CSP: inline handlers are used by the panel, so allow 'unsafe-inline' for
    # scripts in this phase; tighten when the frontend moves to a bundler.
    response.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; img-src 'self' data: https:; style-src 'self' 'unsafe-inline'; "
        "script-src 'self' 'unsafe-inline'; connect-src 'self'",
    )
    return response


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


# Locally stored product images (§21) are served from the same origin so the
# panel and the PWA never depend on a third-party URL.
_MEDIA_DIR = Path(settings.MEDIA_DIR)
_MEDIA_DIR.mkdir(parents=True, exist_ok=True)

_FRONTEND_DIR = _find_frontend_dir()
if _FRONTEND_DIR is not None:
    from fastapi.staticfiles import StaticFiles

    app.mount("/media", StaticFiles(directory=str(_MEDIA_DIR)), name="media")
    # Dedicated mobile/PWA entry point (§10) — its own UX, not a shrunk desktop.
    _MOBILE_DIR = _FRONTEND_DIR / "mobile"
    if _MOBILE_DIR.exists():
        # A phone on the shop Wi-Fi is typed by hand: "192.168.1.5:8000/m".
        # A bare mount only answers "/m/" and 404s on "/m", which reads as
        # "the app is broken" to a staff member. Redirect the slashless form.
        from fastapi.responses import RedirectResponse

        @app.get("/m", include_in_schema=False)
        def _mobile_root():
            return RedirectResponse(url="/m/", status_code=307)

        app.mount("/m", StaticFiles(directory=str(_MOBILE_DIR), html=True), name="mobile")
    app.mount("/", StaticFiles(directory=str(_FRONTEND_DIR), html=True), name="frontend")
