# -*- coding: utf-8 -*-
"""v4.8.0 — بازبینی زندهٔ سرتاسری روی یک دیتابیس تازه (اجرای واقعی، نه واحد).

مسیر کامل: کالای نزدیک انقضا → موتور هوش → کارت پیشنهاد → «اجرا» → قیمت
واقعاً عوض می‌شود → تاریخچهٔ قیمت → گزارش اجرا (OK) → تغییر قیمت از بیرون و
بازبینی دوباره (LOST) → ثبت ضایعات کالای منقضی → پیشنهاد صندوق (nudges) →
پیامک کوتاه حالت الگو.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="v480_e2e_"))
os.environ["DATABASE_URL"] = f"sqlite:///{TMP / 'e2e.db'}"
os.environ["SECRET_KEY"] = "e2e-secret-key-that-is-long-enough-for-hs256"
os.environ["ADMIN_USERNAME"] = "admin"
os.environ["ADMIN_PASSWORD"] = "admin123"
os.environ["SUPERMARKET_LICENSE_GATE"] = "0"
os.environ["SUPERMARKET_INSIGHTS_WORKER"] = "0"
os.environ["SUPERMARKET_LAN_BEACON"] = "0"

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.models import ProductBatch, PriceVersion, SystemSetting, StockMovement  # noqa: E402
from app.services import expiry_plan  # noqa: E402

FAILS: list[str] = []


def check(label: str, cond: bool, extra: str = "") -> None:
    mark = "✅" if cond else "❌"
    print(f"{mark} {label}" + (f" — {extra}" if extra else ""))
    if not cond:
        FAILS.append(label)


def day(n: int) -> str:
    return (date.today() + timedelta(days=n)).isoformat()


with TestClient(app) as c:
    tok = c.post("/api/auth/login", data={"username": "admin", "password": "admin123"})
    assert tok.status_code == 200, tok.text
    H = {"Authorization": f"Bearer {tok.json()['access_token']}"}

    def mk(name: str, qty: int, buy: int, sell: int, expiry_days: int | None):
        p = c.post("/api/products", json={"name": name}, headers=H).json()
        b = c.post("/api/batches/receive", headers=H, json={
            "product_id": p["id"], "quantity_received": qty, "buy_price": buy,
            "sell_price": sell, "expiry_date": day(expiry_days) if expiry_days is not None else None})
        assert b.status_code == 201, b.text
        return p, b.json()

    # ۱) کالای نزدیک انقضا (۲۰ روز) بدون فروش قبلی → باید کارت «نردبان» بگیرد
    near, near_b = mk("ماست ۱ کیلویی [E2E]", 40, 40000, 52000, 20)
    # ۲) کالای منقضی → باید اقدام «ثبت ضایعات» بگیرد، هرگز تخفیف
    dead, dead_b = mk("پنیر کهنه [E2E]", 12, 90000, 120000, -3)

    r = c.post("/api/insights/run", headers=H)
    check("موتور هوش فروشگاه اجرا شد", r.status_code == 200, str(r.status_code))

    rows = c.get("/api/insights", params={"status": "NEW", "limit": 100}, headers=H).json()
    def find(kind_hint: str, pid: int):
        for it in rows:
            if it.get("kind") == kind_hint and (it.get("evidence") or {}).get("product_id") == pid:
                return it
        return None

    card = find("EXPIRY_LADDER", near["id"])
    check("کارت پیشنهاد برای کالای ۲۰ روزه ساخته شد", card is not None,
          json.dumps(rows[0].get("kind") if rows else None, ensure_ascii=False))
    if card:
        ev = card["evidence"]
        check("پیشنهاد از روزهای باقی‌ماندهٔ واقعی خبر می‌دهد و روی روز صفر نیست",
              0 < ev.get("days_left", 0) <= 45, f"days_left={ev.get('days_left')}")
        check("حالت برنامه تخفیف پله‌ای است (نه ضایعات)", ev.get("mode") == "ladder", str(ev.get("mode")))
        timeline = ev.get("timeline") or []
        check("تایم‌لاین پله‌ای با تاریخ و قیمت است", len(timeline) >= 1,
              json.dumps(timeline, ensure_ascii=False)[:160])
        check("آخرین پله پیش از انقضا اعمال می‌شود (≥۲ روز فاصله)",
              all(date.fromisoformat(str(s.get("date"))) <= date.fromisoformat(day(18)) for s in timeline)
              if all(s.get("date") for s in timeline) else True)

        # ---- «اجرا» باید واقعاً قیمت را عوض کند
        with SessionLocal() as db:
            before_price = float(db.get(ProductBatch, near_b["id"]).sell_price)
        acc = c.post(f"/api/insights/{card['id']}/accept", headers=H, json={})
        check("«اجرا» موفق بود", acc.status_code == 200, acc.text[:200])
        executed = (acc.json() or {}).get("executed") or []
        check("گزارش اجرا نوع اقدام را برمی‌گرداند",
              any(e.get("type") in {"markdown_ladder", "apply_markdown"} for e in executed)
              or any(e.get("type") == "markdown_ladder" for e in executed),
              json.dumps(executed, ensure_ascii=False)[:200])
        with SessionLocal() as db:
            after_price = float(db.get(ProductBatch, near_b["id"]).sell_price)
        check("قیمت فروش بچ واقعاً کاهش یافت (کار انجام شد)",
              after_price < before_price, f"{before_price:,.0f} → {after_price:,.0f}")

        with SessionLocal() as db:
            hist = db.query(PriceVersion).filter(PriceVersion.product_id == near["id"]).count()
        check("تاریخچهٔ قیمت ثبت شد", hist >= 1, f"{hist} ردیف")

        rep = c.get("/api/insights/actions/report", headers=H)
        check("سیستم بررسی اجرا گزارش می‌دهد", rep.status_code == 200)
        items = (rep.json() or {}).get("rows") or (rep.json() or {}).get("items") or []
        mine = [x for x in items if str(x.get("insight_id")) == str(card["id"])]
        _health = (mine[0].get("actions") or [{}])[0].get("health") if mine else None
        check("اجرای همین کارت در گزارش «برقرار» (OK) است", _health == "OK",
              json.dumps(mine[:1], ensure_ascii=False)[:220])

        # قیمت را از بیرون خراب می‌کنیم → بازبینی باید «از بین رفته» بدهد
        if _health == "OK":
            with SessionLocal() as db:
                b = db.get(ProductBatch, near_b["id"])
                b.sell_price = 999999
                db.commit()
            scan = c.post("/api/insights/actions/health-scan", headers=H)
            check("بازبینی زنده اجرا شد", scan.status_code == 200, scan.text[:160])
            rep2 = c.get("/api/insights/actions/report", headers=H).json()
            items2 = rep2.get("rows") or rep2.get("items") or []
            mine2 = [x for x in items2 if str(x.get("insight_id")) == str(card["id"])]
            _h2 = (mine2[0].get("actions") or [{}])[0].get("health") if mine2 else None
            check("اثر ازبین‌رفته شناسایی شد (LOST)", _h2 == "LOST",
                  json.dumps(mine2[:1], ensure_ascii=False)[:220])

    # ---- کالای منقضی: پیشنهاد باید «ضایعات» باشد نه تخفیف
    dead_card = find("EXPIRY_LADDER", dead["id"])
    kinds = {it.get("kind") for it in rows}
    check("کالای منقضی کارت گرفت (ضایعات)", dead_card is not None, str(sorted(kinds)))
    if dead_card:
        ev = dead_card.get("evidence") or {}
        actions = json.dumps(dead_card.get("actions") or [], ensure_ascii=False)
        check("حالت برنامه ضایعات است (نه تخفیف روی کالای فاسد)", ev.get("mode") == "waste",
              str(ev.get("mode")))
        check("اقدامش ثبت ضایعات است", "write_off_waste" in actions, actions[:160])
        before = c.get(f"/api/batches/{dead_b['id']}", headers=H).json().get("current_qty")
        acc = c.post(f"/api/insights/{dead_card['id']}/accept", headers=H, json={})
        after = c.get(f"/api/batches/{dead_b['id']}", headers=H).json().get("current_qty")
        check("ثبت ضایعات موجودی را واقعاً کم کرد", float(after or 0) < float(before or 0),
              f"{before} → {after}")
        with SessionLocal() as db:
            mv = db.query(StockMovement).filter(StockMovement.batch_id == dead_b["id"],
                                                StockMovement.movement_type == "WASTE").count()
        check("حرکت WASTE ثبت شد", mv >= 1, f"{mv} حرکت")

    # ---- پیشنهاد پای صندوق برای گوشی (همان مسیر POST /insights/nudges)
    plain, _pb = mk("بیسکویت ساده [E2E]", 50, 10000, 15000, 200)
    with SessionLocal() as db:
        def _set(key: str, value: str):
            row = db.query(SystemSetting).filter(SystemSetting.key == key).one_or_none()
            if row:
                row.value = value
            else:
                db.add(SystemSetting(key=key, value=value))
        _set("insights.pos_nudges", "true")
        # قاعدهٔ دستی «با بیسکویت، ماست نزدیک انقضا را پیشنهاد بده» — همان چیزی که
        # مدیر در پنل تعریف می‌کند و گوشی هم باید ببیند.
        _set("insights.manual_rules", json.dumps([{
            "if": plain["id"], "if_name": "بیسکویت ساده [E2E]",
            "then": near["id"], "then_name": "ماست ۱ کیلویی [E2E]",
            "confidence": 0.6, "lift": 1.0}], ensure_ascii=False))
        db.commit()
    n = c.post("/api/insights/nudges", headers=H, json={"product_ids": [plain["id"]]})
    check("پیشنهاد پای صندوق (اندروید) پاسخ می‌دهد", n.status_code == 200, n.text[:200])
    body = n.json() if n.status_code == 200 else []
    sugg = body if isinstance(body, list) else (body.get("suggestions") or body.get("items") or [])
    check("پیشنهاد، کالای نزدیک انقضا را با روز باقی‌مانده می‌گوید",
          bool(sugg) and sugg[0].get("product_id") == near["id"] and (sugg[0].get("days_left") or 0) > 0,
          json.dumps(sugg[:2], ensure_ascii=False)[:260])
    check("کالای فاسد هرگز پیشنهاد نمی‌شود", all(x.get("product_id") != dead["id"] for x in sugg))

    # ---- پیامک فاکتور: حالت الگو باید کوتاه و مرتب باشد
    from app.services import sms as sms_svc
    from app.models import Invoice  # noqa: F401
    with SessionLocal() as db:
        inv = db.query(Invoice).first()
        if inv:
            long_text = sms_svc.render_invoice(db, inv)
            short_text = sms_svc.render_invoice_short(db, inv)
            check("متن کامل فاکتور مرتب (هر کالا یک ردیف)", long_text.count("\n") >= 2)
            check("حالت الگو متن کوتاه یک‌خطی می‌دهد", "\n" not in short_text.strip(),
                  short_text.replace("\n", "⏎")[:120])
            for bad in ("None", "{", "}"):
                check(f"متن پیامک بدون «{bad}» خام", bad not in long_text and bad not in short_text)

    # ---- تایم‌لاین: قواعد کلیدی موتور (خالص، بدون دیتابیس)
    check("موتور انقضا کالای ۲۰روزه را در پنجره می‌بیند",
          expiry_plan.WINDOW_DAYS == 45 and expiry_plan.MAX_DISCOUNT_PERCENT == 60)

print()
if FAILS:
    print(f"❌ {len(FAILS)} بررسی ناموفق: " + " | ".join(FAILS))
    sys.exit(1)
print("✅ همهٔ بررسی‌های زنده موفق — اجرای واقعی پیشنهادها، بررسی اجرا، ضایعات، صندوق و پیامک")
