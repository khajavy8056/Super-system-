# -*- coding: utf-8 -*-
"""فاکتورها نیتیو: تاریخچه، جزئیات و ابطال با مجوز (pos.void_paid همان قاعدهٔ سرور)."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QLabel, QMessageBox,
                               QPushButton, QVBoxLayout, QWidget)

from app.database import SessionLocal
from app.models import Invoice, InvoiceItem
from app.services import pos as pos_svc
from app.services.timeservice import local_today

from .. import ui_kit
from ..app_context import Context, fa, money


class InvoiceDetailDialog(QDialog):
    def __init__(self, invoice: Invoice, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"فاکتور {invoice.invoice_number}")
        lay = QVBoxLayout(self)
        head = QLabel(f"{invoice.invoice_number} — {fa(str(invoice.created_at)[:10])} — "
                      f"وضعیت: {invoice.status}")
        head.setStyleSheet("font-weight: 700;")
        lay.addWidget(head)
        table = ui_kit.make_table(["کالا", "تعداد", "قیمت واحد", "جمع"])
        lay.addWidget(table, 1)
        total = 0
        for i, item in enumerate(invoice.items):
            ui_kit.fill_row(table, i, [item.product.name if item.product else "—",
                                       fa(float(item.qty)), money(item.unit_sell_price),
                                       money(item.subtotal)])
            total += float(item.subtotal)
        lbl = QLabel(f"جمع فاکتور: {money(total)} تومان")
        lbl.setStyleSheet("font-weight: 800; font-size: 12pt;")
        lay.addWidget(lbl)


class InvoicesPage(QWidget):
    HEADERS = ["شماره فاکتور", "تاریخ", "مبلغ (تومان)", "پرداخت", "وضعیت"]

    def __init__(self, ctx: Context):
        super().__init__()
        self.ctx = ctx
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        row = QHBoxLayout()
        detail = QPushButton("مشاهدهٔ جزئیات")
        detail.clicked.connect(self._detail)
        void = QPushButton("ابطال فاکتور انتخابی")
        void.setProperty("role", "danger")
        void.clicked.connect(self._void)
        row.addWidget(detail)
        row.addWidget(void)
        row.addStretch(1)
        root.addLayout(row)
        self.table = ui_kit.make_table(self.HEADERS)
        self.table.doubleClicked.connect(self._detail)
        root.addWidget(self.table, 1)

    def _selected_invoice(self) -> Invoice | None:
        row = self.table.currentRow()
        if row < 0:
            return None
        iid = self.table.item(row, 0).data(Qt.UserRole)
        db = SessionLocal()
        try:
            return db.get(Invoice, iid)
        finally:
            db.close()

    def _detail(self, *_) -> None:
        invoice = self._selected_invoice()
        if invoice is None:
            QMessageBox.information(self, "انتخاب", "یک فاکتور را انتخاب کنید")
            return
        InvoiceDetailDialog(invoice, self).exec()

    def _void(self) -> None:
        invoice = self._selected_invoice()
        if invoice is None:
            return
        if invoice.status == "VOID":
            QMessageBox.information(self, "ابطال‌شده", "این فاکتور قبلاً باطل شده است")
            return
        if self.ctx.get_setting("security.require_admin_for_void_paid", "0") in ("1", "true") \
                and not self.ctx.is_admin():
            QMessageBox.warning(self, "نیاز به مدیر",
                                "ابطال فاکتور پرداخت‌شده فقط با حساب مدیر مجاز است")
            return
        reason, ok = Q_INPUT(self, "ابطال فاکتور", "دلیل ابطال:")
        if not ok:
            return
        db = SessionLocal()
        try:
            try:
                pos_svc.void_invoice(db, invoice=invoice, user=self.ctx.user, reason=reason)
                db.commit()
            except Exception as exc:  # noqa: BLE001 — PosError و بقیه
                db.rollback()
                QMessageBox.warning(self, "ابطال نشد", str(exc))
                return
        finally:
            db.close()
        self.refresh()

    def refresh(self) -> None:
        from sqlalchemy import select
        db = SessionLocal()
        try:
            stmt = select(Invoice).order_by(Invoice.id.desc()).limit(200)
            rows = db.execute(stmt).scalars().all()
            self.table.setRowCount(0)
            for inv in rows:
                r = self.table.rowCount()
                self.table.insertRow(r)
                color = ui_kit.MUTED if inv.status == "VOID" else ui_kit.TEXT
                ui_kit.fill_row(self.table, r, [
                    inv.invoice_number, fa(str(inv.created_at)[:10]),
                    money(inv.total_amount), inv.payment_method or "CASH", inv.status],
                    colors=[None, None, None, None, color])
                self.table.item(r, 0).setData(Qt.UserRole, inv.id)
        finally:
            db.close()


def Q_INPUT(parent, title, label):
    from PySide6.QtWidgets import QInputDialog
    return QInputDialog.getText(parent, title, label)
