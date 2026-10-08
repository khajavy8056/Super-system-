# -*- coding: utf-8 -*-
"""تنظیمات نیتیو: پروفایل فروشگاه، پشتیبان‌گیری و «بازنشانی کارخانه» (§۱۲).

همان موتور factory_reset سرور، با جریان نیتیو سه‌مرحله‌ای:
گزارش دقیق ← تأیید تایپی RESET + رمز مدیر ← اجرا در پس‌زمینه با پشتیبان اجباری.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (QDialog, QFormLayout, QHBoxLayout, QLabel,
                               QLineEdit, QMessageBox, QPushButton,
                               QTableWidget, QVBoxLayout, QWidget)

from app.config import settings as app_settings
from app.database import SessionLocal
from app.security import verify_password
from app.services import factory_reset as fr_svc
from app.services.audit import write_audit

from .. import ui_kit
from ..app_context import Context, fa, money


def safety_backup() -> Path:
    """پشتیبان آنلاین SQLite (همان روش /system/backup سرور)."""
    db_path = app_settings.DATABASE_URL.split("///")[-1]
    backup_dir = app_settings.data_dir / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    dest = backup_dir / f"supermarket_pre_factory_reset_{datetime.utcnow().strftime('%Y%m%d_%H%M%S_%f')}.db"
    source = sqlite3.connect(db_path)
    target = sqlite3.connect(str(dest))
    with target:
        source.backup(target)
    source.close()
    target.close()
    return dest


class ResetThread(QThread):
    """اجرای بازنشانی در پس‌زمینه — UI هرگز فریز نمی‌شود."""
    done = Signal(dict)
    failed = Signal(str)

    def __init__(self, scope: str, confirm: str, parent=None):
        super().__init__(parent)
        self.scope = scope
        self.confirm = confirm

    def run(self) -> None:
        db = SessionLocal()
        try:
            try:
                result = fr_svc.execute(db, scope=self.scope, actor=None, confirm=self.confirm)
                db.commit()
                self.done.emit(result)
            except fr_svc.FactoryResetError as exc:
                db.rollback()
                self.failed.emit(exc.message)
            except Exception as exc:  # noqa: BLE001
                db.rollback()
                self.failed.emit(str(exc))
        finally:
            db.close()


class FactoryResetDialog(QDialog):
    """گام‌های ۱ تا ۳ بازنشانی کارخانه — دقیقاً مطابق سیاست §۱۲."""

    def __init__(self, ctx: Context, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.setWindowTitle("بازنشانی به تنظیمات کارخانه")
        self.setMinimumWidth(560)
        self.preview: dict | None = None
        lay = QVBoxLayout(self)

        lay.addWidget(QLabel("دامنهٔ بازنشانی را انتخاب کنید و «نمایش گزارش» را بزنید:"))
        bar = QHBoxLayout()
        self.scope = QComboBox__()
        self.scope.addItem("دادهٔ عملیاتی (کالا و مشتری می‌مانند)", "transactions")
        self.scope.addItem("کامل (کاتالوگ و مشتریان هم پاک می‌شوند)", "full")
        preview_btn = QPushButton("۱) نمایش دقیق گزارش")
        preview_btn.clicked.connect(self._preview)
        bar.addWidget(self.scope, 1)
        bar.addWidget(preview_btn)
        lay.addLayout(bar)

        self.report = QTableWidget(0, 2)
        self.report.setHorizontalHeaderLabels(["جدول", "ردیف‌هایی که پاک می‌شوند"])
        self.report.verticalHeader().setVisible(False)
        self.report.setEditTriggers(QTableWidget.NoEditTriggers)
        lay.addWidget(self.report, 1)
        self.note = QLabel("")
        self.note.setProperty("role", "muted")
        self.note.setWordWrap(True)
        lay.addWidget(self.note)

        form = QFormLayout()
        self.confirm = QLineEdit()
        self.confirm.setPlaceholderText("برای تأیید عبارت RESET را تایپ کنید")
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.Password)
        form.addRow("تأیید:", self.confirm)
        form.addRow("رمز مدیر:", self.password)
        lay.addLayout(form)

        run = QPushButton("۲) بازنشانی کن")
        run.setProperty("role", "danger")
        run.clicked.connect(self._run)
        lay.addWidget(run)

    def _preview(self) -> None:
        db = SessionLocal()
        try:
            self.preview = fr_svc.preview(db, scope=self.scope.currentData())
        finally:
            db.close()
        self.report.setRowCount(0)
        for table, count in sorted(self.preview["wiped_tables"].items(), key=lambda kv: -kv[1]):
            r = self.report.rowCount()
            self.report.insertRow(r)
            ui_kit.fill_row(self.report, r, [table, fa(count) if count >= 0 else "خطا"])
        kept = ", ".join(self.preview["kept_tables"])
        self.note.setText(
            f"مجموع {fa(self.preview['wiped_total_rows'])} ردیف پاک می‌شود · "
            f"دورهٔ داده: {fa(self.preview['epoch_current'])} → {fa(self.preview['epoch_after'])}\n"
            f"همیشه حفظ می‌شوند: {kept} + لایسنس، جفت‌سازی گوشی‌ها، تنظیمات اتصال و پشتیبان‌های دیسک. "
            "پیش از اجرا پشتیبان امن ساخته می‌شود.")

    def _run(self) -> None:
        if self.preview is None:
            QMessageBox.information(self, "گزارش لازم است", "ابتدا «نمایش دقیق گزارش» را ببینید")
            return
        if self.confirm.text().strip() != "RESET":
            QMessageBox.warning(self, "تأیید ناقص", "برای تأیید باید RESET را دقیقاً تایپ کنید")
            return
        db = SessionLocal()
        try:
            user = self.ctx.user
            db.refresh(user)
            if not verify_password(self.password.text(), user.password_hash):
                write_audit(db, action="FACTORY_RESET_AUTH_FAILED", user_id=user.id, entity_type="System")
                db.commit()
                QMessageBox.critical(self, "رمز نادرست", "رمز مدیر نادرست است؛ بازنشانی انجام نشد")
                return
        finally:
            db.close()
        if QMessageBox.question(self, "تأیید نهایی",
                                "پشتیبان امن ساخته شود و بازنشانی اجرا شود؟") != QMessageBox.Yes:
            return
        # پشتیبان اجباری — شکست پشتیبان یعنی هیچ حذفی (§۲۹)
        try:
            backup = safety_backup()
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "پشتیبان ناموفق",
                                 f"بدون پشتیبان موفق، بازنشانی انجام نمی‌شود: {exc}")
            return
        self.setEnabled(False)
        self.thread = ResetThread(self.scope.currentData(), "RESET", self)
        self.thread.done.connect(lambda res: self._finish(backup, res))
        self.thread.failed.connect(self._fail)
        self.thread.start()

    def _finish(self, backup: Path, result: dict) -> None:
        self.setEnabled(True)
        QMessageBox.information(
            self, "انجام شد",
            f"بازنشانی کارخانه انجام شد.\nپشتیبان: {backup.name}\n"
            f"دورهٔ دادهٔ جدید: {fa(result['epoch'])}")
        self.accept()

    def _fail(self, message: str) -> None:
        self.setEnabled(True)
        QMessageBox.critical(self, "بازنشانی ناموفق", message)


def QComboBox__():
    from PySide6.QtWidgets import QComboBox
    combo = QComboBox()
    return combo


class SettingsPage(QWidget):
    def __init__(self, ctx: Context):
        super().__init__()
        self.ctx = ctx
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)

        prof, lay = ui_kit.card("پروفایل فروشگاه")
        form = QFormLayout()
        self.store_name = QLineEdit(ctx.get_setting("store.name", ""))
        self.store_phone = QLineEdit(ctx.get_setting("store.phone", ""))
        self.store_address = QLineEdit(ctx.get_setting("store.address", ""))
        form.addRow("نام فروشگاه:", self.store_name)
        form.addRow("تلفن:", self.store_phone)
        form.addRow("آدرس:", self.store_address)
        save = QPushButton("ذخیرهٔ پروفایل")
        save.clicked.connect(self._save_profile)
        form.addRow(save)
        lay.addLayout(form)
        root.addWidget(prof)

        bk, bk_lay = ui_kit.card("پشتیبان‌گیری")
        bk_info = QLabel(f"پوشهٔ پشتیبان‌ها: {app_settings.data_dir / 'backups'}")
        bk_info.setProperty("role", "muted")
        backup_btn = QPushButton("گرفتن پشتیبان الان")
        backup_btn.clicked.connect(self._backup_now)
        bk_lay.addWidget(bk_info)
        bk_lay.addWidget(backup_btn)
        root.addWidget(bk)

        fr, fr_lay = ui_kit.card("بازنشانی به تنظیمات کارخانه (Factory Reset)")
        fr_text = QLabel("بازگشت داده‌ها به وضعیت پایه — با پیش‌نمایش دقیق، تأیید تایپی و پشتیبان اجباری.")
        fr_text.setProperty("role", "muted")
        fr_btn = QPushButton("بازنشانی کارخانه…")
        fr_btn.setProperty("role", "danger")
        fr_btn.clicked.connect(self._factory_reset)
        fr_lay.addWidget(fr_text)
        fr_lay.addWidget(fr_btn)
        root.addWidget(fr)
        root.addStretch(1)

    def _save_profile(self) -> None:
        self.ctx.set_setting("store.name", self.store_name.text().strip())
        self.ctx.set_setting("store.phone", self.store_phone.text().strip())
        self.ctx.set_setting("store.address", self.store_address.text().strip())
        QMessageBox.information(self, "ذخیره شد", "پروفایل فروشگاه ذخیره شد")

    def _backup_now(self) -> None:
        db_path = app_settings.DATABASE_URL.split("///")[-1]
        backup_dir = app_settings.data_dir / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        dest = backup_dir / f"supermarket_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.db"
        source = sqlite3.connect(db_path)
        target = sqlite3.connect(str(dest))
        with target:
            source.backup(target)
        source.close()
        target.close()
        db = SessionLocal()
        try:
            write_audit(db, action="BACKUP_CREATED", entity_type="Backup", reference=str(dest))
            db.commit()
        finally:
            db.close()
        QMessageBox.information(self, "پشتیبان گرفته شد", str(dest))

    def _factory_reset(self) -> None:
        FactoryResetDialog(self.ctx, self).exec()
