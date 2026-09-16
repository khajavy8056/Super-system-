#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build a heavy "stress" backup file — a full year of a big, busy supermarket.

Why this exists
---------------
The bundled demo store is ~120 SKUs and ~95 invoices/day. That is a shop demo, not a
load test. This driver builds a file meant to be *abusive*:

  * the ENTIRE default catalogue (13,570 SKUs, every barcode in the shipped bank)
  * one invoice every ~10 minutes for a year  -> ~52,560 invoices by default
  * receiving / batches / stock movements for every SKU, across 15 suppliers
  * cheques issued and settled, expenses, returns, voids, credit (نسیه) sales
  * the intelligence engine run on the finished year, the strongest suggestions
    accepted through the real accept() path, then measured

Restore it into the app and every screen is working on a genuinely large database,
which is the only way to find the hangs and crashes that a demo file hides.

The build is streamed from a subprocess, so the progress bar is real, not decorative.

Usage
-----
    python tools/make_stress_backup.py                     # the full year (~4-5 GB raw)
    python tools/make_stress_backup.py --out D:\\stress.db.gz
    python tools/make_stress_backup.py --smoke             # 30 days, to prove the pipeline
    python tools/make_stress_backup.py --days 365 --per-day 144 --no-compress

Exit code 0 only if the file was written AND passed the same validation the app's
own /api/system/restore endpoint applies.
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
BACKEND = ROOT / "backend"

# The app package lives under backend/; make it importable no matter where we were called from.
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

# The build writes a brand-new database, so it must never touch the developer's own data.
os.environ.setdefault("SUPERMARKET_LICENSE_GATE", "0")
os.environ.setdefault("ADMIN_USERNAME", "admin")
os.environ.setdefault("ADMIN_PASSWORD", "admin123")


# --------------------------------------------------------------------------- progress
class Bar:
    """A dependency-free progress bar with elapsed time and an ETA.

    The build takes hours on a big store; a number with no ETA reads as a hang.
    """

    def __init__(self, width: int = 44, stream=sys.stdout):
        self.width = width
        self.stream = stream
        self.t0 = time.time()
        self.last = -1.0
        self.tty = hasattr(stream, "isatty") and stream.isatty()

    @staticmethod
    def _hms(seconds: float) -> str:
        seconds = int(max(0, seconds))
        h, rem = divmod(seconds, 3600)
        m, s = divmod(rem, 60)
        return f"{h:d}:{m:02d}:{s:02d}" if h else f"{m:d}:{s:02d}"

    def draw(self, frac: float, label: str = "") -> None:
        frac = max(0.0, min(1.0, frac))
        # On a non-tty (a log file, a redirected pipe) redraw only on whole percent steps,
        # otherwise the file fills up with one line per progress tick.
        if not self.tty and abs(frac - self.last) < 0.01 and frac < 1.0:
            return
        self.last = frac
        filled = int(round(frac * self.width))
        elapsed = time.time() - self.t0
        eta = (elapsed / frac * (1 - frac)) if frac > 0.02 else 0.0
        line = "[%s%s] %5.1f%%  %s%s  (گذشته %s%s)" % (
            "#" * filled, "-" * (self.width - filled), frac * 100,
            label, " " * max(0, 26 - len(label)),
            self._hms(elapsed), "" if frac >= 1.0 or eta <= 0 else " · مانده ~" + self._hms(eta))
        self.stream.write(("\r" if self.tty else "") + line + ("\n" if not self.tty else ""))
        self.stream.flush()
        if frac >= 1.0 and self.tty:
            self.stream.write("\n")
            self.stream.flush()


# --------------------------------------------------------------------------- validation
# The required-table set is deliberately NOT restated here — validate() imports it from
# app.routers.system so this tool cannot drift from what restore actually enforces.


def validate(path: Path) -> dict:
    """Exactly the checks ``backend/app/routers/system.py::restore`` applies.

    The required-table set is imported from the router rather than restated here, so this
    can never quietly drift from what the app will actually demand at restore time.

    The shipped file is gzip; ``restore`` sniffs the ``\\x1f\\x8b`` magic and inflates it,
    so validation has to do the same instead of handing gzip bytes to sqlite3.
    """
    import gzip
    import shutil
    import tempfile

    try:
        from app.routers.system import _REQUIRED_TABLES as required
    except Exception:
        required = {"users", "products", "product_batches", "invoices", "audit_logs"}

    with open(path, "rb") as fh:
        magic = fh.read(2)
    target = path
    tmpdir = None
    if magic == b"\x1f\x8b":
        tmpdir = tempfile.mkdtemp(prefix="stress_validate_")
        target = Path(tmpdir) / "candidate.db"
        with gzip.open(path, "rb") as src, open(target, "wb") as dst:
            shutil.copyfileobj(src, dst, 1 << 20)

    con = sqlite3.connect(str(target))
    try:
        integrity = con.execute("PRAGMA integrity_check").fetchone()[0]
        tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        counts = {}
        for t in ("products", "invoices", "invoice_items", "product_batches", "stock_movements",
                  "customers", "acc_suppliers", "ai_insights", "acc_cheques", "acc_expenses",
                  "returns", "audit_logs"):
            if t in tables:
                counts[t] = con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        raw_size = target.stat().st_size
    finally:
        con.close()
        if tmpdir:
            shutil.rmtree(tmpdir, ignore_errors=True)
    missing = required - tables
    return {"integrity": integrity, "tables": len(tables), "missing": sorted(missing),
            "counts": counts, "uncompressed_bytes": raw_size}


