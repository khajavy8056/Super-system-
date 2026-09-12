"""v2.7 — بانک کالا (product bank): offline barcode → {name, brand, unit, category, image}.

Why a bank in addition to the online lookup (§v2.6 retail_ir):
  * Iran has NO free machine-readable GTIN registry (GS1-IR: 30 manual web queries/day;
    OpenFoodFacts: ~600 Iranian items). The only reliable identification is a
    marketplace listing whose title literally carries the barcode — and that costs a
    network round-trip and works only while the seller keeps the listing.
  * A supermarket scans the same few thousand SKUs again and again. Every barcode that
    is EVER identified (online hit, confirmed product, imported list) is therefore kept
    here, so the second scan — on this PC, on every paired phone, offline — is instant.

Rows are keyed by barcode. ``source`` tells where the knowledge came from:
  ONLINE   an exact online hit (retail_ir / openfoodfacts)            confidence MEDIUM
  USER     a product the shop confirmed (created / edited)             confidence HIGH
  IMPORT   a purchased/collected Excel/CSV bank the shop imported      confidence HIGH
  SEED     the catalogue bundled with the app                          confidence MEDIUM

The bank never writes into ``products`` by itself (§52 — the operator confirms); it only
pre-fills the new-product form and the phones' local table. No shop names, no source
branding is shown to the user — the UI just says «شناسایی شد».
"""
from __future__ import annotations

import csv
import io
import re
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import BankItem, Brand, Product

_FA = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
_INSTORE = {"02", "20", "21", "22", "23", "24", "25", "26", "27", "28", "29"}

# column aliases accepted by import_rows (Persian + English, case-insensitive)
ALIASES = {
    "barcode": ("barcode", "بارکد", "کد", "code", "gtin", "ean", "کد کالا", "بارکد کالا", "شناسه محصول"),
    "name": ("name", "نام", "نام کالا", "عنوان", "title", "شرح", "شرح کالا", "product_name", "نام محصول"),
    "brand": ("brand", "برند", "نام تجاری", "شرکت", "سازنده", "manufacturer", "company"),
    "unit": ("unit", "واحد", "مقدار", "وزن", "حجم", "quantity", "size"),
    "category": ("category", "دسته", "دسته‌بندی", "دسته بندی", "گروه", "گروه کالا", "group"),
    "image": ("image", "image_url", "تصویر", "عکس", "photo", "picture", "نام تصویر", "image_name"),
}


_RANK = {"SEED": 0, "ONLINE": 1, "IMPORT": 2, "USER": 3}


def norm_barcode(s: str | None) -> str:
    return re.sub(r"\D", "", (s or "").translate(_FA))


def is_gtin(bc: str) -> bool:
    return 8 <= len(bc) <= 14 and bc[:2] not in _INSTORE


def lookup(db: Session, barcode: str) -> dict | None:
    bc = norm_barcode(barcode)
    if not bc:
        return None
    row = db.get(BankItem, bc)
    return _dict(row) if row else None


def _dict(r: BankItem) -> dict:
    return {"barcode": r.barcode, "name": r.name, "brand": r.brand, "unit": r.unit, "category": r.category,
            "image_url": r.image_url, "source": r.source, "confidence": r.confidence,
            "updated_at": r.updated_at.isoformat() if r.updated_at else None}


def remember(db: Session, barcode: str, name: str, *, brand: str | None = None, unit: str | None = None,
             category: str | None = None, image_url: str | None = None, source: str = "ONLINE") -> dict | None:
    """Upsert one row. A lower-ranked source never overwrites a higher one (USER beats ONLINE),
    but it may fill fields the better row left empty."""
    bc = norm_barcode(barcode)
    name = " ".join((name or "").split())
    if not is_gtin(bc) or not name:
        return None
    conf = "HIGH" if source in ("USER", "IMPORT") else "MEDIUM"
    row = db.get(BankItem, bc)
    if row is None:
        row = BankItem(barcode=bc, name=name, brand=brand or None, unit=unit or None, category=category or None,
                       image_url=image_url or None, source=source, confidence=conf)
        db.add(row)
    elif _RANK.get(source, 0) >= _RANK.get(row.source, 0):
        row.name, row.source, row.confidence = name, source, conf
        row.brand = brand or row.brand
        row.unit = unit or row.unit
        row.category = category or row.category
        row.image_url = image_url or row.image_url
    else:
        row.brand = row.brand or brand
        row.unit = row.unit or unit
        row.category = row.category or category
        row.image_url = row.image_url or image_url
    row.updated_at = datetime.utcnow()
    db.flush()
    return _dict(row)


def remember_product(db: Session, p: Product, source: str = "USER") -> None:
    """A product the shop created/edited is ground truth for its barcode."""
    if not p.barcode or not is_gtin(norm_barcode(p.barcode)) or not getattr(p, "has_own_barcode", True):
        return
    brand = None
    if p.brand_id:
        b = db.get(Brand, p.brand_id)
        brand = b.name if b else None
    img = p.image_url if p.image_url and p.image_url.startswith("http") else None
    remember(db, p.barcode, p.name, brand=brand, image_url=img, source=source)


