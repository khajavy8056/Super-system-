# -*- coding: utf-8 -*-
"""همگام‌سازی نیتیو ویندوز (build-521) — یک گزینهٔ مستقل، مثل اندروید.

درخواست مالک: «همگام‌سازی باید یک گزینهٔ مستقل باشد و هنگام انتخاب، کار
همگام‌سازی را انجام دهد.» تا این نسخه ویندوز هیچ صفحهٔ همگام‌سازی نداشت؛ فقط
سرورِ پس‌زمینه برای گوشی گوش می‌داد. این صفحه همان موتورهای خودِ برنامه را
صدا می‌زند (بدون منطق تکراری، قانون ساختاری §۱۴):

* «همگام‌سازی اکنون» → ابر (اگر متصل باشد) یا صف محلی؛ در پس‌زمینه اجرا می‌شود
  تا پنجره هرگز فریز نشود.
* «اجرای صف محلی» → همان چیزی که سرور در /diagnostics/sync/run انجام می‌دهد.
* وضعیت رله/LAN، دستگاه‌های اندرویدِ جفت‌شده، صف ارسال و پیامک‌های در انتظار.
"""
from __future__ import annotations

import json

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (QHBoxLayout, QHeaderView, QLabel, QPushButton,
                               QVBoxLayout, QWidget)

from sqlalchemy import func, select

from app.database import SessionLocal
from app.models import SmsMessage, SystemSetting
from app.services import cloud as cloud_svc
from app.services import relay_client
from app.services import sync as sync_svc

from .. import ui_kit
from ..app_context import Context, fa

DEVICES_KEY = "mobile.devices"


class SyncThread(QThread):
    """اجرای کار همگام‌سازی در پس‌زمینه — UI هرگز فریز نمی‌شود."""

    done = Signal(dict)
    failed = Signal(str)

    def __init__(self, action: str, parent=None):
        super().__init__(parent)
        self.action = action

    def run(self) -> None:
        db = SessionLocal()
        try:
            if self.action == "cloud":
                result = cloud_svc.sync_now(db, push_backup=False)
            elif self.action == "local":
                result = sync_svc.run_once(db, limit=200)
            else:  # pragma: no cover — ورودی نامعتبر
                result = {"ok": False, "message": "کار ناشناخته"}
            db.commit()
            self.done.emit(result if isinstance(result, dict) else {"ok": True})
        except Exception as exc:  # noqa: BLE001 — هیچ خطایی پنجره را نمی‌بندد
            db.rollback()
            self.failed.emit(str(exc))
        finally:
            db.close()


