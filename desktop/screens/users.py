# -*- coding: utf-8 -*-
"""کاربران و دسترسی‌ها نیتیو — همان نقش‌های استاندارد و مجوزهای سرور (§۷/§۹)."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QDialog, QFormLayout, QHBoxLayout,
                               QLabel, QLineEdit, QMessageBox, QPushButton,
                               QVBoxLayout, QWidget)
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.database import SessionLocal
from app.models import Role, User
from app.security import hash_password
from app.services.audit import write_audit

from .. import ui_kit
from ..app_context import Context, fa


class UserDialog(QDialog):
    def __init__(self, ctx: Context, user: User | None = None, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.user = user
        self.setWindowTitle("ویرایش کاربر" if user else "کاربر جدید")
        form = QFormLayout(self)
        self.username = QLineEdit()
        self.full_name = QLineEdit()
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.Password)
        self.password.setPlaceholderText("خالی = بدون تغییر رمز")
        self.active = QCheckBox("حساب فعال")
        self.active.setChecked(user.is_active if user else True)
        form.addRow("نام کاربری *:", self.username)
        form.addRow("نام کامل:", self.full_name)
        form.addRow("رمز عبور:", self.password)
        form.addRow("", self.active)
        form.addRow(QLabel("نقش‌ها:"))
        db = SessionLocal()
        try:
            roles = db.execute(select(Role).order_by(Role.id.asc())).scalars().all()
            self.role_boxes = []
            current = {r.name for r in user.roles} if user else set()
            for role in roles:
                box = QCheckBox(role.name)
                box.setChecked(role.name in current)
                self.role_boxes.append((role, box))
                form.addRow("", box)
        finally:
            db.close()
        btn = QPushButton("ذخیره")
        btn.clicked.connect(self._save)
        form.addRow(btn)
        if user:
            self.username.setText(user.username)
            self.username.setEnabled(False)
            self.full_name.setText(user.full_name or "")

    def _save(self) -> None:
        username = self.username.text().strip()
        if not username:
            QMessageBox.warning(self, "ناقص", "نام کاربری لازم است")
            return
        password = self.password.text()
        if not self.user and not password:
            QMessageBox.warning(self, "ناقص", "رمز عبور برای کاربر جدید لازم است")
            return
        # دفاع در عمق: صفحه فقط با users.manage ساخته می‌شود، ولی ذخیره دوباره کنترل می‌شود
        if not self.ctx.can("users.manage"):
            QMessageBox.warning(self, "دسترسی ناکافی", "مدیریت کاربران مجاز نیست")
            return
        db = SessionLocal()
        try:
            user = None if self.user is None else db.merge(self.user, load=True)
            if user is None:
                exists = db.execute(
                    select(User).where(User.username == username)).scalar_one_or_none()
                if exists:
                    QMessageBox.warning(self, "تکراری", "این نام کاربری قبلاً ثبت شده است")
                    return
                user = User(username=username)
                db.add(user)
            user.full_name = self.full_name.text().strip()
            user.is_active = self.active.isChecked()
            if password:
                user.password_hash = hash_password(password)
            chosen = {role.name: box.isChecked() for role, box in self.role_boxes}
            for role, box in self.role_boxes:
                if box.isChecked() and role not in user.roles:
                    user.roles.append(role)
                elif not box.isChecked() and role in user.roles:
                    user.roles.remove(role)
            write_audit(db, action="USER_UPDATED" if self.user else "USER_CREATED",
                        user_id=self.ctx.user.id, entity_type="User",
                        reference=username, after={"roles": [n for n, on in chosen.items() if on]})
            db.commit()
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            QMessageBox.warning(self, "ذخیره نشد", str(exc))
            return
        finally:
            db.close()
        self.accept()


class UsersPage(QWidget):
    HEADERS = ["نام کاربری", "نام کامل", "نقش‌ها", "وضعیت", "آخرین ورود"]

    def __init__(self, ctx: Context):
        super().__init__()
        self.ctx = ctx
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        row = QHBoxLayout()
        add = QPushButton("+ کاربر جدید")
        add.clicked.connect(self._add)
        edit = QPushButton("ویرایش انتخاب‌شده")
        edit.clicked.connect(self._edit)
        row.addWidget(add)
        row.addWidget(edit)
        row.addStretch(1)
        root.addLayout(row)
        self.table = ui_kit.make_table(self.HEADERS)
        self.table.doubleClicked.connect(self._edit)
        root.addWidget(self.table, 1)

    def _add(self) -> None:
        dlg = UserDialog(self.ctx, None, self)
        if dlg.exec() == QDialog.Accepted:
            self.refresh()

    def _edit(self, *_) -> None:
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.information(self, "انتخاب", "یک کاربر را انتخاب کنید")
            return
        uid = self.table.item(row, 0).data(Qt.UserRole)
        db = SessionLocal()
        try:
            user = db.execute(
                select(User).where(User.id == uid)
                .options(selectinload(User.roles))).scalar_one_or_none()
            if user is not None:
                db.expunge(user)
        finally:
            db.close()
        if user is None:
            return
        dlg = UserDialog(self.ctx, user, self)
        if dlg.exec() == QDialog.Accepted:
            self.refresh()

    def refresh(self) -> None:
        from sqlalchemy import select
        db = SessionLocal()
        try:
            rows = db.execute(select(User).order_by(User.id.asc())).scalars().all()
            self.table.setRowCount(0)
            for u in rows:
                r = self.table.rowCount()
                self.table.insertRow(r)
                ui_kit.fill_row(self.table, r, [
                    u.username, u.full_name or "—",
                    "، ".join(role.name for role in u.roles) or "—",
                    "فعال" if u.is_active else "غیرفعال",
                    fa(str(u.last_login_at)[:16]) if u.last_login_at else "—"],
                    colors=[None, None, None,
                            ui_kit.GREEN if u.is_active else ui_kit.RED, None])
                self.table.item(r, 0).setData(Qt.UserRole, u.id)
        finally:
            db.close()
