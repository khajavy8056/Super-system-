"""Seed a realistic showcase dataset through the REAL API (blueprint §125).

Everything here goes through HTTP endpoints, so the data it produces is proof
that the endpoints work — not a direct database injection. Opt-in only; never
run against production.

Usage:  python -m scripts.seed_showcase [http://127.0.0.1:8000]
"""
from __future__ import annotations

import sys
from datetime import date, datetime, timedelta

import httpx

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
API = BASE.rstrip("/") + "/api"

PRODUCTS = [
    # (barcode, name, unit_name, sku, batches[(qty, buy, sell, consumer, expiry_days)])
    ("6260101010017", "شیر پرچرب کاله ۱ لیتری", "لیتر", "MLK-001",
     [(18, 42000, 52000, 55000, 5), (40, 46000, 58000, 62000, 21)]),
    ("6260101010024", "ماست موسیر دامداران ۹۰۰ گرم", "عدد", "YOG-014",
     [(24, 68000, 89000, 95000, 12)]),
    ("6260101010031", "پنیر لیقوان سنتی", "کیلوگرم", "CHS-220",
     [(12.750, 320000, 420000, 450000, 30)]),
    ("6260202020013", "برنج طارم هاشمی درجه یک", "کیلوگرم", "RIC-100",
     [(85.500, 148000, 189000, 199000, 400)]),
    ("6260202020020", "زعفران سرگل قائنات", "گرم", "SAF-001",
     [(250, 42000, 58000, 62000, 700)]),
    ("6260303030019", "روغن آفتابگردان لادن ۱.۸ لیتر", "عدد", "OIL-018",
     [(9, 165000, 210000, 225000, 200), (36, 182000, 235000, 249000, 320)]),
    ("6260404040016", "نوشابه کوکاکولا ۱.۵ لیتری", "عدد", "SDA-015",
     [(60, 28000, 39000, 42000, 150)]),
    ("6260404040023", "آب معدنی دماوند ۱.۵ لیتری", "عدد", "WTR-015",
     [(120, 8000, 13000, 15000, 300)]),
    ("6260505050013", "چای سیاه احمد ۵۰۰ گرم", "عدد", "TEA-500",
     [(22, 210000, 275000, 295000, 500)]),
    ("6260505050020", "شکر سفید بسته ۹۰۰ گرمی", "عدد", "SGR-900",
     [(45, 32000, 44000, 47000, 365)]),
    ("6260606060010", "تخم مرغ بسته ۲۰ عددی", "بسته", "EGG-020",
     [(30, 98000, 132000, 139000, 18)]),
    ("6260606060027", "مرغ تازه کشتار روز", "کیلوگرم", "CHK-001",
     [(48.250, 118000, 149000, 155000, 3)]),
    ("6260707070017", "ماکارونی زر ۷۰۰ گرم", "عدد", "PST-700",
     [(70, 26000, 36000, 39000, 400)]),
    ("6260707070024", "رب گوجه فرنگی چین چین ۸۰۰ گرم", "عدد", "TMT-800",
     [(38, 72000, 95000, 99000, 300)]),
    ("6260808080014", "دستمال کاغذی گلرنگ", "بسته", "TIS-001",
     [(52, 34000, 49000, 52000, 900)]),
    ("6260808080021", "مایع ظرفشویی پریل ۱ لیتری", "عدد", "DSH-100",
     [(28, 78000, 105000, 112000, 900)]),
    ("6260909090011", "بیسکویت مادر ساده", "عدد", "BIS-001",
     [(90, 9000, 14000, 16000, 120)]),
    ("6260909090028", "شکلات تلخ فرمند ۱۰۰ گرم", "عدد", "CHO-100",
     [(44, 45000, 65000, 69000, 220)]),
    ("6261010101018", "سیب زمینی درجه یک", "کیلوگرم", "POT-001",
     [(120.500, 22000, 34000, 36000, 25)]),
    ("6261010101025", "پیاز زرد", "کیلوگرم", "ONI-001",
     [(95.250, 18000, 29000, 31000, 30)]),
]

CUSTOMERS = [
    ("محمد رضایی", "09121234567"),
    ("زهرا کریمی", "09353334455"),
    ("علی موسوی", "09127778899"),
    ("سمیه احمدی", "09190001122"),
    ("حسن نوری", "09122223344"),
]


