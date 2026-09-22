"""v4.0 — Persian presentation layer for the Business Brain.

The brain speaks the owner's language, in the format the product brief asks
for (§20): وضعیت → دلیل → پیشنهاد → اقدام بعدی, short and direct. Templates
live here (not in the LLM prompt) because they are the *guaranteed* answer
shape: when no local model is installed, or the model's draft fails grounding,
these produce the final text — with the same numbers, from the same tools.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

_FA_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")


def fa_digits(text: str | int) -> str:
    return str(text).translate(_FA_DIGITS)


def fa_num(value, digits: int = 0) -> str:
    """Persian-grouped number (۱۲٬۵۰۰٬۰۰۰ style with Persian digits)."""
    try:
        v = float(value or 0)
    except (TypeError, ValueError):
        return "۰"
    s = f"{v:,.{digits}f}" if digits else f"{int(round(v)):,}"
    return fa_digits(s).replace(",", "٬")


def money(value, *, unit: bool = True) -> str:
    return fa_num(value) + (" تومان" if unit else "")


def toman_short(value) -> str:
    """«۷۸ میلیون», «۱٫۲ میلیارد» — the length the UI cards use."""
    try:
        v = float(value or 0)
    except (TypeError, ValueError):
        return "۰"
    for div, name in ((1_000_000_000, "میلیارد"), (1_000_000, "میلیون"), (1_000, "هزار")):
        if abs(v) >= div:
            n = v / div
            s = f"{n:.1f}".rstrip("0").rstrip(".") if abs(n) < 10 else f"{n:.0f}"
            return f"{fa_digits(s)} {name}"
    return fa_num(v)


def fa_date(d: date | datetime, *, with_time: bool = False) -> str:
    """Jalali rendering via the project's own converter (services.timeservice)."""
    from ..timeservice import format_jalali

    dt = d if isinstance(d, datetime) else datetime(d.year, d.month, d.day)
    return format_jalali(dt, with_time=with_time)


def rel_days(days: int | None) -> str:
    if days is None:
        return "نامعلوم"
    if days < 0:
        return f"{fa_num(abs(days))} روز گذشته"
    if days == 0:
        return "امروز"
    if days == 1:
        return "فردا"
    return f"{fa_num(days)} روز آینده"


CONFIDENCE_FA = {"high": "بالا", "medium": "متوسط", "low": "پایین", "blocked": "محدود (کیفیت داده)",
                 "n/a": "—"}
RISK_FA = {"none": "بی‌خطر", "low": "کم", "medium": "متوسط", "high": "زیاد"}
SEVERITY_FA = {"low": "کم", "medium": "متوسط", "high": "مهم", "critical": "فوری"}


def structured_answer(*, situation: str, reason: str, proposal: str, next_step: str,
                      numbers: str | None = None) -> str:
    """The default answer shape (§20). Kept to four short paragraphs."""
    parts = [situation.strip(), reason.strip()]
    if numbers:
        parts.append(numbers.strip())
    body = "\n".join(p for p in parts if p)
    parts = [body, f"پیشنهاد: {proposal.strip()}", f"اقدام بعدی: {next_step.strip()}"]
    return "\n\n".join(p for p in parts if p)


NO_DATA_TEXT = ("هنوز دادهٔ کافی برای تحلیل در فروشگاه ثبت نشده است. با ثبت اولین خریدها، فروش و موجودی، "
                "همین بخش به تحلیل واقعی تبدیل می‌شود؛ تا آن زمان هیچ عدد یا پیشنهادی نمی‌سازم.")

NO_ACTION_TEXT = ("در حال حاضر اقدام مهمی که نیاز به دخالت شما داشته باشد پیدا نکردم. "
                  "وضعیت فروشگاه در محدودهٔ عادی است و پیشنهاد می‌کنم همین روند را ادامه دهید.")


def blocked_by_data_quality(issues: list[str]) -> str:
    detail = "؛ ".join(issues[:3]) if issues else "چند مورد ناسازگاری در داده‌ها"
    return ("قبل از اینکه دربارهٔ این تصمیم نظر بدهم، یک مشکل در داده‌های فروشگاه وجود دارد که باید اصلاح شود: "
            f"{detail}. تا آن زمان نمی‌خواهم با عدد نادقیق تصمیم بگیرم.")


def tool_failed(tool_label: str) -> str:
    return (f"به اطلاعات «{tool_label}» دسترسی پیدا نکردم، بنابراین نمی‌خواهم حدس بزنم. "
            "اگر ممکن است همین بخش را بررسی کنید یا بعداً دوباره بپرسید.")


def degraded_notice(reasons: list[str]) -> str:
    fa = {"model": "هوش محلی در دسترس نیست و پاسخ‌ها از موتور قطعی می‌آید",
          "web": "دسترسی اینترنت نیست؛ جست‌وجوی وب غیرفعال است",
          "cloud": "ارائه‌دهندهٔ ابری خاموش است",
          "data_quality": "کیفیت داده محدود است"}
    return " · ".join(fa.get(r, r) for r in reasons)


def week_window_label(days: int) -> str:
    return f"{fa_num(days)} روز"


def jalali_today() -> str:
    return fa_date(datetime.utcnow() + timedelta(hours=3, minutes=30))


# --------------------------------------------------------------------------- labels
STATUS_FA = {
    "NEEDS_DECISION": "نیازمند تصمیم",
    "WAITING_APPROVAL": "در انتظار تأیید شما",
    "RUNNING": "در حال اجرا",
    "MONITORING": "در حال پایش نتیجه",
    "COMPLETED": "اجرا شد",
    "MEASURED": "نتیجه اندازه‌گیری شد",
    "RESOLVED": "بسته شد",
    "NO_ACTION": "اقدامی لازم نبود",
    "FAILED": "اجرا ناموفق بود",
    "SNOOZED": "به بعد موکول شد",
    "REJECTED": "رد شد",
}

PRIORITY_FA = {1: "فوری", 2: "مهم", 3: "معمولی", 4: "کم"}


def status_label(status: str) -> str:
    return STATUS_FA.get((status or "").upper(), status or "")


def priority_label(priority) -> str:
    try:
        return PRIORITY_FA.get(int(priority), "معمولی")
    except (TypeError, ValueError):
        return "معمولی"
