# -*- coding: utf-8 -*-
"""کیت UI نیتیو: فونت وزیرمتن، راست‌به‌چپ، کارت‌ها و جدول‌های هم‌زبان در همهٔ صفحات."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QIcon, QPalette
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QHeaderView, QLabel,
                               QTableWidget, QVBoxLayout, QWidget)

PRIMARY = "#4f46e5"        # نیلی برند رسا
PRIMARY_DARK = "#3730a3"
BG = "#f5f6fa"
CARD = "#ffffff"
TEXT = "#111827"
MUTED = "#6b7280"
GREEN = "#15803d"
RED = "#b91c1c"
AMBER = "#b45309"
LINE = "#e5e7eb"


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
    palette.setColor(QPalette.Base, QColor(CARD))
    palette.setColor(QPalette.AlternateBase, QColor("#fafafa"))
    palette.setColor(QPalette.Text, QColor(TEXT))
    palette.setColor(QPalette.Button, QColor(CARD))
    palette.setColor(QPalette.ButtonText, QColor(TEXT))
    palette.setColor(QPalette.Highlight, QColor(PRIMARY))
    palette.setColor(QPalette.HighlightedText, QColor("#ffffff"))
    palette.setColor(QPalette.ToolTipText, QColor(TEXT))
    app.setPalette(palette)
    app.setStyleSheet(f"""
        QWidget {{ font-size: 10pt; }}
        QLabel {{ background: transparent; }}
        QLabel[role="title"] {{ font-size: 14pt; font-weight: 700; color: {PRIMARY_DARK}; }}
        QLabel[role="muted"] {{ color: {MUTED}; font-size: 9pt; }}
        QPushButton {{
            background: {PRIMARY}; color: white; border: none; border-radius: 6px;
            padding: 8px 18px; font-weight: 600;
        }}
        QPushButton:hover {{ background: {PRIMARY_DARK}; }}
        QPushButton:disabled {{ background: #c7c9d1; }}
        QPushButton[role="ghost"] {{ background: transparent; color: {PRIMARY_DARK};
            border: 1px solid {LINE}; }}
        QPushButton[role="ghost"]:hover {{ background: #eef0ff; }}
        QPushButton[role="danger"] {{ background: {RED}; }}
        QPushButton[role="success"] {{ background: {GREEN}; }}
        QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QDateEdit {{
            border: 1px solid {LINE}; border-radius: 6px; padding: 6px 10px; background: white;
        }}
        QLineEdit:focus {{ border-color: {PRIMARY}; }}
        QTableWidget {{
            border: 1px solid {LINE}; border-radius: 8px; gridline-color: {LINE};
            selection-background-color: #eef0ff; selection-color: {TEXT};
        }}
        QHeaderView::section {{
            background: #eef0ff; color: {PRIMARY_DARK}; font-weight: 700;
            border: none; padding: 6px;
        }}
        QListWidget {{ border: none; background: transparent; }}
        QTabWidget::pane {{ border: 1px solid {LINE}; border-radius: 8px; background: white; }}
        QTabBar::tab {{ padding: 8px 18px; }}
        QTabBar::tab:selected {{ color: {PRIMARY_DARK}; font-weight: 700;
            border-bottom: 2px solid {PRIMARY}; }}
    """)


def card(title: str = "", parent: QWidget | None = None) -> tuple[QFrame, QVBoxLayout]:
    """کارت سفید استاندارد با عنوان — ساختار همهٔ صفحات."""
    frame = QFrame(parent)
    frame.setObjectName("card")
    frame.setStyleSheet(
        "QFrame#card { background: white; border: 1px solid #e5e7eb; border-radius: 12px; }")
    lay = QVBoxLayout(frame)
    lay.setContentsMargins(16, 14, 16, 14)
    lay.setSpacing(10)
    if title:
        t = QLabel(title)
        t.setProperty("role", "title")
        lay.addWidget(t)
    return frame, lay


def kpi_row(items: list[tuple[str, str, str]]) -> QWidget:
    """ردیف کارت‌های شاخص: [(عنوان، مقدار، رنگ)] — داشبورد نقش‌محور."""
    wrap = QWidget()
    lay = QHBoxLayout(wrap)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(10)
    for title, value, color in items:
        frame = QFrame()
        frame.setStyleSheet(
            f"QFrame {{ background: white; border: 1px solid {LINE}; border-radius: 12px;"
            f" border-{('top' if True else 'top')}: 3px solid {color}; }}")
        v = QVBoxLayout(frame)
        v.setContentsMargins(14, 12, 14, 12)
        cap = QLabel(title)
        cap.setProperty("role", "muted")
        val = QLabel(value)
        val.setStyleSheet(f"font-size: 15pt; font-weight: 800; color: {color};")
        v.addWidget(cap)
        v.addWidget(val)
        lay.addWidget(frame, 1)
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
