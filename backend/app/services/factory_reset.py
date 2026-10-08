# -*- coding: utf-8 -*-
"""build-496 (دور دوم ممیزی) — «بازنشانی به تنظیمات کارخانه» (Factory Reset).

قاعدهٔ طراحی: این عملیات حساس است، پس هیچ‌چیز پنهان یا مبهم نیست.

  ۱. **پیش از بازنشانی، «نقشه» به کاربر نشان داده می‌شود** (`plan()`): دقیقاً
     کدام جدول پاک می‌شود، چند ردیف دارد، چه چیزی می‌ماند و چرا.
  ۲. **بدون نسخهٔ پشتیبان، هیچ‌چیز پاک نمی‌شود.** اول پشتیبان کامل گرفته
     می‌شود؛ اگر پشتیبان‌گیری شکست بخورد، عملیات کامل متوقف می‌شود.
  ۳. اجرای واقعی فقط با **عبارت تأیید عیناً** («بازنشانی») انجام می‌شود.
  ۴. پس از پاک‌سازی، `bootstrap()` همان مسیر نصب تازه اجرا می‌شود تا برنامه به
     وضعیت پایه برگردد (تنظیمات پیش‌فرض، واحدها، منابع پیش‌فرض، بانک کالا،
     نقش‌ها، کاربر مدیر).

چه چیزی **پاک** می‌شود (داده‌های عملیاتی): فاکتور/آیتم/پرداخت/مرجوعی،
مشتریان و دفتر بدهی، چک و هزینه و اسناد حسابداری و صندوق‌ها، Batch و گردش
موجودی و انبارگردانی و قیمت‌ها، کوپن/جشنواره/کمپین، پیشنهادها و آزمایش‌ها،
حقوق و شیفت‌ها و حضور، اعلان‌ها و پیامک‌ها، صف همگام‌سازی، تیکت‌های پشتیبانی،
گزارش حسابرسی، شمارنده‌ها و چیدمان ویجت‌ها.

چه چیزی **می‌ماند** (هویت و پیکربندی): کاربران و نقش‌ها و دسترسی‌ها (مگر با
درخواست صریح)، پروفایل فروشگاه (نام/آدرس/تلفن/لوگو)، واحد ارز، منطقهٔ زمانی و
ساعت، تنظیمات پرینتر/کشوی پول/اسکنر، پیکربندی پیامک و لایسنس و به‌روزرسانی و
سیاست امنیتی، واحدها، بانک کالا، منابع Resolver و **فایل پشتیبان ساخته‌شده**.

دو حالت:
  * ``full`` (پیش‌فرض): کالاها/برندها/دسته‌ها/تأمین‌کنندگان/انبارها هم پاک
    می‌شوند و بانک کالای پیش‌فرض دوباره ساخته می‌شود ⇒ وضعیت ≈ نصب تازه.
  * ``keep_catalog``: کالاها و دسته‌ها و انبارها می‌مانند (موجودی صفر می‌شود،
    چون همهٔ Batchها پاک می‌شوند) ⇒ برای «دورهٔ مالی جدید بدون از دست دادن
    فهرست کالاها».
"""
from __future__ import annotations

import json
import logging
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

from sqlalchemy import inspect as sa_inspect, select, text
from sqlalchemy.orm import Session

from ..config import settings
from ..models import SystemSetting, User

log = logging.getLogger("supermarket.factory_reset")

#: عبارت تأییدی که کاربر باید عیناً بنویسد (محافظ در برابر کلیک اشتباه).
CONFIRMATION_PHRASE = "بازنشانی"

#: ترتیب حذف: هر جدول قبل از والد خودش. (SQLite با FK روشن، ترتیب را الزامی می‌کند)
WIPE_ORDER: tuple[str, ...] = (
    # فروش
    "invoice_items", "payments", "returns", "coupon_redemptions", "campaign_redemptions",
    "customer_ledger_entries", "invoices",
    # بازاریابی
    "coupons", "campaigns",
    # انبار
    "stocktake_items", "stocktakes", "stock_movements", "price_versions",
    "product_batches", "product_resolver_results", "market_prices", "image_assets",
    # حسابداری
    "acc_journal_lines", "acc_journal_entries", "acc_expenses", "acc_cheques",
    "acc_cash_sessions", "acc_fiscal_periods",
    # منابع انسانی
    "hr_shift_attendance", "hr_shift_assignments", "hr_shifts", "hr_payroll",
    "hr_score_events", "hr_achievements", "announcement_reads", "announcements",
    # هوش فروشگاه / تشخیص
    "ai_insights", "experiments", "diagnostic_runs",
    # ارتباطات و صف‌ها
    "notifications", "sms_messages", "sync_jobs", "support_messages", "support_tickets",
    # حسابرسی و شمارنده‌ها و چیدمان شخصی
    "audit_logs", "counters", "user_widget_layouts",
)

