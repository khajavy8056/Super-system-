"""v3.4 — product bank from the shop's Excel folders + catalog.pack for phones."""
import struct
from pathlib import Path

import pytest
from sqlalchemy import select

from app.models import Category, Product
from app.services import catalog_folder as cf


@pytest.fixture
def db_session(client):
    from app.database import SessionLocal
    with SessionLocal() as s:
        yield s


@pytest.fixture
def admin_headers(auth_headers):
    return auth_headers


@pytest.fixture
def tree(tmp_path):
    cf.make_sample(tmp_path)
    # a second folder with nested depth + a csv + jpg-only picture + a `pics` folder name
    d = tmp_path / "شیرینی‌جات و دسر" / "بیسکویت"
    (d / "pics").mkdir(parents=True)
    (d / "list.csv").write_text("نام محصول,دسته,زیر دسته,بارکد,تصویر 1\nبیسکویت ساقه طلایی,شیرینی‌جات,بیسکویت,6260109000010,6260109000010.jpg\n", encoding="utf-8")
    (d / "pics" / "6260109000010.jpg").write_bytes(b"\xff\xd8\xff\xe0jpegjpeg")
    return tmp_path


def test_scan_resolves_webp_for_jpg_names_and_reports_missing(tree):
    res = cf.scan(tree)
    assert res["sheets"] == 2 and res["rows"] == 4
    rows = {r.barcode: r for r in res["_rows"]}
    assert rows["6260100103955"].found[0].name == "1532933656.webp"          # sheet says .jpg → file is .webp
    assert rows["6260200610254"].found[0].name == "6260200610254(1).webp"    # "(1)" variant
    assert rows["6260109000010"].found[0].suffix == ".jpg"                   # jpg accepted too, from `pics`
    assert not rows["6262477320553"].found
    assert res["with_image"] == 3 and res["without_image"] == 1
    assert res["missing"][0]["barcode"] == "6262477320553"


def test_import_creates_products_categories_bank_and_images(tree, db_session, tmp_path, monkeypatch):
    monkeypatch.setattr(cf.settings, "MEDIA_DIR", str(tmp_path / "media"))
    res = cf.import_folder(db_session, tree)
    assert res["created"] == 4 and res["images"] == 3 and not res["errors"]
    p = db_session.execute(select(Product).where(Product.barcode == "6260100103955")).scalar_one()
    assert p.name == "چوب شور 30 گرمی مینو" and p.image_url == "/media/catalog/6260100103955.webp"
    assert (tmp_path / "media" / "catalog" / "6260100103955.webp").is_file()
    sub = db_session.get(Category, p.category_id)
    assert sub.name == "چوب شور" and db_session.get(Category, sub.parent_id).name == "تنقلات"
    from app.services import product_bank
    assert product_bank.lookup(db_session, "6260200610254")["name"] == "لواشک آلو 30 گرمی گلین"
    # re-run: idempotent, hand-set pictures are kept
    p.image_url = "/media/products/manual.jpg"; db_session.commit()
    res2 = cf.import_folder(db_session, tree)
    assert res2["created"] == 0
    db_session.refresh(p)
    assert p.image_url == "/media/products/manual.jpg"
    assert cf.last_state(db_session)["rows"] == 4


def test_pack_roundtrip(tree, db_session, tmp_path, monkeypatch):
    monkeypatch.setattr(cf.settings, "MEDIA_DIR", str(tmp_path / "media"))
    cf.import_folder(db_session, tree, replace_images=True)
    out = tmp_path / "catalog.pack"
    info = cf.export_pack(db_session, out)
    assert info["images"] == 3 and out.is_file()
    idx = cf.read_pack_index(out)
    assert idx["db"][:15] == b"SQLite format 3"
    off, ln = idx["index"]["6260100103955"]
    img = cf.read_pack_image(out, off, ln)
    assert img[:4] == b"RIFF" and len(img) == ln
    import sqlite3
    dbf = tmp_path / "x.db"; dbf.write_bytes(idx["db"])
    con = sqlite3.connect(dbf)
    assert con.execute("SELECT name, category, subcategory, has_image FROM items WHERE barcode='6260100103955'").fetchone() == ("چوب شور 30 گرمی مینو", "تنقلات", "چوب شور", 1)
    assert int(dict(con.execute("SELECT k,v FROM meta").fetchall())["items"]) >= 4


def test_api_endpoints(client, admin_headers, tree, tmp_path, monkeypatch):
    monkeypatch.setattr(cf.settings, "MEDIA_DIR", str(tmp_path / "media"))
    monkeypatch.setattr(cf, "default_root", lambda: tree)
    monkeypatch.setattr(cf, "pack_path", lambda: tmp_path / "catalog.pack")
    r = client.get("/api/catalog/folder", headers=admin_headers)
    assert r.status_code == 200 and r.json()["root"] == str(tree)
    r = client.post("/api/catalog/folder/scan", headers=admin_headers, json={})
    assert r.status_code == 200 and r.json()["rows"] == 4


def test_online_lookups_are_off_in_production(monkeypatch, db_session):
    """v3.5 — there is no web lookup to switch off any more; it is simply gone.

    The ``SUPERMARKET_ONLINE_LOOKUPS`` env flag used to be the kill-switch. With
    the picture hunt removed and ``DEFAULT_SOURCES`` empty, the honest assertions
    are that the pipeline is unconditionally offline and that no source is
    consulted unless a shop registers one itself.
    """
    from app.bootstrap import DEFAULT_SOURCES
    from app.services import product_images, resolvers
    monkeypatch.setenv("SUPERMARKET_ONLINE_LOOKUPS", "1")   # even "on" changes nothing now

    assert DEFAULT_SOURCES == []
    assert product_images.online_enabled() is False
    assert product_images.backfill(db_session)["reason"] == "OFFLINE_MODE"
    r = resolvers.resolve_barcode(db_session, "6260000099999")
    assert r["origin"] != "external"
    assert r.get("sources", []) == []
