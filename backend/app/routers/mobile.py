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
from ..services import relay_client as relay_svc
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
    import os
    if os.environ.get("PORT", "").isdigit():
        return int(os.environ["PORT"])  # v2.3: the launcher's real listening port
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
               "token": minted["token"], "store": (store.value if store else "") or "", "device_id": minted["device_id"],
               "link_key": link_key(db), "port": port}
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


# --- v2.1: short pairing code + LAN discovery (stable link when IPs change) ------------
PAIR_CODES_KEY = "mobile.pair_codes"   # JSON list [{code, token, device_id, store, expires}]
LINK_KEY_SETTING = "mobile.link_key"    # stable per-install secret the phone uses to re-find the PC


def link_key(db: Session) -> str:
    """Stable 12-char key of THIS installation. The phone keeps it after pairing
    and the LAN beacon (UDP) answers only to it — so when the PC's IP changes
    the phone still finds the right PC (and never a neighbour's)."""
    row = db.execute(select(SystemSetting).where(SystemSetting.key == LINK_KEY_SETTING)).scalar_one_or_none()
    if row and row.value:
        return row.value
    key = secrets.token_hex(6).upper()
    db.add(SystemSetting(key=LINK_KEY_SETTING, value=key, is_secret=True, description="Mobile link key"))
    db.commit()
    return key


def _pair_codes(db: Session) -> list[dict]:
    row = db.execute(select(SystemSetting).where(SystemSetting.key == PAIR_CODES_KEY)).scalar_one_or_none()
    try:
        items = json.loads(row.value) if row and row.value else []
    except ValueError:
        items = []
    now = datetime.utcnow().isoformat(timespec="seconds")
    return [c for c in items if c.get("expires", "") > now]


def _save_pair_codes(db: Session, items: list[dict]) -> None:
    row = db.execute(select(SystemSetting).where(SystemSetting.key == PAIR_CODES_KEY)).scalar_one_or_none()
    val = json.dumps(items, ensure_ascii=False)
    if row is None:
        db.add(SystemSetting(key=PAIR_CODES_KEY, value=val, is_secret=True, description="Mobile pairing codes"))
    else:
        row.value = val


def _link_payload(db: Session, request: Request, minted: dict) -> dict:
    port = _server_port(request)
    ips = lan_addresses()
    store = db.execute(select(SystemSetting).where(SystemSetting.key == "store.name")).scalar_one_or_none()
    payload = {"v": 3, "url": f"http://{ips[0]}:{port}", "urls": [f"http://{ip}:{port}" for ip in ips],
               "token": minted["token"], "store": (store.value if store else "") or "", "device_id": minted["device_id"],
               "link_key": link_key(db), "port": port}
    from ..services import cloud as cloud_svc
    cloud = cloud_svc.credentials_for_device(db)
    if cloud:
        payload["cloud"] = cloud
    from ..services import relay_client as relay_svc
    relay = relay_svc.for_device(db)
    if relay:
        payload["relay"] = relay  # v2.3: phones can reach this PC from any network
    return payload


@router.post("/pair/code")
def pair_code(request: Request, db: Session = Depends(get_db), user: User = Depends(require_permission("settings.manage"))):
    """v2.1 — a 6-digit code typed into the phone instead of scanning (valid 10 min,
    single use). The phone posts it to /pair/claim from the same Wi-Fi."""
    minted = _mint(db, user, "گوشی (کد)", 365)
    codes = _pair_codes(db)
    code = "".join(secrets.choice("0123456789") for _ in range(6))
    while any(c["code"] == code for c in codes):
        code = "".join(secrets.choice("0123456789") for _ in range(6))
    payload = _link_payload(db, request, minted)
    codes.append({"code": code, "payload": payload, "expires": (datetime.utcnow() + timedelta(minutes=10)).isoformat(timespec="seconds")})
    _save_pair_codes(db, codes)
    write_audit(db, action="MOBILE_PAIR_CODE", user_id=user.id, entity_type="Mobile", reference=minted["device_id"])
    db.commit()
    return {"code": code, "expires_in": 600, "addresses": payload["urls"], "link_key": payload["link_key"]}


