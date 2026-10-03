# -*- coding: utf-8 -*-
"""build-488 — داشبورد پویا و مبتنی بر Widget (§۴–۱۳).

فرمول: **Dashboard = Roles + Permissions + User Context + Widgets + Personalization**

- کاتالوگ Widgetها با «الزام دسترسی» — UI هرگز از Role تصمیم نمی‌گیرد (§۳)؛
  فقط Permission مشخص می‌کند چه Widgetهایی مجازند (§۷: دیدن ≠ ایجاد/ویرایش).
- چندنقشی: اجتماع Widgetهای همهٔ نقش‌ها (§۶) — یک نقش، نقش دیگر را حذف نمی‌کند.
- شخصی‌سازی (§۸): افزودن/حذف/جابه‌جایی/اندازه/Pin — فقط در محدودهٔ مجاز؛
  فعال‌کردن Widget غیرمجاز در `save_layout` رد می‌شود.
- دادهٔ هیچ Widgetای اینجا ساخته نمی‌شود (§۵۲) — منبع داده، همان payload های
  موجود (reports.dashboard / performance / insights) است؛ این سرویس فقط
  «چه چیزی، با چه ترتیبی، برای چه کسی» را تعیین می‌کند (One Source of Truth).
"""
from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import User, UserWidgetLayout
from ..security import has_permission

#: گروه‌های نمایشی (§۵)
GROUPS_FA: dict[str, str] = {
    "sales": "فروش",
    "cash": "صندوق",
    "inventory": "انبار",
    "intelligence": "هوش فروشگاه",
    "performance": "عملکرد",
    "management": "مدیریت",
}

#: کاتالوگ Widgetها: requires = همهٔ این دسترسی‌ها باید باشند (§۷)
WIDGETS: dict[str, dict] = {
    "sales.my_today": {"title": "داشبورد من (فروش/شیفت/عملکرد)", "group": "sales", "icon": "receipt",
                       "requires": [], "card": ".og-mine"},
    "sales.today": {"title": "فروش امروز", "group": "sales", "icon": "trend",
                    "requires": ["reports.view"], "card": ".og-kpis"},
    "sales.trend": {"title": "روند فروش", "group": "sales", "icon": "trend",
                    "requires": ["reports.view"], "card": ".og-trend"},
    "sales.daily": {"title": "گزارش فروش روزانه", "group": "sales", "icon": "chart",
                    "requires": ["reports.view"], "card": ".og-daily"},
    "sales.invoices": {"title": "فاکتورهای اخیر", "group": "sales", "icon": "receipt",
                       "requires": ["reports.view"], "card": ".og-inv"},
    "sales.top": {"title": "محصولات پرفروش", "group": "sales", "icon": "star",
                  "requires": ["reports.view"], "card": ".dcard-top"},
    "sales.campaigns": {"title": "جشنواره‌ها و تخفیف‌های فعال", "group": "sales", "icon": "megaphone",
                        "requires": ["reports.view"], "card": ""},
    "cash.avg_invoice": {"title": "میانگین فاکتور", "group": "cash", "icon": "receipt",
                         "requires": ["reports.view"], "card": ".dcard-gauge"},
    "cash.session": {"title": "عملیات صندوق", "group": "cash", "icon": "cash",
                     "requires": ["pos.sell"], "card": ""},
    "inv.stocktake": {"title": "موجودی در قفسه", "group": "inventory", "icon": "box",
                      "requires": ["inventory.view"], "card": ""},
    "inv.low_stock": {"title": "کالاهای کم‌موجودی", "group": "inventory", "icon": "box",
                      "requires": ["inventory.view"], "card": ".dcard-low"},
    "inv.slow": {"title": "کالاهای بدون گردش", "group": "inventory", "icon": "box",
                 "requires": ["inventory.view"], "card": ""},
    "inv.stocktake_op": {"title": "عملیات انبارگردانی", "group": "inventory", "icon": "clipboard",
                         "requires": ["inventory.stocktake"], "card": ""},
    "ai.suggestions": {"title": "پیشنهادهای هوشمند", "group": "intelligence", "icon": "ai",
                       "requires": ["reports.view"], "card": ".og-sug"},
    "ai.line": {"title": "نوار هوش فروشگاه", "group": "intelligence", "icon": "ai",
                "requires": ["reports.view"], "card": ".ai-line"},
    "perf.my": {"title": "عملکرد و امتیاز من", "group": "performance", "icon": "target",
                "requires": ["performance.view"], "card": ""},
    "perf.shifts": {"title": "شیفت‌های امروز", "group": "performance", "icon": "clock",
                    "requires": ["shifts.view"], "card": ""},
    "mgmt.staff": {"title": "عملکرد کارکنان", "group": "management", "icon": "users",
                   "requires": ["performance.view_all"], "card": ""},
    "mgmt.pnl": {"title": "سود و زیان", "group": "management", "icon": "chart",
                 "requires": ["pricing.view_cost"], "card": ".dcard-acc"},
    "mgmt.payroll": {"title": "حقوق و مزایا", "group": "management", "icon": "cash",
                     "requires": ["payroll.view"], "card": ""},
    "mgmt.announcements": {"title": "اطلاعیه‌ها", "group": "management", "icon": "megaphone",
                           "requires": ["announcements.publish"], "card": ""},
    "mgmt.expiry": {"title": "هشدار انقضا", "group": "inventory", "icon": "clock",
                    "requires": ["inventory.view"], "card": ".dcard-expiry"},
    "mgmt.receivables": {"title": "مطالبات و بدهی", "group": "management", "icon": "cash",
                         "requires": ["reports.view"], "card": ".dcard-recv"},
    "mgmt.sms": {"title": "وضعیت پیامک", "group": "management", "icon": "megaphone",
                 "requires": ["settings.manage"], "card": ".dcard-sms"},
    "mgmt.system": {"title": "سلامت سیستم", "group": "management", "icon": "target",
                    "requires": ["settings.manage"], "card": ".dcard-sys"},
    "mgmt.price_conflict": {"title": "تعارض قیمت", "group": "management", "icon": "warning",
                            "requires": ["pricing.manage"], "card": ".dcard-price"},
    "sales.transactions": {"title": "تراکنش‌های اخیر", "group": "sales", "icon": "receipt",
                           "requires": ["reports.view"], "card": ".dcard-recent"},
}

