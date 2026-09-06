"""§80–82 — initial product database, imported with ZERO stock.

The bundled ``data/starter_catalog.csv`` is a generic, offline, licence-free
list of common Iranian supermarket lines (category → sub-category → product,
default unit). It intentionally carries **no manufacturer barcodes**: GTINs
must come from the shop's own scanning or from a CSV the shop provides (same
columns) — inventing barcodes would corrupt the resolver. Items with no
barcode receive an ``INT-`` internal code (§16).

Import is idempotent: a product with the same normalised name in the same
category is skipped, so re-running never duplicates. Products are created as
Product rows only — no ProductBatch, so stock is 0 until the first receipt.
"""
from __future__ import annotations

import csv
import io
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import Category, Product, Unit, Brand
from . import catalog

BUNDLED = Path(__file__).resolve().parent.parent / "data" / "starter_catalog.csv"
COLUMNS = ["category", "subcategory", "name", "brand", "unit", "min_stock_alert", "barcode"]


def _category(db: Session, name: str, parent_id: int | None, cache: dict) -> int | None:
    name = (name or "").strip()
    if not name:
        return parent_id
    key = (name.lower(), parent_id)
    if key in cache:
        return cache[key]
    q = select(Category).where(func.lower(Category.name) == name.lower())
    q = q.where(Category.parent_id.is_(None)) if parent_id is None else q.where(Category.parent_id == parent_id)
    row = db.execute(q).scalar_one_or_none()
    if row is None:
        row = Category(name=name, parent_id=parent_id)
        db.add(row)
        db.flush()
    cache[key] = row.id
    return row.id


def _brand(db: Session, name: str, cache: dict) -> int | None:
    name = (name or "").strip()
    if not name:
        return None
    if name.lower() in cache:
        return cache[name.lower()]
    row = db.execute(select(Brand).where(func.lower(Brand.name) == name.lower())).scalar_one_or_none()
    if row is None:
        row = Brand(name=name)
        db.add(row)
        db.flush()
    cache[name.lower()] = row.id
    return row.id


def _unit(db: Session, name: str, cache: dict) -> int | None:
    name = (name or "عدد").strip()
    if name in cache:
        return cache[name]
    row = db.execute(select(Unit).where((Unit.name == name) | (Unit.symbol == name))).scalar_one_or_none()
    cache[name] = row.id if row else None
    return cache[name]


def import_csv(db: Session, text: str | None = None, *, user=None, dry_run: bool = False) -> dict:
    """Import ``text`` (CSV with COLUMNS header) or the bundled catalog.

    Returns counts; never raises for a bad row — it is reported in ``errors``.
    """
    src = text if text is not None else BUNDLED.read_text(encoding="utf-8")
    reader = csv.DictReader(io.StringIO(src.lstrip("\ufeff")))
    missing = [c for c in ("name",) if c not in (reader.fieldnames or [])]
    if missing:
        return {"ok": False, "code": "BAD_HEADER", "message": f"ستون‌های لازم وجود ندارد: {', '.join(missing)}",
                "expected_columns": COLUMNS}

    cat_cache: dict = {}
    brand_cache: dict = {}
    unit_cache: dict = {}
    existing_names = {
        (catalog._normalize_name(n), c) for n, c in db.execute(select(Product.name, Product.category_id)).all()
    }
    created = skipped = 0
    errors: list[dict] = []
    for i, row in enumerate(reader, start=2):
        name = (row.get("name") or "").strip()
        if not name:
            skipped += 1
            continue
        try:
            top = _category(db, row.get("category", ""), None, cat_cache)
            cat_id = _category(db, row.get("subcategory", ""), top, cat_cache)
            key = (catalog._normalize_name(name), cat_id)
            if key in existing_names:
                skipped += 1
                continue
            barcode = (row.get("barcode") or "").strip() or None
            if barcode and catalog.get_product_by_barcode(db, barcode):
                skipped += 1
                continue
            if dry_run:
                created += 1
                existing_names.add(key)
                continue
            catalog.create_product(
                db, barcode=barcode, name=name, user=user,
                brand_id=_brand(db, row.get("brand", ""), brand_cache),
                category_id=cat_id,
                unit_id=_unit(db, row.get("unit", ""), unit_cache),
                min_stock_alert=int(row.get("min_stock_alert") or 0),
                has_own_barcode=bool(barcode),
            )
            existing_names.add(key)
            created += 1
        except Exception as exc:  # noqa: BLE001 — one bad row must not abort the batch
            errors.append({"line": i, "name": name, "error": str(exc)})
    return {"ok": True, "created": created, "skipped": skipped, "errors": errors,
            "dry_run": dry_run, "source": "upload" if text is not None else "bundled",
            "stock_note": "همهٔ کالاها با موجودی صفر ایجاد شدند؛ موجودی فقط با رسید ورود (بچ) اضافه می‌شود."}


def bundled_summary() -> dict:
    rows = list(csv.DictReader(io.StringIO(BUNDLED.read_text(encoding="utf-8"))))
    cats: dict[str, set] = {}
    for r in rows:
        cats.setdefault(r["category"], set()).add(r["subcategory"])
    return {"products": len(rows), "categories": len(cats),
            "subcategories": sum(len(v) for v in cats.values()),
            "tree": {k: sorted(v) for k, v in cats.items()}, "columns": COLUMNS}