def main() -> None:
    c = httpx.Client(base_url=API, timeout=30)
    tok = c.post("/auth/login", data={"username": "admin", "password": "admin123"})
    tok.raise_for_status()
    h = {"Authorization": f"Bearer {tok.json()['access_token']}"}

    units = {u["name"]: u["id"] for u in c.get("/units", headers=h).json()}

    created = {}
    for barcode, name, unit, sku, batches in PRODUCTS:
        r = c.post("/products", headers=h, json={
            "barcode": barcode, "name": name, "sku": sku,
            "unit_id": units.get(unit), "min_stock_alert": 5})
        if r.status_code == 409:
            product = c.get(f"/products/barcode/{barcode}", headers=h).json()
        else:
            r.raise_for_status()
            product = r.json()
        created[barcode] = product
        existing = c.get(f"/batches?product_id={product['id']}", headers=h).json()
        if existing:
            continue
        for qty, buy, sell, consumer, days in batches:
            c.post("/batches/receive", headers=h, json={
                "product_id": product["id"], "quantity_received": qty,
                "buy_price": buy, "sell_price": sell, "consumer_price": consumer,
                "expiry_date": str(date.today() + timedelta(days=days))}).raise_for_status()

    customers = []
    for name, phone in CUSTOMERS:
        customers.append(c.post("/customers", headers=h,
                                json={"name": name, "phone": phone}).json())

    # Campaign + coupons
    camps = c.get("/marketing/campaigns", headers=h).json()
    if not camps:
        c.post("/marketing/campaigns", headers=h, json={
            "name": "جشنواره پاییزه", "discount_type": "PERCENT", "discount_value": 10,
            "min_purchase": 400000, "max_discount": 1000000,
            "auto_issue_threshold": 1500000, "auto_issue_validity_days": 30})
    if not c.get("/marketing/coupons", headers=h).json():
        c.post("/marketing/coupons", headers=h, json={
            "code": "WELCOME10", "discount_type": "PERCENT", "discount_value": 10,
            "min_purchase": 400000, "max_discount": 500000, "usage_limit": 100})
        c.post("/marketing/coupons", headers=h, json={
            "code": "VIP-50K", "discount_type": "FIXED", "discount_value": 50000,
            "min_purchase": 600000, "usage_limit": 1,
            "customer_id": customers[0]["id"],
            "valid_until": (datetime.utcnow() + timedelta(days=30)).isoformat()})

    # A few real sales through the POS endpoint
    if len(c.get("/invoices", headers=h).json().get("items", [])) < 4:
        sales = [
            ([("6260404040023", 6), ("6260909090011", 4)], customers[1]["id"], None),
            ([("6260202020013", 5.5), ("6260101010031", 1.25)], customers[0]["id"], "WELCOME10"),
            ([("6260303030019", 2), ("6260707070024", 3)], None, None),
            ([("6260606060010", 2), ("6260606060027", 2.5), ("6260101010017", 4)],
             customers[2]["id"], None),
        ]
        for lines, cust, coupon in sales:
            items = []
            for barcode, qty in lines:
                pid = created[barcode]["id"]
                opts = c.get(f"/pos/batch-options/{pid}", headers=h).json()["options"]
                if not opts:
                    continue
                items.append({"product_id": pid, "batch_id": opts[0]["batch_id"],
                              "quantity": qty})
            if not items:
                continue
            preview = c.post("/pos/cart/validate", headers=h,
                             json={"items": items, "coupon_code": coupon,
                                   "customer_id": cust}).json()
            total = preview["totals"]["subtotal"]
            c.post("/pos/checkout", headers=h, json={
                "items": items, "payments": [{"method": "CASH", "amount": total}],
                "customer_id": cust, "coupon_code": coupon})

    # An in-progress stocktaking session (so the resume UX is visible)
    sessions = c.get("/inventory/stocktake-sessions/active", headers=h).json()
    if not sessions:
        pids = [p["id"] for p in list(created.values())[:12]]
        st = c.post("/inventory/stocktakes", headers=h, json={
            "name": "انبارگردانی هفتگی — قفسه A", "area": "قفسه A",
            "product_ids": pids}).json()
        for i, item in enumerate(st["items"][:5]):
            delta = [0, -1, 0, 2, 0][i]
            c.post("/inventory/stocktakes/count", headers=h, json={
                "item_id": item["id"],
                "physical_qty": max(0, float(item["system_qty"]) + delta)})

    print(f"Showcase seeded: {len(created)} products, {len(customers)} customers, "
          f"{len(c.get('/invoices', headers=h).json().get('items', []))} invoices")


if __name__ == "__main__":
    main()
