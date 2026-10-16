# -*- coding: utf-8 -*-
"""صندوق فروش نیتیو — تمام امکانات §۱۱: فروش، «نگه داشتن فاکتور»، تخفیف،
کوپن، مشتری، چاپ آفلاین محلی. قیمت‌ها از Batch (سرور حقیقت واحد) می‌آیند."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QComboBox, QDialog, QDoubleSpinBox, QFormLayout,
                               QHBoxLayout, QHeaderView, QInputDialog, QLabel,
                               QLineEdit, QMessageBox, QPushButton, QSpinBox,
                               QTableWidget, QTableWidgetItem, QVBoxLayout,
                               QWidget)

from app.database import SessionLocal
from app.models import Customer, Product
from app.services import coupons as coupon_svc
from app.services import pos as pos_svc

from .. import ui_kit
from ..app_context import Context, fa, money


class CustomerPickDialog(QDialog):
    """انتخاب مشتری ثبت‌شده برای فروش دفتری/کوپن مشتری‌دار."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("انتخاب مشتری")
        self.customer_id: int | None = None
        lay = QVBoxLayout(self)
        self.term = QLineEdit()
        self.term.setPlaceholderText("نام یا شمارهٔ موبایل مشتری…")
        self.term.textChanged.connect(self._search)
        lay.addWidget(self.term)
        self.table = ui_kit.make_table(["نام", "موبایل"])
        self.table.doubleClicked.connect(self._pick)
        lay.addWidget(self.table, 1)
        self._search("")

    def _search(self, term: str) -> None:
        from sqlalchemy import select
        db = SessionLocal()
        try:
            stmt = select(Customer).where(Customer.is_active.is_(True))
            if (term or "").strip():
                like = f"%{term.strip()}%"
                stmt = stmt.where((Customer.name.ilike(like)) | (Customer.phone.ilike(like)))
            rows = db.execute(stmt.order_by(Customer.id.desc()).limit(30)).scalars().all()
            self.table.setRowCount(0)
            for c in rows:
                r = self.table.rowCount()
                self.table.insertRow(r)
                ui_kit.fill_row(self.table, r, [c.name, c.phone or "—"])
                self.table.item(r, 0).setData(Qt.UserRole, c.id)
        finally:
            db.close()

    def _pick(self, index) -> None:
        self.customer_id = self.table.item(index.row(), 0).data(Qt.UserRole)
        self.accept()


