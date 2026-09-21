"""v3.4 — «بانک محصولات» از پوشه: import the shop owner's own product database.

Layout on disk (the operator drops the folders as they are — any depth):

    <root>/
      تنقلات/
        چوب شور و اسنک.xlsx        ← columns: نام محصول | دسته | زیر دسته | بارکد | تصویر 1 | تصویر 2 | تصویر 3
        pic/                         ← (also accepted: pics, images, تصاویر, prc, img)
          1532933656.webp
          6260100103955-(1).webp
      شیرینی‌جات و دسر/
        ...

Rules
  * every ``*.xlsx``/``*.xls``/``*.csv`` under the root is read (hidden / ``~$`` temp files skipped);
  * a picture named in the sheet is looked up in the ``pic`` folder NEXT TO that sheet, then in the
    sheet's own folder, then anywhere under the root (index built once). The sheet says ``.jpg`` but the
    files were converted to ``.webp`` → the stem is matched against every image extension, in the order
    webp, jpg, jpeg, png, gif; ``(1)`` / ``-(1)`` / spaces variations are tolerated;
  * first picture found among تصویر 1..3 becomes the product image (the rest are kept as extra assets);
  * products are keyed by barcode: new → created (active, no stock), existing → name / category / image
    filled in (never overwrites a picture the shop set by hand unless ``replace_images``);
  * categories / sub-categories are created as a two-level tree (parent = دسته, child = زیر دسته);
  * everything also lands in the offline product bank (source=IMPORT) so paired phones learn it;
  * the same rows + images can be exported as ONE ``catalog.pack`` file for phones (see ``export_pack``).

No network, no third-party source — the operator's own data is the single source of truth.
"""
from __future__ import annotations

import io
import json
import logging
import os
import re
import sqlite3
import struct
import time
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import Category, Product
from . import product_bank
from .product_bank import _xlsx_rows, norm_barcode

log = logging.getLogger("supermarket.catalog_folder")

IMG_EXT = (".webp", ".jpg", ".jpeg", ".png", ".gif")
PIC_DIRS = ("pic", "Pic", "PIC", "pics", "picture", "pictures", "images", "image", "img", "prc", "تصاویر", "تصویر", "عکس")
SHEET_EXT = (".xlsx", ".xlsm", ".xls", ".csv", ".tsv")

COLS = {
    "name": ("نام محصول", "نام کالا", "نام", "name", "product_name", "عنوان", "title"),
    "category": ("دسته", "دسته بندی", "دسته‌بندی", "category", "گروه"),
    "subcategory": ("زیر دسته", "زیردسته", "زیر‌دسته", "subcategory", "sub_category", "زیرگروه", "زیر گروه"),
    "barcode": ("بارکد", "barcode", "کد", "gtin", "ean", "کد کالا"),
    "brand": ("برند", "brand", "شرکت", "سازنده"),
    "unit": ("واحد", "unit"),
}
IMG_COL = re.compile(r"^(تصویر|عکس|image|picture|pic)\s*[0-9۰-۹]*$", re.I)

STATE_KEY = "catalog.folder_state"   # last import summary (settings json)


def default_root() -> Path:
    """``<data>/catalog`` — on Windows this is inside the install's data folder, so backups include it."""
    custom = os.environ.get("SUPERMARKET_CATALOG_DIR")
    if custom:
        return Path(custom)
    return settings.data_dir / "catalog"


# ------------------------------------------------------------------ discovery
@dataclass
class Row:
    name: str
    barcode: str
    category: str = ""
    subcategory: str = ""
    brand: str = ""
    unit: str = ""
    images: list[str] = field(default_factory=list)   # names as written in the sheet
    sheet: str = ""                                    # relative path of the sheet
    found: list[Path] = field(default_factory=list)    # resolved image files


def _norm_header(h) -> str:
    return " ".join(str(h or "").replace("\u200c", " ").replace("ي", "ی").replace("ك", "ک").split()).lower()


def _header_map(header: list) -> tuple[dict[str, int], list[int]]:
    idx: dict[str, int] = {}
    imgs: list[int] = []
    for i, h in enumerate(header):
        n = _norm_header(h)
        if not n:
            continue
        if IMG_COL.match(n):
            imgs.append(i)
            continue
        for key, names in COLS.items():
            if key not in idx and n in names:
                idx[key] = i
    return idx, imgs


def _cell(r: list, i: int | None) -> str:
    if i is None or i >= len(r):
        return ""
    v = r[i]
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return " ".join(str(v).split())


