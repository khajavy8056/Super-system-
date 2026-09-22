"""v4.0 — Policy Memory + Policy Gate (§11, §43, §47).

Policies are the *rules of this shop*, structured, so a decision can be checked
against them mechanically instead of the model "remembering" a preference:

    max_discount_without_approval = 15
    minimum_cash_reserve          = 100000000
    supplier.<id>.priority        = HIGH
    discount_below_margin_floor   = false

Three sources, one table (``brain_policies``):

* ``DEFAULT`` — shipped with the product; the owner can change any of them.
* ``OWNER`` — set by the administrator in the UI (or by saying it in chat and
  confirming; the write path is the same).
* ``LEARNED`` — inferred from measured outcomes (e.g. the shop's discounts
  never paid back above 12 %, so the safe ceiling drops). Learned policies are
  always marked, never silent: ``source`` is visible in the UI.

The gate returns a verdict with the individual checks, so the Decision Center
can show *why* an action needs approval — and the chat can say it in Persian.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...models import BrainPolicy
from . import persian as fa

#: key -> (default value, Persian label, type, human note)
DEFAULTS: dict[str, tuple[object, str, str, str]] = {
    "max_discount_without_approval": (15, "سقف تخفیف بدون تأیید (درصد)", "percent",
                                      "تخفیف بیشتر از این عدد همیشه نیاز به تأیید مدیر دارد"),
    "maximum_discount_any": (40, "سقف مطلق تخفیف (درصد)", "percent",
                             "بالاتر از این عدد حتی با تأیید هم پیشنهاد نمی‌شود"),
    "minimum_cash_reserve": (0, "کف نقدینگی (تومان)", "money",
                             "هیچ پیشنهادی نباید نقدینگی را زیر این عدد ببرد"),
    "minimum_margin_pct": (3, "کف حاشیهٔ سود (درصد)", "percent",
                           "فروش زیر این حاشیه پیشنهاد نمی‌شود مگر برای آزادسازی سرمایه"),
    "auto_approve_low_risk": (True, "اجرای خودکار اقدام‌های کم‌ریسک", "bool",
                              "کارهای برگشت‌پذیر مثل یادداشت انبار بدون تأیید اجرا می‌شوند"),
    "supplier_priority": ({}, "اولویت تأمین‌کننده‌ها", "json",
                          "{\"12\": \"HIGH\", \"13\": \"LOW\"} — HIGH یعنی حفظ رابطه و اعتبار مقدم است"),
    "require_approval_for_sms": (True, "تأیید لازم برای پیامک", "bool",
                                 "پیامک به مشتری هزینه دارد و برگشت‌پذیر نیست"),
    "require_approval_for_price": (True, "تأیید لازم برای تغییر قیمت", "bool",
                                   "هر تغییر قیمت باید به‌صورت دستی تأیید شود"),
    "expiry_action_horizon_days": (14, "افق اقدام برای کالای نزدیک انقضا (روز)", "number",
                                   "کمتر از این تعداد روز مانده به انقضا، تصمیم انقضا فعال می‌شود"),
    "max_active_alerts": (5, "حداکثر هشدار فعال", "number",
                          "بیش از این تعداد هشدار، به‌صورت خوشه‌ای نمایش داده می‌شود"),
    "allow_cloud_ai": (False, "اجازهٔ استفاده از هوش ابری", "bool",
                       "پیش‌فرض خاموش؛ داده فقط در صورت روشن‌کردن مدیر و به‌اندازهٔ لازم فرستاده می‌شود"),
    "ai_mode": ("local_only", "حالت هوش مصنوعی", "text",
                "local_only | local_preferred | cloud_fallback | cloud_only"),
}


def _coerce(value, type_: str):
    if type_ == "bool":
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in ("1", "true", "yes", "on", "بله", "روشن")
    if type_ in ("percent", "number", "money"):
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0
    if type_ == "json":
        if isinstance(value, (dict, list)):
            return value
        try:
            return json.loads(value or "{}")
        except ValueError:
            return {}
    return str(value)


@dataclass
class PolicyCheck:
    key: str
    label: str
    ok: bool
    note: str = ""
    value: object = None

    def to_dict(self) -> dict:
        return {"key": self.key, "label": self.label, "ok": self.ok, "note": self.note, "value": self.value}


@dataclass
class PolicyVerdict:
    allowed: bool = True
    requires_approval: bool = True
    checks: list[PolicyCheck] = field(default_factory=list)
    blocking: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"allowed": self.allowed, "requires_approval": self.requires_approval,
                "checks": [c.to_dict() for c in self.checks], "blocking": list(self.blocking)}

    def reason_fa(self) -> str:
        if not self.allowed:
            return "سیاست فروشگاه: " + "؛ ".join(self.blocking)
        if self.requires_approval:
            notes = [c.note for c in self.checks if not c.ok]
            return "نیازمند تأیید شما: " + ("؛ ".join(notes) if notes else "این اقدام برگشت‌پذیر نیست")
        return "در محدودهٔ سیاست‌های تعریف‌شده است"


def ensure_defaults(db: Session) -> None:
    """Materialise the shipped defaults once, so the UI can list/edit them."""
    have = {r.key for r in db.execute(select(BrainPolicy)).scalars()}
    added = False
    for key, (value, label, type_, note) in DEFAULTS.items():
        if key in have:
            continue
        db.add(BrainPolicy(key=key, value=json.dumps(value, ensure_ascii=False), value_type=type_,
                           label=label, note=note, source="DEFAULT", scope="store"))
        added = True
    if added:
        db.flush()


def all_policies(db: Session, *, include_defaults: bool = True) -> dict[str, dict]:
    ensure_defaults(db)
    out: dict[str, dict] = {}
    if include_defaults:
        for key, (value, label, type_, note) in DEFAULTS.items():
            out[key] = {"key": key, "value": value, "value_type": type_, "label": label, "note": note,
                        "source": "DEFAULT", "scope": "store"}
    for row in db.execute(select(BrainPolicy).order_by(BrainPolicy.key)).scalars():
        try:
            value = json.loads(row.value)
        except (TypeError, ValueError):
            value = row.value
        meta = DEFAULTS.get(row.key)
        out[row.key] = {"key": row.key, "value": _coerce(value, row.value_type), "value_type": row.value_type,
                        "label": row.label or (meta[1] if meta else row.key),
                        "note": row.note or (meta[3] if meta else ""),
                        "source": row.source, "scope": row.scope, "updated_at": row.updated_at.isoformat()
                        if getattr(row, "updated_at", None) else None}
    return out


def get_value(db: Session, key: str, default=None):
    row = db.execute(select(BrainPolicy).where(BrainPolicy.key == key)).scalar_one_or_none()
    if row is None:
        if key in DEFAULTS:
            return DEFAULTS[key][0]
        return default
    try:
        raw = json.loads(row.value)
    except (TypeError, ValueError):
        raw = row.value
    return _coerce(raw, row.value_type or (DEFAULTS.get(key, ("", "", "text", ""))[2]))


def set_value(db: Session, key: str, value, *, user_id: int | None = None, source: str = "OWNER",
              note: str | None = None) -> dict:
    """Owner/unset policy write. ``source=LEARNED`` is used by the learner."""
    meta = DEFAULTS.get(key)
    type_ = meta[2] if meta else ("json" if isinstance(value, (dict, list)) else "text")
    value = _coerce(value, type_)
    row = db.execute(select(BrainPolicy).where(BrainPolicy.key == key)).scalar_one_or_none()
    payload = json.dumps(value, ensure_ascii=False)
    if row is None:
        row = BrainPolicy(key=key, value=payload, value_type=type_, label=meta[1] if meta else key,
                          note=note or (meta[3] if meta else ""), source=source, scope="store",
                          updated_by=user_id)
        db.add(row)
    else:
        row.value = payload
        row.value_type = type_
        row.source = source
        row.updated_by = user_id
        if note:
            row.note = note
    db.flush()
    return {"key": key, "value": value, "value_type": type_, "source": source}


# --------------------------------------------------------------------------- the gate
def check_discount(db: Session, percent: float, *, margin_pct: float | None = None) -> PolicyVerdict:
    """§47 — discounts are the most common money-moving action in a supermarket."""
    max_no_approval = float(get_value(db, "max_discount_without_approval", 15) or 0)
    hard_max = float(get_value(db, "maximum_discount_any", 40) or 0)
    margin_floor = float(get_value(db, "minimum_margin_pct", 3) or 0)
    verdict = PolicyVerdict(allowed=True, requires_approval=False)
    if percent > hard_max:
        verdict.allowed = False
        verdict.blocking.append(f"تخفیف {fa.fa_num(percent, 1)}٪ از سقف مطلق فروشگاه ({fa.fa_num(hard_max)}٪) بیشتر است")
        verdict.checks.append(PolicyCheck("maximum_discount_any", "سقف مطلق تخفیف", False,
                                          f"سقف {fa.fa_num(hard_max)}٪ است", hard_max))
    elif percent > max_no_approval:
        verdict.requires_approval = True
        verdict.checks.append(PolicyCheck("max_discount_without_approval", "سقف تخفیف بدون تأیید", False,
                                          f"{fa.fa_num(percent, 1)}٪ بیشتر از حدود مجاز بدون تأیید "
                                          f"({fa.fa_num(max_no_approval)}٪) است", max_no_approval))
    else:
        verdict.checks.append(PolicyCheck("max_discount_without_approval", "سقف تخفیف بدون تأیید", True,
                                          f"در محدودهٔ {fa.fa_num(max_no_approval)}٪", max_no_approval))
    if margin_pct is not None:
        ok = margin_pct >= margin_floor
        verdict.checks.append(PolicyCheck("minimum_margin_pct", "کف حاشیهٔ سود", ok,
                                          f"حاشیهٔ بعد از تخفیف {fa.fa_num(margin_pct, 1)}٪ "
                                          f"(کف {fa.fa_num(margin_floor, 1)}٪)", margin_floor))
        if not ok:
            verdict.requires_approval = True
    if verdict.allowed:
        verdict.requires_approval = verdict.requires_approval or bool(get_value(db, "require_approval_for_price", True))
    return verdict


def check_cash(db: Session, *, cash_after: float, reserve: float | None = None) -> PolicyVerdict:
    """A cash decision must not push the till below the owner's floor."""
    floor = float(reserve if reserve is not None else (get_value(db, "minimum_cash_reserve", 0) or 0))
    verdict = PolicyVerdict(allowed=True, requires_approval=False)
    ok = cash_after >= floor
    verdict.checks.append(PolicyCheck("minimum_cash_reserve", "کف نقدینگی", ok,
                                      f"بعد از این اقدام {fa.money(cash_after)} می‌ماند "
                                      f"(کف {fa.money(floor)})", floor))
    if not ok:
        verdict.requires_approval = True
        verdict.blocking.append(f"نقدینگی بعد از اقدام ({fa.toman_short(cash_after)} تومان) "
                                f"زیر کف تعیین‌شده ({fa.toman_short(floor)} تومان) می‌رود")
        verdict.allowed = False
    return verdict


