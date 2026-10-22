# -*- coding: utf-8 -*-
"""build-488 — اطلاعیه‌های داخلی (§۱۴–۱۷).

هدف: انتشار اطلاعیه با مخاطب‌گیری دقیق (همه / فروشگاه / Roleها / کاربران) و
پیگیری وضعیت «دریافت → دیده شده → خوانده شده» برای هر کاربر.

- ایجاد اطلاعیه فقط با Permission (نه عنوان شغلی): announcements.publish (§۱۵)
- حذف/لغو هر اطلاعیه: announcements.manage
- اطلاعیهٔ مهم به Notification (زنگ اعلان) هم می‌رود (§۱۷)
- خروجی/فهرست کاربر همیشه بر اساس مخاطب بودنِ او فیلتر می‌شود.
"""
from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Announcement, AnnouncementRead, Notification, User


class AnnouncementError(Exception):
    def __init__(self, code: str, message: str = ""):
        self.code = code
        super().__init__(message or code)


def _now() -> datetime:
    return datetime.utcnow()


def _json_list(raw: str | None) -> list:
    try:
        v = json.loads(raw or "[]")
        return v if isinstance(v, list) else []
    except Exception:
        return []


def target_user_ids(db: Session, ann: Announcement) -> set[int] | None:
    """شناسهٔ کاربران مخاطب؛ None = همهٔ کاربران فعال."""
    kind = ann.target_kind or "ALL"
    if kind == "ALL":
        return None
    if kind == "USERS":
        return {int(u) for u in _json_list(ann.target_users)}
    if kind == "ROLES":
        names = set(_json_list(ann.target_roles))
        ids = set()
        for u in db.execute(select(User).where(User.is_active.is_(True))).scalars():
            if any(r.name in names for r in u.roles):
                ids.add(u.id)
        return ids
    if kind == "STORE":
        # کاربران همان فروشگاه + کارکنان «همهٔ فروشگاه‌ها» (بدون فروشگاه ثبت‌شده)
        store = ann.target_store or ""
        ids = set()
        for u in db.execute(select(User).where(User.is_active.is_(True))).scalars():
            if not store or not (u.store or "") or u.store == store:
                ids.add(u.id)
        return ids
    return None


def is_audience(db: Session, ann: Announcement, user: User) -> bool:
    ids = target_user_ids(db, ann)
    return ids is None or user.id in ids


def visible_states(db: Session, user: User) -> list[tuple[Announcement, AnnouncementRead | None]]:
    """اطلاعیه‌های قابل مشاهدهٔ کاربر + وضعیت خواندنش (جدیدترین اول)."""
    now = _now()
    out: list[tuple[Announcement, AnnouncementRead | None]] = []
    rows = db.execute(select(Announcement).order_by(Announcement.created_at.desc()).limit(200)).scalars().all()
    for ann in rows:
        if ann.status == "CANCELLED":
            continue
        if ann.status == "DRAFT" and ann.created_by != user.id:
            continue
        if ann.publish_at and ann.publish_at > now and ann.created_by != user.id:
            continue
        if ann.expires_at and ann.expires_at <= now:
            continue
        if not is_audience(db, ann, user):
            continue
        read = db.execute(select(AnnouncementRead).where(
            AnnouncementRead.announcement_id == ann.id,
            AnnouncementRead.user_id == user.id)).scalar_one_or_none()
        out.append((ann, read))
    return out


def _ensure_read(db: Session, ann: Announcement, user: User) -> AnnouncementRead:
    read = db.execute(select(AnnouncementRead).where(
        AnnouncementRead.announcement_id == ann.id,
        AnnouncementRead.user_id == user.id)).scalar_one_or_none()
    if read is None:
        read = AnnouncementRead(announcement_id=ann.id, user_id=user.id, delivered_at=_now())
        db.add(read)
        db.flush()
    return read


def mark_seen(db: Session, ann: Announcement, user: User) -> AnnouncementRead:
    """«در فهرست دیده شد» (§۱۷) — فقط بار اول ثبت می‌شود."""
    read = _ensure_read(db, ann, user)
    if read.seen_at is None:
        read.seen_at = _now()
    db.commit()
    return read


def mark_read(db: Session, ann: Announcement, user: User) -> AnnouncementRead:
    read = _ensure_read(db, ann, user)
    read.seen_at = read.seen_at or _now()
    read.read_at = _now()
    db.commit()
    return read


