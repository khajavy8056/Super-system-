"""Package the external frontend override supported by existing Windows 3.6.x apps."""
from pathlib import Path
import zipfile, hashlib
ROOT = Path(__file__).resolve().parents[1]
#: نسخهٔ بستهٔ رابط کاربری ویندوز (مستقل از نسخهٔ بک‌اند؛ ۳٫۷٫۰ = بازآرایی ظاهر v4.8.0)
UI_VERSION = "3.7.0"
def build(version: str = UI_VERSION):
    out = ROOT/f'releases/windows/SupermarketDesktopUI-{version}.zip'
    out.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as z:
        for p in sorted((ROOT/'frontend').rglob('*')):
            if p.is_file(): z.write(p,p.relative_to(ROOT))
        for p in sorted((ROOT/'tools/windows-ui').iterdir()):
            data=p.read_bytes()
            if p.suffix=='.bat': data=data.replace(b'\r\n',b'\n').replace(b'\n',b'\r\n')
            z.writestr(p.name,data)
    digest=hashlib.sha256(out.read_bytes()).hexdigest()
    out.with_suffix('.zip.sha256').write_text(digest+'  '+out.name+'\n')
    print(out,digest)
    return out
if __name__=='__main__':build()