def read_sheet(path: Path) -> tuple[list[Row], str | None]:
    """Rows of one sheet (all worksheets of an xlsx). Returns (rows, error)."""
    data = path.read_bytes()
    tables: list[list[list]] = []
    if path.suffix.lower() in (".csv", ".tsv"):
        import csv
        text = data.decode("utf-8-sig", errors="replace")
        try:
            dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t|")
        except csv.Error:
            dialect = csv.excel
        tables.append([list(r) for r in csv.reader(io.StringIO(text), dialect=dialect)])
    else:
        try:
            import openpyxl  # type: ignore
            wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
            for ws in wb.worksheets:
                tables.append([list(r) for r in ws.iter_rows(values_only=True)])
        except ImportError:
            tables.append(_xlsx_rows(data))
        except Exception as exc:  # corrupt file → report, continue with the others
            return [], f"{path.name}: {exc}"
    out: list[Row] = []
    for rows in tables:
        # header may not be the first line (title rows) — find the first line that has name+barcode
        h_at = None
        for k, r in enumerate(rows[:10]):
            idx, imgs = _header_map(r)
            if "name" in idx and "barcode" in idx:
                h_at = k
                break
        if h_at is None:
            continue
        idx, imgs = _header_map(rows[h_at])
        for r in rows[h_at + 1:]:
            name = _cell(r, idx.get("name"))
            bc = norm_barcode(_cell(r, idx.get("barcode")))
            if not name or not bc:
                continue
            images = [x for x in (_cell(r, i) for i in imgs) if x]
            out.append(Row(name=name, barcode=bc, category=_cell(r, idx.get("category")), subcategory=_cell(r, idx.get("subcategory")),
                           brand=_cell(r, idx.get("brand")), unit=_cell(r, idx.get("unit")), images=images))
    if not out and tables:
        return [], f"{path.name}: ستون «نام محصول» و «بارکد» پیدا نشد"
    return out, None


def _stem_keys(name: str) -> list[str]:
    """Variants of an image name that should match the same file on disk."""
    from urllib.parse import unquote
    n = unquote(name.strip()).replace("\\", "/").split("?")[0].split("/")[-1]
    stem = re.sub(r"\.(jpe?g|png|webp|gif|bmp)$", "", n, flags=re.I)
    keys = {stem, stem.replace(" ", ""), stem.replace("-(", "("), stem.replace("(", "-("), stem.replace(" (", "(")}
    return [k.lower() for k in keys if k]


class ImageIndex:
    """stem(lower) → path, for a directory (non-recursive) or the whole root (recursive, built lazily)."""

    def __init__(self, root: Path):
        self.root = root
        self._dir_cache: dict[Path, dict[str, Path]] = {}
        self._all: dict[str, Path] | None = None

    def _scan(self, d: Path, recursive: bool) -> dict[str, Path]:
        out: dict[str, Path] = {}
        it = d.rglob("*") if recursive else d.iterdir()
        try:
            for p in it:
                if p.is_file() and p.suffix.lower() in IMG_EXT:
                    for k in _stem_keys(p.name):
                        # prefer webp when several extensions exist
                        cur = out.get(k)
                        if cur is None or IMG_EXT.index(p.suffix.lower()) < IMG_EXT.index(cur.suffix.lower()):
                            out[k] = p
        except OSError:
            pass
        return out

    def dir(self, d: Path) -> dict[str, Path]:
        if d not in self._dir_cache:
            self._dir_cache[d] = self._scan(d, False) if d.is_dir() else {}
        return self._dir_cache[d]

    def everywhere(self) -> dict[str, Path]:
        if self._all is None:
            self._all = self._scan(self.root, True)
        return self._all

    def find(self, sheet_dir: Path, name: str) -> Path | None:
        keys = _stem_keys(name)
        places = [sheet_dir / d for d in PIC_DIRS] + [sheet_dir]
        for d in places:
            m = self.dir(d)
            for k in keys:
                if k in m:
                    return m[k]
        m = self.everywhere()
        for k in keys:
            if k in m:
                return m[k]
        return None


