# -*- coding: utf-8 -*-
"""مشتریان نیتیو: ثبت، دفتر حساب و تسویه — همان موتور ledger سرور."""
from __future__ import annotations

from decimal import Decimal

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QDoubleSpinBox, QFormLayout,
                               QHBoxLayout, QLabel, QLineEdit, QMessageBox,
                               QPushButton, QVBoxLayout, QWidget)

from app.database import SessionLocal
from app.models import Customer
from app.services import ledger as ledger_svc

from .. import ui_kit
from ..app_context import Context, fa, money


class CustomerDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("مشتری جدید")
        form = QFormLayout(self)
        self.name = QLineEdit()
        self.phone = QLineEdit()
        self.limit = QDoubleSpinBox()
        self.limit.setRange(0, 10**12)
        self.limit.setDecimals(0)
        form.addRow("نام *:", self.name)
        form.addRow("موبایل:", self.phone)
        form.addRow("سقف اعتبار:", self.limit)
        btn = QPushButton("ثبت مشتری")
        btn.clicked.connect(self._save)
        form.addRow(btn)

    def _save(self) -> None:
        name = self.name.text().strip()
        if not name:
            QMessageBox.warning(self, "ناقص", "نام مشتری لازم است")
            return
        db = SessionLocal()
        try:
            db.add(Customer(name=name, phone=self.phone.text().strip() or None,
                            credit_limit=Decimal(str(self.limit.value()))))
            db.commit()
        finally:
            db.close()
        self.accept()


class SettleDialog(QDialog):
    """تسویه جزئی/کامل دفتر حساب — همان قواعد ledger سرور."""

    def __init__(self, ctx: Context, customer: Customer, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.customer = customer
        self.setWindowTitle(f"تسویه — {customer.name}")
        db = SessionLocal()
        try:
            balance = ledger_svc.balance_of(db, customer.id)
        finally:
            db.close()
        form = QFormLayout(self)
        head = QLabel(f"ماندهٔ بدهی: {money(balance)} تومان")
        head.setStyleSheet("font-weight: 700;")
        form.addRow(head)
        self.amount = QDoubleSpinBox()
        self.amount.setRange(0, float(abs(balance)) or 1)
        self.amount.setDecimals(0)
        self.amount.setValue(float(abs(balance)))
        form.addRow("مبلغ تسویه:", self.amount)
        btn = QPushButton("ثبت تسویه")
        btn.clicked.connect(self._save)
        form.addRow(btn)

    def _save(self) -> None:
        db = SessionLocal()
        try:
            try:
                ledger_svc.settle(db, customer=self.customer,
                                  amount=Decimal(str(self.amount.value())),
                                  user=self.ctx.user)
                db.commit()
            except Exception as exc:  # noqa: BLE001 — LedgerError و امثالش
                db.rollback()
                QMessageBox.warning(self, "ثبت نشد", str(exc))
                return
        finally:
            db.close()
        self.accept()


class CustomersPage(QWidget):
    HEADERS = ["نام", "موبایل", "ماندهٔ دفتر (تومان)", "سقف اعتبار"]

    def __init__(self, ctx: Context):
        super().__init__()
        self.ctx = ctx
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        row = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("جست‌وجو…")
        self.search.textChanged.connect(self.refresh)
        add = QPushButton("+ مشتری جدید")
        add.clicked.connect(self._add)
        settle = QPushButton("تسویه دفتر انتخاب‌شده")
        settle.clicked.connect(self._settle)
        row.addWidget(self.search, 1)
        row.addWidget(add)
        row.addWidget(settle)
        root.addLayout(row)
        self.table = ui_kit.make_table(self.HEADERS)
        self.table.doubleClicked.connect(self._settle)
        root.addWidget(self.table, 1)

    def _add(self) -> None:
        dlg = CustomerDialog(self)
        if dlg.exec() == QDialog.Accepted:
            self.refresh()

    def _settle(self, *_) -> None:
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.information(self, "انتخاب", "یک مشتری را انتخاب کنید")
            return
        cid = self.table.item(row, 0).data(Qt.UserRole)
        db = SessionLocal()
        try:
            customer = db.get(Customer, cid)
        finally:
            db.close()
        if customer is None:
            return
        dlg = SettleDialog(self.ctx, customer, self)
        if dlg.exec() == QDialog.Accepted:
            self.refresh()

    def refresh(self) -> None:
        from sqlalchemy import select
        db = SessionLocal()
        try:
            stmt = select(Customer).where(Customer.deleted_at.is_(None))
            term = self.search.text().strip()
            if term:
                like = f"%{term}%"
                stmt = stmt.where((Customer.name.ilike(like)) | (Customer.phone.ilike(like)))
            rows = db.execute(stmt.order_by(Customer.id.desc()).limit(200)).scalars().all()
            self.table.setRowCount(0)
            for c in rows:
                balance = ledger_svc.balance_of(db, c.id)
                r = self.table.rowCount()
                self.table.insertRow(r)
                color = ui_kit.RED if balance > 0 else ui_kit.GREEN
                ui_kit.fill_row(self.table, r, [c.name, c.phone or "—", money(balance),
                                                money(c.credit_limit or 0)],
                                colors=[None, None, color, None])
                self.table.item(r, 0).setData(Qt.UserRole, c.id)
        finally:
            db.close()
