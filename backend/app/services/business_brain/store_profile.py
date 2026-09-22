"""v4.0 — Store Profile («فروشگاه من کیست؟»).

Every decision the brain takes is interpreted through this profile (§12). The
profile is deliberately split in two:

* **Declared** — what the owner says (business type, risk tolerance, pricing
  strategy, operating hours …). Stored in ``system_settings`` under
  ``brain.profile.*`` so it survives the same backup/restore path as every
  other setting and needs no migration.
* **Observed** — what the data says (average basket, customer count, turnover,
  seasonality index, share of credit sales). Computed from real rows, cached
  with a short TTL, and *never* overwritten by the declared side: the owner may
  say "we are a neighbourhood store", the data may say "your basket is 3× the
  neighbourhood average", and both facts matter.

Nothing here calls a language model. The profile is the context the model is
*given*, never something it invents.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ...models import Customer, Invoice, Product, SystemSetting
from . import persian as fa

SETTING_PREFIX = "brain.profile."

#: declared fields with their Persian label + default. A value of ``None``
#: means "not declared yet" — the brain then falls back to the data-driven
#: default instead of pretending the owner said something.
FIELDS: dict[str, dict] = {
    "business_type": {"label": "نوع کسب‌وکار", "default": "سوپرمارکت محله",
                      "options": ["سوپرمارکت محله", "هایپر", "فروشگاه زنجیره‌ای", "سوپرمارکت آنلاین", "عمده‌فروشی"]},
    "store_size": {"label": "متراژ/اندازه", "default": "متوسط", "options": ["کوچک", "متوسط", "بزرگ"]},
    "location": {"label": "موقعیت", "default": ""},
    "customer_profile": {"label": "پروفایل مشتری", "default": "خانواده‌های محله"},
    "pricing_strategy": {"label": "راهبرد قیمت‌گذاری", "default": "رقابتی با حاشیهٔ سالم",
                         "options": ["اقتصادی", "رقابتی با حاشیهٔ سالم", "پریمیوم"]},
    "discount_policy": {"label": "سیاست تخفیف", "default": "تخفیف فقط برای کالای کند-فروش یا نزدیک انقضا"},
    "risk_tolerance": {"label": "تحمل ریسک", "default": "متوسط", "options": ["محافظه‌کار", "متوسط", "پیشرو"]},
    "supplier_policy": {"label": "سیاست تأمین‌کننده", "default": "تنوع تأمین‌کننده، اولویت به اعتبار طولانی‌تر"},
    "payment_policy": {"label": "سیاست پرداخت", "default": "پرداخت نقدی برای تخفیف خرید، چک برای مبالغ بزرگ"},
    "inventory_policy": {"label": "سیاست موجودی", "default": "حداقل موجودی برای کالای پرفروش، سفارش کوتاه و مکرر"},
    "owner_preferences": {"label": "ترجیحات صاحب فروشگاه", "default": ""},
    "operating_hours": {"label": "ساعات کاری", "default": "۸ صبح تا ۲۳"},
    "seasonality": {"label": "فصلی بودن", "default": "متعادل"},
    "store_layout": {"label": "چیدمان", "default": ""},
    "employee_roles": {"label": "نقش کارکنان", "default": ""},
    "min_cash_reserve": {"label": "کف نقدینگی نگه‌داشته‌شده (تومان)", "default": 0, "type": "money"},
}


@dataclass
class StoreProfile:
    declared: dict = field(default_factory=dict)
    observed: dict = field(default_factory=dict)
    source: str = "default"

    def to_dict(self) -> dict:
        return asdict(self)

    def digest(self) -> str:
        """Short Persian text for prompts and the UI header."""
        d, o = self.declared, self.observed
        bits = [f"نوع: {d.get('business_type')}", f"راهبرد قیمت: {d.get('pricing_strategy')}",
                f"تحمل ریسک: {d.get('risk_tolerance')}"]
        if o.get("avg_basket"):
            bits.append(f"میانگین سبد: {fa.money(o['avg_basket'])}")
        if o.get("credit_share_pct") is not None:
            bits.append(f"سهم فروش اعتباری: {fa.fa_num(o['credit_share_pct'], 1)}٪")
        if o.get("active_customers"):
            bits.append(f"مشتری فعال: {fa.fa_num(o['active_customers'])}")
        return " · ".join(bits)


def _get_setting(db: Session, key: str, default: str = "") -> str:
    row = db.execute(select(SystemSetting).where(SystemSetting.key == key)).scalar_one_or_none()
    return row.value if row else default


def _set_setting(db: Session, key: str, value: str, description: str = "business brain profile") -> None:
    row = db.execute(select(SystemSetting).where(SystemSetting.key == key)).scalar_one_or_none()
    if row:
        row.value = value
    else:
        db.add(SystemSetting(key=key, value=value, description=description, is_secret=False))
    db.flush()


def load_declared(db: Session) -> dict:
    out: dict = {}
    for key, spec in FIELDS.items():
        raw = _get_setting(db, SETTING_PREFIX + key, "")
        if raw == "":
            out[key] = spec["default"]
            continue
        try:
            out[key] = json.loads(raw)
        except ValueError:
            out[key] = raw
    return out


def save_declared(db: Session, values: dict) -> dict:
    for key, value in (values or {}).items():
        if key not in FIELDS:
            continue
        _set_setting(db, SETTING_PREFIX + key, json.dumps(value, ensure_ascii=False))
    return load_declared(db)


def observe(db: Session, *, days: int = 90, today=None) -> dict:
    """Data-driven half of the profile. Deterministic, cheap, honest about gaps."""
    from ...models import InvoiceItem
    from ..timeservice import local_now

    now = local_now()
    since = now.replace(tzinfo=None) - __import__("datetime").timedelta(days=days)
    paid = [Invoice.status == "PAID", Invoice.created_at >= since]
    row = db.execute(select(func.count(Invoice.id), func.coalesce(func.sum(Invoice.total_amount), 0),
                            func.coalesce(func.avg(Invoice.total_amount), 0)).where(*paid)).one()
    invoices, revenue, basket = int(row[0] or 0), float(row[1] or 0), float(row[2] or 0)
    credit = db.execute(select(func.count(Invoice.id)).where(*paid, Invoice.payment_method == "ACCOUNT")).scalar_one() \
        if invoices else 0
    items = db.execute(select(func.count(InvoiceItem.id)).join(Invoice, Invoice.id == InvoiceItem.invoice_id)
                       .where(*paid)).scalar_one()
    customers = db.execute(select(func.count(Customer.id)).where(Customer.is_active == True)).scalar_one()  # noqa: E712
    products = db.execute(select(func.count(Product.id)).where(Product.is_active == True,  # noqa: E712
                                                               Product.deleted_at.is_(None))).scalar_one()
    by_hour = db.execute(select(func.strftime("%H", Invoice.created_at), func.count(Invoice.id))
                         .where(*paid).group_by(func.strftime("%H", Invoice.created_at))).all() \
        if db.bind.dialect.name == "sqlite" else []
    peak_hours = sorted(((int(h), int(c)) for h, c in by_hour if h is not None), key=lambda x: -x[1])[:3]
    return {
        "window_days": days,
        "invoices": invoices,
        "revenue": round(revenue),
        "avg_basket": round(basket),
        "lines_per_invoice": round(float(items) / invoices, 2) if invoices else 0.0,
        "credit_share_pct": round(100.0 * credit / invoices, 1) if invoices else 0.0,
        "active_customers": int(customers),
        "active_products": int(products),
        "peak_hours": [h for h, _ in peak_hours],
        "data_confidence": "high" if invoices >= 120 else ("medium" if invoices >= 20 else "low"),
        "sampled_at": now.isoformat(),
    }


def load(db: Session, *, days: int = 90) -> StoreProfile:
    return StoreProfile(declared=load_declared(db), observed=observe(db, days=days), source="merged")


def reserve_floor(db: Session) -> float:
    """Minimum cash the owner wants to keep — used by every cash decision."""
    prof = load_declared(db)
    try:
        return float(prof.get("min_cash_reserve") or 0)
    except (TypeError, ValueError):
        return 0.0