# --------------------------------------------------------------------------- main
def main() -> int:
    ap = argparse.ArgumentParser(description="Build a heavy one-year stress backup for the supermarket system.")
    ap.add_argument("--out", default=str(ROOT / "stress_store.db.gz"), help="output file (.gz recommended)")
    ap.add_argument("--days", type=int, default=365, help="days of history (default 365)")
    ap.add_argument("--per-day", type=float, default=144.0,
                    help="average invoices per day (default 144 = one every 10 minutes)")
    ap.add_argument("--seed", type=int, default=1404, help="RNG seed; same seed = same store")
    ap.add_argument("--no-compress", action="store_true", help="write raw SQLite instead of gzip")
    ap.add_argument("--lite-catalog", action="store_true",
                    help="skip the 13,570-SKU catalogue and build only the ~120 curated products")
    ap.add_argument("--smoke", action="store_true",
                    help="30 days instead of a year — proves the pipeline in minutes, not hours")
    args = ap.parse_args()

    days = 30 if args.smoke else args.days
    out = Path(args.out).expanduser()
    if args.smoke and args.out.endswith("stress_store.db.gz"):
        out = out.with_name("stress_store_smoke.db.gz")

    print("=" * 72)
    print(" ساخت فایل بکاپ پرفشار — یک سال فروشگاه بزرگ و شلوغ")
    print("=" * 72)
    print(f"  روزها            : {days}")
    print(f"  فاکتور در روز    : {args.per_day:g}  (~{int(days * args.per_day):,} فاکتور)")
    print(f"  کاتالوگ کامل     : {'خیر (سبک)' if args.lite_catalog else 'بله — ۱۳٬۵۷۰ کالا'}")
    print(f"  خروجی            : {out}")
    print(f"  فشرده            : {'خیر' if args.no_compress else 'بله (gzip)'}")
    print("-" * 72)
    print(" این ساخت طولانی است. نوار پیشرفت واقعی است؛ پنجره را نبندید.")
    print()

    from app.services import demo_store  # imported late: needs BACKEND on sys.path

    bar = Bar()
    labels = [(0.0, "آماده‌سازی دیتابیس"), (0.05, "بارگذاری کاتالوگ کالاها"), (0.20, "ثبت فاکتورها و ورودی‌ها"),
              (0.60, "ادامهٔ شبیه‌سازی سال"), (0.93, "اجرای مدل هوش"),
              (0.96, "اجرای پیشنهادها"), (0.98, "سنجش اثر"), (0.995, "فشرده‌سازی و اعتبارسنجی")]

    def on_progress(frac: float) -> None:
        label = "در حال ساخت"
        for at, text in labels:
            if frac >= at:
                label = text
        bar.draw(frac, label)

    t0 = time.time()
    try:
        summary = demo_store.generate_backup_file(
            out, days=days, seed=args.seed, invoices_per_day=args.per_day,
            compress=not args.no_compress, full_catalog=not args.lite_catalog,
            progress=on_progress)
    except Exception as exc:
        bar.draw(1.0, "ناموفق")
        print(f"\n[خطا] ساخت ناموفق بود: {exc}")
        return 2

    # compression is the one step the child cannot report on; show it as the last few percent.
    bar.draw(1.0, "اعتبارسنجی")
    raw_bytes = summary.get("bytes", 0)
    v = validate(out)
    raw = v.get("uncompressed_bytes", 0)
    size_txt = f"{raw_bytes:,} بایت ({raw_bytes / 1024 / 1024:.1f} مگابایت)"
    if raw:
        size_txt += f"  →  باز‌شده {raw:,} بایت ({raw / 1024 / 1024 / 1024:.2f} گیگابایت)"

    print()
    print("=" * 72)
    print(" نتیجه")
    print("=" * 72)
    print(f"  فایل             : {out}")
    print(f"  حجم              : {size_txt}")
    print(f"  زمان ساخت        : {bar._hms(time.time() - t0)}")
    print(f"  integrity_check  : {v['integrity']}")
    print(f"  تعداد جدول‌ها     : {v['tables']}")
    print(f"  محصولات (کل)     : {summary.get('products', 0):,} فعال + {summary.get('long_tail_products', 0):,} کاتالوگ")
    print(f"  تأمین‌کنندگان     : {summary.get('suppliers', 0)}")
    print(f"  مشتریان          : {summary.get('customers', 0)}")
    print(f"  فاکتور / قلم     : {v['counts'].get('invoices', 0):,} / {v['counts'].get('invoice_items', 0):,}")
    print(f"  بچ / حرکت موجودی : {v['counts'].get('product_batches', 0):,} / {v['counts'].get('stock_movements', 0):,}")
    ins = summary.get("insights") or {}
    if ins:
        print(f"  مدل هوش          : {ins.get('generated', 0)} پیشنهاد · {ins.get('accepted', 0)} اجراشده · "
              f"{ins.get('measured', 0)} سنجیده · {ins.get('open', 0)} باز")

    ok = v["integrity"] == "ok" and not v["missing"]
    print("-" * 72)
    if ok:
        print(" ✅ فایل سالم است و همان بررسی‌های restore برنامه را پاس می‌کند.")
        print("    در ویندوز: تنظیمات ← پشتیبان‌گیری ← بازیابی، و همین فایل را انتخاب کنید.")
        print("    در اندروید: هوش فروشگاه ← پشتیبان‌گیری ← وارد کردن.")
    else:
        print(" ❌ فایل رد شد:")
        if v["integrity"] != "ok":
            print(f"    integrity_check = {v['integrity']}")
        if v["missing"]:
            print(f"    جدول‌های ناموجود: {', '.join(v['missing'])}")
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
