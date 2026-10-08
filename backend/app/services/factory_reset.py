# -*- coding: utf-8 -*-
"""Factory Reset — بازنشانی برنامه به وضعیت پایه (build-497، دستورالعمل §۱۲).

عملیات حساسِ «بازگشت به تنظیمات کارخانه» با سه اصل طراحی شده است:

۱. **شفافیت کامل** — ``preview()`` دقیقاً اعلام می‌کند چه جدول‌هایی با چند ردیف
   حذف می‌شوند، چه چیزی حفظ می‌شود و چه تنظیماتی بازنشانی می‌شود. هیچ حذفی
   «پنهانی» انجام نمی‌شود.

۲. **هیچ‌وقت کاربر را قفل نمی‌کند** — کاربران، نقش‌ها، مجوزها، لایسنس،
   جفت‌سازی گوشی، هویت دستگاه، پیکربندی اتصال (relay/cloud/update/network)
   و وضعیت راه‌اندازی (setup) همیشه حفظ می‌شوند؛ «وضعیت پایه» یعنی برنامه‌ای
   تمیز که با همان کاربران و همان لایسنس ادامه می‌دهد.

۳. **پشتیبانِ اجباری پیش از حذف** — اگر ساخت پشتیبان شکست بخورد، بازنشانی
   انجام نمی‌شود (همان قاعدهٔ §۲۹ برای Update).

دو دامنه (scope):
- ``transactions`` (پیش‌فرض): فقط دادهٔ عملیاتی — فروش، موجودی، حسابداری،
  هوش فروشگاه، اعلان‌ها، پیامک، شیفت/کارکرد و لاگ‌ها. کالا، مشتری، انبار و
  تنظیمات کسب‌وکار سر جای خود می‌مانند.
- ``full``: علاوه بر عملیاتی، کالا/مشتری/کاتالوگ هم خالی و تنظیمات کسب‌وکار
  (POS، چاپگر، پیامک، بازاریابی، هوش) به پیش‌فرض کارخانه برمی‌گردد.

همگام‌سازی: با هر بازنشانی ``data.epoch`` یکی زیاد می‌شود؛ پاسخ
``POST /api/mobile/sync`` همان epoch را برمی‌گرداند و گوشی با مقایسهٔ آن
دادهٔ محلی قدیمی را تشخیص داده و همگام‌سازی را از صفر انجام می‌دهد —
پس اطلاعات قدیمی هرگز روی دستگاه دیگری نمایش داده نمی‌شود (§۵/§۷).
"""
from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from ..config import settings as app_settings
from .. import __version__
from ..models import SystemSetting

#: شمارندهٔ «دورهٔ داده» — با هر بازنشانی +۱. گوشی‌های جفت‌شده با مقایسهٔ آن
#: تغییر پایگاه سمت رایانه را تشخیص می‌دهند.
EPOCH_KEY = "data.epoch"

#: پیشوندهای تنظیماتی که «زیرساخت/هویت» هستند و در هر دو دامنه حفظ می‌شوند.
#: حذف این‌ها یعنی قفل‌شدن بیرون از برنامه یا قطع اتصال گوشی/لایسنس.
PROTECTED_SETTING_PREFIXES = (
    "license.",        # لایسنس و کلیدهای نصب
    "mobile.",         # جفت‌سازی اندروید (devices, link_key, pair_codes)
    "device.",         # هویت/سلامت سخت‌افزار نصب‌شده
    "machine.",        # machine.id
    "update.",         # کانال/سرور به‌روزرسانی
    "relay.",          # رلهٔ اتصال LAN
    "cloud.",          # پیکربندی ابری
    "security.",       # سیاست‌های امنیتی (session, void تأیید مدیر)
    "setup.",          # وضعیت راه‌اندازی (ویزارد دوباره اجرا نشود)
    "network.",        # پورت LAN
    "backup.keep",     # سیاست نگهداری پشتیبان
    "bank.seeded",     # بانک کالا یک‌بار seed شده است
    EPOCH_KEY,         # خود شمارندهٔ دورهٔ داده
)

