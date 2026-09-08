"""v1.6 — Android companion: LAN pairing by QR + store-and-forward sync.

Design (agreed with the owner):
* The phone never needs the internet. The desktop shows a QR code (Settings →
  موبایل) carrying ``{url, token, store}``; the app scans it once and keeps the
  address + a long-lived *device token*.
* The link is not permanent. The phone works fully offline against its own
  cache; whenever it can reach the PC it calls ``/mobile/sync``: it pushes the
  operations it queued (sales, receipts, counts) and pulls everything that
  changed on the PC since its last ``cursor``. Both sides converge.

Endpoints (all under /api/mobile):
  GET  /pair/info       (settings.manage)  -> LAN addresses + QR payload + PNG
  POST /pair/token      (settings.manage)  -> mint a device token (name, days)
  GET  /devices         (settings.manage)  -> paired devices
  DELETE /devices/{id}  (settings.manage)  -> revoke
  POST /sync            (any user / device) -> {push:[...], cursor} -> {applied, pull, cursor}
"""
from __future__ import annotations

import base64
import io
import json
import secrets
import socket
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..models import Customer, Product, ProductBatch, SystemSetting, User
from ..security import create_access_token, get_current_user, require_permission
from ..services import sync as sync_svc
from ..services.audit import write_audit

router = APIRouter(prefix="/mobile", tags=["mobile"])

DEVICES_KEY = "mobile.devices"   # JSON list in system_settings


def _devices(db: Session) -> list[dict]:
    row = db.execute(select(SystemSetting).where(SystemSetting.key == DEVICES_KEY)).scalar_one_or_none()
    try:
        return json.loads(row.value) if row and row.value else []
    except ValueError:
        return []


def _save_devices(db: Session, items: list[dict]) -> None:
    row = db.execute(select(SystemSetting).where(SystemSetting.key == DEVICES_KEY)).scalar_one_or_none()
    val = json.dumps(items, ensure_ascii=False)
    if row is None:
        db.add(SystemSetting(key=DEVICES_KEY, value=val, is_secret=False, description="Paired Android devices"))
    else:
        row.value = val