class ClaimIn(BaseModel):
    code: str = Field(min_length=6, max_length=6)


@router.post("/pair/claim")
def pair_claim(body: ClaimIn, db: Session = Depends(get_db)):
    """Public (LAN only in practice): exchange a fresh 6-digit code for the pairing payload."""
    codes = _pair_codes(db)
    hit = next((c for c in codes if c["code"] == body.code.strip()), None)
    if hit is None:
        raise HTTPException(status_code=404, detail={"code": "PAIR_CODE_INVALID", "message": "کد نادرست است یا منقضی شده؛ در رایانه کد جدید بسازید"})
    _save_pair_codes(db, [c for c in codes if c is not hit])
    db.commit()
    return hit["payload"]


@router.get("/link")
def link_info(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """v2.1 — what a paired phone needs to keep the link alive: the install's link
    key (for LAN rediscovery) and the PC licence verdict (phone locks with it)."""
    from ..services import license as lic
    st = lic.state(db)
    store = db.execute(select(SystemSetting).where(SystemSetting.key == "store.name")).scalar_one_or_none()
    from ..services import cloud as cloud_svc
    return {"link_key": link_key(db), "store": (store.value if store else "") or "",
            "license": {k: st.get(k) for k in ("allowed", "reason", "status", "expires", "days_left", "activated")},
            "cloud": cloud_svc.credentials_for_device(db),
            "relay": relay_svc.for_device(db),
            "lan": [f"http://{ip}:{_port_env()}" for ip in lan_addresses()]}


def _port_env() -> int:
    import os
    return int(os.environ.get("PORT", settings.PORT) or settings.PORT)


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
            "CUSTOMER_CREATE": "pos.sell", "PRODUCT_CREATE": "products.manage"}.get(kind)
    if need and not has_permission(user, need):
        return {"id": op.id, "status": "REJECTED", "error": f"دسترسی لازم نیست: {need}"}
    try:
        if kind == "PRODUCT_CREATE":
            # v1.8.1: product defined on the phone while offline; same barcode already there → reuse (idempotent)
            from ..routers import products as products_router
            from ..services import catalog
            bc = (op.payload.get("barcode") or "").strip()
            existing = catalog.get_product_by_barcode(db, bc) if bc and not bc.startswith("INT-L") else None
            if existing is not None:
                return {"id": op.id, "status": "APPLIED", "result": {"product_id": existing.id, "reused": True}}
            payload = dict(op.payload)
            if bc.startswith("INT-L"):
                payload["barcode"] = None  # phone-side temporary code → let the PC mint a real INT- code
            body = products_router.ProductIn(**{k: v for k, v in payload.items() if k in products_router.ProductIn.model_fields})
            res = products_router.create_product(body, db=db, user=user)  # type: ignore[arg-type]
            return {"id": op.id, "status": "APPLIED", "result": {"product_id": res.get("id") if isinstance(res, dict) else getattr(res, "id", None)}}
        if kind == "POS_CHECKOUT":
            # lines sold offline may carry only a barcode (product created on the phone) → resolve here
            items = []
            for it in op.payload.get("items", []):
                it = dict(it)
                if not it.get("product_id") and it.get("barcode"):
                    from ..services import catalog
                    prod = catalog.get_product_by_barcode(db, it["barcode"])
                    if prod is None:
                        return {"id": op.id, "status": "REJECTED", "error": f"کالای {it['barcode']} روی رایانه یافت نشد"}
                    it["product_id"] = prod.id
                it.pop("barcode", None)
                if not it.get("batch_id"):
                    it.pop("batch_id", None)
                items.append(it)
            body = pos_router.CheckoutIn(**{**op.payload, "items": items})
            adjusted = None
            try:
                res = pos_router.checkout(body, db=db, user=user)  # type: ignore[arg-type]
            except HTTPException as exc:
                # v2.0: the phone priced the sale with the catalogue it had at the time; if the PC's
                # price/tax differs, keep the sale (money already changed hands) by re-tendering the
                # PC total on the last payment line and report the delta so the phone can show it.
                det = exc.detail if isinstance(exc.detail, dict) else {}
                if det.get("code") != "PAYMENT_MISMATCH" or not body.payments:
                    raise
                db.rollback()
                import re as _re
                m = _re.search(r"total is ([0-9.]+)", str(det.get("message", "")))
                if not m:
                    raise
                from decimal import Decimal as _D
                server_total = _D(m.group(1))
                paid = sum((_D(str(p.amount)) for p in body.payments), _D("0"))
                pays = [p.model_copy() for p in body.payments]
                pays[-1].amount = max(_D("0"), _D(str(pays[-1].amount)) + (server_total - paid))
                body = body.model_copy(update={"payments": pays})
                res = pos_router.checkout(body, db=db, user=user)  # type: ignore[arg-type]
                adjusted = {"phone_total": float(paid), "pc_total": float(server_total)}
            out = {"invoice_number": getattr(res, "invoice_number", None) or (res.get("invoice_number") if isinstance(res, dict) else None)}
            if adjusted:
                out["adjusted"] = adjusted
            return {"id": op.id, "status": "APPLIED", "result": out}
        if kind == "STOCK_RECEIVE":
            body = batches_router.ReceiveIn(**op.payload)
            res = batches_router.receive(body, db=db, user=user)  # type: ignore[arg-type]
            return {"id": op.id, "status": "APPLIED", "result": {"batch_id": getattr(res, "id", None) or (res.get("id") if isinstance(res, dict) else None)}}
        if kind == "PRODUCT_IMAGE_FIND":
            # v2.5 — a phone found/asked for a picture; the PC looks it up in the background too (so Windows + other phones get it)
            from ..services import product_images as _pi
            pid = int(op.payload.get("product_id") or 0)
            if pid > 0:
                _pi.enqueue(db, pid, user_id=user.id)
            return {"id": op.id, "status": "APPLIED", "result": {"queued": pid > 0}}
        if kind == "STOCKTAKE_COUNT":
            body = inventory_router.CountIn(**op.payload)
            inventory_router.count_item(body, db=db, user=user)  # type: ignore[arg-type]
            return {"id": op.id, "status": "APPLIED"}
        if kind == "CUSTOMER_CREATE":
            body = customers_router.CustomerIn(**op.payload)
            res = customers_router.create_customer(body, db=db, _=user)  # type: ignore[arg-type]
            return {"id": op.id, "status": "APPLIED", "result": {"customer_id": res.get("id") if isinstance(res, dict) else getattr(res, "id", None)}}
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
                             "category_id": p.category_id, "brand_id": p.brand_id, "is_active": p.is_active, "image_url": getattr(p, "image_url", None),
                             "min_stock_alert": p.min_stock_alert, "has_own_barcode": getattr(p, "has_own_barcode", True),
                             "updated_at": p.updated_at.isoformat()} for p in prods]
        batches = _changed_since(db, ProductBatch, since, body.limit)
        pull["batches"] = [{"id": b.id, "product_id": b.product_id, "batch_number": b.batch_number, "expiry_date": b.expiry_date.isoformat() if b.expiry_date else None,
                            "current_qty": float(b.current_qty or 0), "unit_sell_price": float(b.sell_price or 0), "sell_price": float(b.sell_price or 0),
                            "consumer_price": float(b.consumer_price or 0), "buy_price": float(b.buy_price or 0), "status": b.status,
                            "updated_at": b.updated_at.isoformat()} for b in batches]
        custs = _changed_since(db, Customer, since, body.limit)
        pull["customers"] = [{"id": c.id, "name": c.name, "last_name": c.last_name, "phone": c.phone, "credit_limit": float(c.credit_limit or 0),
                              "updated_at": c.updated_at.isoformat()} for c in custs]
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