#: جدول‌های «هویت و دسترسی» — هرگز حذف نمی‌شوند.
ALWAYS_KEPT_TABLES = ("users", "user_roles", "user_permissions", "roles",
                      "role_permissions", "permissions", "hardware_devices",
                      "product_bank", "external_sources")

#: جدول‌های دادهٔ عملیاتی — دامنهٔ ``transactions``. ترتیب، «فرزند قبل از پدر»
#: بر اساس گراف واقعی FOREIGN KEY پایگاه است (PRAGMA foreign_keys=ON است؛
#: ترتیب غلط یعنی شکست حذف با «FOREIGN KEY constraint failed»).
TRANSACTION_TABLES = (
    # پشتیبانی، اعلان‌ها، منابع انسانی، شخصی‌سازی
    "support_messages", "support_tickets",
    "announcement_reads", "announcements",
    "hr_score_events", "hr_achievements", "hr_payroll",
    "hr_shift_attendance", "hr_shift_assignments", "hr_shifts",
    "user_widget_layouts",
    "notifications", "sms_messages",
    # صف همگام‌سازی و عیب‌یابی
    "sync_jobs", "diagnostic_runs",
    # بازاریابی (مصرف‌کننده‌های فاکتور/کوپن/جشنواره قبل از همه)
    "coupon_redemptions", "campaign_redemptions",
    # فروش: مرجوعی → ردیف فاکتور → پرداخت → دفتر مشتری → فاکتور
    "returns", "invoice_items", "payments", "customer_ledger_entries", "invoices",
    "counters",                       # شماره‌گذاری فاکتور از نو شروع می‌شود
    # موجودی و انبار: ردیف‌های ارجاع‌دهنده قبل از Batch
    "stocktake_items", "stocktakes", "stock_movements", "product_batches",
    # حسابداری (فرزند قبل از پدر؛ خودارجاع‌ها با UPDATE خنثی می‌شوند)
    "acc_journal_lines", "acc_cash_sessions", "acc_cheques", "acc_expenses",
    "acc_expense_categories", "acc_suppliers", "acc_fiscal_periods",
    "acc_journal_entries", "acc_accounts",
    # کوپن و جشنواره (بعد از مصرف‌کننده‌ها)
    "coupons", "campaigns",
    # هوش فروشگاه و آزمایش‌ها و نتیجه‌های Resolver
    "experiments", "ai_insights", "product_resolver_results", "market_prices",
    # لاگ حسابرسی — دورهٔ جدید با رکورد FACTORY_RESET آغاز می‌شود
    "audit_logs",
)

#: دادهٔ پایه (master data) — فقط در دامنهٔ ``full``. فرزند قبل از پدر:
#: تصاویر/قیمت‌ها/نتایج قبل از «کالا»، کالا قبل از دسته/برند/واحد،
#: محل نگهداری قبل از انبار، مشتری آخر (بعد از پاک‌شدن همهٔ ارجاع‌ها).
MASTER_TABLES = (
    "image_assets", "market_prices", "product_resolver_results", "price_versions",
    "products",
    "storage_locations", "warehouses",
    "customers",
    "categories", "brands", "units",
)

#: ستون‌های خودارجاع که پیش از حذف باید NULL شوند (وگرنه FK همان‌جا می‌شکند).
_NULL_BEFORE_DELETE = (
    ("acc_journal_entries", "reversal_of_id"),
    ("acc_accounts", "parent_id"),
    ("categories", "parent_id"),
)

#: تنظیمات کسب‌وکار — در دامنهٔ ``full`` به پیش‌فرض برمی‌گردند.
BUSINESS_SETTING_PREFIXES = (
    "pos.", "insights.", "sms.", "printer.", "pricing.", "marketing.",
    "customers.", "inventory.", "accounting.", "images.", "hw.",
    "catalog.", "ai.", "inv.", "mgmt.", "cash.", "expiry.", "dq.",
)

_CONFIRM_PHRASE = "RESET"


