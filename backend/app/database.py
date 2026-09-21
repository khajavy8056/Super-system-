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
            from .services.product_search import normalize, compare_names
            dbapi_connection.create_function("product_search_normalize", 1, normalize, deterministic=True)
            dbapi_connection.create_collation("PERSIAN", compare_names)
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
    _ensure_indexes()
    with SessionLocal() as db:
        bootstrap(db)


# v3.3 — indexes for stores with years of history (tens of thousands of invoices).
# Every dashboard / report / insight query becomes an index range scan. Idempotent, never fatal.
PERF_INDEXES = (
    ("ix_perf_inv_created", "invoices", "created_at"),
    ("ix_perf_inv_status_created", "invoices", "status, created_at"),
    ("ix_perf_inv_customer", "invoices", "customer_id, created_at"),
    ("ix_perf_ii_product", "invoice_items", "product_id"),
    ("ix_perf_pb_status_exp", "product_batches", "status, expiry_date"),
    ("ix_perf_pb_product_status", "product_batches", "product_id, status"),
    ("ix_perf_sm_created", "stock_movements", "created_at"),
    ("ix_perf_ai_status", "ai_insights", "status"),
    ("ix_perf_led_customer_created", "customer_ledger_entries", "customer_id, created_at"),
)


def heal_schema() -> dict:
    """Public self-heal: add missing model columns, then (re)create the perf indexes.

    v3.5 — restoring a backup replaces the whole SQLite file with a database
    written by an OLDER release, which by definition lacks the v3.3 performance
    indexes (and any column added since). Nothing re-created them, so a shop that
    restored a backup silently lost the index range scans and went back to full
    table scans on every dashboard/report query. Any code path that swaps or
    rebuilds the live database must call this.
    """
    cols = _reconcile_schema()
    idx = _ensure_indexes()
    return {"columns_added": cols, "indexes_ensured": idx}


def _ensure_indexes() -> list[str]:
    import logging

    from sqlalchemy import inspect, text

    log = logging.getLogger("supermarket.db")
    made: list[str] = []
    try:
        tables = set(inspect(engine).get_table_names())
        with engine.begin() as conn:
            for name, table, cols in PERF_INDEXES:
                if table not in tables:
                    continue
                conn.execute(text(f"CREATE INDEX IF NOT EXISTS {name} ON {table} ({cols})"))
                made.append(name)
    except Exception as exc:  # pragma: no cover - defensive
        log.error("index creation failed: %s", exc)
    return made


def _reconcile_schema() -> list[str]:
    """Add every model column missing from the live database. Returns the
    list of ``table.column`` names added. Never destructive, never fatal."""
    import logging

    from sqlalchemy import inspect, text

    log = logging.getLogger("supermarket.db")
    added: list[str] = []
    failed: list[str] = []
    # v3.5 — drop every pooled connection before reflecting.
    #
    # SQLite caches the schema per connection, and a connection that still holds
    # a read snapshot does NOT see DDL another connection just committed. That
    # produced a nasty contradiction: reflection reported `units.allow_decimal`
    # missing while the ALTER on a second connection failed with "duplicate
    # column name", so the reconcile silently added nothing and the app booted
    # against a schema it had not verified. Reflection here must agree with the
    # connection that is about to run DDL, so both start from a fresh handle.
    try:
        engine.dispose()
    except Exception:  # noqa: BLE001 — a pool that cannot be disposed is not fatal
        log.debug("engine.dispose() before schema reflection failed", exc_info=True)
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
                    # v3.5 — one column per SAVEPOINT. The old code wrapped the
                    # whole loop in a single try/except, so the first column that
                    # failed to ALTER silently aborted the rest and the function
                    # returned [] — the app then booted and crashed later with
                    # "no such column". Each column is now independent and every
                    # failure is reported by name.
                    try:
                        with conn.begin_nested():
                            conn.execute(text(ddl))
                        added.append(f"{table.name}.{col.name}")
                    except Exception as exc:  # noqa: BLE001
                        # "duplicate column name" means the column is in fact
                        # there (stale reflection, or two processes reconciling
                        # at once). That is the desired end state, not a failure.
                        if "duplicate column name" in str(exc).lower():
                            continue
                        failed.append(f"{table.name}.{col.name}: {exc}")
        if added:
            log.warning("schema reconciled: added missing columns %s", ", ".join(added))
        if failed:
            log.error("schema reconciliation could not add: %s", "; ".join(failed))
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