#: جدول‌های «فهرست کالا» که فقط در حالت full پاک می‌شوند.
CATALOG_ORDER: tuple[str, ...] = (
    "products", "storage_locations", "warehouses", "acc_suppliers", "brands", "categories",
)

#: هرگز پاک نمی‌شوند: هویت، دسترسی‌ها و مراجع پایه.
PRESERVED_TABLES: tuple[str, ...] = (
    "users", "roles", "permissions", "role_permissions", "user_roles", "user_permissions",
    "system_settings", "units", "product_bank", "external_sources", "hardware_devices",
)

#: کلیدهای تنظیمات که بازنشانی نمی‌شوند (هویت/پیکربندی دستگاه و فروشگاه).
#: «pos.currency» و «time.» عمداً اینجا هستند: واحد پول و منطقهٔ زمانی روی
#: معنای داده‌های ذخیره‌شده اثر می‌گذارند؛ بازنشانی کورکورانهٔ آن‌ها فاجعه است.
PRESERVED_SETTING_PREFIXES: tuple[str, ...] = (
    "store.", "pos.currency", "time.", "printer.", "sms.", "relay.", "license.", "licence.",
    "update.", "cloud.", "security.", "network.", "ai.", "support.",
)
PRESERVED_SETTING_KEYS: frozenset[str] = frozenset({
    "bank.seeded",          # نشانهٔ بانک کالا: بانک مرجع است و دوباره ساخته نمی‌شود
    "dq.last_verdict",
})

#: برچسب فارسی هر جدول برای «نقشهٔ بازنشانی» (کاربر باید بفهمد چه چیزی می‌رود).
TABLE_LABELS: dict[str, str] = {
    "invoice_items": "ردیف‌های فاکتور", "payments": "پرداخت‌ها", "returns": "مرجوعی‌ها",
    "coupon_redemptions": "مصرف کوپن‌ها", "campaign_redemptions": "مصرف جشنواره‌ها",
    "customer_ledger_entries": "گردش حساب مشتریان", "invoices": "فاکتورها",
    "coupons": "کوپن‌ها", "campaigns": "جشنواره‌ها و کمپین‌ها",
    "stocktake_items": "ردیف‌های انبارگردانی", "stocktakes": "انبارگردانی‌ها",
    "stock_movements": "گردش موجودی", "price_versions": "تاریخچهٔ قیمت",
    "product_batches": "Batchها (موجودی و تاریخ انقضا)", "product_resolver_results": "نتایج بارکدخوان",
    "market_prices": "قیمت‌های بازار", "image_assets": "تصاویر ذخیره‌شده",
    "acc_journal_lines": "ردیف‌های دفتر روزنامه", "acc_journal_entries": "اسناد حسابداری",
    "acc_expenses": "هزینه‌ها", "acc_cheques": "چک‌ها", "acc_cash_sessions": "شیفت‌های صندوق",
    "acc_fiscal_periods": "دوره‌های مالی",
    "hr_shift_attendance": "حضور/خروج کارکنان", "hr_shift_assignments": "تخصیص شیفت",
    "hr_shifts": "تعریف شیفت‌ها", "hr_payroll": "حقوق و دستمزد",
    "hr_score_events": "امتیاز کارکنان", "hr_achievements": "دستاوردهای کارکنان",
    "announcement_reads": "خوانده‌های اطلاعیه", "announcements": "اطلاعیه‌ها",
    "ai_insights": "پیشنهادهای هوش فروشگاه", "experiments": "آزمایش‌ها و اثرسنجی",
    "diagnostic_runs": "اجراهای تشخیصی", "notifications": "اعلان‌ها", "sms_messages": "پیامک‌ها",
    "sync_jobs": "صف همگام‌سازی موبایل", "support_messages": "پیام‌های پشتیبانی",
    "support_tickets": "تیکت‌های پشتیبانی", "audit_logs": "گزارش حسابرسی",
    "counters": "شمارنده‌ها (شمارهٔ فاکتور)", "user_widget_layouts": "چیدمان داشبورد کاربران",
    "products": "کالاها", "storage_locations": "محل‌های نگهداری", "warehouses": "انبارها",
    "acc_suppliers": "تأمین‌کنندگان", "brands": "برندها", "categories": "دسته‌بندی‌ها",
}

