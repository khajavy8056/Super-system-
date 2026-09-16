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

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Campaign, Coupon, Customer, Insight, Invoice, InvoiceItem, Product, ProductBatch, SystemSetting, User
from . import coupons as coupon_svc
from . import sms as sms_svc
from .audit import write_audit
from .notifications import notify

log = logging.getLogger("supermarket.insights.actions")


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
           severity="INFO", reference_type="Insight", reference_id=insight.id)
    return {"note": names}


def act_reorder_note(db, insight, p, user):
    ids = p.get("products") or ([p["product_id"]] if p.get("product_id") else [])
    names = {pr.id: pr.name for pr in db.execute(select(Product).where(Product.id.in_(ids))).scalars()}
    lst = json.loads(_setting(db, "insights.reorder_list", "[]"))
    for pid in ids:
        if not any(x["product_id"] == pid for x in lst):
            lst.append({"product_id": pid, "name": names.get(pid, str(pid)), "qty": p.get("qty"), "added": _now().isoformat(), "insight_id": insight.id})
    _set_setting(db, "insights.reorder_list", json.dumps(lst, ensure_ascii=False))
    notify(db, type="INSIGHT_TASK", title="به لیست سفارش اضافه شد", body="، ".join(names.values()), severity="INFO", reference_type="Insight", reference_id=insight.id)
    return {"reorder_list": len(lst)}


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
    """Apply the first step now; store the ladder so the scheduler applies later steps."""
    b = db.get(ProductBatch, p["batch_id"])
    if not b:
        return {"skipped": "batch"}
    ladder = p["ladder"]
    base_price = float(b.sell_price)
    plan = {"batch_id": b.id, "base_price": base_price, "start": _now().date().isoformat(), "ladder": ladder, "applied": [], "insight_id": insight.id}
    plans = json.loads(_setting(db, "insights.markdown_plans", "[]"))
    plans = [x for x in plans if x["batch_id"] != b.id] + [plan]
    _set_setting(db, "insights.markdown_plans", json.dumps(plans, ensure_ascii=False))
    apply_markdown_steps(db)   # applies step 0 immediately
    return {"plan": plan}


def apply_markdown_steps(db: Session) -> int:
    """Scheduler hook: move batches down the ladder on their due days; never below buy price."""
    plans = json.loads(_setting(db, "insights.markdown_plans", "[]"))
    today = _now().date()
    changed, keep = 0, []
    for plan in plans:
        b = db.get(ProductBatch, plan["batch_id"])
        if not b or b.status != "ACTIVE" or float(b.current_qty) <= 0:
            continue
        day = (today - datetime.fromisoformat(plan["start"]).date()).days
        due = [s for s in plan["ladder"] if s["from_day"] <= day]
        if due:
            step = max(due, key=lambda s: s["from_day"])
            if step["percent"] not in plan["applied"]:
                new_price = round(plan["base_price"] * (1 - step["percent"] / 100) / 100) * 100
                new_price = max(new_price, float(b.buy_price) * 1.01)
                before = float(b.sell_price)
                b.sell_price = Decimal(str(round(new_price)))
                b.discount = Decimal(str(round(plan["base_price"] - new_price)))
                plan["applied"].append(step["percent"])
                write_audit(db, action="INSIGHT_ACTION", entity_type="ProductBatch", entity_id=b.id,
                            before={"sell_price": before}, after={"sell_price": float(b.sell_price), "ladder_step": step["percent"]})
                notify(db, type="INSIGHT_TASK", title=f"تخفیف پله‌ای {step['percent']}٪ اعمال شد", body=f"{b.product.name} — قیمت جدید {_fa(new_price)} تومان",
                       severity="INFO", reference_type="ProductBatch", reference_id=b.id)
                changed += 1
        if len(plan["applied"]) < len(plan["ladder"]):
            keep.append(plan)
    _set_setting(db, "insights.markdown_plans", json.dumps(keep, ensure_ascii=False))
    db.flush()
    return changed


def _coupon(db, *, code_prefix: str, customer: Customer, percent: int, days: int, campaign_id: int | None, user):
    code = coupon_svc.generate_code(prefix=code_prefix)
    c = Coupon(code=code, campaign_id=campaign_id, customer_id=customer.id, customer_phone=customer.phone, discount_type="PERCENT",
               discount_value=Decimal(percent), min_purchase=Decimal(0), valid_from=_now(),
               valid_until=_now() + timedelta(days=days), usage_limit=1, status="ACTIVE", created_by=user.id if user else None)
    db.add(c)
    db.flush()
    return c


