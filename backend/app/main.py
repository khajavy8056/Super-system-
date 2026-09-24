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
    accounting,
    audit,
    auth,
    batches,
    brain,
    customers,
    diagnostics,
    hardware,
    hw,
    inventory,
    mobile,
    invoices,
    marketing,
    pos,
    pricing,
    products,
    reports,
    resolvers,
    returns,
    settings as settings_router,
    setup,
    sms,
    system,
    users,
    warehouses,
    support,
    cloud, insights)

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


def _start_brain_autostart() -> None:
    """v4.2 — the local Business Brain wakes up on its own.

    The owner's rule: on the shop PC the brain must be ALIVE out of the box —
    the installer already put the verified model + llama.cpp engine in the
    user's data dir, so at startup we (1) adopt that preinstalled model
    (idempotent, re-hashed, never deletes) and (2) warm-start llama-server so
    the first question does not wait for a cold model load. Everything is
    guarded: without a model/engine this is a no-op, and no failure here may
    ever keep the app from starting. Kill-switch: SUPERMARKET_BRAIN_AUTOSTART=0.
    """
    import logging

    if os.environ.get("SUPERMARKET_BRAIN_AUTOSTART", "1") in ("0", "false", "off"):
        return

    log = logging.getLogger("supermarket.brain.autostart")

    def run() -> None:
        try:
            from .database import SessionLocal
            from .services.business_brain import model_manager as mm
            from .services.business_brain import runtime as runtime_svc

            db = SessionLocal()
            try:
                manager = mm.ModelManager(db)
                manager.adopt_preinstalled()          # installer seed → INSTALLED (+activate)
                install = mm.active_install(db)
                binary = mm.find_binary()
                if install is not None and binary:
                    runtime_svc.get_runtime(db).load()   # warm-start llama-server
                    log.info("brain autostart: model %s ready (engine %s)",
                             install.model_id, binary)
                else:
                    log.info("brain autostart: no model/engine to start (deterministic mode)")
            finally:
                db.close()
        except Exception:                              # noqa: BLE001 — never block startup
            log.warning("brain autostart failed (the brain still works on demand)",
                        exc_info=True)

    threading.Thread(target=run, name="brain-autostart", daemon=True).start()


def _start_brain_worker() -> None:
    """v4.4.0 — the brain is ALWAYS analysing the store (owner's rule).

    A quiet daemon thread runs one proactive pass every 15 minutes: expiring
    stock, dying products, cash pressure, follow-up measurement windows… and
    the reminder loop (due reminders → in-app notification; unanswered → SMS
    to the manager, re-sent until acknowledged). Every tick is guarded — a
    failure here must never touch the rest of the app.
    Kill-switch: SUPERMARKET_BRAIN_WORKER=0.
    """
    import logging

    if os.environ.get("SUPERMARKET_BRAIN_WORKER", "1") in ("0", "false", "off"):
        return

    log = logging.getLogger("supermarket.brain.worker")
    stop = threading.Event()

    def tick() -> None:
        from .database import SessionLocal
        from .services.business_brain import briefing as briefing_svc
        from .services.business_brain import proactive as proactive_svc

        db = SessionLocal()
        try:
            out = proactive_svc.evaluate(db, force=False)
            log.info("brain pass: %s alert(s), %s skipped, %s notified",
                     len(out.get("alerts", [])), len(out.get("skipped", [])),
                     out.get("followups_notified", 0))
        except Exception:                            # noqa: BLE001 — never propagate
            log.warning("brain pass failed (will retry next tick)", exc_info=True)
        try:
            # v4.5.0 — the model also works in the intelligence section:
            # refresh the manager's briefing every pass (grounded, cached).
            briefing_svc.build(db, refresh=True)
        except Exception:                            # noqa: BLE001
            log.warning("briefing refresh failed (will retry next tick)", exc_info=True)
        finally:
            db.close()

    def loop() -> None:
        stop.wait(60)                                # let the app finish booting first
        while not stop.is_set():
            tick()
            stop.wait(15 * 60)                       # every 15 minutes, all day

    threading.Thread(target=loop, name="brain-worker", daemon=True).start()


@asynccontextmanager
async def lifespan(app: FastAPI):
    from .database import SessionLocal
    from .services import sms as sms_svc

    from .services import sync as sync_svc

    init_db()
    from .services.default_catalog import ensure_bundled_update
    with SessionLocal() as catalog_db:
        ensure_bundled_update(catalog_db)
    # v1.7.1: store timezone (default Asia/Tehran, +03:30) drives every "today"
    from .services import timeservice as _ts
    with SessionLocal() as _db:
        _ts.set_local_timezone(_ts.configured_timezone_name(_db))
    sms_svc.start_worker(SessionLocal)  # background SMS dispatch (§68)
    from .services import cloud as cloud_svc
    cloud_svc.start_worker(SessionLocal)  # v1.7 internet sync (no-op until connected)
    from .services import support as support_svc
    support_svc.start_poller(SessionLocal)  # v1.7.1 support replies (every 20 s)
    _start_sync_worker(SessionLocal)    # offline job queue drain (§49)
    from .services import license as license_svc
    license_svc.start_worker(SessionLocal)  # v1.5: 24h online licence re-validation
    from .services import discovery as discovery_svc
    if os.environ.get("SUPERMARKET_LAN_BEACON", "1") not in ("0", "false", "off"):
        discovery_svc.start(SessionLocal, settings.PORT)  # v2.1: phone re-finds the PC when its IP changes
    from .services import relay_client as relay_svc
    relay_svc.start_worker(SessionLocal)  # v2.3: outbound connection to the optional online relay
    from .services import insights as insights_svc
    if os.environ.get("SUPERMARKET_INSIGHTS_WORKER", "1") not in ("0", "false", "off"):
        insights_svc.start_worker(SessionLocal)  # v3.0: store intelligence (local analytics + A/B measurement)
    _start_brain_autostart()                     # v4.2: the local brain wakes up on first launch
    _start_brain_worker()                       # v4.4.0: the brain never sleeps (analyze + reminders)
    yield
    insights_svc.stop_worker()
    relay_svc.stop_worker()
    discovery_svc.stop()
    sms_svc.stop_worker()
    cloud_svc.stop_worker()
    support_svc.stop_poller()
    _stop_sync_worker()
    license_svc.stop_worker()