class FactoryResetError(Exception):
    """خطای سطح کسب‌وکار با کد ماشینی (§۱۰۲)."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _row_counts(db: Session, tables: tuple[str, ...]) -> dict[str, int]:
    counts: dict[str, int] = {}
    insp = db.get_bind()
    from sqlalchemy import inspect as sa_inspect
    existing = set(sa_inspect(insp).get_table_names())
    for t in tables:
        if t in existing:
            try:
                counts[t] = int(db.execute(text(f'SELECT COUNT(*) FROM "{t}"')).scalar_one())
            except Exception:  # noqa: BLE001 — جدول خراب هم باید در گزارش بیاید
                counts[t] = -1
    return counts


def data_epoch(db: Session) -> int:
    row = db.execute(select(SystemSetting.value).where(SystemSetting.key == EPOCH_KEY)).scalar_one_or_none()
    try:
        return int(row or 0)
    except (TypeError, ValueError):
        return 0


def _kept_settings(db: Session) -> list[str]:
    rows = db.execute(select(SystemSetting.key).order_by(SystemSetting.key.asc())).scalars().all()
    return [k for k in rows if k.startswith(PROTECTED_SETTING_PREFIXES)]


def preview(db: Session, scope: str = "transactions") -> dict:
    """گزارش دقیق پیش از بازنشانی — بدون هیچ تغییر داده‌ای."""
    scope = (scope or "transactions").lower()
    if scope not in ("transactions", "full"):
        raise FactoryResetError("INVALID_SCOPE", "scope باید transactions یا full باشد")

    wiped = dict(_row_counts(db, TRANSACTION_TABLES))
    if scope == "full":
        for t, c in _row_counts(db, MASTER_TABLES).items():
            wiped[t] = c

    reset_setting_keys = []
    if scope == "full":
        rows = db.execute(select(SystemSetting.key).order_by(SystemSetting.key.asc())).scalars().all()
        reset_setting_keys = [k for k in rows
                              if k.startswith(BUSINESS_SETTING_PREFIXES)
                              and not k.startswith(PROTECTED_SETTING_PREFIXES)]

    return {
        "scope": scope,
        "confirm_phrase": _CONFIRM_PHRASE,
        "epoch_current": data_epoch(db),
        "epoch_after": data_epoch(db) + 1,
        "version": __version__,
        "wiped_tables": wiped,
        "wiped_total_rows": sum(max(0, c) for c in wiped.values()),
        "kept_tables": list(ALWAYS_KEPT_TABLES),
        "kept_setting_keys": _kept_settings(db),
        "reset_setting_keys": reset_setting_keys,
        "notes": [
            "کاربران، نقش‌ها و دسترسی‌ها حفظ می‌شوند (ورود بعد از بازنشانی ممکن است).",
            "لایسنس، جفت‌سازی گوشی‌ها و پیکربندی اتصال حفظ می‌شود.",
            "فایل‌های پشتیبان روی دیسک حذف نمی‌شوند.",
            "پیش از حذف، یک پشتیبان امن از وضعیت فعلی ساخته می‌شود.",
            "با بازنشانی، گوشی‌های جفت‌شده در اولین همگام‌سازی تغییر را تشخیص می‌دهند و از صفر همگام می‌شوند.",
        ],
    }


def _safety_backup(db: Session) -> Path:
    """پشتیبان اجباری پیش از حذف — شکست پشتیبان = انصراف از بازنشانی (§۲۹)."""
    if not app_settings.DATABASE_URL.startswith("sqlite"):
        raise FactoryResetError("BACKUP_FAILED", "پشتیبان آنلاین فقط برای SQLite پیاده شده است")
    db_path = app_settings.DATABASE_URL.split("///")[-1]
    if db_path == ":memory:":
        raise FactoryResetError("BACKUP_FAILED", "پایگاه درون‌حافظه‌ای قابل پشتیبان‌گیری نیست")
    backup_dir = app_settings.data_dir / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    dest = backup_dir / f"supermarket_pre_factory_reset_{datetime.utcnow().strftime('%Y%m%d_%H%M%S_%f')}.db"
    try:
        source = sqlite3.connect(db_path)
        target = sqlite3.connect(str(dest))
        with target:
            source.backup(target)
        source.close()
        target.close()
    except Exception as exc:  # noqa: BLE001 — هر خطایی یعنی «بازنشانی ممنوع»
        raise FactoryResetError("BACKUP_FAILED", f"ساخت پشتیبان امن ناموفق بود: {exc}")
    if not dest.is_file() or dest.stat().st_size == 0:
        raise FactoryResetError("BACKUP_FAILED", "فایل پشتیبان ساخته نشد")
    return dest


def execute(db: Session, *, scope: str = "transactions", actor=None,
            confirm: str = "") -> dict:
    """بازنشانی واقعی. تراکنش را caller مدیریت می‌کند (commit/rollback)."""
    scope = (scope or "transactions").lower()
    if scope not in ("transactions", "full"):
        raise FactoryResetError("INVALID_SCOPE", "scope باید transactions یا full باشد")
    if confirm != _CONFIRM_PHRASE:
        raise FactoryResetError("CONFIRMATION_REQUIRED",
                                "تأیید صریح لازم است؛ confirm باید RESET باشد")

    report = preview(db, scope=scope)
    backup_path = _safety_backup(db)

    wiped: dict[str, int] = {}

    def _wipe(tables: tuple[str, ...]) -> None:
        # خودارجاع‌ها خنثی می‌شوند تا حذف گروهی FK نخورد
        for tbl, col in _NULL_BEFORE_DELETE:
            try:
                db.execute(text(f'UPDATE "{tbl}" SET "{col}" = NULL'))
            except Exception:  # noqa: BLE001 — جدول نبود در دامنهٔ دیگر طبیعی است
                pass
        for table in tables:
            try:
                res = db.execute(text(f'DELETE FROM "{table}"'))
                wiped[table] = int(res.rowcount or 0)
            except Exception as exc:  # noqa: BLE001 — گزارش می‌شود، توقف نمی‌کند
                wiped[table] = -1
                import logging
                logging.getLogger("supermarket.factory_reset").error(
                    "factory-reset: DELETE FROM %s failed: %s", table, exc)

    _wipe(TRANSACTION_TABLES)
    if scope == "full":
        _wipe(MASTER_TABLES)
        # تنظیمات کسب‌وکار به پیش‌فرض کارخانه
        from sqlalchemy import or_
        rows = db.execute(select(SystemSetting).where(or_(
            *[SystemSetting.key.startswith(p) for p in BUSINESS_SETTING_PREFIXES]))).scalars().all()
        reset_keys = [r.key for r in rows if not r.key.startswith(PROTECTED_SETTING_PREFIXES)]
        for r in rows:
            if not r.key.startswith(PROTECTED_SETTING_PREFIXES):
                db.delete(r)
    else:
        reset_keys = []

    # شمارندهٔ دورهٔ داده — همان لحظه افزایش می‌یابد تا گوشی‌ها تغییر را ببینند.
    epoch = data_epoch(db) + 1
    row = db.execute(select(SystemSetting).where(SystemSetting.key == EPOCH_KEY)).scalar_one_or_none()
    if row is None:
        db.add(SystemSetting(key=EPOCH_KEY, value=str(epoch), description="Data epoch (factory resets)"))
    else:
        row.value = str(epoch)

    from .audit import write_audit
    write_audit(db, action="FACTORY_RESET", entity_type="System", user_id=getattr(actor, "id", None),
                after={"scope": scope, "epoch": epoch, "backup": str(backup_path),
                       "wiped_rows": sum(max(0, c) for c in wiped.values()),
                       "reset_settings": reset_keys})
    from . import notifications as notif_svc
    try:
        notif_svc.notify(db, type="SYSTEM", title="بازنشانی کارخانه انجام شد",
                         body=f"داده‌ها پاک شد (دامنهٔ {scope})؛ پشتیبان: {backup_path.name}")
    except Exception:  # noqa: BLE001 — اعلان هرگز بازنشانی را خراب نمی‌کند
        pass

    return {
        "ok": True,
        "scope": scope,
        "epoch": epoch,
        "backup_path": str(backup_path),
        "backup_size": backup_path.stat().st_size,
        "wiped": wiped,
        "wiped_total_rows": sum(max(0, c) for c in wiped.values()),
        "reset_setting_keys": reset_keys,
    }
