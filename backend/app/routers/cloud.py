"""v1.7 — /api/cloud: internet sync through the owner's Google Drive (appDataFolder)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import User
from ..security import get_current_user, require_permission
from ..services import cloud as svc
from ..services.audit import write_audit

router = APIRouter(prefix="/cloud", tags=["cloud"])


def _raise(exc: svc.CloudError):
    raise HTTPException(status_code=400, detail={"code": exc.code, "message": str(exc)})


class ConnectIn(BaseModel):
    client_id: str
    client_secret: str


@router.get("/status")
def status(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    return svc.status(db)


@router.post("/connect/start")
def connect_start(body: ConnectIn, db: Session = Depends(get_db), user: User = Depends(require_permission("settings.manage"))):
    try:
        out = svc.device_start(db, body.client_id, body.client_secret)
    except svc.CloudError as exc:
        _raise(exc)
    write_audit(db, action="CLOUD_CONNECT_STARTED", user_id=user.id, entity_type="Cloud"); db.commit()
    return out


@router.post("/connect/poll")
def connect_poll(db: Session = Depends(get_db), user: User = Depends(require_permission("settings.manage"))):
    try:
        out = svc.device_poll(db)
    except svc.CloudError as exc:
        _raise(exc)
    if out.get("status") == "CONNECTED":
        write_audit(db, action="CLOUD_CONNECTED", user_id=user.id, entity_type="Cloud", reference=out.get("account")); db.commit()
    return out


class OAuthStartIn(BaseModel):
    client_id: str | None = None
    client_secret: str | None = None


@router.post("/oauth/start")
def oauth_start(body: OAuthStartIn, request: Request, db: Session = Depends(get_db), user: User = Depends(require_permission("settings.manage"))):
    """v2.1 — in-app Google sign-in: returns the URL the browser opens; Google
    redirects back to /api/cloud/oauth/callback on this very machine."""
    host = request.headers.get("host") or f"127.0.0.1:{request.url.port or 8000}"
    hostname = host.split(":")[0]
    # Google only allows loopback IPs for desktop clients; map localhost → 127.0.0.1
    if hostname in ("localhost", "0.0.0.0", "::1"):
        host = "127.0.0.1" + (":" + host.split(":")[1] if ":" in host else "")
    redirect = f"http://{host}/api/cloud/oauth/callback"
    try:
        return svc.oauth_start(db, redirect, body.client_id, body.client_secret)
    except svc.CloudError as exc:
        _raise(exc)


@router.get("/oauth/callback", response_class=HTMLResponse)
def oauth_callback(code: str | None = None, state: str | None = None, error: str | None = None, db: Session = Depends(get_db)):
    """Landing page after the Google account picker (no bearer header here — the
    single-use ``state`` proves the request was started from this install)."""
    ok, msg = False, ""
    if error:
        msg = "ورود انجام نشد: " + error
    else:
        try:
            out = svc.oauth_finish(db, code or "", state or "")
            ok, msg = True, f"حساب {out.get('account') or ''} متصل شد"
            write_audit(db, action="CLOUD_CONNECTED", entity_type="Cloud", reference=out.get("account")); db.commit()
        except svc.CloudError as exc:
            msg = str(exc)
    color = "#1f9d55" if ok else "#c0392b"
    return f"""<!doctype html><html lang="fa" dir="rtl"><meta charset="utf-8"><title>همگام‌سازی ابری</title>
<body style="font-family:Vazirmatn,Tahoma,sans-serif;background:#f6f7f9;display:grid;place-items:center;height:100vh;margin:0">
<div style="background:#fff;border-radius:16px;padding:28px 32px;box-shadow:0 8px 30px rgba(0,0,0,.08);text-align:center;max-width:420px">
<div style="font-size:42px">{'✓' if ok else '✕'}</div><h2 style="color:{color};margin:8px 0">{msg}</h2>
<p style="color:#666">{'می‌توانید این برگه را ببندید؛ برنامه خودش ادامه می‌دهد.' if ok else 'به برنامه برگردید و دوباره تلاش کنید.'}</p>
<button onclick="window.close()" style="padding:10px 22px;border-radius:10px;border:0;background:#2563eb;color:#fff;font-size:15px">بستن</button></div>
<script>try{{if(window.opener){{window.opener.postMessage({{type:'cloud-oauth',ok:{str(ok).lower()}}},'*');setTimeout(()=>window.close(),1500);}}}}catch(e){{}}</script></body></html>"""


@router.post("/disconnect")
def disconnect(db: Session = Depends(get_db), user: User = Depends(require_permission("settings.manage"))):
    svc.disconnect(db)
    write_audit(db, action="CLOUD_DISCONNECTED", user_id=user.id, entity_type="Cloud"); db.commit()
    return {"ok": True}


@router.post("/sync-now")
def sync_now(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    try:
        return svc.sync_now(db)
    except svc.CloudError as exc:
        _raise(exc)


@router.get("/device-credentials")
def device_credentials(db: Session = Depends(get_db), _: User = Depends(require_permission("settings.manage"))):
    """Handed to a paired phone (inside the QR) so it can reach the same mailbox."""
    return svc.credentials_for_device(db) or {}


# --- v2.3 online relay (optional, self-hosted) ------------------------------------------------
from ..services import relay_client as relay_svc  # noqa: E402


class RelayIn(BaseModel):
    url: str = ""
    enabled: bool = True
    regenerate_key: bool = False


@router.get("/relay/status")
def relay_status(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    return relay_svc.status(db)


@router.put("/relay")
def relay_config(body: RelayIn, db: Session = Depends(get_db), user: User = Depends(require_permission("settings.manage"))):
    url = body.url.strip().rstrip("/")
    if url and not url.startswith(("http://", "https://")):
        url = "https://" + url
    relay_svc._set(db, "relay.url", url)
    relay_svc._set(db, "relay.enabled", "true" if body.enabled else "false")
    if body.regenerate_key:
        relay_svc._set(db, "relay.key", "", secret=True)
    relay_svc.ensure_identity(db)
    write_audit(db, action="SETTINGS_CHANGED", user_id=user.id, entity_type="SystemSetting", entity_id=None, after={"key": "relay.url", "value": url})
    db.commit()
    return relay_svc.status(db)


@router.post("/relay/test")
def relay_test(db: Session = Depends(get_db), _: User = Depends(require_permission("settings.manage"))):
    return relay_svc.test(db)