def scan(root: Path) -> dict:
    """Walk the root: every sheet, every row, resolved image paths. Pure (no DB)."""
    root = Path(root)
    if not root.is_dir():
        return {"error": f"پوشه پیدا نشد: {root}", "root": str(root)}
    sheets = sorted(p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in SHEET_EXT and not p.name.startswith(("~$", ".")))
    index = ImageIndex(root)
    rows: list[Row] = []
    errors: list[str] = []
    seen: dict[str, Row] = {}
    dup = 0
    for sh in sheets:
        rs, err = read_sheet(sh)
        if err:
            errors.append(err)
        rel = str(sh.relative_to(root))
        for r in rs:
            r.sheet = rel
            for nm in r.images:
                p = index.find(sh.parent, nm)
                if p is not None and p not in r.found:
                    r.found.append(p)
            if r.barcode in seen:
                dup += 1
                prev = seen[r.barcode]
                for p in r.found:            # merge pictures of a duplicate line
                    if p not in prev.found:
                        prev.found.append(p)
                continue
            seen[r.barcode] = r
            rows.append(r)
    with_img = sum(1 for r in rows if r.found)
    downloadable = sum(1 for r in rows if not r.found and any(x.lower().startswith("http") for x in r.images))
    missing = [{"barcode": r.barcode, "name": r.name, "images": r.images, "sheet": r.sheet} for r in rows if not r.found]
    return {"root": str(root), "sheets": len(sheets), "rows": len(rows), "duplicates": dup, "with_image": with_img,
            "without_image": len(rows) - with_img, "downloadable": downloadable, "errors": errors, "missing": missing[:200], "_rows": rows}


# ------------------------------------------------------------------ import into the shop
def _category(db: Session, cache: dict, name: str, parent_id: int | None) -> int | None:
    name = " ".join((name or "").split())
    if not name:
        return None
    key = (name, parent_id)
    if key in cache:
        return cache[key]
    c = db.execute(select(Category).where(Category.name == name, Category.parent_id == parent_id, Category.deleted_at.is_(None))).scalars().first()
    if c is None:
        c = Category(name=name, parent_id=parent_id, is_active=True)
        db.add(c)
        db.flush()
    cache[key] = c.id
    return c.id


def _store_image(barcode: str, src: Path) -> str:
    """Copy into MEDIA_DIR/catalog/<barcode>.<ext> (WEBP kept as is) → '/media/…' url."""
    ext = src.suffix.lower().lstrip(".")
    ext = "jpg" if ext == "jpeg" else ext
    rel = f"catalog/{re.sub(r'[^0-9A-Za-z]', '', barcode)[:32] or 'x'}.{ext}"
    dest = Path(settings.MEDIA_DIR) / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        if not dest.exists() or dest.stat().st_size != src.stat().st_size:
            dest.write_bytes(src.read_bytes())
    except OSError as exc:
        log.warning("image copy failed %s: %s", src, exc)
        return ""
    return f"/media/{rel}"


def _download(url: str, dest_dir: Path) -> Path | None:
    """Sheet gives a full URL and the file is not in any pic folder → fetch it once into <root>/_downloaded/."""
    if not url.lower().startswith(("http://", "https://")):
        return None
    try:
        import httpx
        from urllib.parse import unquote
        name = unquote(url.split("?")[0].split("/")[-1]) or "img"
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / name
        if dest.is_file() and dest.stat().st_size > 0:
            return dest
        r = httpx.get(url, timeout=15, follow_redirects=True, headers={"User-Agent": "SuperyMan-Catalog/1.0"})
        if r.status_code == 200 and r.content[:4] in (b"RIFF", b"\xff\xd8\xff\xe0", b"\x89PNG") or (r.status_code == 200 and r.headers.get("content-type", "").startswith("image/")):
            dest.write_bytes(r.content)
            return dest
    except Exception as exc:  # offline / blocked → simply reported as missing
        log.info("download skipped %s: %s", url, exc)
    return None


