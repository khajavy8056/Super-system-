#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build a heavy "stress" backup file — a full year of a big, busy supermarket.

Why this exists
---------------
The bundled demo store is ~120 SKUs and ~95 invoices/day. That is a shop demo, not a
load test. This driver builds a file meant to be *abusive*:

  * the ENTIRE default catalogue (13,570 SKUs, every barcode in the shipped bank)
  * 1,100 invoices/day target (actual persisted count is validated separately)
  * receiving / batches / stock movements for every SKU, across 15 suppliers
  * cheques issued and settled, expenses, returns, voids, credit (نسیه) sales
  * the intelligence engine run on the finished year, the strongest suggestions
    accepted through the real accept() path, then measured

Restore it into the app and every screen is working on a genuinely large database,
which is the only way to find the hangs and crashes that a demo file hides.

The build is streamed from a subprocess, so the progress bar is real, not decorative.

Usage
-----
    python tools/make_stress_backup.py                     # the full year (disk size and runtime must be measured)
    python tools/make_stress_backup.py --out D:\\stress.db.gz
    python tools/make_stress_backup.py --smoke             # 30 days, to prove the pipeline
    python tools/make_stress_backup.py --days 365 --per-day 1100 --minimum-invoices 365000 --no-compress
    python tools/make_stress_backup.py --python C:\\Python312\\python.exe

Dependencies
------------
Nothing has to be installed by hand. If the interpreter that launched this file cannot
import the backend's libraries (the normal case on a machine that only ever ran the
packaged app), it creates ``tools/.venv``, pip-installs ``backend/requirements.txt`` into
it once, and re-runs itself there. ``--no-bootstrap`` turns that off and just reports
what is missing; ``--force-deps`` reinstalls.

Exit code 0 only if the file was written AND passed the same validation the app's
own /api/system/restore endpoint applies. 4 means "dependencies missing and the
automatic install did not work"; the message above it says exactly what to run.
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
REQUIREMENTS = BACKEND / "requirements.txt"

# The app package lives under backend/; make it importable no matter where we were called from.
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

# A shop owner double-clicks the .bat from an unzipped GitHub download. Their Python has no
# third-party packages in it, so a bare `import app.services.demo_store` dies with
# "No module named 'sqlalchemy'" — which is what v3.5.9 printed. Persian console output also
# dies with UnicodeEncodeError when stdout is redirected under a cp1256 code page.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    except Exception:
        pass

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

    con = sqlite3.connect(target.resolve().as_uri() + "?mode=ro", uri=True)
    # Audit large snapshots without growing an unbounded in-memory sort/cache.
    con.execute("PRAGMA temp_store=FILE")
    con.execute("PRAGMA cache_size=-32768")
    try:
        integrity = con.execute("PRAGMA integrity_check").fetchone()[0]
        tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        counts = {}
        for t in ("products", "invoices", "invoice_items", "product_batches", "stock_movements",
                  "customers", "acc_suppliers", "ai_insights", "acc_cheques", "acc_expenses",
                  "returns", "audit_logs"):
            if t in tables:
                counts[t] = con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        foreign_key_errors = con.execute("PRAGMA foreign_key_check").fetchmany(25)
        daily = con.execute("SELECT substr(created_at,1,10), COUNT(*) FROM invoices GROUP BY substr(created_at,1,10) ORDER BY 1").fetchall() if "invoices" in tables else []
        from app.services.simulation_audit import audit
        economic = audit(con)
        raw_size = target.stat().st_size
    finally:
        con.close()
        if tmpdir:
            shutil.rmtree(tmpdir, ignore_errors=True)
    missing = required - tables
    return {"integrity": integrity, "tables": len(tables), "missing": sorted(missing),
            "counts": counts, "uncompressed_bytes": raw_size,
            "foreign_key_errors": foreign_key_errors, "daily_invoices": daily, "economic": economic}


# --------------------------------------------------------------------------- dependencies
# v3.5.10 — the tool used to assume the Python it was launched with already had the backend's
# libraries installed. On a plain Windows machine it does not, and the user got a
# ModuleNotFoundError instead of a backup file. The tool now installs what it needs into a
# private venv (tools/.venv) and re-runs itself there, so a double-click is still enough.

#: Probe set, measured from the real import chain rather than guessed:
#: ``app.services.demo_store`` needs sqlalchemy + pydantic + pydantic_settings, and
#: ``app.routers.system`` (imported by validate()) needs fastapi.
PROBE_PACKAGES = ("sqlalchemy", "pydantic", "pydantic_settings", "fastapi")

#: argv as the user typed it, so a re-exec can forward the flags verbatim.
_ORIG_ARGV = list(sys.argv[1:])


def _missing_packages() -> list[str]:
    import importlib

    missing = []
    for name in PROBE_PACKAGES:
        try:
            importlib.import_module(name)
        except Exception:
            missing.append(name)
    return missing


def _venv_python(venv_dir: Path) -> Path:
    if os.name == "nt":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def _show(cmd: list[str]) -> None:
    print("   $ " + " ".join(f'"{c}"' if " " in str(c) else str(c) for c in cmd))


