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
    # Self-healing schema reconciliation (v1.2.5). ``create_all`` only creates
    # MISSING TABLES; it never adds columns to tables that already exist. A
    # shop database created by an older release (or one whose alembic_version
    # table is absent, e.g. v0.x) therefore kept an old ``units`` table and the
    # first SELECT crashed the installed app with "no such column:
    # units.allow_decimal". Any column present in the models but missing in
    # the database is now added in place (additive only, data preserved).
    _reconcile_schema()
    with SessionLocal() as db:
        bootstrap(db)


def _reconcile_schema() -> list[str]:
    """Add every model column missing from the live database. Returns the
    list of ``table.column`` names added. Never destructive, never fatal."""
    import logging

    from sqlalchemy import inspect, text

    log = logging.getLogger("supermarket.db")
    added: list[str] = []
    try:
        insp = inspect(engine)
        existing_tables = set(insp.get_table_names())
        with engine.begin() as conn:
            for table in Base.metadata.sorted_tables:
                if table.name not in existing_tables:
                    continue
                have = {c["name"] for c in insp.get_columns(table.name)}
                for col in table.columns:
                    if col.name in have:
                        continue
                    ddl = _add_column_ddl(conn, table.name, col)
                    conn.execute(text(ddl))
                    added.append(f"{table.name}.{col.name}")
        if added:
            log.warning("schema reconciled: added missing columns %s", ", ".join(added))
    except Exception as exc:  # pragma: no cover - defensive
        log.error("schema reconciliation failed: %s", exc)
    return added


def _add_column_ddl(conn, table: str, col) -> str:
    """Render ``ALTER TABLE ... ADD COLUMN`` for one column, with a safe
    default so NOT NULL columns can be added to non-empty tables."""
    from sqlalchemy.schema import CreateColumn

    spec = str(CreateColumn(col).compile(dialect=conn.dialect))
    # SQLite cannot add a NOT NULL column without a default; if the model has
    # no server_default derive one from the Python default or a type-neutral
    # fallback so the ALTER never fails mid-way.
    if "NOT NULL" in spec.upper() and "DEFAULT" not in spec.upper():
        default = None
        if col.default is not None and getattr(col.default, "is_scalar", False):
            v = col.default.arg
            default = "1" if v is True else "0" if v is False else repr(v)
        if default is None:
            py = col.type.python_type if hasattr(col.type, "python_type") else str
            try:
                default = "0" if py in (int, float, bool) or py.__name__ == "Decimal" else "''"
            except Exception:
                default = "''"
        spec = spec.replace("NOT NULL", f"NOT NULL DEFAULT {default}", 1)
    # SQLite: PRIMARY KEY / UNIQUE cannot be added via ALTER; strip them.
    for kw in (" PRIMARY KEY", " UNIQUE"):
        spec = spec.replace(kw, "")
    return f"ALTER TABLE {table} ADD COLUMN {spec}"


def _sync_alembic() -> None:
    """Stamp fresh databases and bring stamped ones up to head. Never fatal."""
    import logging

    from alembic import command
    from alembic.config import Config as AlembicConfig
    from sqlalchemy import inspect

    log = logging.getLogger("supermarket.db")
    try:
        # In a frozen build the source tree is gone; the migrations are
        # bundled next to the executable instead. Check both layouts so an
        # installed shop can still upgrade its schema on a later release.
        import sys

        roots = [Path(__file__).resolve().parent.parent]
        if getattr(sys, "frozen", False):
            exe_dir = Path(sys.executable).resolve().parent
            roots = [exe_dir, exe_dir / "lib", Path(getattr(sys, "_MEIPASS", exe_dir))] + roots
        for root in roots:
            if (root / "alembic" / "env.py").exists():
                backend_dir = root
                break
        else:
            raise RuntimeError(
                f"alembic tree not found (looked in: {[str(r) for r in roots]})")
        ini = backend_dir / "alembic.ini"
        cfg = AlembicConfig(str(ini) if ini.exists() else None)
        cfg.set_main_option("script_location", str(backend_dir / "alembic"))
        cfg.set_main_option("sqlalchemy.url", settings.DATABASE_URL)
        if not inspect(engine).has_table("alembic_version"):
            command.stamp(cfg, "head")
        else:
            command.upgrade(cfg, "head")
    except Exception as exc:  # e.g. frozen executable without the alembic tree
        log.warning("Alembic sync skipped: %s", exc)
