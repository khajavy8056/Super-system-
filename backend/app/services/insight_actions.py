"""v3.0 — executes the actions attached to an accepted insight.

Every action goes through the *same* service layer the UI uses (campaigns,
coupons, SMS queue, price versions, batch prices, notifications, audit), so an
accepted suggestion is indistinguishable from a manager doing it by hand — and
fully visible in the audit log (action ``INSIGHT_ACTION``).
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import (Campaign, Coupon, Customer, Insight, Invoice, InvoiceItem, Product, ProductBatch,
                      StockMovement, SystemSetting, User)
from . import coupons as coupon_svc
from . import sms as sms_svc
from .audit import write_audit
from .notifications import notify

log = logging.getLogger("supermarket.insights.actions")


def _ref(owner) -> tuple[str, int]:
    """(reference_type, reference_id) for every row an action creates (notification,
    SMS, audit).

    v3.x passes an ``Insight``; v4.0 passes a Business-Brain ``ActionOwner``. The
    reference type travels with the owner so a Brain-executed action's SMS rows
    can never be mistaken for an insight's (ids are counted per reference type
    during VERIFY, and a colliding id would silently validate the wrong rows).
    """
    return (str(getattr(owner, "reference_type", "Insight")), int(owner.id))


def _now() -> datetime:
    from . import insights as _ins
    return _ins._now()


def _setting(db: Session, key: str, default: str = "") -> str:
    row = db.execute(select(SystemSetting).where(SystemSetting.key == key)).scalar_one_or_none()
    return row.value if row else default


def _set_setting(db: Session, key: str, value: str) -> None:
    row = db.execute(select(SystemSetting).where(SystemSetting.key == key)).scalar_one_or_none()
    if row:
        row.value = value
    else:
        db.add(SystemSetting(key=key, value=value, description="set by store intelligence", is_secret=False))
    db.flush()


def _store(db: Session) -> str:
    return _setting(db, "store.name", "فروشگاه")


def _fa(n) -> str:
    return f"{int(round(float(n))):,}".translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹"))


def _sms_enabled(db: Session) -> bool:
    return bool(_setting(db, "sms.provider", ""))


# ------------------------------------------------------------------ individual actions
def act_shelf_note(db, insight, p, user):
    names = [pr.name for pr in db.execute(select(Product).where(Product.id.in_(p.get("products", [])))).scalars()]
    notify(db, type="INSIGHT_TASK", title="کار انبار: تغییر چیدمان", body="این کالاها را کنار هم بچینید: " + "، ".join(names),
           severity="INFO", reference_type=_ref(insight)[0], reference_id=_ref(insight)[1])
    return {"note": names}


def act_reorder_note(db, insight, p, user):
    ids = p.get("products") or ([p["product_id"]] if p.get("product_id") else [])
    names = {pr.id: pr.name for pr in db.execute(select(Product).where(Product.id.in_(ids))).scalars()}
    lst = json.loads(_setting(db, "insights.reorder_list", "[]"))
    for pid in ids:
        if not any(x["product_id"] == pid for x in lst):
            lst.append({"product_id": pid, "name": names.get(pid, str(pid)), "qty": p.get("qty"), "added": _now().isoformat(), "insight_id": insight.id})
    _set_setting(db, "insights.reorder_list", json.dumps(lst, ensure_ascii=False))
    notify(db, type="INSIGHT_TASK", title="به لیست سفارش اضافه شد", body="، ".join(names.values()), severity="INFO", reference_type=_ref(insight)[0], reference_id=_ref(insight)[1])
    # v4.8.0 — شناسهٔ کالاهایی که این اقدام در فهرست گذاشت، تا بازبینی بعدی روی
    # «همان کالاها» بررسی کند و با هر خط جدیدِ بینش‌های دیگر، دروغ هشدار ندهد.
    # build-481 (step 1) — مسیر اجرای واقعی: بعد از «اجرا کن»، فرم ورود کالا با
    # همین محصولات از پیش انتخاب می‌شود؛ مدیر مقدار را وارد می‌کند، Batch واقعی
    # ثبت می‌شود، موجودی بالا می‌رود و بازبینی بعدی خودکار پیشنهاد را می‌بندد.
    return {"reorder_list": len(lst), "added_ids": [int(x) for x in ids],
            "navigate": {"screen": "inventory_receive", "product_ids": [int(x) for x in ids]}}


def act_set_min_stock(db, insight, p, user):
    pr = db.get(Product, p["product_id"])
    if not pr:
        return {"skipped": "product"}
    before = pr.min_stock_alert
    pr.min_stock_alert = int(p["min_stock"])
    write_audit(db, action="INSIGHT_ACTION", user_id=user.id if user else None, entity_type="Product", entity_id=pr.id,
                before={"min_stock_alert": before}, after={"min_stock_alert": pr.min_stock_alert})
    return {"min_stock_alert": pr.min_stock_alert}


def act_set_price(db, insight, p, user):
    b = db.get(ProductBatch, p["batch_id"])
    if not b:
        return {"skipped": "batch"}
    # v3.6.1 — hard stop. The ceiling is enforced HERE rather than only in the analyzers, so an
    # insight written by an older version, or by an analyzer with a bug, still cannot push a
    # price above the printed consumer price into the database.
    from . import pricing_law
    new_price = pricing_law.guard_sell_price(b, float(p["sell_price"]))
    before = float(b.sell_price)
    b.sell_price = Decimal(str(new_price))
    try:
        from . import pricing
        pricing.set_price(db, product=b.product, price_type="SELL", price=b.sell_price, user=user, source="insight", note=f"insight #{insight.id}")
    except Exception:  # pricing history is best-effort
        log.debug("price version not recorded", exc_info=True)
    write_audit(db, action="INSIGHT_ACTION", user_id=user.id if user else None, entity_type="ProductBatch", entity_id=b.id,
                before={"sell_price": before}, after={"sell_price": float(b.sell_price)})
    return {"sell_price": float(b.sell_price)}


def act_markdown_ladder(db, insight, p, user):
    """Apply the first step now; store the ladder so later steps land on their dates.

    v4.8.0 — the action reports exactly what it did: which step was applied, the
    old/new price, and the remaining timeline (so the UI can show «اجرا شد —
    پلهٔ بعدی از ۱۴۰۵/۰۷/۱۲» instead of a vague «انجام شد»).
    """
    b = db.get(ProductBatch, p["batch_id"])
    if not b:
        return {"skipped": "batch"}
    ladder = json.loads(json.dumps(p["ladder"]))     # defensive copy (persisted JSON)
    ladder.sort(key=lambda s: int(s.get("from_day", 0)))
    base_price = float(b.sell_price)
    plan = {"batch_id": b.id, "product_id": b.product_id, "base_price": base_price,
            "start": _now().date().isoformat(), "ladder": ladder, "applied": [],
            "applied_dates": [], "insight_id": getattr(insight, "id", None),
            "label": getattr(b.product, "name", None) or str(b.id)}
    plans = json.loads(_setting(db, "insights.markdown_plans", "[]"))
    plans = [x for x in plans if x["batch_id"] != b.id] + [plan]
    _set_setting(db, "insights.markdown_plans", json.dumps(plans, ensure_ascii=False))
    changed = apply_markdown_steps(db)               # applies due steps (step 0 = today)
    stored = next((x for x in json.loads(_setting(db, "insights.markdown_plans", "[]")) if x["batch_id"] == b.id), plan)
    return {"plan": stored, "applied_now": changed, "sell_price": float(b.sell_price),
            "base_price": base_price, "ladder_steps": len(ladder)}


def apply_markdown_steps(db: Session) -> int:
    """Move batches down the ladder on their due days; never below buy price.

    Called by the insights worker every 15 minutes **and** right before every
    checkout (§v4.8.0), so a shop that turned the background worker off still
    sells at the step that is due today — an accepted discount that never
    reaches the till is worse than no discount at all.

    Each step is identified by its index (not by its percent) so two steps with
    the same percentage are both applied, and every change writes a price
    version + audit row exactly like a manual price change.
    """
    plans = json.loads(_setting(db, "insights.markdown_plans", "[]"))
    today = _now().date()
    changed, keep = 0, []
    for plan in plans:
        b = db.get(ProductBatch, plan["batch_id"])
        if not b:
            continue                     # the batch row itself is gone → nothing to verify
        start = datetime.fromisoformat(plan.get("start") or today.isoformat()).date()
        day = (today - start).days
        applied = list(plan.get("applied") or [])
        due_idx = [i for i, s in enumerate(plan["ladder"]) if int(s.get("from_day", 0)) <= day]
        target = max(due_idx) if due_idx else -1
        if target >= 0 and str(target) not in applied:
            step = plan["ladder"][target]
            percent = float(step.get("percent", 0))
            new_price = round(float(plan["base_price"]) * (1 - percent / 100) / 100) * 100
            floor = float(b.buy_price or 0) * 1.01
            new_price = max(new_price, floor)
            before = float(b.sell_price)
            b.sell_price = Decimal(str(round(new_price)))
            b.discount = Decimal(str(max(0, round(float(plan["base_price"]) - new_price))))
            applied.append(str(target))
            plan["applied"] = applied
            plan.setdefault("applied_dates", []).append({"step": target + 1, "percent": percent,
                                                         "date": today.isoformat(), "price": float(b.sell_price)})
            try:   # price history, exactly like a manual change
                from . import pricing
                pricing.set_price(db, product=b.product, price_type="SELL", price=b.sell_price,
                                  user=None, source="insight", note=f"markdown step {percent}% plan#{plan.get('insight_id')}")
            except Exception:  # best-effort: never block the discount
                log.debug("price version not recorded", exc_info=True)
            write_audit(db, action="INSIGHT_ACTION", entity_type="ProductBatch", entity_id=b.id,
                        before={"sell_price": before},
                        after={"sell_price": float(b.sell_price), "ladder_step": percent, "step_index": target + 1})
            notify(db, type="INSIGHT_TASK", title=f"تخفیف پله‌ای {_fa(percent)}٪ اعمال شد",
                   body=f"{b.product.name} — قیمت جدید {_fa(new_price)} تومان (پلهٔ {_fa(percent)}٪ از {start.isoformat()})",
                   severity="INFO", reference_type="ProductBatch", reference_id=b.id)
            changed += 1
        if b.expiry_date and b.expiry_date < today and not plan.get("closed"):
            notify(db, type="INSIGHT_TASK", title="برنامهٔ تخفیف به پایان رسید",
                   body=f"{b.product.name}: تاریخ انقضا گذشت و {_fa(b.current_qty)} عدد در انبار مانده؛ "
                        f"تخفیف متوقف شد — این بچ باید ضایعات ثبت شود.",
                   severity="WARN", reference_type="ProductBatch", reference_id=b.id)
            plan["closed"] = today.isoformat()      # once, then stay quiet
        if len(plan.get("applied") or []) >= len(plan["ladder"]):
            # v4.8.0 — پلان تمام‌شده **حذف نمی‌شود**: بازبینی («آیا اثرش هست؟») و
            # گزارش اقدام‌ها به آن نیاز دارند. قبلاً پلانِ یک‌پله‌ای همان لحظه
            # پاک می‌شد و verify می‌گفت «برنامه گم شد» — یعنی اقدام سالم،
            # اما گزارش دروغِ خرابی می‌داد.
            plan.setdefault("completed", today.isoformat())
        keep.append(plan)
    _set_setting(db, "insights.markdown_plans", json.dumps(keep, ensure_ascii=False))
    db.flush()
    return changed


def act_write_off_waste(db, insight, p, user):
    """v4.8.0 — «ثبت ضایعات» واقعی: کالای تاریخ‌گذشته از موجودی فروشنی بیرون می‌رود.

    گزارش مالک «محصول صفر روز مانده عملاً فاسد شده بود». وقتی پیشنهاد با تأخیر
    برسد، تنها کار صادقانه ثبت ضایعات است — نه تخفیف روی کالای تاریخ‌گذشته.
    این اقدام از همان سرویس انبار (``inventory.record_waste``) استفاده می‌کند،
    پس حرکت WASTE و ردیف حسابرسی و اصلاح موجودی مثل کار دستیِ انباردار است.
    """
    from . import inventory as inv
    b = db.get(ProductBatch, p["batch_id"])
    if not b:
        return {"skipped": "batch"}
    qty = p.get("qty")
    qty = float(qty) if qty is not None else float(b.current_qty)
    qty = min(qty, float(b.current_qty))
    if qty <= 0:
        return {"skipped": "empty"}
    before = float(b.current_qty)
    inv.record_waste(db, batch=b, qty=qty, user=user, reason=p.get("reason") or "Expired stock (store intelligence)")
    return {"batch_id": b.id, "wasted": qty, "before_qty": before, "after_qty": float(b.current_qty)}


def _coupon(db, *, code_prefix: str, customer: Customer, percent: int, days: int, campaign_id: int | None, user):
    code = coupon_svc.generate_code(prefix=code_prefix)
    c = Coupon(code=code, campaign_id=campaign_id, customer_id=customer.id, customer_phone=customer.phone, discount_type="PERCENT",
               discount_value=Decimal(percent), min_purchase=Decimal(0), valid_from=_now(),
               valid_until=_now() + timedelta(days=days), usage_limit=1, status="ACTIVE", created_by=user.id if user else None)
    db.add(c)
    db.flush()
    return c


def _campaign(db, name: str, percent: int, days: int, user, description: str, owner=None) -> Campaign:
    """Create the campaign this action promises — or hand back the one it already made.

    build-481 (step 35): executing the same action twice must never leave two
    live festivals granting the same benefit.  When the owner already created
    this campaign (same source insight + name, still active), that row is
    returned instead — the second «اجرا» is a verified no-op, not a twin.
    """
    src_id = getattr(owner, "id", None) if getattr(owner, "reference_type", "Insight") == "Insight" else None
    if src_id is not None:
        existing = db.execute(
            select(Campaign).where(Campaign.source_insight_id == src_id,
                                   Campaign.name == name,
                                   Campaign.status == "ACTIVE")
        ).scalars().first()
        if existing is not None:
            return existing
    c = Campaign(name=name, description=description, discount_type="PERCENT", discount_value=Decimal(percent), min_purchase=Decimal(0),
                 valid_from=_now(), valid_until=_now() + timedelta(days=days), status="ACTIVE",
                 source_insight_id=src_id,
                 created_by=user.id if user else None)
    db.add(c)
    db.flush()
    write_audit(db, action="INSIGHT_ACTION", user_id=user.id if user else None, entity_type="Campaign", entity_id=c.id, after={"name": name})
    return c


def act_vip_coupons(db, insight, p, user):
    camp = _campaign(db, "باشگاه VIP", p["percent"], p["days"], user, "کوپن ماهانهٔ مشتریان برتر — ساخته‌شده توسط هوش فروشگاه", owner=insight)
    sent = issued = 0
    for cust in db.execute(select(Customer).where(Customer.id.in_(p["customer_ids"]))).scalars():
        c = _coupon(db, code_prefix="VIP", customer=cust, percent=p["percent"], days=p["days"], campaign_id=camp.id, user=user)
        issued += 1
        if cust.phone and _sms_enabled(db):
            sms_svc.queue_sms(db, phone=cust.phone, text=f"{cust.name} عزیز، شما مشتری ویژهٔ {_store(db)} هستید. کد {c.code} = {p['percent']}٪ تخفیف تا {p['days']} روز. با سپاس از همراهی‌تان.",
                              reference_type=_ref(insight)[0], reference_id=_ref(insight)[1])
            sent += 1
    sms_svc.kick_worker()
    return {"campaign_id": camp.id, "coupons": issued, "sms": sent}


def act_winback_sms(db, insight, p, user):
    camp = _campaign(db, "بازگشت مشتری", p["percent"], p["days"], user, "کوپن بازگشت برای مشتریان غایب — هوش فروشگاه", owner=insight)
    sent = issued = 0
    for cust in db.execute(select(Customer).where(Customer.id.in_(p["customer_ids"]))).scalars():
        c = _coupon(db, code_prefix="BACK", customer=cust, percent=p["percent"], days=p["days"], campaign_id=camp.id, user=user)
        issued += 1
        if cust.phone and _sms_enabled(db):
            sms_svc.queue_sms(db, phone=cust.phone, text=f"{cust.name} عزیز، دلمان برایتان تنگ شده! {_store(db)} با کد {c.code} {p['percent']}٪ تخفیف تا {p['days']} روز منتظر شماست.",
                              reference_type=_ref(insight)[0], reference_id=_ref(insight)[1])
            sent += 1
    sms_svc.kick_worker()
    return {"campaign_id": camp.id, "coupons": issued, "sms": sent}


def act_visit_sms(db, insight, p, user):
    """v3.2 — personal «your usual item» reminder to the customers whose visit is due."""
    sent = 0
    if not _sms_enabled(db):
        return {"sms": 0, "skipped": "sms_disabled"}
    for row in p.get("customers", []):
        cust = db.get(Customer, _row_id(row))
        if not cust or not cust.phone:
            continue
        item = (row.get("item") or "").strip()
        txt = (f"{cust.name} عزیز، {_store(db)}: " + (f"«{item}» تازه رسیده و برایتان کنار گذاشته‌ایم؛ " if item else "")
               + "منتظر دیدارتان هستیم.")
        sms_svc.queue_sms(db, phone=cust.phone, text=txt, reference_type=_ref(insight)[0], reference_id=_ref(insight)[1])
        sent += 1
    sms_svc.kick_worker()
    return {"sms": sent}


def act_sms_buyers(db, insight, p, user):
    pid = p["product_id"]
    since = _now() - timedelta(days=120)
    ids = {r[0] for r in db.execute(select(Invoice.customer_id).join(InvoiceItem, InvoiceItem.invoice_id == Invoice.id)
                                    .where(Invoice.status == "PAID", Invoice.created_at >= since, InvoiceItem.product_id == pid,
                                           Invoice.customer_id.is_not(None))).all()}
    pr = db.get(Product, pid)
    if not _sms_enabled(db):
        # v3.6.2 — used to return {"buyers": N, "sms": 0} with no explanation, which reads as
        # "done" in the UI. visit_sms already reported the reason; this must too.
        return {"buyers": len(ids), "sms": 0, "skipped": "sms_disabled"}
    sent = 0
    if _sms_enabled(db):
        for cust in db.execute(select(Customer).where(Customer.id.in_(list(ids)), Customer.phone.is_not(None))).scalars():
            sms_svc.queue_sms(db, phone=cust.phone, text=f"{cust.name} عزیز، «{pr.name if pr else 'کالای موردعلاقهٔ شما'}» این هفته در {_store(db)} با {p['percent']}٪ تخفیف. تا اتمام موجودی.",
                              reference_type=_ref(insight)[0], reference_id=_ref(insight)[1])
            sent += 1
        sms_svc.kick_worker()
    return {"buyers": len(ids), "sms": sent}


def act_bundle_campaign(db, insight, p, user):
    """build-481 — one source of truth for the promised discount (step 46).

    Before, the batch was silently marked down AND an inert festival row was
    created — two channels for one promise, neither of them showing «چرا تخفیف»
    at the till.  Now the campaign IS the discount: scoped to the dead-stock
    product, auto-applied at checkout, recorded on the invoice with its name so
    the receipt and the audit both say «باندل …».
    """
    pr = db.get(Product, p["product_id"])
    partner = db.get(Product, p["partner_id"]) if p.get("partner_id") else None
    name = f"باندل {pr.name if pr else ''}" + (f" + {partner.name}" if partner else "")
    camp = _campaign(db, name, p["percent"], 21, user, "باندل کالای راکد با کالای پرفروش — هوش فروشگاه", owner=insight)
    camp.target_type = "PRODUCTS"
    camp.target_ids = json.dumps([int(p["product_id"])] + ([int(p["partner_id"])] if p.get("partner_id") else []))
    camp.auto_apply = True
    db.flush()
    notify(db, type="INSIGHT_TASK", title="باندل ساخته شد",
           body=f"{name} — {p['percent']}٪ تخفیف روی کالای راکد؛ صندوق هنگام فروش همان کالا به‌صورت خودکار اعمال می‌کند. آن را کنار کالای پرفروش بچینید.",
           severity="INFO", reference_type="Campaign", reference_id=camp.id)
    return {"campaign_id": camp.id, "auto_applied": True, "target_products": camp.target_ids}


def act_flash_sale(db, insight, p, user):
    """build-481 — the festival must be applicable at the till, not just exist in a table.

    A flash sale is a *human* decision at the moment of sale (which basket, which
    customer), so it is offered to the cashier as a SELECTABLE campaign (§24)
    instead of silently discounting every basket in its window.  When the
    analyzer knows WHICH products the sale is about (``products`` param), the
    benefit is scoped to those lines.
    """
    camp = _campaign(db, "فروش ویژهٔ نقدینگی", p["percent"], p["days"], user, "فروش ویژهٔ کوتاه برای آزادسازی نقدینگی — هوش فروشگاه", owner=insight)
    if p.get("products"):
        camp.target_type = "PRODUCTS"
        camp.target_ids = json.dumps([int(x) for x in p["products"]])
    if p.get("min_purchase"):
        camp.min_purchase = Decimal(str(int(p["min_purchase"])))
    db.flush()
    notify(db, type="INSIGHT_TASK", title="فروش ویژه فعال شد",
           body=f"{p['days']} روز، {p['percent']}٪ تخفیف — صندوق‌دار هنگام فروش می‌تواند این جشنواره را انتخاب و اعمال کند (از بخش جشنواره قابل ویرایش است).",
           severity="INFO", reference_type="Campaign", reference_id=camp.id)
    return {"campaign_id": camp.id, "selectable_at_pos": True}


def act_debt_reminders(db, insight, p, user):
    from ..models import CustomerLedgerEntry
    from sqlalchemy import func
    sub = select(CustomerLedgerEntry.customer_id, func.max(CustomerLedgerEntry.id).label("mid")).group_by(CustomerLedgerEntry.customer_id).subquery()
    rows = db.execute(select(CustomerLedgerEntry).join(sub, CustomerLedgerEntry.id == sub.c.mid)).scalars().all()
    sent = 0
    n_debt = len([e for e in rows if float(e.balance_after) > 0])
    if not _sms_enabled(db):
        # v3.6.2 — same silent no-op that sms_buyers had: it reported the debtors it found
        # with sms=0 and no reason, which the UI reads as "reminders sent".
        return {"debtors": n_debt, "sms": 0, "skipped": "sms_disabled"}
    if _sms_enabled(db):
        for e in rows:
            if float(e.balance_after) > 0:
                cust = db.get(Customer, e.customer_id)
                if cust and cust.phone:
                    text = sms_svc.render_template(db, "debt_reminder", customer=cust.name, amount=_fa(e.balance_after))
                    sms_svc.queue_sms(db, phone=cust.phone, text=text, reference_type=_ref(insight)[0], reference_id=_ref(insight)[1])
                    sent += 1
        sms_svc.kick_worker()
    return {"debtors": n_debt, "sms": sent}


def act_enable_nudges(db, insight, p, user):
    _set_setting(db, "insights.pos_nudges", "true")
    return {"pos_nudges": True}


def act_pos_nudge(db, insight, p, user):
    _set_setting(db, "insights.pos_nudges", "true")
    extra = json.loads(_setting(db, "insights.manual_rules", "[]"))
    a, b = p["a"], p["b"]
    names = {pr.id: pr.name for pr in db.execute(select(Product).where(Product.id.in_([a, b]))).scalars()}
    for x, y in ((a, b), (b, a)):
        if not any(r["if"] == x and r["then"] == y for r in extra):
            extra.append({"if": x, "then": y, "if_name": names.get(x, ""), "then_name": names.get(y, ""), "confidence": 1.0, "lift": 1.0})
    _set_setting(db, "insights.manual_rules", json.dumps(extra, ensure_ascii=False))
    return {"rules": len(extra)}


def act_note(db, insight, p, user):
    notify(db, type="INSIGHT_TASK", title=insight.title, body=insight.body[:400], severity="WARN", reference_type=_ref(insight)[0], reference_id=_ref(insight)[1])
    return {"noted": True}


# ------------------------------------------------------------------ v3.5 PRO actions
def act_personal_sms(db, insight, p, user):
    """One *different* text per customer (the PRO analyzers write the message for each person)."""
    if not _sms_enabled(db):
        return {"sms": 0, "skipped": "sms_disabled"}
    sent = 0
    for row in p.get("customers", []):
        cust = db.get(Customer, _row_id(row))
        txt = (row.get("text") or "").strip()
        if not cust or not cust.phone or not txt:
            continue
        sms_svc.queue_sms(db, phone=cust.phone, text=txt, reference_type=_ref(insight)[0], reference_id=_ref(insight)[1])
        sent += 1
    sms_svc.kick_worker()
    return {"sms": sent}


def act_personal_coupons(db, insight, p, user):
    """Per-customer percent/days (+ optional personal text). One campaign groups them for the ROI report."""
    rows = p.get("customers", [])
    if not rows:
        return {"coupons": 0}
    pct = int(rows[0].get("percent", 5)); days = int(rows[0].get("days", 7))
    camp = _campaign(db, f"کوپن شخصی — {insight.title[:40]}", pct, days, user, f"کوپن‌های شخصی هوش فروشگاه (پیشنهاد #{insight.id})", owner=insight)
    issued = sent = 0
    for row in rows:
        cust = db.get(Customer, _row_id(row))
        if not cust:
            continue
        c = _coupon(db, code_prefix="ME", customer=cust, percent=int(row.get("percent", pct)), days=int(row.get("days", days)), campaign_id=camp.id, user=user)
        issued += 1
        if cust.phone and _sms_enabled(db):
            txt = row.get("text") or f"{cust.name} عزیز، کد {c.code} = {row.get('percent', pct)}٪ تخفیف شخصی شما در {_store(db)} تا {row.get('days', days)} روز آینده."
            sms_svc.queue_sms(db, phone=cust.phone, text=txt.replace("WELCOME۱۰", c.code).replace("VIP۵", c.code).replace("BACK۱۰", c.code), reference_type=_ref(insight)[0], reference_id=_ref(insight)[1])
            sent += 1
    sms_svc.kick_worker()
    return {"campaign_id": camp.id, "coupons": issued, "sms": sent}


def act_tag_customers(db, insight, p, user):
    """Append «#tag» markers to the customer's notes so the POS and the customer card show them."""
    n = 0
    for tag, ids in (p.get("tags") or {}).items():
        marker = f"#{tag}"
        for cust in db.execute(select(Customer).where(Customer.id.in_(list(ids)))).scalars():
            notes = cust.notes or ""
            if marker not in notes:
                cust.notes = (notes + " " + marker).strip()[:1000]
                n += 1
    return {"tagged": n}


