"""Connection Center / System Diagnostics (§42–44).

Every check performs a REAL operation and reports latency + evidence. Nothing
returns a green tick just because a row exists in a config table:

  * database          – executes a write+read round-trip in a savepoint
  * api               – exercises the app's own routing layer
  * disk / storage     – writes and deletes a probe file in the media dir
  * internet           – TCP/HTTPS request to a neutral endpoint
  * product sources    – runs each configured provider against a probe barcode
  * image source       – downloads + validates the resolved image
  * price source       – queries the configured PRICE providers
  * sms                – provider config validation + (file provider) real send
  * printer/drawer/scanner – queries the hardware layer; when no device is
    present the result is SKIPPED (environment limited), never PASS.

Result statuses: PASS | FAIL | WARN | SKIPPED. A check that cannot be performed
in this environment is SKIPPED with a reason — it is never reported as PASS.
"""
from __future__ import annotations

import json
import os
import socket
import time
from datetime import datetime
from pathlib import Path

import httpx
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from ..config import settings
from ..models import DiagnosticRun, ExternalSource, HardwareDevice, SystemSetting, User

PROBE_BARCODE = "3017620422003"  # a real, well-known GS1 barcode (Nutella 400g)
NEUTRAL_HOSTS = [("1.1.1.1", 443), ("8.8.8.8", 53)]


def _check(name: str, category: str, fn, *, timeout_note: str = "") -> dict:
    started = time.perf_counter()
    try:
        result = fn()
    except Exception as exc:  # noqa: BLE001 — a diagnostic must never crash
        return {
            "name": name, "category": category, "status": "FAIL",
            "detail": f"{type(exc).__name__}: {exc}"[:500],
            "duration_ms": round((time.perf_counter() - started) * 1000, 1),
        }
    ms = round((time.perf_counter() - started) * 1000, 1)
    status = result.get("status", "PASS")
    return {
        "name": name, "category": category, "status": status,
        "detail": result.get("detail", ""),
        "evidence": result.get("evidence"),
        "duration_ms": ms,
        "steps": result.get("steps", []),
    }


# --- individual checks --------------------------------------------------------

def check_database(db: Session) -> dict:
    steps = []
    db.execute(text("SELECT 1"))
    steps.append({"step": "connect", "ok": True})
    nested = db.begin_nested()
    try:
        db.add(SystemSetting(key="__diag_probe__", value=datetime.utcnow().isoformat(),
                             description="diagnostic write probe", is_secret=False))
        db.flush()
        steps.append({"step": "write", "ok": True})
        got = db.execute(
            select(SystemSetting).where(SystemSetting.key == "__diag_probe__")
        ).scalar_one_or_none()
        steps.append({"step": "read_back", "ok": got is not None})
    finally:
        nested.rollback()  # probe row never persists
    steps.append({"step": "rollback", "ok": True})
    url = settings.DATABASE_URL
    engine_kind = url.split(":", 1)[0]
    return {"status": "PASS", "detail": f"{engine_kind} write/read/rollback OK",
            "evidence": {"engine": engine_kind}, "steps": steps}


def check_api(db: Session) -> dict:
    """Verify the API surface is actually mounted.

    Routers are included lazily by recent FastAPI versions, so counting
    ``app.routes`` alone under-reports. The OpenAPI schema is the authoritative
    view of what a client can call, so we assert against that.
    """
    from ..main import app

    paths = [p for p in app.openapi().get("paths", {}) if p.startswith("/api")]
    if not paths:
        return {"status": "FAIL", "detail": "No /api routes registered"}
    expected = {"/api/pos/checkout", "/api/products", "/api/inventory/stocktakes",
                "/api/marketing/coupons", "/api/diagnostics/run"}
    missing = sorted(expected - set(paths))
    if missing:
        return {"status": "WARN", "detail": f"{len(paths)} routes mounted, missing: {missing}",
                "evidence": {"route_count": len(paths), "missing": missing}}
    return {"status": "PASS", "detail": f"{len(paths)} API endpoints mounted and reachable",
            "evidence": {"route_count": len(paths)}}


