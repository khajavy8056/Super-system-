#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v4.8.0 — one-to-two-year store simulator (CLI, runs anywhere — Google Colab ready).

Builds a COMPLETE year of a big supermarket through the project's REAL service
layer (POS checkout, receiving, accounting, cash sessions/shifts, stocktakes,
expenses, salaries, cheques, customers, the store-intelligence engine with
accepted suggestions), then writes a backup file that restores on BOTH Windows
(Settings ← Backup ← بازیابی از فایل) and Android (تنظیمات ← پشتیبان ← انتخاب
فایل — the phone imports a Windows backup natively).

What the simulated year now includes (v4.8.0): the daily loop plays the real
store-intelligence worker, so **dated markdown steps land on their day**, the
periodic manager review accepts the **expiry cards** (discount ladder for the
living batch, «ثبت ضایعات» for the expired one), and the finished year carries a
**verification report** (`health_scan` + `execution_report`) proving the executed
actions still hold in the data.

Usage:
    python tools/simulate_year.py                       # full defaults: 365 days, ~100 sales/day, full default catalogue
    python tools/simulate_year.py --days 730            # TWO years (~73 000 invoices) — the Colab notebook's two-year switch
    python tools/simulate_year.py --days 90 --per-day 100 --seed 7 --out my_store.db.gz
    python tools/simulate_year.py --resume-dir /content/sim_work   # resumable build (pause/restart safe)

The progress is a live tqdm bar (0–100 %) fed by the build's own progress
protocol; every phase is printed in Persian so the log reads like a story.
Two years is roughly twice the build time and about twice the backup size; a
Colab run of 730 days at ~100 invoices/day is the honest upper bound.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"


