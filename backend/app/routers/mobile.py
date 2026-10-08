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
import hashlib
import io
import json
import logging
import secrets
import socket
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..models import Campaign, CampaignRedemption, Coupon, Customer, Product, ProductBatch, SystemSetting, User
from ..security import create_access_token, get_current_user, has_permission, require_permission
from ..services import relay_client as relay_svc
from ..services import sync as sync_svc
from ..services.audit import write_audit
from ..services.reports import redact_costs

router = APIRouter(prefix="/mobile", tags=["mobile"])
log = logging.getLogger("supermarket.mobile")

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
    #: v3.5.11 — a phone that is already paired sends the id it holds, so signing in again
    #: refreshes that row instead of adding yet another "device" to the list.
    device_id: str | None = Field(default=None, max_length=64)


def _mint(db: Session, user: User, name: str, days: int, device_id: str | None = None) -> dict:
    """Mint a device token.

    v3.5.11 — ``device_id`` lets a caller reuse an identity it already has. The phone used to
    call this on *every* sign-in and got a fresh random id back each time, so the paired-device
    list grew by one row per idle-lock re-login and the phone's licence identity moved with it.
    Reusing the row keeps the list honest and the identity fixed.
    """
    did = (device_id or "").strip()[:64] or secrets.token_hex(6)
    exp = datetime.utcnow() + timedelta(days=days)
    token = create_access_token(str(user.id), extra={"device": did, "exp": exp, "kind": "mobile"})
    items = _devices(db)
    for it in items:
        if it.get("id") == did:
            # Same phone again: refresh its name/owner/expiry. ``revoked`` is deliberately left
            # alone — authenticating must not undo a revocation the shop's admin made on purpose.
            it.update({"name": name, "user_id": user.id, "user": user.username,
                       "expires_at": exp.isoformat(timespec="seconds")})
            break
    else:
        items.append({"id": did, "name": name, "user_id": user.id, "user": user.username,
                      "created_at": datetime.utcnow().isoformat(timespec="seconds"), "expires_at": exp.isoformat(timespec="seconds"),
                      "last_sync_at": None, "revoked": False})
    _save_devices(db, items)
    return {"device_id": did, "token": token, "expires_at": exp.isoformat(timespec="seconds")}


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
def pair_token(body: TokenIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Mint (or re-mint) a device token.

    v4.8.1 / build-492 — pairing is PERMANENT. A phone that already paired once
    can re-mint a token bound to the currently signed-in user for its known
    ``device_id``; introducing a brand-new ``device_id`` requires ``settings.manage``.
    """
    from ..security import is_admin as _is_admin
    did = (body.device_id or "").strip()
    devs = _devices(db)
    if did and any(d.get("id") == did and d.get("revoked") for d in devs):
        raise HTTPException(status_code=403, detail={
            "code": "DEVICE_REVOKED", "message": "این دستگاه توسط مدیر غیرفعال شده است"})
    known = any(d.get("id") == did and did for d in devs)
    if not known and not has_permission(user, "settings.manage") and not _is_admin(user):
        raise HTTPException(status_code=403, detail={
            "code": "DEVICE_NEW_FORBIDDEN", "message": "افزودن دستگاه تازه فقط با دسترسی مدیر انجام می‌شود"})
    out = _mint(db, user, body.name, body.days, device_id=body.device_id)
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
    from ..routers import batches as batches_router, customers as customers_router, hr as hr_router, inventory as inventory_router, pos as pos_router
    from ..security import has_permission
    kind = op.type.upper()
    need = {"POS_CHECKOUT": "pos.sell", "STOCK_RECEIVE": "batches.manage", "STOCKTAKE_COUNT": "inventory.stocktake",
            "CUSTOMER_CREATE": "pos.sell", "PRODUCT_CREATE": "products.manage",
            "SHIFT_CREATE": "shifts.manage", "SHIFT_UPDATE": "shifts.manage",
            "SHIFT_ASSIGN": "shifts.manage", "SHIFT_UNASSIGN": "shifts.manage", "SHIFT_MOVE": "shifts.manage",
            "PAYROLL_CREATE": "payroll.manage", "PAYROLL_UPDATE": "payroll.manage",
            "PAYROLL_APPROVE": "payroll.manage", "PAYROLL_PAY": "payroll.manage",
            "ANNOUNCEMENT_CREATE": "announcements.publish"}.get(kind)
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
        if kind == "BANK_REMEMBER":
            # v2.7 — a phone identified a barcode online (or the operator confirmed a name): teach the PC bank
            from ..services import product_bank as _bank
            pl = op.payload
            res = _bank.remember(db, str(pl.get("barcode") or ""), str(pl.get("name") or ""), brand=pl.get("brand"),
                                 unit=pl.get("unit"), category=pl.get("category"), image_url=pl.get("image_url"),
                                 source="USER" if pl.get("source") == "USER" else "ONLINE")
            db.commit()
            return {"id": op.id, "status": "APPLIED", "result": {"stored": res is not None}}
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
        if kind == "SHIFT_CREATE":
            payload = dict(op.payload)
            shift_body = hr_router.ShiftIn(**{k: v for k, v in payload.items() if k in hr_router.ShiftIn.model_fields})
            res = hr_router.create_shift(shift_body, db=db, user=user)  # type: ignore[arg-type]
            shift_id = res.get("id") if isinstance(res, dict) else getattr(res, "id", None)
            return {"id": op.id, "status": "APPLIED", "result": {"shift_id": shift_id, "id": shift_id}}
        if kind == "SHIFT_UPDATE":
            payload = dict(op.payload); shift_id = int(payload.get("shift_id") or 0)
            patch = hr_router.ShiftPatch(**{k: v for k, v in payload.items() if k in hr_router.ShiftPatch.model_fields})
            res = hr_router.update_shift(shift_id, patch, db=db, user=user)  # type: ignore[arg-type]
            return {"id": op.id, "status": "APPLIED", "result": {"shift_id": res.get("id") if isinstance(res, dict) else getattr(res, "id", shift_id)}}
        if kind == "SHIFT_ASSIGN":
            payload = dict(op.payload); shift_id = int(payload.get("shift_id") or 0)
            assign_body = hr_router.AssignIn(**{k: v for k, v in payload.items() if k in hr_router.AssignIn.model_fields})
            res = hr_router.assign_shift(shift_id, assign_body, db=db, user=user)  # type: ignore[arg-type]
            return {"id": op.id, "status": "APPLIED", "result": {"assignment_id": res.get("assignment_id"), "shift_id": shift_id}}
        if kind == "SHIFT_UNASSIGN":
            assignment_id = int(op.payload.get("assignment_id") or 0)
            res = hr_router.unassign_shift(assignment_id, db=db, user=user)  # type: ignore[arg-type]
            return {"id": op.id, "status": "APPLIED", "result": {"assignment_id": assignment_id, "ok": res.get("ok", True)}}
        if kind == "SHIFT_MOVE":
            assignment_id = int(op.payload.get("assignment_id") or 0)
            move_body = hr_router.MoveIn(**{k: v for k, v in op.payload.items() if k in hr_router.MoveIn.model_fields})
            res = hr_router.move_shift(assignment_id, move_body, db=db, user=user)  # type: ignore[arg-type]
            return {"id": op.id, "status": "APPLIED", "result": {"assignment_id": res.get("assignment_id"), "shift_id": res.get("shift_id")}}
        if kind in ("ATTENDANCE_CLOCK_IN", "ATTENDANCE_CLOCK_OUT"):
            from ..services import shifts as shift_svc
            from datetime import datetime as _dt
            day = str(op.payload.get("day") or "") or None
            raw_at = op.payload.get("started_at" if kind == "ATTENDANCE_CLOCK_IN" else "ended_at")
            at = _dt.fromisoformat(str(raw_at)) if raw_at else None
            if kind == "ATTENDANCE_CLOCK_IN":
                if shift_svc.has_attendance(db, user, day):
                    return {"id": op.id, "status": "REJECTED", "error": "حضور این روز روی رایانه یا دستگاه دیگری قبلاً ثبت شده است"}
                shift_id = int(op.payload.get("shift_id") or 0) or None
                row = shift_svc.clock_in(db, user, shift_id=shift_id, day=day, at=at)
            else:
                row = shift_svc.clock_out(db, user, day=day, at=at)
            db.commit()
            return {"id": op.id, "status": "APPLIED", "result": {"attendance_id": row.id, "id": row.id}}
        if kind.startswith("ANNOUNCEMENT_"):
            from ..models import Announcement
            from ..services import announcements as ann_svc
            ann_id = int(op.payload.get("announcement_id") or 0)
            if kind == "ANNOUNCEMENT_CREATE":
                payload = dict(op.payload)
                ann_body = hr_router.AnnouncementIn(**{k: v for k, v in payload.items() if k in hr_router.AnnouncementIn.model_fields})
                res = hr_router.create_announcement(ann_body, db=db, user=user)  # type: ignore[arg-type]
                remote_id = res.get("id") if isinstance(res, dict) else getattr(res, "id", None)
                return {"id": op.id, "status": "APPLIED", "result": {"announcement_id": remote_id, "id": remote_id}}
            announcement = db.get(Announcement, ann_id)
            if announcement is None:
                raise HTTPException(status_code=404, detail="ANNOUNCEMENT_NOT_FOUND")
            if kind == "ANNOUNCEMENT_READ":
                ann_svc.mark_read(db, announcement, user); db.commit()
                return {"id": op.id, "status": "APPLIED", "result": {"announcement_id": ann_id}}
            if kind == "ANNOUNCEMENT_SEEN":
                ann_svc.mark_seen(db, announcement, user); db.commit()
                return {"id": op.id, "status": "APPLIED", "result": {"announcement_id": ann_id}}
            if kind == "ANNOUNCEMENT_CANCEL":
                res = hr_router.cancel_announcement(ann_id, db=db, user=user)  # type: ignore[arg-type]
                return {"id": op.id, "status": "APPLIED", "result": {"announcement_id": ann_id, "ok": res.get("ok", True)}}
        if kind.startswith("PAYROLL_"):
            payload = dict(op.payload)
            payroll_id = int(payload.get("payroll_id") or 0)
            if kind == "PAYROLL_CREATE":
                payroll_body = hr_router.PayrollIn(**{k: v for k, v in payload.items() if k in hr_router.PayrollIn.model_fields})
                res = hr_router.create_payroll(payroll_body, db=db, user=user)  # type: ignore[arg-type]
                remote_id = res.get("id") if isinstance(res, dict) else getattr(res, "id", None)
                return {"id": op.id, "status": "APPLIED", "result": {"payroll_id": remote_id, "id": remote_id}}
            if kind == "PAYROLL_UPDATE":
                patch = hr_router.PayrollPatch(**{k: v for k, v in payload.items() if k in hr_router.PayrollPatch.model_fields})
                res = hr_router.update_payroll(payroll_id, patch, db=db, user=user)  # type: ignore[arg-type]
                return {"id": op.id, "status": "APPLIED", "result": {"payroll_id": res.get("id") if isinstance(res, dict) else payroll_id}}
            if kind == "PAYROLL_APPROVE":
                res = hr_router.approve_payroll(payroll_id, db=db, user=user)  # type: ignore[arg-type]
                return {"id": op.id, "status": "APPLIED", "result": {"payroll_id": res.get("id") if isinstance(res, dict) else payroll_id}}
            if kind == "PAYROLL_PAY":
                res = hr_router.pay_payroll(payroll_id, db=db, user=user)  # type: ignore[arg-type]
                return {"id": op.id, "status": "APPLIED", "result": {"payroll_id": res.get("id") if isinstance(res, dict) else payroll_id}}
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


def _pull_cursor(pull: dict, fallback: str, limit: int) -> tuple[str, bool]:
    """v3.5 — the sync cursor must advance to the last row actually delivered.

    It used to be ``now``. That was invisible while the catalogue was a few
    hundred lines: one pull covered everything. With the 13 570-line default bank
    it silently broke the phones — the first pull returned the 500 OLDEST
    products and then handed back ``cursor = now``, so the next pull asked for
    "everything changed since now" and the remaining 13 000 lines were never
    delivered. A paired phone would sit on 500 products forever.

    The cursor is now the newest ``updated_at`` in the page, so the next pull
    continues exactly where this one stopped. ``>=`` (not ``>``) is used on the
    way back in, which re-sends the boundary row; that is harmless because the
    phone upserts by id, and it can never skip a row that shares a timestamp.

    ``has_more`` tells the client to pull again immediately instead of waiting
    for the next scheduled sync — a fresh install needs ~28 rounds to receive the
    whole bank at the default page size of 500.
    """
    per_table_newest: list[datetime] = []
    truncated_newest: list[datetime] = []
    # These compact roster snapshots have no independent monotonic update clock;
    # they are intentionally re-sent in full and must not pin the shared cursor.
    snapshot_tables = {"roster_users", "shift_assignments", "attendance"}
    for table, rows in pull.items():
        if table in snapshot_tables or not isinstance(rows, list) or not rows:
            continue
        newest: datetime | None = None
        for r in rows:
            ts = r.get("updated_at") if isinstance(r, dict) else getattr(r, "updated_at", None)
            if isinstance(ts, str):
                try:
                    ts = datetime.fromisoformat(ts)
                except ValueError:
                    ts = None
            if ts is not None and (newest is None or ts > newest):
                newest = ts
        if newest is None:
            continue
        per_table_newest.append(newest)
        # Only a table whose page came back FULL still has rows to deliver. An
        # exhausted (short) table must not hold the cursor back, or the client
        # would re-request the same page forever.
        if len(rows) >= limit:
            truncated_newest.append(newest)
    if not per_table_newest:
        return fallback, False
    if not truncated_newest:
        # every table fit in one page — the client is caught up
        return max(per_table_newest).isoformat(), False
    # ONE cursor covers several independently-paginated tables, so it may only
    # advance as far as the SLOWEST table that is still truncated. Taking the
    # global newest would let a finished table drag the cursor past rows another
    # table has not delivered yet, skipping them for good.
    return min(truncated_newest).isoformat(), True


@router.post("/sync")
def sync(body: SyncIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Store-and-forward sync. Push is idempotent (same op id → applied once,
    tracked in sync_jobs); pull returns rows changed since ``cursor``."""
    applied: list[dict] = []
    for op in body.push:
        # Idempotency results are user-scoped: a guessed/reused operation UUID
        # must never reveal another account's prior invoice/result. Look up the
        # legacy v492 key only when its recorded creator is this same user.
        legacy_key = f"mob:{op.id}"
        digest = hashlib.sha256(op.id.encode("utf-8")).hexdigest()[:64]
        idempotency_key = f"mob:{user.id}:{digest}"
        existing = db.execute(select(sync_svc.SyncJob).where(sync_svc.SyncJob.idempotency_key == idempotency_key)).scalar_one_or_none()
        if existing is None:
            existing = db.execute(select(sync_svc.SyncJob).where(
                sync_svc.SyncJob.idempotency_key == legacy_key,
                sync_svc.SyncJob.created_by == user.id,
            )).scalar_one_or_none()
        if existing is not None:
            applied.append({"id": op.id, "status": "DUPLICATE", "result": json.loads(existing.last_error or "null")})
            continue
        res = _apply(db, user, op)
        job = sync_svc.SyncJob(job_type=f"MOBILE_{op.type.upper()}", payload=json.dumps(op.payload, ensure_ascii=False, default=str),
                               status="COMPLETED" if res["status"] == "APPLIED" else "FAILED", attempts=1, max_attempts=1,
                               idempotency_key=idempotency_key, reference_type="MobileDevice", created_by=user.id,
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
        can_catalog = any(has_permission(user, code) for code in
                          ("products.view", "products.manage", "pos.sell", "batches.manage", "inventory.view"))
        can_stock = any(has_permission(user, code) for code in
                        ("inventory.view", "inventory.adjust", "inventory.stocktake", "batches.manage", "pos.sell"))
        can_customers = any(has_permission(user, code) for code in
                            ("customers.manage", "customers.ledger", "customers.settle", "pos.sell"))
        if has_permission(user, "pos.sell"):
            # POS-only snapshots keep native checkout useful offline without giving
            # cashiers access to the general settings or marketing-management APIs.
            tax_rate = db.execute(select(SystemSetting.value).where(
                SystemSetting.key == "pos.tax_rate")).scalar_one_or_none()
            pull["pos_config"] = {"tax_rate": tax_rate if tax_rate is not None else "0"}
            campaign_stmt = select(Campaign)
            coupon_stmt = select(Coupon)
            if since is not None:
                campaign_stmt = campaign_stmt.where(Campaign.updated_at >= since)
                coupon_stmt = coupon_stmt.where(Coupon.updated_at >= since)
            campaigns = db.execute(campaign_stmt.order_by(Campaign.updated_at.asc()).limit(body.limit)).scalars().all()
            coupons = db.execute(coupon_stmt.order_by(Coupon.updated_at.asc()).limit(body.limit)).scalars().all()
            assigned_customer_ids = {c.customer_id for c in coupons if c.customer_id is not None}
            assigned_customer_phones = {}
            if assigned_customer_ids:
                assigned_customer_phones = {
                    customer_id: phone for customer_id, phone in db.execute(
                        select(Customer.id, Customer.phone).where(Customer.id.in_(assigned_customer_ids))
                    ).all() if phone
                }
            pull["pos_campaigns"] = [{
                "id": c.id, "name": c.name, "discount_type": c.discount_type,
                "discount_value": float(c.discount_value or 0), "min_purchase": float(c.min_purchase or 0),
                "max_purchase": float(c.max_purchase) if c.max_purchase is not None else None,
                "max_discount": float(c.max_discount) if c.max_discount is not None else None,
                "valid_from": c.valid_from.isoformat() if c.valid_from else None,
                "valid_until": c.valid_until.isoformat() if c.valid_until else None,
                "auto_issue_threshold": float(c.auto_issue_threshold) if c.auto_issue_threshold is not None else None,
                "auto_issue_validity_days": c.auto_issue_validity_days,
                "auto_issue_sms": bool(c.auto_issue_sms),
                "target_type": c.target_type, "target_ids": c.target_ids,
                "first_purchase_only": bool(c.first_purchase_only),
                "usage_limit": c.usage_limit, "per_customer_limit": c.per_customer_limit,
                "stackable": bool(c.stackable), "auto_apply": bool(c.auto_apply),
                "priority": c.priority, "used_count": c.used_count, "status": c.status,
                "updated_at": c.updated_at.isoformat(),
            } for c in campaigns]
            pull["pos_coupons"] = [{
                "id": c.id, "code": c.code, "campaign_id": c.campaign_id,
                "customer_id": c.customer_id,
                "customer_phone": c.customer_phone or assigned_customer_phones.get(c.customer_id),
                "discount_type": c.discount_type, "discount_value": float(c.discount_value or 0),
                "min_purchase": float(c.min_purchase or 0),
                "max_discount": float(c.max_discount) if c.max_discount is not None else None,
                "valid_from": c.valid_from.isoformat() if c.valid_from else None,
                "valid_until": c.valid_until.isoformat() if c.valid_until else None,
                "usage_limit": c.usage_limit, "used_count": c.used_count,
                "status": c.status, "updated_at": c.updated_at.isoformat(),
            } for c in coupons]
            limited_campaign_ids = db.execute(select(Campaign.id).where(
                Campaign.per_customer_limit.is_not(None))).scalars().all()
            pull_redemptions = select(CampaignRedemption)
            if limited_campaign_ids:
                pull_redemptions = pull_redemptions.where(
                    CampaignRedemption.campaign_id.in_(limited_campaign_ids))
            else:
                pull_redemptions = pull_redemptions.where(CampaignRedemption.id == -1)
            if since is not None:
                pull_redemptions = pull_redemptions.where(CampaignRedemption.created_at >= since)
            redemptions = db.execute(pull_redemptions.order_by(
                CampaignRedemption.created_at.asc()).limit(body.limit)).scalars().all()
            pull["pos_campaign_redemptions"] = [{
                "id": r.id, "campaign_id": r.campaign_id, "customer_id": r.customer_id,
                "created_at": r.created_at.isoformat(), "updated_at": r.created_at.isoformat(),
            } for r in redemptions]
        if can_catalog:
            prods = _changed_since(db, Product, since, body.limit)
            pull["products"] = [{"id": p.id, "name": p.name, "sku": p.sku, "barcode": p.barcode, "unit_id": p.unit_id,
                                 "category_id": p.category_id, "brand_id": p.brand_id, "is_active": p.is_active, "image_url": getattr(p, "image_url", None),
                                 "min_stock_alert": p.min_stock_alert, "has_own_barcode": getattr(p, "has_own_barcode", True),
                                 "updated_at": p.updated_at.isoformat()} for p in prods]
            from ..services import product_bank as _bank
            pull["bank"] = _bank.changed_since(db, since, body.limit)   # v2.7 — the phones carry the whole bank offline
        if can_stock:
            batches = _changed_since(db, ProductBatch, since, body.limit)
            pull["batches"] = [{"id": b.id, "product_id": b.product_id, "batch_number": b.batch_number, "expiry_date": b.expiry_date.isoformat() if b.expiry_date else None,
                                "current_qty": float(b.current_qty or 0), "unit_sell_price": float(b.sell_price or 0), "sell_price": float(b.sell_price or 0),
                                "consumer_price": float(b.consumer_price or 0), "buy_price": float(b.buy_price or 0), "status": b.status,
                                "updated_at": b.updated_at.isoformat()} for b in batches]
        if can_customers:
            custs = _changed_since(db, Customer, since, body.limit)
            purchase_counts: dict[int, int] = {}
            if custs:
                from ..models import Invoice
                counts = db.execute(select(Invoice.customer_id, func.count(Invoice.id)).where(
                    Invoice.customer_id.in_([c.id for c in custs]), Invoice.status == "PAID"
                ).group_by(Invoice.customer_id)).all()
                purchase_counts = {int(customer_id): int(count) for customer_id, count in counts}
            pull["customers"] = [{"id": c.id, "name": c.name, "last_name": c.last_name, "phone": c.phone,
                                  "credit_limit": float(c.credit_limit or 0),
                                  "lifetime_purchase_count": purchase_counts.get(c.id, 0),
                                  "updated_at": c.updated_at.isoformat()} for c in custs]
        # v4.8.1 — users ride the sync so the phone's offline sign-in policy stays
        # current (roles / is_active / «دسترسی فقط به صورت بومی»). Password hashes
        # deliberately do NOT travel: the phone caches its own verifier when the
        # user signs in online at least once.
        from ..models import User as _User
        from ..security import allowed_views_for_user, is_admin as _is_admin, user_permissions
        user_stmt = select(_User)
        if since is not None:
            user_stmt = user_stmt.where(_User.updated_at >= since)
        if not has_permission(user, "users.manage"):
            # Filter in SQL before the page limit: otherwise a busy roster could
            # consume the page and silently omit the authenticated user's own grant.
            user_stmt = user_stmt.where(_User.id == user.id)
        usrs = db.execute(user_stmt.order_by(_User.updated_at.asc()).limit(body.limit)).scalars().all()
        pull["users"] = [{"id": u.id, "username": u.username, "full_name": u.full_name,
                          "phone": u.phone, "job_title": u.job_title, "store": u.store,
                          "hire_date": u.hire_date.isoformat() if u.hire_date else None,
                          "roles": [r.name for r in u.roles],
                          "permissions": sorted(user_permissions(u)),
                          "allowed_views": allowed_views_for_user(u),
                          "is_active": bool(u.is_active),
                          "local_only": bool(u.local_only),
                          "offline_allowed": bool(u.offline_allowed),
                          "updated_at": u.updated_at.isoformat()} for u in usrs]

        # Shift/HR data is synced under the same permission boundary as the PC API.
        from ..models import Announcement, PayrollEntry, Shift, ShiftAssignment, ShiftAttendance
        can_roster = any(has_permission(user, code) for code in
                         ("shifts.view", "shifts.manage", "payroll.view", "payroll.manage",
                          "performance.view", "performance.view_all"))
        if can_roster:
            roster = db.execute(select(_User).where(_User.is_active.is_(True)).order_by(_User.full_name).limit(body.limit)).scalars().all()
            pull["roster_users"] = [{"id": person.id, "full_name": person.full_name or person.username,
                                     "job_title": person.job_title or ""} for person in roster]

        can_see_roster = has_permission(user, "shifts.view") or has_permission(user, "shifts.manage")
        assignment_stmt = select(ShiftAssignment).order_by(ShiftAssignment.id.asc())
        if not can_see_roster:
            assignment_stmt = assignment_stmt.where(ShiftAssignment.user_id == user.id)
        assignments = db.execute(assignment_stmt.limit(body.limit)).scalars().all()
        if can_see_roster:
            shift_stmt = select(Shift).order_by(Shift.id.asc())
        else:
            shift_ids = sorted({a.shift_id for a in assignments})
            shift_stmt = select(Shift).where(Shift.id.in_(shift_ids)).order_by(Shift.id.asc()) if shift_ids else select(Shift).where(Shift.id == -1)
        shifts = db.execute(shift_stmt.limit(body.limit)).scalars().all()
        from ..services import shifts as _shift_svc
        pull["shifts"] = [{**_shift_svc.out_dict(db, sh), "created_by": sh.created_by,
                            "updated_at": sh.updated_at.isoformat()} for sh in shifts]
        pull["shift_assignments"] = [{"id": a.id, "shift_id": a.shift_id, "user_id": a.user_id,
                                      "day": a.day, "status": a.status,
                                      "created_at": a.created_at.isoformat(),
                                      "updated_at": a.created_at.isoformat()} for a in assignments]
        attendance_stmt = select(ShiftAttendance).order_by(ShiftAttendance.id.desc())
        if not can_see_roster and not has_permission(user, "payroll.view") and not has_permission(user, "payroll.manage"):
            attendance_stmt = attendance_stmt.where(ShiftAttendance.user_id == user.id)
        attendance = db.execute(attendance_stmt.limit(body.limit)).scalars().all()
        pull["attendance"] = [{"id": a.id, "shift_id": a.shift_id, "user_id": a.user_id, "day": a.day,
                               "started_at": a.started_at.isoformat() if a.started_at else None,
                               "ended_at": a.ended_at.isoformat() if a.ended_at else None,
                               "late_minutes": a.late_minutes, "early_leave_minutes": a.early_leave_minutes,
                               "note": a.note,
                               "updated_at": (a.ended_at or a.started_at or datetime.utcnow()).isoformat()} for a in attendance]

        from ..services import announcements as _ann_svc
        pull["announcements"] = []
        for ann, read in _ann_svc.visible_states(db, user):
            item = _ann_svc.out_dict(db, ann, user=user, read=read)
            item["updated_at"] = ann.updated_at.isoformat()
            item["delivered_at"] = read.delivered_at.isoformat() if read and read.delivered_at else None
            item["seen_at"] = read.seen_at.isoformat() if read and read.seen_at else None
            item["read_at"] = read.read_at.isoformat() if read and read.read_at else None
            pull["announcements"].append(item)

        if has_permission(user, "payroll.view") or has_permission(user, "payroll.manage"):
            pay_stmt = select(PayrollEntry).order_by(PayrollEntry.updated_at.asc())
            if since is not None:
                pay_stmt = pay_stmt.where(PayrollEntry.updated_at >= since)
            payroll_rows = db.execute(pay_stmt.limit(body.limit)).scalars().all()
            from ..services import payroll as _pay_svc
            pull["payroll"] = [{**_pay_svc.out_dict(row), "updated_at": row.updated_at.isoformat()} for row in payroll_rows]
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
    # v3.5 — advance to the last delivered row (see _pull_cursor), not to "now".
    cursor, has_more = (_pull_cursor(pull, now, body.limit) if body.pull else (now, False))
    if body.pull and "batches" in pull and not has_permission(user, "pricing.view_cost"):
        # v3.7 (§34) — cashier phones sync everything except buy costs.
        pull["batches"] = redact_costs(pull["batches"])
    from ..security import allowed_views_for_user as _av, is_admin as _ia, user_permissions as _up
    from ..services import shifts as _shift_svc
    current_user_payload = {
        "id": user.id, "pc_id": user.id,
        "username": user.username,
        "full_name": user.full_name,
        "phone": user.phone, "job_title": user.job_title, "store": user.store,
        "hire_date": user.hire_date.isoformat() if user.hire_date else None,
        "is_active": bool(user.is_active),
        "is_admin": _ia(user),
        "local_only": bool(getattr(user, "local_only", True)),
        "offline_allowed": bool(getattr(user, "offline_allowed", False)),
        "roles": [r.name for r in user.roles],
        "permissions": sorted(_up(user)),
        "allowed_views": _av(user),
    }
    try:
        shift_status = _shift_svc.attendance_status(db, user, auto_enter=True)
    except Exception:
        db.rollback()
        log.exception("mobile sync could not compute attendance status for user_id=%s", user.id)
        raise
    return {"applied": applied, "pull": pull, "cursor": cursor, "server_time": now,
            "has_more": has_more, "current_user": current_user_payload, "shift_status": shift_status}
