# -*- coding: utf-8 -*-
"""جشنواره‌ها نیتیو ویندوز — گزارش عملکرد + ساخت/ویرایش کامل.

build-514: گزارش عملکرد هر جشنواره (چند بار استفاده شده، چند کوپن صادر شده،
چقدر تخفیف داده شده، آخرین استفاده).

build-521 — برابری نسخه‌ها (§۱۴): تا این نسخه ساخت/ویرایش جشنواره فقط روی
اندروید و رابط وب بود و ویندوز «فقط گزارش»؛ خواستهٔ مالک این است که هر
قابلیت اندروید روی ویندوز هم باشد و هر نسخه مستقل کار کند. این صفحه اکنون
همان جشنواره‌ها را می‌سازد و ویرایش می‌کند، با همان مدل و همان موتور فروش
(بدون منطق تکراری): نوع تخفیف (درصدی/مبلغی/هدیهٔ رایگان/هدیهٔ خرید بعدی)،
شرط مبلغ و تعداد خرید، بازهٔ اعتبار، هدف‌گیری کالا/دسته، سقف تخفیف،
«خودکار»، اولویت، ترکیب با کوپن، سقف استفاده، صدور خودکار کوپن خرید بعدی.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QFormLayout,
                               QHBoxLayout, QHeaderView, QLabel, QLineEdit,
                               QMessageBox, QPushButton, QSpinBox, QTableWidgetItem,
                               QVBoxLayout, QWidget)

from app.database import SessionLocal
from app.models.marketing import Campaign, Coupon
from app.services.audit import write_audit
from sqlalchemy import func, select

from .. import ui_kit
from ..app_context import Context, Context as _Context, fa, money

KINDS = [("PERCENT", "درصدی روی خرید"), ("FIXED", "مبلغ ثابت تخفیف"),
         ("GIFT", "هدیهٔ رایگان (یک قلم هدیه)"), ("NEXT", "هدیهٔ خرید بعدی (کوپن)")]
TARGETS = [("ALL", "کل سبد"), ("PRODUCTS", "کالاهای انتخابی"), ("CATEGORY", "دستهٔ انتخابی")]


class CampaignDialog(QDialog):
    """ساخت/ویرایش جشنواره — همان میدان‌های جادوگر اندروید/وب."""

    def __init__(self, ctx: Context, campaign: Campaign | None = None, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.campaign = campaign
        self.setWindowTitle("ویرایش جشنواره" if campaign else "جشنوارهٔ جدید")
        self.setMinimumWidth(520)
        root = QVBoxLayout(self)
        form = QFormLayout()

        self.name = QLineEdit(campaign.name if campaign else "")
        form.addRow("نام جشنواره *", self.name)

        self.kind = QComboBox()
        for code, label in KINDS:
            self.kind.addItem(label, code)
        if campaign is not None:
            code = "NEXT" if campaign.reward_next_only else (
                "GIFT" if campaign.discount_type == "GIFT" else campaign.discount_type)
            index = self.kind.findData(code)
            if index >= 0:
                self.kind.setCurrentIndex(index)
        form.addRow("نوع پاداش", self.kind)

        self.value = QLineEdit(str(campaign.discount_value if campaign else 10))
        form.addRow("مقدار (٪ یا تومان)", self.value)

        self.min_purchase = QLineEdit(str(campaign.min_purchase if campaign else 0))
        form.addRow("حداقل خرید (تومان)", self.min_purchase)

        self.max_discount = QLineEdit(
            "" if campaign is None or campaign.max_discount is None else str(campaign.max_discount))
        self.max_discount.setPlaceholderText("خالی = بدون سقف")
        form.addRow("سقف تخفیف (تومان)", self.max_discount)

        self.count = QSpinBox()
        self.count.setRange(0, 10000)
        self.count.setPrefix("بعد از ")
        self.count.setSuffix(" خرید")
        self.count.setValue(int(campaign.min_purchase_count or 0) if campaign else 0)
        form.addRow("شرط تعداد خرید", self.count)

        self.days = QSpinBox()
        self.days.setRange(1, 3650)
        self.days.setSuffix(" روز اعتبار")
        self.days.setValue(30)
        form.addRow("اعتبار (از امروز)", self.days)

        self.target = QComboBox()
        for code, label in TARGETS:
            self.target.addItem(label, code)
        if campaign is not None:
            index = self.target.findData(campaign.target_type or "ALL")
            if index >= 0:
                self.target.setCurrentIndex(index)
        form.addRow("هدف پاداش", self.target)

        self.targets = QLineEdit(
            "" if campaign is None or not campaign.target_ids else campaign.target_ids)
        self.targets.setPlaceholderText("شناسهٔ کالاها با کاما، یا نام دسته‌ها با کاما")
        form.addRow("کالا/دسته‌های هدف", self.targets)

        self.threshold = QLineEdit(
            "" if campaign is None or campaign.auto_issue_threshold is None
            else str(campaign.auto_issue_threshold))
        self.threshold.setPlaceholderText("خالی = بدون صدور خودکار کوپن خرید بعدی")
        form.addRow("آستانهٔ صدور کوپن خرید بعدی", self.threshold)

        self.threshold_days = QSpinBox()
        self.threshold_days.setRange(1, 3650)
        self.threshold_days.setSuffix(" روز اعتبار کوپن")
        self.threshold_days.setValue(int(getattr(campaign, "auto_issue_validity_days", 30) or 30)
                                     if campaign else 30)
        form.addRow("اعتبار کوپن صادرشده", self.threshold_days)

        self.sms = QComboBox()
        self.sms.addItem("پیامک کوپن برای مشتری ارسال شود", True)
        self.sms.addItem("پیامک ارسال نشود", False)
        if campaign is not None and not bool(getattr(campaign, "auto_issue_sms", True)):
            self.sms.setCurrentIndex(1)
        form.addRow("پیامک کوپن", self.sms)

        self.usage_limit = QSpinBox()
        self.usage_limit.setRange(0, 1000000)
        self.usage_limit.setSpecialValueText("بدون سقف")
        self.usage_limit.setValue(int(campaign.usage_limit or 0) if campaign else 0)
        form.addRow("سقف تعداد استفاده", self.usage_limit)

        self.per_customer = QSpinBox()
        self.per_customer.setRange(0, 1000000)
        self.per_customer.setSpecialValueText("بدون سقف")
        self.per_customer.setValue(int(campaign.per_customer_limit or 0) if campaign else 0)
        form.addRow("سقف استفادهٔ هر مشتری", self.per_customer)

        self.priority = QSpinBox()
        self.priority.setRange(1, 5)
        self.priority.setValue(int(campaign.priority or 3) if campaign else 3)
        form.addRow("اولویت (۱ = مهم‌تر)", self.priority)

        self.flags = QComboBox()
        self.flags.addItem("فقط با انتخاب صندوق‌دار", (False, False, False))
        self.flags.addItem("خودکار اعمال شود", (True, False, False))
        self.flags.addItem("فقط اولین خرید مشتری", (False, True, False))
        self.flags.addItem("قابل ترکیب با کوپن", (False, False, True))
        if campaign is not None:
            if campaign.auto_apply:
                self.flags.setCurrentIndex(1)
            elif campaign.first_purchase_only:
                self.flags.setCurrentIndex(2)
            elif campaign.stackable:
                self.flags.setCurrentIndex(3)
        form.addRow("قاعدهٔ اعمال", self.flags)

        self.status = QComboBox()
        self.status.addItem("فعال", "ACTIVE")
        self.status.addItem("متوقف", "PAUSED")
        self.status.addItem("پایان‌یافته", "ENDED")
        if campaign is not None:
            index = self.status.findData(campaign.status)
            if index >= 0:
                self.status.setCurrentIndex(index)
        form.addRow("وضعیت", self.status)

        root.addLayout(form)
        note = QLabel("این جشنواره روی همان موتور فروش رایانه اجرا می‌شود؛ گوشی‌های اندروید "
                      "هنگام همگام‌سازی همین قواعد را می‌گیرند و مستقل هم اجرا می‌کنند.")
        note.setProperty("role", "muted")
        note.setWordWrap(True)
        root.addWidget(note)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    # ---------- ذخیره ----------
    def _number(self, field: QLineEdit, label: str) -> Decimal:
        raw = (field.text() or "").strip().replace(",", "").replace("،", "")
        if not raw:
            return Decimal(0)
        try:
            value = Decimal(raw)
        except Exception as exc:  # noqa: BLE001
            raise ValueError(f"{label} عدد معتبر نیست") from exc
        if value < 0:
            raise ValueError(f"{label} نمی‌تواند منفی باشد")
        return value

    def _optional_number(self, field: QLineEdit, label: str) -> Decimal | None:
        raw = (field.text() or "").strip().replace(",", "").replace("،", "")
        if not raw:
            return None
        return self._number(field, label)

    def _targets_json(self, target_type: str) -> str | None:
        raw = (self.targets.text() or "").strip()
        if target_type == "ALL" or not raw:
            return None
        items = [part.strip() for part in raw.replace("،", ",").split(",") if part.strip()]
        if not items:
            return None
        import json as _json
        return _json.dumps(items, ensure_ascii=False)

    def _save(self) -> None:
        name = (self.name.text() or "").strip()
        if not name:
            QMessageBox.warning(self, "نام لازم است", "نام جشنواره را وارد کنید")
            return
        kind = self.kind.currentData()
        target_type = self.target.currentData()
        try:
            value = self._number(self.value, "مقدار")
            min_purchase = self._number(self.min_purchase, "حداقل خرید")
            max_discount = self._optional_number(self.max_discount, "سقف تخفیف")
            threshold = self._optional_number(self.threshold, "آستانهٔ صدور کوپن")
            targets = self._targets_json(target_type)
        except ValueError as exc:
            QMessageBox.warning(self, "مقدار نامعتبر", str(exc))
            return
        if kind == "PERCENT" and value > 100:
            QMessageBox.warning(self, "درصد نامعتبر", "درصد تخفیف نمی‌تواند بیشتر از ۱۰۰ باشد")
            return
        if kind in ("FIXED", "GIFT", "NEXT") and value <= 0:
            QMessageBox.warning(self, "مقدار لازم است",
                                "برای این نوع پاداش، مقدار باید بزرگ‌تر از صفر باشد")
            return
        if target_type != "ALL" and not targets:
            QMessageBox.warning(self, "هدف لازم است", "کالا یا دستهٔ هدف را مشخص کنید")
            return
        if kind == "NEXT" and threshold is None:
            # «هدیهٔ خرید بعدی» بدون آستانه یعنی پاداش هیچ فاکتوری؛ آستانه را از حداقل خرید می‌گیریم
            threshold = min_purchase if min_purchase > 0 else None
            if threshold is None:
                QMessageBox.warning(self, "آستانه لازم است",
                                    "برای «هدیهٔ خرید بعدی» آستانهٔ مبلغ یا حداقل خرید را وارد کنید")
                return

        auto_apply, first_only, stackable = self.flags.currentData()
        now = datetime.utcnow()
        days = int(self.days.value())
        db = SessionLocal()
        try:
            campaign = self.campaign or Campaign()
            campaign.name = name
            campaign.description = campaign.description
            campaign.discount_type = "PERCENT" if kind == "PERCENT" else (
                "FIXED" if kind == "FIXED" else ("GIFT" if kind == "GIFT" else "PERCENT"))
            campaign.discount_value = value
            campaign.min_purchase = min_purchase
            campaign.max_discount = max_discount
            campaign.min_purchase_count = int(self.count.value())
            campaign.reward_next_only = kind == "NEXT"
            campaign.auto_issue_threshold = threshold
            campaign.auto_issue_validity_days = int(self.threshold_days.value())
            campaign.auto_issue_sms = bool(self.sms.currentData())
            campaign.target_type = target_type
            campaign.target_ids = targets
            campaign.first_purchase_only = bool(first_only)
            campaign.stackable = bool(stackable)
            campaign.auto_apply = bool(auto_apply) or threshold is not None
            campaign.priority = int(self.priority.value())
            campaign.usage_limit = int(self.usage_limit.value()) or None
            campaign.per_customer_limit = int(self.per_customer.value()) or None
            campaign.status = self.status.currentData()
            if self.campaign is None:
                campaign.valid_from = now
                campaign.valid_until = now + timedelta(days=days)
                campaign.created_by = self.ctx.user.id if self.ctx.user else None
                db.add(campaign)
            db.flush()
            write_audit(
                db, action="CAMPAIGN_SAVED" if self.campaign else "CAMPAIGN_CREATED",
                user_id=self.ctx.user.id if self.ctx.user else None,
                entity_type="Campaign", entity_id=campaign.id,
                after={"name": campaign.name, "kind": kind, "value": str(value),
                       "min_purchase": str(min_purchase),
                       "auto_issue_threshold": str(threshold) if threshold is not None else None,
                       "auto_apply": campaign.auto_apply})
            db.commit()
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            QMessageBox.critical(self, "ذخیره نشد", f"جشنواره ذخیره نشد: {exc}")
            return
        finally:
            db.close()
        self.accept()


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
        b_new = QPushButton("جشنوارهٔ جدید")
        b_new.setProperty("role", "success")
        b_new.clicked.connect(self._new)
        b_edit = QPushButton("ویرایش")
        b_edit.setProperty("role", "ghost")
        b_edit.clicked.connect(self._edit)
        b_toggle = QPushButton("فعال/متوقف")
        b_toggle.setProperty("role", "ghost")
        b_toggle.clicked.connect(self._toggle)
        b_end = QPushButton("پایان جشنواره")
        b_end.setProperty("role", "ghost")
        b_end.clicked.connect(self._end)
        reload = QPushButton("به‌روزرسانی")
        reload.clicked.connect(self.refresh)
        for b in (b_new, b_edit, b_toggle, b_end):
            row.addWidget(b)
        row.addStretch(1)
        row.addWidget(reload)
        root.addLayout(row)
        self.table = ui_kit.make_table(self.HEADERS)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.doubleClicked.connect(self._edit)
        root.addWidget(self.table, 1)
        hint = QLabel("دوبار کلیک روی هر ردیف = ویرایش. جشنوارهٔ «خودکار» بدون انتخاب صندوق‌دار "
                      "روی فاکتورهای واجد شرایط اعمال می‌شود و «هدیهٔ خرید بعدی» هنگام ثبت فروش "
                      "برای همان مشتری کوپن می‌سازد و در پیامک می‌آید.")
        hint.setProperty("role", "muted")
        hint.setWordWrap(True)
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
                # شناسهٔ جشنواره روی همان ردیف تا ویرایش/توقف روی درست‌ترین رکورد انجام شود
                self.table.item(r, 0).setData(Qt.UserRole, int(c.id))
                total_used += int(c.used_count or 0)
                total_issued += issued_n
                total_spent += spent
            self.summary.setText(
                f"جشنواره‌ها: {fa(len(campaigns))} · مجموع استفاده: {fa(total_used)} · "
                f"کوپن صادرشده: {fa(total_issued)} · مجموع تخفیف داده‌شده: {money(total_spent)}")
        finally:
            db.close()


    # ---------- ساخت/ویرایش (build-521 — برابری نسخه‌ها) ----------
    def _selected(self) -> Campaign | None:
        row = self.table.currentRow()
        if row < 0:
            return None
        item = self.table.item(row, 0)
        campaign_id = item.data(Qt.UserRole) if item is not None else None
        if campaign_id is None:
            return None
        db = SessionLocal()
        try:
            return db.get(Campaign, int(campaign_id))
        finally:
            db.close()

    def _new(self) -> None:
        if not self.ctx.can("marketing.manage"):
            QMessageBox.warning(self, "دسترسی ناکافی", "حساب شما مجوز ساخت جشنواره ندارد")
            return
        if CampaignDialog(self.ctx, None, self).exec() == QDialog.Accepted:
            self.refresh()

    def _edit(self, *_args) -> None:
        if not self.ctx.can("marketing.manage"):
            QMessageBox.warning(self, "دسترسی ناکافی", "حساب شما مجوز ویرایش جشنواره ندارد")
            return
        campaign = self._selected()
        if campaign is None:
            QMessageBox.information(self, "انتخاب کنید", "ابتدا یک جشنواره را انتخاب کنید")
            return
        if CampaignDialog(self.ctx, campaign, self).exec() == QDialog.Accepted:
            self.refresh()

    def _set_status(self, status: str, action: str) -> None:
        if not self.ctx.can("marketing.manage"):
            QMessageBox.warning(self, "دسترسی ناکافی", "حساب شما مجوز تغییر جشنواره ندارد")
            return
        campaign = self._selected()
        if campaign is None:
            QMessageBox.information(self, "انتخاب کنید", "ابتدا یک جشنواره را انتخاب کنید")
            return
        db = SessionLocal()
        try:
            row = db.get(Campaign, campaign.id)
            if row is None:
                return
            row.status = status
            write_audit(db, action=action, user_id=self.ctx.user.id if self.ctx.user else None,
                        entity_type="Campaign", entity_id=row.id, after={"status": status})
            db.commit()
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            QMessageBox.critical(self, "ذخیره نشد", f"وضعیت جشنواره تغییر نکرد: {exc}")
        finally:
            db.close()
        self.refresh()

    def _toggle(self) -> None:
        campaign = self._selected()
        if campaign is None:
            QMessageBox.information(self, "انتخاب کنید", "ابتدا یک جشنواره را انتخاب کنید")
            return
        self._set_status("PAUSED" if campaign.status == "ACTIVE" else "ACTIVE",
                         "CAMPAIGN_STATUS_CHANGED")

    def _end(self) -> None:
        self._set_status("ENDED", "CAMPAIGN_ENDED")

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
