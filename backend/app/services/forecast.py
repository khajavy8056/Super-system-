"""v3.1 — Forecasting, planning and self-calibration for the Store-Intelligence engine.

Three jobs, all on the local database, no network:

1. **Calibration (the model learns).** Every suggestion is created with an *expected* gain
   and — once executed — ends with a *measured* gain (difference-in-differences, see
   ``insights.measure``).  The ratio measured/expected per suggestion kind is tracked as an
   exponentially-weighted mean with dispersion.  New suggestions of that kind are then
   scaled by the learned ratio and carry a confidence band.  The more actions the shop
   executes, the tighter the band and the closer the prediction — the model gets more
   accurate with use, per shop, without any cloud.

2. **Profit forecast.** Daily net profit for the last 26 weeks is decomposed into a linear
   trend (least squares on weekly sums) × weekday seasonality index.  That gives a
   *baseline* path for the next N days.  The *plan* path adds the calibrated gains of the
   open suggestions (ramping up over the first week, as real actions do).

3. **Planning report.** Per open suggestion: calibrated monthly gain, low/high band,
   confidence label, 90-day cumulative; plus a kind breakdown and the accuracy history
   (predicted vs. measured) so the manager can see how well the engine has done so far.
"""
from __future__ import annotations

import json
import math
from collections import defaultdict
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import Insight, Invoice, InvoiceItem, SystemSetting
from .insights import KIND_LABELS, _f, _now

PAID = "PAID"
CAL_KEY = "insights.calibration"
RAMP_DAYS = 7          # actions do not bite on day 1: linear ramp-up
DECAY = 0.7            # EWMA weight of the previous estimate (0.7 → last ~3 results dominate)
# v3.8 — NO clamps. v3.1 clamped every measured/expected ratio into [0.15, 2.5],
# which silently rewrote every real loss (negative ratio) as a +15 % win and fed
# the lie back into predictions. Ratios are recorded raw; robustness comes from
# reporting dispersion honestly (sd, CI, pos/neg rates), not from hiding data.


# ----------------------------------------------------------------------------- calibration
def _load_cal(db: Session) -> dict:
    row = db.execute(select(SystemSetting).where(SystemSetting.key == CAL_KEY)).scalar_one_or_none()
    try:
        return json.loads(row.value) if row and row.value else {}
    except ValueError:
        return {}


def _save_cal(db: Session, cal: dict) -> None:
    row = db.execute(select(SystemSetting).where(SystemSetting.key == CAL_KEY)).scalar_one_or_none()
    val = json.dumps(cal, ensure_ascii=False)
    if row:
        row.value = val
    else:
        db.add(SystemSetting(key=CAL_KEY, value=val, description="v3.1 learned accuracy of the insight engine per kind"))


def learn(db: Session) -> dict:
    """Re-fit the per-kind calibration from every completed measurement.

    Deterministic (re-computed from scratch each time, chronological EWMA) so that a restore
    or a re-run yields the same numbers.  Returns the calibration table.

    v3.8 honesty contract: every completed measurement counts exactly as measured —
    Positive, Neutral and Negative. No clamps, no floors: a kind whose actions lost
    money shows a negative ratio and a low/negative confidence story, which is what
    the manager must see before accepting the next card of that kind.
    """
    rows = db.execute(select(Insight).where(Insight.status == "MEASURED", Insight.measured_gain.isnot(None))
                      .order_by(Insight.measured_at.asc(), Insight.id.asc())).scalars().all()
    cal: dict[str, dict] = {}
    for r in rows:
        exp = _f(r.expected_gain)
        ev = json.loads(r.evidence or "{}")
        raw = _f(ev.get("expected_gain_raw", exp))      # un-calibrated prediction at creation time
        if raw <= 0:
            continue
        measured = _f(r.measured_gain)
        ratio = measured / raw                           # raw, unclamped — see module note
        err = measured - raw                             # signed error in toman
        c = cal.setdefault(r.kind, {"ratio": 1.0, "n": 0, "var": 0.0, "abs_err": 0.0, "hits": 0,
                                    "n_positive": 0, "n_zero": 0, "n_negative": 0,
                                    "sum_err": 0.0, "sum_abs_err": 0.0})
        if c["n"] == 0:
            c["ratio"], c["var"] = ratio, 0.25
        else:
            d = ratio - c["ratio"]
            c["ratio"] = DECAY * c["ratio"] + (1 - DECAY) * ratio
            c["var"] = DECAY * c["var"] + (1 - DECAY) * d * d
        c["n"] += 1
        c["abs_err"] = DECAY * c["abs_err"] + (1 - DECAY) * abs(err) if c["n"] > 1 else abs(err)
        c["sum_err"] += err
        c["sum_abs_err"] += abs(err)
        if measured > 0:
            c["n_positive"] += 1
        elif measured < 0:
            c["n_negative"] += 1
        else:
            c["n_zero"] += 1
        if (measured > 0) == (raw > 0):
            c["hits"] += 1
    for c in cal.values():
        n = c["n"]
        sd = math.sqrt(max(0.0, c["var"]))
        c["ratio"] = round(c["ratio"], 3)
        c["sd"] = round(sd, 3)
        c["direction_accuracy"] = round(c["hits"] / n, 2) if n else None
        c["pos_rate"] = round(c["n_positive"] / n, 3) if n else None
        c["neg_rate"] = round(c["n_negative"] / n, 3) if n else None
        c["mean_error"] = round(c["sum_err"] / n) if n else None
        c["mae"] = round(c["sum_abs_err"] / n) if n else None
        # 95 % CI of the mean ratio (normal approx): the band predictions honestly live in
        half = round(1.96 * sd / math.sqrt(n), 3) if n else 0.0
        c["ratio_ci95"] = [round(c["ratio"] - half, 3), round(c["ratio"] + half, 3)]
        del c["var"]
        del c["sum_err"]
        del c["sum_abs_err"]
    _save_cal(db, cal)
    db.commit()
    return cal


