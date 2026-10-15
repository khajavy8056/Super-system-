# -*- coding: utf-8 -*-
"""ورود بومی — بدون توکن/کوکی/نشست وب؛ bcrypt روی همان کاربران سرور."""
from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QFormLayout, QHBoxLayout, QLabel,
                               QLineEdit, QPushButton, QVBoxLayout)

from sqlalchemy import select

from app.database import SessionLocal
from app.models import User
from app.security import verify_password
from app.services import shifts as shift_svc
from app.services.audit import write_audit

from . import ui_kit


class LoginDialog(QDialog):
    """پنجرهٔ ورود نیتیو. خروجی: کاربر معتبر یا None (بستن = خروج از برنامه)."""

    def __init__(self, store_name: str = "رسا سیستم", parent=None):
        super().__init__(parent)
        self.user: User | None = None
        self.setWindowTitle(f"{store_name} — ورود")
        self.setMinimumWidth(380)

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 26, 28, 22)
        root.setSpacing(12)

        brand = QLabel(store_name)
        brand.setProperty("role", "title")
        brand.setAlignment(Qt.AlignCenter)
        sub = QLabel("برای ادامه وارد حساب کاربری خود شوید")
        sub.setProperty("role", "muted")
        sub.setAlignment(Qt.AlignCenter)
        root.addWidget(brand)
        root.addWidget(sub)

        form = QFormLayout()
        self.username = QLineEdit()
        self.username.setPlaceholderText("نام کاربری")
        self.password = QLineEdit()
        self.password.setPlaceholderText("رمز عبور")
        self.password.setEchoMode(QLineEdit.Password)
        form.addRow("نام کاربری:", self.username)
        form.addRow("رمز عبور:", self.password)
        root.addLayout(form)

        self.error = QLabel("")
        self.error.setStyleSheet(f"color: {ui_kit.RED};")
        self.error.setAlignment(Qt.AlignCenter)
        root.addWidget(self.error)

        row = QHBoxLayout()
        self.btn = QPushButton("ورود")
        self.btn.setDefault(True)
        self.btn.clicked.connect(self._login)
        row.addWidget(self.btn)
        root.addLayout(row)
        self.username.setFocus()

    def _login(self) -> None:
        username = self.username.text().strip()
        password = self.password.text()
        if not username or not password:
            self.error.setText("نام کاربری و رمز عبور لازم است")
            return
        db = SessionLocal()
        try:
            user = db.execute(
                select(User).where(User.username == username)
            ).scalar_one_or_none()
            if not user or not verify_password(password, user.password_hash) or not user.is_active:
                write_audit(db, action="USER_LOGIN_FAILED", entity_type="User", reference=username)
                db.commit()
                self.error.setText("نام کاربری یا رمز عبور نادرست است")
                self.password.clear()
                return
            # اتصال شیفت خودکار (همان رفتار ورود سرور)
            try:
                shift_svc.auto_enter_shift(db, user)
            except Exception:  # noqa: BLE001 — شیفت هرگز ورود را نمی‌بندد
                pass
            user.last_login_at = datetime.utcnow()
            write_audit(db, action="USER_LOGIN", user_id=user.id, entity_type="User", entity_id=user.id)
            db.commit()
            self.user = user
        finally:
            db.close()
        self.accept()
