"""v2.7 — بانک کالا: offline barcode → name/brand bank on PC, shared to phones over /mobile/sync."""
from __future__ import annotations

import io
import zipfile

import httpx
import pytest

from app.database import SessionLocal
from app.models import BankItem
from app.services import product_bank as bank
from app.services import resolvers

BASALAM_HIT = {"meta": {"count": 1}, "products": [{
    "id": 1, "name": "خامه صبحانه پگاه 200 گرم – 6260007424016", "mainAttribute": "200 گرم",
    "categoryTitle": "خامه و سرشیر", "photo": {"MEDIUM": "https://statics.basalam.com/x/KkYp.jpg_512X512X70.jpg"},
    "vendor": {"name": "x"}}]}


@pytest.fixture
def db_session(client):
    s = SessionLocal(); yield s; s.close()


def _clear(s):
    s.query(BankItem).delete(); s.commit()


def test_seeded_at_bootstrap(db_session):
    st = bank.stats(db_session)
    assert st["total"] >= 20 and st["by_source"].get("SEED", 0) >= 20
    hit = bank.lookup(db_session, "۶۲۶۰۴۹۲۶۱۰۰۸۶")          # Persian digits normalised
    assert hit and "نستله" in hit["name"] and hit["brand"] == "نستله"


def test_remember_ranking_and_validation(db_session):
    _clear(db_session)
    assert bank.remember(db_session, "2099000000019", "in-store") is None        # in-store prefix rejected
    assert bank.remember(db_session, "6260001", "short") is None
    bank.remember(db_session, "6261149010631", "بیسکویت شیرین عسل", source="ONLINE")
    bank.remember(db_session, "6261149010631", "بیسکویت نارگیلی شیرین عسل", brand="شیرین عسل", source="USER")
    bank.remember(db_session, "6261149010631", "چیز دیگر", unit="100 g", source="ONLINE")   # lower rank: name kept, unit filled
    row = bank.lookup(db_session, "6261149010631")
    assert row["name"] == "بیسکویت نارگیلی شیرین عسل" and row["source"] == "USER" and row["confidence"] == "HIGH"
    assert row["brand"] == "شیرین عسل" and row["unit"] == "100 g"


def test_resolver_uses_bank_first_and_remembers_online_hits(db_session):
    """A shop-registered source is still consulted; its hit is remembered offline.

    v3.5: the bank used to be fed by the bundled Basalam provider. That provider
    is gone, so the test registers its own ``custom_http`` source — which is
    exactly how a shop that runs its own identification service would do it —
    and asserts the remember-then-offline behaviour is unchanged.
    """
    from app.models import ExternalSource
    _clear(db_session)
    calls = []

    if db_session.query(ExternalSource).filter_by(code="bank_test_src").first() is None:
        db_session.add(ExternalSource(code="bank_test_src", name="Bank test", source_type="PRODUCT",
                                      base_url="https://svc.test/{barcode}", priority=5, is_active=True))
    else:
        db_session.query(ExternalSource).filter_by(code="bank_test_src").update({"is_active": True})
    db_session.commit()

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(req.url.host)
        return httpx.Response(200, json={"name": "خامه صبحانه پگاه 200 گرم",
                                         "image_url": "https://svc.test/img/1.jpg"})

    c = httpx.Client(transport=httpx.MockTransport(handler))
    try:
        r1 = resolvers.resolve_barcode(db_session, "6260007424016", client=c)
        assert r1["origin"] == "external" and calls
        row = bank.lookup(db_session, "6260007424016")
        assert row and row["name"] == "خامه صبحانه پگاه 200 گرم" and row["source"] == "ONLINE" and row["image_url"]
        calls.clear()
        r2 = resolvers.resolve_barcode(db_session, "6260007424016", client=c)
        assert r2["origin"] == "bank" and r2["merged"]["name"]["chosen"] == "خامه صبحانه پگاه 200 گرم"
        assert r2["image_url"] and calls == []                                   # second scan: no network
    finally:
        db_session.query(ExternalSource).filter_by(code="bank_test_src").update({"is_active": False})
        db_session.commit()


def test_product_create_teaches_bank_and_api(client, auth_headers, db_session):
    r = client.post("/api/products", json={"barcode": "6260007424099", "name": "ماست پگاه ۹۰۰ گرمی"}, headers=auth_headers)
    assert r.status_code in (200, 201), r.text
    r = client.get("/api/bank/lookup/6260007424099", headers=auth_headers)
    assert r.status_code == 200 and r.json()["source"] == "USER"
    assert client.get("/api/bank/lookup/6260000000000", headers=auth_headers).status_code == 404
    assert client.get("/api/bank/stats", headers=auth_headers).json()["total"] >= 1
    csv_out = client.get("/api/bank/export.csv", headers=auth_headers)
    assert csv_out.status_code == 200 and "6260007424099" in csv_out.text


def test_import_csv_persian_headers_and_xlsx(client, auth_headers, db_session):
    csv_text = "بارکد;نام کالا;برند\n6262004907516;سس کچاپ کاله ۷۰۰ گرمی;کاله\n۶۲۶۰۱۶۱۵۲۶۷۶۲;ماست پرو کاله;کاله\nabc;bad;x\n"
    r = client.post("/api/bank/import", files={"file": ("bank.csv", csv_text.encode("utf-8"), "text/csv")}, headers=auth_headers)
    assert r.status_code == 200, r.text
    j = r.json(); assert j["added"] + j["updated"] == 2 and j["skipped"] == 1
    assert bank.lookup(db_session, "6260161526762")["source"] == "IMPORT"

    # minimal xlsx without openpyxl: inline strings + numeric barcode cell
    sheet = ('<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'
             '<row r="1"><c r="A1" t="inlineStr"><is><t>barcode</t></is></c><c r="B1" t="inlineStr"><is><t>name</t></is></c></row>'
             '<row r="2"><c r="A2"><v>6260918600349</v></c><c r="B2" t="inlineStr"><is><t>پنیر کیبی</t></is></c></row>'
             '</sheetData></worksheet>')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("xl/worksheets/sheet1.xml", sheet)
    r = client.post("/api/bank/import", files={"file": ("bank.xlsx", buf.getvalue(), "application/octet-stream")}, headers=auth_headers)
    assert r.status_code == 200, r.text
    db_session.expire_all()
    assert bank.lookup(db_session, "6260918600349")["name"] == "پنیر کیبی"

    r = client.post("/api/bank/import", files={"file": ("x.csv", b"a,b\n1,2\n", "text/csv")}, headers=auth_headers)
    assert r.status_code == 400


def test_mobile_sync_pulls_bank_and_accepts_bank_remember(client, auth_headers, db_session):
    r = client.post("/api/mobile/sync", json={"device_id": "t1", "cursor": None, "pull": True, "limit": 2000,
                                              "push": [{"id": "op-bank-1", "type": "BANK_REMEMBER",
                                                        "payload": {"barcode": "6260360010147", "name": "ویفر کوپا فندقی", "brand": "کوپا", "source": "USER"}}]},
                    headers=auth_headers)
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["applied"][0]["status"] == "APPLIED"
    codes = {b["barcode"]: b for b in j["pull"]["bank"]}
    assert "6260360010147" in codes and codes["6260360010147"]["source"] == "USER"
    assert "6260918600349" in codes                                              # imported rows travel to the phone too
    # incremental: nothing new after the cursor
    r2 = client.post("/api/mobile/sync", json={"device_id": "t1", "cursor": j["cursor"], "pull": True, "push": []}, headers=auth_headers)
    assert all(b["updated_at"] >= j["cursor"][:19] for b in r2.json()["pull"]["bank"])
