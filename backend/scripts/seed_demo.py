"""Seed the database with realistic demo data (blueprint §125).

Demo data must NEVER be loaded into production — this script is opt-in.
Usage:  python -m scripts.seed_demo
"""
from __future__ import annotations

import sys
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import SessionLocal, init_db  # noqa: E402
from app.models import Category, Product, User  # noqa: E402
from app.security import hash_password  # noqa: E402
from app.services.catalog import receive_batch  # noqa: E402

DEMO = [
    {
        "category": "Dairy", "product": {"barcode": "6260000000001", "name": "Milk X 1L", "unit": "Liter"},
        "batches": [
            {"qty": 8, "buy": 50000, "sell": 60000, "expiry": date.today() + timedelta(days=6)},
            {"qty": 20, "buy": 55000, "sell": 65000, "expiry": date.today() + timedelta(days=16)},
        ],
    },
    {
        "category": "Beverages", "product": {"barcode": "6260000000002", "name": "Soda X 300ml", "unit": "Can"},
        "batches": [
            {"qty": 5, "buy": 20000, "sell": 25000, "expiry": date.today() + timedelta(days=2)},
            {"qty": 30, "buy": 23000, "sell": 29000, "expiry": date.today() + timedelta(days=120)},
        ],
    },
    {
        "category": "Bakery", "product": {"barcode": "6260000000003", "name": "Bread Toast 500g", "unit": "Pack"},
        "batches": [{"qty": 40, "buy": 15000, "sell": 22000, "expiry": date.today() + timedelta(days=4)}],
    },
    {
        "category": "Snacks", "product": {"barcode": "6260000000004", "name": "Chips Classic", "unit": "Bag"},
        "batches": [{"qty": 60, "buy": 18000, "sell": 25000, "expiry": date.today() + timedelta(days=90)}],
    },
    {
        "category": "Household", "product": {"barcode": "6260000000005", "name": "Detergent 2kg", "unit": "Box"},
        "batches": [{"qty": 4, "buy": 90000, "sell": 120000, "expiry": date.today() + timedelta(days=300)}],
    },
]


def main() -> None:
    init_db()
    db = SessionLocal()
    try:
        # Demo cashier user.
        cashier = db.query(User).filter(User.username == "cashier").first()
        if not cashier:
            cashier = User(username="cashier", full_name="Demo Cashier", password_hash=hash_password("cashier123"))
            db.add(cashier)
            db.flush()
            from sqlalchemy import select
            from app.models import Role
            role = db.execute(select(Role).where(Role.name == "Cashier")).scalar_one_or_none()
            if role:
                cashier.roles.append(role)

        for item in DEMO:
            cat = db.query(Category).filter(Category.name == item["category"]).first()
            if not cat:
                cat = Category(name=item["category"])
                db.add(cat)
                db.flush()

            product = db.query(Product).filter(Product.barcode == item["product"]["barcode"]).first()
            if not product:
                product = Product(
                    barcode=item["product"]["barcode"], name=item["product"]["name"],
                    category_id=cat.id, min_stock_alert=5,
                )
                db.add(product)
                db.flush()
            existing = len(product.batches)
            if existing == 0:
                for b in item["batches"]:
                    receive_batch(
                        db, product=product, quantity_received=b["qty"],
                        buy_price=Decimal(b["buy"]), sell_price=Decimal(b["sell"]),
                        expiry_date=b["expiry"], received_at=datetime.utcnow(),
                    )
        db.commit()
        print(f"Seeded {len(DEMO)} demo products (with batches).")
    finally:
        db.close()


if __name__ == "__main__":
    main()
