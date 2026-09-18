"""Delivery hashes, isolated package contents and honest resumed progress."""
from pathlib import Path
import hashlib
import importlib.util
import io
import re
import zipfile

ROOT = Path(__file__).resolve().parents[2]

def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'tools' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

def test_published_kit_matches_sources_and_launcher_hashes(tmp_path):
    pack = load('package_generator')
    built = tmp_path / 'kit.zip'
    digest = pack.build(built)
    published = ROOT / 'releases/generator/SupermarketDemo-3.6.4.zip'
    from app import __version__
    if __version__ == '3.6.4':
        assert hashlib.sha256(published.read_bytes()).hexdigest() == digest
    # Historical release kit is immutable; newer apps intentionally differ.
    digest = hashlib.sha256(published.read_bytes()).hexdigest()
    ps = ROOT / 'tools/bootstrap-year.ps1'
    assert f"$BundleHash = '{digest}'" in ps.read_text()
    bat = (ROOT / 'tools/run-year-simulation.bat').read_text()
    assert hashlib.sha256(ps.read_bytes()).hexdigest() in bat
    assert 'BUNDLE_HASH' not in ps.read_text() and 'SCRIPT_HASH' not in bat
    with zipfile.ZipFile(built) as z:
        assert 'backend/app/data/default_catalog.csv' in z.namelist()
        assert 'tools/make_stress_backup.py' in z.namelist()
        assert all(not re.search(r'(^|/)(\.env|\.venv|keystore|__pycache__)(/|$)', n) for n in z.namelist())
        assert not any(n.endswith(('.db', '.apk', '.jks')) for n in z.namelist())
        assert z.read('backend/app/services/demo_store.py') == (ROOT / 'backend/app/services/demo_store.py').read_bytes()

def test_resumed_eta_uses_only_work_completed_this_session(monkeypatch):
    driver = load('make_stress_backup')
    now = [0.0]
    monkeypatch.setattr(driver.time, 'time', lambda: now[0])
    stream = io.StringIO()
    bar = driver.Bar(stream=stream)
    bar.draw(.4, 'resumed', phase='days', force=True)
    now[0] = 60.0
    bar.draw(.5, 'next days', phase='days', force=True)
    # 10% done in this session took a minute; remaining 50% ~5 minutes, not 1.
    assert 'مانده ~5:00' in stream.getvalue()
    before = len(stream.getvalue().splitlines())
    bar.draw(.501, 'another committed day', phase='days', force=True)
    assert len(stream.getvalue().splitlines()) == before + 1