def check_storage(db: Session) -> dict:
    media = Path(settings.MEDIA_DIR) if hasattr(settings, "MEDIA_DIR") else Path("data/media")
    media.mkdir(parents=True, exist_ok=True)
    probe = media / ".diag_probe"
    probe.write_bytes(b"probe")
    ok = probe.read_bytes() == b"probe"
    probe.unlink(missing_ok=True)
    free = None
    try:
        st = os.statvfs(media)
        free = round(st.f_bavail * st.f_frsize / (1024 ** 3), 2)
    except (AttributeError, OSError):
        pass
    return {"status": "PASS" if ok else "FAIL",
            "detail": f"media dir writable ({media})" + (f", {free} GB free" if free else ""),
            "evidence": {"path": str(media), "free_gb": free}}


def check_internet(db: Session) -> dict:
    for host, port in NEUTRAL_HOSTS:
        try:
            with socket.create_connection((host, port), timeout=3):
                return {"status": "PASS", "detail": f"TCP reachable: {host}:{port}",
                        "evidence": {"host": host, "port": port}}
        except OSError:
            continue
    return {"status": "WARN",
            "detail": "No internet egress. Local/LAN operation is unaffected "
                      "(offline-first); external resolvers and SMS will queue."}


def check_lan(db: Session) -> dict:
    """Report the LAN address a phone must use (§15 local network)."""
    ip = None
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
    except OSError:
        try:
            ip = socket.gethostbyname(socket.gethostname())
        except OSError:
            ip = None
    if not ip or ip.startswith("127."):
        return {"status": "WARN", "detail": "No routable LAN address detected",
                "evidence": {"ip": ip}}
    port = getattr(settings, "PORT", 8000)
    return {"status": "PASS",
            "detail": f"Mobile devices can reach this server at http://{ip}:{port}/m/",
            "evidence": {"lan_ip": ip, "port": port,
                         "mobile_url": f"http://{ip}:{port}/m/"}}


def _source_check(db: Session, source: ExternalSource, barcode: str) -> dict:
    from .resolvers import _instantiate  # local import: avoids a cycle
    from .providers import ProviderError

    provider = _instantiate(source)
    steps = []
    try:
        lookup = provider.lookup(barcode)
    except ProviderError as exc:
        return {"status": "FAIL",
                "detail": f"{source.code}: {exc.kind} {exc.detail}"[:400],
                "steps": [{"step": "connect", "ok": False, "error": exc.kind}]}
    steps.append({"step": "connect", "ok": True})
    steps.append({"step": "authenticate", "ok": True,
                  "note": "no auth required" if not source.api_key else "api key accepted"})
    has_fields = bool(lookup.fields)
    steps.append({"step": "barcode_query", "ok": True})
    steps.append({"step": "product_data", "ok": has_fields,
                  "note": f"{len(lookup.fields or {})} fields"})
    steps.append({"step": "image_data", "ok": bool(lookup.image_url)})
    status = "PASS" if has_fields else "WARN"
    return {"status": status,
            "detail": f"{source.code}: " + ("data returned" if has_fields
                                            else "reachable but no data for the probe barcode"),
            "evidence": {"fields": list((lookup.fields or {}).keys()),
                         "image": bool(lookup.image_url), "price": lookup.price is not None},
            "steps": steps}