def calibrate(db: Session, kind: str, raw_gain: float, cal: dict | None = None) -> dict:
    """Apply the learned ratio of *kind* to a raw prediction.

    Returns the flat keys the UI already reads (gain/low/high/confidence/n/ratio)
    plus the v3.8 split the honesty contract requires — ``economic_impact`` (money),
    ``evidence_strength`` (how much history backs it) and ``prediction_uncertainty``
    (how wide the truth could swing). Money, evidence and uncertainty are never
    mixed into one number again.
    """
    cal = _load_cal(db) if cal is None else cal
    c = cal.get(kind)
    if raw_gain <= 0:
        return {"gain": 0.0, "low": 0.0, "high": 0.0, "confidence": "n/a", "n": (c or {}).get("n", 0), "ratio": 1.0,
                "economic_impact": {"gain": 0.0, "low": 0.0, "high": 0.0, "unit": "toman_month"},
                "evidence_strength": {"n": (c or {}).get("n", 0), "verdict": "NO_PREDICTION"},
                "prediction_uncertainty": {"confidence": "n/a"}}
    if not c or not c.get("n"):
        # No history for this kind yet: keep the analyzer estimate but flag it as a first guess
        out = {"gain": raw_gain, "low": round(raw_gain * 0.4), "high": round(raw_gain * 1.4), "confidence": "low", "n": 0, "ratio": 1.0}
        out["economic_impact"] = {"gain": out["gain"], "low": out["low"], "high": out["high"], "unit": "toman_month"}
        out["evidence_strength"] = {"n": 0, "verdict": "FIRST_GUESS"}
        out["prediction_uncertainty"] = {"confidence": "low", "note": "no measured history for this kind"}
        return out
    n, ratio, sd = int(c["n"]), float(c["ratio"]), float(c.get("sd", 0.5))
    # 1-sigma band shrinks with more observations (standard error of the mean).
    # v3.8: the low edge is NOT floored at zero — a kind that lost money shows a
    # band reaching into the red, which is the entire point of the band.
    band = sd / math.sqrt(n) if n else sd
    lo, hi = ratio - band, ratio + band
    gain, low, high = round(raw_gain * ratio), round(raw_gain * lo), round(raw_gain * hi)
    # Confidence comes from real performance only: sample size, stability of the
    # ratio AND the share of past actions that actually made money.
    pos_rate = float(c.get("pos_rate", 0.0) or 0.0)
    if n >= 5 and band < 0.25 and pos_rate >= 0.7:
        conf = "high"
    elif n >= 3 and band < 0.6 and pos_rate >= 0.5:
        conf = "medium"
    else:
        conf = "low"
    return {"gain": gain, "low": low, "high": high, "confidence": conf, "n": n, "ratio": ratio,
            "economic_impact": {"gain": gain, "low": low, "high": high, "unit": "toman_month"},
            "evidence_strength": {"n": n, "n_positive": c.get("n_positive", 0), "n_zero": c.get("n_zero", 0),
                                  "n_negative": c.get("n_negative", 0), "pos_rate": pos_rate,
                                  "direction_accuracy": c.get("direction_accuracy"),
                                  "mae": c.get("mae"), "mean_error": c.get("mean_error")},
            "prediction_uncertainty": {"confidence": conf, "sd": round(sd, 3), "band": round(band, 3),
                                       "ratio_ci95": c.get("ratio_ci95")}}


