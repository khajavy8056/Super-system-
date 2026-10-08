# -*- coding: utf-8 -*-
"""کالا و موجودی نیتیو: فهرست، ثبت کالا، دریافت Batch (ورود کالا) و اصلاح موجودی."""
from __future__ import annotations

from datetime import date

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDateEdit, QDialog, QDoubleSpinBox, QFormLayout,
                               QHBoxLayout, QLabel, QLineEdit, QMessageBox,
                               QPushButton, QVBoxLayout, QWidget)

from app.database import SessionLocal
from app.models import Product, ProductBatch
from app.services import catalog as catalog_svc
from app.services import inventory as inv_svc

from .. import ui_kit
from ..app_context import Context, fa, money


class ProductDialog(QDialog):
    def __init__(self, ctx: Context, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.setWindowTitle("کالای جدید")
        form = QFormLayout(self)
        self.barcode = QLineEdit()
        self.barcode.setPlaceholderText("خالی = تولید بارکد داخلی")
        self.name = QLineEdit()
        self.buy = QDoubleSpinBox(); self.buy.setRange(0, 10**12); self.buy.setDecimals(0)
        self.sell = QDoubleSpinBox(); self.sell.setRange(0, 10**12); self.sell.setDecimals(0)
        self.qty = QDoubleSpinBox(); self.qty.setRange(0, 10**9); self.qty.setDecimals(3)
        self.expiry = QDateEdit(); self.expiry.setCalendarPopup(True)
        self.expiry.setSpecialValueText("بدون انقضا")
        form.addRow("بارکد:", self.barcode)
        form.addRow("نام کالا *:", self.name)
        form.addRow("قیمت خرید:", self.buy)
        form.addRow("قیمت فروش:", self.sell)
        form.addRow("موجودی اولیه:", self.qty)
        form.addRow("انقضا:", self.expiry)
        btn = QPushButton("ثبت کالا")
        btn.clicked.connect(self._save)
        form.addRow(btn)

    def _save(self) -> None:
        name = self.name.text().strip()
        if not name:
            QMessageBox.warning(self, "ناقص", "نام کالا لازم است")
            return
        db = SessionLocal()
        try:
            try:
                product = catalog_svc.create_product(
                    db, barcode=self.barcode.text().strip() or None, name=name,
                    user=self.ctx.user)
                if self.qty.value() > 0:
                    catalog_svc.receive_batch(
                        db, product=product, quantity_received=self.qty.value(),
                        buy_price=self.buy.value(), sell_price=self.sell.value(),
                        expiry_date=(self.expiry.date().toPython()
                                     if self.expiry.date() != self.expiry.minimumDate() else None),
                        user=self.ctx.user)
                db.commit()
            except Exception as exc:  # noqa: BLE001 — CatalogError و بقیه با پیام
                db.rollback()
                QMessageBox.warning(self, "ثبت نشد", str(exc))
                return
        finally:
            db.close()
        self.accept()


class ReceiveDialog(QDialog):
    """ورود کالا (Batch جدید) روی کالای انتخابی — قیمت تاریخی بازنویسی نمی‌شود."""

    def __init__(self, ctx: Context, product: Product, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.product = product
        self.setWindowTitle(f"ورود کالا — {product.name}")
        form = QFormLayout(self)
        self.qty = QDoubleSpinBox(); self.qty.setRange(0.001, 10**9); self.qty.setDecimals(3)
        self.buy = QDoubleSpinBox(); self.buy.setRange(0, 10**12); self.buy.setDecimals(0)
        self.sell = QDoubleSpinBox(); self.sell.setRange(0, 10**12); self.sell.setDecimals(0)
        self.expiry = QDateEdit(); self.expiry.setCalendarPopup(True)
        self.expiry.setSpecialValueText("بدون انقضا")
        form.addRow("تعداد ورودی *:", self.qty)
        form.addRow("قیمت خرید *:", self.buy)
        form.addRow("قیمت فروش *:", self.sell)
        form.addRow("تاریخ انقضا:", self.expiry)
        btn = QPushButton("ثبت ورود کالا")
        btn.clicked.connect(self._save)
        form.addRow(btn)

    def _save(self) -> None:
        db = SessionLocal()
        try:
            try:
                catalog_svc.receive_batch(
                    db, product=self.product, quantity_received=self.qty.value(),
                    buy_price=self.buy.value(), sell_price=self.sell.value(),
                    expiry_date=(self.expiry.date().toPython()
                                 if self.expiry.date() != self.expiry.minimumDate() else None),
                    user=self.ctx.user)
                db.commit()
            except Exception as exc:  # noqa: BLE001
                db.rollback()
                QMessageBox.warning(self, "ثبت نشد", str(exc))
                return
        finally:
            db.close()
        self.accept()


class ProductsPage(QWidget):
    HEADERS = ["کالا", "بارکد", "موجودی", "قیمت فروش", "انقضای نزدیک‌ترین Batch"]

    def __init__(self, ctx: Context):
        super().__init__()
        self.ctx = ctx
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        row = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("جست‌وجو…")
        self.search.textChanged.connect(self.refresh)
        add = QPushButton("+ کالای جدید")
        add.clicked.connect(self._add_product)
        row.addWidget(self.search, 1)
        row.addWidget(add)
        root.addLayout(row)
        self.table = ui_kit.make_table(self.HEADERS)
        self.table.doubleClicked.connect(self._receive_for_selected)
        root.addWidget(self.table, 1)
        hint = QLabel("دوبار کلیک روی هر سطر = ورود کالا (Batch جدید)")
        hint.setProperty("role", "muted")
        root.addWidget(hint)

    def _add_product(self) -> None:
        dlg = ProductDialog(self.ctx, self)
        if dlg.exec() == QDialog.Accepted:
            self.refresh()

    def _receive_for_selected(self, index) -> None:
        pid = self.table.item(index.row(), 0).data(Qt.UserRole)
        db = SessionLocal()
        try:
            product = db.get(Product, pid)
        finally:
            db.close()
        if product is None:
            return
        dlg = ReceiveDialog(self.ctx, product, self)
        if dlg.exec() == QDialog.Accepted:
            self.refresh()

    def refresh(self) -> None:
        from sqlalchemy import func, select
        db = SessionLocal()
        try:
            stmt = (select(Product, func.coalesce(func.sum(ProductBatch.current_qty), 0))
                    .outerjoin(ProductBatch, (ProductBatch.product_id == Product.id)
                               & (ProductBatch.status == "ACTIVE"))
                    .where(Product.deleted_at.is_(None))
                    .group_by(Product.id))
            term = self.search.text().strip()
            if term:
                like = f"%{term}%"
                stmt = stmt.having((Product.name.ilike(like)) | (Product.barcode.ilike(like)))
            rows = db.execute(stmt.order_by(Product.name.asc()).limit(300)).all()
            self.table.setRowCount(0)
            for product, qty in rows:
                batch = db.execute(
                    select(ProductBatch).where(ProductBatch.product_id == product.id,
                                               ProductBatch.current_qty > 0,
                                               ProductBatch.status == "ACTIVE")
                    .order_by(ProductBatch.expiry_date.asc().nullslast()).limit(1)
                ).scalars().first()
                expiry = fa(batch.expiry_date) if batch and batch.expiry_date else "—"
                r = self.table.rowCount()
                self.table.insertRow(r)
                ui_kit.fill_row(self.table, r, [
                    product.name, product.barcode or "—",
                    fa(float(qty)) + " " + (product.unit.name if product.unit else ""),
                    money(batch.sell_price) if batch else "—", expiry])
                self.table.item(r, 0).setData(Qt.UserRole, product.id)
        finally:
            db.close()
