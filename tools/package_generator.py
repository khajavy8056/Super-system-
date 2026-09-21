"""Deterministic source kit: no shop DB, secrets, APKs or venv."""
from pathlib import Path
import zipfile
import hashlib
ROOT = Path(__file__).resolve().parents[1]
def build(destination):
    files = list((ROOT / 'backend/app').rglob('*.py'))
    files += list((ROOT / 'backend/app/data').glob('*.csv'))
    files += list((ROOT / 'backend/alembic').rglob('*.py'))
    files += [ROOT / p for p in ('backend/requirements.txt', 'backend/alembic.ini', 'tools/make_stress_backup.py')]
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for p in sorted(set(files)):
            if p.is_file():
                info = zipfile.ZipInfo(p.relative_to(ROOT).as_posix(), (2026, 9, 18, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                z.writestr(info, p.read_bytes())
    return hashlib.sha256(destination.read_bytes()).hexdigest()
if __name__ == '__main__':
    import sys
    print(build(sys.argv[1]))
