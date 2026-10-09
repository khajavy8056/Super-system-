# -*- coding: utf-8 -*-
"""کیت UI نیتیو: فونت وزیرمتن، راست‌به‌چپ، کارت‌ها و جدول‌های هم‌زبان در همهٔ صفحات."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QIcon, QPalette
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QHeaderView, QLabel,
                               QTableWidget, QVBoxLayout, QWidget)

#: پالت برند — تم تیرهٔ رسمی (تصاویر مرجع docs/screenshots/02,03، §۸)
PRIMARY = "#2563eb"        # آبی اکشن/انتخاب
PRIMARY_DARK = "#1d4ed8"
BG = "#0b1220"             # پس‌زمینهٔ پنجره
SURFACE = "#111a2e"        # کارت‌ها
SURFACE_2 = "#0e1626"      # سایدبار
TEXT = "#e6edf7"
MUTED = "#8fa3bf"
GREEN = "#22c55e"
RED = "#ef4444"
AMBER = "#f59e0b"
LINE = "#1f2b45"


def load_fonts(app) -> None:
    """فونت برند وزیرمتن از دارایی‌های بک‌اند — بومی، بدون وب‌فونت."""
    base = Path(__file__).resolve().parents[1]
    candidates = [base / "backend" / "app" / "assets" / "fonts",   # اجرا از مخزن
                  base / "app" / "assets" / "fonts"]               # نصب‌شده (frozen)
    for assets in candidates:
        for ttf in sorted(assets.glob("Vazirmatn-*.ttf")):
            QFontDatabase.addApplicationFont(str(ttf))
    if getattr(app, "_rasa_font_set", False):
        return
    font = QFont("Vazirmatn", 10)
    app.setFont(font)
    app.setLayoutDirection(Qt.RightToLeft)
    app._rasa_font_set = True


def apply_theme(app) -> None:
    app.setStyle("Fusion")
    palette = QPalette()
    palette.setColor(QPalette.Window, QColor(BG))
    palette.setColor(QPalette.WindowText, QColor(TEXT))
    palette.setColor(QPalette.Base, QColor(SURFACE))
    palette.setColor(QPalette.AlternateBase, QColor("#0d1526"))
    palette.setColor(QPalette.Text, QColor(TEXT))
    palette.setColor(QPalette.Button, QColor(SURFACE))
    palette.setColor(QPalette.ButtonText, QColor(TEXT))
    palette.setColor(QPalette.Highlight, QColor(PRIMARY))
    palette.setColor(QPalette.HighlightedText, QColor("#ffffff"))
    palette.setColor(QPalette.ToolTipText, QColor(TEXT))
    palette.setColor(QPalette.PlaceholderText, QColor(MUTED))
    app.setPalette(palette)
    app.setStyleSheet(f"""
        QWidget {{ font-size: 10pt; color: {TEXT}; }}
        QLabel {{ background: transparent; }}
        QLabel[role="title"] {{ font-size: 14pt; font-weight: 700; color: {TEXT}; }}
        QLabel[role="muted"] {{ color: {MUTED}; font-size: 9pt; }}
        QFrame#card, QFrame[frameShape="4"] {{ background: {SURFACE}; }}
        QPushButton {{
            background: {PRIMARY}; color: white; border: none; border-radius: 8px;
            padding: 9px 18px; font-weight: 600;
        }}
        QPushButton:hover {{ background: {PRIMARY_DARK}; }}
        QPushButton:disabled {{ background: #24304d; color: {MUTED}; }}
        QPushButton[role="ghost"] {{
            background: {SURFACE}; color: {TEXT}; border: 1px solid {LINE}; }}
        QPushButton[role="ghost"]:hover {{ border-color: {PRIMARY}; }}
        QPushButton[role="danger"] {{ background: #b91c1c; }}
        QPushButton[role="danger"]:hover {{ background: {RED}; }}
        QPushButton[role="success"] {{ background: #16a34a; }}
        QPushButton[role="success"]:hover {{ background: {GREEN}; }}
        QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QDateEdit {{
            border: 1px solid {LINE}; border-radius: 8px; padding: 7px 10px;
            background: {SURFACE}; selection-background-color: {PRIMARY};
        }}
        QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus,
        QDateEdit:focus {{ border-color: {PRIMARY}; }}
        QTableWidget {{
            border: 1px solid {LINE}; border-radius: 10px; gridline-color: {LINE};
            background: {SURFACE}; alternate-background-color: #0d1526;
            selection-background-color: {PRIMARY}; selection-color: white;
        }}
        QHeaderView::section {{
            background: {SURFACE}; color: {MUTED}; font-weight: 700;
            border: none; border-bottom: 1px solid {LINE}; padding: 7px;
        }}
        QTableWidget QTableCornerButton::section {{ background: {SURFACE}; border: none; }}
        QListWidget {{ border: none; background: transparent; }}
        QTabWidget::pane {{ border: 1px solid {LINE}; border-radius: 10px; background: {SURFACE}; }}
        QTabBar::tab {{ padding: 8px 18px; background: transparent; color: {MUTED}; }}
        QTabBar::tab:selected {{ color: {TEXT}; font-weight: 700;
            border-bottom: 2px solid {PRIMARY}; }}
        QScrollBar:vertical {{ background: transparent; width: 10px; }}
        QScrollBar::handle:vertical {{ background: #24304d; border-radius: 5px; min-height: 30px; }}
        QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
        QScrollBar:horizontal {{ background: transparent; height: 10px; }}
        QScrollBar::handle:horizontal {{ background: #24304d; border-radius: 5px; min-width: 30px; }}
        QDoubleSpinBox::up-button, QSpinBox::up-button,
        QDoubleSpinBox::down-button, QSpinBox::down-button {{ width: 18px; }}
        QDialog {{ background: {BG}; }}
    """)


def card(title: str = "", parent: QWidget | None = None) -> tuple[QFrame, QVBoxLayout]:
    """کارت سفید استاندارد با عنوان — ساختار همهٔ صفحات."""
    frame = QFrame(parent)
    frame.setObjectName("card")
    frame.setStyleSheet(
        f"QFrame#card {{ background: {SURFACE}; border: 1px solid {LINE};"
        f" border-radius: 12px; }}")
    lay = QVBoxLayout(frame)
    lay.setContentsMargins(16, 14, 16, 14)
    lay.setSpacing(10)
    if title:
        t = QLabel(title)
        t.setProperty("role", "title")
        lay.addWidget(t)
    return frame, lay


def kpi_row(items: list[tuple[str, str, str]]) -> QWidget:
    """کارت‌های شاخص در شبکهٔ ۳ستونه: [(عنوان، مقدار، رنگ)] — داشبورد نقش‌محور.

    شبکه به‌جای ردیف تک‌خطی: با ۵–۶ شاخص، کارت‌ها در نمایشگرهای معمولی بریده
    نمی‌شوند. کارتِ تختِ تیره مثل تصاویر مرجع (مقدار رنگی، عنوان خاکستری)."""
    from PySide6.QtWidgets import QGridLayout
    wrap = QWidget()
    grid = QGridLayout(wrap)
    grid.setContentsMargins(0, 0, 0, 0)
    grid.setHorizontalSpacing(10)
    grid.setVerticalSpacing(10)
    for index, (title, value, color) in enumerate(items):
        frame = QFrame()
        frame.setObjectName("kpiCard")   # سلکتور محدود: QFrame خام QLabel را هم می‌گیرد
        frame.setMinimumHeight(92)
        frame.setStyleSheet(
            f"QFrame#kpiCard {{ background: {SURFACE}; border: 1px solid {LINE};"
            f" border-radius: 12px; }}")
        v = QVBoxLayout(frame)
        v.setContentsMargins(14, 12, 14, 12)
        cap = QLabel(title)
        cap.setProperty("role", "muted")
        cap.setWordWrap(True)
        val = QLabel(value)
        val.setStyleSheet(f"font-size: 14pt; font-weight: 800; color: {color};")
        v.addWidget(cap)
        v.addWidget(val)
        grid.addWidget(frame, index // 3, index % 3)
    for col in range(3):
        grid.setColumnStretch(col, 1)
    return wrap


def make_table(headers: list[str]) -> QTableWidget:
    """جدول نیتیو هم‌زبان: فقط‌خواندنی، عرض منطقی، بدون ویرایش تصادفی."""
    t = QTableWidget(0, len(headers))
    t.setHorizontalHeaderLabels(headers)
    t.verticalHeader().setVisible(False)
    t.setEditTriggers(QTableWidget.NoEditTriggers)
    t.setSelectionBehavior(QTableWidget.SelectRows)
    t.setAlternatingRowColors(True)
    h = t.horizontalHeader()
    h.setSectionResizeMode(QHeaderView.Stretch)
    h.setDefaultAlignment(Qt.AlignCenter)
    return t


def fill_row(table: QTableWidget, row: int, values: list[str], colors: list[str] | None = None) -> None:
    from PySide6.QtWidgets import QTableWidgetItem
    for col, value in enumerate(values):
        item = QTableWidgetItem(str(value))
        item.setTextAlignment(Qt.AlignCenter)
        if colors and col < len(colors) and colors[col]:
            item.setForeground(QColor(colors[col]))
        table.setItem(row, col, item)
