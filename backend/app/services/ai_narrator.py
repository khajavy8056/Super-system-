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


# v3.5 — free / cheap OpenAI-compatible providers the owner can pick with one tap.
# No key is bundled; the owner creates a free key on the provider's site and pastes it.
PRESETS = [
    {"id": "openrouter", "label": "OpenRouter (مدل‌های رایگان)", "base_url": "https://openrouter.ai/api/v1", "model": "meta-llama/llama-3.3-70b-instruct:free",
     "keys_url": "https://openrouter.ai/keys", "free": True, "note": "ثبت‌نام با ایمیل، بدون کارت؛ مدل‌های :free روزانه سهمیهٔ رایگان دارند"},
    {"id": "groq", "label": "Groq (سریع، رایگان)", "base_url": "https://api.groq.com/openai/v1", "model": "llama-3.3-70b-versatile",
     "keys_url": "https://console.groq.com/keys", "free": True, "note": "سهمیهٔ رایگان روزانه؛ پاسخ در کمتر از ۲ ثانیه"},
    {"id": "gemini", "label": "Google Gemini (رایگان)", "base_url": "https://generativelanguage.googleapis.com/v1beta/openai", "model": "gemini-2.0-flash",
     "keys_url": "https://aistudio.google.com/apikey", "free": True, "note": "کلید رایگان از AI Studio؛ ممکن است در ایران به VPN نیاز داشته باشد"},
    {"id": "mistral", "label": "Mistral (رایگان)", "base_url": "https://api.mistral.ai/v1", "model": "mistral-small-latest",
     "keys_url": "https://console.mistral.ai/api-keys", "free": True, "note": "پلن رایگان با محدودیت نرخ"},
    {"id": "ollama", "label": "Ollama روی همین رایانه (آفلاین)", "base_url": "http://127.0.0.1:11434/v1", "model": "qwen2.5:7b",
     "keys_url": "https://ollama.com/download", "free": True, "note": "کاملاً محلی و بدون اینترنت؛ به ۸ گیگ رم نیاز دارد"},
    {"id": "openai", "label": "OpenAI", "base_url": "https://api.openai.com/v1", "model": "gpt-4o-mini", "keys_url": "https://platform.openai.com/api-keys", "free": False, "note": "پولی"},
]


def _setting(db: Session, key: str, default: str = "") -> str:
    row = db.execute(select(SystemSetting).where(SystemSetting.key == key)).scalar_one_or_none()
    return row.value if row else default


def configured(db: Session) -> dict:
    prov = _setting(db, "ai.provider", "")
    return {"provider": prov or "local", "online": prov == "openai_compatible" and bool(_setting(db, "ai.api_key") or _setting(db, "ai.base_url")),
            "model": _setting(db, "ai.model", "") or ("—" if not prov else "gpt-4o-mini"), "base_url": _setting(db, "ai.base_url", ""),
            "preset": _setting(db, "ai.preset", ""), "has_key": bool(_setting(db, "ai.api_key", "")), "last_advice_at": _setting(db, "ai.last_advice_at", "")}


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


# ============================================================================ v3.5 advisor loop
ADVISOR_PROMPT = (
    "تو مشاور ارشد یک سوپرمارکت محلی در ایران هستی. یک گزارش ساخت‌یافته از وضعیت فروشگاه (اعداد واقعی، بدون نام و شمارهٔ مشتری) دریافت می‌کنی. "
    "وظیفهٔ تو: ۳ تا ۶ راهکار مشخص، عملی و اولویت‌بندی‌شده بده که همین هفته قابل اجرا باشند. عدد جدید نساز؛ فقط از اعداد گزارش استفاده کن. "
    "خروجی را فقط به صورت JSON معتبر با این ساختار بده، بدون هیچ متن اضافه:\n"
    '{"summary": "دو جملهٔ خلاصهٔ وضعیت", "suggestions": [{"title": "عنوان کوتاه", "why": "دلیل با استناد به اعداد گزارش", '
    '"steps": ["گام ۱", "گام ۲"], "priority": 1, "expected_gain_toman_month": 0, '
    '"action": {"type": "note|enable_nudges|flash_sale|threshold_campaign|set_setting|none", "params": {}}}]}\n'
    "action.type فقط از همین فهرست؛ برای flash_sale پارامترهای percent و days، برای threshold_campaign پارامترهای percent و min_purchase و days. "
    "اگر مطمئن نیستی از note استفاده کن. لحن: ساده، محترمانه، فارسی."
)
_SAFE_ACTIONS = {"note", "enable_nudges", "flash_sale", "threshold_campaign", "set_setting", "none"}
_SAFE_SETTINGS = {"insights.pos_nudges", "pos.max_manual_discount_pct", "sms.max_promo_per_month", "pos.ask_phone_above"}