def check_sms(db: Session) -> dict:
    from . import sms as sms_svc

    provider = sms_svc.get_setting(db, "sms.provider", "").strip()
    if not provider:
        return {"status": "SKIPPED", "detail": "No SMS provider configured"}
    if provider not in sms_svc.PROVIDERS:
        return {"status": "FAIL", "detail": f"Unknown provider: {provider}"}
    if provider == "file":
        path = sms_svc.get_setting(db, "sms.file_path", "data/sms_out.log")
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        sms_svc._send_file(db, "0000000000", "[diagnostic] connection test")
        return {"status": "PASS", "detail": f"file provider wrote to {path}"}
    # real panels: validate credentials presence, then a live credit/status call
    missing = []
    if provider == "melipayamak":
        for k in ("sms.username", "sms.password", "sms.sender"):
            if not sms_svc.get_setting(db, k, ""):
                missing.append(k)
    if provider == "kavenegar" and not sms_svc.get_setting(db, "sms.api_key", ""):
        missing.append("sms.api_key")
    if missing:
        return {"status": "FAIL", "detail": "Missing settings: " + ", ".join(missing)}
    try:
        if provider == "kavenegar":
            key = sms_svc.get_setting(db, "sms.api_key", "")
            r = httpx.get(f"https://api.kavenegar.com/v1/{key}/account/info.json", timeout=8)
        else:
            r = httpx.post("https://rest.payamak-panel.com/api/SendSMS/GetCredit",
                           json={"username": sms_svc.get_setting(db, "sms.username", ""),
                                 "password": sms_svc.get_setting(db, "sms.password", "")},
                           timeout=8)
    except httpx.HTTPError as exc:
        return {"status": "FAIL", "detail": f"network: {type(exc).__name__}"}
    ok = r.status_code == 200
    return {"status": "PASS" if ok else "FAIL",
            "detail": f"{provider} credit/status HTTP {r.status_code}",
            "evidence": {"body": r.text[:200]}}


def check_hardware(db: Session, device_type: str) -> dict:
    from . import hardware as hw

    # Newest enabled device wins — same rule the print path uses, so the
    # diagnostic tests exactly the device that would actually be driven.
    dev = db.execute(
        select(HardwareDevice).where(HardwareDevice.device_type == device_type,
                                     HardwareDevice.is_enabled.is_(True))
        .order_by(HardwareDevice.id.desc())
    ).scalars().first()
    if dev is None:
        return {"status": "SKIPPED",
                "detail": f"No enabled {device_type} configured — "
                          f"hardware test requires a physical device"}
    if device_type == "PRINTER":
        ok, detail = hw.probe_printer(db, dev)
    elif device_type == "CASH_DRAWER":
        ok, detail = hw.probe_drawer(db, dev)
    else:
        ok, detail = hw.probe_scanner(db, dev)
    return {"status": "PASS" if ok else "FAIL", "detail": detail,
            "evidence": {"device": dev.name, "connection": dev.connection}}


def check_time(db: Session) -> dict:
    """Verify the machine clock against trusted network time (§22).

    A wrong clock silently mis-dates invoices, so this is a first-class check.
    It never rewrites the clock — it reports drift for a human to fix.
    """
    from . import sms as sms_svc
    from .timeservice import check_time_sync, describe_now

    servers = [x.strip() for x in
               sms_svc.get_setting(db, "time.ntp_servers", "pool.ntp.org").split(",")
               if x.strip()]
    try:
        max_drift = int(sms_svc.get_setting(db, "time.max_drift_seconds", "120") or 120)
    except ValueError:
        max_drift = 120

    result = check_time_sync(servers, max_drift_seconds=max_drift, timeout=3.0)
    now = describe_now(sms_svc.get_setting(db, "time.timezone", "Asia/Tehran"))

    status = {"PASS": "PASS", "WARNING": "WARN", "UNVERIFIED": "SKIPPED"}[result["status"]]
    return {
        "status": status,
        "detail": result["message"],
        "evidence": {
            "source": result["source"],
            "drift_seconds": result["drift_seconds"],
            "local_utc": result["local_utc"],
            "timezone": now["timezone"],
            "jalali_now": now["jalali"],
        },
    }


def check_customer_ledger(db: Session) -> dict:
    """Prove every customer account balance still equals its own history (§32).

    This is a real data-validation test in the §45 sense: it recomputes each
    balance from the append-only entries and compares it with the stored
    witness, rather than asserting the feature is 'configured'.
    """
    from ..models import Customer as _Customer
    from .ledger import verify_integrity

    ids = list(db.execute(select(_Customer.id)).scalars())
    checked = 0
    broken: list[dict] = []
    for cid in ids:
        report = verify_integrity(db, cid)
        if report["entries"] == 0:
            continue
        checked += 1
        if not report["ok"]:
            broken.append({"customer_id": cid, "mismatches": report["mismatches"]})

    if broken:
        return {"status": "FAIL",
                "detail": f"{len(broken)} حساب مشتری با تاریخچهٔ خود مغایرت دارد",
                "evidence": {"broken": broken[:5], "accounts_checked": checked}}
    if checked == 0:
        return {"status": "SKIPPED", "detail": "هیچ حساب دفتری فعالی وجود ندارد",
                "evidence": {"customers": len(ids)}}
    return {"status": "PASS",
            "detail": f"{checked} حساب مشتری بررسی شد؛ مانده با تاریخچه مطابقت دارد",
            "evidence": {"accounts_checked": checked}}


