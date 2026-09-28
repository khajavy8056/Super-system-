"""v4.8.0 — «تایم‌لاین انقضا»: برنامهٔ فروش بچ‌های نزدیک انقضا، با تاریخ واقعی هر پله.

**گزارش مالک (round-16، عیناً):**
«وقتی محصول صفر روز مانده بود پیشنهاد می‌داد، عملاً فاسد شده؛ باید چند روز
قبلش، یک هفته قبلش پیشنهاد بدهد تا بشود کاری کرد.»

**ریشهٔ باگ:** تحلیل‌گر قدیمی «فروش می‌رود یا نه» را با یک سرعت فروشِ **خوش‌بینانه**
(تنها میانگین ۲۸ روز) و **بدون حاشیهٔ اطمینان** می‌سنجید
(``will_sell >= qty * 0.9 → continue``). یک هفتهٔ جشنواره یا تبلیغ، میانگین را
بالا می‌برد؛ پس پیشنهاد دقیقاً همان روزهایی که هنوز وقتِ اقدام بود ساکت می‌ماند و
فقط وقتی ظاهر می‌شد که روزهای باقی‌مانده به‌قدر کم شده بود که از سرعت متورم‌شده
جلو بزند — یعنی روی آخرین روز (همان چیزی که مالک دید).

**اصلاح، با سه قاعدهٔ صادقانه:**
  ۱. **سرعت محافظه‌کارانه** — برنامه با *کندترین* سرعت اخیر ساخته می‌شود
     (کمینهٔ نرخ ۷/۲۸/۹۰ روز). برنامه باید هفته‌های آرام را دوام بیاورد، نه
     بهترین هفته را.
  ۲. **حاشیهٔ اطمینان** — موجودی باید «واضحاً» زیر فروشِ پیش‌بینی‌شده باشد
     (۱۵٪ بافر)، نه فقط برابر آن.
  ۳. **تایم‌لاین واقعی** — هر پلهٔ تخفیف تاریخ شمسی و میلادی خودش را دارد و
     برنامه طوری چیده می‌شود که **آخرین پله دست‌کم ۲ روز فرصت فروش** پیش از
     تاریخ انقضا داشته باشد (کاربر گفت: «چند روز قبلش، یک هفته قبلش»).

خروجی این ماژول کاملاً قطعی است: نه مدل، نه شبکه، نه حدس. هر عدد از همین
داده‌های فروشگاه می‌آید و در «شواهد» پیشنهاد قابل بازبینی است.
"""
from __future__ import annotations

from datetime import date as _date
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from .timeservice import to_jalali

#: بیش از این تعداد روز تا انقضا، اصلاً پیشنهادی ساخته نمی‌شود (سر و صدای بی‌فایده).
WINDOW_DAYS = 45
#: پیشنهاد باید حداکثر تا این تعداد روز پیش از انقضا داده شود تا «وقت اقدام» بماند.
DEFAULT_LEAD_DAYS = 21
#: موجودی باید دست‌کم این‌قدر *زیر* فروش پیش‌بینی‌شده باشد تا بگوییم «فروش می‌رود».
SAFETY_BUFFER = 1.15
#: دست‌کم فرصت فروش پس از اعمال آخرین پله (روز).
MIN_FINAL_RUNWAY_DAYS = 2
#: کف و سقف تخفیف (٪) — سقف در محاسبه هرگز از قیمت خرید پایین‌تر نمی‌رود.
MIN_STEP_PERCENT = 5
MAX_DISCOUNT_PERCENT = 60

_PERSIAN_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")


def jdate(d: _date | None) -> str:
    """۱۴۰۵/۰۷/۰۵ — تاریخ شمسی برای متن‌ها و تایم‌لاین (بدون وابستگی به UI)."""
    if d is None:
        return ""
    jy, jm, jd = to_jalali(datetime(d.year, d.month, d.day))
    return f"{jy:04d}/{jm:02d}/{jd:02d}".translate(_PERSIAN_DIGITS)


