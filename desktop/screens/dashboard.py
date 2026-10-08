# -*- coding: utf-8 -*-
"""داشبورد نقش‌محور — نمای هر نقش از مجوزهای مؤثر می‌آید (§۹، مثل build-495 سرور)."""
from __future__ import annotations

from datetime import timedelta

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QFrame, QGridLayout, QLabel, QPushButton,
                               QVBoxLayout, QWidget)

from app.database import SessionLocal
from app.models import Invoice, ProductBatch, Product
from app.services.reports import dashboard as report_dashboard
from app.services.reports import dashboard_profile
from app.services.timeservice import local_now, local_today

from .. import ui_kit
from ..app_context import Context, fa, money


def _sales_by_day(db, days: int = 7) -> list[tuple]:
    """فروش ۷ روز اخیر برای نمودار نیتیو."""
    from sqlalchemy import func, select
    start = local_today() - timedelta(days=days - 1)
    rows = db.execute(
        select(func.date(Invoice.created_at), func.count(Invoice.id),
               func.sum(Invoice.total_amount))
        .where(Invoice.created_at >= start, Invoice.status != "VOID")
        .group_by(func.date(Invoice.created_at))
        .order_by(func.date(Invoice.created_at).asc())
    ).all()
    return [(str(r[0]), int(r[1] or 0), float(r[2] or 0)) for r in rows]


class MiniChart(QFrame):
    """نمودار میلهٔ نیتیو (QPainter) — بدون هیچ کتابخانهٔ وبی."""

    def __init__(self, data: list[tuple], parent=None):
        super().__init__(parent)
        self.data = data
        self.setMinimumHeight(170)

    def paintEvent(self, event):  # noqa: N802 — نام Qt
        from PySide6.QtGui import QPainter, QPen
        super().paintEvent(event)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        area = self.rect().adjusted(8, 12, -8, -26)
        p.setPen(QPen(ui_kit.LINE, 1))
        p.drawLine(area.left(), area.bottom(), area.right(), area.bottom())
        if not self.data:
            p.setPen(ui_kit.MUTED)
            p.drawText(self.rect(), Qt.AlignCenter, "فروشی ثبت نشده است")
            p.end()
            return
        peak = max((r[2] for r in self.data), default=1.0) or 1.0
        n = len(self.data)
        slot = area.width() / max(1, n)
        bar_w = max(10, int(slot * 0.55))
        for i, (_day, _cnt, total) in enumerate(self.data):
            h = int((total / peak) * max(1, area.height() - 6))
            x = int(area.left() + i * slot + (slot - bar_w) / 2)
            p.setBrush(ui_kit.PRIMARY)
            p.setPen(Qt.NoPen)
            p.drawRoundedRect(x, area.bottom() - h, bar_w, h, 4, 4)
            p.setPen(ui_kit.MUTED)
            p.drawText(int(area.left() + i * slot), area.bottom() + 4, slot,
                       18, Qt.AlignCenter, fa(_day[5:]))
        p.end()


class DashboardPage(QWidget):
    def __init__(self, ctx: Context):
        super().__init__()
        self.ctx = ctx
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(18, 18, 18, 18)
        self.lay.setSpacing(12)
        self.refresh()

    def refresh(self) -> None:
        while self.lay.count():
            item = self.lay.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        profile = self.ctx.dashboard_profile()
        db = SessionLocal()
        try:
            scope_user = None if profile in ("administrator", "supervisor", "manager") else self.ctx.user.id
            d = report_dashboard(db, user_id=scope_user)
            sales = d.get("sales", {}) or {}
            cur = money(sales.get("today_count", 0) and sales.get("today_sum") or 0)
            cur_cnt = money(sales.get("today_count", 0))
            yest = money(sales.get("yesterday_sum") or 0)
            month = money(sales.get("month_sum") or 0)
            inv_val = money(d.get("inventory_value") or 0)

            head = QLabel(f"داشبورد {self.ctx.user.full_name or self.ctx.user.username}")
            head.setProperty("role", "title")
            self.lay.addWidget(head)

            cards = [(f"فروش امروز (تومان)", cur, ui_kit.PRIMARY),
                     ("فاکتورهای امروز", cur_cnt, ui_kit.GREEN),
                     ("فروش دیروز", yest, ui_kit.MUTED),
                     ("فروش این ماه", month, ui_kit.AMBER)]
            if self.ctx.can("pricing.view_cost") or profile in ("administrator", "supervisor", "manager"):
                cards.append(("ارزش موجودی انبار", inv_val, ui_kit.PRIMARY_DARK))
            self.lay.addWidget(ui_kit.kpi_row(cards))

            # نقش‌ها: محتوای اختصاصی همان نقش (§۹)
            if profile == "seller":
                self.lay.addWidget(self._note(
                    "صندوق فروش آماده است — برای شروع فروش به «صندوق فروش» بروید. "
                    "آمار این داشبورد فقط فروش خودِ شماست."))
            elif profile == "accountant":
                profit = d.get("profit") or {}
                self.lay.addWidget(ui_kit.kpi_row([
                    ("سود امروز", money(profit.get("today") or 0), ui_kit.GREEN),
                    ("سود این ماه", money(profit.get("month") or 0), ui_kit.PRIMARY_DARK)]))
                self.lay.addWidget(self._note(
                    "خلاصهٔ مالی: سود واقعی بر پایهٔ بهای تمام‌شدهٔ Batch. "
                    "گزارش‌های کامل در «گزارش‌ها» و حساب مشتریان در «مشتریان» است."))
            else:
                chart_card, lay = ui_kit.card("فروش ۷ روز اخیر (تومان)")
                lay.addWidget(MiniChart(_sales_by_day(db)))
                self.lay.addWidget(chart_card)
                alerts = self._alerts(db)
                if alerts:
                    self.lay.addWidget(alerts)
            self.lay.addStretch(1)
        finally:
            db.close()

    def _note(self, text: str) -> QFrame:
        frame, lay = ui_kit.card()
        lbl = QLabel(text)
        lbl.setWordWrap(True)
        lbl.setProperty("role", "muted")
        lay.addWidget(lbl)
        return frame

    def _alerts(self, db) -> QFrame | None:
        """هشدارهای انقضا و کم‌موجودی — همان سطل‌های سرور، خلاصه‌شده."""
        from sqlalchemy import select
        today = local_today()
        soon = today + timedelta(days=30)
        expiring = db.execute(
            select(ProductBatch, Product.name)
            .join(Product, ProductBatch.product_id == Product.id)
            .where(ProductBatch.current_qty > 0, ProductBatch.status == "ACTIVE",
                   ProductBatch.expiry_date.is_not(None), ProductBatch.expiry_date <= soon)
            .order_by(ProductBatch.expiry_date.asc()).limit(8)
        ).all()
        if not expiring:
            return None
        frame, lay = ui_kit.card("هشدار انقضا — نزدیک‌ترین Batchها")
        grid = QGridLayout()
        grid.setHorizontalSpacing(24)
        for i, (batch, name) in enumerate(expiring):
            days = (batch.expiry_date - today).days
            color = ui_kit.RED if days < 0 else (ui_kit.AMBER if days <= 7 else ui_kit.TEXT)
            lbl = QLabel(f"{name} — {fa(batch.expiry_date)} ({'منقضی' if days < 0 else fa(days) + ' روز'})")
            lbl.setStyleSheet(f"color: {color};")
            grid.addWidget(lbl, i % 4, i // 4)
        lay.addLayout(grid)
        return frame
