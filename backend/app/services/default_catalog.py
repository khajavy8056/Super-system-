"""§80–82 / v3.5 — the DEFAULT PRODUCT BANK that ships inside the app.

``data/default_catalog.csv`` is generated from the 13 Excel sheets in ``docs/``
by ``scripts/build_default_catalog.py`` — do not hand-edit the CSV. It carries
every supermarket line a shop is likely to scan:

    category, subcategory, name, brand, unit, min_stock_alert, barcode,
    image_url, images

Import rules (unchanged from §80, extended for pictures):

* **zero stock.** Products are created as ``Product`` rows only — never a
  ``ProductBatch`` — so stock stays 0 until the first receiving.
* **idempotent.** A barcode that already exists is skipped, and so is a product
  with the same normalised name inside the same category. Re-running the import
  (or running it after the shop already typed a few products) never duplicates.
* **pictures come with the product.** ``image_url`` is the first direct link and
  ``gallery`` the rest; nothing is looked up on the web any more (v3.5 removed
  the OpenFoodFacts / Wikimedia / DuckDuckGo picture hunt — the bank already has
  a picture for 13 537 of its 13 570 lines).
* **never raises for one bad row.** A broken line is reported in ``errors`` and
  the rest of the bank still lands.

Performance: 13 570 rows are imported with a bulk ``INSERT`` in chunks, so the
whole bank lands in a couple of seconds instead of one round trip per product.
"""
from __future__ import annotations

import csv
import io
import json
import logging
from collections import OrderedDict
from pathlib import Path

from sqlalchemy import func, insert, select
from sqlalchemy.orm import Session

from ..models import Brand, Category, Product, Unit
from . import catalog
from .catalog import _normalize_name

log = logging.getLogger("supermarket.default_catalog")

BUNDLED = Path(__file__).resolve().parent.parent / "data" / "default_catalog.csv"
COLUMNS = ["category", "subcategory", "name", "brand", "unit",
           "min_stock_alert", "barcode", "image_url", "images"]
CHUNK = 1000
INTERNAL_PREFIX = "INT-"


# --------------------------------------------------------------------- helpers
def _split_images(raw: str) -> list[str]:
    return [u for u in (u.strip() for u in (raw or "").split("|")) if u][:3]


def _preload(db: Session) -> tuple[set, set, dict, dict, dict, dict]:
    """Everything the importer needs about the current catalogue, in 5 queries.

    Doing this per row would mean ~40 000 round trips for one import.
    """
    barcodes = set(db.execute(select(Product.barcode)).scalars().all())
    existing_names = {
        (_normalize_name(n or ""), c)
        for n, c in db.execute(select(Product.name, Product.category_id)).all()
    }
    # v3.5.1 — products the shop typed by hand before the bank existed. These
    # carry no manufacturer GTIN of their own (the API mints an internal INT-
    # code for them), so barcode equality can never match them and the import
    # used to create a second row with the same name. Indexed by normalised name
    # so the importer can reconcile instead of duplicating.
    hand_typed: dict[str, list[int]] = {}
    for pid, nm in db.execute(
        select(Product.id, Product.name).where(
            Product.deleted_at.is_(None), Product.has_own_barcode.is_(False)
        )
    ).all():
        hand_typed.setdefault(_normalize_name(nm or ""), []).append(pid)
    cats: dict = {}
    for cid, name, parent in db.execute(select(Category.id, Category.name, Category.parent_id)).all():
        cats[(name.lower(), parent)] = cid
    units = {
        key: uid
        for uid, name, sym in db.execute(select(Unit.id, Unit.name, Unit.symbol)).all()
        for key in {name, sym} if key
    }
    brands = {n.lower(): b for b, n in db.execute(select(Brand.id, Brand.name)).all()}
    return barcodes, existing_names, cats, units, brands, hand_typed


def _ensure_categories(db: Session, wanted: list[tuple[str, str | None]], cache: dict) -> None:
    """Create any missing category (top level first, then children), in bulk."""
    pending = [(n, p) for (n, p) in wanted if (n.lower(), p) not in cache]
    if not pending:
        return
    # parents must exist before children can point at them
    pending.sort(key=lambda t: 0 if t[1] is None else 1)
    for name, parent in pending:
        key = (name.lower(), parent)
        if key in cache:
            continue
        row = db.execute(
            select(Category.id).where(func.lower(Category.name) == name.lower())
            .where(Category.parent_id.is_(None) if parent is None else Category.parent_id == parent)
        ).scalar_one_or_none()
        if row is None:
            db.add(Category(name=name, parent_id=parent))
            db.flush()
            row = db.execute(select(Category.id).where(Category.name == name)
                             .where(Category.parent_id.is_(None) if parent is None
                                    else Category.parent_id == parent)).scalar_one()
        cache[key] = row