def _header_map(fields: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    low = {f: (f or "").strip().lower() for f in fields}
    for key, names in ALIASES.items():
        for f, lf in low.items():
            if lf in names and key not in out:
                out[key] = f
    return out


def import_rows(db: Session, rows: list[dict], *, source: str = "IMPORT") -> dict:
    """Import already-parsed rows ({barcode, name, brand?, unit?, category?, image?})."""
    added = updated = skipped = 0
    for r in rows:
        bc = norm_barcode(str(r.get("barcode") or ""))
        name = " ".join(str(r.get("name") or "").split())
        if not is_gtin(bc) or not name:
            skipped += 1
            continue
        existed = db.get(BankItem, bc) is not None
        res = remember(db, bc, name, brand=r.get("brand") or None, unit=r.get("unit") or None,
                       category=r.get("category") or None, image_url=r.get("image") or r.get("image_url") or None, source=source)
        if res is None:
            skipped += 1
        elif existed:
            updated += 1
        else:
            added += 1
    return {"added": added, "updated": updated, "skipped": skipped, "total": len(rows)}


def import_csv_text(db: Session, text: str, *, source: str = "IMPORT") -> dict:
    """CSV/TSV with a header row; Persian or English column names (see ALIASES)."""
    text = text.lstrip("\ufeff")
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    fields = reader.fieldnames or []
    hm = _header_map(fields)
    if "barcode" not in hm or "name" not in hm:
        return {"error": "ستون بارکد و نام پیدا نشد", "columns": fields, "accepted": {k: list(v[:4]) for k, v in ALIASES.items()}}
    rows = []
    for raw in reader:
        rows.append({k: (raw.get(col) or "").strip() for k, col in hm.items()})
    out = import_rows(db, rows, source=source)
    out["columns"] = hm
    return out


def import_xlsx_bytes(db: Session, data: bytes, *, source: str = "IMPORT") -> dict:
    """Excel (.xlsx) — read with openpyxl when available, otherwise a minimal zip/XML reader
    (shared strings + first sheet), so the Windows build has no extra dependency."""
    rows = _xlsx_rows(data)
    if not rows:
        return {"error": "فایل اکسل خالی یا ناخوانا است"}
    header = [str(c or "").strip() for c in rows[0]]
    hm = _header_map(header)
    if "barcode" not in hm or "name" not in hm:
        return {"error": "ستون بارکد و نام پیدا نشد", "columns": header, "accepted": {k: list(v[:4]) for k, v in ALIASES.items()}}
    idx = {k: header.index(col) for k, col in hm.items()}
    parsed = []
    for r in rows[1:]:
        rec = {}
        for k, i in idx.items():
            v = r[i] if i < len(r) else ""
            if isinstance(v, float) and v.is_integer():
                v = str(int(v))
            rec[k] = str(v if v is not None else "").strip()
        parsed.append(rec)
    out = import_rows(db, parsed, source=source)
    out["columns"] = hm
    return out


def _xlsx_rows(data: bytes) -> list[list]:
    try:
        import openpyxl  # type: ignore
        wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        ws = wb.worksheets[0]
        return [list(r) for r in ws.iter_rows(values_only=True)]
    except ImportError:
        pass
    import xml.etree.ElementTree as ET
    import zipfile
    ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        shared: list[str] = []
        if "xl/sharedStrings.xml" in z.namelist():
            for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall("m:si", ns):
                shared.append("".join(t.text or "" for t in si.iter("{%s}t" % ns["m"])))
        sheet = next((n for n in sorted(z.namelist()) if n.startswith("xl/worksheets/sheet")), None)
        if not sheet:
            return []
        out: list[list] = []
        for row in ET.fromstring(z.read(sheet)).iter("{%s}row" % ns["m"]):
            cells: dict[int, object] = {}
            for c in row.findall("m:c", ns):
                ref = c.get("r") or "A"
                col = 0
                for ch in re.match(r"[A-Z]+", ref).group(0):  # type: ignore[union-attr]
                    col = col * 26 + (ord(ch) - 64)
                t = c.get("t")
                v = c.find("m:v", ns)
                if t == "s" and v is not None:
                    val: object = shared[int(v.text)] if v.text and v.text.isdigit() and int(v.text) < len(shared) else ""
                elif t == "inlineStr":
                    val = "".join(x.text or "" for x in c.iter("{%s}t" % ns["m"]))
                elif v is not None and v.text is not None:
                    try:
                        f = float(v.text)
                        val = str(int(f)) if f.is_integer() else v.text
                    except ValueError:
                        val = v.text
                else:
                    val = ""
                cells[col - 1] = val
            width = max(cells) + 1 if cells else 0
            out.append([cells.get(i, "") for i in range(width)])
        return out


def changed_since(db: Session, since: datetime | None, limit: int = 2000) -> list[dict]:
    stmt = select(BankItem)
    if since is not None:
        stmt = stmt.where(BankItem.updated_at >= since)
    return [_dict(r) for r in db.execute(stmt.order_by(BankItem.updated_at.asc()).limit(limit)).scalars()]


def stats(db: Session) -> dict:
    total = db.execute(select(func.count()).select_from(BankItem)).scalar() or 0
    by = dict(db.execute(select(BankItem.source, func.count()).group_by(BankItem.source)).all())
    with_img = db.execute(select(func.count()).select_from(BankItem).where(BankItem.image_url.isnot(None))).scalar() or 0
    return {"total": int(total), "by_source": {k: int(v) for k, v in by.items()}, "with_image": int(with_img)}


def seed_from_products(db: Session) -> int:
    """One-time: every existing product with a real GTIN enters the bank as USER truth."""
    n = 0
    for p in db.execute(select(Product).where(Product.is_active.is_(True))).scalars():
        before = db.get(BankItem, norm_barcode(p.barcode))
        remember_product(db, p, source="USER")
        if before is None and db.get(BankItem, norm_barcode(p.barcode)) is not None:
            n += 1
    return n


def export_csv(db: Session) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["barcode", "name", "brand", "unit", "category", "image_url", "source"])
    for r in db.execute(select(BankItem).order_by(BankItem.name)).scalars():
        w.writerow([r.barcode, r.name, r.brand or "", r.unit or "", r.category or "", r.image_url or "", r.source])
    return buf.getvalue()
