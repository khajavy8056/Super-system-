# -*- coding: utf-8 -*-
"""اسکرین‌شات‌های نیتیو برنامهٔ دسکتاپ (offscreen) — راستی‌آزمایی بصری UI/UX §۸.

Usage (از پوشهٔ backend، با venv دارای PySide6):
    QT_QPA_PLATFORM=offscreen LD_LIBRARY_PATH=/tmp/qtstub \
        .venv/bin/python ../tools/screenshot_native_desktop.py [out-dir]

خروجی: PNGهای پنجرهٔ ورود، داشبورد نقش‌ها، صندوق فروش، کالا، گزارش‌ها،
تنظیمات و دیالوگ بازنشانی کارخانه — برای مقایسه با docs/screenshots/.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

_TMP = Path(tempfile.mkdtemp(prefix="rasa_shot_"))
os.environ["DATABASE_URL"] = f"sqlite:///{_TMP / 'shot.db'}"
os.environ.setdefault("SECRET_KEY", "screenshot-secret-key-that-is-long-enough")
os.environ.setdefault("ADMIN_USERNAME", "admin")
os.environ.setdefault("ADMIN_PASSWORD", "admin123")
os.environ.setdefault("SUPERMARKET_LICENSE_GATE", "0")

from datetime import timedelta  # noqa: E402
from decimal import Decimal  # noqa: E402

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication  # noqa: E402

from app.database import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Product  # noqa: E402
from app.security import hash_password  # noqa: E402
from app.services import catalog as catalog_svc  # noqa: E402
from app.services import pos as pos_svc  # noqa: E402
from app.services.timeservice import local_today  # noqa: E402

OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "docs" / "screenshots" / "native-desktop"
OUT.mkdir(parents=True, exist_ok=True)

from fastapi.testclient import TestClient  # noqa: E402

with TestClient(app) as tc:
    headers = {"Authorization": "Bearer " + tc.post(
        "/api/auth/login",
        data={"username": "admin", "password": "admin123"}).json()["access_token"]}
    db = SessionLocal()
    try:
        # دادهٔ نمونهٔ واقع‌گرا برای تصاویر
        samples = [
            ("شیر پگاه ۱ لیتر", "6260110000011", 18000, 22000, 40, 9),
            ("نان تست جو", "6260110000028", 35000, 45000, 25, 20),
            ("پنیر لیقوان ۴۰۰ گرم", "6260110000035", 95000, 128000, 12, 45),
            ("نوشابه خانواده ۱.۵", "6260110000042", 20000, 28000, 60, 120),
            ("برنج ایرانی ۵ کیلو", "6260110000059", 480000, 620000, 8, 300),
            ("رب گوجه چین‌چین", "6260110000066", 45000, 58000, 3, 400),
        ]
        today = local_today()
        for name, barcode, buy, sell, qty, exp_days in samples:
            product = Product(name=name, barcode=barcode)
            db.add(product)
            db.commit()
            catalog_svc.receive_batch(db, product=product, quantity_received=qty,
                                      buy_price=buy, sell_price=sell,
                                      expiry_date=today + timedelta(days=exp_days),
                                      user=None)
        db.commit()
        # چند فاکتور فروش برای داشبورد و گزارش (روی کالاهای خودم — کاتالوگ پیش‌فرض
        # سرور هم موقع بووت seed می‌شود؛ موجودی‌شان صفر است)
        products = db.execute(__import__("sqlalchemy", fromlist=["select"])
                              .select(Product)
                              .where(Product.barcode.like("62601100000%"))
                              .limit(3)).scalars().all()
        for p in products:
            batch = pos_svc.recommend_batch(db, p)
            price = Decimal(str(batch.sell_price)) if batch and batch.sell_price else Decimal("1000")
            total = price * 2
            pos_svc.checkout(db, items=[pos_svc.CartItem(
                product_id=p.id, quantity=Decimal("2"), discount=Decimal("0"))],
                payments=[{"method": "CASH", "amount": str(total)}])
        db.commit()
    finally:
        db.close()

from desktop import ui_kit  # noqa: E402
from desktop.app_context import Context  # noqa: E402
from desktop.login import LoginDialog  # noqa: E402
from desktop.main_window import MainWindow  # noqa: E402
from desktop.screens.settings import FactoryResetDialog  # noqa: E402

qt_app = QApplication.instance() or QApplication([])
ui_kit.load_fonts(qt_app)
ui_kit.apply_theme(qt_app)
qt_app.setApplicationName("RasaSystem")


def shoot(widget, name: str) -> None:
    widget.resize(1280, 800)
    widget.show()
    qt_app.processEvents()
    pix = widget.grab()
    pix.save(str(OUT / f"{name}.png"))
    widget.close()
    print("✓", OUT / f"{name}.png")


ctx = Context(_TMP)
login = LoginDialog(store_name="فروشگاه نمونه رسا")
shoot(login, "01-login")
db = SessionLocal()
try:
    from app.models import User
    admin = db.execute(__import__("sqlalchemy", fromlist=["select"])
                       .select(User).where(User.username == "admin")).scalar_one()
finally:
    db.close()
ctx.set_user(admin)

win = MainWindow(ctx, version="1.0.499")
shoot(win, "02-dashboard-admin")
for row, name in ((1, "03-pos"), (2, "04-products"), (4, "05-invoices"),
                  (5, "06-reports"), (7, "07-settings")):
    if row < win.nav.count():
        win.nav.setCurrentRow(row)
        qt_app.processEvents()
        pix = win.grab()
        pix.save(str(OUT / f"{name}.png"))
        print("✓", OUT / f"{name}.png")

dlg = FactoryResetDialog(ctx, win)
dlg._preview()
shoot(dlg, "08-factory-reset")
dlg.close()
win.close()
print("done →", OUT)
