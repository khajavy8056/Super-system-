"""v3.0 — optional cloud narrator for Store Intelligence.

The numbers always come from the local engine. This module only *writes*: a
warm, concrete Persian narrative for one insight or for the weekly report.

Two modes, chosen by settings:
  * ``ai.provider = ""``       → local template narrator (no network, always works)
  * ``ai.provider = "openai_compatible"`` → any OpenAI-compatible chat endpoint the
    shop owner configures (``ai.base_url``, ``ai.api_key``, ``ai.model``). This
    covers OpenAI, OpenRouter, Groq, Together, local Ollama/LM Studio, or an
    Iranian reseller — the product never depends on one paid vendor.

No key is bundled, nothing is sent unless the owner enabled it, and only the
already-aggregated evidence (no customer phone numbers) is transmitted.
"""
from __future__ import annotations

import json
import logging
import urllib.request

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Insight, SystemSetting

log = logging.getLogger("supermarket.insights.narrator")

SYSTEM_PROMPT = (
    "تو مشاور فروش یک سوپرمارکت محلی در ایران هستی. با لحن گرم، ساده و حرفه‌ای فارسی بنویس. "
    "فقط از اعداد و شواهدی که به تو داده می‌شود استفاده کن؛ عدد جدید نساز. "
    "خروجی: یک پاراگراف کوتاه «چه خبر است»، سپس ۲ تا ۳ اقدام مشخص با فعل امری، و یک جملهٔ انگیزشی کوتاه. حداکثر ۱۲۰ کلمه."
)


def _setting(db: Session, key: str, default: str = "") -> str:
    row = db.execute(select(SystemSetting).where(SystemSetting.key == key)).scalar_one_or_none()
    return row.value if row else default


def configured(db: Session) -> dict:
    prov = _setting(db, "ai.provider", "")
    return {"provider": prov or "local", "online": prov == "openai_compatible" and bool(_setting(db, "ai.api_key") or _setting(db, "ai.base_url")),
            "model": _setting(db, "ai.model", "") or ("—" if not prov else "gpt-4o-mini"), "base_url": _setting(db, "ai.base_url", "")}


def _redact(evidence: dict) -> dict:
    """Strip personal identifiers before anything leaves the machine."""
    def walk(x):
        if isinstance(x, dict):
            return {k: walk(v) for k, v in x.items() if k not in ("phone", "email", "address")}
        if isinstance(x, list):
            return [walk(i) for i in x[:12]]
        return x
    return walk(evidence)


def _chat(db: Session, messages: list[dict], max_tokens: int = 400) -> str:
    base = (_setting(db, "ai.base_url", "") or "https://api.openai.com/v1").rstrip("/")
    key = _setting(db, "ai.api_key", "")
    model = _setting(db, "ai.model", "") or "gpt-4o-mini"
    body = json.dumps({"model": model, "messages": messages, "temperature": 0.6, "max_tokens": max_tokens}).encode()
    req = urllib.request.Request(base + "/chat/completions", data=body, method="POST",
                                 headers={"Content-Type": "application/json", **({"Authorization": f"Bearer {key}"} if key else {})})
    with urllib.request.urlopen(req, timeout=float(_setting(db, "ai.timeout_seconds", "25") or 25)) as r:
        data = json.loads(r.read().decode())
    return data["choices"][0]["message"]["content"].strip()


def _local_narrative(ins: Insight) -> str:
    acts = json.loads(ins.actions or "[]")
    lines = [ins.body.strip()]
    if acts:
        lines.append("اقدام‌های پیشنهادی:")
        lines += [f"• {a['label']}" for a in acts]
    if float(ins.expected_gain or 0) > 0:
        g = f"{int(float(ins.expected_gain)):,}".translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹"))
        lines.append(f"برآورد اثر: حدود {g} تومان در ماه.")
    return "\n".join(lines)


def narrate(db: Session, ins: Insight, *, force: bool = False) -> str:
    if ins.narrative and not force:
        return ins.narrative
    cfg = configured(db)
    text = None
    if cfg["online"]:
        try:
            payload = {"title": ins.title, "summary": ins.body, "evidence": _redact(json.loads(ins.evidence or "{}")),
                       "actions": [a["label"] for a in json.loads(ins.actions or "[]")], "expected_gain_toman_month": float(ins.expected_gain or 0)}
            text = _chat(db, [{"role": "system", "content": SYSTEM_PROMPT},
                              {"role": "user", "content": "این پیشنهاد را برای صاحب فروشگاه روایت کن:\n" + json.dumps(payload, ensure_ascii=False)}])
        except Exception as exc:
            log.warning("cloud narrator failed (%s) — using local narrative", exc)
    ins.narrative = text or _local_narrative(ins)
    db.flush()
    return ins.narrative


def weekly_report(db: Session, summary: dict, insights: list[dict]) -> str:
    """Manager-facing weekly story (used by /insights/report and the SMS digest)."""
    fa = lambda n: f"{int(round(float(n))):,}".translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹"))  # noqa: E731
    cfg = configured(db)
    if cfg["online"]:
        try:
            payload = {"impact": summary, "open_insights": [{"kind": i["label"], "title": i["title"], "expected_gain": i["expected_gain"]} for i in insights[:8]]}
            return _chat(db, [{"role": "system", "content": SYSTEM_PROMPT.replace("حداکثر ۱۲۰ کلمه", "حداکثر ۲۲۰ کلمه")},
                              {"role": "user", "content": "گزارش هفتگی هوش فروشگاه را بنویس:\n" + json.dumps(payload, ensure_ascii=False)}], max_tokens=700)
        except Exception as exc:
            log.warning("cloud weekly report failed (%s)", exc)
    parts = [f"این هفته {fa(summary.get('accepted', 0))} پیشنهاد اجرا شده و اثر اندازه‌گیری‌شدهٔ آن‌ها {fa(summary.get('total_gain', 0))} تومان است"
             + (f" ({fa(summary['share_of_month_profit'] * 100)}٪ سود این ماه)." if summary.get("share_of_month_profit") else ".")]
    if insights:
        parts.append(f"{fa(len(insights))} پیشنهاد باز دارید؛ مهم‌ترین‌ها:")
        parts += [f"• {i['title']}" for i in insights[:5]]
        exp = sum(float(i["expected_gain"] or 0) for i in insights)
        if exp:
            parts.append(f"اگر همه اجرا شوند، برآورد اثر حدود {fa(exp)} تومان در ماه است.")
    parts.append("هر پیشنهاد را با یک لمس اجرا کنید؛ اثر واقعی آن به‌طور خودکار اندازه‌گیری می‌شود.")
    return "\n".join(parts)