#: جدول‌هایی که هنگام reset_users پاک می‌شوند (به‌جز مدیر).
USER_TABLES: tuple[str, ...] = ("user_roles", "user_permissions", "user_widget_layouts")


class FactoryResetError(RuntimeError):
    """خطای قابل‌نمایش به کاربر (پیام فارسی در ``detail``)."""


def _rows(db: Session, table: str) -> int:
    try:
        return int(db.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar_one())
    except Exception:
        return 0


def _table_names(db: Session) -> set[str]:
    try:
        return set(sa_inspect(db.get_bind()).get_table_names())
    except Exception:
        return set()


def _mode_error(mode: str) -> None:
    if mode not in ("full", "keep_catalog"):
        raise FactoryResetError("حالت بازنشانی نامعتبر است (full | keep_catalog)")


def plan(db: Session, *, mode: str = "full", reset_users: bool = False,
         keep_support: bool = False) -> dict:
    """«نقشهٔ بازنشانی»: دقیقاً چه چیزی پاک می‌شود و چه چیزی می‌ماند (dry-run)."""
    _mode_error(mode)
    existing = _table_names(db)
    wipe = [t for t in WIPE_ORDER if t in existing and (t not in ("support_messages", "support_tickets") or not keep_support)]
    catalog = [t for t in CATALOG_ORDER if t in existing]
    if mode == "full":
        wipe = wipe + catalog

    delete_rows = [{"table": t, "label": TABLE_LABELS.get(t, t), "rows": _rows(db, t)}
                   for t in wipe]
    keep_rows = [{"table": t, "label": TABLE_LABELS.get(t, t), "rows": _rows(db, t)}
                 for t in PRESERVED_TABLES if t in existing]

    settings_rows = db.execute(select(SystemSetting)).scalars().all()
    reset_keys = sorted(s.key for s in settings_rows
                        if not any(s.key.startswith(p) for p in PRESERVED_SETTING_PREFIXES)
                        and s.key not in PRESERVED_SETTING_KEYS)
    kept_keys = sorted(s.key for s in settings_rows if s.key not in reset_keys)

    from ..bootstrap import DEFAULT_SETTINGS
    users = db.execute(select(User)).scalars().all()
    media = _media_files()
    warnings: list[str] = [
        "پیش از هر تغییری یک نسخهٔ پشتیبان کامل گرفته می‌شود؛ اگر پشتیبان‌گیری شکست بخورد، بازنشانی انجام نمی‌شود.",
        "کاربران، نقش‌ها و دسترسی‌ها به‌صورت پیش‌فرض می‌مانند تا پس از بازنشانی بتوانید وارد شوید.",
    ]
    if mode == "keep_catalog":
        warnings.append("حالت «حفظ کالاها»: کالاها می‌مانند اما موجودی صفر می‌شود (همهٔ Batchها پاک می‌شوند).")
    else:
        warnings.append("حالت «نصب تازه»: کالاها هم پاک و بانک کالای پیش‌فرض دوباره ساخته می‌شود.")
    if reset_users:
        warnings.append("«بازنشانی کاربران» فعال است: همهٔ کاربران به‌جز مدیر اصلی حذف می‌شوند.")
    if keep_support:
        warnings.append("تیکت‌های پشتیبانی حفظ می‌شوند.")

    return {
        "mode": mode,
        "modes": {
            "full": "بازگشت به نصب تازه (کالاها هم پاک می‌شوند و بانک پیش‌فرض ساخته می‌شود)",
            "keep_catalog": "حفظ کالاها و دسته‌بندی‌ها؛ فقط عملیات و موجودی صفر می‌شود",
        },
        "confirmation_phrase": CONFIRMATION_PHRASE,
        "delete": delete_rows,
        "delete_total": sum(r["rows"] for r in delete_rows),
        "keep": keep_rows,
        "settings_reset": [{"key": k, "new_value": DEFAULT_SETTINGS[k][0],
                            "description": DEFAULT_SETTINGS[k][1]}
                           for k in reset_keys if k in DEFAULT_SETTINGS],
        # کلیدهای عملیاتی بدون پیش‌فرض رسمی: ردیف حذف می‌شود (بازگشت به پیش‌فرض داخلی).
        "settings_reset_unknown": [k for k in reset_keys if k not in DEFAULT_SETTINGS],
        "settings_kept": kept_keys,
        "media_files": media[0],
        "media_bytes": media[1],
        "users": {"total": len(users), "reset_users": reset_users,
                  "kept_admin": settings.ADMIN_USERNAME},
        "database_bytes": _db_bytes(db),
        "backup_required": True,
        "warnings": warnings,
    }


