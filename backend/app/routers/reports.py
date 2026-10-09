from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import User
from ..security import get_current_user, has_permission, require_any_permission, require_permission
from ..services import reports as rep
from ..services.reports import dashboard_profile  # noqa: F401 — تک‌منبع منطق در services

router = APIRouter(prefix="/reports", tags=["reports"])


def _require_stock_report_access(user: User = Depends(get_current_user)) -> User:
    """Stock reports require report scope as well as inventory visibility.

    A storewide-report grant is sufficient on its own; otherwise the caller
    must hold both reports.view and inventory.view. Inventory visibility alone
    never grants access to the Reports area.
    """
    if has_permission(user, "reports.view_all") or (
        has_permission(user, "reports.view") and has_permission(user, "inventory.view")
    ):
        return user
    raise HTTPException(status_code=403, detail="Stock reports require reports.view and inventory.view, or reports.view_all")


def _maybe_redact(user: User, payload):
    """Redact inventory cost/margin data without conflating accounting access.

    ``accounting.view`` and ``pricing.view_cost`` are independent capabilities:
    the former permits the financial ledger summary, while the latter exposes
    product costs and margin analytics. ``rep.redact_costs`` is deliberately
    conservative for callers without user context, so restore the dashboard's
    accounting block only after checking the separate accounting permission.
    """
    if has_permission(user, "pricing.view_cost"):
        return payload
    redacted = rep.redact_costs(payload)
    if has_permission(user, "accounting.view") and isinstance(payload, dict) and "accounting" in payload:
        redacted["accounting"] = payload["accounting"]
    return redacted


_SELF_ONLY_BLOCKS = ("receivables", "top_products", "sales_by_category",
                     "customers_new", "expiry", "pricing")


@router.get("/dashboard")
def dashboard(db: Session = Depends(get_db), user: User = Depends(require_permission("reports.view"))):
    # build-490 (§۲–۳/§۷) — زنجیرهٔ واقعی Role → Permission → Data Scope:
    # «کل فروشگاه» فقط با reports.view_all؛ فروشنده/صندوق‌دار فقط دادهٔ خودش؛ بدون آن دامنهٔ خالی.
    # اطلاعات حساس (بدهکاران، مالی، عملکرد دیگران) اصلاً به کلاینت نمی‌رود — نه اینکه در UI مخفی شود.
    if has_permission(user, "reports.view_all"):
        scope = "store"
    elif has_permission(user, "pos.sell"):
        scope = "self"
    else:
        scope = "none"
    # A None user_id means store-wide data in the service layer. For the no-scope
    # case, use a non-existent id instead so every user-attributed sales query is
    # empty rather than accidentally widening to the whole store.
    uid = user.id if scope == "self" else (None if scope == "store" else -1)
    payload = rep.dashboard(db, user_id=uid)
    payload["scope"] = scope
    payload["dashboard_profile"] = dashboard_profile(user)
    if scope != "store":
        for k in _SELF_ONLY_BLOCKS:
            payload[k] = [] if isinstance(payload.get(k), list) else {}
        # Sales scope and inventory scope are independent. A cashier may see the
        # stock figures their inventory.view permission authorizes, without gaining
        # store-wide sales, customer, or staff reporting.
        if not has_permission(user, "inventory.view"):
            payload["inventory"] = {"value": 0, "product_count": 0, "low_stock": [],
                                    "no_stock": [], "low_stock_count": 0, "no_stock_count": 0}
    # Cost visibility and accounting visibility are independent capabilities:
    # inventory operators may inspect costs without opening the general ledger.
    if not has_permission(user, "accounting.view"):
        payload["accounting"] = None
    return _maybe_redact(user, payload)


@router.get("/sales")
def sales(start: date, end: date, group: str = "daily", db: Session = Depends(get_db),
          user: User = Depends(require_permission("reports.view"))):
    """group: daily | weekly | monthly (Jalali buckets) | product (§49, §137)."""
    # build-490 — دامنهٔ شخصی: بدون reports.view_all فقط فروش‌های خودِ کاربر (نه آمار کل فروشگاه)
    uid = None if has_permission(user, "reports.view_all") else user.id
    return _maybe_redact(user, rep.sales_report(db, start, end, group, user_id=uid))


@router.get("/cashiers")
def cashiers(start: date | None = None, end: date | None = None, db: Session = Depends(get_db),
             _: User = Depends(require_permission("reports.view_all"))):
    # build-490 (§۲/§۷) — گزارش تفکیکی صندوق‌داران = دادهٔ عملکرد کارکنان؛ فقط گزارش کل فروشگاه
    return _maybe_redact(_, rep.cashier_report(db, start, end))


@router.get("/inventory")
def inventory(limit: int | None = Query(default=None, ge=1, le=5000),
              db: Session = Depends(get_db),
              user: User = Depends(_require_stock_report_access)):
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
           db: Session = Depends(get_db),
           user: User = Depends(_require_stock_report_access)):
    # v3.5.9 — capped per bucket, same reason as /inventory. Desktop unaffected by default.
    out = rep.expiry_report(db)
    if limit and isinstance(out, dict):
        out = {k: (v[:limit] if isinstance(v, list) else v) for k, v in out.items()}
    return _maybe_redact(user, out)


@router.get("/adjustments")
def adjustments(limit: int = Query(default=200, le=1000), db: Session = Depends(get_db),
                _: User = Depends(_require_stock_report_access)):
    return rep.adjustments_report(db, limit=limit)


@router.get("/profit")
def profit(start: date | None = None, end: date | None = None,
           limit: int | None = Query(default=None, ge=1, le=5000),
           db: Session = Depends(get_db),
           # v3.7 (§34) — this endpoint IS cost analysis; redaction would leave
           # an empty shell, so it requires the cost permission outright.
           _: User = Depends(require_permission("pricing.view_cost"))):
    # v1.0.0 (RASA) — ``limit`` اختیاری (مثل /inventory): روی فروشگاه یک‌ساله این
    # گزارش ۳۲۶۴ ردیف/۲۵۵KB است و رابط، همه را در DOM می‌ساخت و صفحه را قفل می‌کرد.
    rows = rep.profit_by_batch(db, start, end)
    return rows[:limit] if limit else rows


@router.get("/batches")
def batches(db: Session = Depends(get_db),
           _: User = Depends(_require_stock_report_access)):
    return rep.batch_status_report(db)


@router.get("/low-stock")
def low_stock(limit: int | None = Query(default=None, ge=1, le=5000),
              db: Session = Depends(get_db),
              _: User = Depends(_require_stock_report_access)):
    # v3.5.9 — most of a 13k-SKU store sits at zero stock, so "no stock" alone can be
    # thousands of rows. Desktop unaffected by default.
    rows = rep.low_stock_report(db)
    return rows[:limit] if limit else rows


@router.get("/movements")
def movements(limit: int = 200, db: Session = Depends(get_db),
              _: User = Depends(_require_stock_report_access)):
    return rep.movements_report(db, limit=limit)


@router.get("/stocktakes")
def stocktakes(db: Session = Depends(get_db),
               _: User = Depends(_require_stock_report_access)):
    return rep.stocktake_report(db)
