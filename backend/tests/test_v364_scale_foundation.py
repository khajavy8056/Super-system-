from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
import subprocess
import sys
from pathlib import Path

import pytest

from app.services import insights, demo_store
from app.database import SessionLocal
from app.models import Invoice


def test_simulation_clock_is_thread_local():
    past = datetime(2016, 1, 1)
    insights.set_clock(past)
    try:
        assert insights._now() == past
        with ThreadPoolExecutor(max_workers=1) as pool:
            assert pool.submit(insights._now).result().year != 2016
    finally:
        insights.set_clock(None)


def test_analysis_window_excludes_future_invoices(client, auth_headers, milk, two_batches):
    response = client.post('/api/pos/checkout', headers=auth_headers, json={
        'items': [{'product_id': milk['id'], 'batch_id': two_batches['a']['id'], 'quantity': 1}],
        'payments': [{'method': 'CASH', 'amount': 60000}]})
    assert response.status_code == 201, response.text
    iid = response.json()['invoice_id']
    with SessionLocal() as db:
        inv = db.get(Invoice, iid)
        actual = inv.created_at
        try:
            insights.set_clock(actual - timedelta(seconds=1))
            assert iid not in insights._load_ctx(db).invoices
            insights.set_clock(actual + timedelta(seconds=1))
            ctx = insights._load_ctx(db)
            assert iid in ctx.invoices
            assert any(line['inv'] == iid for line in ctx.lines)
        finally:
            insights.set_clock(None)


@pytest.mark.parametrize('days,rate', [(0, 100), (4000, 100), (365, float('nan')), (365, float('inf')), (365, 0)])
def test_bad_scale_rejected_before_accessing_database(days, rate):
    with pytest.raises(ValueError, match='DEMO_INVALID_SCALE'):
        demo_store.generate(None, days=days, invoices_per_day=rate)


def test_cli_rejects_invalid_scale_before_bootstrap():
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run([sys.executable, str(root/'tools/make_stress_backup.py'), '--days', '0', '--no-bootstrap'],
                            capture_output=True, text=True)
    assert result.returncode == 2
    assert 'days must be' in result.stderr