def import_folder(db: Session, root: Path | None = None, *, replace_images: bool = False, download_missing: bool = False, progress=None, user_id: int | None = None) -> dict:
    """Scan + write products/categories/bank/images. Returns a summary (also stored in settings)."""
    root = Path(root) if root else default_root()
    root.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    res = scan(root)
    if res.get("error"):
        return res
    rows: list[Row] = res.pop("_rows")
    cats: dict = {}
    created = updated = images = img_skipped = 0
    n = len(rows)
    existing = {p.barcode: p for p in db.execute(select(Product)).scalars()}
    for i, r in enumerate(rows):
        if progress and (i % 50 == 0 or i == n - 1):
            progress(i + 1, n, r.name)
        parent = _category(db, cats, r.category, None)
        cat_id = _category(db, cats, r.subcategory, parent) if r.subcategory else parent
        url = ""
        if not r.found and download_missing:
            for nm in r.images:
                d = _download(nm, root / "_downloaded")
                if d is not None:
                    r.found.append(d)
                    break
        if r.found:
            url = _store_image(r.barcode, r.found[0])
        p = existing.get(r.barcode)
        if p is None:
            p = Product(barcode=r.barcode, name=r.name, category_id=cat_id, image_url=url or None, min_stock_alert=0, is_active=True, has_own_barcode=True)
            db.add(p)
            existing[r.barcode] = p
            created += 1
            if url:
                images += 1
        else:
            changed = False
            if p.name != r.name:
                p.name = r.name
                changed = True
            if cat_id and p.category_id != cat_id:
                p.category_id = cat_id
                changed = True
            if url and (replace_images or not p.image_url or p.image_url.startswith("/media/catalog/")):
                if p.image_url != url:
                    p.image_url = url
                    images += 1
                    changed = True
            elif url:
                img_skipped += 1
            if changed:
                updated += 1
        product_bank.remember(db, r.barcode, r.name, brand=r.brand or None, unit=r.unit or None,
                              category=(r.subcategory or r.category) or None, image_url=url or None, source="IMPORT")
        if i % 500 == 499:
            db.flush()
    db.flush()
    summary = {k: v for k, v in res.items() if k != "missing"}
    summary["with_image"] = sum(1 for r in rows if r.found); summary["without_image"] = len(rows) - summary["with_image"]
    summary["missing"] = [{"barcode": r.barcode, "name": r.name, "images": r.images, "sheet": r.sheet} for r in rows if not r.found][:50]
    summary.update({"created": created, "updated": updated, "images": images, "images_kept": img_skipped,
                    "seconds": round(time.time() - t0, 1), "at": time.strftime("%Y-%m-%dT%H:%M:%S")})
    try:
        from ..models import SystemSetting
        row = db.execute(select(SystemSetting).where(SystemSetting.key == STATE_KEY)).scalars().first()
        if row is None:
            db.add(SystemSetting(key=STATE_KEY, value=json.dumps(summary, ensure_ascii=False)[:20000], is_secret=False))
        else:
            row.value = json.dumps(summary, ensure_ascii=False)[:20000]
    except Exception as exc:  # pragma: no cover
        log.info("state save skipped: %s", exc)
    db.commit()
    return summary


def last_state(db: Session) -> dict | None:
    try:
        from ..models import SystemSetting
        row = db.execute(select(SystemSetting).where(SystemSetting.key == STATE_KEY)).scalars().first()
        return json.loads(row.value) if row and row.value else None
    except Exception:
        return None


# ------------------------------------------------------------------ catalog.pack (for phones)
PACK_MAGIC = b"SUPERYPK1"


