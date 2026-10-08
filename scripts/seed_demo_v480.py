# -*- coding: utf-8 -*-
"""v4.8.0 — پرکردن فروشگاه نمایشی روی سرور زنده (برای پیش‌نمایش و تست UI).

یک فروشگاه واقعی‌نما می‌سازد: کالاهای ایرانی، بچ‌های با تاریخ‌های مختلف
(نزدیک انقضا، منقضی، تاریخ‌دار دور)، چند فروش در بازهٔ چرخش، تنظیمات فروشگاه و
یک قاعدهٔ دستی صندوق — بعد تحلیل‌گر را اجرا می‌کند تا کارت‌های واقعی بسازد.
"""
from __future__ import annotations

import json
import sys
from datetime import date, timedelta

import httpx

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
C = httpx.Client(base_url=BASE, timeout=60.0)

tok = C.post("/api/auth/login", data={"username": "admin", "password": "admin123"})
tok.raise_for_status()
H = {"Authorization": f"Bearer {tok.json()['access_token']}"}

#: (نام، قفسه، تعداد، خرید، فروش، روز تا انقضا)
ITEMS = [
    ("شیر پرچرب ۱ لیتری میهن", 240, 42000, 55000, 6),
    ("ماست موسیر ۹۰۰ گرمی", 180, 52000, 68000, 12),
    ("پنیر سفید ۴۰۰ گرمی", 150, 68000, 89000, 18),
    ("کره حیوانی ۱۰۰ گرمی", 90, 38000, 49000, 25),
    ("خامه صبحانه ۲۰۰ گرمی", 120, 44000, 57000, 3),
    ("دوغ گازدار ۱.۵ لیتری", 200, 35000, 45000, 40),
    ("آبمیوه طبیعی پرتقال", 160, 48000, 62000, 55),
    ("نوشابه قوطی ۳۳۰", 400, 25000, 35000, 200),
    ("بیسکویت کرمدار", 300, 18000, 26000, 150),
    ("چیپس نمکی ۷۵ گرمی", 250, 28000, 38000, 120),
    ("شکلات تخته‌ای تلخ", 120, 55000, 72000, 90),
    ("قهوه فوری ۱۰۰ گرمی", 60, 145000, 189000, 300),
    ("چای کیسه‌ای ۲۵ بسته", 140, 78000, 99000, 400),
    ("برنج ایرانی ۵ کیلویی", 45, 720000, 890000, None),
    ("روغن سرخ‌کردنی ۱.۸ لیتری", 70, 165000, 205000, 240),
    ("ماکارونی ۵۰۰ گرمی", 350, 22000, 31000, 365),
    ("رب گوجه فرنگی ۸۰۰ گرمی", 210, 62000, 79000, 300),
    ("کنسرو تن‌ماهی", 130, 92000, 118000, 500),
    ("نان تست جو", 80, 45000, 58000, 9),
    ("ژامبون مرغ ۳۰۰ گرمی", 40, 130000, 168000, -2),
    ("ماست چکیده سنتی ۲ کیلویی", 35, 210000, 268000, -5),
    ("خمیر پیتزا آماده", 55, 78000, 99000, 15),
    ("سالاد الویه بسته‌بندی", 30, 95000, 125000, 2),
    ("کیک یزدی بسته ۶ عددی", 66, 52000, 67000, 21),
]

products: dict[str, dict] = {}
for name, qty, buy, sell, days in ITEMS:
    p = C.post("/api/products", headers=H, json={"name": name}).json()
    body = {"product_id": p["id"], "quantity_received": qty, "buy_price": buy, "sell_price": sell}
    if days is not None:
        body["expiry_date"] = (date.today() + timedelta(days=days)).isoformat()
    b = C.post("/api/batches/receive", headers=H, json=body)
    b.raise_for_status()
    products[name] = {"product": p, "batch": b.json()}

# ---- چند فروش واقعی: گوشی/پنل داده داشته باشد و موتور سرعت فروش را حساب کند ----
import random
random.seed(7)
ok = 0
for i in range(26):
    names = random.sample(list(products), 3)
    lines = [{"product_id": products[n]["product"]["id"], "quantity": 1} for n in names]
    v = C.post("/api/pos/cart/validate", headers=H, json={"items": lines}).json()
    totals = v.get("totals") or {}
    total = totals.get("subtotal")
    if total is None:
        total = totals.get("gross")
    if not total:
        # v4.8.0 — اگر اعتبارسنجی همهٔ خط‌ها را رد کند (منقضی/ناموجود) جمع صفر (و در
        # Python «فالس») است؛ قبلاً `str(None or 0)` عملاً None می‌شد و صندوق ۴۲۲
        # می‌داد. فروشی که وجود ندارد را نمی‌فروشیم.
        continue
    r = C.post("/api/pos/checkout", headers=H, json={
        "items": lines, "payments": [{"method": "CASH", "amount": str(total)}]})
    if r.status_code in (200, 201):
        ok += 1
    else:
        print("checkout failed:", r.status_code, r.text[:160])
print(f"فروش ثبت‌شده: {ok}")

# ---- تنظیمات فروشگاه ----
for key, value in {
    "store.name": "فروشگاه بهار",
    "store.mobile": "09121112233",
    "pos.currency": "IRT",
    "insights.pos_nudges": "true",
    "insights.expiry_lead_days": "21",
}.items():
    C.put("/api/settings", headers=H, json={"key": key, "value": value})

# قاعدهٔ دستی صندوق: با «شیر» → «ماست موسیر» نزدیک انقضا پیشنهاد شود
plain = products["بیسکویت کرمدار"]["product"]
near = products["ماست موسیر ۹۰۰ گرمی"]["product"]
C.put("/api/settings", headers=H, json={"key": "insights.manual_rules", "value": json.dumps([{
    "if": plain["id"], "if_name": plain["name"], "then": near["id"], "then_name": near["name"],
    "confidence": 0.62, "lift": 1.4}], ensure_ascii=False)})

run = C.post("/api/insights/run", headers=H)
run.raise_for_status()
cards = C.get("/api/insights", headers=H, params={"status": "NEW", "limit": 100}).json()
kinds: dict[str, int] = {}
for c in cards:
    kinds[c["kind"]] = kinds.get(c["kind"], 0) + 1
print("کارت‌های ساخته‌شده:", json.dumps(kinds, ensure_ascii=False))
expiry = [c for c in cards if c["kind"] == "EXPIRY_LADDER"]
print(f"پیشنهادهای انقضا: {len(expiry)} — نمونه: {expiry[0]['title'] if expiry else '—'}")
