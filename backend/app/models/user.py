"""Users, roles and permissions (blueprint §5 core, §83–84)."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Table, Column, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import Base
from .base import TimestampMixin

user_permissions = Table(
    "user_permissions",
    Base.metadata,
    Column("user_id", ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("permission_id", ForeignKey("permissions.id", ondelete="CASCADE"), primary_key=True),
)

user_roles = Table(
    "user_roles",
    Base.metadata,
    Column("user_id", ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("role_id", ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
)

role_permissions = Table(
    "role_permissions",
    Base.metadata,
    Column("role_id", ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
    Column("permission_id", ForeignKey("permissions.id", ondelete="CASCADE"), primary_key=True),
)


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(128), default="")
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # «دسترسی فقط به صورت بومی» — the phone may sign this user in ONLY while it
    # is on the shop's own network (the PC answers over LAN). Unchecked → the
    # user may work standalone / from outside the network and the data syncs
    # back when the phone rejoins the LAN. The main admin is exempt by role:
    # standalone access is ON for the Administrator by default.
    local_only: Mapped[bool] = mapped_column(Boolean, default=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # build-488 — تکمیل پروفایل کاربر (بخش ۱ دستور): شماره تماس، عنوان شغلی،
    # تصویر پروفایل، تاریخ استخدام. فیلدها افزودنی‌اند و منطق موجود را نمی‌شکنند.
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    job_title: Mapped[str | None] = mapped_column(String(128), nullable=True)
    avatar_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    hire_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    #: فروشگاه محل خدمت (برای مخاطب‌گیری اطلاعیه و گزارش‌ها؛ خالی = همهٔ فروشگاه‌ها)
    store: Mapped[str | None] = mapped_column(String(128), nullable=True)

    roles: Mapped[list["Role"]] = relationship(secondary=user_roles, back_populates="users")
    #: build-488 — دسترسی مستقیم (مستقل از Role): User → Permissions
    direct_permissions: Mapped[list["Permission"]] = relationship(
        secondary=user_permissions, back_populates="users")


class Role(TimestampMixin, Base):
    __tablename__ = "roles"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    description: Mapped[str] = mapped_column(String(255), default="")
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)

    users: Mapped[list["User"]] = relationship(secondary=user_roles, back_populates="roles")
    permissions: Mapped[list["Permission"]] = relationship(secondary=role_permissions, back_populates="roles")


class Permission(Base):
    __tablename__ = "permissions"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    description: Mapped[str] = mapped_column(String(255), default="")

    roles: Mapped[list["Role"]] = relationship(secondary=role_permissions, back_populates="permissions")
    users: Mapped[list["User"]] = relationship(secondary=user_permissions, back_populates="direct_permissions")
