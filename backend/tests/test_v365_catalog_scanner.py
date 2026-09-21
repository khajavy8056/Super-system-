from pathlib import Path
import csv
import io
import json
import zipfile
import subprocess
import shutil
import pytest

ROOT = Path(__file__).resolve().parents[2]

def test_new_catalog_is_append_only_exact_and_image_free():
    with zipfile.ZipFile(ROOT/'releases/generator/SupermarketDemo-3.6.4.zip') as z:
        before = list(csv.DictReader(io.StringIO(z.read('backend/app/data/default_catalog.csv').decode())))
    after = list(csv.DictReader((ROOT/'backend/app/data/default_catalog.csv').open(encoding='utf-8')))
    assert after[:len(before)] == before  # existing names, identifiers, pictures untouched
    assert len(after) == 16953 and len(before) == 13570
    new = after[len(before):]
    assert len(new) == 3383
    assert all(not r['image_url'] and not r['images'] and r['min_stock_alert']=='0' for r in new)
    assert len({r['barcode'] for r in after}) == len(after)
    report = json.loads((ROOT/'docs/CATALOG_200_REPORT.json').read_text())
    assert len(report['files']) == 6 and report['rows'] == 6096
    assert report['added'] + report['duplicate_barcodes'] == report['rows']
    known = {r['barcode']: r for r in after}
    assert all(r['barcode'] in known for r in report['source_images'])
    new_codes = {r['barcode'] for r in new}
    first = {}
    for r in report['source_images']: first.setdefault(r['barcode'], r)
    assert all(known[bc]['name'] == first[bc]['name'] for bc in new_codes)
    assert 'Hy-40312350' in known  # do not strip letters/hyphen or recompute checksum


def test_update_marker_skips_unchanged_catalog_and_does_not_create_stock(client):
    from app.database import SessionLocal
    from app.models import ProductBatch
    from app.services.default_catalog import ensure_bundled_update
    from sqlalchemy import select, func
    with SessionLocal() as db:
        before = db.scalar(select(func.count(ProductBatch.id)))
        assert ensure_bundled_update(db)["ok"] is True  # other tests may reset the shared settings/database
        assert ensure_bundled_update(db) == {'ok':True,'unchanged':True}
        assert db.scalar(select(func.count(ProductBatch.id))) == before


def test_actual_javascript_scanner_handlers():
    if not shutil.which('node'): pytest.skip('Node needed for DOM-event harness')
    result = subprocess.run(['node', str(ROOT/'scripts/uitest/scanner-regression.cjs')], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'PASS:' in result.stdout
