"""
v2.3 — PC side of the online relay (see relay/server.py).

The shop PC dials OUT to the relay and long-polls for requests coming from the
phones; each request is replayed against the local API (http://127.0.0.1:PORT)
and the answer is posted back. Nothing listens on the internet, so it works
behind NAT / mobile hotspots / shared office networks, and inside Iran as long
as the relay host itself is reachable (any Iranian host works).

Settings (system_settings):
    relay.url      https://relay.example.ir      (empty → disabled)
    relay.store    short store id (auto: store slug + 4 hex)
    relay.key      shared secret (auto-generated, shown inside the pairing QR)
    relay.enabled  true/false
"""
from __future__ import annotations

import base64
import logging
import os
import re
import secrets
import threading
import time
from datetime import datetime

import httpx
from sqlalchemy import select

from ..models import SystemSetting

log = logging.getLogger("supermarket.relay")
_stop = threading.Event()
_thread: threading.Thread | None = None
_state = {"online": False, "last_ok": None, "last_error": None, "served": 0, "since": None}


def _get(db, key: str, default: str = "") -> str:
    row = db.execute(select(SystemSetting).where(SystemSetting.key == key)).scalar_one_or_none()
    return (row.value if row and row.value is not None else default) or default


def _set(db, key: str, value: str, secret: bool = False) -> None:
    row = db.execute(select(SystemSetting).where(SystemSetting.key == key)).scalar_one_or_none()
    if row is None:
        db.add(SystemSetting(key=key, value=value, description="online relay", is_secret=secret))
    else:
        row.value = value
    db.commit()


def config(db) -> dict:
    return {"url": _get(db, "relay.url").rstrip("/"), "store": _get(db, "relay.store"), "key": _get(db, "relay.key"),
            "enabled": _get(db, "relay.enabled", "true").lower() != "false"}


def ensure_identity(db) -> dict:
    """Store id + key are created once and never change (phones remember them)."""
    c = config(db)
    if not c["store"]:
        name = _get(db, "store.name", "shop")
        slug = re.sub(r"[^a-z0-9]+", "", name.encode("ascii", "ignore").decode().lower()) or "shop"
        c["store"] = f"{slug[:12]}-{secrets.token_hex(2)}"
        _set(db, "relay.store", c["store"])
    if not c["key"]:
        c["key"] = secrets.token_hex(12)
        _set(db, "relay.key", c["key"], secret=True)
    return c


def active(db) -> bool:
    c = config(db)
    return bool(c["url"] and c["store"] and c["key"] and c["enabled"])


def status(db) -> dict:
    c = config(db)
    return {"configured": bool(c["url"]), "enabled": c["enabled"], "url": c["url"] or None, "store": c["store"] or None,
            "has_key": bool(c["key"]), "online": _state["online"], "last_ok": _state["last_ok"], "last_error": _state["last_error"],
            "served": _state["served"], "since": _state["since"]}


def for_device(db) -> dict | None:
    """What the phone needs (goes into the pairing QR / /mobile/link)."""
    c = config(db)
    if not (c["url"] and c["store"] and c["key"]):
        return None
    return {"url": c["url"], "store": c["store"], "key": c["key"]}


def test(db) -> dict:
    c = ensure_identity(db)
    if not c["url"]:
        return {"ok": False, "message": "آدرس رله وارد نشده"}
    try:
        r = httpx.get(f"{c['url']}/r/{c['store']}/status", params={"key": c["key"]}, timeout=8)
        if r.status_code == 401:
            return {"ok": False, "message": "کلید رله پذیرفته نشد (فروشگاه دیگری با همین نام؟)"}
        r.raise_for_status()
        j = r.json()
        return {"ok": True, "message": "رله در دسترس است" + (" و رایانه متصل است" if j.get("pc_online") else " — اتصال رایانه در حال برقراری"), "relay": j}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "message": f"رله در دسترس نیست: {type(exc).__name__}"}


_HOP = {"host", "content-length", "connection", "transfer-encoding", "accept-encoding"}


def _serve_one(client: httpx.Client, local: str, req: dict) -> dict:
    method = (req.get("method") or "GET").upper()
    path = req.get("path") or "/"
    if not path.startswith("/"):
        path = "/" + path
    headers = {k: v for k, v in (req.get("headers") or {}).items() if k.lower() not in _HOP}
    body = req.get("body")
    content = None
    if body is not None:
        content = base64.b64decode(body) if req.get("binary") else body.encode("utf-8")
    try:
        r = client.request(method, local + path, headers=headers, content=content, timeout=60)
        ctype = r.headers.get("content-type", "")
        binary = not (ctype.startswith("application/json") or ctype.startswith("text/"))
        out_body = base64.b64encode(r.content).decode() if binary else r.text
        return {"id": req["id"], "status": r.status_code, "headers": {"content-type": ctype}, "body": out_body, "binary": binary}
    except Exception as exc:  # noqa: BLE001
        return {"id": req["id"], "status": 502, "headers": {"content-type": "application/json"}, "body": '{"detail":"LOCAL_API: %s"}' % type(exc).__name__, "binary": False}


def _loop(session_factory) -> None:
    from ..routers.mobile import lan_addresses
    backoff = 3
    last_beacon = 0.0
    with httpx.Client(timeout=30) as local, httpx.Client(timeout=35) as up:
        while not _stop.is_set():
            with session_factory() as db:
                if not active(db):
                    _state["online"] = False
                    _stop.wait(15)
                    continue
                c = config(db)
            port = int(os.environ.get("PORT", 8000))
            base = f"{c['url']}/r/{c['store']}"
            try:
                if time.time() - last_beacon > 60:
                    up.post(f"{base}/beacon", params={"key": c["key"]}, json={"lan": lan_addresses(), "port": port}, timeout=10)
                    last_beacon = time.time()
                r = up.get(f"{base}/pull", params={"key": c["key"], "wait": 20}, timeout=35)
                if r.status_code == 401:
                    _state.update(online=False, last_error="کلید رله پذیرفته نشد")
                    _stop.wait(30)
                    continue
                r.raise_for_status()
                if not _state["online"]:
                    _state["since"] = datetime.utcnow().isoformat(timespec="seconds")
                _state.update(online=True, last_ok=datetime.utcnow().isoformat(timespec="seconds"), last_error=None)
                backoff = 3
                for req in r.json().get("requests", []):
                    rep = _serve_one(local, f"http://127.0.0.1:{port}", req)
                    up.post(f"{base}/reply", params={"key": c["key"]}, json=rep, timeout=15)
                    _state["served"] += 1
            except Exception as exc:  # noqa: BLE001
                _state.update(online=False, last_error=f"{type(exc).__name__}")
                _stop.wait(backoff)
                backoff = min(backoff * 2, 60)


def start_worker(session_factory) -> None:
    global _thread
    if _thread and _thread.is_alive():
        return
    if os.environ.get("SUPERMARKET_RELAY", "1") in ("0", "false", "off"):
        return
    _stop.clear()
    _thread = threading.Thread(target=_loop, args=(session_factory,), name="relay-client", daemon=True)
    _thread.start()


def stop_worker() -> None:
    _stop.set()