def lan_addresses() -> list[str]:
    """Every private IPv4 this machine has (the phone must be on the same Wi-Fi)."""
    ips: list[str] = []
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        ips.append(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if ip not in ips and not ip.startswith("127."):
                ips.append(ip)
    except OSError:
        pass
    # v1.7: drop APIPA / link-local (169.254.x.x) — never reachable from a phone
    ips = [ip for ip in ips if not ip.startswith("169.254.")]
    return ips or ["127.0.0.1"]


def _server_port(request: Request) -> int:
    try:
        return int(request.url.port or settings.PORT)
    except (TypeError, ValueError):
        return settings.PORT


class TokenIn(BaseModel):
    name: str = Field(default="گوشی فروشگاه", max_length=60)
    days: int = Field(default=365, ge=1, le=3650)


def _mint(db: Session, user: User, name: str, days: int) -> dict:
    device_id = secrets.token_hex(6)
    exp = datetime.utcnow() + timedelta(days=days)
    token = create_access_token(str(user.id), extra={"device": device_id, "exp": exp, "kind": "mobile"})
    items = _devices(db)
    items.append({"id": device_id, "name": name, "user_id": user.id, "user": user.username,
                  "created_at": datetime.utcnow().isoformat(timespec="seconds"), "expires_at": exp.isoformat(timespec="seconds"),
                  "last_sync_at": None, "revoked": False})
    _save_devices(db, items)
    return {"device_id": device_id, "token": token, "expires_at": exp.isoformat(timespec="seconds")}


@router.get("/pair/info")
def pair_info(request: Request, db: Session = Depends(get_db), user: User = Depends(require_permission("settings.manage"))):
    """QR payload for the Android app + a PNG (data URL) so the desktop can show it."""
    port = _server_port(request)
    ips = lan_addresses()
    store = db.execute(select(SystemSetting).where(SystemSetting.key == "store.name")).scalar_one_or_none()
    minted = _mint(db, user, "گوشی (QR)", 365)
    write_audit(db, action="MOBILE_PAIR_TOKEN", user_id=user.id, entity_type="Mobile", reference=minted["device_id"])
    db.commit()
    payload = {"v": 2, "url": f"http://{ips[0]}:{port}", "urls": [f"http://{ip}:{port}" for ip in ips],
               "token": minted["token"], "store": (store.value if store else "") or "", "device_id": minted["device_id"]}
    # v1.7: when internet sync is on, the phone gets the same cloud mailbox
    from ..services import cloud as cloud_svc
    cloud = cloud_svc.credentials_for_device(db)
    if cloud:
        payload["cloud"] = cloud
    text = "SMKT:" + base64.urlsafe_b64encode(json.dumps(payload, ensure_ascii=False).encode()).decode()
    png = None
    try:
        import qrcode
        img = qrcode.make(text, box_size=6, border=2)
        buf = io.BytesIO(); img.save(buf, format="PNG")
        png = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
    except Exception:  # noqa: BLE001 — qrcode optional; the app also accepts manual entry
        png = None
    return {"addresses": ips, "port": port, "payload": payload, "qr_text": text, "qr_png": png,
            "mobile_url": f"http://{ips[0]}:{port}/mobile/"}


@router.post("/pair/token")
def pair_token(body: TokenIn, db: Session = Depends(get_db), user: User = Depends(require_permission("settings.manage"))):
    out = _mint(db, user, body.name, body.days)
    write_audit(db, action="MOBILE_PAIR_TOKEN", user_id=user.id, entity_type="Mobile", reference=out["device_id"])
    db.commit()
    return out


@router.get("/devices")
def devices(db: Session = Depends(get_db), _: User = Depends(require_permission("settings.manage"))):
    return [d for d in _devices(db) if not d.get("revoked")]


@router.delete("/devices/{device_id}")
def revoke(device_id: str, db: Session = Depends(get_db), user: User = Depends(require_permission("settings.manage"))):
    items = _devices(db)
    hit = False
    for d in items:
        if d["id"] == device_id:
            d["revoked"] = True; hit = True
    if not hit:
        raise HTTPException(status_code=404, detail="دستگاه یافت نشد")
    _save_devices(db, items)
    write_audit(db, action="MOBILE_DEVICE_REVOKED", user_id=user.id, entity_type="Mobile", reference=device_id)
    db.commit()
    return {"ok": True}


# --- sync ----------------------------------------------------------------------------
class SyncOp(BaseModel):
    id: str                       # client-generated idempotency key
    type: str                     # POS_CHECKOUT | STOCK_RECEIVE | STOCKTAKE_COUNT | CUSTOMER_CREATE
    payload: dict
    created_at: str | None = None


class SyncIn(BaseModel):
    device_id: str | None = None
    cursor: str | None = None     # ISO timestamp of the last successful pull
    push: list[SyncOp] = []
    pull: bool = True
    limit: int = Field(default=500, ge=1, le=2000)


def _apply(db: Session, user: User, op: SyncOp) -> dict:
    """Replay one offline operation through the SAME services the desktop uses."""
    from ..routers import batches as batches_router, customers as customers_router, inventory as inventory_router, pos as pos_router
    from ..security import has_permission
    kind = op.type.upper()
    need = {"POS_CHECKOUT": "pos.sell", "STOCK_RECEIVE": "batches.manage", "STOCKTAKE_COUNT": "inventory.stocktake",
            "CUSTOMER_CREATE": "pos.sell"}.get(kind)
    if need and not has_permission(user, need):
        return {"id": op.id, "status": "REJECTED", "error": f"دسترسی لازم نیست: {need}"}
    try:
        if kind == "POS_CHECKOUT":
            body = pos_router.CheckoutIn(**op.payload)
            res = pos_router.checkout(body, db=db, user=user)  # type: ignore[arg-type]
            return {"id": op.id, "status": "APPLIED", "result": {"invoice_number": getattr(res, "invoice_number", None) or (res.get("invoice_number") if isinstance(res, dict) else None)}}
        if kind == "STOCK_RECEIVE":
            body = batches_router.ReceiveIn(**op.payload)
            res = batches_router.receive(body, db=db, user=user)  # type: ignore[arg-type]
            return {"id": op.id, "status": "APPLIED", "result": {"batch_id": getattr(res, "id", None) or (res.get("id") if isinstance(res, dict) else None)}}
        if kind == "STOCKTAKE_COUNT":
            body = inventory_router.CountIn(**op.payload)
            inventory_router.count_item(body, db=db, user=user)  # type: ignore[arg-type]
            return {"id": op.id, "status": "APPLIED"}
        if kind == "CUSTOMER_CREATE":
            body = customers_router.CustomerIn(**op.payload)
            res = customers_router.create_customer(body, db=db, _=user)  # type: ignore[arg-type]
            return {"id": op.id, "status": "APPLIED", "result": {"customer_id": getattr(res, "id", None)}}
        if kind == "SUPPORT_TICKET":
            # v1.7: a support request written on the phone while the PC was unreachable
            from ..routers import support as support_router
            body = support_router.TicketIn(**op.payload)
            res = support_router.create_ticket(body, db=db, user=user)  # type: ignore[arg-type]
            return {"id": op.id, "status": "APPLIED", "result": {"number": res.get("number") if isinstance(res, dict) else getattr(res, "number", None)}}
        return {"id": op.id, "status": "REJECTED", "error": f"نوع عملیات ناشناخته: {op.type}"}
    except HTTPException as exc:
        db.rollback()
        return {"id": op.id, "status": "REJECTED", "error": str(exc.detail)}
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        return {"id": op.id, "status": "REJECTED", "error": f"{type(exc).__name__}: {exc}"}


def _changed_since(db: Session, model, since: datetime | None, limit: int):
    stmt = select(model)
    if since is not None:
        stmt = stmt.where(model.updated_at >= since)
    return db.execute(stmt.order_by(model.updated_at.asc()).limit(limit)).scalars().all()


@router.post("/sync")
def sync(body: SyncIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Store-and-forward sync. Push is idempotent (same op id → applied once,
    tracked in sync_jobs); pull returns rows changed since ``cursor``."""
    applied: list[dict] = []
    for op in body.push:
        existing = db.execute(select(sync_svc.SyncJob).where(sync_svc.SyncJob.idempotency_key == f"mob:{op.id}")).scalar_one_or_none()
        if existing is not None:
            applied.append({"id": op.id, "status": "DUPLICATE", "result": json.loads(existing.last_error or "null")})
            continue
        res = _apply(db, user, op)
        job = sync_svc.SyncJob(job_type=f"MOBILE_{op.type.upper()}", payload=json.dumps(op.payload, ensure_ascii=False, default=str),
                               status="COMPLETED" if res["status"] == "APPLIED" else "FAILED", attempts=1, max_attempts=1,
                               idempotency_key=f"mob:{op.id}", reference_type="MobileDevice", created_by=user.id,
                               last_error=json.dumps(res.get("result") or res.get("error"), ensure_ascii=False),
                               completed_at=datetime.utcnow())
        db.add(job)
        db.commit()
        applied.append(res)

    since = None
    if body.cursor:
        try:
            since = datetime.fromisoformat(body.cursor)
        except ValueError:
            since = None
    now = datetime.utcnow().isoformat(timespec="seconds")
    pull: dict = {}
    if body.pull:
        prods = _changed_since(db, Product, since, body.limit)
        pull["products"] = [{"id": p.id, "name": p.name, "sku": p.sku, "barcode": p.barcode, "unit_id": p.unit_id,
                             "category_id": p.category_id, "is_active": p.is_active, "image_url": getattr(p, "image_url", None),
                             "updated_at": p.updated_at.isoformat()} for p in prods]
        batches = _changed_since(db, ProductBatch, since, body.limit)
        pull["batches"] = [{"id": b.id, "product_id": b.product_id, "batch_number": b.batch_number, "expiry_date": b.expiry_date.isoformat() if b.expiry_date else None,
                            "current_qty": float(b.current_qty or 0), "unit_sell_price": float(b.sell_price or 0), "status": b.status,
                            "updated_at": b.updated_at.isoformat()} for b in batches]
        custs = _changed_since(db, Customer, since, body.limit)
        pull["customers"] = [{"id": c.id, "name": c.name, "phone": c.phone, "updated_at": c.updated_at.isoformat()} for c in custs]
    # remember the device
    if body.device_id:
        items = _devices(db)
        for d in items:
            if d["id"] == body.device_id:
                d["last_sync_at"] = now
        _save_devices(db, items)
    write_audit(db, action="MOBILE_SYNC", user_id=user.id, entity_type="Mobile", reference=body.device_id,
                after={"pushed": len(body.push), "applied": sum(1 for a in applied if a["status"] == "APPLIED"),
                       "pulled": {k: len(v) for k, v in pull.items()}})
    db.commit()
    return {"applied": applied, "pull": pull, "cursor": now, "server_time": now}
