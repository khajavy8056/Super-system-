"""v4.0 — Prompts and sampling parameters (§20, §21, §32, §33, §34).

The prompt is written for **Qwen3-1.7B**, the model this product ships: a small
model that must be told exactly what shape the answer takes, exactly what it may
not do, and exactly where its facts come from. Anything softer produces fluent
Persian that drifts into invented numbers — the one failure mode this product
cannot tolerate.

Sampling parameters follow the model family's own recommendations:

* thinking mode (reasoning, agent loop): temperature .6, top_p .95, top_k 20, min_p 0
* fast mode (summaries, navigation):  temperature .7, top_p .8, top_k 20, min_p 0
"""
from __future__ import annotations

#: §32 — reasoning parameters, as published by the Qwen team for thinking mode
THINKING_PARAMS = {"temperature": 0.6, "top_p": 0.95, "top_k": 20, "min_p": 0.0,
                   "max_tokens": 512, "thinking": True}

#: §33 — fast mode for short/simple turns
FAST_PARAMS = {"temperature": 0.7, "top_p": 0.8, "top_k": 20, "min_p": 0.0,
               "max_tokens": 320, "thinking": False}

#: §34 — a hard ceiling on the agent loop; never unbounded
MAX_TOOL_ROUNDS = 8


SYSTEM_PROMPT = """تو «مغز کسب‌وکار» یک سوپرمارکت محلی در ایران هستی و با صاحب فروشگاه حرف می‌زنی.

قواعد قطعی:
۱) هیچ عددی از خودت نساز. فقط اعدادی را بنویس که در «اطلاعات فروشگاه» یا در «نتیجهٔ ابزارها» آمده است.
۲) اگر عددی لازم داری و در دست نیست، ابزار مناسب را صدا بزن؛ اگر جواب نداد، صریح بگو که به آن اطلاعات دسترسی نداشتی.
۳) لحن: ساده، محترمانه، حرفه‌ای و کوتاه. نه خودمانی، نه اداری و خشک. شوخی و تعریف بی‌مورد ممنوع.
۴) خروجی حداکثر چهار بخش کوتاه: وضعیت / دلیل / پیشنهاد / اقدام بعدی. جزئیات فنی را وارد نکن.
۵) اگر وضعیت نیازی به اقدام ندارد، صریح بگو «کاری لازم نیست» — پیشنهاد الکی نساز.
۶) هیچ‌وقت نگو که به دیتابیس دسترسی داری یا SQL می‌زنی. تو فقط ابزارها را صدا می‌زنی.
۷) سیاست‌های صاحب فروشگاه (در «سیاست‌ها») بر نظر تو اولویت دارند.
۸) ساختار داخلی، نام فایل، نام جدول و متن ابزار خام را برای مدیر ننویس.

قالب پیشنهادی پاسخ:
وضعیت: ...
دلیل: ...
پیشنهاد: ...
اقدام بعدی: ...
"""


def situation_block(situation_text: str, policies: str, memory: str = "") -> str:
    parts = ["[وضعیت فروشگاه]", situation_text]
    if policies:
        parts += ["[سیاست‌های صاحب فروشگاه]", policies]
    if memory:
        parts += ["[حافظهٔ تصمیم‌ها و نتایج گذشته]", memory]
    return "\n\n".join(parts)


def tools_block(tool_list: list[dict]) -> str:
    lines = ["[ابزارهای در دسترس] برای هر ابزار فقط نام و پارامترها را در قالب JSON بنویس."]
    for tool in tool_list:
        params = ", ".join(f"{k}:{v}" for k, v in (tool.get("input_schema") or {}).items()) or "—"
        lines.append(f"- {tool['name']}({params}): {tool['description']}")
    return "\n".join(lines)


def tool_call_instruction() -> str:
    return ('اگر به اطلاعات بیشتری نیاز داری، فقط و فقط یک خط JSON به این شکل بنویس و منتظر نتیجه بمان:\n'
            '{"tool": "<نام ابزار>", "params": {…}}\n'
            'وقتی اطلاعات کافی بود، پاسخ نهایی فارسی را بنویس و هیچ JSON ننویس.')


def decision_block(title: str, reason: str, option_label: str, approval_hint: str) -> str:
    return ("\n".join(["", "[تصمیم پیشنهادی موتور قطعی] این اعداد از موتور قطعی آمده‌اند و قابل استنادند:",
                       f"موضوع: {title}", f"دلیل: {reason}", f"گزینهٔ پیشنهادی: {option_label}",
                       approval_hint]))


GREETING = "سلام! وضعیت فروشگاه را بررسی کردم."

FORBIDDEN_MARKERS = ("<think", "</think", "<|", "```json")
