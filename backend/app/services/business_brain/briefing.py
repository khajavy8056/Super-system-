# -*- coding: utf-8 -*-
"""v4.5.0 — the brain's daily briefing: the MODEL works in the intelligence
section, not only in the chat (owner's rule: «نباید مدل فقط جنبه چت داشته
باشد بلکه باید در بخش هوشمندی سیستم هم عمل کند»).

Every 15 minutes the brain worker (main._start_brain_worker) already runs one
proactive pass over the store. This module turns the RESULT of that pass into
a short manager-facing Persian briefing:

  • deterministic facts first (open proactive cards, open decisions, due
    reminders — counts and toman impacts from the audited decision rows);
  • then, when the local model is available, the narrative is WRITTEN BY THE
    MODEL over exactly those facts — with a grounding gate: any number the
    model writes that did not come from the facts throws the narrative away
    and the deterministic text is served instead. No invented numbers, ever;
  • the result is cached (brain.briefing setting, ~15 min) so the intelligence
    screens read it instantly; ``refresh=True`` forces a rebuild.

Never raises: a broken model or a missing table degrades to the deterministic
briefing.
"""
from __future__ import annotations

import json
import re
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...models import SystemSetting
from . import persian as fa
from . import decisions as decision_svc
from . import followups as followup_svc
from . import proactive as proactive_svc

SETTING_KEY = "brain.briefing"
MAX_AGE_MIN = 15

_SYSTEM = (
    "تو «مغز فروشگاه سوپری‌من» هستی و برای مدیر فروشگاه یک خلاصهٔ کوتاه و روان می‌نویسی. "
    "فقط از همین داده‌هایی که داده شده استفاده کن؛ هیچ عددی از خودت نساز. "
    "حداکثر ۴ جمله بنویس؛ لحن ساده و حرفه‌ای؛ اگر کاری لازم نیست صریح بگو «کاری لازم نیست»."
)


def _cached(db: Session) -> dict | None:
    try:
        row = db.execute(select(SystemSetting).where(SystemSetting.key == SETTING_KEY)).scalar_one_or_none()
        return json.loads(row.value) if row and row.value else None
    except Exception:
        return None


def _store(db: Session, payload: dict) -> None:
    row = db.execute(select(SystemSetting).where(SystemSetting.key == SETTING_KEY)).scalar_one_or_none()
    if row is None:
        db.add(SystemSetting(key=SETTING_KEY, value=json.dumps(payload, ensure_ascii=False)))
    else:
        row.value = json.dumps(payload, ensure_ascii=False)
    db.flush()


def _normalize_digits(text: str) -> str:
    """Persian/Arabic digits → ASCII, so grounding compares one alphabet."""
    table = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
    return (text or "").translate(table)


def _numbers_in(text: str) -> set[str]:
    return set(re.findall(r"\d+(?:[.,]\d+)?", _normalize_digits(text)))


def _facts(db: Session) -> dict:
    """The deterministic, audited facts the briefing is allowed to mention."""
    alerts = proactive_svc.alerts(db, limit=5)
    open_decisions = decision_svc.open_count(db)
    followups = followup_svc.open_items(db, limit=25)
    now = datetime.utcnow()
    due = [f for f in followups if (f.get("due_at") or "")[:16] <= now.isoformat()[:16]]
    impact = sum(float(a.get("impact_toman") or 0) for a in alerts)
    return {
        "alerts": [{"title": a.get("title", ""), "priority": a.get("priority", 3),
                    "impact_toman": float(a.get("impact_toman") or 0)} for a in alerts],
        "open_decisions": int(open_decisions),
        "followups_open": len(followups),
        "followups_due": len(due),
        "impact_toman": impact,
        "last_run": proactive_svc.last_run(db),
    }