def presets() -> list[dict]:
    return PRESETS


def apply_preset(db: Session, preset_id: str) -> dict:
    from .insight_actions import _set_setting
    p = next((x for x in PRESETS if x["id"] == preset_id), None)
    if not p:
        raise ValueError("unknown preset")
    _set_setting(db, "ai.provider", "openai_compatible")
    _set_setting(db, "ai.base_url", p["base_url"])
    _set_setting(db, "ai.model", p["model"])
    _set_setting(db, "ai.preset", preset_id)
    db.commit()
    return configured(db)


def test_connection(db: Session) -> dict:
    import time
    t = time.time()
    try:
        txt = _chat(db, [{"role": "user", "content": "فقط بنویس: آماده"}], max_tokens=10)
        return {"ok": True, "reply": txt[:80], "ms": int((time.time() - t) * 1000), **configured(db)}
    except Exception as exc:
        return {"ok": False, "error": _friendly_error(exc), "ms": int((time.time() - t) * 1000), **configured(db)}


def _friendly_error(exc: Exception) -> str:
    import urllib.error
    if isinstance(exc, urllib.error.HTTPError):
        code = exc.code
        try:
            body = exc.read().decode()[:300]
        except Exception:
            body = ""
        if code == 401:
            return "کلید API نامعتبر است (401)"
        if code == 429:
            return "سهمیهٔ رایگان امروز تمام شده یا نرخ درخواست زیاد است (429) — کمی بعد دوباره تلاش کنید"
        if code == 404:
            return "مدل یا آدرس سرویس پیدا نشد (404) — نام مدل را بررسی کنید"
        return f"خطای سرویس {code}: {body}"
    if isinstance(exc, urllib.error.URLError):
        return f"اتصال برقرار نشد: {exc.reason} (اینترنت / فیلترینگ / VPN)"
    return str(exc)[:200]


def build_report(db: Session) -> dict:
    """The structured, anonymised report that goes to the model (and is shown to the owner first)."""
    from . import insights as svc
    from sqlalchemy import func
    from ..models import Invoice, InvoiceItem
    now = svc._now()
    ctx = svc._load_ctx(db, 90)
    n = len(ctx.invoices)
    sales = sum(i["total"] for i in ctx.invoices.values())
    profit = sum(l["profit"] for l in ctx.lines)
    last30 = [i for i in ctx.invoices.values() if i["at"] >= now - __import__("datetime").timedelta(days=30)]
    prev30 = [i for i in ctx.invoices.values() if now - __import__("datetime").timedelta(days=60) <= i["at"] < now - __import__("datetime").timedelta(days=30)]
    top_profit = {}
    for l in ctx.lines:
        top_profit[l["pid"]] = top_profit.get(l["pid"], 0) + l["profit"]
    top = sorted(top_profit.items(), key=lambda kv: -kv[1])[:10]
    open_rows = db.execute(select(Insight).where(Insight.status == "NEW").order_by(Insight.priority, Insight.expected_gain.desc()).limit(25)).scalars().all()
    from . import insights_pro
    facts = insights_pro.surprise_facts(ctx)[:6]
    return {
        "generated_at": now.isoformat(), "window_days": 90, "currency": "toman",
        "store": {"invoices_90d": n, "sales_90d": round(sales), "profit_90d": round(profit), "margin_pct": round(profit / sales * 100, 1) if sales else 0,
                  "avg_ticket": round(sales / n) if n else 0, "registered_customer_share_pct": round(sum(1 for i in ctx.invoices.values() if i["cust"]) / n * 100) if n else 0,
                  "sales_last30": round(sum(i["total"] for i in last30)), "sales_prev30": round(sum(i["total"] for i in prev30)),
                  "invoices_last30": len(last30), "invoices_prev30": len(prev30), "active_products": len(ctx.products)},
        "top_profit_products": [{"name": svc._pname(ctx, p), "profit_90d": round(v)} for p, v in top],
        "open_suggestions": [{"kind": r.kind, "label": svc.KIND_LABELS.get(r.kind, r.kind), "title": r.title, "priority": r.priority, "expected_gain_month": float(r.expected_gain or 0)} for r in open_rows],
        "impact": svc.impact_summary(db),
        "facts": [f["title"] for f in facts],
    }