def settings(db: Session | None) -> dict:
    """پارامترهای تنظیم‌پذیر فروشگاه (با پیش‌فرض‌های امن).

    * ``insights.expiry_lead_days`` — چند روز پیش از انقضا، توصیه «باید کم شود».
    * ``insights.expiry_safety``    — ضریب حاشیهٔ اطمینان (۱.۱۵ = ۱۵٪ بافر).
    * ``insights.pos_expiry_days``  — افق «نزدیک انقضا» در پیشنهاد پای صندوق.
    """
    out = {"lead_days": DEFAULT_LEAD_DAYS, "safety": SAFETY_BUFFER, "pos_days": 30}
    if db is None:
        return out
    from ..models import SystemSetting
    from sqlalchemy import select

    rows = {r.key: r.value for r in db.execute(select(SystemSetting).where(
        SystemSetting.key.in_(["insights.expiry_lead_days", "insights.expiry_safety", "insights.pos_expiry_days"]))).scalars()}
    try:
        out["lead_days"] = max(3, min(WINDOW_DAYS, int(float(rows.get("insights.expiry_lead_days", out["lead_days"])))))
    except (TypeError, ValueError):
        pass
    try:
        out["safety"] = max(1.0, min(3.0, float(rows.get("insights.expiry_safety", out["safety"]))))
    except (TypeError, ValueError):
        pass
    try:
        out["pos_days"] = max(1, min(90, int(float(rows.get("insights.pos_expiry_days", out["pos_days"])))))
    except (TypeError, ValueError):
        pass
    return out


def conservative_velocity(ctx, product_id: int) -> float:
    """کندترین سرعت فروش اخیر (کمینهٔ نرخ ۷/۲۸/۹۰ روز).

    چرا کمینه؟ چون تصمیم «تخفیف لازم است یا نه» باید بر پایهٔ بدترین حالتِ
    گذشته گرفته شود. اگر در هفتهٔ آرام هم کالا فروش می‌رود، نیازی به تخفیف نیست؛
    اما تخفیفی که بر پایهٔ هفتهٔ شلوغ حساب شود، همان باگ قدیمی است.
    """
    from .insights import _daily_velocity

    windows = [7, 28]
    if getattr(ctx, "days", 90) >= 90:
        windows.append(90)
    rates = [max(0.0, _daily_velocity(ctx, product_id, d)) for d in windows]
    return min(rates) if rates else 0.0


