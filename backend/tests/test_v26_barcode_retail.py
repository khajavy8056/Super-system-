"""v2.6 — Iranian barcode → product identification through marketplace listings.

Response shapes are the ones captured live on 2026-09-12 from the public search
endpoints (Basalam / Torob) for GTINs 6260007424016 and 6263812801249.
"""
from __future__ import annotations

import json

import httpx
import pytest
from sqlalchemy import select

from app.database import SessionLocal
from app.models.external import ExternalSource
from app.services.providers import REGISTRY
from app.services.providers.base import ProviderError
from app.services.providers.retail_ir import RetailIrProvider, clean_title, parse_shop, title_has_barcode
from app.services import product_images as pi
from app.services import resolvers

BASALAM_HIT = {"meta": {"count": 1}, "products": [{
    "id": 35223354, "name": "خامه صبحانه پگاه 200 گرم – 6260007424016", "mainAttribute": "200 گرم",
    "categoryTitle": "خامه و سرشیر",
    "photo": {"MEDIUM": "https://statics.basalam.com/x/KkYp.jpg_512X512X70.jpg", "SMALL": "https://statics.basalam.com/x/KkYp.jpg_256X256X70.jpg"},
    "vendor": {"name": "مرکز خرید کوثر قم"}}]}
BASALAM_FUZZY = {"meta": {"count": 2}, "products": [
    {"id": 1, "name": "شیر پرچرب کاله یک لیتری", "photo": {"MEDIUM": "https://statics.basalam.com/x/milk.jpg"}},
    {"id": 2, "name": "کاسه شیر سرامیکی", "photo": {"MEDIUM": "https://statics.basalam.com/x/bowl.jpg"}},
]}
TOROB_ONE = {"results": [{"name1": "خامه صبحانه پگاه ۲۰۰ گرم", "image_url": "https://image.torob.com/base/images/Ub/iL/UbiL.jpg"}],
             "count": 1, "categories": [{"title": "خامه"}]}
TOROB_MANY = {"results": [{"name1": "الف", "image_url": "https://image.torob.com/a.jpg"}, {"name1": "ب", "image_url": "https://image.torob.com/b.jpg"}], "count": 2}


@pytest.fixture
def db_session(client):
    s = SessionLocal(); yield s; s.close()


class Src:
    def __init__(self, connection=None):
        self.code = "retail_ir"; self.base_url = None; self.api_key = None; self.connection = connection


def client_for(basalam=None, torob=None, status=200):
    def handler(req: httpx.Request) -> httpx.Response:
        if "basalam.com" in req.url.host:
            return httpx.Response(status, json=basalam or {"products": []})
        if "torob.com" in req.url.host:
            return httpx.Response(status, json=torob or {"results": []})
        return httpx.Response(404)
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_registered_and_default_source(db_session):
    assert REGISTRY["retail_ir"] is RetailIrProvider
    from app.bootstrap import ensure_default_sources
    ensure_default_sources(db_session); db_session.commit()
    row = db_session.execute(select(ExternalSource).where(ExternalSource.code == "retail_ir")).scalar_one()
    assert row.is_active and row.source_type == "PRODUCT" and row.priority < 10  # asked before OpenFoodFacts
    assert json.loads(row.connection) == {"basalam": True, "torob": False}


def test_title_rules():
    assert title_has_barcode("خامه صبحانه پگاه 200 گرم – 6260007424016", "6260007424016")
    assert title_has_barcode("اسنک چی توز ۶۲۶۳۸۱۲۸۰۱۲۴۹", "6263812801249")  # Persian digits
    assert not title_has_barcode("شیر پرچرب کاله", "6260007424016")
    assert clean_title("خامه صبحانه پگاه 200 گرم – 6260007424016", "6260007424016") == "خامه صبحانه پگاه 200 گرم"
    assert clean_title("اسنک طلایی چی توز مقدار110گرم 6263812801249", "6263812801249") == "اسنک طلایی چی توز مقدار110گرم"
    assert clean_title("رب گوجه بارکد: 6261234567890", "6261234567890") == "رب گوجه"