def export_pack(db: Session, dest: Path, *, progress=None) -> dict:
    """ONE file for the phone: a SQLite catalogue + every product image, indexed by barcode.

    Layout:  MAGIC(9) | u64 db_len | sqlite bytes | u64 img_count | [u16 bc_len | bc | u32 len | bytes]* | u64 index_offset
    The phone streams it into its private files dir and reads images by seeking — nothing is ever written
    as a picture file, so the gallery never sees it.
    """
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    prods = db.execute(select(Product).where(Product.is_active.is_(True), Product.deleted_at.is_(None))).scalars().all()
    cats = {c.id: c for c in db.execute(select(Category)).scalars()}
    tmp = dest.with_suffix(".sqlite.tmp")
    if tmp.exists():
        tmp.unlink()
    con = sqlite3.connect(tmp)
    con.executescript("""
        CREATE TABLE meta(k TEXT PRIMARY KEY, v TEXT);
        CREATE TABLE categories(id INTEGER PRIMARY KEY, name TEXT, parent_id INTEGER);
        CREATE TABLE items(barcode TEXT PRIMARY KEY, name TEXT, category TEXT, subcategory TEXT, brand TEXT, unit TEXT, has_image INTEGER);
        CREATE INDEX ix_items_name ON items(name);
    """)
    con.executemany("INSERT INTO categories VALUES(?,?,?)", [(c.id, c.name, c.parent_id) for c in cats.values()])
    media = Path(settings.MEDIA_DIR)
    imgs: list[tuple[str, Path]] = []
    rows = []
    for p in prods:
        c = cats.get(p.category_id) if p.category_id else None
        parent = cats.get(c.parent_id) if c and c.parent_id else None
        sub = c.name if parent else ""
        top = parent.name if parent else (c.name if c else "")
        f = None
        if p.image_url and p.image_url.startswith("/media/"):
            cand = media / p.image_url[len("/media/"):]
            if cand.is_file():
                f = cand
        rows.append((p.barcode, p.name, top, sub, "", "", 1 if f else 0))
        if f:
            imgs.append((p.barcode, f))
    con.executemany("INSERT OR REPLACE INTO items VALUES(?,?,?,?,?,?,?)", rows)
    from .. import __version__
    con.executemany("INSERT INTO meta VALUES(?,?)", [("version", str(int(time.time()))), ("app", __version__), ("items", str(len(rows))), ("images", str(len(imgs))),
                                                     ("created_at", time.strftime("%Y-%m-%dT%H:%M:%S"))])
    con.commit()
    con.close()
    dbb = tmp.read_bytes()
    tmp.unlink()
    with open(dest, "wb") as out:
        out.write(PACK_MAGIC)
        out.write(struct.pack("<Q", len(dbb)))
        out.write(dbb)
        out.write(struct.pack("<Q", len(imgs)))
        index: list[tuple[str, int, int]] = []
        for i, (bc, f) in enumerate(imgs):
            if progress and i % 200 == 0:
                progress(i, len(imgs))
            b = f.read_bytes()
            bcb = bc.encode("utf-8")
            off = out.tell()
            out.write(struct.pack("<H", len(bcb)))
            out.write(bcb)
            out.write(struct.pack("<I", len(b)))
            out.write(b)
            index.append((bc, off, len(b)))
        idx_off = out.tell()
        for bc, off, ln in index:      # trailing index: u16 bc_len | bc | u64 off | u32 len
            bcb = bc.encode("utf-8")
            out.write(struct.pack("<H", len(bcb)))
            out.write(bcb)
            out.write(struct.pack("<QI", off, ln))
        out.write(struct.pack("<Q", idx_off))
    return {"file": str(dest), "items": len(rows), "images": len(imgs), "bytes": dest.stat().st_size}


def pack_path() -> Path:
    return settings.data_dir / "catalog.pack"


# ------------------------------------------------------------------ unpack (tests / desktop preview)
def read_pack_index(path: Path) -> dict:
    with open(path, "rb") as f:
        if f.read(len(PACK_MAGIC)) != PACK_MAGIC:
            raise ValueError("not a catalog.pack")
        (db_len,) = struct.unpack("<Q", f.read(8))
        dbb = f.read(db_len)
        f.seek(-8, os.SEEK_END)
        (idx_off,) = struct.unpack("<Q", f.read(8))
        f.seek(idx_off)
        end = path.stat().st_size - 8
        index: dict[str, tuple[int, int]] = {}
        while f.tell() < end:
            (bl,) = struct.unpack("<H", f.read(2))
            bc = f.read(bl).decode("utf-8")
            off, ln = struct.unpack("<QI", f.read(12))
            index[bc] = (off, ln)
    return {"db": dbb, "index": index}


def read_pack_image(path: Path, off: int, ln: int) -> bytes:
    with open(path, "rb") as f:
        f.seek(off)
        (bl,) = struct.unpack("<H", f.read(2))
        f.seek(bl, os.SEEK_CUR)
        (n,) = struct.unpack("<I", f.read(4))
        return f.read(n)


def make_sample(root: Path) -> None:
    """Build a tiny demo tree (one sheet + two webp) for tests / first-run guidance."""
    import openpyxl  # type: ignore

    d = root / "تنقلات"
    (d / "pic").mkdir(parents=True, exist_ok=True)
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["نام محصول", "دسته", "زیر دسته", "بارکد", "تصویر 1", "تصویر 2", "تصویر 3"])
    ws.append(["چوب شور 30 گرمی مینو", "تنقلات", "چوب شور", "6260100103955", "1532933656.jpg", "6260100103955-(1).jpg", None])
    ws.append(["لواشک آلو 30 گرمی گلین", "تنقلات", "تنقلات ترش", "6260200610254", "6260200610254(1).jpg", None, None])
    ws.append(["اسنک پنیری توپی ریز 25 گرمی مزمز", "تنقلات", "اسنک", "6262477320553", "nope.jpg", None, None])
    wb.save(d / "تنقلات.xlsx")
    webp = bytes.fromhex("52494646240000005745425056503820180000003001009d012a0100010002003425a400037000fef8fe0000")
    (d / "pic" / "1532933656.webp").write_bytes(webp)
    (d / "pic" / "6260200610254(1).webp").write_bytes(webp)