def _campaign(db, name: str, percent: int, days: int, user, description: str) -> Campaign:
    c = Campaign(name=name, description=description, discount_type="PERCENT", discount_value=Decimal(percent), min_purchase=Decimal(0),
                 valid_from=_now(), valid_until=_now() + timedelta(days=days), status="ACTIVE",
                 created_by=user.id if user else None)
    db.add(c)
    db.flush()
    write_audit(db, action="INSIGHT_ACTION", user_id=user.id if user else None, entity_type="Campaign", entity_id=c.id, after={"name": name})
    return c


def act_vip_coupons(db, insight, p, user):
    camp = _campaign(db, "باشگاه VIP", p["percent"], p["days"], user, "کوپن ماهانهٔ مشتریان برتر — ساخته‌شده توسط هوش فروشگاه")
    sent = issued = 0
    for cust in db.execute(select(Customer).where(Customer.id.in_(p["customer_ids"]))).scalars():
        c = _coupon(db, code_prefix="VIP", customer=cust, percent=p["percent"], days=p["days"], campaign_id=camp.id, user=user)
        issued += 1
        if cust.phone and _sms_enabled(db):
            sms_svc.queue_sms(db, phone=cust.phone, text=f"{cust.name} عزیز، شما مشتری ویژهٔ {_store(db)} هستید. کد {c.code} = {p['percent']}٪ تخفیف تا {p['days']} روز. با سپاس از همراهی‌تان.",
                              reference_type="Insight", reference_id=insight.id)
            sent += 1
    sms_svc.kick_worker()
    return {"campaign_id": camp.id, "coupons": issued, "sms": sent}


def act_winback_sms(db, insight, p, user):
    camp = _campaign(db, "بازگشت مشتری", p["percent"], p["days"], user, "کوپن بازگشت برای مشتریان غایب — هوش فروشگاه")
    sent = issued = 0
    for cust in db.execute(select(Customer).where(Customer.id.in_(p["customer_ids"]))).scalars():
        c = _coupon(db, code_prefix="BACK", customer=cust, percent=p["percent"], days=p["days"], campaign_id=camp.id, user=user)
        issued += 1
        if cust.phone and _sms_enabled(db):
            sms_svc.queue_sms(db, phone=cust.phone, text=f"{cust.name} عزیز، دلمان برایتان تنگ شده! {_store(db)} با کد {c.code} {p['percent']}٪ تخفیف تا {p['days']} روز منتظر شماست.",
                              reference_type="Insight", reference_id=insight.id)
            sent += 1
    sms_svc.kick_worker()
    return {"campaign_id": camp.id, "coupons": issued, "sms": sent}


def act_visit_sms(db, insight, p, user):
    """v3.2 — personal «your usual item» reminder to the customers whose visit is due."""
    sent = 0
    if not _sms_enabled(db):
        return {"sms": 0, "skipped": "sms_disabled"}
    for row in p.get("customers", []):
        cust = db.get(Customer, row.get("customer_id"))
        if not cust or not cust.phone:
            continue
        item = (row.get("item") or "").strip()
        txt = (f"{cust.name} عزیز، {_store(db)}: " + (f"«{item}» تازه رسیده و برایتان کنار گذاشته‌ایم؛ " if item else "")
               + "منتظر دیدارتان هستیم.")
        sms_svc.queue_sms(db, phone=cust.phone, text=txt, reference_type="Insight", reference_id=insight.id)
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
    sent = 0
    if _sms_enabled(db):
        for cust in db.execute(select(Customer).where(Customer.id.in_(list(ids)), Customer.phone.is_not(None))).scalars():
            sms_svc.queue_sms(db, phone=cust.phone, text=f"{cust.name} عزیز، «{pr.name if pr else 'کالای موردعلاقهٔ شما'}» این هفته در {_store(db)} با {p['percent']}٪ تخفیف. تا اتمام موجودی.",
                              reference_type="Insight", reference_id=insight.id)
            sent += 1
        sms_svc.kick_worker()
    return {"buyers": len(ids), "sms": sent}


