# -*- coding: utf-8 -*-
"""نقطهٔ ورود برنامهٔ دسکتاپ نیتیو.

QApplication ← ورود بومی ← پنجرهٔ اصلی. وضعیت تمام‌صفحه (پیش‌فرض نصب فروشگاهی)
مثل قبل با SUPERMARKET_KIOSK کنترل می‌شود: 1/خالی = تمام‌صفحه، 0 = پنجرهٔ
معمولی، kiosk = تمام‌صفحهٔ بدون قاب.
"""
from __future__ import annotations

import os
from pathlib import Path


def run_desktop_app(data_dir: Path, version: str = "", store_name: str = "رسا سیستم") -> int:
    """برنامهٔ دسکتاپ را اجرا می‌کند و تا بستن پنجره برمی‌گردد (0 = خروج عادی)."""
    import sys

    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    from . import ui_kit
    from .app_context import Context
    from .login import LoginDialog
    from .main_window import MainWindow

    app = QApplication.instance() or QApplication(sys.argv)
    ui_kit.load_fonts(app)
    ui_kit.apply_theme(app)
    app.setApplicationName("RasaSystem")
    app.setApplicationVersion(version)

    ctx = Context(data_dir)
    while True:
        login = LoginDialog(store_name=ctx.store_name() or store_name)
        if login.exec() != login.DialogCode.Accepted or login.user is None:
            return 0
        ctx.set_user(login.user)

        win = MainWindow(ctx, version=version)
        kiosk_env = os.environ.get("SUPERMARKET_KIOSK", "1").strip().lower()
        if kiosk_env in ("0", "false", "no", "windowed"):
            win.show()                # حالت پنجره‌ای فقط برای تعمیر/توسعه
        elif kiosk_env == "kiosk":
            win.setWindowFlags(Qt.FramelessWindowHint)   # صندوق قفل‌شده: بدون قاب
            win.showFullScreen()
        else:
            # پیش‌فرض (1/خالی): تمام‌صفحه — مثل نرم‌فروشی‌های واقعی
            win.showFullScreen()
        app.exec()
        if ctx.user is None:      # «خروج از حساب» → دوباره ورود
            continue
        return 0                  # پنجره بسته شد → پایان برنامه