def _deterministic_text(facts: dict) -> str:
    parts: list[str] = []
    n_alerts = len(facts["alerts"])
    if n_alerts == 0 and facts["open_decisions"] == 0 and facts["followups_open"] == 0:
        return ("همه‌چیز مرتب است: کارت بازّی روی میز نیست و یادآوریِ انجام‌نشده‌ای در نوبت نیست. "
                "مغز فروشگاه هر ۱۵ دقیقه فروشگاه را از نو بررسی می‌کند.")
    if n_alerts:
        top = facts["alerts"][0]
        parts.append(f"مهم‌ترین موضوع روی میز: {top['title']}"
                     + (f" (اولویت {fa.fa_num(top['priority'])} از ۵)" if top.get("priority") else "") + ".")
        if n_alerts > 1:
            parts.append(f"جمعاً {fa.fa_num(n_alerts)} کارت تصمیم باز دارد"
                         + (f" با اثر تخمینی {fa.money(facts['impact_toman'])}" if facts["impact_toman"] > 0 else "")
                         + ".")
    else:
        parts.append("کارت تصمیم تازه‌ای روی میز نیست.")
    if facts["followups_due"]:
        parts.append(f"{fa.fa_num(facts['followups_due'])} یادآوری سررسیدشده منتظر پاسخ شماست — از بخش مغز فروشگاه ببینید.")
    elif facts["followups_open"]:
        parts.append(f"{fa.fa_num(facts['followups_open'])} پیگیری زمان‌دار در جریان است.")
    return " ".join(parts)


def _model_text(db: Session, facts: dict) -> str | None:
    """Ask the LOCAL model to write the briefing over the facts. Grounded:
    any number not present in the facts (or in the boilerplate numbers) → None."""
    from .runtime import get_runtime

    runtime = get_runtime(db)
    if not runtime.available():
        return None
    fact_lines = [
        f"- کارت‌های تصمیم باز (مغز): {len(facts['alerts'])}"
        + (f"؛ عناوین: " + "، ".join(a["title"] for a in facts["alerts"][:3]) if facts["alerts"] else ""),
        f"- تصمیم‌های باز در کل: {facts['open_decisions']}",
        f"- پیگیری‌های باز: {facts['followups_open']}",
        f"- یادآوری‌های سررسیدشده: {facts['followups_due']}",
    ]
    if facts["impact_toman"] > 0:
        fact_lines.append(f"- مجموع اثر تخمینی کارت‌های باز: {int(facts['impact_toman']):,} تومان")
    allowed = _numbers_in(json.dumps(facts, ensure_ascii=False)) | _numbers_in(" ".join(fact_lines)) | {"15", "5"}
    try:
        text = runtime.chat(
            [{"role": "system", "content": _SYSTEM},
             {"role": "user", "content": "داده‌های همین الان فروشگاه:\n" + "\n".join(fact_lines)
              + "\n\nاز همین‌ها یک خلاصهٔ کوتاه فارسی برای مدیر بنویس."}],
            max_tokens=220, temperature=0.4).strip()
    except Exception:                                   # noqa: BLE001 — the model is an enhancement
        return None
    if not text:
        return None
    unknown = _numbers_in(text) - allowed
    if unknown:
        return None                                     # a number the facts never had → refuse
    return text


def build(db: Session, *, refresh: bool = False) -> dict:
    """The briefing shown in the intelligence sections. Cached ~15 min."""
    cached = _cached(db)
    if cached and not refresh:
        try:
            age_min = (datetime.utcnow() - datetime.fromisoformat(cached["at"])).total_seconds() / 60
            if age_min < MAX_AGE_MIN:
                return cached
        except Exception:
            pass
    facts = _facts(db)
    text = None
    by = "deterministic"
    try:
        text = _model_text(db, facts)
    except Exception:                                   # noqa: BLE001
        text = None
    if text:
        by = "model"
    else:
        text = _deterministic_text(facts)
    payload = {"text": text, "by": by, "at": datetime.utcnow().isoformat(),
               "counts": {"open_decisions": facts["open_decisions"],
                          "followups_open": facts["followups_open"],
                          "followups_due": facts["followups_due"],
                          "alerts": len(facts["alerts"])},
               "alerts": [a["title"] for a in facts["alerts"][:3]]}
    try:
        _store(db, payload)
        db.commit()
    except Exception:                                   # noqa: BLE001 — cache is best-effort
        db.rollback()
    return payload
