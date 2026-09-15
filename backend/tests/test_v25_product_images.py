"""v2.5 → v3.5 — product pictures.

v2.5 introduced *automatic pictures by name*: the system searched OpenFoodFacts,
Wikimedia Commons, Wikipedia and DuckDuckGo (and from v2.5.1 the Iranian retail
catalogues) for a photo matching the product name. **All of that was removed in
v3.5** — the default product bank now ships its own pictures for 13 537 of its
13 570 lines, and a guessed photo is worse than none because the cashier then
sells the wrong pack.

What this module still guards:

* the picture an operator uploads / pastes is validated byte-by-byte and stored
  LOCALLY under ``MEDIA_DIR/products`` (§21 — ``image_url`` is never a hot link);
* the bank's own links can be mirrored locally, so an offline shop keeps its
  thumbnails;
* the API surface (status / backfill / candidates / pick / upload) keeps working
  and reports honestly that there is no web lookup any more.
"""
from __future__ import annotations

import struct
import zlib

import pytest
from sqlalchemy import select

from app.database import SessionLocal
from app.models import Product, SyncJob
from app.services import product_images as pi
from app.services import resolvers
from app.services import sync as sync_svc


def _png(w=200, h=200, color=(200, 30, 30)) -> bytes:
    import random
    rnd = random.Random(sum(color))
    raw = b"".join(b"\x00" + bytes(min(255, max(0, ch + rnd.randint(-40, 40)))
                                   for _ in range(w) for ch in color) for _ in range(h))

    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


MILK_PNG = _png(color=(240, 240, 240))
NOT_AN_IMAGE = b"<html>not an image" + b"x" * 2048 + b"</html>"


@pytest.fixture(scope="module", autouse=True)
def _app():
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app) as tc:   # lifespan → init_db + bootstrap (admin, settings)
        yield tc


@pytest.fixture()
def db():
    s = SessionLocal()
    yield s
    s.close()


def _auth(tc):
    tok = tc.post("/api/auth/login", data={"username": "admin", "password": "admin123"}).json()["access_token"]
    return {"Authorization": f"Bearer {tok}"}


def _product(db, name, barcode=None, gallery=None):
    # Product names are NOT unique — two lines can share a name under different
    # barcodes — so take the first match instead of demanding exactly one.
    p = db.execute(select(Product).where(Product.name == name)
                   .order_by(Product.id).limit(1)).scalar_one_or_none()
    if p is None:
        import hashlib
        import uuid
        bc = barcode or ("INT-T" + hashlib.md5(name.encode()).hexdigest()[:8] + uuid.uuid4().hex[:4])
        p = Product(name=name, barcode=bc, is_active=True, has_own_barcode=bool(barcode))
        db.add(p)
        db.flush()
    p.image_url = None
    if gallery is not None:
        p.gallery = gallery
    return p


# ------------------------------------------------------------- no web, ever
def test_the_web_picture_hunt_is_gone():
    assert pi.online_enabled() is False
    for gone in ("find_candidates", "src_duckduckgo", "src_commons", "src_wikipedia",
                 "src_off_search", "src_retail_ir", "parse_retail", "score_title"):
        assert not hasattr(pi, gone), f"{gone} should have been removed with the web ladder"


def test_a_product_with_no_shipped_picture_stays_pictureless(db):
    p = _product(db, "کالای بدون تصویر تست")
    rep = pi.find_and_store(db, p)
    assert rep == {"ok": False, "reason": "NO_REMOTE_IMAGE", "tried": 0}
    assert p.image_url is None
    db.rollback()


def test_backfill_reports_offline_instead_of_queueing_noop_jobs(db):
    assert pi.backfill(db) == {"queued": 0, "reason": "OFFLINE_MODE"}


# ------------------------------------------------------- mirroring the bank
def test_mirror_remote_stores_locally_and_never_hot_links(db, monkeypatch):
    monkeypatch.setattr(resolvers, "_fetch_image",
                        lambda url, client=None: ({"ok": True, "format": "PNG",
                                                   "width": 200, "height": 200}, MILK_PNG))
    p = _product(db, "شیر پرچرب ۱ لیتری آینه", gallery='["https://img.test/a.png", "https://img.test/b.png"]')
    rep = pi.mirror_remote(db, p)
    assert rep["ok"] is True and rep["reason"] == "STORED", rep
    assert p.image_url.startswith("/media/products/"), p.image_url
    # a second call is a no-op — the picture is already local
    again = pi.mirror_remote(db, p)
    assert again["reason"] == "ALREADY_LOCAL"
    db.rollback()