def act_bundle_campaign(db, insight, p, user):
    pr = db.get(Product, p["product_id"])
    partner = db.get(Product, p["partner_id"]) if p.get("partner_id") else None
    name = f"باندل {pr.name if pr else ''}" + (f" + {partner.name}" if partner else "")
    camp = _campaign(db, name, p["percent"], 21, user, "باندل کالای راکد با کالای پرفروش — هوش فروشگاه")
    # markdown on the dead stock's batches
    for b in db.execute(select(ProductBatch).where(ProductBatch.product_id == p["product_id"], ProductBatch.status == "ACTIVE", ProductBatch.current_qty > 0)).scalars():
        before = float(b.sell_price)
        from . import pricing_law
        new_price = max(float(b.buy_price) * 1.01, round(before * (1 - p["percent"] / 100) / 100) * 100)
        # the cost floor above can itself sit over the printed consumer price — never charge it
        new_price = pricing_law.clamp_sell(b, new_price)
        b.sell_price = Decimal(str(round(new_price)))
        b.discount = Decimal(str(round(before - new_price)))
    notify(db, type="INSIGHT_TASK", title="باندل ساخته شد", body=f"{name} — {p['percent']}٪ تخفیف روی کالای راکد؛ آن را کنار کالای پرفروش بچینید.",
           severity="INFO", reference_type="Campaign", reference_id=camp.id)
    return {"campaign_id": camp.id}


def act_flash_sale(db, insight, p, user):
    camp = _campaign(db, "فروش ویژهٔ نقدینگی", p["percent"], p["days"], user, "فروش ویژهٔ کوتاه برای آزادسازی نقدینگی — هوش فروشگاه")
    notify(db, type="INSIGHT_TASK", title="فروش ویژه فعال شد", body=f"{p['days']} روز، {p['percent']}٪ روی کالاهای راکد (از بخش جشنواره قابل ویرایش است).",
           severity="INFO", reference_type="Campaign", reference_id=camp.id)
    return {"campaign_id": camp.id}


def act_debt_reminders(db, insight, p, user):
    from ..models import CustomerLedgerEntry
    from sqlalchemy import func
    sub = select(CustomerLedgerEntry.customer_id, func.max(CustomerLedgerEntry.id).label("mid")).group_by(CustomerLedgerEntry.customer_id).subquery()
    rows = db.execute(select(CustomerLedgerEntry).join(sub, CustomerLedgerEntry.id == sub.c.mid)).scalars().all()
    sent = 0
    if _sms_enabled(db):
        for e in rows:
            if float(e.balance_after) > 0:
                cust = db.get(Customer, e.customer_id)
                if cust and cust.phone:
                    text = sms_svc.render_template(db, "debt_reminder", customer=cust.name, amount=_fa(e.balance_after))
                    sms_svc.queue_sms(db, phone=cust.phone, text=text, reference_type="Insight", reference_id=insight.id)
                    sent += 1
        sms_svc.kick_worker()
    return {"debtors": len([e for e in rows if float(e.balance_after) > 0]), "sms": sent}


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
    notify(db, type="INSIGHT_TASK", title=insight.title, body=insight.body[:400], severity="WARN", reference_type="Insight", reference_id=insight.id)
    return {"noted": True}


# ------------------------------------------------------------------ v3.5 PRO actions
def act_personal_sms(db, insight, p, user):
    """One *different* text per customer (the PRO analyzers write the message for each person)."""
    if not _sms_enabled(db):
        return {"sms": 0, "skipped": "sms_disabled"}
    sent = 0
    for row in p.get("customers", []):
        cust = db.get(Customer, row.get("customer_id"))
        txt = (row.get("text") or "").strip()
        if not cust or not cust.phone or not txt:
            continue
        sms_svc.queue_sms(db, phone=cust.phone, text=txt, reference_type="Insight", reference_id=insight.id)
        sent += 1
    sms_svc.kick_worker()
    return {"sms": sent}