def _db_bytes(db: Session) -> int:
    path = settings.DATABASE_URL.split("///")[-1]
    try:
        return Path(path).stat().st_size
    except Exception:
        return 0


def _media_dir() -> Path:
    return Path(settings.MEDIA_DIR) / "products"


def _media_files() -> tuple[int, int]:
    d = _media_dir()
    if not d.is_dir():
        return 0, 0
    files = [f for f in d.rglob("*") if f.is_file()]
    return len(files), sum(f.stat().st_size for f in files)


def _online_backup(db: Session, *, label: str) -> Path:
    """پشتیبان SQLite با API رسمی (نه کپی خام) — همان روشی که /system/backup دارد."""
    if not settings.DATABASE_URL.startswith("sqlite"):
        raise FactoryResetError("بازنشانی برای پایگاه SQLite پیاده‌سازی شده است")
    db_path = settings.DATABASE_URL.split("///")[-1]
    if db_path == ":memory:":
        raise FactoryResetError("پایگاه درون‌حافظه‌ای قابل بازنشانی نیست")
    backup_dir = settings.data_dir / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    dest = backup_dir / f"supermarket_{datetime.utcnow().strftime('%Y%m%d_%H%M%S_%f')}_{label}.db"
    source = sqlite3.connect(db_path)
    target = sqlite3.connect(str(dest))
    try:
        source.backup(target)
    finally:
        source.close()
        target.close()
    if not dest.exists() or dest.stat().st_size == 0:
        raise FactoryResetError("نسخهٔ پشتیبان ساخته نشد؛ بازنشانی متوقف شد")
    return dest


def _reset_sequences(db: Session, tables: list[str]) -> None:
    if db.get_bind().dialect.name != "sqlite":
        return
    try:
        for table in tables:
            db.execute(text("DELETE FROM sqlite_sequence WHERE name = :t"), {"t": table})
    except Exception:      # جدولی بدون AUTOINCREMENT یا پایگاهی بدون sqlite_sequence
        pass