def test_mirror_falls_back_to_the_next_link_when_one_fails(db, monkeypatch):
    calls = []

    def fake(url, client=None):
        calls.append(url)
        if url.endswith("a.png"):
            return {"ok": False, "reason": "FETCH_FAILED"}, b""
        return {"ok": True, "format": "PNG", "width": 200, "height": 200}, MILK_PNG

    monkeypatch.setattr(resolvers, "_fetch_image", fake)
    p = _product(db, "شیر کم‌چرب آینه دوم", gallery='["https://img.test/a.png", "https://img.test/b.png"]')
    rep = pi.mirror_remote(db, p)
    assert rep["ok"] is True and calls == ["https://img.test/a.png", "https://img.test/b.png"], (rep, calls)
    db.rollback()


def test_mirror_reports_failure_honestly_when_every_link_is_dead(db, monkeypatch):
    monkeypatch.setattr(resolvers, "_fetch_image", lambda url, client=None: ({"ok": False, "reason": "FETCH_FAILED"}, b""))
    p = _product(db, "شیر شکست آینه", gallery='["https://img.test/a.png"]')
    rep = pi.mirror_remote(db, p)
    assert rep == {"ok": False, "reason": "FETCH_FAILED", "tried": 1}
    assert p.image_url is None, "a failed download must not leave a half-set image"
    db.rollback()


# ------------------------------------------------------------ upload / pick
def test_upload_validates_bytes_and_stores_locally(db):
    p = _product(db, "پنیر سفید ۴۰۰ گرمی آپلود")
    ok = pi.set_image_from_bytes(db, p, MILK_PNG, source="upload")
    assert ok["ok"] is True and ok["image_url"].startswith("/media/products/")
    bad = pi.set_image_from_bytes(db, _product(db, "پنیر سفید آپلود بد"), NOT_AN_IMAGE, source="upload")
    assert bad == {"ok": False, "reason": "INVALID_IMAGE"}
    db.rollback()


def test_pick_a_url_downloads_and_stores(db, monkeypatch):
    monkeypatch.setattr(resolvers, "_fetch_image",
                        lambda url, client=None: ({"ok": True, "format": "PNG",
                                                   "width": 200, "height": 200}, MILK_PNG))
    p = _product(db, "ماست پرچرب انتخابی")
    rep = pi.set_image_from_url(db, p, "https://img.test/picked.png", source="picked")
    assert rep["ok"] is True and rep["source"] == "picked"
    db.rollback()


def test_candidates_are_the_shipped_pictures_only(db):
    p = _product(db, "کره ۵۰ گرمی گالری", gallery='["https://img.test/1.png", "https://img.test/2.png"]')
    cands = pi.list_candidates(db, p)
    assert [c["url"] for c in cands] == ["https://img.test/1.png", "https://img.test/2.png"]
    assert all(c["source"] == "bank" for c in cands)
    assert pi.list_candidates(db, _product(db, "کره بدون گالری")) == []
    db.rollback()


# ------------------------------------------------------------------- the API
def test_api_endpoints(_app):
    tc = _app
    H = _auth(tc)
    st = tc.get("/api/products/images/status", headers=H).json()
    assert {"total", "missing", "jobs", "auto_find"} <= set(st)
    # v3.5 — the panel must not advertise a web lookup that no longer exists
    assert st["web_fallback"] is False and st["web_lookup"] is False

    r = tc.post("/api/products", json={"name": "پنیر سفید ۴۰۰ گرمی تست‌تصویر",
                                       "has_own_barcode": False}, headers=H)
    assert r.status_code == 201, r.text
    pid = r.json()["id"]

    bf = tc.post("/api/products/images/backfill?limit=5", headers=H).json()
    assert bf["queued"] == 0 and bf["reason"] == "OFFLINE_MODE", bf
    # nothing is queued: there is no lookup to run
    with SessionLocal() as s:
        assert s.execute(select(SyncJob).where(
            SyncJob.idempotency_key == f"product-image:{pid}")).scalar_one_or_none() is None

    cands = tc.get(f"/api/products/{pid}/image/candidates", headers=H).json()
    assert cands["web_lookup"] is False and cands["candidates"] == []

    up = tc.post(f"/api/products/{pid}/image/upload", headers=H,
                 files={"file": ("p.png", MILK_PNG, "image/png")})
    assert up.status_code == 200 and up.json()["image_url"].startswith("/media/products/"), up.text
    tc.delete(f"/api/products/{pid}", headers=H)


def test_image_job_handler_is_still_registered():
    """The sync worker keeps its PRODUCT_IMAGE handler (it now mirrors, not searches)."""
    assert "PRODUCT_IMAGE" in sync_svc.HANDLERS