class HeldDialog(QDialog):
    """فهرست فاکتورهای نگه‌داشته‌شده — بازیابی با دوبار کلیک."""

    def __init__(self, ctx: Context, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.setWindowTitle("فاکتورهای نگه‌داشته‌شده")
        self.chosen_index: int | None = None
        lay = QVBoxLayout(self)
        self.table = ui_kit.make_table(["برچسب", "کاربر", "اقلام", "مجموع (تومان)"])
        self.table.doubleClicked.connect(self._pick)
        lay.addWidget(self.table)
        owners = {}
        if ctx.user is not None:
            from sqlalchemy import select
            from app.models import User as UserModel
            db = SessionLocal()
            try:
                for uid, uname in db.execute(select(UserModel.id, UserModel.username)).all():
                    owners[uid] = uname
            finally:
                db.close()
        carts = ctx.held_carts(None)
        for i, cart in enumerate(carts):
            total = sum(float(line.get("qty", 0)) * float(line.get("price", 0)) for line in cart.get("lines", []))
            r = self.table.rowCount()
            self.table.insertRow(r)
            ui_kit.fill_row(self.table, r, [cart.get("label", "—"),
                                            owners.get(cart.get("user_id"), "—"),
                                            fa(len(cart.get("lines", []))) + " قلم", money(total)])
            self.table.item(r, 0).setData(Qt.UserRole, i)
        if not carts:
            r = self.table.rowCount()
            self.table.insertRow(r)
            ui_kit.fill_row(self.table, r, ["فاکتور نگه‌داشته‌ای نیست", "—", "—", "—"])

    def _pick(self, index) -> None:
        self.chosen_index = self.table.item(index.row(), 0).data(Qt.UserRole)
        self.accept()


class CampaignPickDialog(QDialog):
    """فهرست جشنواره‌های واجد شرایط برای همین سبد (build-521).

    دقیقاً همان چیزی که صندوق اندروید و رابط وب می‌بینند: فقط جشنواره‌هایی که
    شرط‌هایشان با همین سبد جمع شده + دلیل اعمال‌نشدن بقیهٔ جشنواره‌های فعال.
    """

    def __init__(self, cart_total: Decimal, customer_id: int | None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("جشنواره‌های قابل اعمال")
        self.campaign_id: int | None = None
        lay = QVBoxLayout(self)
        head = QLabel("فقط جشنواره‌های سازگار با همین سبد؛ شرایط هنگام ثبت فروش دوباره بررسی می‌شود.")
        head.setProperty("role", "muted")
        lay.addWidget(head)
        self.table = ui_kit.make_table(["جشنواره", "مزیت", "نحوهٔ اعمال"])
        self.table.doubleClicked.connect(self._pick)
        lay.addWidget(self.table, 1)

        self.reasons = QLabel("")
        self.reasons.setProperty("role", "muted")
        self.reasons.setWordWrap(True)
        lay.addWidget(self.reasons)

        row = QHBoxLayout()
        row.addStretch(1)
        b_none = QPushButton("بدون جشنواره")
        b_none.setProperty("role", "ghost")
        b_none.clicked.connect(self.reject)
        row.addWidget(b_none)
        lay.addLayout(row)

        db = SessionLocal()
        try:
            options = coupon_svc.eligible_campaigns(
                db, amount=cart_total, customer_id=customer_id, include_auto_apply=True)
        except Exception:  # noqa: BLE001 — فهرست نبود = فقط بدون انتخاب، نه کرش
            options = []
        finally:
            db.close()
        for i, offer in enumerate(options):
            r = self.table.rowCount()
            self.table.insertRow(r)
            benefit = (f"{offer['discount_value']:g}٪"
                       if str(offer.get("discount_type", "")).upper() == "PERCENT"
                       else f"{money(offer['discount'])} تومان")
            ui_kit.fill_row(self.table, r, [offer["name"], benefit,
                                            "خودکار" if offer.get("auto_apply") else "انتخاب صندوق‌دار"])
            self.table.item(r, 0).setData(Qt.UserRole, int(offer["campaign_id"]))
            self.table.item(r, 0).setData(Qt.UserRole + 1, offer["name"])
        if not options:
            self.reasons.setText("هیچ جشنواره‌ای با این سبد جمع نشد؛ شرط/بازهٔ جشنواره‌ها را در «جشنواره‌ها» بررسی کنید.")

    def _pick(self, index) -> None:
        if index.row() < 0:
            return
        self.campaign_id = self.table.item(index.row(), 0).data(Qt.UserRole)
        self.accept()


class PosPage(QWidget):
    HEADERS = ["کالا", "تعداد", "قیمت واحد", "تخفیف", "جمع"]

    def __init__(self, ctx: Context):
        super().__init__()
        self.ctx = ctx
        self.cart: list[dict] = []       # {product_id, name, qty, price, discount}
        self.customer_id: int | None = None
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(10)

        top = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("اسکن بارکد یا جست‌وجوی نام کالا… (Enter = افزودن به سبد)")
        # Enter (F2 مرجع) = افزودن؛ Enter خالی = اسکن پیوسته بدون پاک‌کردن تمرکز
        self.search.returnPressed.connect(self._add_searched)
        top.addWidget(self.search, 1)
        held_btn = QPushButton("فاکتورهای نگه‌داشته")
        held_btn.setProperty("role", "ghost")
        held_btn.clicked.connect(self._show_held)
        top.addWidget(held_btn)
        root.addLayout(top)

        body = QHBoxLayout()
        # --- کاتالوگ ---
        left = QVBoxLayout()
        self.catalog = ui_kit.make_table(["کالا", "بارکد", "قیمت فروش"])
        self.catalog.doubleClicked.connect(self._add_from_catalog)
        left.addWidget(self.catalog, 1)
        # --- سبد ---
        right = QVBoxLayout()
        self.cart_table = QTableWidget(0, len(self.HEADERS))
        self.cart_table.setHorizontalHeaderLabels(self.HEADERS)
        self.cart_table.verticalHeader().setVisible(False)
        self.cart_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.cart_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        right.addWidget(self.cart_table, 1)

        form = QHBoxLayout()
        self.qty = QSpinBox()
        self.qty.setRange(1, 100000)
        self.qty.setPrefix("تعداد: ")
        self.disc = QDoubleSpinBox()
        self.disc.setRange(0, 10**9)
        self.disc.setDecimals(0)
        self.disc.setPrefix("تخفیف قلم: ")
        btn_add_qty = QPushButton("تغییر مورد انتخابی")
        btn_add_qty.setProperty("role", "ghost")
        btn_add_qty.clicked.connect(self._edit_selected)
        form.addWidget(self.qty)
        form.addWidget(self.disc)
        form.addWidget(btn_add_qty)
        form.addStretch(1)
        right.addLayout(form)

        actions = QHBoxLayout()
        b_cust = QPushButton("مشتری…")
        b_cust.setProperty("role", "ghost")
        b_cust.clicked.connect(self._pick_customer)
        b_disc = QPushButton("تخفیف فاکتور…")
        b_disc.setProperty("role", "ghost")
        b_disc.clicked.connect(self._invoice_discount)
        b_coupon = QPushButton("کوپن…")
        b_coupon.setProperty("role", "ghost")
        b_coupon.clicked.connect(self._coupon)
        # build-521 — برابری با اندروید/وب: انتخاب جشنواره در صندوق ویندوز
        b_campaign = QPushButton("جشنواره…")
        b_campaign.setProperty("role", "ghost")
        b_campaign.clicked.connect(self._campaigns)
        b_remove = QPushButton("حذف قلم")
        b_remove.setProperty("role", "danger")
        b_remove.clicked.connect(self._remove_line)
        actions.addWidget(b_cust)
        actions.addWidget(b_disc)
        actions.addWidget(b_coupon)
        actions.addWidget(b_campaign)
        actions.addWidget(b_remove)
        actions.addStretch(1)
        right.addLayout(actions)

        bottom = QHBoxLayout()
        self.total_label = QLabel("جمع کل: ۰")
        self.total_label.setStyleSheet("font-size: 13pt; font-weight: 800;")
        bottom.addWidget(self.total_label)
        bottom.addStretch(1)
        b_hold = QPushButton("نگه داشتن فاکتور (F8)")
        b_hold.setProperty("role", "ghost")
        b_hold.clicked.connect(self._hold)
        b_pay = QPushButton("ثبت فروش / پرداخت (F2)")
        b_pay.setProperty("role", "success")
        b_pay.clicked.connect(self._checkout)
        bottom.addWidget(b_hold)
        bottom.addWidget(b_pay)
        right.addLayout(bottom)

        left_w, right_w = QWidget(), QWidget()
        left_w.setLayout(left)
        right_w.setLayout(right)
        body.addWidget(left_w, 1)
        body.addWidget(right_w, 1)
        root.addLayout(body, 1)

        self.invoice_discount = Decimal(0)
        self.coupon_code = ""
        self.campaign_id: int | None = None
        self.campaign_name = ""
        self.coupon_discount = Decimal(0)
        self.campaign_discount = Decimal(0)
        self._load_catalog()

    # ---------- کاتالوگ ----------
    def _load_catalog(self, term: str = "") -> None:
        products = Context.find_products(term)
        self.catalog.setRowCount(0)
        db = SessionLocal()
        try:
            # قیمت همهٔ کالاهای صفحه با «یک» کوئری (همان سیاست recommend_batch)
            prices = pos_svc.recommend_price_map(db, products)
        finally:
            db.close()
        for p in products:
            sell = prices.get(p.id)
            r = self.catalog.rowCount()
            self.catalog.insertRow(r)
            ui_kit.fill_row(self.catalog, r, [p.name, p.barcode or "—", money(sell) if sell else "—"])
            it = self.catalog.item(r, 0)
            it.setData(Qt.UserRole, p.id)

    def _add_searched(self) -> None:
        """Enter روی کادر جست‌وجو (مثل F2 مرجع): افزودن به سبد + تمرکز دوباره
        برای اسکن پیوستهٔ بارکد — صندوق هرگز منتظر کلیک اضافه نمی‌ماند."""
        term = self.search.text().strip()
        if not term:
            return
        products = Context.find_products(term, limit=1)
        if products:
            self._add_product(products[0].id)
            self.search.clear()
            self._load_catalog()
            self.search.setFocus()
        else:
            QMessageBox.information(self, "یافت نشد", "کالایی با این نام/بارکد پیدا نشد")
            self.search.setFocus()

    def keyPressEvent(self, event) -> None:  # noqa: N802 — نام Qt
        """میان‌برهای صندوق مثل تصویر مرجع: F2 پرداخت، F8 نگه‌داشتن،
        Del حذف قلم انتخابی، Esc پاک‌کردن جست‌وجو."""
        from PySide6.QtCore import Qt as _Qt
        key = event.key()
        if key == _Qt.Key_F2:
            self._checkout()
        elif key == _Qt.Key_F8:
            self._hold()
        elif key == _Qt.Key_Delete:
            self._remove_line()
        elif key == _Qt.Key_Escape:
            self.search.clear()
            self.search.setFocus()
        else:
            super().keyPressEvent(event)

    def _add_from_catalog(self, index) -> None:
        pid = self.catalog.item(index.row(), 0).data(Qt.UserRole)
        self._add_product(pid)

    def _add_product(self, product_id: int) -> None:
        db = SessionLocal()
        try:
            p = db.get(Product, product_id)
            if p is None:
                return
            batch = pos_svc.recommend_batch(db, p)
            price = Decimal(str(batch.sell_price)) if batch and batch.sell_price else Decimal(0)
            name = p.name
        finally:
            db.close()
        for line in self.cart:
            if line["product_id"] == product_id:
                line["qty"] += 1
                self._render_cart()
                return
        self.cart.append({"product_id": product_id, "name": name,
                          "qty": self.qty.value(), "price": float(price),
                          "discount": float(self.disc.value())})
        self.qty.setValue(1)
        self.disc.setValue(0)
        self._render_cart()

    def _edit_selected(self) -> None:
        row = self.cart_table.currentRow()
        if not (0 <= row < len(self.cart)):
            return
        line = self.cart[row]
        line["qty"] = self.qty.value()
        line["discount"] = float(self.disc.value())
        self._render_cart()

    def _remove_line(self) -> None:
        row = self.cart_table.currentRow()
        if 0 <= row < len(self.cart):
            self.cart.pop(row)
            self._render_cart()

    # ---------- مشتری / تخفیف / کوپن ----------
    def _pick_customer(self) -> None:
        dlg = CustomerPickDialog(self)
        if dlg.exec() == QDialog.Accepted:
            self.customer_id = dlg.customer_id

    def _invoice_discount(self) -> None:
        text, ok = QInputDialog.getText(self, "تخفیف فاکتور", "مبلغ تخفیف کل (تومان):")
        if ok:
            try:
                self.invoice_discount = Decimal(text.strip() or "0")
            except Exception:  # noqa: BLE001
                self.invoice_discount = Decimal(0)

    def _coupon(self) -> None:
        text, ok = QInputDialog.getText(self, "کوپن", "کد کوپن:")
        if ok:
            self.coupon_code = text.strip()
            self._render_cart()

    def _campaigns(self) -> None:
        """build-521 — انتخاب جشنواره با همان فهرست معتبر فروشگاه."""
        if not self.cart:
            QMessageBox.information(self, "سبد خالی", "ابتدا کالا اضافه کنید")
            return
        dlg = CampaignPickDialog(self._cart_amount(), self.customer_id, self)
        if dlg.exec() == QDialog.Accepted and dlg.campaign_id is not None:
            self.campaign_id = int(dlg.campaign_id)
            self.campaign_name = self.table_campaign_name(dlg.campaign_id)
        elif dlg.result() == QDialog.Rejected and dlg.campaign_id is None:
            return
        self._render_cart()

    def table_campaign_name(self, campaign_id: int) -> str:
        from app.models import Campaign
        db = SessionLocal()
        try:
            row = db.get(Campaign, int(campaign_id))
            return row.name if row is not None else ""
        finally:
            db.close()

    def _cart_amount(self) -> Decimal:
        total = Decimal(0)
        for line in self.cart:
            total += Decimal(str(line["price"])) * Decimal(str(line["qty"])) - Decimal(str(line.get("discount", 0)))
        return max(Decimal(0), total - self.invoice_discount)

    def _price(self) -> dict:
        """قیمت‌گذاری معتبر سبد با تخفیف کوپن/جشنواره (منبع واحد = سرویس فروش)."""
        items = [pos_svc.CartItem(product_id=line["product_id"],
                                  quantity=Decimal(str(line["qty"])),
                                  discount=Decimal(str(line.get("discount", 0))))
                 for line in self.cart]
        db = SessionLocal()
        try:
            return pos_svc.price_cart(
                db, items=items, customer_id=self.customer_id,
                coupon_code=self.coupon_code or None,
                invoice_discount=self.invoice_discount or None,
                campaign_id=self.campaign_id,
                include_offers=False)
        finally:
            db.close()

    # ---------- نگه داشتن فاکتور (§۱۱) ----------
    def _hold(self) -> None:
        if not self.cart:
            QMessageBox.information(self, "سبد خالی", "چیزی برای نگه‌داشتن نیست")
            return
        label, ok = QInputDialog.getText(self, "نگه داشتن فاکتور", "برچسب (مثلاً نام مشتری):")
        if not ok:
            return
        self.ctx.hold_cart(self.ctx.user.id, {
            "label": (label or "بدون برچسب").strip(),
            "customer_id": self.customer_id,
            "coupon_code": self.coupon_code,
            "invoice_discount": float(self.invoice_discount),
            "lines": [dict(line) for line in self.cart],
            "created": datetime.now().isoformat(timespec="seconds"),
        })
        self._reset_cart()
        QMessageBox.information(self, "نگه داشته شد", "فاکتور نگه داشته شد؛ از «فاکتورهای نگه‌داشته» بازیابی کنید")

    def _show_held(self) -> None:
        dlg = HeldDialog(self.ctx, self)
        if dlg.exec() == QDialog.Accepted and dlg.chosen_index is not None:
            cart = self.ctx.pop_held_cart(dlg.chosen_index)
            if cart:
                self.cart = [dict(line) for line in cart.get("lines", [])]
                self.customer_id = cart.get("customer_id")
                self.coupon_code = cart.get("coupon_code", "")
                self.invoice_discount = Decimal(str(cart.get("invoice_discount", 0)))
                self._render_cart()

    # ---------- پرداخت ----------
    def _checkout(self) -> None:
        if not self.cart:
            QMessageBox.information(self, "سبد خالی", "هیچ کالایی در سبد نیست")
            return
        # دفاع در عمق: مجوز فروش دوباره روی دادهٔ تازه کنترل می‌شود (§۷)
        if not self.ctx.can("pos.sell"):
            QMessageBox.warning(self, "دسترسی ناکافی", "حساب شما مجوز فروش ندارد")
            return
        items = [pos_svc.CartItem(product_id=line["product_id"],
                                  quantity=Decimal(str(line["qty"])),
                                  discount=Decimal(str(line.get("discount", 0))))
                 for line in self.cart]
        db = SessionLocal()
        try:
            # build-521 — مبلغ قطعی از همان سرویس فروش می‌آید (تخفیف کوپن + جشنوارهٔ
            # خودکار + مالیات). پیش‌تر جمع سبد فقط تخفیف فاکتور را می‌دید و اگر
            # جشنوارهٔ خودکار فعال بود، مقایسهٔ «پرداخت = جمع فاکتور» در سرویس
            # می‌شکست (PAYMENT_MISMATCH) و فروش ثبت نمی‌شد.
            try:
                priced = pos_svc.price_cart(
                    db, items=items, customer_id=self.customer_id,
                    coupon_code=self.coupon_code or None,
                    invoice_discount=self.invoice_discount or None,
                    campaign_id=self.campaign_id, include_offers=True)
            except pos_svc.PosError as exc:
                QMessageBox.warning(self, "سبد نامعتبر", exc.message)
                return
            total = Decimal(str(priced["total"]))
            self.coupon_discount = Decimal(str(priced.get("coupon_discount", 0)))
            self.campaign_discount = Decimal(str(priced.get("campaign_discount", 0)))
            campaign = priced.get("campaign")
            if campaign:
                self.campaign_id = int(campaign["campaign_id"])
                self.campaign_name = campaign["name"]
            summary = [f"جمع کالاها: {money(priced['gross'])}"]
            if priced["discount"]:
                summary.append(f"تخفیف: {money(priced['discount'])}")
            if priced["coupon_discount"]:
                summary.append(f"کوپن {self.coupon_code}: {money(priced['coupon_discount'])}")
            if priced["campaign_discount"]:
                summary.append(f"جشنواره {self.campaign_name}: {money(priced['campaign_discount'])}")
            if priced["tax"]:
                summary.append(f"مالیات: {money(priced['tax'])}")
            summary.append(f"قابل پرداخت: {money(total)} تومان")
            hints = priced.get("issue_on_checkout") or []
            if hints:
                summary.append("🎁 کد تخفیف خرید بعدی با همین فاکتور صادر می‌شود: "
                               + " + ".join(str(h.get("name", "")) for h in hints))
            if QMessageBox.question(self, "تأیید فروش", "\n".join(summary),
                                    QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
                return
            try:
                invoice = pos_svc.checkout(
                    db, items=items, user=self.ctx.user,
                    customer_id=self.customer_id,
                    coupon_code=self.coupon_code or None,
                    invoice_discount=self.invoice_discount or None,
                    campaign_id=self.campaign_id,
                    payments=[{"method": "CASH", "amount": str(total)}],
                )
                # build-521 — کوپن خرید بعدی + پیامک فاکتور دقیقاً مثل اندروید/وب
                customer = db.get(Customer, self.customer_id) if self.customer_id else None
                extras = pos_svc.after_sale(db, invoice=invoice, customer=customer,
                                            user=self.ctx.user)
                db.commit()
            except pos_svc.PosError as exc:
                db.rollback()
                QMessageBox.warning(self, "فروش ناموفق", exc.message)
                return
            except Exception as exc:  # noqa: BLE001
                db.rollback()
                QMessageBox.critical(self, "خطا", f"فروش ثبت نشد: {exc}")
                return
            issued = extras.get("issued_coupon")
            note = f"فاکتور {fa(invoice.invoice_number)} — جمع: {money(invoice.total_amount)} تومان"
            if issued is not None:
                note += f"\n🎁 کد تخفیف خرید بعدی: {issued.code}"
            if extras.get("sms_id"):
                note += "\nپیامک فاکتور برای مشتری در صف ارسال قرار گرفت."
        finally:
            db.close()
        QMessageBox.information(self, "فروش ثبت شد", note)
        self._reset_cart()

    # ---------- نمایش ----------
    def _render_cart(self) -> None:
        self.cart_table.setRowCount(0)
        total = Decimal(0)
        for i, line in enumerate(self.cart):
            r = self.cart_table.rowCount()
            self.cart_table.insertRow(r)
            line_total = Decimal(str(line["price"])) * Decimal(str(line["qty"])) - Decimal(str(line.get("discount", 0)))
            total += line_total
            ui_kit.fill_row(self.cart_table, r, [
                line["name"], fa(line["qty"]), money(line["price"]),
                money(line.get("discount", 0)), money(line_total)])
            self.cart_table.item(r, 0).setData(Qt.UserRole, i)
        net = total - self.invoice_discount - self.coupon_discount - self.campaign_discount
        parts = [f"جمع کل: {money(total)}"]
        if self.invoice_discount:
            parts.append(f"− تخفیف فاکتور: {money(self.invoice_discount)}")
        if self.coupon_code:
            parts.append(f"− کوپن {self.coupon_code}: {money(self.coupon_discount)}")
        if self.campaign_id:
            parts.append(f"− جشنواره {self.campaign_name or ''}: {money(self.campaign_discount)}")
        parts.append(f"= {money(net)} تومان")
        self.total_label.setText(" ".join(parts))
        self._refresh_benefits()

    def _refresh_benefits(self) -> None:
        """build-521 — تخفیف کوپن/جشنواره و «کوپن خرید بعدی در راه است» را زنده نشان بده.

        پیش‌تر صندوق ویندوز مبلغ را بدون تخفیف جشنوارهٔ خودکار نشان می‌داد و هنگام
        ثبت فروش، مقایسهٔ پرداخت با جمعِ (تخفیف‌خوردهٔ) سرور می‌شکست. اکنون مبلغِ
        نمایش‌داده‌شده همان مبلغِ قطعی سرویس فروش است.
        """
        if not self.cart:
            self.coupon_discount = Decimal(0)
            self.campaign_discount = Decimal(0)
            return
        try:
            priced = self._price()
        except pos_svc.PosError as exc:
            self.coupon_discount = Decimal(0)
            self.campaign_discount = Decimal(0)
            self.total_label.setToolTip(f"بررسی مزایا: {exc.message}")
            return
        except Exception:  # noqa: BLE001 — نبود قیمت‌گذاری هرگز صندوق را نمی‌بندد
            return
        self.coupon_discount = Decimal(str(priced.get("coupon_discount", 0)))
        self.campaign_discount = Decimal(str(priced.get("campaign_discount", 0)))
        campaign = priced.get("campaign")
        if campaign and not self.campaign_id:
            # جشنوارهٔ «خودکار»: صندوق ویندوز هم مثل اندروید باید ببیند چه چیزی اعمال شد
            self.campaign_id = int(campaign["campaign_id"])
            self.campaign_name = campaign["name"]
        self.total_label.setText(
            f"جمع کل: {money(priced['gross'])}"
            + (f" − تخفیف: {money(priced['discount'])}" if priced["discount"] else "")
            + f" = {money(priced['total'])} تومان"
            + (f" + مالیات {money(priced['tax'])}" if priced["tax"] else ""))
        hints = priced.get("issue_on_checkout") or []
        if hints:
            names = " + ".join(h.get("name", "") for h in hints)
            self.total_label.setToolTip(f"🎁 با ثبت همین فاکتور، کد تخفیف خرید بعدی صادر می‌شود: {names}")
            self.total_label.setText(self.total_label.text() + "  🎁")

    def _reset_cart(self) -> None:
        self.cart = []
        self.customer_id = None
        self.coupon_code = ""
        self.invoice_discount = Decimal(0)
        self.campaign_id = None
        self.campaign_name = ""
        self.coupon_discount = Decimal(0)
        self.campaign_discount = Decimal(0)
        self._render_cart()

    def refresh(self) -> None:
        self._load_catalog(self.search.text().strip())