def create(db: Session, *, title: str, body: str, user: User,
           priority: int = 3, publish_at: datetime | None = None,
           expires_at: datetime | None = None,
           target_kind: str = "ALL", target_store: str | None = None,
           target_roles: list[str] | None = None,
           target_users: list[int] | None = None,
           attachment_path: str | None = None,
           status: str = "PUBLISHED") -> Announcement:
    if not title.strip():
        raise AnnouncementError("EMPTY_TITLE", "عنوان اطلاعیه خالی است")
    kind = (target_kind or "ALL").upper()
    if kind not in ("ALL", "STORE", "ROLES", "USERS"):
        raise AnnouncementError("BAD_TARGET", f"نوع مخاطب نامعتبر: {target_kind}")
    if kind == "ROLES" and not target_roles:
        raise AnnouncementError("BAD_TARGET", "برای مخاطب Role باید دست‌کم یک Role انتخاب شود")
    if kind == "USERS" and not target_users:
        raise AnnouncementError("BAD_TARGET", "برای مخاطب کاربر باید دست‌کم یک کاربر انتخاب شود")
    now = _now()
    if publish_at and publish_at > now and status == "PUBLISHED":
        status = "SCHEDULED"
    ann = Announcement(
        title=title.strip()[:255], body=body or "", created_by=user.id,
        status=status, priority=max(1, min(5, int(priority))),
        publish_at=publish_at, expires_at=expires_at,
        target_kind=kind, target_store=target_store,
        target_roles=json.dumps(target_roles or [], ensure_ascii=False),
        target_users=json.dumps([int(u) for u in (target_users or [])], ensure_ascii=False),
        attachment_path=attachment_path,
    )
    db.add(ann)
    db.flush()
    # زنگ اعلان برای اطلاعیه‌های مهم (فوری/مهم) — §۱۷
    if ann.status == "PUBLISHED" and ann.priority <= 2:
        n = Notification(type="ANNOUNCEMENT", title=ann.title, body=(ann.body or "")[:500],
                         severity="WARNING" if ann.priority == 1 else "INFO",
                         reference_type="announcement", reference_id=ann.id,
                         created_at=now, user_id=None)
        db.add(n)
    db.commit()
    db.refresh(ann)
    return ann


def cancel(db: Session, ann: Announcement) -> Announcement:
    ann.status = "CANCELLED"
    db.commit()
    return ann


def sweep(db: Session) -> int:
    """SCHEDULED → PUBLISHED و PUBLISHED → EXPIRED بر اساس زمان (idempotent)."""
    now = _now()
    n = 0
    for ann in db.execute(select(Announcement).where(
            Announcement.status.in_(["SCHEDULED", "PUBLISHED"]))).scalars():
        if ann.status == "SCHEDULED" and ann.publish_at and ann.publish_at <= now:
            ann.status = "PUBLISHED"
            n += 1
        elif ann.status == "PUBLISHED" and ann.expires_at and ann.expires_at <= now:
            ann.status = "EXPIRED"
            n += 1
    if n:
        db.commit()
    return n


def out_dict(db: Session, ann: Announcement, user: User | None = None,
             read: AnnouncementRead | None = None) -> dict:
    from ..security import role_title_fa
    creator = db.get(User, ann.created_by) if ann.created_by else None
    return {
        "id": ann.id, "title": ann.title, "body": ann.body,
        "status": ann.status, "priority": ann.priority,
        "created_by": ann.created_by,
        "created_by_name": creator.full_name or creator.username if creator else "",
        "created_at": ann.created_at.isoformat() if ann.created_at else None,
        "publish_at": ann.publish_at.isoformat() if ann.publish_at else None,
        "expires_at": ann.expires_at.isoformat() if ann.expires_at else None,
        "target_kind": ann.target_kind,
        "target_store": ann.target_store,
        "target_roles": _json_list(ann.target_roles),
        "target_roles_titles": [role_title_fa(r) for r in _json_list(ann.target_roles)],
        "target_users": _json_list(ann.target_users),
        "attachment_path": ann.attachment_path,
        "is_read": bool(read and read.read_at),
        "is_seen": bool(read and read.seen_at),
        "read_at": read.read_at.isoformat() if read and read.read_at else None,
    }
