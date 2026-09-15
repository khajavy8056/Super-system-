"""v3.5 — the default product bank replaces web lookups.

Two things were removed in this release and this module is the regression guard
for both:

1. **no web picture hunt.** v2.5–v3.4 searched OpenFoodFacts, Wikimedia Commons,
   Wikipedia and DuckDuckGo for a photo by product name, and v2.6 additionally
   scraped Basalam/Torob listings. All of it is gone — the bank ships its own
   pictures.
2. **no online barcode identification by default.** Earlier releases registered
   ``retail_ir`` + ``openfoodfacts`` on first boot. ``DEFAULT_SOURCES`` is now
   empty and the legacy rows are switched off on upgrade, so a scan that is not
   in the bank is typed once instead of being sent to a third party.

Plus the bank itself: 13 570 lines, exact GTINs, category tree, pictures, zero
stock, idempotent re-import.
"""
from __future__ import annotations

import csv
import io
import re
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.database import SessionLocal
from app.models import Category, Product, ProductBatch
from app.models.external import ExternalSource
from app.services import default_catalog, product_images, resolvers
from app.services.providers import REGISTRY

ROOT = Path(__file__).resolve().parents[2]
CSV_PATH = ROOT / "backend" / "app" / "data" / "default_catalog.csv"
ANDROID_CSV = ROOT / "mobile-android" / "app" / "src" / "main" / "assets" / "default_catalog.csv"
SHEETS = sorted((ROOT / "docs").glob("*.xlsx"))


@pytest.fixture
def db(client):
    s = SessionLocal()
    yield s
    s.close()


# ---------------------------------------------------------------- the bank itself
def test_bank_file_ships_thirteen_thousand_plus_lines():
    assert len(SHEETS) == 13, "the 13 Excel sheets must still be in docs/"
    assert CSV_PATH.exists(), "run scripts/build_default_catalog.py"
    rows = list(csv.DictReader(io.StringIO(CSV_PATH.read_text(encoding="utf-8"))))
    assert len(rows) >= 13000, f"only {len(rows)} lines"
    assert default_catalog.COLUMNS == list(rows[0].keys())


def test_android_carries_the_same_bank():
    """The phone is offline-first: it must bundle the identical file."""
    assert ANDROID_CSV.exists()
    assert ANDROID_CSV.read_bytes() == CSV_PATH.read_bytes()


def test_every_line_has_a_name_a_category_and_a_valid_barcode():
    def check_digit(body: str) -> int:
        return (10 - sum(int(c) * (3 if i % 2 == 0 else 1)
                         for i, c in enumerate(reversed(body))) % 10) % 10

    bad: list[str] = []
    seen: set[str] = set()
    for i, r in enumerate(csv.DictReader(io.StringIO(CSV_PATH.read_text(encoding="utf-8"))), start=2):
        if not r["name"].strip():
            bad.append(f"line {i}: no name")
        if not r["category"].strip():
            bad.append(f"line {i}: no category")
        bc = r["barcode"]
        if not bc:
            bad.append(f"line {i}: no barcode")
        elif bc in seen:
            bad.append(f"line {i}: duplicate barcode {bc}")
        seen.add(bc)
        d = re.sub(r"\D", "", bc)
        if not bc.startswith("INT-"):
            if len(d) == 13 and check_digit(d[:12]) != int(d[12]):
                bad.append(f"line {i}: bad EAN-13 {bc}")
            elif len(d) not in (8, 13):
                bad.append(f"line {i}: odd length {bc}")
    assert not bad, bad[:10]


def test_most_lines_carry_a_direct_picture_link():
    rows = list(csv.DictReader(io.StringIO(CSV_PATH.read_text(encoding="utf-8"))))
    with_img = [r for r in rows if (r["image_url"] or "").strip()]
    assert len(with_img) >= int(len(rows) * 0.99), "the bank must ship its own pictures"
    multi = sum(1 for r in rows if len([u for u in (r["images"] or "").split("|") if u]) >= 2)
    assert multi > 5000, "many lines carry two or three pictures"
    for r in with_img[:50]:
        urls = [u for u in (r["images"] or "").split("|") if u]
        assert r["image_url"] == urls[0], "image_url must be the first gallery entry"
        assert all(u.startswith("http") for u in urls)


def test_builder_check_mode_verifies_the_shipped_file():
    """``scripts/build_default_catalog.py --check`` is what CI can run without writing."""
    import subprocess
    import sys
    out = subprocess.run([sys.executable, str(ROOT / "scripts" / "build_default_catalog.py"), "--check"],
                         capture_output=True, text=True, cwd=str(ROOT))
    assert out.returncode == 0, out.stdout + out.stderr
    assert "verify: OK" in out.stdout


