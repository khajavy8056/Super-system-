from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends
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
    return rep.sales_report(db, start, end, group)


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
