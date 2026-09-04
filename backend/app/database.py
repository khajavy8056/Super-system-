"""Database engine/session management.

Uses SQLAlchemy 2.0. SQLite runs in WAL mode for concurrent reads during POS
operation, which is essential for offline, single-machine deployments.
"""
from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import settings


class Base(DeclarativeBase):
    pass


def _make_engine(url: str | None = None):
    url = url or settings.DATABASE_URL
    kwargs: dict = {"future": True}
    if url.startswith("sqlite"):
        path = url.split("///", 1)[-1]
        if path and path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        kwargs["connect_args"] = {"check_same_thread": False, "timeout": 30}

    engine = create_engine(url, pool_pre_ping=True, **kwargs)

    if url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def _set_sqlite_pragma(dbapi_connection, connection_record):  # pragma: no cover
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA busy_timeout=30000")
            cursor.close()

    return engine


engine = _make_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def get_db():
    """FastAPI dependency yielding a scoped session."""
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Create tables + first-run bootstrap (idempotent)."""
    from . import models  # noqa: F401  (register mappers)
    from .bootstrap import bootstrap

    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        bootstrap(db)