DEFAULT_ORDER: list[str] = list(WIDGETS.keys())


class WidgetError(Exception):
    def __init__(self, code: str, message: str = ""):
        self.code = code
        super().__init__(message or code)


def allowed_widgets(user: User) -> list[str]:
    """Widgetهای مجاز این کاربر = اجتماع نقش‌ها + دسترسی‌های مستقیم (§۶–۷)."""
    out = []
    for wid, meta in WIDGETS.items():
        if all(has_permission(user, code) for code in meta["requires"]):
            out.append(wid)
    return out


def _layout(user_id: int, db: Session) -> dict:
    row = db.execute(select(UserWidgetLayout).where(
        UserWidgetLayout.user_id == user_id)).scalar_one_or_none()
    if row is None:
        return {}
    try:
        v = json.loads(row.layout or "{}")
        return v if isinstance(v, dict) else {}
    except Exception:
        return {}


def compose(db: Session, user: User) -> dict:
    """چیدمان نهایی داشبورد کاربر: گروه‌ها + Widgetهای مجاز + شخصی‌سازی."""
    allowed = allowed_widgets(user)
    allowed_set = set(allowed)
    lay = _layout(user.id, db)
    order = [w for w in lay.get("order", []) if w in allowed_set]
    order += [w for w in DEFAULT_ORDER if w in allowed_set and w not in order]
    hidden = {w for w in lay.get("hidden", []) if w in allowed_set}
    pinned = [w for w in lay.get("pinned", []) if w in allowed_set and w not in hidden]
    sizes = {k: v for k, v in (lay.get("sizes") or {}).items() if k in allowed_set}
    # Pin شده‌ها اول، بعد بقیه به ترتیب کاربر
    final = pinned + [w for w in order if w not in pinned]
    groups: dict[str, list] = {}
    for wid in final:
        if wid in hidden:
            continue
        meta = WIDGETS[wid]
        groups.setdefault(meta["group"], []).append({
            "id": wid, "title": meta["title"], "icon": meta["icon"],
            "card": meta["card"], "size": sizes.get(wid, "md"),
            "pinned": wid in pinned,
        })
    return {
        "groups": [{"id": g, "title": GROUPS_FA.get(g, g), "widgets": ws}
                   for g, ws in groups.items() if ws],
        "all_allowed": [{"id": w, "title": WIDGETS[w]["title"], "group": WIDGETS[w]["group"],
                         "group_title": GROUPS_FA.get(WIDGETS[w]["group"], WIDGETS[w]["group"]),
                         "card": WIDGETS[w]["card"],
                         "hidden": w in hidden, "pinned": w in pinned,
                         "size": sizes.get(w, "md")}
                        for w in allowed],
        # build-489 — کارت‌هایی که کاربر به Widget آن‌ها دسترسی ندارد باید واقعاً مخفی
        # شوند (باگ مالک: داشبورد صندوق‌دار مثل مدیر بود). کلاینت این سلکتورها را می‌بندد.
        "hide_cards": sorted({WIDGETS[w]["card"] for w in WIDGETS
                              if w not in allowed_set and WIDGETS[w]["card"]}),
        "personalization": True,
    }


def save_layout(db: Session, user: User, *, order: list[str] | None = None,
                pinned: list[str] | None = None, hidden: list[str] | None = None,
                sizes: dict | None = None) -> dict:
    """ذخیرهٔ چیدمان — Widget غیرمجاز رد می‌شود (§۸: «فعال‌کردن Widget غیرمجاز ممنوع»)."""
    allowed = set(allowed_widgets(user))
    for label, items in (("order", order or []), ("pinned", pinned or []),
                         ("hidden", hidden or [])):
        bad = [w for w in items if w not in allowed and w not in WIDGETS]
        unauthorized = [w for w in items if w in WIDGETS and w not in allowed]
        if bad:
            raise WidgetError("UNKNOWN_WIDGET", f"Widget ناشناخته: {bad}")
        if unauthorized:
            raise WidgetError("FORBIDDEN_WIDGET",
                              f"این Widgetها خارج از محدودهٔ دسترسی شما هستند: {unauthorized}")
    sizes = {k: v for k, v in (sizes or {}).items() if k in allowed}
    for v in sizes.values():
        if v not in ("sm", "md", "lg"):
            raise WidgetError("BAD_SIZE", f"اندازهٔ نامعتبر: {v}")
    row = db.execute(select(UserWidgetLayout).where(
        UserWidgetLayout.user_id == user.id)).scalar_one_or_none()
    payload = json.dumps({"order": order or [], "pinned": pinned or [],
                          "hidden": hidden or [], "sizes": sizes}, ensure_ascii=False)
    now = datetime.utcnow()
    if row is None:
        row = UserWidgetLayout(user_id=user.id, layout=payload, updated_at=now)
        db.add(row)
    else:
        row.layout = payload
        row.updated_at = now
    db.commit()
    return compose(db, user)
