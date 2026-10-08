# -*- coding: utf-8 -*-
"""build-488 — Developer Mode (§۳۸–۴۰).

کاملاً جدا از UI معمولی و برای کاربران عادی/مدیر فروشگاه نامرئی: همهٔ endpointها
با دسترسی `dev.mode` محافظت می‌شوند (§۵۰) و در UI فقط با همان دسترسی دیده می‌شوند.

- Debug/Diagnostics: خلاصهٔ وضعیت، اجرای عیب‌یابی، تاریخچه
- Logs ساختاریافته و قابل فیلتر با دسته‌بندی‌های §۳۹ (بدون اطلاعات حساس)
- API/Database: فهرست مسیرها + آمار جداول
- Sync/Device/Hardware/Network/Update/Performance
"""
from __future__ import annotations

import os
import time
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import inspect as sa_inspect, select, text
from sqlalchemy.orm import Session

from .. import BUILD, __version__
from ..database import get_db
from ..models import AuditLog, DiagnosticRun, HardwareDevice, SyncJob, User
from ..security import require_permission

router = APIRouter(prefix="/dev", tags=["dev"],
                   dependencies=[Depends(require_permission("dev.mode"))])

_STARTED_AT = time.time()

#: دسته‌بندی لاگ‌ها (§۳۹) — حساس‌ها هرگز لاگ نمی‌شوند (§۳۹)
LOG_CATEGORIES = ["AUTH", "API", "DATABASE", "SYNC", "POS", "INVENTORY", "AI",
                  "UPDATE", "NETWORK", "HARDWARE", "PAYMENT_TERMINAL", "BARCODE",
                  "PRINTER", "APPLICATION_ERROR"]

_ACTION_CATEGORY = {
    "LOGIN": "AUTH", "LOGOUT": "AUTH", "LOGIN_FAILED": "AUTH", "UPDATE_AUTH_FAILED": "AUTH",
    "UPDATE_PREPARE": "UPDATE", "UPDATE_APPLIED": "UPDATE",
    "SALE_VOIDED": "POS", "SALE_CREATED": "POS", "SALE_RETURNED": "POS",
    "STOCKTAKE": "INVENTORY", "STOCK_ADJUSTED": "INVENTORY",
    "USER_CREATED": "AUTH", "USER_UPDATED": "AUTH",
    "DEMO_STORE_GENERATED": "DATABASE", "BACKUP_CREATED": "DATABASE", "BACKUP_RESTORED": "DATABASE",
    "HARDWARE_TEST": "HARDWARE", "SYNC_JOB": "SYNC",
}


@router.get("/overview")
def overview(db: Session = Depends(get_db)):
    insp = sa_inspect(db.get_bind())
    tables = insp.get_table_names()
    row_total = 0
    for t in tables:
        try:
            row_total += db.execute(text(f'SELECT COUNT(*) FROM "{t}"')).scalar_one()
        except Exception:
            pass
    return {
        "version": __version__, "build": BUILD,
        "uptime_seconds": int(time.time() - _STARTED_AT),
        "db_tables": len(tables), "db_rows_estimate": row_total,
        "python": os.sys.version.split()[0],
        "pid": os.getpid(),
    }


@router.get("/logs")
def logs(category: str | None = Query(default=None), limit: int = Query(default=100, le=500),
         db: Session = Depends(get_db)):
    """لاگ‌های ساختاریافته — فقط متادیتای امن؛ رمز/توکن هرگز (§۳۹)."""
    q = select(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit * 3)
    rows = []
    for a in db.execute(q).scalars():
        cat = _ACTION_CATEGORY.get(a.action, "API")
        if category and cat != category:
            continue
        rows.append({"id": a.id, "category": cat, "action": a.action,
                     "user_id": a.user_id, "entity_type": a.entity_type,
                     "entity_id": a.entity_id,
                     "created_at": a.created_at.isoformat() if a.created_at else None})
        if len(rows) >= limit:
            break
    return {"categories": LOG_CATEGORIES, "items": rows}


@router.get("/api/routes")
def api_routes():
    from ..main import app
    out = []
    for r in app.routes:
        path = getattr(r, "path", "")
        methods = sorted(getattr(r, "methods", []) or [])
        if path.startswith("/api") or path.startswith("/users") or path.startswith("/system"):
            out.append({"path": path, "methods": methods})
    return out


@router.get("/db/tables")
def db_tables(db: Session = Depends(get_db)):
    insp = sa_inspect(db.get_bind())
    out = []
    for t in sorted(insp.get_table_names()):
        try:
            n = db.execute(text(f'SELECT COUNT(*) FROM "{t}"')).scalar_one()
        except Exception:
            n = None
        cols = [c["name"] for c in insp.get_columns(t)]
        out.append({"table": t, "rows": n, "columns": cols})
    return out


@router.get("/sync")
def sync_status(db: Session = Depends(get_db)):
    jobs = db.execute(select(SyncJob).order_by(SyncJob.id.desc()).limit(20)).scalars().all()
    by_status: dict[str, int] = {}
    for j in db.execute(select(SyncJob)).scalars():
        by_status[j.status] = by_status.get(j.status, 0) + 1
    return {"counts": by_status,
            "recent": [{"id": j.id, "status": j.status,
                        "created_at": j.created_at.isoformat() if j.created_at else None}
                       for j in jobs]}


@router.get("/hardware")
def hardware(db: Session = Depends(get_db)):
    return [{"id": d.id, "name": d.name, "type": getattr(d, "type", None) or getattr(d, "hw_type", None),
             "status": getattr(d, "status", None)} for d in
            db.execute(select(HardwareDevice)).scalars()]


@router.get("/diagnostics/history")
def diagnostics_history(db: Session = Depends(get_db), limit: int = Query(default=10, le=50)):
    return [{"id": r.id,
             "created_at": r.created_at.isoformat() if getattr(r, "created_at", None) else None,
             "status": getattr(r, "status", None)}
            for r in db.execute(select(DiagnosticRun).order_by(DiagnosticRun.id.desc()).limit(limit)).scalars()]


@router.get("/network")
def network():
    """وضعیت اتصال به مخزن انتشار (§۴۱) و کانال به‌روزرسانی — غیرمختل‌کننده."""
    from ..services.updater import GITHUB_REPO
    out = {"update_repo": GITHUB_REPO, "checked_at": datetime.utcnow().isoformat()}
    try:
        import httpx
        resp = httpx.head(f"https://api.github.com/repos/{GITHUB_REPO}", timeout=4.0,
                          follow_redirects=True)
        out["github_reachable"] = resp.status_code < 500
        out["github_status"] = resp.status_code
    except Exception as exc:
        out["github_reachable"] = False
        out["error"] = type(exc).__name__
    return out


@router.get("/performance")
def performance():
    usage = {}
    try:
        import resource
        r = resource.getrusage(resource.RUSAGE_SELF)
        usage = {"max_rss_kb": r.ru_maxrss, "user_cpu_s": round(r.ru_utime, 2),
                 "system_cpu_s": round(r.ru_stime, 2)}
    except Exception:
        pass
    return {"uptime_seconds": int(time.time() - _STARTED_AT), "pid": os.getpid(), **usage}
