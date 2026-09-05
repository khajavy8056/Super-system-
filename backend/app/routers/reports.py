from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import User
from ..security import get_current_user, require_permission
from ..services import reports as rep

router = APIRouter(prefix="/reports", tags=["reports"])


@router.get("/dashboard")
def dashboard(db: Session = Depends(get_db), _: User = Depends(require_permission("reports.view"))):
    return rep.dashboard(db)


@router.get("/sales")
def sales(start: date, end: date, group: str = "daily", db: Session = Depends(get_db),
          _: User = Depends(require_permission("reports.view"))):
    """group: daily | product (§49)."""
    return rep.sales_report(db, start, end, group)


@router.get("/cashiers")
def cashiers(start: date | None = None, end: date | None = None, db: Session = Depends(get_db),
             _: User = Depends(require_permission("reports.view"))):
    return rep.cashier_report(db, start, end)


@router.get("/inventory")
def inventory(db: Session = Depends(get_db), _: User = Depends(require_permission("reports.view"))):
    return rep.inventory_report(db)


@router.get("/purchase-cost")
def purchase_cost(product_id: int | None = None, limit: int = Query(default=100, le=500),
                  db: Session = Depends(get_db),
                  _: User = Depends(require_permission("pricing.view_cost"))):
    return rep.purchase_cost_history(db, product_id=product_id, limit=limit)


@router.get("/expiry")
def expiry(db: Session = Depends(get_db), _: User = Depends(require_permission("reports.view"))):
    return rep.expiry_report(db)


@router.get("/adjustments")
def adjustments(limit: int = Query(default=200, le=1000), db: Session = Depends(get_db),
                _: User = Depends(require_permission("reports.view"))):
    return rep.adjustments_report(db, limit=limit)


@router.get("/profit")
def profit(start: date | None = None, end: date | None = None, db: Session = Depends(get_db),
           _: User = Depends(require_permission("reports.view"))):
    return rep.profit_by_batch(db, start, end)


@router.get("/batches")
def batches(db: Session = Depends(get_db), _: User = Depends(require_permission("reports.view"))):
    return rep.batch_status_report(db)


@router.get("/low-stock")
def low_stock(db: Session = Depends(get_db), _: User = Depends(require_permission("reports.view"))):
    return rep.low_stock_report(db)


@router.get("/movements")
def movements(limit: int = 200, db: Session = Depends(get_db), _: User = Depends(require_permission("reports.view"))):
    return rep.movements_report(db, limit=limit)


@router.get("/stocktakes")
def stocktakes(db: Session = Depends(get_db), _: User = Depends(require_permission("reports.view"))):
    return rep.stocktake_report(db)