def execute(db: Session, *, actor: User | None, mode: str = "full", reset_users: bool = False,
            keep_support: bool = False, confirmation: str = "", reason: str | None = None) -> dict:
    """اجرای واقعی بازنشانی. خروجی: گزارش کامل کاری که انجام شد."""
    _mode_error(mode)
    if (confirmation or "").strip() != CONFIRMATION_PHRASE:
        raise FactoryResetError(f"عبارت تأیید درست نیست؛ باید عیناً «{CONFIRMATION_PHRASE}» نوشته شود")

    started = datetime.utcnow()
    before = plan(db, mode=mode, reset_users=reset_users, keep_support=keep_support)

    backup = _online_backup(db, label=mode)
    manifest_path = backup.with_suffix(".factory-reset.json")
    manifest = {"created_at": started.isoformat(), "mode": mode, "reset_users": bool(reset_users),
                "keep_support": bool(keep_support), "reason": reason or "",
                "actor": getattr(actor, "username", None), "plan": before, "backup": str(backup)}
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    existing = _table_names(db)
    deleted: dict[str, int] = {}
    tables = [t for t in WIPE_ORDER if t in existing
              and (t not in ("support_messages", "support_tickets") or not keep_support)]
    if mode == "full":
        tables += [t for t in CATALOG_ORDER if t in existing]

    try:
        for table in tables:
            deleted[table] = _rows(db, table)
            db.execute(text(f"DELETE FROM {table}"))
        db.flush()

        if reset_users:
            # مدیر اصلی و کاربرِ همین درخواست همیشه می‌مانند؛ بقیه حذف می‌شوند.
            kept_ids = [u.id for u in db.execute(select(User)).scalars().all()
                        if u.username == settings.ADMIN_USERNAME or (actor is not None and u.id == actor.id)]
            kept_sql = ", ".join(str(int(i)) for i in kept_ids) or "0"   # فقط عدد صحیح از خود پایگاه
            for table in USER_TABLES:
                if table in existing:
                    db.execute(text(f"DELETE FROM {table}"))
            db.execute(text(f"DELETE FROM users WHERE id NOT IN ({kept_sql})"))
            db.flush()

        # تنظیمات: فقط کلیدهای عملیاتی به مقدار پیش‌فرض برمی‌گردند.
        from ..bootstrap import DEFAULT_SETTINGS
        settings_reset: list[str] = []
        for row in db.execute(select(SystemSetting)).scalars().all():
            if any(row.key.startswith(p) for p in PRESERVED_SETTING_PREFIXES):
                continue
            if row.key in PRESERVED_SETTING_KEYS:
                continue
            if row.key in DEFAULT_SETTINGS:
                row.value = DEFAULT_SETTINGS[row.key][0]
                settings_reset.append(row.key)
            else:
                # کلید عملیاتیِ ناشناخته (بدون پیش‌فرض رسمی): حذف می‌شود تا
                # برنامه به پیش‌فرض داخلی خودش برگردد، نه به مقدار باقی‌مانده.
                db.delete(row)
                settings_reset.append(row.key)
        db.flush()

        _reset_sequences(db, tables)
        db.commit()
    except Exception as exc:                        # هیچ‌چیز نیمه‌کاره نمی‌ماند
        db.rollback()
        raise FactoryResetError(f"بازنشانی نیمه‌کاره متوقف شد (داده‌ها دست‌نخورده‌اند): {exc}") from exc

    # وضعیت پایه (نقش‌ها/مجوزها/تنظیمات/واحدها/بانک کالا/کاربر مدیر) دوباره ساخته می‌شود.
    from ..bootstrap import bootstrap
    bootstrap(db)
    db.commit()

    # در حالت «نصب تازه»، همان مسیر راه‌اندازی اول برنامه دوباره اجرا می‌شود تا
    # کاتالوگ پیش‌فرضِ همراه برنامه (≈۱۷٬۰۰۰ قلم، با موجودی صفر) برگردد — وگرنه
    # فروشگاهی که بازنشانی کرده، کالایی برای فروش نداشت و «پایه» یعنی نصب تازه
    # به‌دست نمی‌آمد. نشانهٔ نسخهٔ کاتالوگ هم در بازنشانی پاک شده است، پس import
    # واقعاً اجرا می‌شود (idempotent است و هیچ موجودی نمی‌سازد).
    catalog_result: dict | None = None
    if mode == "full":
        try:
            from . import default_catalog
            catalog_result = default_catalog.ensure_bundled_update(db)
            db.commit()
        except Exception as exc:
            db.rollback()
            log.warning("factory reset: default catalog reseed failed: %r", exc)
            catalog_result = {"ok": False, "error": repr(exc)}

    media_removed, media_bytes = 0, 0
    if mode == "full":
        d = _media_dir()
        if d.is_dir():
            files = [f for f in d.rglob("*") if f.is_file()]
            media_removed, media_bytes = len(files), sum(f.stat().st_size for f in files)
            shutil.rmtree(d, ignore_errors=True)
            d.mkdir(parents=True, exist_ok=True)

    finished = datetime.utcnow()
    report = {"ok": True, "mode": mode, "started_at": started.isoformat(),
              "finished_at": finished.isoformat(), "seconds": round((finished - started).total_seconds(), 2),
              "backup_path": str(backup), "manifest_path": str(manifest_path),
              "deleted": deleted, "deleted_total": sum(deleted.values()),
              "tables_wiped": len(deleted), "settings_reset": len(before["settings_reset"]),
              "media_files_removed": media_removed, "media_bytes_removed": media_bytes,
              "users_reset": bool(reset_users), "kept_users": _rows(db, "users"),
              "catalog_reseeded": catalog_result, "products_after": _rows(db, "products")}
    try:                       # رکورد پایدارِ خود عملیات، بعد از پاک‌سازی نوشته می‌شود
        from .audit import write_audit
        write_audit(db, action="FACTORY_RESET", user_id=getattr(actor, "id", None),
                    entity_type="System", entity_id=None,
                    after={"mode": mode, "deleted_total": report["deleted_total"],
                           "tables": report["tables_wiped"], "backup": backup.name,
                           "reason": (reason or "")[:200], "reset_users": bool(reset_users)})
        db.commit()
    except Exception:
        db.rollback()
    return report