def _ensure_unit(db: Session, name: str, cache: dict) -> int | None:
    name = (name or "عدد").strip() or "عدد"
    if name in cache:
        return cache[name]
    row = db.execute(select(Unit).where((Unit.name == name) | (Unit.symbol == name))).scalar_one_or_none()
    if row is None:
        row = Unit(name=name, symbol=name,
                   allow_decimal=any(w in name for w in ("کیلو", "گرم", "لیتر", "متر")),
                   decimals=3 if any(w in name for w in ("کیلو", "گرم", "لیتر", "متر")) else 0)
        db.add(row)
        db.flush()
    cache[name] = row.id
    return row.id


def _ensure_brand(db: Session, name: str, cache: dict) -> int | None:
    name = (name or "").strip()
    if not name:
        return None
    key = name.lower()
    if key in cache:
        return cache[key]
    row = db.execute(select(Brand.id).where(func.lower(Brand.name) == key)).scalar_one_or_none()
    if row is None:
        db.add(Brand(name=name))
        db.flush()
        row = db.execute(select(Brand.id).where(func.lower(Brand.name) == key)).scalar_one()
    cache[key] = row
    return row


# ------------------------------------------------------------------ the import
def import_csv(db: Session, text: str | None = None, *, user=None, dry_run: bool = False) -> dict:
    """Import ``text`` (CSV with COLUMNS header) or the bundled default bank.

    Returns counts; never raises for a bad row — it is reported in ``errors``.
    """
    src = text if text is not None else BUNDLED.read_text(encoding="utf-8")
    reader = csv.DictReader(io.StringIO(src.lstrip("\ufeff")))
    missing = [c for c in ("name",) if c not in (reader.fieldnames or [])]
    if missing:
        return {"ok": False, "code": "BAD_HEADER",
                "message": f"ستون‌های لازم وجود ندارد: {', '.join(missing)}",
                "expected_columns": COLUMNS}

    barcodes, existing_names, cats, units, brands, hand_typed = _preload(db)
    created = skipped_barcode = skipped_name = skipped_empty = reconciled = 0
    images_with = 0
    errors: list[dict] = []
    tree: "OrderedDict[str, set]" = OrderedDict()

    def flush(rows: list[dict]) -> None:
        if rows:
            db.execute(insert(Product), rows)

    batch: list[dict] = []
    for i, row in enumerate(reader, start=2):
        name = (row.get("name") or "").strip()
        if not name:
            skipped_empty += 1
            continue
        try:
            top_name = (row.get("category") or "").strip()
            sub_name = (row.get("subcategory") or "").strip()
            top_id = None
            if top_name:
                _ensure_categories(db, [(top_name, None)], cats)
                top_id = cats[(top_name.lower(), None)]
            cat_id = top_id
            if sub_name and top_id is not None:
                _ensure_categories(db, [(sub_name, top_id)], cats)
                cat_id = cats[(sub_name.lower(), top_id)]
            tree.setdefault(top_name or "—", set()).add(sub_name or "—")

            barcode = (row.get("barcode") or "").strip()
            has_own = bool(barcode) and not barcode.startswith(INTERNAL_PREFIX)

            if barcode and barcode in barcodes:
                skipped_barcode += 1
                continue

            norm_name = _normalize_name(name)

            # v3.5.1 — RECONCILE with a product the shop typed by hand before the
            # bank existed. Such a row carries no manufacturer GTIN (the API mints
            # an internal INT- code), so the barcode-equality rule above can never
            # match it and the import used to create a second row with the same
            # name — exactly the duplicate the cashier then has to disambiguate at
            # the till. Matching on the normalised name instead lets the shop's own
            # row keep its id (and any stock or history attached to it) while
            # adopting the exact code, category and picture it was missing.
            #
            # Deliberately narrow: only when the match is UNAMBIGUOUS (one
            # candidate, not several) and only onto a row that has no real code of
            # its own, so a genuine GTIN the shop already recorded is never
            # overwritten.
            if has_own and barcode:
                candidates = hand_typed.get(norm_name) or []
                if len(candidates) == 1:
                    pid = candidates.pop()
                    if not dry_run:
                        target = db.get(Product, pid)
                        if target is not None:
                            target.barcode = barcode
                            target.has_own_barcode = True
                            if cat_id is not None and target.category_id is None:
                                target.category_id = cat_id
                            if target.unit_id is None:
                                target.unit_id = _ensure_unit(db, row.get("unit") or "عدد", units)
                            if target.brand_id is None:
                                target.brand_id = _ensure_brand(db, row.get("brand") or "", brands)
                            row_imgs = _split_images(row.get("images") or "")
                            row_image = (row.get("image_url") or "").strip() or (row_imgs[0] if row_imgs else None)
                            if row_image and not target.image_url:
                                target.image_url = row_image
                            if len(row_imgs) > 1 and not target.gallery:
                                target.gallery = json.dumps(row_imgs, ensure_ascii=False)
                            if row_image:
                                images_with += 1
                    barcodes.add(barcode)
                    existing_names.add((norm_name, cat_id))
                    reconciled += 1
                    continue

            key = (norm_name, cat_id)
            # §32 — barcode equality is the ONLY hard identity rule. Two bank
            # lines may legitimately share a normalised name inside one category
            # (different pack size, a re-branded line) and still be different
            # goods with different GTINs, so the name guard is applied ONLY to
            # rows that carry no real code of their own: it exists to stop the
            # import duplicating a loose/bulk product the shop typed by hand,
            # never to drop a scanned manufacturer code.
            if not has_own and key in existing_names:
                skipped_name += 1
                continue

            imgs = _split_images(row.get("images") or "")
            image_url = (row.get("image_url") or "").strip() or (imgs[0] if imgs else None)
            if image_url:
                images_with += 1

            if dry_run:
                created += 1
                if barcode:
                    barcodes.add(barcode)
                existing_names.add(key)
                continue

            batch.append({
                "barcode": barcode or None,
                "name": name,
                "sku": None,
                "brand_id": _ensure_brand(db, row.get("brand") or "", brands),
                "category_id": cat_id,
                "unit_id": _ensure_unit(db, row.get("unit") or "عدد", units),
                "model": None,
                "description": None,
                "image_url": image_url,
                "gallery": json.dumps(imgs, ensure_ascii=False) if len(imgs) > 1 else None,
                "min_stock_alert": int(row.get("min_stock_alert") or 0),
                "is_active": True,
                "has_own_barcode": has_own,
            })
            if barcode:
                barcodes.add(barcode)
            existing_names.add(key)
            created += 1

            if len(batch) >= CHUNK:
                flush(batch)
                batch = []
        except Exception as exc:  # noqa: BLE001 — one bad row must not abort the batch
            errors.append({"line": i, "name": name, "error": str(exc)})
            if len(errors) > 50:
                break

    if not dry_run:
        flush(batch)

    return {
        "ok": True, "created": created,
        "skipped": skipped_barcode + skipped_name + skipped_empty,
        "skipped_duplicate_barcode": skipped_barcode,
        "skipped_duplicate_name": skipped_name,
        "skipped_empty": skipped_empty,
        # v3.5.1 — hand-typed products the import matched instead of duplicating
        "reconciled_existing": reconciled,
        "with_image": images_with,
        "errors": errors[:50],
        "dry_run": dry_run,
        "source": "upload" if text is not None else "bundled",
        "stock_note": "همهٔ کالاها با موجودی صفر ایجاد شدند؛ موجودی فقط با رسید ورود (بچ) اضافه می‌شود.",
    }


def bundled_summary() -> dict:
    """Describe the bundled bank without importing it (the setup wizard shows this)."""
    rows = list(csv.DictReader(io.StringIO(BUNDLED.read_text(encoding="utf-8"))))
    cats: "OrderedDict[str, set]" = OrderedDict()
    with_image = 0
    for r in rows:
        cats.setdefault(r["category"] or "—", set()).add(r["subcategory"] or "—")
        if (r.get("image_url") or "").strip():
            with_image += 1
    return {
        "products": len(rows),
        "categories": len(cats),
        "subcategories": sum(len(v) for v in cats.values()),
        "with_image": with_image,
        "columns": COLUMNS,
        "stock": 0,
        "tree": {k: sorted(v) for k, v in cats.items()},
    }


# Backwards-compatible aliases — `starter_catalog` was the v2.x name for the same
# feature and is still imported by the setup router and by older tests.
def bundled_path() -> Path:
    return BUNDLED
