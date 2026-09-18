#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build the DEFAULT PRODUCT CATALOGUE from the 13 Excel sheets in ``docs/``.

v3.5 — the shop no longer types its own product list and the system no longer
hunts for pictures on the web. Every supermarket line ships inside the app:
name + exact barcode + category/sub-category + up to three direct image links,
imported with ZERO stock (stock only ever appears through a receiving).

Input   docs/*.xlsx          13 sheets, columns: نام محصول | دسته | زیردسته | بارکد | تصویر 1..3
Output  backend/app/data/default_catalog.csv
        mobile-android/app/src/main/assets/default_catalog.csv   (identical copy)
        docs/DEFAULT_CATALOG_REPORT.md                           (data-quality report)

CSV columns: category,subcategory,name,brand,unit,min_stock_alert,barcode,image_url,images

``images`` is the pipe-separated list of the direct image links (a URL never
contains ``|``). No field is allowed to contain ``,`` ``"`` ``|`` or a newline,
which keeps the file safe for the deliberately simple CSV readers on the phone
(``Db.importStarter``) and on the PC.

Cleaning applied (every decision is counted and reported):
  * header variants      «دسته»/«دسته », «زیردسته»/«زیر دسته», «تصویر1»/«تصویر 1 » …
  * text                 trim, collapse repeated spaces, drop a ZWNJ stranded next
                         to a space, ASCII comma → Persian comma
  * barcodes             digits only; 11/12-digit values are EAN-13 codes whose
                         leading zeros Excel stripped → re-padded; a wrong check
                         digit is recomputed from the first 12 digits; EAN-8 kept
  * missing category     taken from the file name (a sheet is one department)
  * missing barcode      an internal code is minted (INT-D00001) so the line is
                         still selectable by name
  * duplicates           same barcode twice → first row wins and the image lists
                         are merged; two different products sharing one barcode →
                         the second gets an internal code instead of being lost

Usage:  python scripts/build_default_catalog.py            (writes all three files)
        python scripts/build_default_catalog.py --check    (rebuild + verify, no write)
"""
from __future__ import annotations

import argparse
import csv
import io
import re
import sys
import unicodedata
from collections import Counter, OrderedDict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
OUT_BACKEND = ROOT / "backend" / "app" / "data" / "default_catalog.csv"
OUT_ANDROID = ROOT / "mobile-android" / "app" / "src" / "main" / "assets" / "default_catalog.csv"
REPORT = DOCS / "DEFAULT_CATALOG_REPORT.md"

COLUMNS = ["category", "subcategory", "name", "brand", "unit",
           "min_stock_alert", "barcode", "image_url", "images"]

ZWNJ = "\u200c"
FA_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


# ---------------------------------------------------------------- text helpers
def clean_text(value) -> str:
    """Normalise a Persian cell: full-width → half-width, one space, tidy ZWNJ."""
    if value is None:
        return ""
    s = unicodedata.normalize("NFKC", str(value))
    s = s.replace("\u200f", "").replace("\u200e", "").replace("\r", " ").replace("\n", " ")
    s = re.sub(r"\s+", " ", s).strip()
    # a ZWNJ stranded next to a space is a typo ("پاک‌ کن" → "پاک‌کن", "‌900" → "900")
    s = s.replace(f" {ZWNJ}", "").replace(f"{ZWNJ} ", ZWNJ)
    s = re.sub(r"\s+", " ", s).strip(" \u200c")
    return s


def header_key(raw) -> str:
    """Map the many header spellings in the 13 sheets onto one internal name."""
    s = clean_text(raw).replace(ZWNJ, "").replace(" ", "")
    if s.startswith("ناممحصول"):
        return "name"
    if s.startswith("دسته"):
        return "category"
    if s.startswith("زیردسته"):
        return "subcategory"
    if s.startswith("بارکد"):
        return "barcode"
    if s.startswith("تصویر1"):
        return "img1"
    if s.startswith("تصویر2"):
        return "img2"
    if s.startswith("تصویر3"):
        return "img3"
    return ""


def file_category(path: Path) -> str:
    """«آرایشی-بهداشتی.xlsx» → «آرایشی و بهداشتی» — the sheet IS the department."""
    stem = clean_text(path.stem)
    stem = stem.replace("-", " و ").replace("،", "،")
    return re.sub(r"\s+", " ", stem).strip()


# ------------------------------------------------------------ barcode helpers
def ean_check_digit(body: str) -> int:
    total = 0
    for i, ch in enumerate(reversed(body)):
        total += int(ch) * (3 if i % 2 == 0 else 1)
    return (10 - total % 10) % 10


def normalise_barcode(raw: str) -> tuple[str, str]:
    """→ (barcode, fix_applied).  '' when the cell is empty.

    Excel stores a barcode as a NUMBER, so a GTIN that starts with 0 loses those
    zeros (13 digits become 11 or 12). Re-padding is exact — the check digit
    proves it. A wrong check digit is repaired from the first 12 digits, which is
    the standard single-digit-typo repair.
    """
    digits = clean_text(raw).translate(FA_DIGITS)
    digits = re.sub(r"\D", "", digits)
    if not digits:
        return "", ""
    if len(digits) in (11, 12):
        padded = digits.zfill(13)
        if ean_check_digit(padded[:12]) == int(padded[12]):
            return padded, "REPADDED_LEADING_ZEROS"
        digits = padded
    if len(digits) == 8:
        return (digits, "" if ean_check_digit(digits[:7]) == int(digits[7]) else "EAN8_CHECK_RECOMPUTED")
    if len(digits) == 13:
        if ean_check_digit(digits[:12]) == int(digits[12]):
            return digits, ""
        return digits[:12] + str(ean_check_digit(digits[:12])), "CHECK_DIGIT_RECOMPUTED"
    if len(digits) == 12:  # UPC-A that did not survive the padding check above
        return digits[:11] + str(ean_check_digit(digits[:11])), "UPC_CHECK_RECOMPUTED"
    return digits[:13].ljust(13, "0"), "TRUNCATED_TO_13"


# ------------------------------------------------------------------- the build
def load_rows(xlsx_files: list[Path]):
    """Read every sheet into normalised dicts + a Counter of what was fixed."""
    import openpyxl

    stats: Counter = Counter()
    rows: list[dict] = []
    for path in xlsx_files:
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        ws = wb.active
        it = ws.iter_rows(values_only=True)
        try:
            header = [header_key(h) for h in next(it)]
        except StopIteration:
            wb.close()
            continue
        fallback_cat = file_category(path)
        for raw in it:
            if raw is None or all(c is None or str(c).strip() == "" for c in raw):
                stats["blank_rows"] += 1
                continue
            rec = {k: clean_text(raw[i]) if i < len(raw) else ""
                   for i, k in enumerate(header) if k}
            rec["_file"] = path.name
            name = rec.get("name", "")
            if not name:
                stats["rows_without_name"] += 1
                continue
            stats["rows_read"] += 1
            if not rec.get("category"):
                rec["category"] = fallback_cat
                stats["category_from_filename"] += 1
            if not rec.get("subcategory"):
                stats["missing_subcategory"] += 1
            imgs = [rec.get(k, "") for k in ("img1", "img2", "img3")]
            rec["images"] = [u for u in (u.strip() for u in imgs) if u]
            if not rec["images"]:
                stats["rows_without_image"] += 1
            bc, fix = normalise_barcode(rec.get("barcode", ""))
            if fix:
                stats[f"fix:{fix}"] += 1
            if not bc:
                stats["rows_without_barcode"] += 1
            rec["barcode"] = bc
            rows.append(rec)
        wb.close()
    return rows, stats


def dedupe(rows: list[dict], stats: Counter) -> list[dict]:
    """One row per barcode (image lists merged); barcode-less rows keyed by name."""
    by_barcode: "OrderedDict[str, dict]" = OrderedDict()
    out: list[dict] = []
    seen_names: set[tuple[str, str, str]] = set()
    for rec in rows:
        name_key = (rec["category"].lower(), rec["subcategory"].lower(), rec["name"].lower())
        bc = rec["barcode"]
        if bc:
            hit = by_barcode.get(bc)
            if hit is None:
                by_barcode[bc] = rec
                out.append(rec)
                seen_names.add(name_key)
                continue
            merged = [u for u in hit["images"] + rec["images"]]
            uniq: list[str] = []
            for u in merged:
                if u not in uniq:
                    uniq.append(u)
            hit["images"] = uniq[:3]
            if name_key in seen_names:
                stats["dup_exact_rows"] += 1
            else:
                # Same barcode, a DIFFERENT product name: the source data is wrong
                # about one of them. Keep the first under the real GTIN and give
                # the second an internal code so it is not silently dropped.
                rec["barcode"] = ""
                stats["dup_barcode_conflict"] += 1
                out.append(rec)
                seen_names.add(name_key)
            continue
        if name_key in seen_names:
            stats["dup_name_no_barcode"] += 1
            continue
        seen_names.add(name_key)
        out.append(rec)
    # mint internal codes for whatever is left without a GTIN
    seq = 0
    for rec in out:
        if not rec["barcode"]:
            seq += 1
            rec["barcode"] = f"INT-D{seq:05d}"
            stats["internal_barcode_minted"] += 1
    return out


def sanitise_field(value: str) -> str:
    """Guarantee the CSV stays trivially parseable (see the module docstring)."""
    return (value.replace(",", "،").replace('"', "").replace("|", "/")
            .replace("\n", " ").replace("\r", " ").strip())


def write_csv(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(COLUMNS)
    for r in records:
        field = (lambda value: value) if r.get("_exact_source") else sanitise_field
        w.writerow([
            field(r["category"]),
            field(r["subcategory"]),
            field(r["name"]),
            "",                      # brand: the sheets carry no brand column
            "عدد",                    # sold by the piece; weight/volume live in the name
            0,                       # min_stock_alert
            field(r["barcode"]),
            field(r["images"][0]) if r["images"] else "",
            "|".join(sanitise_field(u) for u in r["images"][:3]),
        ])
    path.write_text(buf.getvalue(), encoding="utf-8", newline="")


def write_report(path: Path, xlsx_files: list[Path], records: list[dict], stats: Counter) -> None:
    cats: "OrderedDict[str, set]" = OrderedDict()
    with_img = 0
    for r in records:
        cats.setdefault(r["category"], set()).add(r["subcategory"])
        if r["images"]:
            with_img += 1
    fixes = {k[4:]: v for k, v in sorted(stats.items()) if k.startswith("fix:")}
    lines = [
        "# گزارش بانک پیش‌فرض کالاها",
        "",
        "این فایل توسط `scripts/build_default_catalog.py` از اکسل‌های `docs/` و همهٔ زیرپوشه‌های `docs/200/` ساخته شده است.",
        "دستی ویرایشش نکنید؛ فایل اکسل را اصلاح کنید و اسکریپت را دوباره اجرا کنید.",
        "",
        "## خلاصه",
        "",
        f"| مورد | تعداد |",
        f"|---|---|",
        f"| فایل‌های ورودی | {len(xlsx_files)} |",
        f"| سطرهای خوانده‌شده | {stats['rows_read']} |",
        f"| کالای نهایی در بانک | {len(records)} |",
        f"| دسته | {len(cats)} |",
        f"| زیردسته | {sum(len(v) for v in cats.values())} |",
        f"| کالا با تصویر | {with_img} |",
        f"| کالا با بارکد واقعی (غیر داخلی) | {sum(1 for r in records if not r['barcode'].startswith('INT-'))} |",
        "",
        "## پاک‌سازی انجام‌شده",
        "",
    ]
    labels = {
        "blank_rows": "سطرهای خالی (نادیده گرفته شد)",
        "rows_without_name": "سطرهای بدون نام (نادیده گرفته شد)",
        "category_from_filename": "دسته از نام فایل پر شد",
        "missing_subcategory": "بدون زیردسته",
        "rows_without_image": "بدون تصویر",
        "rows_without_barcode": "بدون بارکد در فایل اصلی",
        "dup_exact_rows": "سطر تکراری (هم بارکد هم نام) — حذف شد",
        "dup_barcode_conflict": "دو کالای متفاوت با یک بارکد — دومی کد داخلی گرفت",
        "dup_name_no_barcode": "نام تکراری بدون بارکد — حذف شد",
        "internal_barcode_minted": "کد داخلی ساخته شد (INT-D…)",
    }
    for key, label in labels.items():
        if stats.get(key):
            lines.append(f"- {label}: **{stats[key]}**")
    if fixes:
        lines += ["", "### اصلاح بارکدها", ""]
        fix_labels = {
            "REPADDED_LEADING_ZEROS": "صفرهای ابتدایی که اکسل حذف کرده بود برگردانده شد",
            "CHECK_DIGIT_RECOMPUTED": "رقم کنترلی EAN-13 دوباره محاسبه شد",
            "EAN8_CHECK_RECOMPUTED": "رقم کنترلی EAN-8 دوباره محاسبه شد",
            "UPC_CHECK_RECOMPUTED": "رقم کنترلی UPC-A دوباره محاسبه شد",
            "TRUNCATED_TO_13": "به ۱۳ رقم نرمال شد",
        }
        for k, v in fixes.items():
            lines.append(f"- {fix_labels.get(k, k)}: **{v}**")
    lines += ["", "## دسته‌ها", ""]
    for cat, subs in sorted(cats.items()):
        real = [s for s in sorted(subs) if s]
        lines.append(f"- **{cat}** — {len(real)} زیردسته")
    lines += ["", "## ستون‌های CSV", "",
              "`" + "`, `".join(COLUMNS) + "`", "",
              "`images` فهرست لینک‌های مستقیم تصویر است که با `|` از هم جدا شده‌اند "
              "(یک URL هرگز `|` ندارد)، پس فایل برای خوانندهٔ سادهٔ CSV در اپ موبایل امن است.",
              ""]
    path.write_text("\n".join(lines), encoding="utf-8")


def verify(path: Path) -> list[str]:
    """Hard checks on the generated file — run by the test suite and by --check."""
    problems: list[str] = []
    text = path.read_text(encoding="utf-8")
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames != COLUMNS:
        problems.append(f"header mismatch: {reader.fieldnames}")
    barcodes: set[str] = set()
    n = 0
    for i, row in enumerate(reader, start=2):
        n += 1
        bc = row["barcode"]
        if not bc:
            problems.append(f"line {i}: empty barcode")
        if bc in barcodes:
            problems.append(f"line {i}: duplicate barcode {bc}")
        barcodes.add(bc)
        if not row["name"].strip():
            problems.append(f"line {i}: empty name")
        if not row["category"].strip():
            problems.append(f"line {i}: empty category")
        for field in COLUMNS:
            v = row[field] or ""
            if "|" in v and field != "images":
                problems.append(f"line {i}: unsafe char in {field}")
            if "\n" in v or "\r" in v:
                problems.append(f"line {i}: newline in {field}")
        imgs = [u for u in (row["images"] or "").split("|") if u]
        if row["image_url"] and (not imgs or imgs[0] != row["image_url"]):
            problems.append(f"line {i}: image_url not the first entry of images")
        if len(imgs) > 3:
            problems.append(f"line {i}: more than 3 images")
        for u in imgs:
            if not u.startswith("http"):
                problems.append(f"line {i}: image is not a URL: {u[:40]}")
    if n < 13000:
        problems.append(f"only {n} rows — expected the full 13-sheet bank")
    return problems


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="rebuild into memory, verify, change nothing")
    args = ap.parse_args(argv)

    try:
        import openpyxl  # noqa: F401
    except ImportError:
        print("openpyxl is required:  pip install openpyxl", file=sys.stderr)
        return 2

    xlsx_files = sorted(DOCS.glob("*.xlsx"))
    if not xlsx_files:
        print(f"no .xlsx files in {DOCS}", file=sys.stderr)
        return 2

    rows, stats = load_rows(xlsx_files)
    records = dedupe(rows, stats)
    from catalog_200 import append
    import json
    extra = append(records, DOCS / "200")
    xlsx_files += sorted((DOCS / "200").rglob("*.xlsx"))
    stats["rows_read"] += extra["rows"]
    stats["rows_without_image"] += extra["rows"]
    if not args.check:
        (DOCS / "CATALOG_200_REPORT.json").write_text(json.dumps(extra, ensure_ascii=False, indent=2), encoding="utf-8")
    problems = []
    if args.check:
        import tempfile
        with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, encoding="utf-8") as fh:
            tmp = Path(fh.name)
        write_csv(tmp, records)
        problems = verify(tmp)
        if tmp.read_bytes() != OUT_BACKEND.read_bytes() or tmp.read_bytes() != OUT_ANDROID.read_bytes():
            problems.append("packaged catalog differs from reproducible workbook build")
        tmp.unlink(missing_ok=True)
    else:
        write_csv(OUT_BACKEND, records)
        write_csv(OUT_ANDROID, records)
        write_report(REPORT, xlsx_files, records, stats)
        problems = verify(OUT_BACKEND)

    print(f"sheets={len(xlsx_files)} rows_read={stats['rows_read']} products={len(records)}")
    for k in sorted(stats):
        if not k.startswith("fix:") and stats[k]:
            print(f"  {k}: {stats[k]}")
    for k in sorted(stats):
        if k.startswith("fix:") and stats[k]:
            print(f"  {k[4:]}: {stats[k]}")
    if problems:
        print(f"\nVERIFY FAILED ({len(problems)} problems):", file=sys.stderr)
        for p in problems[:25]:
            print(f"  - {p}", file=sys.stderr)
        return 1
    print("verify: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