def _manual_help(missing: list[str]) -> None:
    print()
    print("-" * 72)
    print(" کتابخانه‌های زیر در پایتون شما نصب نیستند:")
    print("   " + ", ".join(missing))
    print()
    print(" نصب خودکار ممکن نشد. اگر اینترنت دارید، این دو خط را در CMD اجرا کنید:")
    print(f'   "{sys.executable}" -m venv "{HERE / ".venv"}"')
    print(f'   "{_venv_python(HERE / ".venv")}" -m pip install -r "{REQUIREMENTS}"')
    print(" و بعد دوباره make-stress-backup.bat را اجرا کنید (بار دوم نصب را رد می‌کند).")
    print("-" * 72)


def _reexec(python: Path, argv: list[str]) -> int:
    """Run this same script under a different interpreter and hand back its exit code."""
    import subprocess

    cmd = [str(python), str(Path(__file__).resolve()), *argv, "--no-bootstrap"]
    _show(cmd)
    print()
    try:
        return subprocess.run(cmd).returncode
    except OSError as exc:
        print(f"\n[خطا] اجرای {python} ممکن نشد: {exc}")
        return 4


def ensure_dependencies(args):
    """Make sure the backend's libraries are importable.

    Returns ``None`` when THIS process may go on and build, or an ``int`` exit code when it
    must stop — including the case where a bootstrapped child already did the whole job. That
    distinction is the whole function: returning 0 for "the child finished" made the parent
    run the build a second time under the very interpreter that has no sqlalchemy, which
    reproduced the ModuleNotFoundError this was written to prevent.
    """
    import subprocess

    missing = _missing_packages()
    if not missing:
        return None          # this interpreter can build; carry on

    # --python X is an explicit instruction: run under that interpreter and stop guessing.
    if args.python:
        chosen = Path(args.python).expanduser()
        if not chosen.exists():
            print(f"[خطا] پایتون درخواستی پیدا نشد: {chosen}")
            return 4
        forwarded = [a for i, a in enumerate(_ORIG_ARGV)
                     if not (a == "--python" or a.startswith("--python=")
                             or (i and _ORIG_ARGV[i - 1] == "--python"))]
        # Compare the paths as given, NOT resolved: a venv's python is a symlink to its base
        # interpreter, so .resolve() made "--python tools/.venv/..." look identical to the
        # interpreter we are already running and the flag was silently ignored.
        if os.path.abspath(sys.executable) == os.path.abspath(str(chosen)):
            pass  # already there; fall through to the bootstrap logic below
        else:
            print(f" اجرای ساخت با پایتون انتخابی شما: {chosen}")
            return _reexec(chosen, forwarded)

    if args.no_bootstrap:
        # Second pass, or the user asked us not to install anything: report, don't crash.
        _manual_help(missing)
        return 4

    venv_dir = HERE / ".venv"
    vpy = _venv_python(venv_dir)

    print(" کتابخانه‌های لازم در پایتون فعلی نصب نیستند:")
    print("   " + ", ".join(missing))
    print()
    print(f" در حال ساخت محیط اختصاصی در: {venv_dir}")
    print(" (فقط بار اول؛ دانلود کتابخانه‌ها بسته به سرعت اینترنت ۲ تا ۱۰ دقیقه طول می‌کشد.)")
    print()

    if not vpy.exists():
        rc = subprocess.run([sys.executable, "-m", "venv", str(venv_dir)]).returncode
        if rc != 0 or not vpy.exists():
            print(f"\n[خطا] ساخت venv ناموفق بود (کد {rc}).")
            _manual_help(missing)
            return 4

    def _probe() -> bool:
        code = "import " + ",".join(PROBE_PACKAGES)
        return subprocess.run([str(vpy), "-c", code],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0

    if _probe() and not args.force_deps:
        print(" محیط قبلاً آماده است — نصب رد شد.")
    else:
        if not REQUIREMENTS.exists():
            print(f"\n[خطا] فایل {REQUIREMENTS} پیدا نشد.")
            _manual_help(missing)
            return 4
        pip = [str(vpy), "-m", "pip", "--disable-pip-version-check"]
        if subprocess.run([*pip, "--version"], stdout=subprocess.DEVNULL,
                          stderr=subprocess.DEVNULL).returncode != 0:
            _show([str(vpy), "-m", "ensurepip", "--upgrade"])
            subprocess.run([str(vpy), "-m", "ensurepip", "--upgrade"])
        cmd = [*pip, "install", "--upgrade", "pip"]
        _show(cmd)
        subprocess.run(cmd)
        cmd = [*pip, "install", "-r", str(REQUIREMENTS)]
        _show(cmd)
        rc = subprocess.run(cmd).returncode
        if rc != 0:
            print(f"\n[خطا] نصب کتابخانه‌ها ناموفق بود (کد {rc}).")
            _manual_help(missing)
            return 4
        if not _probe():
            print("\n[خطا] کتابخانه‌ها نصب شدند اما هنوز import نمی‌شوند.")
            _manual_help(missing)
            return 4

    print()
    print(" نصب کامل شد. حالا ساخت اصلی اجرا می‌شود…")
    forwarded = [a for i, a in enumerate(_ORIG_ARGV)
                 if not (a == "--python" or a.startswith("--python=")
                         or (i and _ORIG_ARGV[i - 1] == "--python"))]
    return _reexec(vpy, forwarded)


# --------------------------------------------------------------------------- main
def main() -> int:
    ap = argparse.ArgumentParser(description="Build a heavy one-year stress backup for the supermarket system.")
    ap.add_argument("--out", default=str(ROOT / "stress_store.db.gz"), help="output file (.gz recommended)")
    ap.add_argument("--days", type=int, default=365, help="days of history (default 365)")
    ap.add_argument("--per-day", type=float, default=1100.0,
                    help="average invoices per day (default 1100; validate actual count afterwards)")
    ap.add_argument("--seed", type=int, default=1404, help="RNG seed; same seed = same store")
    ap.add_argument("--no-compress", action="store_true", help="write raw SQLite instead of gzip")
    ap.add_argument("--lite-catalog", action="store_true",
                    help="skip the 13,570-SKU catalogue and build only the ~120 curated products")
    ap.add_argument("--smoke", action="store_true",
                    help="30 days instead of a year — proves the pipeline in minutes, not hours")
    ap.add_argument("--python", metavar="EXE",
                    help="run the build with this Python instead of the one found on PATH")
    ap.add_argument("--no-bootstrap", action="store_true",
                    help="do not create tools/.venv or install anything; just report what is missing")
    ap.add_argument("--force-deps", action="store_true",
                    help="reinstall the requirements into tools/.venv even if they already import")
    ap.add_argument("--minimum-invoices", type=int, default=None,
                    help="fail validation if the actual invoice count is below this target")
    ap.add_argument("--work-dir", help="persistent simulation workspace; defaults to OUTPUT.work")
    ap.add_argument("--resume", action="store_true", help="continue the last completed day with the original parameters")
    ap.add_argument("--pause-after-days", type=int, help="save and stop after this many additional days (exit 75)")
    args = ap.parse_args()
    import math
    if not 1 <= args.days <= 3660 or not math.isfinite(args.per_day) or not 1 <= args.per_day <= 10000:
        ap.error("days must be 1..3660 and per-day 1..10000")
    if args.minimum_invoices is not None and args.minimum_invoices < 1:
        ap.error("minimum-invoices must be positive")

    if args.pause_after_days is not None and args.pause_after_days < 1:
        ap.error("pause-after-days must be positive")

    # Before anything else: a missing sqlalchemy must produce instructions, not a traceback.
    # `is not None`, not truthiness: 0 here means "a bootstrapped child already built the
    # file", and the parent must not then try to build it again.
    rc = ensure_dependencies(args)
    if rc is not None:
        return rc

    days = 30 if args.smoke else args.days
    if args.minimum_invoices is None and args.per_day >= 1000 and not args.lite_catalog:
        args.minimum_invoices = days * 1000
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

    from app.services.simulation_checkpoint import SimulationPaused
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
            progress=on_progress, work_dir=args.work_dir or str(out) + ".work",
            resume=args.resume, pause_after_days=args.pause_after_days)
    except SimulationPaused as exc:
        print(f"\n[PAUSED] {exc}\nبرای ادامه همان فرمان را با --resume اجرا کنید؛ بکاپ نهایی هنوز آماده نیست.")
        return 75
    except Exception as exc:
        bar.draw(1.0, "ناموفق")
        print(f"\n[خطا] ساخت ناموفق بود: {exc}")
        return 2

    # compression is the one step the child cannot report on; show it as the last few percent.
    bar.draw(1.0, "اعتبارسنجی")
    raw_bytes = summary.get("bytes", 0)
    v = validate(out)
    raw = v.get("uncompressed_bytes", 0)
    import json
    report = {"simulation_only": True, "summary": summary, "validation": v,
              "elapsed_seconds": round(time.time() - t0, 3),
              "requested_days": days, "requested_invoices_per_day": args.per_day,
              "model_effect_is_causal_evidence": False}
    report_path = out.with_name(out.name + ".report.json")
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    actual = v.get("counts", {}).get("invoices", 0)
    if args.minimum_invoices is not None and actual < args.minimum_invoices:
        print(f"[FAILED] actual invoices {actual:,} < required {args.minimum_invoices:,}; report: {report_path}")
        return 3
    if not v.get("economic", {}).get("ok"):
        print(f"[FAILED] economic validation failed; report: {report_path}")
        return 3
    if v.get("foreign_key_errors"):
        print(f"[FAILED] foreign-key violations detected; report: {report_path}")
        return 3
    if (summary.get("insights") or {}).get("errors"):
        print(f"[FAILED] model errors were detected; report: {report_path}")
        return 3
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