app = FastAPI(
    title=settings.APP_NAME,
    version=__version__,
    description="Supermarket ERP / Smart Inventory / POS — batch-aware, offline-first.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    # v1.6: the Android shell serves the mobile app from its private origin
    # https://app.local and calls this server over the LAN; browsers on LAN
    # terminals use http://<lan-ip>:<port> which is same-origin anyway.
    allow_origins=list(dict.fromkeys(settings.cors_origin_list + ["https://app.local"])),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

API = "/api"
for r in (
    auth.router, products.router, products.unit_router, products.bank_router, products.catalog_router, batches.router, customers.router,
    inventory.router, pricing.router,
    pos.router, invoices.router, returns.router, resolvers.router, sms.router,
    hardware.router, hw.router, reports.router, users.router, audit.router, settings_router.router,
    marketing.router, diagnostics.router, warehouses.router, accounting.router,
    setup.router, mobile.router, support.router, cloud.router, insights.router, brain.router,
):
    app.include_router(r, prefix=API)

# system router is intentionally unprefixed for /health
app.include_router(system.router)
# v3.0: the same endpoints are also reachable on the authenticated API surface
# (/api/system/backups, /backup, /restore, /demo, /demo/load) for the Backup panel + phones.
app.include_router(system.router, prefix=API + "/system", include_in_schema=False)
# ...but the update endpoints belong on the normal authenticated API surface
app.include_router(system.update_router, prefix="/api")


# --- Error handling (BUG-020): users never see raw stack/SQL traces ----------
def _audit_api_error(request: Request, code: str, status: int, error_id: str,
                     exc: Exception) -> None:
    """§43 — API_ERROR must land in the audit trail, not only in the log file.

    The operator needs to correlate "the system misbehaved at 14:20" with a
    record inside the app; a stderr line on a shop PC is gone at the next
    reboot. This opens its own short-lived session because the request-scoped
    one may be the thing that is broken. Any failure here is swallowed: a
    broken audit writer must never replace a 500 with a second, worse error.
    """
    try:
        from .database import SessionLocal
        from .services.audit import write_audit

        db = SessionLocal()
        try:
            write_audit(
                db, action="API_ERROR", entity_type="Request",
                reference=f"{request.method} {request.url.path}",
                after={"code": code, "status": status, "error_id": error_id,
                       "exception": type(exc).__name__, "detail": str(exc)[:500]},
            )
            db.commit()
        finally:
            db.close()
    except Exception:  # pragma: no cover - defensive
        logger.exception("could not write API_ERROR audit entry")


def _error_response(exc: Exception, request: Request, code: str, status: int) -> JSONResponse:
    error_id = uuid.uuid4().hex[:12]
    logger.error(
        "ErrorID=%s %s %s -> %s: %s",
        error_id, request.method, request.url.path, type(exc).__name__, exc,
    )
    _audit_api_error(request, code, status, error_id, exc)
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


# --- v1.5 licence gate ---------------------------------------------------------
# The application never works without an activated licence. Everything except
# health, the setup/licence endpoints and static assets is refused with 402 so
# the UI can show the activation wizard. The verdict comes from the cached state
# (no network on the request path); a background worker re-validates every 24 h.
_LICENSE_FREE_PREFIXES = ("/api/setup/", "/health", "/media/", "/icons/", "/docs", "/openapi.json", "/redoc")
_LICENSE_GATE_ENABLED = os.environ.get("SUPERMARKET_LICENSE_GATE", "1") not in ("0", "false", "off")


@app.middleware("http")
async def method_override(request: Request, call_next):
    """v2.0 — the native Android client (HttpURLConnection) cannot emit PATCH;
    it sends POST + ``X-HTTP-Method-Override: PATCH``. Only PATCH is honoured."""
    if request.method == "POST" and request.headers.get("x-http-method-override", "").upper() == "PATCH":
        request.scope["method"] = "PATCH"
    return await call_next(request)


@app.middleware("http")
async def license_gate(request: Request, call_next):
    path = request.url.path
    if _LICENSE_GATE_ENABLED and path.startswith("/api/") and not path.startswith(_LICENSE_FREE_PREFIXES):
        from .database import SessionLocal
        from .services import license as license_svc

        db = SessionLocal()
        try:
            st = license_svc.state(db)
            if not st["allowed"] and st.get("activated"):
                try:  # v1.6: preserve the shop's data in an encrypted archive when locking
                    if license_svc.lock_vault(db):
                        db.commit()
                except Exception as exc:  # noqa: BLE001
                    logging.getLogger("supermarket.license").warning("vault failed: %s", exc)
        finally:
            db.close()
        if not st["allowed"]:
            return JSONResponse(status_code=402, content={"detail": {
                "code": "LICENSE_REQUIRED", "message": st["reason"] or "لایسنس فعال نیست",
                "license": {k: st[k] for k in ("status", "expires", "days_left", "hwid")}}})
    return await call_next(request)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    # v3.7 (§34) — the shop panel needs no camera/mic/geolocation; deny the lot.
    response.headers.setdefault(
        "Permissions-Policy",
        "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
    )
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
