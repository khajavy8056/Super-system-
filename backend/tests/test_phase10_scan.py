"""Scan-to-draft pipeline (§9-§11, §21).

The question these tests answer: when a shopkeeper scans a barcode to add a
product, does the system really pull the details AND the picture from external
sources, or does it quietly fall back to manual entry?

All HTTP is mocked so the suite stays offline-safe. A real-network check
against OpenFoodFacts is a separate, environment-dependent step and is never
claimed on the strength of these mocks.
"""
from __future__ import annotations

import os
import struct
import tempfile
import zlib
from pathlib import Path

import httpx
import pytest

_TMP = Path(tempfile.mkdtemp(prefix="supermarket_scan_"))
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_TMP / 'scan.db'}")

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app.config import settings  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models import ExternalSource  # noqa: E402


def ean13(prefix12: str) -> str:
    total = sum(int(d) * (3 if i % 2 else 1) for i, d in enumerate(prefix12))
    return prefix12 + str((10 - total % 10) % 10)


def real_png(w: int = 120, h: int = 90) -> bytes:
    """A genuinely decodable PNG, so header/dimension validation is real.

    Random pixel data on purpose: a flat-colour image compresses to a few
    hundred bytes and would trip the resolver's MIN_IMAGE_BYTES floor, which
    would make this fixture — not the code — the thing under test.
    """
    import random

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    rnd = random.Random(1234)
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    raw = b"".join(b"\x00" + bytes(rnd.randrange(256) for _ in range(w * 3))
                   for _ in range(h))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def H(client):
    r = client.post("/api/auth/login",
                    data={"username": "admin", "password": "admin123"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture(scope="module", autouse=True)
def only_our_source():
    from app.database import init_db
    init_db()
    s = SessionLocal()
    # Deactivate, never delete: resolver results reference sources via FK.
    for src in s.execute(select(ExternalSource)).scalars():
        src.is_active = False
    s.add(ExternalSource(code="custom_http:scan", name="Scan Test",
                         source_type="PRODUCT", priority=10,
                         base_url="http://scan.test/{barcode}", is_active=True))
    s.commit()
    s.close()


def mock_http(monkeypatch, handler):
    import app.services.providers.base as pbase
    real = httpx.Client
    monkeypatch.setattr(
        pbase.httpx, "Client",
        lambda *a, **k: real(transport=httpx.MockTransport(handler)))
    import app.services.resolvers as rsv
    monkeypatch.setattr(
        rsv.httpx, "Client",
        lambda *a, **k: real(transport=httpx.MockTransport(handler)))


# ---------------------------------------------------------------------------
# The headline scenario
# ---------------------------------------------------------------------------
def test_scan_returns_a_full_draft_with_a_locally_stored_image(client, H, monkeypatch):
    bc = ean13("400000000001")
    png = real_png()

    def h(request):
        if "/img/" in request.url.path:
            return httpx.Response(200, content=png,
                                  headers={"content-type": "image/png"})
        return httpx.Response(200, json={
            "name": "شیر پرچرب کاله ۱ لیتری", "brand": "کاله",
            "category": "لبنیات", "description": "شیر پاستوریزه",
            "image_url": "http://scan.test/img/1.png"})

    mock_http(monkeypatch, h)
    r = client.post(f"/api/barcode/scan?barcode={bc}", headers=H,
                    json={"with_image": True})
    assert r.status_code == 200, r.text
    body = r.json()

    draft = body["draft"]
    assert draft["name"] == "شیر پرچرب کاله ۱ لیتری"
    assert draft["brand"] == "کاله"
    assert draft["category"] == "لبنیات"

    # §52: external data is a suggestion, never an auto-commit
    assert body["need_manual"] is True

    # §21: the image must be DOWNLOADED, not hotlinked
    assert body["coverage"]["image_found"] is True
    local = body["image"]["best_local_path"]
    assert local and not local.startswith("http")
    assert (Path(settings.MEDIA_DIR) / local.replace("media/", "", 1)).exists() \
        or (Path(settings.MEDIA_DIR) / local).exists()
    assert draft["image_url"] == local
    monkeypatch.undo()


def test_draft_reports_which_fields_each_source_supplied(client, H, monkeypatch):
    bc = ean13("400000000002")
    mock_http(monkeypatch, lambda rq: httpx.Response(
        200, json={"name": "کالای الف", "brand": "برند الف"}))
    body = client.post(f"/api/barcode/scan?barcode={bc}", headers=H,
                       json={"with_image": False}).json()
    assert set(body["filled_fields"]) >= {"name", "brand"}
    assert body["merged"]["name"]["sources"]  # provenance is preserved
    assert body["sources"][0]["source"] == "custom_http:scan"
    monkeypatch.undo()


# ---------------------------------------------------------------------------
# Honest failure — the old behaviour was silent
# ---------------------------------------------------------------------------
def test_unreachable_source_is_reported_not_swallowed(client, H, monkeypatch):
    bc = ean13("400000000003")

    def boom(request):
        raise httpx.ConnectError("network is down")

    mock_http(monkeypatch, boom)
    body = client.post(f"/api/barcode/scan?barcode={bc}", headers=H,
                       json={"with_image": False}).json()
    assert body["origin"] == "none"
    assert body["need_manual"] is True
    failed = [s for s in body["sources"] if not s["ok"]]
    assert failed, "a dead network must surface as a failed source"
    assert failed[0]["error"]["kind"] in ("UNREACHABLE", "TIMEOUT")
    monkeypatch.undo()


def test_missing_image_never_blocks_the_draft(client, H, monkeypatch):
    bc = ean13("400000000004")

    def h(request):
        if "/img/" in request.url.path:
            return httpx.Response(404)
        return httpx.Response(200, json={"name": "بدون تصویر",
                                         "image_url": "http://scan.test/img/x.png"})

    mock_http(monkeypatch, h)
    body = client.post(f"/api/barcode/scan?barcode={bc}", headers=H,
                       json={"with_image": True}).json()
    assert body["draft"]["name"] == "بدون تصویر"      # text still usable
    assert body["coverage"]["image_found"] is False
    assert "image_url" not in body["draft"]
    monkeypatch.undo()


def test_invalid_checksum_is_rejected_before_any_network_call(client, H):
    r = client.post("/api/barcode/scan?barcode=1234567890123", headers=H,
                    json={"with_image": True})
    body = r.json()
    assert body["origin"] == "invalid"
    assert body["draft"] is None


def test_known_barcode_short_circuits_to_the_local_product(client, H, monkeypatch):
    bc = ean13("400000000005")
    mock_http(monkeypatch, lambda rq: httpx.Response(
        200, json={"name": "کالای محلی"}))
    client.post("/api/products", headers=H,
                json={"barcode": bc, "name": "کالای محلی", "min_stock_alert": 1})
    body = client.post(f"/api/barcode/scan?barcode={bc}", headers=H,
                       json={"with_image": False}).json()
    assert body["origin"] == "local"
    assert body["product"]["name"] == "کالای محلی"
    assert body["draft"] is None
    monkeypatch.undo()


# ---------------------------------------------------------------------------
# First-boot wiring — the actual root cause of "scanning does nothing"
# ---------------------------------------------------------------------------
def test_bootstrap_registers_openfoodfacts_by_default():
    """A fresh install must ship with a working, openly-licensed source."""
    from app.bootstrap import DEFAULT_SOURCES, ensure_default_sources

    codes = {s["code"] for s in DEFAULT_SOURCES}
    assert "openfoodfacts" in codes
    assert any(s["source_type"] == "IMAGE" for s in DEFAULT_SOURCES)
    # licensing rule: nothing keyed/commercial is shipped enabled
    for s in DEFAULT_SOURCES:
        assert "holoo" not in s["code"].lower()
        assert s["base_url"].startswith("https://")

    db = SessionLocal()
    try:
        ensure_default_sources(db)
        db.commit()
        got = {s.code for s in db.execute(select(ExternalSource)).scalars()}
        assert "openfoodfacts" in got
        # idempotent
        ensure_default_sources(db)
        db.commit()
        again = [s for s in db.execute(select(ExternalSource)).scalars()
                 if s.code == "openfoodfacts"]
        assert len(again) == 1
    finally:
        db.close()