# ----------------------------------------------------------------------------- time series
def _daily_profit(db: Session, days: int) -> list[tuple[datetime, float]]:
    since = _now() - timedelta(days=days)
    rows = db.execute(select(func.date(Invoice.created_at), func.coalesce(func.sum(InvoiceItem.profit), 0))
                      .join(Invoice, Invoice.id == InvoiceItem.invoice_id)
                      .where(Invoice.status == PAID, Invoice.created_at >= since)
                      .group_by(func.date(Invoice.created_at)).order_by(func.date(Invoice.created_at))).all()
    by = {str(d): _f(v) for d, v in rows}
    out = []
    d0 = (since + timedelta(days=1)).date()
    for i in range(days):
        d = d0 + timedelta(days=i)
        out.append((datetime(d.year, d.month, d.day), by.get(d.isoformat(), 0.0)))
    return out


def _fit(series: list[tuple[datetime, float]]) -> dict:
    """Weekly linear trend + weekday index. Robust to short/sparse history."""
    vals = [v for _, v in series]
    n = len(vals)
    if n < 14 or sum(1 for v in vals if v > 0) < 7:
        avg = (sum(vals) / n) if n else 0.0
        return {"level": avg, "slope_per_day": 0.0, "weekday": [1.0] * 7, "r2": 0.0, "weeks": n // 7}
    # weekly sums (drop a trailing partial week)
    weeks = [sum(vals[i:i + 7]) for i in range(0, n - n % 7, 7)]
    if len(weeks) >= 3:
        xs = list(range(len(weeks)))
        mx, my = sum(xs) / len(xs), sum(weeks) / len(weeks)
        sxx = sum((x - mx) ** 2 for x in xs) or 1.0
        slope_w = sum((x - mx) * (y - my) for x, y in zip(xs, weeks)) / sxx
        # damp the slope: never extrapolate more than ±1.5 %/week
        slope_w = max(-0.015 * my, min(0.015 * my, slope_w))
        ss_res = sum((y - (my + slope_w * (x - mx))) ** 2 for x, y in zip(xs, weeks))
        ss_tot = sum((y - my) ** 2 for y in weeks) or 1.0
        r2 = max(0.0, 1 - ss_res / ss_tot)
        level_w = my + slope_w * (len(weeks) - 1 - mx)     # fitted value of the last full week
    else:
        slope_w, level_w, r2 = 0.0, sum(weeks) / len(weeks), 0.0
    # weekday index from the last 8 weeks
    tail = series[-56:]
    by_wd = defaultdict(list)
    for d, v in tail:
        by_wd[d.weekday()].append(v)
    mean_all = sum(v for _, v in tail) / max(1, len(tail))
    idx = [(sum(by_wd[w]) / len(by_wd[w]) / mean_all) if by_wd.get(w) and mean_all > 0 else 1.0 for w in range(7)]
    s = sum(idx) / 7 or 1.0
    idx = [i / s for i in idx]
    return {"level": level_w / 7, "slope_per_day": slope_w / 49, "weekday": idx, "r2": round(r2, 3), "weeks": len(weeks)}


def _open_rows(db: Session) -> list[Insight]:
    return db.execute(select(Insight).where(Insight.status == "NEW").order_by(Insight.priority, Insight.expected_gain.desc())).scalars().all()


def plan(db: Session, horizon: int = 90, history_days: int = 182) -> dict:
    """The planning report + chart series consumed by both the PC and the phone UI."""
    cal = _load_cal(db)
    hist = _daily_profit(db, history_days)
    fit = _fit(hist)
    today = _now().replace(hour=0, minute=0, second=0, microsecond=0)
    open_rows = _open_rows(db)
    items = []
    for r in open_rows:
        ev = json.loads(r.evidence or "{}")
        raw = _f(ev.get("expected_gain_raw", r.expected_gain))
        c = calibrate(db, r.kind, raw, cal)
        items.append({"id": r.id, "kind": r.kind, "label": KIND_LABELS.get(r.kind, r.kind), "title": r.title, "priority": r.priority,
                      "raw_gain": round(raw), "gain_month": round(c["gain"]), "low_month": round(c["low"]), "high_month": round(c["high"]),
                      "confidence": c["confidence"], "history_n": c["n"], "gain_horizon": round(c["gain"] / 30 * max(0, horizon - RAMP_DAYS / 2))})
    # daily series: history (weekly buckets for the chart) + forecast paths
    hist_weeks = []
    vals = [v for _, v in hist]
    for i in range(0, len(vals) - len(vals) % 7, 7):
        hist_weeks.append({"week_start": hist[i][0].date().isoformat(), "profit": round(sum(vals[i:i + 7]))})
    base_path, plan_path, low_path, high_path = [], [], [], []
    cum_b = cum_p = cum_l = cum_h = 0.0
    plan_day = sum(x["gain_month"] for x in items) / 30
    low_day = sum(x["low_month"] for x in items) / 30
    high_day = sum(x["high_month"] for x in items) / 30
    for d in range(1, horizon + 1):
        day = today + timedelta(days=d)
        base = max(0.0, (fit["level"] + fit["slope_per_day"] * d) * fit["weekday"][day.weekday()])
        ramp = min(1.0, d / RAMP_DAYS)
        cum_b += base
        cum_p += base + plan_day * ramp
        cum_l += base + low_day * ramp
        cum_h += base + high_day * ramp
        if d % 7 == 0 or d == horizon:
            base_path.append({"day": day.date().isoformat(), "cum_baseline": round(cum_b), "cum_plan": round(cum_p), "cum_low": round(cum_l), "cum_high": round(cum_h),
                              "week_baseline": round(base * 7), "week_plan": round((base + plan_day * ramp) * 7)})
    by_kind: dict[str, dict] = {}
    for x in items:
        k = by_kind.setdefault(x["kind"], {"kind": x["kind"], "label": x["label"], "count": 0, "gain_month": 0, "low_month": 0, "high_month": 0})
        k["count"] += 1
        k["gain_month"] += x["gain_month"]
        k["low_month"] += x["low_month"]
        k["high_month"] += x["high_month"]
    month_base = round(fit["level"] * 30)
    plan_month = round(plan_day * 30)
    # accuracy history — predicted vs measured (completed ones)
    acc = []
    for r in db.execute(select(Insight).where(Insight.status == "MEASURED", Insight.measured_gain.isnot(None)).order_by(Insight.measured_at.desc()).limit(40)).scalars():
        ev = json.loads(r.evidence or "{}")
        acc.append({"id": r.id, "kind": r.kind, "label": KIND_LABELS.get(r.kind, r.kind), "title": r.title,
                    "predicted": round(_f(ev.get("expected_gain_raw", r.expected_gain))), "calibrated": round(_f(r.expected_gain)),
                    "measured": round(_f(r.measured_gain)), "measured_at": r.measured_at.isoformat() if r.measured_at else None})
    hits = sum(1 for a in acc if (a["measured"] > 0) == (a["predicted"] > 0))
    mape = [abs(a["measured"] - a["calibrated"]) / abs(a["calibrated"]) for a in acc if a["calibrated"]]
    return {
        "generated_at": _now().isoformat(), "horizon_days": horizon,
        "model": {"weeks_of_history": fit["weeks"], "trend_pct_per_week": round(fit["slope_per_day"] * 7 / fit["level"] * 100, 2) if fit["level"] else 0,
                  "fit_r2": fit["r2"], "weekday_index": [round(i, 2) for i in fit["weekday"]],
                  "calibration": [{"kind": k, "label": KIND_LABELS.get(k, k), **v} for k, v in sorted(cal.items())],
                  "measured_count": len(acc), "direction_accuracy": round(hits / len(acc), 2) if acc else None,
                  "mean_abs_pct_error": round(sum(mape) / len(mape) * 100) if mape else None},
        "baseline": {"profit_per_day": round(fit["level"]), "profit_month": month_base, "profit_horizon": round(cum_b)},
        "plan": {"open": len(items), "gain_month": plan_month, "low_month": round(low_day * 30), "high_month": round(high_day * 30),
                 "gain_horizon": round(cum_p - cum_b), "profit_month": month_base + plan_month, "profit_horizon": round(cum_p),
                 "growth_pct": round(plan_month / month_base * 100, 1) if month_base else None},
        "items": items, "by_kind": sorted(by_kind.values(), key=lambda k: -k["gain_month"]),
        "history_weeks": hist_weeks, "forecast": base_path, "accuracy": acc,
    }


def predict_for(db: Session, insight: Insight) -> dict:
    """Detail-card block for one suggestion: what happens to profit if it is executed."""
    cal = _load_cal(db)
    ev = json.loads(insight.evidence or "{}")
    raw = _f(ev.get("expected_gain_raw", insight.expected_gain))
    c = calibrate(db, insight.kind, raw, cal)
    hist = _daily_profit(db, 91)
    fit = _fit(hist)
    month_base = fit["level"] * 30
    path = []
    cum = 0.0
    for d in range(1, 91):
        cum += c["gain"] / 30 * min(1.0, d / RAMP_DAYS)
        if d % 15 == 0:
            path.append({"day": d, "cum_gain": round(cum), "cum_low": round(cum * (c["low"] / c["gain"]) if c["gain"] else 0), "cum_high": round(cum * (c["high"] / c["gain"]) if c["gain"] else 0)})
    return {"raw_gain_month": round(raw), "gain_month": round(c["gain"]), "low_month": round(c["low"]), "high_month": round(c["high"]),
            "confidence": c["confidence"], "history_n": c["n"], "ratio": c["ratio"],
            "store_profit_month": round(month_base), "growth_pct": round(c["gain"] / month_base * 100, 1) if month_base else None,
            "gain_90d": round(cum), "path": path}