class SyncPage(QWidget):
    HEADERS = ["نوع کار", "ارجاع", "وضعیت", "تلاش", "آخرین خطا"]

    def __init__(self, ctx: Context):
        super().__init__()
        self.ctx = ctx
        self.thread: SyncThread | None = None
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(10)

        self.status_label = QLabel("")
        self.status_label.setProperty("role", "muted")
        root.addWidget(self.status_label)

        row = QHBoxLayout()
        b_now = QPushButton("همگام‌سازی اکنون")
        b_now.setProperty("role", "success")
        b_now.clicked.connect(lambda: self._run("cloud"))
        b_queue = QPushButton("اجرای صف محلی")
        b_queue.setProperty("role", "ghost")
        b_queue.clicked.connect(lambda: self._run("local"))
        b_relay = QPushButton("آزمایش رله")
        b_relay.setProperty("role", "ghost")
        b_relay.clicked.connect(self._test_relay)
        b_reload = QPushButton("به‌روزرسانی")
        b_reload.clicked.connect(self.refresh)
        for b in (b_now, b_queue, b_relay):
            row.addWidget(b)
        row.addStretch(1)
        row.addWidget(b_reload)
        root.addLayout(row)

        self.jobs = ui_kit.make_table(self.HEADERS)
        self.jobs.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        root.addWidget(self.jobs, 1)

        devices_title = QLabel("دستگاه‌های اندروید جفت‌شده")
        devices_title.setStyleSheet("font-weight: 800; padding-top: 6px;")
        root.addWidget(devices_title)
        self.devices = ui_kit.make_table(["دستگاه", "کاربر", "آخرین همگام", "وضعیت"])
        self.devices.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        root.addWidget(self.devices, 1)

        hint = QLabel("گوشی اندروید مستقل کار می‌کند؛ این صفحه فقط همگام‌سازی را انجام می‌دهد "
                      "(کالا، فاکتور، کوپن و تنظیمات دو طرفه).")
        hint.setProperty("role", "muted")
        root.addWidget(hint)
        self.refresh()

    # ---------- کارها ----------
    def _run(self, action: str) -> None:
        if self.thread is not None and self.thread.isRunning():
            return
        self.status_label.setText("در حال همگام‌سازی…")
        self.thread = SyncThread(action, self)
        self.thread.done.connect(self._finish)
        self.thread.failed.connect(self._fail)
        self.thread.start()

    def _finish(self, result: dict) -> None:
        parts = []
        for key, label in (("sent", "ارسال‌شده"), ("failed", "خطا"), ("applied", "دریافت‌شده"),
                           ("ops", "عملیات"), ("pushed", "فرستاده به ابر"), ("pulled", "گرفته از ابر")):
            if key in result and result[key] not in (None, ""):
                parts.append(f"{label}: {fa(result[key])}")
        if result.get("message"):
            parts.append(str(result["message"]))
        self.status_label.setText(" · ".join(parts) if parts else "همگام‌سازی انجام شد")
        self.refresh()

    def _fail(self, message: str) -> None:
        self.status_label.setText(f"همگام‌سازی ناموفق: {message}")
        self.refresh()

    def _test_relay(self) -> None:
        db = SessionLocal()
        try:
            result = relay_client.test(db)
        except Exception as exc:  # noqa: BLE001
            result = {"ok": False, "message": str(exc)}
        finally:
            db.close()
        self.status_label.setText(
            ("رله پاسخ داد: " + str(result.get("message", "سالم"))) if result.get("ok")
            else ("رله در دسترس نیست: " + str(result.get("message", "—"))))
        self.refresh()

    # ---------- نمایش ----------
    def refresh(self) -> None:
        db = SessionLocal()
        try:
            stats = sync_svc.stats(db)
            cloud = cloud_svc.status(db)
            relay = relay_client.status(db)
            sms_pending = 0
            try:
                sms_pending = int(db.execute(
                    select(func.count()).select_from(SmsMessage)
                    .where(SmsMessage.status == "PENDING")).scalar_one() or 0)
            except Exception:  # noqa: BLE001 — آمار پیامک هرگز صفحه را نمی‌بندد
                sms_pending = 0
            relay_on = False
            try:
                relay_on = bool(relay_client.active(db))
            except Exception:  # noqa: BLE001
                relay_on = bool(relay.get("enabled"))
            self.status_label.setText(
                f"ابر: {'متصل' if cloud.get('connected') else 'قطع'} · "
                f"رله: {'فعال' if relay_on else 'غیرفعال'} · "
                f"صف: {fa(stats.get('pending', 0))} · خطا: {fa(stats.get('failed', 0))} · "
                f"پیامک در انتظار: {fa(sms_pending)}")

            self.jobs.setRowCount(0)
            # آخرین کارهای صف (بدون LIMIT بی‌نهایت): هم در انتظار و هم خطادار
            try:
                from app.models import SyncJob
                jobs = list(db.execute(
                    select(SyncJob).order_by(SyncJob.id.desc()).limit(200)
                ).scalars())
            except Exception:  # noqa: BLE001 — فهرست صف هرگز صفحه را نمی‌بندد
                jobs = []
            for job in jobs:
                r = self.jobs.rowCount()
                self.jobs.insertRow(r)
                ui_kit.fill_row(self.jobs, r, [
                    str(getattr(job, "job_type", "—")),
                    str(getattr(job, "reference_type", "") or "—"),
                    str(getattr(job, "status", "—")),
                    fa(getattr(job, "attempts", 0)),
                    str(getattr(job, "last_error", "") or "—")[:60],
                ])

            self.devices.setRowCount(0)
            setting = db.execute(
                select(SystemSetting).where(SystemSetting.key == DEVICES_KEY)
            ).scalars().first()
            devices = []
            if setting is not None:
                try:
                    devices = json.loads(setting.value or "[]")
                except Exception:  # noqa: BLE001 — مقدار خراب = فهرست خالی، نه کرش
                    devices = []
            for device in devices:
                if device.get("revoked"):
                    continue
                r = self.devices.rowCount()
                self.devices.insertRow(r)
                ui_kit.fill_row(self.devices, r, [
                    str(device.get("name", "—")),
                    str(device.get("user", "—")),
                    str(device.get("last_sync_at", "—"))[:19],
                    "فعال",
                ])
            if not devices:
                r = self.devices.rowCount()
                self.devices.insertRow(r)
                ui_kit.fill_row(self.devices, r, ["گوشی جفت‌شده‌ای نیست", "—", "—", "—"])
        finally:
            db.close()