def act_personal_coupons(db, insight, p, user):
    """Per-customer percent/days (+ optional personal text). One campaign groups them for the ROI report."""
    rows = p.get("customers", [])
    if not rows:
        return {"coupons": 0}
    pct = int(rows[0].get("percent", 5)); days = int(rows[0].get("days", 7))
    camp = _campaign(db, f"کوپن شخصی — {insight.title[:40]}", pct, days, user, f"کوپن‌های شخصی هوش فروشگاه (پیشنهاد #{insight.id})")
    issued = sent = 0
    for row in rows:
        cust = db.get(Customer, row.get("customer_id"))
        if not cust:
            continue
        c = _coupon(db, code_prefix="ME", customer=cust, percent=int(row.get("percent", pct)), days=int(row.get("days", days)), campaign_id=camp.id, user=user)
        issued += 1
        if cust.phone and _sms_enabled(db):
            txt = row.get("text") or f"{cust.name} عزیز، کد {c.code} = {row.get('percent', pct)}٪ تخفیف شخصی شما در {_store(db)} تا {row.get('days', days)} روز آینده."
            sms_svc.queue_sms(db, phone=cust.phone, text=txt.replace("WELCOME۱۰", c.code).replace("VIP۵", c.code).replace("BACK۱۰", c.code), reference_type="Insight", reference_id=insight.id)
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


def act_set_credit_limit(db, insight, p, user):
    n = 0
    for row in p.get("customers", []):
        cust = db.get(Customer, row.get("customer_id"))
        if not cust:
            continue
        before = float(cust.credit_limit or 0)
        cust.credit_limit = Decimal(str(int(row["limit"])))
        write_audit(db, action="INSIGHT_ACTION", user_id=user.id if user else None, entity_type="Customer", entity_id=cust.id,
                    before={"credit_limit": before}, after={"credit_limit": float(cust.credit_limit)})
        n += 1
    return {"updated": n}


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
    camp = _campaign(db, f"خرید بالای {_fa(p['min_purchase'])} = {p['percent']}٪", p["percent"], p["days"], user, "کمپین آستانهٔ سبد — هوش فروشگاه")
    camp.min_purchase = Decimal(str(int(p["min_purchase"])))
    notify(db, type="INSIGHT_TASK", title="کمپین آستانهٔ سبد فعال شد", body=f"خرید بالای {_fa(p['min_purchase'])} تومان = {p['percent']}٪ تخفیف تا {p['days']} روز. یک برگهٔ کوچک روی صندوق بگذارید.",
           severity="INFO", reference_type="Campaign", reference_id=camp.id)
    return {"campaign_id": camp.id}


def act_set_setting(db, insight, p, user):
    _set_setting(db, str(p["key"]), str(p["value"]))
    write_audit(db, action="INSIGHT_ACTION", user_id=user.id if user else None, entity_type="SystemSetting", entity_id=0, after={p["key"]: p["value"]})
    return {p["key"]: p["value"]}


ACTIONS = {
    "personal_sms": act_personal_sms, "personal_coupons": act_personal_coupons, "tag_customers": act_tag_customers, "set_credit_limit": act_set_credit_limit,
    "set_min_stock_bulk": act_set_min_stock_bulk, "set_prices_bulk": act_set_prices_bulk, "threshold_campaign": act_threshold_campaign, "set_setting": act_set_setting,
    "shelf_note": act_shelf_note, "reorder_note": act_reorder_note, "set_min_stock": act_set_min_stock, "set_price": act_set_price,
    "markdown_ladder": act_markdown_ladder, "vip_coupons": act_vip_coupons, "winback_sms": act_winback_sms, "sms_buyers": act_sms_buyers,
    "bundle_campaign": act_bundle_campaign, "flash_sale": act_flash_sale, "debt_reminders": act_debt_reminders,
    "enable_nudges": act_enable_nudges, "pos_nudge": act_pos_nudge, "note": act_note, "visit_sms": act_visit_sms,
}


def execute(db: Session, insight: Insight, *, user: User | None, only: list[str] | None = None) -> list[dict]:
    out = []
    for a in json.loads(insight.actions or "[]"):
        if only is not None and a["type"] not in only:
            continue
        fn = ACTIONS.get(a["type"])
        if not fn:
            out.append({"type": a["type"], "ok": False, "error": "unknown action"})
            continue
        try:
            res = fn(db, insight, a.get("params", {}), user)
            out.append({"type": a["type"], "ok": True, "result": res})
        except Exception as exc:
            log.exception("insight action %s failed", a["type"])
            out.append({"type": a["type"], "ok": False, "error": str(exc)})
    write_audit(db, action="INSIGHT_ACCEPTED", user_id=user.id if user else None, entity_type="Insight", entity_id=insight.id,
                after={"kind": insight.kind, "actions": [o["type"] for o in out if o["ok"]]})
    db.flush()
    return out