def _steps_for(days_left: int, buy: float, sell: float) -> list[int]:
    """پله‌های تخفیف: تعداد پله‌ها به «فرصت باقی‌مانده» بستگی دارد، نه به سلیقه.

    * ۰ تا ۲ روز مانده → یک پله (بیشترین تخفیف، فوری).
    * ۳ تا ۶ روز    → دو پله.
    * بیش از ۶ روز  → سه پله.
    """
    if sell <= 0:
        return []
    ceiling = min(MAX_DISCOUNT_PERCENT, max(0, int((1 - (buy * 1.01) / sell) * 100)))
    if ceiling < MIN_STEP_PERCENT:
        return []          # حتی با بیشترین تخفیف هم زیر قیمت خرید می‌رود → تخفیف جواب نیست
    if days_left >= 7:
        raw = [max(MIN_STEP_PERCENT, ceiling // 3), max(MIN_STEP_PERCENT + 5, (ceiling * 2) // 3), ceiling]
    elif days_left >= 3:
        raw = [max(MIN_STEP_PERCENT, ceiling // 2), ceiling]
    else:
        raw = [ceiling]
    out: list[int] = []
    for p in raw:                      # حذف پله‌های تکراری/نزولی
        p = max(MIN_STEP_PERCENT, min(MAX_DISCOUNT_PERCENT, int(p)))
        if not out or p > out[-1]:
            out.append(p)
    return out


def _schedule(today: _date, days_left: int, steps: list[int], sell: float) -> list[dict]:
    """هر پله را روی یک تاریخ می‌نشاند؛ آخرین پله دست‌کم ۲ روز پیش از انقضا."""
    n = len(steps)
    if n == 0:
        return []
    span = max(0, days_left - MIN_FINAL_RUNWAY_DAYS)   # روزهای قابل استفاده برای پخش پله‌ها
    out = []
    for i, percent in enumerate(steps):
        offset = 0 if i == 0 else min(max(1, round(i * span / n)), max(1, days_left))
        d = today + timedelta(days=offset)
        price = None
        if sell > 0:
            price = round(sell * (1 - percent / 100) / 100) * 100
        out.append({"step": i + 1, "from_day": offset, "percent": percent, "date": d.isoformat(),
                    "jdate": jdate(d), "suggested_price": price})
    return out


def build_plan(*, today: _date, expiry: _date | None, qty: float, velocity: float,
               buy: float, sell: float, lead_days: int = DEFAULT_LEAD_DAYS,
               safety: float = SAFETY_BUFFER, window: int = WINDOW_DAYS) -> dict | None:
    """تصمیم کامل برای یک بچ — بدون دیتابیس (خالص و قابل تست).

    ``None`` یعنی «کاری لازم نیست»: یا تاریخ ندارد، یا خیلی دور است، یا موجودی
    به‌طور واضح پیش از انقضا فروش می‌رود. هر عدد دیگر یعنی «اکنون اقدام کن» —
    و دلیلش در همان دیکشنری است.
    """
    if expiry is None or qty <= 0:
        return None
    days_left = (expiry - today).days
    if days_left > window:
        return None

    base = {"days_left": days_left, "qty": round(float(qty), 3), "velocity_per_day": round(float(velocity), 4),
            "sell_by": expiry.isoformat(), "sell_by_jdate": jdate(expiry), "lead_days": lead_days}

    # ---- کالای تاریخ‌گذشته: دیگر تخفیف معنا ندارد؛ فقط صداقت و ثبت ضایعات --------
    if days_left < 0:
        at_risk = float(qty) * float(buy)
        if at_risk < 50_000:
            return None
        base.update({"mode": "waste", "at_risk": round(at_risk), "surplus": round(float(qty), 3),
                     "will_sell": 0.0, "timeline": [
                         {"step": 1, "kind": "expired", "date": today.isoformat(), "jdate": jdate(today),
                          "label": "از قفسه برداشته شود و ضایعات ثبت گردد"}]})
        return base

    will_sell = float(velocity) * days_left
    safe = will_sell >= float(qty) * safety
    base.update({"will_sell": round(will_sell, 3), "safe": bool(safe)})
    if safe:
        return None

    surplus = max(0.0, float(qty) - will_sell)
    at_risk = surplus * float(buy)
    if at_risk < 50_000:
        return None                        # ریسک ناچیز: با سر و صدا وقت مدیر را نگیر

    steps = _steps_for(days_left, float(buy), float(sell))
    if not steps:
        # تخفیف ممکن نیست (حاشیهٔ سود صفر) → صداقت: فقط بگو ریسک ضایعات هست.
        base.update({"mode": "risk_only", "surplus": round(surplus, 3), "at_risk": round(at_risk), "timeline": []})
        return base
    timeline = _schedule(today, days_left, steps, float(sell))
    base.update({
        "mode": "ladder", "surplus": round(surplus, 3), "at_risk": round(at_risk),
        "ladder": [{"from_day": t["from_day"], "percent": t["percent"]} for t in timeline],
        "timeline": [{**t, "kind": "markdown",
                      "label": ("امروز — تخفیف " + _fa(t["percent"]) + "٪") if t["step"] == 1
                      else ("از " + t["jdate"] + " — تخفیف " + _fa(t["percent"]) + "٪")} for t in timeline],
        "final_runway_days": max(0, days_left - timeline[-1]["from_day"]),
        "deepest_percent": steps[-1],
    })
    if base["final_runway_days"] < MIN_FINAL_RUNWAY_DAYS:
        # کالایی که فرصت پله‌ای‌شدن ندارد: یک پیام صریح «آخرین فرصت امروز».
        base["urgent"] = True
    return base


def plan_for_batch(ctx, batch, *, cfg: dict | None = None) -> dict | None:
    """پلان یک ``ProductBatch`` واقعی روی داده‌های همین فروشگاه."""
    cfg = cfg or settings(ctx.db)
    from .insights import _f

    plan = build_plan(today=ctx.today, expiry=batch.expiry_date, qty=_f(batch.current_qty),
                      velocity=conservative_velocity(ctx, batch.product_id),
                      buy=_f(batch.buy_price), sell=_f(batch.sell_price),
                      lead_days=cfg["lead_days"], safety=cfg["safety"])
    if plan is not None:
        plan["batch_id"] = batch.id
        plan["product_id"] = batch.product_id
    return plan


def _fa(n) -> str:
    return f"{int(round(float(n))):,}".translate(_PERSIAN_DIGITS)
