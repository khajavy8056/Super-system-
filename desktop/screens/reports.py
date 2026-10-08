# -*- coding: utf-8 -*-
"""گزارش‌ها نیتیو: فروش، کم‌موجودی و پرفروش‌ها — از همان سرویس گزارش سرور."""
from __future__ import annotations

from datetime import timedelta

from PySide6.QtWidgets import (QComboBox, QHBoxLayout, QLabel, QPushButton,
                               QTabWidget, QVBoxLayout, QWidget)

from app.database import SessionLocal
from app.services.reports import sales_report
from app.services.timeservice import local_today

from .. import ui_kit
from ..app_context import Context, fa, money


class ReportsPage(QWidget):
    def __init__(self, ctx: Context):
        super().__init__()
        self.ctx = ctx
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        tabs = QTabWidget()
        root.addWidget(tabs, 1)

        # --- فروش دوره‌ای ---
        sales_w = QWidget()
        lay = QVBoxLayout(sales_w)
        bar = QHBoxLayout()
        self.range = QComboBox()
        self.range.addItems(["۷ روز اخیر", "۳۰ روز اخیر", "۹۰ روز اخیر"])
        self.range.currentIndexChanged.connect(self.refresh)
        btn = QPushButton("به‌روزرسانی")
        btn.clicked.connect(self.refresh)
        bar.addWidget(QLabel("بازه:"))
        bar.addWidget(self.range)
        bar.addStretch(1)
        bar.addWidget(btn)
        lay.addLayout(bar)
        self.sales_table = ui_kit.make_table(["تاریخ", "تعداد فاکتور", "فروش (تومان)"])
        lay.addWidget(self.sales_table, 1)
        tabs.addTab(sales_w, "فروش")

        # --- کم‌موجودی ---
        low_w = QWidget()
        low_lay = QVBoxLayout(low_w)
        self.low_table = ui_kit.make_table(["کالا", "بارکد", "موجودی", "حداقل هشدار"])
        low_lay.addWidget(self.low_table, 1)
        tabs.addTab(low_w, "کم‌موجودی")

        self.refresh()

    def refresh(self) -> None:
        days = (7, 30, 90)[self.range.currentIndex()]
        end = local_today()
        start = end - timedelta(days=days - 1)
        db = SessionLocal()
        try:
            rep = sales_report(db, start, end, group="daily")
            rows = rep.get("rows", rep.get("daily", []))
            self.sales_table.setRowCount(0)
            for i, row in enumerate(rows if isinstance(rows, list) else []):
                r = self.sales_table.rowCount()
                self.sales_table.insertRow(r)
                ui_kit.fill_row(self.sales_table, r, [
                    fa(str(row.get("day", row.get("date", "—")))),
                    fa(row.get("invoices", row.get("count", 0))),
                    money(row.get("total", row.get("sum", 0)))])
            # کم‌موجودی
            from sqlalchemy import func, select
            from app.models import Product, ProductBatch
            low = db.execute(
                select(Product, func.coalesce(func.sum(ProductBatch.current_qty), 0))
                .outerjoin(ProductBatch, (ProductBatch.product_id == Product.id)
                           & (ProductBatch.status == "ACTIVE"))
                .where(Product.deleted_at.is_(None), Product.min_stock_alert > 0)
                .group_by(Product.id)
                .having(func.coalesce(func.sum(ProductBatch.current_qty), 0) <= Product.min_stock_alert)
                .order_by(func.coalesce(func.sum(ProductBatch.current_qty), 0).asc())
                .limit(100)).all()
            self.low_table.setRowCount(0)
            for product, qty in low:
                r = self.low_table.rowCount()
                self.low_table.insertRow(r)
                ui_kit.fill_row(self.low_table, r, [
                    product.name, product.barcode or "—", fa(float(qty)),
                    fa(product.min_stock_alert)],
                    colors=[None, None, ui_kit.RED, None])
        finally:
            db.close()
