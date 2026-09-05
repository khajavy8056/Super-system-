"""Barcode resolver tests — the 13 mandatory scenarios (§10) + provider config.

All external HTTP is exercised through httpx.MockTransport — deterministic and
offline-safe. Live-internet checks against the real OpenFoodFacts API are run
separately (see TEST_REPORT §7) and never claimed from mocks.
"""
from __future__ import annotations

import os
import tempfile
from decimal import Decimal
from pathlib import Path

import httpx
import pytest

_TMP = Path(tempfile.mkdtemp(prefix="supermarket_resolver_"))
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_TMP / 'resolver.db'}")

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app.database import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models import ExternalSource, MarketPrice, ProductResolverResult  # noqa: E402
from app.services import resolvers  # noqa: E402


def ean13(prefix12: str) -> str:
    """Compute a valid EAN-13 check digit so every test barcode is checksum-valid."""
    total = sum(int(d) * (3 if i % 2 else 1) for i, d in enumerate(prefix12))
    return prefix12 + str((10 - total % 10) % 10)


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def H(client):
    r = client.post("/api/auth/login", data={"username": "admin", "password": "admin123"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture()
def db():
    s = SessionLocal()
    yield s
    s.close()


def add_source(db, code: str, base_url: str, source_type: str = "PRODUCT",
               priority: int = 100, connection: str | None = None):
    existing = db.execute(select(ExternalSource).where(ExternalSource.code == code)).scalar_one_or_none()
    if existing:
        db.delete(existing)
        db.commit()
    s = ExternalSource(code=code, name=code, source_type=source_type,
                       base_url=base_url, priority=priority, is_active=True, connection=connection)
    db.add(s)
    db.commit()
    return s


def transport(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


@pytest.fixture(scope="module", autouse=True)
def clean_sources():
    """Isolation: no external sources may leak in from other test modules.

    Deactivate rather than delete. Bootstrap now registers default sources on
    first boot, and once any resolver result / market price references one, a
    hard DELETE trips the FK. Only `_active_sources` matters for isolation, so
    flipping is_active is both sufficient and safe.
    """
    from app.database import init_db
    init_db()  # tables exist even when this module runs first
    s = SessionLocal()
    for src in s.execute(select(ExternalSource)).scalars():
        src.is_active = False
    s.commit()
    s.close()
    yield
    # deactivate (not delete): results/prices reference sources via FK
    s = SessionLocal()
    for src in s.execute(select(ExternalSource)).scalars():
        src.is_active = False
    s.commit()
    s.close()


def json_handler(routes: dict[str, object], default=404):
    def h(request: httpx.Request) -> httpx.Response:
        key = request.url.path.rsplit("/", 1)[-1].replace(".json", "")
        if key in routes:
            body = routes[key]
            if isinstance(body, httpx.Response):
                return body
            return httpx.Response(200, json=body)
        if default == 404:
            return httpx.Response(404, json={"error": "not found"})
        return httpx.Response(200, json=default)
    return h


BC_LOCAL = ean13("200000000001")   # created locally below
BC_A = ean13("200000000002")
BC_B = ean13("200000000003")
BC_BOTH = ean13("200000000004")
BC_CONFLICT = ean13("200000000005")
BC_NOIMG = ean13("200000000006")
BC_UNKNOWN = ean13("999999999999")
BC_TIMEOUT = ean13("200000000007")
BC_DOWN = ean13("200000000008")
BC_INVALID_JSON = ean13("200000000009")
BC_RATE = ean13("200000000010")


@pytest.fixture(scope="module", autouse=True)
def seed_local_product(client, H):
    client.post("/api/products", headers=H, json={"barcode": BC_LOCAL, "name": "Local Milk"})


# --- Test 1: local hit ---------------------------------------------------------
def test_01_local_database(client, H, db):
    r = client.get(f"/api/barcode/resolve/{BC_LOCAL}", headers=H)
    assert r.status_code == 200
    body = r.json()
    assert body["origin"] == "local"
    assert body["product"]["name"] == "Local Milk"
    assert body["need_manual"] is False


# --- Test 2: only source A has it ----------------------------------------------
def test_02_source_a_only(db):
    add_source(db, "custom_http:A", "http://a.test/{barcode}")
    with transport(json_handler({BC_A: {"name": "Product A", "brand": "BrandA"}})) as c:
        out = resolvers.resolve_barcode(db, BC_A, client=c)
        db.commit()
    assert out["origin"] == "external"
    assert out["need_manual"] is True
    assert out["merged"]["name"]["chosen"] == "Product A"
    assert out["merged"]["name"]["confidence"] == "MEDIUM"  # single source
    rows = db.execute(select(ProductResolverResult).where(
        ProductResolverResult.barcode == BC_A)).scalars().all()
    fields = {r.field for r in rows}
    assert {"name", "brand", "merged_name", "merged_brand"} <= fields  # candidates + merged proposal
    db.close()


# --- Test 3: only source B has it ----------------------------------------------
def test_03_source_b_only(db):
    add_source(db, "custom_http:B", "http://b.test/{barcode}", priority=200)
    with transport(json_handler({BC_B: {"product_name": "Product B"}})) as c:
        out = resolvers.resolve_barcode(db, BC_B, client=c)
        db.commit()
    assert out["origin"] == "external"
    assert out["merged"]["name"]["chosen"] == "Product B"


# --- Test 4: both sources agree -> HIGH confidence ------------------------------
def test_04_multi_source_agreement(db):
    add_source(db, "custom_http:A", "http://a.test/{barcode}")
    add_source(db, "custom_http:B", "http://b.test/{barcode}", priority=200)
    payload = {"name": "Shared Name", "brand": "SharedBrand"}
    with transport(json_handler({BC_BOTH: payload})) as c:
        out = resolvers.resolve_barcode(db, BC_BOTH, client=c)
        db.commit()
    assert out["origin"] == "external"
    assert out["merged"]["name"]["chosen"] == "Shared Name"
    assert out["merged"]["name"]["confidence"] == "HIGH"
    assert out["merged"]["name"]["conflict"] is False
    assert all(s["ok"] for s in out["sources"])


# --- Test 5: conflicting values -> conflict flagged, LOW confidence -------------
def test_05_conflicting_sources(db):
    add_source(db, "custom_http:A", "http://a.test/{barcode}")
    add_source(db, "custom_http:B", "http://b.test/{barcode}", priority=200)
    routes = {BC_CONFLICT: None}

    def h(request: httpx.Request) -> httpx.Response:
        key = request.url.path.rsplit("/", 1)[-1]
        if "a.test" in request.url.host:
            return httpx.Response(200, json={"name": "Name From A"})
        return httpx.Response(200, json={"name": "Name From B"})

    with transport(h) as c:
        out = resolvers.resolve_barcode(db, BC_CONFLICT, client=c)
        db.commit()
    assert out["merged"]["name"]["conflict"] is True
    assert out["merged"]["name"]["confidence"] == "LOW"
    assert len(out["merged"]["name"]["sources"]) == 2
    assert out["need_manual"] is True  # conflict ALWAYS requires a human


# --- Test 6: no image available --------------------------------------------------
def test_06_no_image(db):
    add_source(db, "custom_http:A", "http://a.test/{barcode}")
    with transport(json_handler({BC_NOIMG: {"name": "No Image Product"}})) as c:
        out = resolvers.resolve_barcode(db, BC_NOIMG, client=c)
        img = resolvers.resolve_image(db, BC_NOIMG, client=c)
        db.commit()
    assert out["origin"] == "external"
    assert img["valid_count"] == 0
    assert img["best"] is None


# --- Test 7: broken image (404 / not-an-image) ----------------------------------
def test_07_broken_image(db):
    add_source(db, "custom_http:A", "http://a.test/{barcode}")
    good_jpeg = b"\xff\xd8\xff" + b"\x00" * 2048

    def h(request: httpx.Request) -> httpx.Response:
        if "/img/ok" in request.url.path:
            return httpx.Response(200, content=good_jpeg, headers={"content-type": "image/jpeg"})
        if "/img/broken" in request.url.path:
            return httpx.Response(200, content=b"<html>not an image" + b"x" * 2048 + b"</html>",
                                  headers={"content-type": "text/html"})
        if "/img/404" in request.url.path:
            return httpx.Response(404)
        key = request.url.path.rsplit("/", 1)[-1]
        return httpx.Response(200, json={"name": "X", "image_url": f"http://a.test/img/{key}"})

    def h_with(request: httpx.Request) -> httpx.Response:
        # barcode resolve returns all three image urls as candidates sequentially
        key = request.url.path.rsplit("/", 1)[-1]
        if key.startswith("7"):
            return httpx.Response(200, json={"name": "X", "image_url": "http://a.test/img/ok"})
        return h(request)

    with transport(h) as c:
        ok = resolvers.validate_image_url("http://a.test/img/ok", client=c)
        broken = resolvers.validate_image_url("http://a.test/img/broken", client=c)
        missing = resolvers.validate_image_url("http://a.test/img/404", client=c)
    assert ok == {"ok": True, "format": "JPEG", "bytes": len(good_jpeg)}
    assert broken["ok"] is False and broken["reason"] == "NOT_AN_IMAGE"
    assert missing["ok"] is False and missing["reason"] == "HTTP_404"


# --- Test 8: unknown barcode -----------------------------------------------------
def test_08_unknown_barcode(db):
    add_source(db, "custom_http:A", "http://a.test/{barcode}")
    with transport(json_handler({})) as c:  # everything 404
        out = resolvers.resolve_barcode(db, BC_UNKNOWN, client=c)
        db.commit()
    assert out["origin"] == "none"
    assert out["need_manual"] is True
    assert out["sources"][0]["error"]["kind"] == "NOT_FOUND"
    # invalid checksum never reaches providers at all
    bad = resolvers.resolve_barcode(db, "1234567890123")  # checksum-invalid
    assert bad["origin"] == "invalid"


# --- Test 9: external API timeout --------------------------------------------------
def test_09_timeout(db):
    add_source(db, "custom_http:A", "http://a.test/{barcode}")

    def h(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("simulated timeout")

    with transport(h) as c:
        out = resolvers.resolve_barcode(db, BC_TIMEOUT, client=c)
        db.commit()
    assert out["origin"] == "none"  # timeout != fake success
    assert out["sources"][0]["error"]["kind"] == "TIMEOUT"
    assert out["need_manual"] is True


# --- Test 10: API down (unreachable) -----------------------------------------------
def test_10_api_down(db):
    add_source(db, "custom_http:A", "http://a.test/{barcode}")

    def h(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    with transport(h) as c:
        out = resolvers.resolve_barcode(db, BC_DOWN, client=c)
        db.commit()
    assert out["sources"][0]["error"]["kind"] == "UNREACHABLE"
    assert out["origin"] == "none"


# --- Test 11: invalid response (non-JSON) -------------------------------------------
def test_11_invalid_response(db):
    add_source(db, "custom_http:A", "http://a.test/{barcode}")

    def h(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>maintenance page</html>",
                              headers={"content-type": "text/html"})

    with transport(h) as c:
        out = resolvers.resolve_barcode(db, BC_INVALID_JSON, client=c)
        db.commit()
    assert out["sources"][0]["error"]["kind"] == "INVALID_RESPONSE"


# --- Test 12: rate limited ------------------------------------------------------------
def test_12_rate_limited(db):
    add_source(db, "custom_http:A", "http://a.test/{barcode}")

    def h(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": "rate limit"})

    with transport(h) as c:
        out = resolvers.resolve_barcode(db, BC_RATE, client=c)
        db.commit()
    assert out["sources"][0]["error"]["kind"] == "RATE_LIMITED"
    assert out["origin"] == "none"


# --- Test 13: duplicate product (barcode already exists) -------------------------------
def test_13_duplicate_product(client, H, db):
    # BC_LOCAL exists; the pipeline must answer "local" without any external call
    with transport(json_handler({BC_LOCAL: {"name": "Sneaky Duplicate"}})) as c:
        out = resolvers.resolve_barcode(db, BC_LOCAL, client=c)
    assert out["origin"] == "local"
    assert out["product"]["name"] == "Local Milk"
    # apply() for an existing barcode is refused
    r = client.post("/api/barcode/apply", headers=H, json={"barcode": BC_LOCAL, "name": "Dup"})
    assert r.status_code == 409


# --- Source management API (BUG-008) ---------------------------------------------------
def test_sources_crud(client, H):
    r = client.get("/api/barcode/sources/providers", headers=H)
    assert r.status_code == 200
    codes = {p["code"] for p in r.json()}
    assert {"openfoodfacts", "custom_http"} <= codes

    r = client.post("/api/barcode/sources", headers=H, json={
        "code": "custom_http:testsrc", "name": "Test Source", "source_type": "PRODUCT",
        "base_url": "http://x.test/{barcode}"})
    assert r.status_code == 201, r.text
    sid = r.json()["id"]
    r = client.patch(f"/api/barcode/sources/{sid}", headers=H, json={"is_active": False})
    assert r.json()["is_active"] is False
    r = client.delete(f"/api/barcode/sources/{sid}", headers=H)
    assert r.status_code == 204
    # unknown provider code rejected
    r = client.post("/api/barcode/sources", headers=H, json={
        "code": "nonexistent", "name": "X", "source_type": "PRODUCT"})
    assert r.status_code == 400


# --- POST endpoint persists (BUG-006 fix, endpoint level) ------------------------------
def test_post_resolve_persists_candidates(client, H, db, monkeypatch):
    add_source(db, "custom_http:persist", "http://p.test/{barcode}")
    bc = ean13("310000000001")

    def h(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"name": "Persisted Product", "brand": "PBrand"})

    import app.services.providers.base as pbase
    real_client = httpx.Client
    monkeypatch.setattr(pbase.httpx, "Client", lambda *a, **k: real_client(transport=httpx.MockTransport(h)))

    r = client.post(f"/api/barcode/resolve/{bc}", headers=H)
    assert r.status_code == 200
    body = r.json()
    assert body["origin"] == "external"
    assert body["need_manual"] is True

    db2 = SessionLocal()
    rows = db2.execute(select(ProductResolverResult).where(
        ProductResolverResult.barcode == bc)).scalars().all()
    db2.close()
    assert len(rows) >= 3  # name + brand + merged_name — persisted by the endpoint
    monkeypatch.undo()


# --- Human review + apply flow (§9 end-to-end) ----------------------------------------
def test_review_and_apply_flow(client, H, db):
    add_source(db, "custom_http:flow", "http://f.test/{barcode}")
    bc = ean13("320000000001")
    with transport(json_handler({bc: {"name": "Flow Product", "brand": "FlowBrand",
                                      "image_url": "http://f.test/img/ok"}})) as c:
        out = resolvers.resolve_barcode(db, bc, client=c)
        db.commit()
    merged_name_id = next(r.id for r in db.execute(
        select(ProductResolverResult).where(ProductResolverResult.barcode == bc,
                                            ProductResolverResult.field == "merged_name")).scalars())
    # approve merged_name via the review endpoint
    r = client.post(f"/api/barcode/results/{merged_name_id}/review", headers=H,
                    json={"approved": True, "reason": "looks correct"})
    assert r.status_code == 200 and r.json()["status"] == "APPROVED"
    # apply (human-edited name is allowed — final authority is the human)
    r = client.post("/api/barcode/apply", headers=H, json={
        "barcode": bc, "name": "Flow Product 500g", "brand": "FlowBrand",
        "review_ids": [merged_name_id]})
    assert r.status_code == 201, r.text
    pid = r.json()["product"]["id"]
    # after apply the barcode resolves straight from the local DB (no providers)
    out2 = resolvers.resolve_barcode(db, bc)
    assert out2["origin"] == "local"
    assert out2["product"]["id"] == pid
    assert out2["product"]["name"] == "Flow Product 500g"
    assert out2["need_manual"] is False
    # rejected results stay rejected
    r2 = client.post(f"/api/barcode/results/{merged_name_id}/review", headers=H, json={"approved": False})
    assert r2.status_code == 409


# --- Market price resolution (§15) ------------------------------------------------------
def test_market_price_resolution(db):
    bc = ean13("330000000001")
    add_source(db, "custom_http:pr1", "http://pr1.test/{barcode}", source_type="PRICE", priority=10)
    add_source(db, "custom_http:pr2", "http://pr2.test/{barcode}", source_type="PRICE", priority=20)

    def h(request: httpx.Request) -> httpx.Response:
        if "pr1" in request.url.host:
            return httpx.Response(200, json={"price": 10000})
        return httpx.Response(200, json={"price": 12000})

    with transport(h) as c:
        out = resolvers.resolve_market_price(db, bc, client=c)
        db.commit()
    assert out["aggregate"]["count"] == 2
    assert out["aggregate"]["min"] == 10000.0
    assert out["aggregate"]["max"] == 12000.0
    rows = db.execute(select(MarketPrice).where(MarketPrice.barcode == bc)).scalars().all()
    assert len(rows) == 2
