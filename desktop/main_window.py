# -*- coding: utf-8 -*-
"""پنجرهٔ اصلی برنامهٔ ویندوزی: نوار کنار نیتیو + صفحات نقش‌محور.

منو بر اساس مجوزهای «همان کاربر» ساخته می‌شود (§۷/§۹) — امکان غیرمجاز اصلاً
در UI نمی‌آید؛ این فقط نمایش است و هر مسیر منطق نیز خودش مجوز را دوباره
کنترل می‌کند (مثل سرور).
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QListWidget,
                               QMainWindow, QMessageBox, QPushButton,
                               QStackedWidget, QVBoxLayout, QWidget)

from . import ui_kit
from .app_context import Context


class MainWindow(QMainWindow):
    def __init__(self, ctx: Context, version: str = ""):
        super().__init__()
        self.ctx = ctx
        self.version = version
        self.setWindowTitle(f"{ctx.store_name()} — رسا سیستم")
        self.resize(1280, 800)

        central = QWidget()
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ---- نوار کنار (نیتیو) ----
        side = QFrame()
        side.setFixedWidth(230)
        side.setStyleSheet(f"QFrame {{ background: {ui_kit.PRIMARY_DARK}; }}")
        side_lay = QVBoxLayout(side)
        side_lay.setContentsMargins(12, 18, 12, 12)
        side_lay.setSpacing(8)

        self.brand = QLabel(ctx.store_name())
        self.brand.setStyleSheet("color: white; font-size: 14pt; font-weight: 800;")
        self.user_label = QLabel(self.ctx.user.full_name or self.ctx.user.username)
        self.user_label.setStyleSheet("color: #c7d2fe; font-size: 9pt;")
        side_lay.addWidget(self.brand)
        side_lay.addWidget(self.user_label)
        side_lay.addSpacing(10)

        self.nav = QListWidget()
        self.nav.setStyleSheet("""
            QListWidget::item { color: #e0e7ff; padding: 10px 8px; border-radius: 8px; margin: 2px 0; }
            QListWidget::item:selected { background: rgba(255,255,255,0.16); color: white; font-weight: 700; }
        """)
        self.nav.currentRowChanged.connect(self._navigate)
        side_lay.addWidget(self.nav, 1)

        logout = QPushButton("خروج از حساب")
        logout.setProperty("role", "ghost")
        logout.setStyleSheet(
            "color: white; border: 1px solid rgba(255,255,255,0.4); border-radius: 6px; padding: 8px;")
        logout.clicked.connect(self._logout)
        side_lay.addWidget(logout)
        root.addWidget(side)

        # ---- صفحات ----
        self.stack = QStackedWidget()
        root.addWidget(self.stack, 1)
        self.setCentralWidget(central)
        self._build_pages()

    # ---------- ساخت صفحات مجاز ----------
    def _build_pages(self) -> None:
        from .screens.dashboard import DashboardPage
        from .screens.pos import PosPage
        from .screens.products import ProductsPage
        from .screens.customers import CustomersPage
        from .screens.invoices import InvoicesPage
        from .screens.users import UsersPage
        from .screens.reports import ReportsPage
        from .screens.settings import SettingsPage

        ctx = self.ctx
        pages: list[tuple[str, QWidget]] = []
        pages.append(("داشبورد", DashboardPage(ctx)))
        if ctx.can("pos.sell"):
            pages.append(("صندوق فروش", PosPage(ctx)))
        if ctx.can("products.view"):
            pages.append(("کالا و موجودی", ProductsPage(ctx)))
        if ctx.can("customers.manage") or ctx.can("customers.ledger"):
            pages.append(("مشتریان", CustomersPage(ctx)))
        if ctx.can("pos.sell") or ctx.can("reports.view"):
            pages.append(("فاکتورها", InvoicesPage(ctx)))
        if ctx.can("reports.view"):
            pages.append(("گزارش‌ها", ReportsPage(ctx)))
        if ctx.can("users.manage"):
            pages.append(("کاربران", UsersPage(ctx)))
        if ctx.can("settings.manage"):
            pages.append(("تنظیمات", SettingsPage(ctx)))

        for title, page in pages:
            self.nav.addItem(title)
            self.stack.addWidget(page)
        if self.nav.count():
            self.nav.setCurrentRow(0)

    def _navigate(self, row: int) -> None:
        if 0 <= row < self.stack.count():
            self.stack.setCurrentIndex(row)
            page = self.stack.widget(row)
            if hasattr(page, "refresh"):
                try:
                    page.refresh()
                except Exception as exc:  # noqa: BLE001 — هیچ صفحه نباید پنجره را ببندد
                    QMessageBox.warning(self, "خطا", f"به‌روزرسانی صفحه ناموفق بود: {exc}")

    def _logout(self) -> None:
        """خروج بومی: کاربر جاری پاک می‌شود — هیچ اثری از نشست باقی نمی‌ماند (§۷)."""
        if QMessageBox.question(self, "خروج", "از حساب خارج می‌شوید؟") != QMessageBox.Yes:
            return
        self.ctx.set_user(None)
        self.close()