# ------------------------------------------------------------------- the import
def test_import_creates_the_whole_bank_with_zero_stock(client, auth_headers, db):
    batches_before = db.execute(select(func.count(ProductBatch.id))).scalar()
    products_before = db.execute(select(func.count(Product.id))).scalar()
    res = default_catalog.import_csv(db)
    db.commit()
    assert res["ok"] is True, res
    assert res["created"] + res["skipped"] >= 13000, res
    assert res["errors"] == []
    assert db.execute(select(func.count(Product.id))).scalar() - products_before == res["created"]
    # §80 — the import itself must not create stock (other tests in this session
    # have their own batches, so compare against the count from before).
    assert db.execute(select(func.count(ProductBatch.id))).scalar() == batches_before
    # categories are a real tree (top level + children)
    tops = db.execute(select(func.count(Category.id)).where(Category.parent_id.is_(None))).scalar()
    kids = db.execute(select(func.count(Category.id)).where(Category.parent_id.isnot(None))).scalar()
    assert tops >= 30 and kids >= 100
    # pictures came with the product, not from a search
    assert db.execute(select(func.count(Product.id)).where(Product.image_url.isnot(None))).scalar() >= 13000
    assert db.execute(select(func.count(Product.id)).where(Product.gallery.isnot(None))).scalar() > 5000


def test_reimport_is_idempotent(client, auth_headers, db):
    default_catalog.import_csv(db)
    db.commit()
    before = db.execute(select(func.count(Product.id))).scalar()
    second = default_catalog.import_csv(db)
    db.commit()
    assert second["created"] == 0, second
    assert db.execute(select(func.count(Product.id))).scalar() == before


def test_a_shop_product_with_the_same_barcode_is_never_duplicated(client, auth_headers, db):
    """The bank must not fight a code the shop already typed."""
    from app.services import catalog
    bc = "2099111222334"          # not in the bank; stands in for a shop-typed line
    csv_text = ("category,subcategory,name,brand,unit,min_stock_alert,barcode,image_url,images\n"
                f"لبنیات,شیر,شیر تست بانک,,عدد,0,{bc},https://example.test/x.webp,https://example.test/x.webp\n")
    if db.execute(select(Product).where(Product.barcode == bc)).scalar_one_or_none() is not None:
        pytest.skip("barcode already present from an earlier run of this session")
    p = catalog.create_product(db, barcode=bc, name="کالای خود فروشگاه")
    db.commit()
    res = default_catalog.import_csv(db, csv_text)
    db.commit()
    assert res["created"] == 0 and res["skipped_duplicate_barcode"] == 1, res
    rows = db.execute(select(Product).where(Product.barcode == bc)).scalars().all()
    assert len(rows) == 1 and rows[0].id == p.id