def check_sms(db: Session, *, count: int) -> PolicyVerdict:
    verdict = PolicyVerdict(allowed=True, requires_approval=bool(get_value(db, "require_approval_for_sms", True)))
    verdict.checks.append(PolicyCheck("require_approval_for_sms", "تأیید پیامک",
                                      not verdict.requires_approval,
                                      f"{fa.fa_num(count)} پیامک هزینهٔ واقعی دارد", verdict.requires_approval))
    return verdict


def supplier_rank(db: Session, supplier_id: int | None) -> str:
    """HIGH | NORMAL | LOW — who gets paid first when cash is short (§23)."""
    prio = get_value(db, "supplier_priority", {}) or {}
    if supplier_id is None:
        return "NORMAL"
    value = prio.get(str(supplier_id)) or prio.get(supplier_id)
    return str(value).upper() if value else "NORMAL"


def action_requires_approval(db: Session, action_type: str, params: dict | None = None) -> bool:
    """Classify a concrete action against policy + the project's §47 taxonomy."""
    from ..insight_actions import ACTION_SPECS

    params = params or {}
    spec = ACTION_SPECS.get(action_type, {})
    if spec.get("external_side_effect"):
        return True
    if action_type in ("set_price", "markdown_ladder", "set_prices_bulk", "bundle_campaign", "flash_sale",
                       "threshold_campaign", "reorder_note", "reorder_point", "create_purchase_order"):
        return True
    if action_type in ("set_min_stock", "set_min_stock_bulk", "note", "shelf_note", "create_task",
                       "tag_customers", "set_setting"):
        return not bool(get_value(db, "auto_approve_low_risk", True))
    if "percent" in params:
        try:
            return check_discount(db, float(params["percent"])).requires_approval
        except (TypeError, ValueError):
            return True
    return True


def summarise(db: Session) -> list[dict]:
    """For the Settings screen (§92): every policy with its current value."""
    return list(all_policies(db).values())
