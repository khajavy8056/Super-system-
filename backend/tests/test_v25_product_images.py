"""v2.5 — automatic product pictures by name.

External HTTP goes through httpx.MockTransport (deterministic, offline).
The «رب گوجه‌فرنگی» case guards relevance: a tomato *plant* photo must lose to
the tomato-paste can even though both mention «tomato».
"""
from __future__ import annotations

import io
import struct
import zlib

import httpx
import pytest
from sqlalchemy import select

from app.database import SessionLocal
from app.models import Product, SyncJob
from app.services import product_images as pi
from app.services import sync as sync_svc


def _png(w=200, h=200, color=(200, 30, 30)) -> bytes:
    import random
    rnd = random.Random(sum(color))
    raw = b"".join(b"\x00" + bytes(min(255, max(0, ch + rnd.randint(-40, 40))) for _ in range(w) for ch in color) for _ in range(h))
    def chunk(t, d): return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


PASTE_PNG, PLANT_PNG, MILK_PNG = _png(), _png(color=(30, 160, 30)), _png(color=(240, 240, 240))


def handler(req: httpx.Request) -> httpx.Response:
    u, q = str(req.url), dict(req.url.params)
    if "openfoodfacts.org/api/v2/product/6260100108219" in u:
        return httpx.Response(200, json={"status": 1, "product": {"product_name": "شیر پرچرب میهن ۱ لیتری", "image_front_url": "https://img.test/milk.png"}})
    if "openfoodfacts.org/api/v2/product/" in u:
        return httpx.Response(200, json={"status": 0})
    if "openfoodfacts.org/cgi/search.pl" in u:
        if "رب" in q.get("search_terms", "") or "tomato paste" in q.get("search_terms", ""):
            return httpx.Response(200, json={"products": [
                {"product_name": "Tomato plant seedling", "image_front_url": "https://img.test/plant.png"},
                {"product_name_fa": "رب گوجه فرنگی چین چین", "product_name": "Tomato paste", "brands": "Chin Chin", "image_front_url": "https://img.test/paste.png"},
            ]})
        return httpx.Response(200, json={"products": []})
    if "commons.wikimedia.org" in u or "wikipedia.org" in u:
        return httpx.Response(200, json={"query": {"pages": {}}})
    if "duckduckgo.com" in u:
        return httpx.Response(200, text="<html>vqd=3-123</html>") if u.endswith("images") or "i.js" not in u else httpx.Response(200, json={"results": []})
    if u.endswith("paste.png"): return httpx.Response(200, content=PASTE_PNG, headers={"content-type": "image/png"})
    if u.endswith("plant.png"): return httpx.Response(200, content=PLANT_PNG, headers={"content-type": "image/png"})
    if u.endswith("milk.png"): return httpx.Response(200, content=MILK_PNG, headers={"content-type": "image/png"})
    return httpx.Response(404)


@pytest.fixture()
def client():
    with httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True) as c:
        yield c


@pytest.fixture(scope="module", autouse=True)
def _app():
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app) as tc:   # lifespan → init_db + bootstrap (admin, settings)
        yield tc


@pytest.fixture()
def db():
    s = SessionLocal(); yield s; s.close()


def _product(db, name, barcode=None):
    p = db.execute(select(Product).where(Product.name == name)).scalar_one_or_none()
    if p is None:
        import hashlib, uuid
        bc = barcode or ("INT-T" + hashlib.md5(name.encode()).hexdigest()[:8] + uuid.uuid4().hex[:4])
        p = Product(name=name, barcode=bc, is_active=True, has_own_barcode=bool(barcode)); db.add(p); db.flush()
    p.image_url = None
    return p


def test_01_query_building():
    assert "tomato paste" in pi.english_query("رب گوجه‌فرنگی ۸۰۰ گرمی", "چین‌چین")
    assert pi.persian_query("شیر پرچرب ۱ لیتری", "میهن").startswith("شیر پرچرب")
    assert "لیتری" not in pi.persian_query("شیر پرچرب ۱ لیتری", None)


def test_02_relevance_paste_beats_plant():
    name = "رب گوجه‌فرنگی"
    assert pi.score_title("رب گوجه فرنگی چین چین Tomato paste", name, None) > pi.score_title("Tomato plant seedling", name, None)


def test_03_rob_gets_paste_not_plant(db, client):
    p = _product(db, "رب گوجه‌فرنگی ۸۰۰ گرمی")
    rep = pi.find_and_store(db, p, client=client, force=True)
    assert rep["ok"], rep
    assert rep["url"].endswith("paste.png"), rep
    assert p.image_url and p.image_url.startswith("/media/products/")
    db.rollback()


def test_04_barcode_exact_hit_first(db, client):
    p = _product(db, "شیر پرچرب ۱ لیتری میهن", barcode="6260100108219")
    rep = pi.find_and_store(db, p, client=client, force=True)
    assert rep["ok"] and rep["source"] == "openfoodfacts:barcode" and rep["url"].endswith("milk.png")
    db.rollback()


def test_05_no_candidates_reports_honestly(db, client):
    p = _product(db, "کالای کاملاً ناشناخته زیدبیس")
    rep = pi.find_and_store(db, p, client=client, force=True)
    assert rep["ok"] is False and rep["reason"] in ("NO_CANDIDATES", "NO_VALID_IMAGE")
    db.rollback()


def test_06_enqueue_is_idempotent_and_handler_registered(db):
    p = _product(db, "ماست کم‌چرب ۹۰۰ گرمی")
    db.flush()
    for j in db.execute(select(SyncJob).where(SyncJob.idempotency_key == f"product-image:{p.id}")).scalars().all():
        db.delete(j)
    db.flush()
    pi.enqueue(db, p.id); pi.enqueue(db, p.id)
    jobs = db.execute(select(SyncJob).where(SyncJob.idempotency_key == f"product-image:{p.id}")).scalars().all()
    assert len(jobs) == 1 and jobs[0].job_type == "PRODUCT_IMAGE"
    assert "PRODUCT_IMAGE" in sync_svc.HANDLERS
    db.rollback()


def test_07_api_endpoints(_app):
    tc = _app
    if True:
        tok = tc.post("/api/auth/login", data={"username": "admin", "password": "admin123"}).json()["access_token"]
        H = {"Authorization": f"Bearer {tok}"}
        st = tc.get("/api/products/images/status", headers=H).json()
        assert {"total", "missing", "jobs", "auto_find"} <= set(st)
        r = tc.post("/api/products", json={"name": "پنیر سفید ۴۰۰ گرمی تست‌تصویر", "has_own_barcode": False}, headers=H)
        assert r.status_code == 201, r.text
        pid = r.json()["id"]
        bf = tc.post("/api/products/images/backfill?limit=5", headers=H).json()
        assert "queued" in bf
        # job queued for the new product
        with SessionLocal() as s:
            assert s.execute(select(SyncJob).where(SyncJob.idempotency_key == f"product-image:{pid}")).scalar_one_or_none() is not None
        tc.delete(f"/api/products/{pid}", headers=H)