def test_summary_endpoint_reports_the_bank(client, auth_headers):
    r = client.get("/api/products/import/default", headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["products"] >= 13000 and body["categories"] >= 30
    assert body["stock"] == 0
    assert "products_in_shop" in body


def test_import_endpoint_and_legacy_route_stay_compatible(client, auth_headers):
    """Older clients still GET/POST /import/starter; both routes must behave alike."""
    dry = client.post("/api/products/import/default?dry_run=true", headers=auth_headers).json()
    assert dry["ok"] is True and dry["dry_run"] is True
    assert dry["created"] + dry["skipped"] >= 13000, dry
    legacy = client.get("/api/products/import/starter", headers=auth_headers)
    assert legacy.status_code == 200 and legacy.json()["products"] >= 13000
    real = client.post("/api/products/import/default", headers=auth_headers).json()
    assert real["ok"] is True and real["created"] + real["skipped"] >= 13000, real


# ------------------------------------------------- web lookups are really gone
def test_no_web_search_providers_are_registered():
    assert "retail_ir" not in REGISTRY, "the Basalam/Torob scraper must be gone"
    assert "openfoodfacts" not in REGISTRY, "the OpenFoodFacts provider must be gone"
    # the generic shop-configured provider stays available
    assert "custom_http" in REGISTRY


def test_no_default_external_sources_and_legacy_rows_are_retired(db):
    from app.bootstrap import DEFAULT_SOURCES, LEGACY_ONLINE_SOURCES, ensure_default_sources
    assert DEFAULT_SOURCES == []
    # simulate a shop that upgraded from v3.4: it has an ACTIVE retail_ir row
    for code in LEGACY_ONLINE_SOURCES:
        if db.execute(select(ExternalSource).where(ExternalSource.code == code)).scalar_one_or_none() is None:
            db.add(ExternalSource(code=code, name=code, source_type="PRODUCT", base_url="http://x/{barcode}",
                                  is_active=True))
    db.commit()
    ensure_default_sources(db)
    db.commit()
    still_on = [s.code for s in db.execute(
        select(ExternalSource).where(ExternalSource.code.in_(LEGACY_ONLINE_SOURCES),
                                     ExternalSource.is_active.is_(True))).scalars()]
    assert still_on == [], "an upgraded shop must stop calling those sites"


def test_unknown_barcode_is_not_sent_anywhere(db):
    """With no source registered the resolver answers locally and touches no network."""
    out = resolvers.resolve_barcode(db, "6260000000194")   # valid EAN-13, not in the bank
    assert out["origin"] == "none", out
    assert out["sources"] == []
    assert out["need_manual"] is True and "بانک کالا" in (out["message"] or "")


def test_picture_pipeline_never_searches_the_web(db):
    assert product_images.online_enabled() is False
    p = Product(id=1, barcode="6260000000194", name="شیر پرچرب میهن", image_url=None)
    assert product_images.find_and_store(db, p) == {"ok": False, "reason": "NO_REMOTE_IMAGE", "tried": 0}
    assert product_images.backfill(db) == {"queued": 0, "reason": "OFFLINE_MODE"}
    assert product_images.list_candidates(db, p) == []


def test_mirror_remote_stores_the_shipped_picture_locally(db, monkeypatch):
    """§21 — image_url ends up a LOCAL path, never a hot link to someone else's CDN."""
    jpeg = b"\xff\xd8\xff" + b"\x00" * 4096 + b"\xff\xd9"
    monkeypatch.setattr(resolvers, "_fetch_image",
                        lambda url, client=None: ({"ok": True, "format": "JPEG",
                                                   "width": 64, "height": 64}, jpeg))
    p = Product(barcode="6260000000194", name="شیر پرچرب میهن",
                image_url="https://example.test/a.webp",
                gallery='["https://example.test/a.webp", "https://example.test/b.webp"]')
    db.add(p)
    db.flush()
    rep = product_images.mirror_remote(db, p)
    assert rep["ok"] is True and rep["reason"] == "STORED", rep
    assert p.image_url.startswith("/media/"), p.image_url


def test_gallery_survives_the_api_round_trip(client, auth_headers, db):
    p = next(r for r in csv.DictReader(io.StringIO(CSV_PATH.read_text(encoding="utf-8")))
             if len([u for u in (r["images"] or "").split("|") if u]) >= 2)
    res = default_catalog.import_csv(db)
    db.commit()
    got = client.get(f"/api/products/barcode/{p['barcode']}", headers=auth_headers).json()
    assert len(got["gallery"]) >= 2, got
    assert got["image_url"] == got["gallery"][0]
    assert res["created"] >= 0


def test_image_picker_offers_the_shipped_pictures_not_the_web(client, auth_headers, db):
    p = next(r for r in csv.DictReader(io.StringIO(CSV_PATH.read_text(encoding="utf-8")))
             if len([u for u in (r["images"] or "").split("|") if u]) >= 2)
    default_catalog.import_csv(db)
    db.commit()
    row = db.execute(select(Product).where(Product.barcode == p["barcode"])).scalar_one()
    body = client.get(f"/api/products/{row.id}/image/candidates", headers=auth_headers).json()
    assert body["web_lookup"] is False
    assert len(body["candidates"]) >= 2
    assert all(c["source"] == "bank" for c in body["candidates"])


def test_images_status_reports_no_web_lookup(client, auth_headers):
    body = client.get("/api/products/images/status", headers=auth_headers).json()
    assert body["web_fallback"] is False and body["web_lookup"] is False


# ---------------------------------------------------------------------------
# v3.5 — the till sorts by what is actually on the shelf
# ---------------------------------------------------------------------------
def test_product_search_puts_in_stock_items_first(client, auth_headers, db):
    """With a 13 570-line bank an alphabetical list buries the items the shop
    actually stocks under hundreds of rows it does not. The till must therefore
    sort sellable items first and fall back to alphabetical order inside each
    group."""
    from datetime import date, timedelta
    import uuid

    tag = uuid.uuid4().hex[:6]
    # «آ» sorts before «ب», so alphabetically the out-of-stock item wins.
    names = [f"آزمون موجودی {tag}", f"بزمون موجودی {tag}"]
    ids = []
    for nm in names:
        r = client.post("/api/products", headers=auth_headers, json={
            "name": nm, "barcode": None, "unit_id": None, "min_stock_alert": 0})
        assert r.status_code == 201, r.text
        ids.append(r.json()["id"])
    oos_id, in_stock_id = ids

    # give only the alphabetically-LATER product some sellable stock
    r = client.post("/api/batches/receive", headers=auth_headers, json={
        "product_id": in_stock_id, "quantity_received": 5, "buy_price": 1000,
        "sell_price": 2000, "consumer_price": 2000,
        "expiry_date": (date.today() + timedelta(days=30)).isoformat()})
    assert r.status_code == 201, r.text

    body = client.get("/api/products", headers=auth_headers,
                      params={"q": tag, "limit": 50}).json()
    order = [p["id"] for p in body["items"]]
    assert order == [in_stock_id, oos_id], \
        f"in-stock item must come first, got {order}"
    by_id = {p["id"]: p for p in body["items"]}
    assert by_id[in_stock_id]["in_stock"] is True and by_id[in_stock_id]["stock_qty"] == 5
    assert by_id[oos_id]["in_stock"] is False and by_id[oos_id]["stock_qty"] == 0

    # alphabetical order is preserved inside each group
    assert body["items"][0]["name"] > body["items"][1]["name"]

    # and it can be turned off for the plain catalogue view
    plain = client.get("/api/products", headers=auth_headers,
                       params={"q": tag, "limit": 50, "in_stock_first": False}).json()
    assert [p["id"] for p in plain["items"]] == [oos_id, in_stock_id]
