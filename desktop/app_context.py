# -*- coding: utf-8 -*-
"""هستهٔ اپ دسکتاپ: دسترسی درون‌پروسه‌ای به پایگاه داده و کاربر جاری.

قاعدهٔ امنیتی (دستورالعمل §۷): هیچ نشست/کوکی/توکنی در UI وجود ندارد. کاربر جاری
فقط با ورود بومی (bcrypt) مشخص می‌شود و هر صفحه فقط با مجوزِ همان کاربر ساخته
می‌شود؛ خروج، شیء کاربر جاری را پاک می‌کند.
"""
from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select

from app.database import SessionLocal
from app.models import Customer, Product, SystemSetting, User
from app.security import has_permission, is_admin, user_permissions


class Context:
    """وضعیت مشترک برنامه: کاربر جاری + تنظیمات + پوشهٔ داده."""

    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        self.user: User | None = None

    # ---------- کاربر جاری / مجوزها ----------
    def set_user(self, user: User | None) -> None:
        self.user = user

    def can(self, code: str) -> bool:
        return self.user is not None and has_permission(self.user, code)

    def is_admin(self) -> bool:
        return self.user is not None and is_admin(self.user)

    def permissions(self) -> list[str]:
        return sorted(user_permissions(self.user)) if self.user else []

    def dashboard_profile(self) -> str:
        from app.routers.reports import dashboard_profile
        return dashboard_profile(self.user) if self.user else "seller"

    # ---------- تنظیمات ----------
    def get_setting(self, key: str, default: str = "") -> str:
        db = SessionLocal()
        try:
            row = db.execute(
                select(SystemSetting.value).where(SystemSetting.key == key)
            ).scalar_one_or_none()
            return row if row is not None else default
        finally:
            db.close()

    def set_setting(self, key: str, value: str, secret: bool = False) -> None:
        db = SessionLocal()
        try:
            row = db.execute(
                select(SystemSetting).where(SystemSetting.key == key)
            ).scalar_one_or_none()
            if row is None:
                db.add(SystemSetting(key=key, value=value, is_secret=secret))
            else:
                row.value = value
            db.commit()
        finally:
            db.close()

    def store_name(self) -> str:
        return self.get_setting("store.name", "فروشگاه من")

    # ---------- فاکتور نگه‌داشته‌شده («نگه داشتن فاکتور» §۱۱) ----------
    @property
    def held_path(self) -> Path:
        return self.data_dir / "held_carts.json"

    def hold_cart(self, user_id: int, payload: dict) -> None:
        """سبد جاری را با برچسب نگه می‌دارد — مثل برنامه‌های استاندارد صندوق."""
        items: list = []
        if self.held_path.exists():
            try:
                items = json.loads(self.held_path.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001 — فایل خراب = شروع تازه
                items = []
        items.append({"user_id": user_id, **payload})
        self.held_path.write_text(
            json.dumps(items[-50:], ensure_ascii=False, indent=1), encoding="utf-8")

    def held_carts(self, user_id: int | None = None) -> list[dict]:
        if not self.held_path.exists():
            return []
        try:
            items = json.loads(self.held_path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return []
        if user_id is None:
            return items
        return [c for c in items if c.get("user_id") in (user_id, None)]

    def pop_held_cart(self, index: int) -> dict | None:
        items = self.held_carts()
        if not (0 <= index < len(items)):
            return None
        cart = items.pop(index)
        self.held_path.write_text(
            json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")
        return cart

    # ---------- جست‌وجوی کالا برای POS ----------
    @staticmethod
    def find_products(term: str, limit: int = 40) -> list[Product]:
        db = SessionLocal()
        try:
            stmt = select(Product).where(Product.deleted_at.is_(None), Product.is_active.is_(True))
            term = (term or "").strip()
            if term:
                like = f"%{term}%"
                stmt = stmt.where((Product.name.ilike(like)) | (Product.barcode.ilike(like)))
            return list(db.execute(stmt.order_by(Product.name.asc()).limit(limit)).scalars())
        finally:
            db.close()

    @staticmethod
    def find_customer(term: str) -> Customer | None:
        db = SessionLocal()
        try:
            term = (term or "").strip()
            if not term:
                return None
            stmt = select(Customer).where(Customer.deleted_at.is_(None))
            like = f"%{term}%"
            stmt = stmt.where((Customer.name.ilike(like)) | (Customer.phone.ilike(like)))
            return db.execute(stmt.limit(1)).scalars().first()
        finally:
            db.close()


def money(value) -> str:
    """۱۲۳۴۵۶۷ → «۱٬۲۳۴٬۵۶۷» — ارقام فارسی با جداکننده."""
    try:
        d = Decimal(str(value or 0))
    except Exception:  # noqa: BLE001
        d = Decimal(0)
    text = f"{int(d):,}"
    return text.translate(str.maketrans("0123456789,", "۰۱۲۳۴۵۶۷۸۹٬"))


def fa(text) -> str:
    return str(text).translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹"))
