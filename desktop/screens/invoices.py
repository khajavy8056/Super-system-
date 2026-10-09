# -*- coding: utf-8 -*-
"""فاکتورها نیتیو — دقیقاً همان قواعد سرور (app/routers/invoices.py):

* مشاهده: مجوز ``reports.view``؛ بدون ``reports.view_all`` فقط فاکتورهای خودِ
  کاربر (build-490 §۲–۳) — هیچ نشتی داده بین کاربران (§۷).
* ابطال: مجوز ``pos.void_unpaid``؛ فاکتور پرداخت‌شده نیازمند ``pos.void_paid``
  و — طبق تنظیم ``security.require_admin_for_void_paid`` (پیش‌فرض «true» مثل
  سرور) — تایپ مجدد رمز عبور همین کاربر (§209). رد شدن = رویداد VOID_DENIED.
* رند کردن بهای تمام‌شده: فیلدهای هزینه فقط با ``pricing.view_cost`` دیده
  می‌شوند (§34) — در UI نیتیو هم هیچ ستونی از هزینه نمایش داده نمی‌شود.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QInputDialog, QLabel,
                               QLineEdit, QMessageBox, QPushButton,
                               QVBoxLayout, QWidget)
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.database import SessionLocal
from app.models import Invoice, InvoiceItem
from app.security import verify_password
from app.services import pos as pos_svc
from app.services.audit import write_audit

from .. import ui_kit
from ..app_context import Context, fa, money


def _load_invoice(db, invoice_id: int) -> Invoice | None:
    """فاکتور با اقلام و کالاها — برای استفادهٔ امن پس از بستن نشست (expunge)."""
    inv = db.execute(
        select(Invoice).where(Invoice.id == invoice_id)
        .options(selectinload(Invoice.items).selectinload(InvoiceItem.product))
    ).scalar_one_or_none()
    if inv is not None:
        db.expunge(inv)
    return inv


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
        self.void_btn = QPushButton("ابطال فاکتور انتخابی")
        self.void_btn.setProperty("role", "danger")
        self.void_btn.clicked.connect(self._void)
        row.addWidget(detail)
        if ctx.can("pos.void_unpaid"):
            row.addWidget(self.void_btn)
        row.addStretch(1)
        root.addLayout(row)
        self.table = ui_kit.make_table(self.HEADERS)
        self.table.doubleClicked.connect(self._detail)
        root.addWidget(self.table, 1)

    def _selected_id(self) -> int | None:
        row = self.table.currentRow()
        if row < 0:
            return None
        return self.table.item(row, 0).data(Qt.UserRole)

    def _detail(self, *_) -> None:
        iid = self._selected_id()
        if iid is None:
            QMessageBox.information(self, "انتخاب", "یک فاکتور را انتخاب کنید")
            return
        db = SessionLocal()
        try:
            invoice = _load_invoice(db, iid)
        finally:
            db.close()
        if invoice is None:
            return
        InvoiceDetailDialog(invoice, self).exec()

    # ---------- ابطال — همان قواعد مسیر POST /api/invoices/{id}/void ----------
    def _void(self) -> None:
        iid = self._selected_id()
        if iid is None:
            return
        db = SessionLocal()
        try:
            invoice = db.get(Invoice, iid)
            if invoice is None or invoice.status == "VOID":
                QMessageBox.information(self, "ابطال‌شده", "این فاکتور قبلاً باطل شده است")
                return
            # محدودهٔ دسترسی: بدون reports.view_all فقط فاکتور خودِ کاربر
            if not self.ctx.can("reports.view_all") and invoice.created_by != self.ctx.user.id:
                QMessageBox.warning(self, "دسترسی ناکافی",
                                    "فقط فاکتورهای ثبت‌شدهٔ خودِ شما قابل ابطال است")
                return
            admin_password = None
            if invoice.status == "PAID":
                if not self.ctx.can("pos.void_paid"):
                    QMessageBox.warning(self, "نیاز به مجوز",
                                        "ابطال فاکتور پرداخت‌شده مجوز «ابطال پرداخت‌شده» (pos.void_paid) می‌خواهد")
                    return
                if self.ctx.get_setting("security.require_admin_for_void_paid", "true").lower() == "true":
                    text, ok = QInputDialog.getText(
                        self, "تأیید امنیتی", "رمز عبور خود را وارد کنید:",
                        QLineEdit.Password)
                    if not ok:
                        return
                    merged = self.ctx._attached_user(db)
                    if not text or not verify_password(text, merged.password_hash):
                        write_audit(db, action="VOID_DENIED", user_id=self.ctx.user.id,
                                    entity_type="Invoice", entity_id=invoice.id,
                                    reference="admin password missing/invalid")
                        db.commit()
                        QMessageBox.critical(self, "رمز نادرست",
                                             "رمز عبور نادرست است؛ ابطال انجام نشد")
                        return
                    admin_password = text
            reason, ok = QInputDialog.getText(self, "ابطال فاکتور", "دلیل ابطال:")
            if not ok:
                return
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
        db = SessionLocal()
        try:
            stmt = select(Invoice).order_by(Invoice.id.desc()).limit(200)
            # build-490 §۲–۳ — بدون reports.view_all فقط سوابق فروش خودِ کاربر
            if not self.ctx.can("reports.view_all"):
                stmt = stmt.where(Invoice.created_by == self.ctx.user.id)
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