def _bar(total_days: int = 365):
    label = f"شبیه‌سازی {total_days} روزه" if total_days != 365 else "شبیه‌سازی یک‌ساله"
    try:
        from tqdm.auto import tqdm        # Colab/Jupyter render it natively
        return tqdm(total=100, desc=label, unit="%", bar_format="{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}]")
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
    ap = argparse.ArgumentParser(description="یک تا دو سال کامل فروشگاه را شبیه‌سازی و فایل پشتیبان سازندهٔ برنامه می‌سازد")
    ap.add_argument("--days", type=int, default=365,
                    help="طول شبیه‌سازی به روز — ۳۶۵ = یک سال (پیش‌فرض)، ۷۳۰ = دو سال")
    ap.add_argument("--per-day", type=float, default=100.0, help="میانگین فاکتور در روز (پیش‌فرض ۱۰۰ — فروشگاه بزرگ)")
    ap.add_argument("--seed", type=int, default=1404, help="بذر تصادفی (تکرارپذیری)")
    ap.add_argument("--out", default=None, help="مسیر فایل خروجی (پیش‌فرض supermarket_sim_<days>d_<seed>.db.gz)")
    ap.add_argument("--no-compress", action="store_true", help="خروجی .db بدون فشرده‌سازی")
    ap.add_argument("--no-full-catalog", action="store_true",
                    help="فقط ~۱۲۰ کالای منتخب به‌جای کل بانک پیش‌فرض (سریع‌تر برای آزمون)")
    ap.add_argument("--resume-dir", default=None, help="پوشهٔ کار قابل‌ادامه (قطع شد؟ از همان روز ادامه می‌دهد)")
    ap.add_argument("--no-hr-shifts", action="store_true",
                    help="بدون شیفت‌بندی/حضور کارکنان (پیش‌فرض: ثبت می‌شود)")
    args = ap.parse_args(argv)

    if not BACKEND.exists():
        print(f"پوشهٔ backend کنار این اسکریپت پیدا نشد: {BACKEND}", file=sys.stderr)
        return 2
    sys.path.insert(0, str(BACKEND))

    out = Path(args.out) if args.out else ROOT / f"supermarket_sim_{args.days}d_{args.seed}.db.gz"
    if args.no_compress and str(out).endswith(".gz"):
        out = out.with_suffix("")

    from app.services.demo_store import generate_backup_file   # noqa: E402  (needs sys.path first)

    years = args.days / 365.0
    version = "?"
    try:
        import re
        version = re.search(r'__version__\s*=\s*"([^"]+)"',
                            (BACKEND / "app" / "__init__.py").read_text(encoding="utf-8")).group(1)
    except Exception:
        pass
    print("=" * 64)
    print(f"شبیه‌ساز فروشگاه — رسا سیستم {version}  ({args.days} روز ≈ {years:.2f} سال)")
    print(f"  {args.days} روز · ~{args.per_day:.0f} فاکتور در روز · بذر {args.seed}")
    print(f"  بانک کامل کالاها: {'خاموش' if args.no_full_catalog else 'روشن (۱۳٬۵۷۰ کالای پیش‌فرض)'}")
    print(f"  خروجی: {out}")
    print("=" * 64)

    bar = _bar(args.days)
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
        hr_shifts=not args.no_hr_shifts,
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
        ("تعریف شیفت کارکنان", f"{(summary.get('hr_shifts') or {}).get('definitions', 0):,}"),
        ("تخصیص شیفت روزانه", f"{(summary.get('hr_shifts') or {}).get('daily_assignments', 0):,}"),
        ("حضور/خروج ثبت‌شدهٔ کارکنان", f"{(summary.get('hr_shifts') or {}).get('attendance_records', 0):,}"),
        ("انبارگردانی‌های تأییدشده", f"{summary.get('stocktakes', 0):,}"),
        ("پیشنهادهای اجراشده (هوش فروشگاه)", f"{summary.get('accepted_insights', 0):,}"),
        ("پیشنهادهای سنجیده‌شده", f"{(ins or {}).get('measured', 0):,}"),
        ("پله‌های تخفیف اعمال‌شده روی تاریخ خودشان", f"{summary.get('markdown_steps', 0):,}"),
        ("کارت‌های انقضای اجراشده (تخفیف پله‌ای)", f"{summary.get('expiry_markdowns', 0):,}"),
        ("ثبت ضایعات کالای منقضی (اقدام واقعی)", f"{summary.get('expiry_waste_actions', 0):,}"),
        ("مرجوعی‌ها", f"{summary.get('returns', 0):,}"),
    ]
    for k, v in rows:
        print(f"  {k:<38} {v}")
    if summary.get("hr_shifts_error"):
        print(f"  {'هشدار':<38} شیفت‌بندی کارکنان ثبت نشد: {summary['hr_shifts_error'][:90]}")
        print(f"  {'':<38} فایل پشتیبان معتبر است اما گزارش شیفت خالی می‌ماند")
    size = out.stat().st_size if out.exists() else 0
    print(f"  {'حجم فایل پشتیبان':<38} {size / 1048576:.1f} مگابایت")
    print()
    # ---- v4.8.0: «سیستم بررسی فروشگاه» — آیا اقدام‌های اجراشده هنوز برقرارند؟ ----------
    verification = summary.get("verification") or {}
    counts = verification.get("counts") or {}
    lost = verification.get("lost") or []
    print("بررسی اجراها (آیا «اجرا» واقعاً انجام شده و اثرش مانده؟):")
    if counts:
        checked = verification.get("actions_checked")
        checked = sum(counts.values()) if checked is None else int(checked)
        print(f"  {'اقدام‌های بازبینی‌شده':<38} {checked:,}"
              f"   (از {int(verification.get('insights_checked', 0) or 0):,} پیشنهاد پذیرفته‌شده)")
        print(f"  {'وضعیت':<38} برقرار {counts.get('OK', 0):,} · از بین رفته {counts.get('LOST', 0):,} · "
              f"ناموفق {counts.get('FAILED', 0):,} · بدون بازبینی {counts.get('UNVERIFIED', 0):,}"
              + (f" · نامعلوم {counts['UNKNOWN']:,}" if counts.get("UNKNOWN") else ""))
        if not any(counts.values()):
            print(f"  {'یادداشت':<38} در این مدت هیچ پیشنهادی پذیرفته نشد")
    if lost:
        for x in lost[:5]:
            print(f"  {'اثر ازبین‌رفته':<38} {x.get('kind')} → {x.get('state')} — {str(x.get('detail'))[:60]}")
        if len(lost) > 5:
            print(f"  {'':<38} … و {len(lost) - 5:,} مورد دیگر (فهرست کامل در خلاصهٔ ماشین‌خوان)")
    print()

    # خلاصهٔ ماشین‌خوان کنار خروجی (نوت‌بوک/CI بدون پارس‌کردن لاگ می‌خواند)
    try:
        side = out.with_suffix(out.suffix + ".summary.json")
        side.write_text(json.dumps({**summary, "products_total": summary.get("products", 0) + summary.get("long_tail_products", 0)},
                                   ensure_ascii=False, default=str, indent=1), encoding="utf-8")
        print(f"خلاصهٔ ماشین‌خوان: {side}")
    except Exception as exc:                       # a sidecar is a convenience, never a requirement
        print(f"یادداشت: نوشتن خلاصهٔ ماشین‌خوان نشد ({exc!r})")
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