def _row_id(row) -> int | None:
    """Customer id from a payload row, accepting either spelling.

    The executors used to read only ``row["customer_id"]`` and ``continue`` when it was absent,
    so a payload that said ``id`` produced ``ok: True`` with nothing changed — the shop presses
    «اجرا», sees a green tick, and no coupon exists. Accepting both makes that impossible.
    """
    if not isinstance(row, dict):
        return None
    v = row.get("customer_id", row.get("id"))
    try:
        return int(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def act_set_credit_limit(db, insight, p, user):
    n = 0
    rows = p.get("customers", [])
    for row in rows:
        cust = db.get(Customer, _row_id(row))
        if not cust:
            continue
        before = float(cust.credit_limit or 0)
        cust.credit_limit = Decimal(str(int(row["limit"])))
        write_audit(db, action="INSIGHT_ACTION", user_id=user.id if user else None, entity_type="Customer", entity_id=cust.id,
                    before={"credit_limit": before}, after={"credit_limit": float(cust.credit_limit)})
        n += 1
    # say so when rows were supplied but none of them matched a real customer
    return {"updated": n, **({"skipped": "no_matching_customers"} if rows and not n else {})}


def act_set_min_stock_bulk(db, insight, p, user):
    n = 0
    for it in p.get("items", []):
        pr = db.get(Product, it.get("product_id"))
        if not pr:
            continue
        before = pr.min_stock_alert
        pr.min_stock_alert = int(it["min_stock"])
        write_audit(db, action="INSIGHT_ACTION", user_id=user.id if user else None, entity_type="Product", entity_id=pr.id,
                    before={"min_stock_alert": before}, after={"min_stock_alert": pr.min_stock_alert})
        n += 1
    return {"updated": n}


def act_set_prices_bulk(db, insight, p, user):
    from .pricing_law import PriceLawError
    n = skipped = 0
    for it in p.get("items", []):
        # one illegal row must not abort the whole batch — skip it and say how many were skipped,
        # otherwise a 40-item rounding card fails entirely because of a single bad ceiling.
        try:
            r = act_set_price(db, insight, {"batch_id": it["batch_id"], "sell_price": it["sell_price"]}, user)
        except PriceLawError:
            skipped += 1
            continue
        n += 0 if r.get("skipped") else 1
    return {"updated": n, "skipped_over_consumer_price": skipped}


def act_threshold_campaign(db, insight, p, user):
    """build-481 (§21) — «خرید بالای X → تخفیف» must really reach the till.

    Before: the campaign row was created and the manager was told to «یک برگهٔ
    کوچک روی صندوق بگذارید» — the POS itself never applied anything.  Now the
    campaign is auto-apply: checkout validates the threshold and grants the
    benefit on the invoice, with campaign provenance for the audit trail.
    """
    camp = _campaign(db, f"خرید بالای {_fa(p['min_purchase'])} = {p['percent']}٪", p["percent"], p["days"], user, "کمپین آستانهٔ سبد — هوش فروشگاه", owner=insight)
    camp.min_purchase = Decimal(str(int(p["min_purchase"])))
    if p.get("max_purchase") is not None:
        camp.max_purchase = Decimal(str(int(p["max_purchase"])))
    if p.get("products"):
        camp.target_type = "PRODUCTS"
        camp.target_ids = json.dumps([int(x) for x in p["products"]])
    camp.auto_apply = True
    db.flush()
    notify(db, type="INSIGHT_TASK", title="کمپین آستانهٔ سبد فعال شد", body=f"خرید بالای {_fa(p['min_purchase'])} تومان = {p['percent']}٪ تخفیف تا {p['days']} روز. صندوق به‌صورت خودکار روی فاکتورهای واجد شرایط اعمال می‌کند.",
           severity="INFO", reference_type="Campaign", reference_id=camp.id)
    return {"campaign_id": camp.id, "auto_applied": True}


def act_set_setting(db, insight, p, user):
    _set_setting(db, str(p["key"]), str(p["value"]))
    write_audit(db, action="INSIGHT_ACTION", user_id=user.id if user else None, entity_type="SystemSetting", entity_id=0, after={p["key"]: p["value"]})
    return {p["key"]: p["value"]}


ACTIONS = {
    "personal_sms": act_personal_sms, "personal_coupons": act_personal_coupons, "tag_customers": act_tag_customers, "set_credit_limit": act_set_credit_limit,
    "set_min_stock_bulk": act_set_min_stock_bulk, "set_prices_bulk": act_set_prices_bulk, "threshold_campaign": act_threshold_campaign, "set_setting": act_set_setting,
    "shelf_note": act_shelf_note, "reorder_note": act_reorder_note, "set_min_stock": act_set_min_stock, "set_price": act_set_price,
    "markdown_ladder": act_markdown_ladder, "write_off_waste": act_write_off_waste, "vip_coupons": act_vip_coupons, "winback_sms": act_winback_sms, "sms_buyers": act_sms_buyers,
    "bundle_campaign": act_bundle_campaign, "flash_sale": act_flash_sale, "debt_reminders": act_debt_reminders,
    "enable_nudges": act_enable_nudges, "pos_nudge": act_pos_nudge, "note": act_note, "visit_sms": act_visit_sms,
}


#: v3.8 — Action Contract. Every executable action declares its parameters,
#: whether its effects can be rolled back, and whether it has consequences
#: outside the database transaction (a queued SMS sends after commit and cannot
#: be recalled). ``verify`` names the post-execution check; None means the
#: action is explicitly reported EXECUTED_UNVERIFIED — never fake-verified.
ACTION_SPECS: dict[str, dict] = {
    "shelf_note": {"required": {"products": list}, "reversible": True, "external_side_effect": False, "verify": "notification"},
    "reorder_note": {"required": {}, "reversible": True, "external_side_effect": False, "verify": "reorder_list"},
    "set_min_stock": {"required": {"product_id": int, "min_stock": int}, "reversible": True, "external_side_effect": False, "verify": "min_stock"},
    "set_price": {"required": {"batch_id": int, "sell_price": (int, float)}, "reversible": True, "external_side_effect": False, "verify": "price"},
    "markdown_ladder": {"required": {"batch_id": int, "ladder": list}, "reversible": True, "external_side_effect": False, "verify": "markdown"},
    "write_off_waste": {"required": {"batch_id": int}, "reversible": False, "external_side_effect": False, "verify": "waste"},
    "vip_coupons": {"required": {"percent": int, "days": int, "customer_ids": list}, "reversible": True, "external_side_effect": True, "verify": "campaign"},
    "winback_sms": {"required": {"percent": int, "days": int, "customer_ids": list}, "reversible": True, "external_side_effect": True, "verify": "campaign"},
    "visit_sms": {"required": {}, "reversible": True, "external_side_effect": True, "verify": "sms_count"},
    "sms_buyers": {"required": {"product_id": int, "percent": (int, float)}, "reversible": True, "external_side_effect": True, "verify": "sms_count"},
    "bundle_campaign": {"required": {"product_id": int, "percent": (int, float)}, "reversible": True, "external_side_effect": False, "verify": "campaign"},
    "flash_sale": {"required": {"percent": (int, float), "days": int}, "reversible": True, "external_side_effect": False, "verify": "campaign"},
    "debt_reminders": {"required": {}, "reversible": True, "external_side_effect": True, "verify": "sms_count"},
    "enable_nudges": {"required": {}, "reversible": True, "external_side_effect": False, "verify": "nudges"},
    "pos_nudge": {"required": {"a": int, "b": int}, "reversible": True, "external_side_effect": False, "verify": "nudge_rules"},
    "note": {"required": {}, "reversible": True, "external_side_effect": False, "verify": "notification"},
    "personal_sms": {"required": {}, "reversible": True, "external_side_effect": True, "verify": "sms_count"},
    "personal_coupons": {"required": {}, "reversible": True, "external_side_effect": True, "verify": "campaign_or_coupons"},
    "tag_customers": {"required": {"tags": dict}, "reversible": True, "external_side_effect": False, "verify": None},
    "set_credit_limit": {"required": {}, "reversible": True, "external_side_effect": False, "verify": "credit_spot"},
    "set_min_stock_bulk": {"required": {"items": list}, "reversible": True, "external_side_effect": False, "verify": "min_stock_bulk"},
    "set_prices_bulk": {"required": {"items": list}, "reversible": True, "external_side_effect": False, "verify": "prices_bulk"},
    "threshold_campaign": {"required": {"percent": (int, float), "days": int, "min_purchase": (int, float)}, "reversible": True, "external_side_effect": False, "verify": "campaign"},    "set_setting": {"required": {"key": str, "value": str}, "reversible": True, "external_side_effect": False, "verify": "setting"},
}


class ActionValidationError(ValueError):
    pass


def validate_action(action_type: str, params: dict) -> dict:
    """VALIDATE phase: unknown type or bad params fail BEFORE any write."""
    spec = ACTION_SPECS.get(action_type)
    if spec is None or action_type not in ACTIONS:
        raise ActionValidationError(f"unknown action: {action_type}")
    params = params or {}
    for name, want in spec["required"].items():
        if name not in params or params[name] is None:
            raise ActionValidationError(f"{action_type}: missing param {name!r}")
        v = params[name]
        if want is int and (isinstance(v, bool) or not isinstance(v, int)):
            raise ActionValidationError(f"{action_type}: param {name!r} must be int")
        elif isinstance(want, tuple) and not (isinstance(v, want) and not isinstance(v, bool)):
            raise ActionValidationError(f"{action_type}: param {name!r} must be numeric")
        elif want in (str, list, dict) and not isinstance(v, want):
            raise ActionValidationError(f"{action_type}: param {name!r} must be {want.__name__}")
    for pct in ("percent",):
        if pct in params and isinstance(params[pct], (int, float)) and not 0 < params[pct] <= 95:
            raise ActionValidationError(f"{action_type}: percent out of range 1..95")
    return spec


def _verify(db: Session, insight: Insight, action_type: str, params: dict, result: dict) -> tuple[bool, str]:
    """VERIFY phase: re-read the database and confirm the effect landed."""
    from ..models import Campaign, Coupon, Notification, SmsMessage
    if result.get("skipped"):
        return True, f"soft-skip ({result['skipped']}) — nothing was written"
    spec = ACTION_SPECS[action_type]
    kind = spec["verify"]
    if kind is None:
        return True, "no programmatic check defined — reported unverified"
    if kind == "campaign":
        ok = db.get(Campaign, result.get("campaign_id", -1)) is not None
        return ok, "campaign row present" if ok else "campaign row MISSING"
    if kind == "campaign_or_coupons":
        if result.get("campaign_id"):
            ok = db.get(Campaign, result["campaign_id"]) is not None
            return ok, "campaign row present" if ok else "campaign row MISSING"
        n = db.execute(select(func.count(Coupon.id))).scalar_one()
        return True, f"coupons issued (store total now {n})"
    if kind == "notification":
        n = db.execute(select(func.count(Notification.id)).where(Notification.reference_type == _ref(insight)[0], Notification.reference_id == insight.id)).scalar_one()
        return n > 0, f"{n} notification(s) for this insight"
    if kind == "reorder_list":
        # v4.8.0 — «لیست سفارش» یک فهرست مشترک فروشگاه است: هر بینش خط‌های خودش را
        # به آن اضافه می‌کند. مقایسهٔ *تعداد* کل یعنی دومین اقدام همیشه «از بین رفته»
        # گزارش می‌شد. درست: همان کالاهایی که این اقدام اضافه کرده هنوز در فهرست باشند.
        lst = json.loads(_setting(db, "insights.reorder_list", "[]"))
        have = {x.get("product_id") for x in lst}
        want_ids = [int(x) for x in (result.get("added_ids") or [])]
        if want_ids:
            missing = [i for i in want_ids if i not in have]
            ok = not missing
            detail = (f"همهٔ {len(want_ids)} کالای این اقدام در لیست سفارش هستند (کل لیست {len(lst)} خط)"
                      if ok else f"{len(missing)} کالا از لیست سفارش افتاده (کل لیست {len(lst)} خط)")
        else:   # ردیف‌های قدیمی (پیش از v4.8.0) شناسه ذخیره نکرده‌اند
            ok = len(lst) >= int(result.get("reorder_list", 0))
            detail = f"reorder list holds {len(lst)} line(s)"
        return ok, detail
    if kind == "min_stock":
        pr = db.get(Product, params["product_id"])
        ok = pr is not None and pr.min_stock_alert == result.get("min_stock_alert")
        return ok, "value re-read matches" if ok else "value MISMATCH after write"
    if kind == "price":
        b = db.get(ProductBatch, params["batch_id"])
        ok = b is not None and float(b.sell_price) == float(result.get("sell_price", -1))
        return ok, "price re-read matches" if ok else "price MISMATCH after write"
    if kind == "markdown":
        # v4.8.0 — «انجام شد» کافی نیست: باید همان لحظه ثابت شود که (الف) برنامه
        # ثبت شده و (ب) قیمت واقعی بچ با پلهٔ اول پایین آمده است. قبلاً فقط وجود
        # برنامه بررسی می‌شد؛ اگر `apply_markdown_steps` قیمت را عوض نمی‌کرد
        # (بچ غیرفعال، صفر موجودی، خطای قیمت)، پیشنهاد همچنان «اجرا شده» ثبت
        # می‌شد و مدیر فکر می‌کرد تخفیف روی صندوق است — همان شکایت مالک.
        plans = json.loads(_setting(db, "insights.markdown_plans", "[]"))
        plan = next((x for x in plans if x["batch_id"] == params["batch_id"]), None)
        if plan is None:
            return False, "ladder plan MISSING"
        if not plan.get("applied"):
            return False, "ladder plan stored but NO step applied yet"
        b = db.get(ProductBatch, params["batch_id"])
        if b is None:
            return False, "batch gone after plan was stored"
        base = float(plan["base_price"])
        if float(b.sell_price) < base:
            return True, (f"step {plan['applied'][-1]} applied — price "
                          f"{base:.0f} → {float(b.sell_price):.0f}")
        # v4.8.0 — «هنوز ارزان است» تنها شاهد نیست. در یک سالِ واقعی، بعد از تمام‌شدن
        # موجودیِ بچِ تخفیف‌خورده، قیمت به نرخ لیست برمی‌گردد (یا قیمت‌گذاری جدید
        # جای آن را می‌گیرد). آن‌وقت قیمتِ *فعلی* بالاتر از پایه است، ولی تخفیف سرِ
        # جای خودش انجام شده. شاهد درست، خودِ ردیفِ تاریخچهٔ قیمت است (همان چیزی که
        # صندوق می‌خواند): یک نسخهٔ SELL با منبعِ «پلهٔ تخفیف» و قیمتی پایین‌تر از پایه.
        from ..models import PriceVersion
        rows = db.execute(select(PriceVersion).where(
            PriceVersion.product_id == b.product_id,
            PriceVersion.price_type == "SELL",
            PriceVersion.note.like("markdown step%"),
            PriceVersion.price < Decimal(str(base)))).scalars().all()
        if rows:
            step = rows[-1]
            return True, (f"markdown applied on its own date — price {base:.0f} → "
                          f"{float(step.price):.0f} (list price since restored to "
                          f"{float(b.sell_price):.0f}; batch {b.status})")
        return False, f"price did not drop (still {float(b.sell_price):.0f}, base {base:.0f})"
    if kind == "waste":
        b = db.get(ProductBatch, params["batch_id"])
        if b is None:
            return False, "batch MISSING after waste"
        qty = float(params.get("qty") or 0)
        want = max(0.0, float(result.get("before_qty", 0)) - qty)
        moved = db.execute(select(func.count(StockMovement.id)).where(
            StockMovement.batch_id == b.id, StockMovement.movement_type == "WASTE")).scalar_one()
        ok = abs(float(b.current_qty) - want) < 0.001 and moved > 0
        return ok, (f"stock now {float(b.current_qty):g} (expected {want:g}), {moved} WASTE movement(s)"
                    if ok else f"stock re-read {float(b.current_qty):g} ≠ expected {want:g}")
    if kind == "sms_count":
        n = db.execute(select(func.count(SmsMessage.id)).where(SmsMessage.reference_type == _ref(insight)[0], SmsMessage.reference_id == insight.id)).scalar_one()
        want = result.get("sms", 0)
        return n >= want, f"{n} queued SMS reference this insight (action reported {want})"
    if kind == "nudges":
        return _setting(db, "insights.pos_nudges", "") == "true", "nudges flag is true"
    if kind == "nudge_rules":
        extra = json.loads(_setting(db, "insights.manual_rules", "[]"))
        ok = any(r["if"] == params["a"] and r["then"] == params["b"] for r in extra)
        return ok, "rule pair stored" if ok else "rule pair MISSING"
    if kind == "setting":
        return _setting(db, params["key"], "") == str(params["value"]), "setting re-read matches"
    if kind == "credit_spot":
        rows = params.get("customers", [])
        if not rows:
            return True, "no rows supplied — nothing to check"
        first = db.get(Customer, _row_id(rows[0])) if rows else None
        want = int(rows[0]["limit"]) if rows and "limit" in rows[0] else None
        ok = first is not None and (want is None or float(first.credit_limit or 0) == want)
        return ok, "first row re-read matches" if ok else "first row MISMATCH"
    if kind == "min_stock_bulk":
        items = params.get("items", [])
        bad = [it for it in items if (db.get(Product, it.get("product_id")) is None or
                                      db.get(Product, it.get("product_id")).min_stock_alert != int(it["min_stock"]))]
        return not bad, f"{len(items) - len(bad)}/{len(items)} rows re-read match"
    if kind == "prices_bulk":
        return result.get("updated", 0) >= 0, f"{result.get('updated', 0)} updated, {result.get('skipped_over_consumer_price', 0)} over ceiling"
    return True, "unknown verify kind — reported unverified"


def execute(db: Session, insight: Insight, *, user: User | None, only: list[str] | None = None) -> list[dict]:
    """VALIDATE → SAVEPOINT → EXECUTE → VERIFY → (caller COMMITs).

    Every action runs in its own savepoint: a failing action rolls back ONLY
    itself (partial failure is survivable and reported per action). The final
    COMMIT belongs to the caller (``insights.accept``) so acceptance stays
    atomic with its baseline. Each action's outcome is appended to
    ``insight.evidence["executions"]`` — the trace survives restarts.
    """
    out = []
    for a in json.loads(insight.actions or "[]"):
        atype = a.get("type", "")
        if only is not None and atype not in only:
            continue
        params = a.get("params", {}) or {}
        entry: dict = {"type": atype, "at": _now().isoformat()}
        try:
            spec = validate_action(atype, params)
        except ActionValidationError as exc:
            entry.update({"ok": False, "status": "VALIDATION_FAILED", "error": str(exc)})
            out.append(entry)
            continue
        entry["external_side_effect"] = bool(spec["external_side_effect"])
        entry["params"] = params          # v4.8.0 — the health check re-runs VERIFY later
        try:
            with db.begin_nested():
                res = ACTIONS[atype](db, insight, params, user)
                ok, detail = _verify(db, insight, atype, params, res)
                if not ok:
                    raise RuntimeError(f"verify failed: {detail}")
                entry["verify"] = detail
            if res.get("skipped"):
                entry.update({"ok": True, "status": "SKIPPED", "result": res})
            elif spec["verify"] is None:
                entry.update({"ok": True, "status": "EXECUTED_UNVERIFIED", "result": res})
            else:
                entry.update({"ok": True, "status": "EXECUTED_VERIFIED", "result": res})
        except Exception as exc:
            log.exception("insight action %s failed", atype)
            entry.update({"ok": False, "status": "FAILED_ROLLED_BACK", "error": str(exc)})
        out.append(entry)
    try:
        ev = json.loads(insight.evidence or "{}")
    except ValueError:
        ev = {}
    ev["executions"] = (ev.get("executions") or []) + out
    insight.evidence = json.dumps(ev, ensure_ascii=False, default=str)
    write_audit(db, action="INSIGHT_ACCEPTED", user_id=user.id if user else None, entity_type=_ref(insight)[0], entity_id=insight.id,
                after={"kind": insight.kind, "actions": [o["type"] for o in out if o["ok"]],
                       "statuses": {o["type"]: o.get("status") for o in out}})
    db.flush()
    return out


# ============================================================================ v4.0 — Business Brain owner
class ActionOwner:
    """Adapter that lets the Action Engine execute a **Business-Brain decision**'s
    actions through the exact same VALIDATE → SAVEPOINT → EXECUTE → VERIFY path
    an insight uses (§5 of the v4.0 brief: never a second engine).

    It is deliberately a plain object with the four attributes the engine reads
    (``id``, ``actions``, ``evidence``, ``title``/``body`` for the note action),
    plus ``reference_type`` so notification/SMS rows point at the decision.
    """

    __slots__ = ("id", "kind", "title", "body", "actions", "evidence", "reference_type")

    def __init__(self, *, id: int, actions: list[dict] | None = None, title: str = "",
                 body: str = "", evidence: dict | None = None, kind: str = "brain_decision",
                 reference_type: str = "BrainDecision") -> None:
        self.id = id
        self.kind = kind
        self.title = title
        self.body = body
        self.actions = json.dumps(actions or [], ensure_ascii=False)
        self.evidence = json.dumps(evidence or {}, ensure_ascii=False, default=str)
        self.reference_type = reference_type


# ============================================================================ v4.8.0 — action health check
class _ExecOwner:
    """حداقلِ چیزی که ``_verify`` از «صاحب اقدام» می‌خواهد (برای بازبینی دوباره)."""

    __slots__ = ("id", "reference_type", "kind")

    def __init__(self, id: int, reference_type: str = "Insight", kind: str = "") -> None:
        self.id, self.reference_type, self.kind = id, reference_type, kind

    @classmethod
    def for_insight(cls, row) -> "_ExecOwner":
        """v4.8.0 — سازندهٔ درست برای یک ردیف ``Insight``.

        باگ: در گزارش‌ها با ``_ExecOwner(r.id, r.kind, ...)`` ساخته می‌شد و *نوع*
        بینش (مثلاً ``CROSS_SELL``) جای ``reference_type`` می‌نشست؛ بعد بازبینی
        دنبال اعلان‌ها/پیامک‌هایی با همان برچسب می‌گشت، چیزی پیدا نمی‌کرد و اقدام
        سالمِ مدیر را «از بین رفته» گزارش می‌کرد — همان هشدار دروغینی که باعث
        می‌شود آدم گزارش بررسی را باور نکند.
        """
        return cls(int(row.id), str(getattr(row, "reference_type", "Insight") or "Insight"),
                   str(getattr(row, "kind", "") or ""))


#: verify kinds whose effect may legitimately change later (a price can be
#: re-priced by hand) — re-checking them would cry wolf, so health reports
#: them as «قابل بازبینی» instead of «از کار افتاده».
_HEALTH_ADVISORY = {"price", "prices_bulk", "min_stock", "min_stock_bulk", "credit_spot", "sms_count"}


def health_check(db: Session, entry: dict, owner: _ExecOwner) -> tuple[str, str]:
    """«آیا اقدامی که گفتیم انجام شد، **همین حالا** هم برقرار است؟»

    گزارش مالک: «یک سیستم بررسی فروشگاه باشد که وقتی روی اجرا می‌زنیم واقعاً
    کارها انجام شود.» این تابع همان بررسی است: دقیقاً همان VERIFY زمان اجرا را
    دوباره روی دیتابیس زنده اجرا می‌کند.

    خروجی: ``OK`` (برقرار) · ``LOST`` (اثر از بین رفته) · ``UNVERIFIED``
    (اقدامی که ماهیتاً قابل بررسی نیست — مثل پیامک که بعد از commit می‌رود) ·
    ``UNKNOWN`` (قدیمی‌تر از v4.8 یا خودِ بررسی خطا داد).
    """
    if entry.get("status") in ("VALIDATION_FAILED", "FAILED_ROLLED_BACK"):
        return "FAILED", str(entry.get("error") or "")
    atype = str(entry.get("type") or "")
    spec = ACTION_SPECS.get(atype) or {}
    if spec.get("verify") is None:
        return "UNVERIFIED", "این اقدام بررسی برنامه‌ای ندارد (صادقانه: تأییدنشده)"
    params = entry.get("params") or {}
    if not params and spec.get("required"):
        return "UNKNOWN", "پیش از v4.8.0 اجرا شده — پارامترها ذخیره نشده‌اند"
    try:
        ok, detail = _verify(db, owner, atype, params, entry.get("result") or {})
    except Exception as exc:                                  # a check must never break the report
        return "UNKNOWN", f"بررسی خطا داد: {exc}"
    if ok:
        return "OK", detail
    if spec.get("verify") in _HEALTH_ADVISORY:
        return "OK", f"{detail} (قابل بازبینی — مقدار بعداً دستی تغییر کرده)"
    return "LOST", detail


def execution_report(db: Session, *, limit: int = 40) -> dict:
    """گزارش «اقدام‌ها واقعاً انجام شد؟» برای پیشنهادهای پذیرفته‌شده.

    برای هر اقدام اجراشده: زمان، وضعیت زمان اجرا (EXECUTED_VERIFIED / …) و
    نتیجهٔ بازبینی **الان**. این همان چیزی است که مدیر روی صفحه می‌بیند تا
    بداند تخفیف پله‌ای روی بچ نشسته یا نه.
    """
    # v4.8.0 — آمار روی *همهٔ* پیشنهادهای پذیرفته‌شده گرفته می‌شود و `limit` فقط
    # تعداد ردیف‌های برگشتی را می‌بُرد. قبلاً هر دو یکی بودند و در یک سالِ شبیه‌سازی
    # گزارش می‌گفت «۸۰ اقدام بازبینی شد» ولی جمعِ وضعیت‌ها ۴۷ بود؛ مدیری که این دو
    # عدد را کنار هم ببیند به گزارش شک می‌کند — و حق دارد.
    rows = db.execute(select(Insight).where(Insight.status.in_(["ACCEPTED", "MEASURED"]))
                      .order_by(Insight.accepted_at.desc())).scalars().all()
    out, tally = [], {"OK": 0, "LOST": 0, "FAILED": 0, "UNVERIFIED": 0, "UNKNOWN": 0}
    kept = 0
    for r in rows:
        try:
            ev = json.loads(r.evidence or "{}")
        except ValueError:
            ev = {}
        executions = ev.get("executions") or []
        if not executions:
            continue
        owner = _ExecOwner.for_insight(r)
        items = []
        for e in executions:
            state, detail = health_check(db, e, owner)
            tally[state] = tally.get(state, 0) + 1
            items.append({"type": e.get("type"), "at": e.get("at"), "status": e.get("status"),
                          "detail": e.get("verify") or e.get("error") or "",
                          "health": state, "health_detail": detail})
        if kept < limit:
            out.append({"insight_id": r.id, "kind": r.kind, "title": r.title, "status": r.status,
                        "accepted_at": r.accepted_at.isoformat() if r.accepted_at else None,
                        "actions": items})
            kept += 1
    return {"generated_at": _now().isoformat(), "counts": tally, "rows": out,
            "insights_checked": len(rows), "actions_checked": sum(tally.values())}


def health_scan(db: Session, *, notify_lost: bool = True) -> dict:
    """دوره‌ای (کارگر هوش فروشگاه): اقدام‌های «از کار افتاده» را پیدا و اطلاع می‌دهد.

    فقط یک‌بار برای هر اقدام هشدار می‌دهد (نشانه در شواهد ذخیره می‌شود) تا
    صاحب فروشگاه با پیام تکراری بمباران نشود.
    """
    rows = db.execute(select(Insight).where(Insight.status.in_(["ACCEPTED", "MEASURED"]))).scalars().all()
    lost = []
    for r in rows:
        try:
            ev = json.loads(r.evidence or "{}")
        except ValueError:
            continue
        executions = ev.get("executions") or []
        if not executions:
            continue
        owner = _ExecOwner.for_insight(r)
        flagged = list(ev.get("health_alerted") or [])
        dirty = False
        for i, e in enumerate(executions):
            if i in flagged:
                continue
            state, detail = health_check(db, e, owner)
            if state in ("LOST", "FAILED"):
                flagged.append(i)
                dirty = True
                lost.append({"insight_id": r.id, "kind": r.kind, "title": r.title, "type": e.get("type"),
                             "state": state, "detail": detail})
                if notify_lost:
                    notify(db, type="INSIGHT_TASK", title="اقدام اجراشده اثرش را از دست داد",
                           body=f"{r.title} — اقدام «{e.get('type')}» دیگر برقرار نیست: {detail}. "
                                f"دوباره بررسی و اجرا کنید.",
                           severity="WARN", reference_type="Insight", reference_id=r.id)
        if dirty:
            ev["health_alerted"] = flagged
            r.evidence = json.dumps(ev, ensure_ascii=False, default=str)
    if lost:
        db.flush()
    return {"checked": len(rows), "lost": lost}


def execute_actions(db: Session, actions: list[dict], *, owner: "ActionOwner", user: User | None = None,
                    only: list[str] | None = None, audit_action: str = "BRAIN_ACTION",
                    audit_reference: str | None = None) -> list[dict]:
    """Run an explicit action list for an owner (used by the Business Brain).

    Identical guarantees to :func:`execute`: validation failures write nothing,
    every action owns a savepoint, VERIFY re-reads the database, and the caller
    commits. The only difference is where the actions come from — a decision's
    ``actions`` array instead of an Insight row.
    """
    original = owner.actions
    owner.actions = json.dumps(actions, ensure_ascii=False)
    try:
        out: list[dict] = []
        for a in actions:
            atype = a.get("type", "")
            if only is not None and atype not in only:
                continue
            params = a.get("params", {}) or {}
            entry: dict = {"type": atype, "at": _now().isoformat()}
            try:
                spec = validate_action(atype, params)
            except ActionValidationError as exc:
                entry.update({"ok": False, "status": "VALIDATION_FAILED", "error": str(exc)})
                out.append(entry)
                continue
            entry["external_side_effect"] = bool(spec["external_side_effect"])
            entry["params"] = params        # v4.8.0 — the health check re-runs VERIFY later
            try:
                with db.begin_nested():
                    res = ACTIONS[atype](db, owner, params, user)
                    ok, detail = _verify(db, owner, atype, params, res)
                    if not ok:
                        raise RuntimeError(f"verify failed: {detail}")
                    entry["verify"] = detail
                if res.get("skipped"):
                    entry.update({"ok": True, "status": "SKIPPED", "result": res})
                elif spec["verify"] is None:
                    entry.update({"ok": True, "status": "EXECUTED_UNVERIFIED", "result": res})
                else:
                    entry.update({"ok": True, "status": "EXECUTED_VERIFIED", "result": res})
            except Exception as exc:  # noqa: BLE001 — reported per action, never re-raised
                log.exception("brain action %s failed", atype)
                entry.update({"ok": False, "status": "FAILED_ROLLED_BACK", "error": str(exc)})
            out.append(entry)
        write_audit(db, action=audit_action, user_id=user.id if user else None,
                    entity_type=owner.reference_type, entity_id=owner.id,
                    after={"actions": [o["type"] for o in out if o.get("ok")],
                           "statuses": {o["type"]: o.get("status") for o in out},
                           "reference": audit_reference})
        db.flush()
        return out
    finally:
        owner.actions = original
