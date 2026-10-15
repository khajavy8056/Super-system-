# -*- coding: utf-8 -*-
"""build-508 — دو درخواست مالک + قفل ضددواگرایی:

۱) **نوار «پرفروش‌ها» پای صندوق** — پرفروش‌ترین کالاهای روزهای اخیر با تصویر،
   نواری افقی بالای صندوق تا صندوق‌دار بدون تایپ با یک لمس به سبد بیفزاید.
   endpoint جدید `/pos/fast-movers`: مرتب‌سازی واقعی بر پایهٔ فروش، حذف فاکتور
   ابطال‌شده، فقط کالای «الان قابل فروش»، و عیناً همان شکل آیتم‌های /pos/search
   (batches/unit) تا کلیک روی کاشی همان مسیر افزودن جست‌وجو را برود.

۲) **تصویر محصول به‌جای آیکون عمومی در پیشنهادهای هوش فروشگاه** — زنجیرهٔ
   to_dict → product_ids_of → attach_products باید تصویر واقعی کالا را کنار هر
   پیشنهادِ «کالای مشخص» بیاورد (ویندوز و اندروید هر دو از همین خروجی می‌خوانند).

۳) قرارداد سورس: کاشی POS ویندوز (loadFastMovers/pos-fast)، نوار اندروید
   (Db.fastMovers + SalesScreens.buildFastStrip) و گسترش fallback تصویر هوش
   در Images.insightIcon — اگر کسی یکی را بشکند، همین تست می‌شکند.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _mk_product(client, h, barcode, name, image_url=None):
    body = {"barcode": barcode, "name": name}
    if image_url:
        body["image_url"] = image_url
    r = client.post("/api/products", json=body, headers=h)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _receive(client, h, pid, qty, buy=10000, sell=40000):
    r = client.post("/api/batches/receive", headers=h, json={
        "product_id": pid, "quantity_received": qty, "buy_price": buy, "sell_price": sell})
    assert r.status_code == 201, r.text
    return r.json()


def _sell(client, h, pid, batch_id, qty):
    r = client.post("/api/pos/checkout", headers=h, json={
        "items": [{"product_id": pid, "batch_id": batch_id, "quantity": qty}],
        "payments": [{"method": "CASH", "amount": 40000 * qty}]})
    assert r.status_code == 201, r.text
    return r.json()["invoice_id"]


# ---------------------------------------------------------------- fast-movers

def test_fast_movers_order_excludes_and_shape(client, auth_headers):
    a = _mk_product(client, auth_headers, "6265081000001", "پرفروش نوع A")
    b = _mk_product(client, auth_headers, "6265081000002", "پرفروش نوع B")
    c = _mk_product(client, auth_headers, "6265081000003", "فروش‌نشدهٔ با موجودی")
    d = _mk_product(client, auth_headers, "6265081000004", "تمام‌فروش‌رفته")
    # تعدادهای فوق‌بزرگ تا ادعا در هر پایگاهی قطعی باشد (حتی پس از بازیابی دموی شبیه‌ساز
    # در تست‌های دیگر، هیچ فروش دمویی به ۱۰۰هزار واحد نمی‌رسد)
    ba = _receive(client, auth_headers, a, 120_000)["id"]
    bb = _receive(client, auth_headers, b, 60_000)["id"]
    _receive(client, auth_headers, c, 50)               # موجودی دارد، فروش ندارد
    bd = _receive(client, auth_headers, d, 4)["id"]
    inv_a = _sell(client, auth_headers, a, ba, 100_000)   # A پرفروش اول
    _sell(client, auth_headers, b, bb, 50_000)            # B دوم
    _sell(client, auth_headers, d, bd, 4)                 # D تمام موجودی‌اش فروخته شد

    r = client.get("/api/pos/fast-movers", headers=auth_headers)
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    ids = [x["product_id"] for x in items]
    by_id = {x["product_id"]: x for x in items}
    # ادعاهای نسبی (مستقل از فروش‌های دیگر همین پایگاه مشترک — مثلاً پس از بازیابی دمو):
    assert a in by_id and b in by_id, "دو کالای فروخته‌شده باید در نوار باشند"
    assert ids.index(a) < ids.index(b), "مرتب‌سازی پرفروشی: A (۱۰۰هزار) باید جلوتر از B (۵۰هزار) باشد"
    assert c not in by_id, "کالای بدون فروش نباید در نوار پرفروش‌ها باشد"
    assert d not in by_id, "کالای بی‌موجودی نباید پیشنهاد شود (فقط «الان قابل فروش»)"
    top = by_id[a]
    assert top["sold_qty"] == 100_000 and top["available_qty"] == 20_000
    # عین شکل /pos/search — تا کلیک روی کاشی همان مسیر افزودن جست‌وجو را برود
    for key in ("name", "barcode", "batches", "available_qty", "price_count", "unit"):
        assert key in top, f"آیتم fast-movers باید «{key}» داشته باشد (قرارداد /pos/search)"
    assert top["batches"] and top["batches"][0]["batch_id"] == ba

    # فاکتور ابطال‌شده از پرفروشی خارج می‌شود (باطل‌کردن فاکتور پرداخت‌شده = رمز مدیر)
    rv = client.post(f"/api/invoices/{inv_a}/void", headers=auth_headers,
                     json={"reason": "تست نوار پرفروش‌ها", "admin_password": "admin123"})
    assert rv.status_code in (200, 201), rv.text
    items2 = client.get("/api/pos/fast-movers", headers=auth_headers).json()["items"]
    assert a not in [x["product_id"] for x in items2], "فروشِ فاکتور ابطال‌شده نباید پرفروش بشمارد"


# ------------------------------------------------- تصویر محصول در پیشنهاد هوش

def test_insight_product_image_pipeline(client, auth_headers):
    """پیشنهادِ «کالای مشخص» باید رکورد Product (نام + image_url) را کنارش بیاورد —
    همان چیزی که آیکون کارت ویندوز و اندروید از آن می‌سازند."""
    img = "media/products/6265082000001.jpg"
    pid = _mk_product(client, auth_headers, "6265082000001", "کالای تصویردار هوش", image_url=img)
    from app.database import SessionLocal
    from app.models import Insight
    from app.services.timeservice import local_now
    s = SessionLocal()
    try:
        s.add(Insight(kind="VELOCITY", dedupe_key=f"product:{pid}", title=f"کالای تصویردار {pid}",
                      body="تست", priority=2, evidence="{}", actions="[]",
                      metric='{"metric": "availability", "product_id": %d, "window_days": 14}' % pid,
                      status="NEW", created_at=local_now(), updated_at=local_now()))
        s.commit()
    finally:
        s.close()
    rows = client.get("/api/insights", params={"status": "NEW", "kind": "VELOCITY"},
                      headers=auth_headers).json()
    row = next(x for x in rows if x.get("product_ids") == [pid])
    assert row["products"], "attach_products باید رکورد محصول را بیاورد"
    p0 = row["products"][0]
    assert p0["id"] == pid and p0["name"] == "کالای تصویردار هوش" and p0["image_url"] == img


# ------------------------------------------------------- قرارداد سورس دو سکو

def test_source_contract_both_platforms():
    web = (ROOT / "frontend/app.js").read_text("utf-8")
    assert "id=\"pos-fast\"" in web and "loadFastMovers" in web
    assert "/pos/fast-movers" in web and "posAddResolved(item)" in web
    css = (ROOT / "frontend/styles.css").read_text("utf-8")
    assert ".pos-fast" in css and ".pos-fast-item" in css
    sales = (ROOT / "mobile-android/app/src/main/java/ir/khajavy/supermarket/SalesScreens.java").read_text("utf-8")
    assert "buildFastStrip" in sales and "Db.fastMovers(12)" in sales and "Ui.thumb(c, p, 44)" in sales
    db = (ROOT / "mobile-android/app/src/main/java/ir/khajavy/supermarket/Db.java").read_text("utf-8")
    assert "fastMovers" in db and "SUM(ii.qty) sq" in db
    img = (ROOT / "mobile-android/app/src/main/java/ir/khajavy/supermarket/Images.java").read_text("utf-8")
    assert "spec.optLong(\"a\", spec.optLong(\"b\", 0))" in img, "fallback هوش باید metric.a/b را هم بخواند"
    ins = (ROOT / "mobile-android/app/src/main/java/ir/khajavy/supermarket/InsightScreens.java").read_text("utf-8")
    assert "Images.insightIcon(c, x, kindIcon(x.optString(\"kind\")), 0xFFFFFFFF, 26)" in ins, \
        "هیرو جزئیات پیشنهاد باید تصویر محصول را نشان دهد"
