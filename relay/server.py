"""
سوپری من / Supermarket — Online Relay (v2.3)

A tiny, stateless HTTP relay that lets phones reach the shop PC from ANY network
(mobile data, another city) without port-forwarding, VPN or a public IP:

    phone  --HTTPS-->  relay  <--HTTPS(long-poll)--  shop PC (dials OUT)

* The PC runs `services/relay_client.py`: it long-polls `/r/{store}/pull`, executes
  each request against its own local API and posts the answer to `/r/{store}/reply`.
* The phone posts `/r/{store}/call` {method, path, headers, body} and waits (≤25 s)
  for the answer. Its normal bearer token still travels inside; the relay never sees
  a password and stores nothing on disk.
* One shared secret (`relay.key`, shown in the PC's pairing QR) authenticates both
  ends; different shops never see each other's traffic.

Deploy anywhere that can run Python 3.11+ (any Iranian or foreign VPS/host, Docker,
Liara/ParsPack/Fandogh style PaaS). ~50 MB RAM. See relay/README.md.

    pip install fastapi uvicorn
    RELAY_ADMIN_TOKEN=... uvicorn server:app --host 0.0.0.0 --port 8080
"""
from __future__ import annotations

import asyncio
import hmac
import os
import secrets
import time
import uuid

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

app = FastAPI(title="Supermarket Relay", version="2.3.0", docs_url=None, redoc_url=None)

MAX_BODY = int(os.environ.get("RELAY_MAX_BODY", 6 * 1024 * 1024))
CALL_TIMEOUT = float(os.environ.get("RELAY_CALL_TIMEOUT", 25))
PULL_TIMEOUT = float(os.environ.get("RELAY_PULL_TIMEOUT", 20))
IDLE_TTL = float(os.environ.get("RELAY_IDLE_TTL", 900))


class Store:
    def __init__(self, key: str):
        self.key = key
        self.queue: asyncio.Queue = asyncio.Queue()
        self.waiting: dict[str, asyncio.Future] = {}
        self.pc_seen = 0.0
        self.last = time.time()
        self.calls = 0


_stores: dict[str, Store] = {}


def _store(name: str, key: str) -> Store:
    if not name or not key or len(key) < 8:
        raise HTTPException(status_code=401, detail="bad key")
    s = _stores.get(name)
    if s is None:
        s = _stores[name] = Store(key)
    elif not hmac.compare_digest(s.key, key):
        # a second party claiming the same store name with another key
        if time.time() - s.last > IDLE_TTL:
            s = _stores[name] = Store(key)  # stale entry: allow re-registration
        else:
            raise HTTPException(status_code=401, detail="bad key")
    s.last = time.time()
    return s


class CallIn(BaseModel):
    method: str = Field(default="GET", max_length=8)
    path: str = Field(max_length=2048)
    headers: dict[str, str] = Field(default_factory=dict)
    body: str | None = None            # utf-8 text or base64 when binary=true
    binary: bool = False


class ReplyIn(BaseModel):
    id: str
    status: int
    headers: dict[str, str] = Field(default_factory=dict)
    body: str | None = None
    binary: bool = False


@app.get("/")
def root():
    return {"service": "supermarket-relay", "version": "2.3.0", "stores": len(_stores)}


@app.get("/r/{store}/status")
def status(store: str, key: str):
    s = _store(store, key)
    return {"pc_online": time.time() - s.pc_seen < PULL_TIMEOUT + 10, "pc_seen_ago": round(time.time() - s.pc_seen, 1) if s.pc_seen else None, "queued": s.queue.qsize(), "calls": s.calls}


@app.post("/r/{store}/call")
async def call(store: str, key: str, body: CallIn, request: Request):
    s = _store(store, key)
    if body.body and len(body.body) > MAX_BODY:
        raise HTTPException(status_code=413, detail="body too large")
    if time.time() - s.pc_seen > PULL_TIMEOUT + 15:
        return JSONResponse(status_code=503, content={"detail": "PC_OFFLINE", "message": "رایانهٔ فروشگاه به رله وصل نیست"})
    rid = uuid.uuid4().hex
    fut: asyncio.Future = asyncio.get_running_loop().create_future()
    s.waiting[rid] = fut
    await s.queue.put({"id": rid, **body.model_dump()})
    s.calls += 1
    try:
        rep = await asyncio.wait_for(fut, timeout=CALL_TIMEOUT)
    except asyncio.TimeoutError:
        s.waiting.pop(rid, None)
        return JSONResponse(status_code=504, content={"detail": "PC_TIMEOUT", "message": "رایانه پاسخ نداد"})
    return rep


@app.get("/r/{store}/pull")
async def pull(store: str, key: str, wait: float = PULL_TIMEOUT):
    """PC side: block until a request arrives (or `wait` seconds pass)."""
    s = _store(store, key)
    s.pc_seen = time.time()
    try:
        item = await asyncio.wait_for(s.queue.get(), timeout=min(wait, PULL_TIMEOUT))
    except asyncio.TimeoutError:
        return {"requests": []}
    s.pc_seen = time.time()
    return {"requests": [item]}


@app.post("/r/{store}/reply")
async def reply(store: str, key: str, body: ReplyIn):
    s = _store(store, key)
    s.pc_seen = time.time()
    fut = s.waiting.pop(body.id, None)
    if fut is None or fut.done():
        return {"ok": False, "reason": "no such request (timed out)"}
    fut.set_result(body.model_dump())
    return {"ok": True}


@app.get("/r/{store}/beacon")
def beacon(store: str, key: str):
    """Phones on the *same* Wi-Fi as the PC but with a changed IP: the PC publishes its
    current LAN addresses here every minute so a phone can go back to the fast LAN path."""
    s = _store(store, key)
    return {"lan": getattr(s, "lan", []), "port": getattr(s, "port", None), "pc_online": time.time() - s.pc_seen < PULL_TIMEOUT + 10}


class BeaconIn(BaseModel):
    lan: list[str] = Field(default_factory=list, max_length=16)
    port: int | None = None


@app.post("/r/{store}/beacon")
def beacon_set(store: str, key: str, body: BeaconIn):
    s = _store(store, key)
    s.lan = body.lan  # type: ignore[attr-defined]
    s.port = body.port  # type: ignore[attr-defined]
    s.pc_seen = time.time()
    return {"ok": True}


@app.on_event("startup")
async def _gc():
    async def loop():
        while True:
            await asyncio.sleep(60)
            now = time.time()
            for name in [n for n, s in _stores.items() if now - s.last > IDLE_TTL * 4 and s.queue.empty()]:
                _stores.pop(name, None)
    asyncio.create_task(loop())


def new_key() -> str:
    return secrets.token_hex(12)