def ask_advisor(db: Session, *, user=None) -> dict:
    """Send the report, parse the model's suggestions, store each as an AI_ADVISOR insight (accept = apply)."""
    from .insight_actions import _set_setting
    from decimal import Decimal
    cfg = configured(db)
    if not cfg["online"]:
        raise RuntimeError("سرویس هوش مصنوعی پیکربندی نشده — ابتدا یک سرویس رایگان انتخاب و کلید را وارد کنید")
    report = build_report(db)
    raw = _chat(db, [{"role": "system", "content": ADVISOR_PROMPT}, {"role": "user", "content": json.dumps(report, ensure_ascii=False)}], max_tokens=1500)
    data = _parse_json(raw)
    sugg = data.get("suggestions") or []
    from . import insights as svc
    now = svc._now()
    created = 0
    ids = []
    for i, sg in enumerate(sugg[:6]):
        title = str(sg.get("title") or "").strip()[:200]
        if not title:
            continue
        act = sg.get("action") or {}
        typ = act.get("type") if act.get("type") in _SAFE_ACTIONS else "note"
        params = act.get("params") or {}
        if typ == "set_setting" and params.get("key") not in _SAFE_SETTINGS:
            typ = "note"; params = {}
        if typ == "flash_sale":
            params = {"percent": max(1, min(20, int(params.get("percent", 5) or 5))), "days": max(1, min(30, int(params.get("days", 7) or 7)))}
        if typ == "threshold_campaign":
            params = {"percent": max(1, min(10, int(params.get("percent", 3) or 3))), "min_purchase": max(10000, int(params.get("min_purchase", 200000) or 200000)), "days": max(7, min(60, int(params.get("days", 30) or 30)))}
        actions = [] if typ == "none" else [{"type": typ, "label": {"note": "ثبت به‌عنوان کار", "enable_nudges": "فعال‌کردن پیشنهاد پای صندوق", "flash_sale": "ساخت کمپین فروش ویژه", "threshold_campaign": "ساخت کمپین آستانهٔ سبد", "set_setting": "اعمال تنظیم"}[typ], "params": params}]
        body = str(sg.get("why") or "").strip()
        steps = [str(x) for x in (sg.get("steps") or [])][:6]
        if steps:
            body += "\n\nگام‌ها:\n" + "\n".join(f"{k+1}. {st}" for k, st in enumerate(steps))
        key = f"{now.date().isoformat()}:{i}"
        row = Insight(kind="AI_ADVISOR", dedupe_key=key, title=title, body=body[:2000], priority=max(1, min(4, int(sg.get("priority", 3) or 3))),
                      evidence=json.dumps({"model": cfg["model"], "steps": steps, "summary": data.get("summary", ""), "report_digest": {k: report["store"][k] for k in ("sales_last30", "sales_prev30", "margin_pct")}}, ensure_ascii=False),
                      actions=json.dumps(actions, ensure_ascii=False), expected_gain=Decimal(str(int(float(sg.get("expected_gain_toman_month", 0) or 0)))),
                      metric=json.dumps({"metric": "avg_basket_size", "window_days": 28}), status="NEW", last_seen_at=now)
        db.add(row); db.flush(); ids.append(row.id); created += 1
    _set_setting(db, "ai.last_advice_at", now.isoformat())
    db.commit()
    return {"ok": True, "created": created, "ids": ids, "summary": data.get("summary", ""), "model": cfg["model"], "report": report}


def _parse_json(raw: str) -> dict:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.lower().startswith("json"):
            raw = raw[4:]
    try:
        return json.loads(raw)
    except Exception:
        a, b = raw.find("{"), raw.rfind("}")
        if a >= 0 and b > a:
            try:
                return json.loads(raw[a:b + 1])
            except Exception:
                pass
    return {"summary": raw[:400], "suggestions": [{"title": "پاسخ مشاور", "why": raw[:1500], "steps": [], "priority": 3, "action": {"type": "note"}}]}
