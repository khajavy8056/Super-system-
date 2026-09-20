from pathlib import Path
import hashlib
import zipfile

ROOT=Path(__file__).resolve().parents[2]
def test_desktop_bundle_is_complete_and_does_not_replace_shop_data():
    path=ROOT/'releases/windows/SupermarketDesktopUI-3.6.6.zip'
    assert hashlib.sha256(path.read_bytes()).hexdigest() == path.with_suffix('.zip.sha256').read_text().split()[0]
    with zipfile.ZipFile(path) as z:
        for p in (ROOT/'frontend').rglob('*'):
            if p.is_file(): assert z.read(p.relative_to(ROOT).as_posix()) == p.read_bytes()
        bat=z.read('START-WINDOWS-UI.bat').decode()
        assert 'set "FRONTEND_DIR=%~dp0frontend"' in bat
        assert 'taskkill' not in bat.lower()
        assert not any(n.endswith(('.db','.exe')) for n in z.namelist())
    assert 'desktop.css' in (ROOT/'frontend/index.html').read_text()
    assert '"/desktop.css"' in (ROOT/'frontend/sw.js').read_text()

def test_existing_backend_supports_external_frontend_override(monkeypatch,tmp_path):
    from app.main import _find_frontend_dir
    monkeypatch.setenv('FRONTEND_DIR',str(tmp_path))
    assert _find_frontend_dir() == tmp_path