def test_exact_hit_returns_product_and_image():
    out = RetailIrProvider(Src()).lookup("6260007424016", client=client_for(basalam=BASALAM_HIT))
    f = {x.field: x for x in out.fields}
    assert f["name"].value == "خامه صبحانه پگاه 200 گرم" and f["name"].confidence == "MEDIUM"
    assert f["unit"].value == "200 گرم" and f["category"].value == "خامه و سرشیر"
    assert out.image_url.startswith("https://statics.basalam.com/")
    assert out.raw["shop"] == "basalam"


def test_fuzzy_results_are_rejected():
    """The 'bowl of milk' guarantee: no barcode in the title → NOT_FOUND, never a guess."""
    with pytest.raises(ProviderError) as e:
        RetailIrProvider(Src()).lookup("6260007424016", client=client_for(basalam=BASALAM_FUZZY))
    assert e.value.kind == "NOT_FOUND"
    assert parse_shop("basalam", BASALAM_FUZZY, "6260007424016") == []


def test_in_store_and_short_codes_skipped():
    with pytest.raises(ProviderError) as e:
        RetailIrProvider(Src()).lookup("2000000000012", client=client_for(basalam=BASALAM_HIT))
    assert e.value.kind == "NOT_FOUND"
    with pytest.raises(ProviderError):
        RetailIrProvider(Src()).lookup("12345", client=client_for(basalam=BASALAM_HIT))


def test_torob_only_single_exact_result_and_off_by_default():
    # off by default → basalam empty, torob ignored → NOT_FOUND
    with pytest.raises(ProviderError):
        RetailIrProvider(Src()).lookup("6260007424016", client=client_for(torob=TOROB_ONE))
    on = Src('{"basalam": false, "torob": true}')
    out = RetailIrProvider(on).lookup("6260007424016", client=client_for(torob=TOROB_ONE))
    assert {x.field: x.value for x in out.fields}["name"] == "خامه صبحانه پگاه 200 گرم"  # digits normalised
    assert {x.field: x.value for x in out.fields}["unit"]  # parsed from the title («۲۰۰ گرم»)
    with pytest.raises(ProviderError):  # ambiguous → rejected
        RetailIrProvider(on).lookup("6260007424016", client=client_for(torob=TOROB_MANY))


def test_network_errors_are_classified():
    with pytest.raises(ProviderError) as e:
        RetailIrProvider(Src()).lookup("6260007424016", client=client_for(status=429))
    assert e.value.kind == "RATE_LIMITED"

    def boom(req):
        raise httpx.ConnectTimeout("t")
    with pytest.raises(ProviderError) as e:
        RetailIrProvider(Src()).lookup("6260007424016", client=httpx.Client(transport=httpx.MockTransport(boom)))
    assert e.value.kind == "TIMEOUT"


def test_resolve_barcode_pipeline_uses_retail_first(db_session):
    from app.bootstrap import ensure_default_sources
    ensure_default_sources(db_session); db_session.commit()

    def handler(req: httpx.Request) -> httpx.Response:
        if "basalam.com" in req.url.host:
            return httpx.Response(200, json=BASALAM_HIT)
        if "openfoodfacts.org" in req.url.host:
            return httpx.Response(200, json={"status": 0})
        return httpx.Response(404)
    r = resolvers.resolve_barcode(db_session, "6260007424016", client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert r["origin"] == "external" and r["need_manual"] is True
    assert r["merged"]["name"]["chosen"] == "خامه صبحانه پگاه 200 گرم"
    srcs = {s["source"]: s for s in r["sources"]}
    assert srcs["retail_ir"]["ok"] and srcs["retail_ir"]["image_url"]
    assert srcs["openfoodfacts"]["error"]["kind"] == "NOT_FOUND"


def test_image_ladder_exact_barcode_beats_name_search():
    calls = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(req.url.host)
        if "basalam.com" in req.url.host:
            return httpx.Response(200, json=BASALAM_HIT)
        if "openfoodfacts.org" in req.url.host:
            return httpx.Response(200, json={"status": 0})
        return httpx.Response(200, json={})
    c = httpx.Client(transport=httpx.MockTransport(handler))
    cands = pi.find_candidates("خامه پگاه", None, "6260007424016", client=c, web_fallback=False, retail={"basalam": True})
    assert cands and cands[0].source == "retail:basalam:barcode" and cands[0].score == 1.0
    assert "duckduckgo.com" not in calls and "api.digikala.com" not in calls  # early stop after the exact hit