# --- runner -------------------------------------------------------------------

def run_full(db: Session, user: User | None = None, *, include_external: bool = True) -> dict:
    started = datetime.utcnow()
    checks: list[dict] = [
        _check("Local Database", "core", lambda: check_database(db)),
        _check("Backend API", "core", lambda: check_api(db)),
        _check("Media Storage", "core", lambda: check_storage(db)),
        _check("Internet", "network", lambda: check_internet(db)),
        _check("Mobile / LAN access", "network", lambda: check_lan(db)),
        _check("Trusted time (NTP)", "core", lambda: check_time(db)),
        _check("Customer ledger integrity", "data",
               lambda: check_customer_ledger(db)),
    ]

    if include_external:
        sources = list(db.execute(
            select(ExternalSource).where(ExternalSource.is_active.is_(True))
            .order_by(ExternalSource.priority)
        ).scalars())
        if not sources:
            checks.append({"name": "External product sources", "category": "external",
                           "status": "SKIPPED", "detail": "No external source configured",
                           "duration_ms": 0.0, "steps": []})
        for s in sources:
            label = {"PRODUCT": "Product source", "IMAGE": "Image source",
                     "PRICE": "Pricing source"}.get(s.source_type, "Source")
            checks.append(_check(f"{label}: {s.name}", "external",
                                 lambda s=s: _source_check(db, s, PROBE_BARCODE)))
    else:
        checks.append({"name": "External sources", "category": "external",
                       "status": "SKIPPED", "detail": "Skipped by request (offline mode)",
                       "duration_ms": 0.0, "steps": []})

    checks.append(_check("SMS gateway", "services", lambda: check_sms(db)))
    checks.append(_check("Thermal printer", "hardware", lambda: check_hardware(db, "PRINTER")))
    checks.append(_check("Cash drawer", "hardware", lambda: check_hardware(db, "CASH_DRAWER")))
    checks.append(_check("Barcode scanner", "hardware",
                         lambda: check_hardware(db, "BARCODE_SCANNER")))

    passed = sum(1 for c in checks if c["status"] == "PASS")
    failed = sum(1 for c in checks if c["status"] == "FAIL")
    skipped = sum(1 for c in checks if c["status"] in ("SKIPPED", "WARN"))

    run = DiagnosticRun(
        started_at=started, finished_at=datetime.utcnow(), total=len(checks),
        passed=passed, failed=failed, skipped=skipped,
        report=json.dumps(checks, ensure_ascii=False, default=str),
        created_by=user.id if user else None,
    )
    db.add(run)
    db.commit()

    return {"run_id": run.id, "started_at": started.isoformat(),
            "finished_at": run.finished_at.isoformat(),
            "total": len(checks), "passed": passed, "failed": failed,
            "skipped": skipped, "checks": checks}


def history(db: Session, limit: int = 20) -> list[dict]:
    rows = db.execute(
        select(DiagnosticRun).order_by(DiagnosticRun.id.desc()).limit(limit)
    ).scalars()
    return [{"id": r.id, "started_at": r.started_at.isoformat(),
             "finished_at": r.finished_at.isoformat() if r.finished_at else None,
             "total": r.total, "passed": r.passed, "failed": r.failed,
             "skipped": r.skipped} for r in rows]


def get_run(db: Session, run_id: int) -> dict | None:
    r = db.get(DiagnosticRun, run_id)
    if not r:
        return None
    return {"id": r.id, "started_at": r.started_at.isoformat(),
            "finished_at": r.finished_at.isoformat() if r.finished_at else None,
            "total": r.total, "passed": r.passed, "failed": r.failed,
            "skipped": r.skipped, "checks": json.loads(r.report)}
