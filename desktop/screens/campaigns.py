# -*- coding: utf-8 -*-
"""جشنواره‌ها نیتیو (build-514): عملکرد هر جشنواره در خود ویندوز.

تا این نسخه ویندوز نیتیو بخش جشنواره نداشت (فقط رابط وب) — درخواست مالک:
«گزارش‌های جشنواره در بخش جشنواره‌ها باشد: چند بار استفاده شده، چند کوپن
صادر شده، چقدر مصرف شده.» این صفحه فقط-خواندنی است (ساخت/ویرایش روی اندروید
و رابط وب؛ حذف تکرار منطق = قانون ساختاری) و آمار را مستقیم از سشن محلی
می‌خواند: استفاده، سقف، کوپن صادره، مجموع تخفیف داده‌شده، آخرین استفاده.
"""
from __future__ import annotations

from PySide6.QtWidgets import (QHBoxLayout, QHeaderView, QLabel, QPushButton,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from app.database import SessionLocal
from app.models.marketing import Campaign, Coupon
from sqlalchemy import func, select

from .. import ui_kit
from ..app_context import Context, fa, money


class CampaignsPage(QWidget):
    HEADERS = ["جشنواره", "مقدار", "وضعیت", "دفعات استفاده",
               "کوپن صادره", "مجموع تخفیف داده‌شده", "آخرین استفاده"]

    def __init__(self, ctx: Context):
        super().__init__()
        self.ctx = ctx
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        self.summary = QLabel("")
        self.summary.setProperty("role", "muted")
        root.addWidget(self.summary)
        row = QHBoxLayout()
        reload = QPushButton("به‌روزرسانی")
        reload.clicked.connect(self.refresh)
        row.addStretch(1)
        row.addWidget(reload)
        root.addLayout(row)
        self.table = ui_kit.make_table(self.HEADERS)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        root.addWidget(self.table, 1)
        hint = QLabel("ساخت/ویرایش جشنواره: از اندروید یا رابط وب — این صفحه گزارش عملکرد است.")
        hint.setProperty("role", "muted")
        root.addWidget(hint)
        self.refresh()

    def refresh(self) -> None:
        db = SessionLocal()
        try:
            issued = dict(db.execute(
                select(Coupon.campaign_id, func.count())
                .where(Coupon.campaign_id.is_not(None))
                .group_by(Coupon.campaign_id)).all())
            campaigns = db.execute(
                select(Campaign).order_by(Campaign.used_count.desc(), Campaign.id.desc())).scalars().all()
            self.table.setRowCount(0)
            total_used = total_issued = 0
            total_spent = 0.0
            for c in campaigns:
                issued_n = int(issued.get(c.id, 0))
                spent = float(c.used_count or 0)  # placeholder replaced below
                # مجموع تخفیف واقعی: از فاکتورهای پرداخت‌شده
                spent = float(db.execute(
                    select(func.coalesce(func.sum(_invoice_benefit()), 0))
                    .where(_invoice_campaign() == c.id, _invoice_status() == "PAID")
                ).scalar_one())
                last = db.execute(
                    select(func.max(_invoice_at()))
                    .where(_invoice_campaign() == c.id, _invoice_status() == "PAID")
                ).scalar_one()
                r = self.table.rowCount()
                self.table.insertRow(r)
                amount = (fa(c.discount_value) + "٪" if c.discount_type == "PERCENT"
                          else money(c.discount_value) + " تومان")
                ui_kit.fill_row(self.table, r, [
                    c.name + (" · خودکار" if c.auto_apply else ""),
                    amount,
                    {"ACTIVE": "فعال", "PAUSED": "متوقف", "ENDED": "پایان‌یافته"}.get(c.status, c.status),
                    fa(c.used_count) + (f" از {fa(c.usage_limit)}" if c.usage_limit else ""),
                    fa(issued_n),
                    money(spent),
                    fa(str(last)[:10]) if last else "—",
                ])
                total_used += int(c.used_count or 0)
                total_issued += issued_n
                total_spent += spent
            self.summary.setText(
                f"جشنواره‌ها: {fa(len(campaigns))} · مجموع استفاده: {fa(total_used)} · "
                f"کوپن صادرشده: {fa(total_issued)} · مجموع تخفیف داده‌شده: {money(total_spent)}")
        finally:
            db.close()


def _invoice_benefit():
    from app.models import Invoice
    return Invoice.benefit_amount


def _invoice_campaign():
    from app.models import Invoice
    return Invoice.campaign_id


def _invoice_status():
    from app.models import Invoice
    return Invoice.status


def _invoice_at():
    from app.models import Invoice
    return Invoice.created_at
