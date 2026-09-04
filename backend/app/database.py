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
    """Create tables + first-run bootstrap (idempotent).

    Alembic is the single migration path going forward (BUG-014): databases
    created here are stamped at the current head, so ``alembic upgrade head``
    never conflicts with ``create_all``; databases stamped at an older revision
    are upgraded programmatically on startup.
    """
    from . import models  # noqa: F401  (register mappers)
    from .bootstrap import bootstrap

    Base.metadata.create_all(bind=engine)
    _sync_alembic()
    with SessionLocal() as db:
        bootstrap(db)


def _sync_alembic() -> None:
    """Stamp fresh databases and bring stamped ones up to head. Never fatal."""
    import logging

    from alembic import command
    from alembic.config import Config as AlembicConfig
    from sqlalchemy import inspect

    log = logging.getLogger("supermarket.db")
    try:
        backend_dir = Path(__file__).resolve().parent.parent
        cfg = AlembicConfig(str(backend_dir / "alembic.ini"))
        cfg.set_main_option("script_location", str(backend_dir / "alembic"))
        if not inspect(engine).has_table("alembic_version"):
            command.stamp(cfg, "head")
        else:
            command.upgrade(cfg, "head")
    except Exception as exc:  # e.g. frozen executable without the alembic tree
        log.warning("Alembic sync skipped: %s", exc)
