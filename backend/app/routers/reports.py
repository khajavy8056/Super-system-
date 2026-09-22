from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import User
from ..security import get_current_user, has_permission, require_permission
from ..services import reports as rep

router = APIRouter(prefix="/reports", tags=["reports"])


def _maybe_redact(user: User, payload):
    """v3.7 (§34) — costs/profit/valuation leave the server only for users
    holding ``pricing.view_cost``. Everyone else gets the same shape with
    those figures nulled (keys stay, so clients keep working)."""
    if has_permission(user, "pricing.view_cost"):
        return payload
    return rep.redact_costs(payload)


@router.get("/dashboard")
def dashboard(db: Session = Depends(get_db), user: User = Depends(require_permission("reports.view"))):
    return _maybe_redact(user, rep.dashboard(db))


@router.get("/sales")
def sales(start: date, end: date, group: str = "daily", db: Session = Depends(get_db),
          user: User = Depends(require_permission("reports.view"))):
    """group: daily | weekly | monthly (Jalali buckets) | product (§49, §137)."""
    return _maybe_redact(user, rep.sales_report(db, start, end, group))


@router.get("/cashiers")
def cashiers(start: date | None = None, end: date | None = None, db: Session = Depends(get_db),
             user: User = Depends(require_permission("reports.view"))):
    return _maybe_redact(user, rep.cashier_report(db, start, end))


@router.get("/inventory")
def inventory(limit: int | None = Query(default=None, ge=1, le=5000),
              db: Session = Depends(get_db), user: User = Depends(require_permission("reports.view"))):
    # v3.5.9 — one row per product. On a store carrying the full 13k-SKU bank the phone used
    # to build one view per row and froze. Default stays None so the desktop is unchanged.
    rows = rep.inventory_report(db)
    rows = rows[:limit] if limit else rows
    return _maybe_redact(user, rows)


@router.get("/purchase-cost")
def purchase_cost(product_id: int | None = None, limit: int = Query(default=100, le=500),
                  db: Session = Depends(get_db),
                  _: User = Depends(require_permission("pricing.view_cost"))):
    return rep.purchase_cost_history(db, product_id=product_id, limit=limit)


@router.get("/expiry")
def expiry(limit: int | None = Query(default=None, ge=1, le=5000),
           db: Session = Depends(get_db), user: User = Depends(require_permission("reports.view"))):
    # v3.5.9 — capped per bucket, same reason as /inventory. Desktop unaffected by default.
    out = rep.expiry_report(db)
    if limit and isinstance(out, dict):
        out = {k: (v[:limit] if isinstance(v, list) else v) for k, v in out.items()}
    return _maybe_redact(user, out)


@router.get("/adjustments")
def adjustments(limit: int = Query(default=200, le=1000), db: Session = Depends(get_db),
                _: User = Depends(require_permission("reports.view"))):
    return rep.adjustments_report(db, limit=limit)


@router.get("/profit")
def profit(start: date | None = None, end: date | None = None, db: Session = Depends(get_db),
           # v3.7 (§34) — this endpoint IS cost analysis; redaction would leave
           # an empty shell, so it requires the cost permission outright.
           _: User = Depends(require_permission("pricing.view_cost"))):
    return rep.profit_by_batch(db, start, end)


@router.get("/batches")
def batches(db: Session = Depends(get_db), _: User = Depends(require_permission("reports.view"))):
    return rep.batch_status_report(db)


@router.get("/low-stock")
def low_stock(limit: int | None = Query(default=None, ge=1, le=5000),
              db: Session = Depends(get_db), _: User = Depends(require_permission("reports.view"))):
    # v3.5.9 — most of a 13k-SKU store sits at zero stock, so "no stock" alone can be
    # thousands of rows. Desktop unaffected by default.
    rows = rep.low_stock_report(db)
    return rows[:limit] if limit else rows


@router.get("/movements")
def movements(limit: int = 200, db: Session = Depends(get_db), _: User = Depends(require_permission("reports.view"))):
    return rep.movements_report(db, limit=limit)


@router.get("/stocktakes")
def stocktakes(db: Session = Depends(get_db), _: User = Depends(require_permission("reports.view"))):
    return rep.stocktake_report(db)
