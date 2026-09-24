#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v4.7.0 — one-year store simulator (CLI, runs anywhere — Google Colab ready).

Builds a COMPLETE year of a big supermarket through the project's REAL service
layer (POS checkout, receiving, accounting, cash sessions/shifts, stocktakes,
expenses, salaries, cheques, customers, the store-intelligence engine with
accepted suggestions), then writes a backup file that restores on BOTH Windows
(Settings ← Backup ← بازیابی از فایل) and Android (تنظیمات ← پشتیبان ← انتخاب
فایل — the phone imports a Windows backup natively).

Usage:
    python tools/simulate_year.py                       # full defaults: 365 days, ~100 sales/day, full default catalogue
    python tools/simulate_year.py --days 90 --per-day 100 --seed 7 --out my_store.db.gz
    python tools/simulate_year.py --resume-dir /content/sim_work   # resumable build (pause/restart safe)

The progress is a live tqdm bar (0–100 %) fed by the build's own progress
protocol; every phase is printed in Persian so the log reads like a story.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"


def _bar():
    try:
        from tqdm.auto import tqdm        # Colab/Jupyter render it natively
        return tqdm(total=100, desc="شبیه‌سازی سال", unit="%", bar_format="{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}]")
    except Exception:                      # plain terminal without tqdm
        class _Plain:
            def __init__(self): self.last = -1

            def update(self, pct):
                p = int(pct)
                if p != self.last:
                    self.last = p
                    print(f"  پیشرفت: {p}٪", flush=True)

            def close(self): pass

            def set_description(self, *a): pass
        return _Plain()


_PHASES = {
    "days": "روزهای فروش (فروش/دریافت/هزینه/چک/شیفت/انبارگردانی)",
    "snapshot": "گرفتن نسخهٔ یکپارچه از پایگاه داده",
    "compress": "فشرده‌سازی فایل پشتیبان",
}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="یک سال کامل فروشگاه را شبیه‌سازی و فایل پشتیبان سازندهٔ برنامه می‌سازد")
    ap.add_argument("--days", type=int, default=365, help="طول شبیه‌سازی به روز (پیش‌فرض ۳۶۵)")
    ap.add_argument("--per-day", type=float, default=100.0, help="میانگین فاکتور در روز (پیش‌فرض ۱۰۰ — فروشگاه بزرگ)")
    ap.add_argument("--seed", type=int, default=1404, help="بذر تصادفی (تکرارپذیری)")
    ap.add_argument("--out", default=None, help="مسیر فایل خروجی (پیش‌فرض supermarket_sim_<days>d_<seed>.db.gz)")
    ap.add_argument("--no-compress", action="store_true", help="خروجی .db بدون فشرده‌سازی")
    ap.add_argument("--no-full-catalog", action="store_true",
                    help="فقط ~۱۲۰ کالای منتخب به‌جای کل بانک پیش‌فرض (سریع‌تر برای آزمون)")
    ap.add_argument("--resume-dir", default=None, help="پوشهٔ کار قابل-from-ادامه (قطع شد؟ از همان روز ادامه می‌دهد)")
    args = ap.parse_args(argv)

    if not BACKEND.exists():
        print(f"پوشهٔ backend کنار این اسکریپت پیدا نشد: {BACKEND}", file=sys.stderr)
        return 2
    sys.path.insert(0, str(BACKEND))

    out = Path(args.out) if args.out else ROOT / f"supermarket_sim_{args.days}d_{args.seed}.db.gz"
    if args.no_compress and str(out).endswith(".gz"):
        out = out.with_suffix("")

    from app.services.demo_store import generate_backup_file   # noqa: E402  (needs sys.path first)

    print("=" * 64)
    print("شبیه‌ساز یک‌سالهٔ فروشگاه — سوپری‌من")
    print(f"  {args.days} روز · ~{args.per_day:.0f} فاکتور در روز · بذر {args.seed}")
    print(f"  بانک کامل کالاها: {'خاموش' if args.no_full_catalog else 'روشن (۱۳٬۵۷۰ کالای پیش‌فرض)'}")
    print(f"  خروجی: {out}")
    print("=" * 64)

    bar = _bar()
    events = {"phase": ""}

    def on_progress(pct: float) -> None:
        # absolute percentage → incremental tqdm update
        try:
            delta = pct - main._last
            main._last = pct
            bar.update(max(0.0, delta))
        except Exception:
            pass

    def on_event(ev: dict) -> None:
        ph = ev.get("phase", "")
        if ph and ph != events["phase"]:
            events["phase"] = ph
            try:
                bar.set_description(_PHASES.get(ph, ph))
            except Exception:
                pass
        if ph == "days":
            done, total = ev.get("done", 0), ev.get("total", 0)
            if total and done % max(1, total // 10) == 0:
                print(f"  روز {done}/{total} — {ev.get('invoices', 0):,} فاکتور ثبت شد", flush=True)

    main._last = 0.0
    summary = generate_backup_file(
        out, days=args.days, seed=args.seed, invoices_per_day=args.per_day,
        compress=not args.no_compress, full_catalog=not args.no_full_catalog,
        progress=on_progress, event_callback=on_event,
        work_dir=args.resume_dir, resume=bool(args.resume_dir),
    )
    bar.close()

    print()
    print("=" * 64)
    print("شبیه‌سازی کامل شد ✓  خلاصهٔ فروشگاه:")
    ins = summary.get("insights") or {}
    rows = [
        ("بازهٔ شبیه‌سازی", f"{summary.get('start_date', '?')} تا {summary.get('end_date', '?')}"),
        ("فاکتورها", f"{summary.get('invoices', 0):,}"),
        ("خطوط فروش", f"{summary.get('lines', 0):,}"),
        ("گردش فروش (تومان)", f"{summary.get('sales', 0):,.0f}"),
        ("مشتریان", f"{summary.get('customers', 0):,}"),
        ("کالاها (منتخب + بانک کامل)", f"{summary.get('products', 0) + summary.get('long_tail_products', 0):,}"),
        ("تأمین‌کنندگان", f"{summary.get('suppliers', 0):,}"),
        ("شیفت‌های صندوق (جمع‌بندی هفتگی)", f"{summary.get('cash_sessions', 0):,}"),
        ("انبارگردانی‌های تأییدشده", f"{summary.get('stocktakes', 0):,}"),
        ("پیشنهادهای اجراشده (هوش فروشگاه)", f"{summary.get('accepted_insights', 0):,}"),
        ("پیشنهادهای سنجیده‌شده", f"{(ins or {}).get('measured', 0):,}"),
        ("مرجوعی‌ها", f"{summary.get('returns', 0):,}"),
    ]
    for k, v in rows:
        print(f"  {k:<38} {v}")
    size = out.stat().st_size if out.exists() else 0
    print(f"  {'حجم فایل پشتیبان':<38} {size / 1048576:.1f} مگابایت")
    print()
    print("فایل پشتیبان آماده است:")
    print(f"  {out}")
    print("ویندوز: تنظیمات ← پشتیبان‌گیری ← «بازیابی از فایل…»")
    print("اندروید: تنظیمات ← پشتیبان ← انتخاب همین فایل (ایمپورت نسخهٔ ویندوز)")
    print("=" * 64)
    # machine-readable marker for pipelines/notebooks
    print("__SIM_DONE__ " + json.dumps({"file": str(out), "bytes": size}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
