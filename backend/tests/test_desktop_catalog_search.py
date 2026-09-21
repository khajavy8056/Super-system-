"""Next desktop release: complete pages, literal/prefix search, live POS eligibility."""
import importlib.util
import json
import logging
import uuid
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import Mock

import pytest
from sqlalchemy import select
from app.database import SessionLocal
from app.models import Product, ProductBatch
from app.models.insights import Insight
from app.services import product_search, insights


def test_persian_alphabet_and_normalization():
    letters = list('ابپتثجچحخدذرزژسشصضطظعغفقکگلمنوهی')
    assert sorted(reversed(letters), key=product_search.alphabet_key) == letters
    assert product_search.normalize('  عَرقي كاسني ۱۲٣ ') == 'عرقی کاسنی 123'


def test_sql_pages_expose_every_match_with_prefix_and_stock_order(client, auth_headers):
    marker = uuid.uuid4().hex[:10]
    names = ['عرق '+marker, 'بسته ۱۲ عددی '+marker, 'تعداد '+marker, 'آب '+marker]
    ids = []
    for i, name in enumerate(names):
        r = client.post('/api/products', headers=auth_headers, json={'barcode': f'{marker}-{i}', 'name':name})
        assert r.status_code == 201, r.text
        ids.append(r.json()['id'])
    # Only this test's four rows. SQL pages have a deterministic id tie-break.
    rows=[]
    for offset in range(0,4,2):
        r=client.get('/api/products', headers=auth_headers, params={'q':marker,'limit':2,'offset':offset}).json()
        assert r['total']==4
        rows.extend(r['items'])
    assert len({r['id'] for r in rows})==4
    assert [r['name'] for r in rows]==sorted(names,key=product_search.alphabet_key)
    r=client.get('/api/products', headers=auth_headers, params={'q':'ع','limit':1000}).json()
    matching=list(r['items'])
    for offset in range(1000,r['total'],1000):
        matching.extend(client.get('/api/products',headers=auth_headers,params={'q':'ع','limit':1000,'offset':offset}).json()['items'])
    ranked=[x['id'] for x in matching if x['id'] in ids]
    assert ranked.index(ids[0]) < ranked.index(ids[1]) < ranked.index(ids[2])
    received=client.post('/api/batches/receive',headers=auth_headers,json={'product_id':ids[1], 'quantity_received':2,'buy_price':10,'sell_price':12})
    assert received.status_code==201
    r=client.get('/api/products',headers=auth_headers,params={'q':marker,'limit':2}).json()
    assert r['items'][0]['id']==ids[1]
    # Scanned alphanumeric identifiers retain their case and punctuation.
    r=client.get('/api/pos/search',headers=auth_headers,params={'q':f'{marker}-0'}).json()
    assert r['items'][0]['product_id']==ids[0]


def test_like_metacharacters_are_literal(client,auth_headers):
    r=client.get('/api/products',headers=auth_headers,params={'q':'%___unlikely_367_%'}).json()
    assert r['total']==0


@pytest.mark.parametrize('state',['valid','empty','inactive','deleted','expired','quarantined','missing'])
def test_nudges_recheck_live_product_and_sellable_batch(client,milk,two_batches,state):
    with SessionLocal() as db:
        product=db.get(Product,milk['id'])
        if state=='inactive': product.is_active=False
        if state=='deleted':
            from datetime import datetime
            product.deleted_at=datetime.utcnow()
        batches=list(db.scalars(select(ProductBatch).where(ProductBatch.product_id==product.id)))
        for batch in batches:
            if state=='empty': batch.current_qty=0
            if state=='expired': batch.expiry_date=date.today()-timedelta(days=2)
            if state=='quarantined': batch.status='QUARANTINED'
        target=product.id if state!='missing' else 999999999
        from datetime import datetime
        row=Insight(kind='BASKET_NUDGE', dedupe_key='live-test',title='test',body='test',status='ACCEPTED',accepted_at=datetime(2099,1,1),evidence=json.dumps({'rules':[{'if':-100,'then':target,'if_name':'source','then_name':'STALE NAME','confidence':.95}]}))
        db.add(row);db.flush()
        result=insights.nudges(db,[-100])
        if state=='valid':
            assert result[0]['name']==product.name
            assert result[0]['purpose']=='sell_now'
            assert insights.nudges(db,[-100,product.id])==[]
        else: assert result==[]
        db.rollback()


def test_native_shell_defaults_to_resizable_window_and_never_browser(monkeypatch,tmp_path):
    import sys
    from types import SimpleNamespace
    root=Path(__file__).resolve().parents[2]
    path=root/'installer/windows/run_supermarket.py'
    spec=importlib.util.spec_from_file_location('native_launcher_test',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    stub=SimpleNamespace(create_window=Mock(return_value=SimpleNamespace(events=SimpleNamespace())), start=Mock())
    monkeypatch.setitem(sys.modules,'webview',stub)
    monkeypatch.delenv('SUPERMARKET_KIOSK',raising=False)
    assert module.open_native_window('http://127.0.0.1:1',tmp_path,logging.getLogger(),lambda:None)
    kw=stub.create_window.call_args.kwargs
    assert kw['fullscreen'] is False and kw['frameless'] is False
    assert kw['min_size']==(640,480)
    stub.start.side_effect=RuntimeError('runtime missing')
    assert not module.open_native_window('http://127.0.0.1:1',tmp_path,logging.getLogger(),lambda:None)
    assert 'webbrowser.open' not in path.read_text()
    assert 'open_window(' not in path.read_text()


@pytest.mark.parametrize('visit_count,gap',[(3,30),(8,7)])
def test_recurrence_abstains_for_small_or_short_history(visit_count,gap):
    from datetime import datetime
    from types import SimpleNamespace
    today=date(2026,9,21)
    days=[today-timedelta(days=1+i*gap) for i in range(visit_count)][::-1]
    db=Mock()
    db.execute.return_value=[(1,d.isoformat()) for d in days]
    # Multiple invoices per visit must not create evidence of more visits.
    invoices={i:{'cust':1,'at':datetime.combine(days[i%len(days)],datetime.min.time()),'total':100} for i in range(40)}
    ctx=insights.Ctx(db=db,today=today,now_utc=datetime(2026,9,21),invoices=invoices)
    assert insights.customer_patterns(ctx)==[]
