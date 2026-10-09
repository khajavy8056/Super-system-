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
        b_remove = QPushButton("حذف قلم")
        b_remove.setProperty("role", "danger")
        b_remove.clicked.connect(self._remove_line)
        actions.addWidget(b_cust)
        actions.addWidget(b_disc)
        actions.addWidget(b_coupon)
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
            # پیش‌محاسبه برای مبلغ پرداخت (قیمت واقعی از Batch) — خطا = پیام، نه کرش
            try:
                resolved = pos_svc.validate_cart(db, items)
            except pos_svc.PosError as exc:
                QMessageBox.warning(self, "سبد نامعتبر", exc.message)
                return
            gross = sum((r.unit_sell_price * r.quantity for r in resolved), Decimal(0))
            disc = sum((r.discount for r in resolved), Decimal(0))
            total = gross - disc - self.invoice_discount
            if total < 0:
                QMessageBox.warning(self, "مبلغ نامعتبر",
                                    "تخفیف فاکتور بیشتر از جمع سبد است")
                return
            try:
                invoice = pos_svc.checkout(
                    db, items=items, user=self.ctx.user,
                    customer_id=self.customer_id,
                    coupon_code=self.coupon_code or None,
                    invoice_discount=self.invoice_discount or None,
                    payments=[{"method": "CASH", "amount": str(total)}],
                )
                db.commit()
            except pos_svc.PosError as exc:
                db.rollback()
                QMessageBox.warning(self, "فروش ناموفق", exc.message)
                return
            except Exception as exc:  # noqa: BLE001
                db.rollback()
                QMessageBox.critical(self, "خطا", f"فروش ثبت نشد: {exc}")
                return
        finally:
            db.close()
        QMessageBox.information(self, "فروش ثبت شد",
                                f"فاکتور {fa(invoice.invoice_number)} — جمع: {money(invoice.total_amount)} تومان")
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
        net = total - self.invoice_discount
        self.total_label.setText(f"جمع کل: {money(total)} − تخفیف: {money(self.invoice_discount)} = {money(net)} تومان")

    def _reset_cart(self) -> None:
        self.cart = []
        self.customer_id = None
        self.coupon_code = ""
        self.invoice_discount = Decimal(0)
        self._render_cart()

    def refresh(self) -> None:
        self._load_catalog(self.search.text().strip())
