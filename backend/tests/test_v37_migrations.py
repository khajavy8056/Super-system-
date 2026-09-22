# -*- coding: utf-8 -*-
"""v3.7 — Alembic is the sole schema manager: migration-path tests.

1. ``upgrade head`` on an EMPTY database must produce EXACTLY the schema the
   models describe (every table, every column) — this is what every fresh
   install boots from now that ``create_all`` is gone from the runtime path.
2. Downgrade of the v3.7 step and re-upgrade must round-trip (downgrade to
   ``base`` is intentionally NOT supported: one historical revision keeps its
   tables on purpose to avoid destroying shop data).
3. A real checkout (POS + accounting + audit writes) must work on a migrated
   database — proving the migrated column types are behaviourally identical.
4. A pre-3.7 database (built by ``create_all``, stamped at an older revision
   or unstamped) must upgrade to head without losing data.
"""
from __future__ import annotations

import os
import tempfile
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config as AlembicConfig
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text

BACKEND = Path(__file__).resolve().parent.parent


def _cfg(url: str) -> AlembicConfig:
    cfg = AlembicConfig()
    cfg.set_main_option("script_location", str(BACKEND / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg


@pytest.fixture()
def migrated_url():
    d = tempfile.mkdtemp(prefix="mig37_")
    url = f"sqlite:///{d}/migrated.db"
    command.upgrade(_cfg(url), "head")
    return url


def _model_tables() -> dict[str, set[str]]:
    from app.database import Base
    import app.models  # noqa: F401
    return {t.name: {c.name for c in t.columns} for t in Base.metadata.sorted_tables}


def test_upgrade_head_matches_modelsExactly(migrated_url):
    """Parity guard: the migration chain must equal the models, forever."""
    insp = inspect(create_engine(migrated_url))
    db_tables = {t: {c["name"] for c in insp.get_columns(t)}
                 for t in insp.get_table_names() if t != "alembic_version"}
    models = _model_tables()
    assert set(db_tables) == set(models), (
        "tables only in db=%s tables only in models=%s"
        % (sorted(set(db_tables) - set(models)), sorted(set(models) - set(db_tables))))
    for t, cols in models.items():
        assert db_tables[t] == cols, (
            f"table {t}: only in db={sorted(db_tables[t] - cols)} "
            f"only in models={sorted(cols - db_tables[t])}")


def test_head_revision_is_v37_catchup(migrated_url):
    cfg = _cfg(migrated_url)
    heads = ScriptDirectory.from_config(cfg).get_heads()
    assert heads == ["f7a1c2d3e4b5"]
    eng = create_engine(migrated_url)
    with eng.connect() as c:
        assert c.execute(text("select version_num from alembic_version")).scalar_one() == heads[0]


def test_downgrade_one_step_and_reupgrade_preserves_shop_data():
    """Downgrade the v3.7 revision and re-upgrade: v3.7 objects come and go,
    shop data (products, …) is never touched.

    Note: downgrade-to-``base`` is NOT the project contract — one historical
    revision (warehouses) deliberately keeps its tables on downgrade to avoid
    destroying shop data, so ``base`` is not empty by design. The supported
    downgrade is the v3.7 step itself (dev/test use; production never
    downgrades — the app only moves forward).
    """
    from sqlalchemy.orm import sessionmaker
    import app.models as m

    d = tempfile.mkdtemp(prefix="mig37down_")
    url = f"sqlite:///{d}/roundtrip.db"
    cfg = _cfg(url)
    command.upgrade(cfg, "head")

    eng = create_engine(url)
    Session = sessionmaker(bind=eng)
    db = Session()
    db.add(m.Product(barcode="6269990000077", name="Roundtrip Rice"))
    db.commit()
    db.close()

    command.downgrade(cfg, "-1")
    insp = inspect(create_engine(url))
    assert "experiments" not in insp.get_table_names()
    assert "product_bank" not in insp.get_table_names()
    assert "next_retry_at" not in {c["name"] for c in insp.get_columns("sms_messages")}
    # shop data survives the downgrade
    db = Session()
    try:
        assert db.query(m.Product).filter_by(barcode="6269990000077").count() == 1
    finally:
        db.close()

    command.upgrade(cfg, "head")
    insp2 = inspect(create_engine(url))
    assert set(t for t in insp2.get_table_names() if t != "alembic_version") == set(_model_tables())
    db = Session()
    try:
        assert db.query(m.Product).filter_by(barcode="6269990000077").count() == 1
    finally:
        db.close()


def test_checkout_works_on_migrated_schema(migrated_url):
    """End-to-end proof: sell on a migrated DB (POS + ledger + accounting + audit)."""
    from sqlalchemy.orm import sessionmaker
    from app import models as m
    from app.bootstrap import bootstrap
    from app.services import pos as pos_svc

    eng = create_engine(migrated_url, connect_args={"check_same_thread": False})
    Session = sessionmaker(bind=eng)
    db = Session()
    try:
        bootstrap(db)
        db.commit()
        prod = m.Product(barcode="6269990000013", name="Migrated Milk")
        db.add(prod)
        db.flush()
        batch = m.ProductBatch(
            product_id=prod.id, batch_number="M1", quantity_received=Decimal(10),
            current_qty=Decimal(10), buy_price=Decimal(50000),
            consumer_price=Decimal(70000), sell_price=Decimal(60000),
            expiry_date=date.today() + timedelta(days=30),
            received_at=__import__("datetime").datetime.utcnow(), status="ACTIVE")
        db.add(batch)
        db.commit()
        user = db.query(m.User).filter_by(username="admin").one()
        inv = pos_svc.checkout(
            db, items=[pos_svc.CartItem(product_id=prod.id, quantity=Decimal(2))],
            payments=[{"method": "CASH", "amount": "120000"}], user=user)
        db.commit()
        assert inv.invoice_number.startswith("INV-")
        assert inv.total_amount == Decimal("120000")
        assert db.get(m.ProductBatch, batch.id).current_qty == Decimal(8)
        # accounting posted in the same transaction
        assert db.query(m.JournalEntry).count() >= 1
    finally:
        db.close()


def test_pre37_create_all_db_upgrades_without_data_loss():
    """Simulates a shop database written by a pre-3.7 release (create_all +
    stamp at the previous head): upgrade to the new head must keep its rows."""
    from sqlalchemy.orm import sessionmaker
    from app.database import Base
    import app.models as m  # noqa: F401

    d = tempfile.mkdtemp(prefix="mig37legacy_")
    url = f"sqlite:///{d}/legacy.db"
    eng = create_engine(url)
    Base.metadata.create_all(eng)  # what pre-3.7 init_db did
    Session = sessionmaker(bind=eng)
    db = Session()
    db.add(m.Product(barcode="6269990000099", name="Legacy Beans"))
    db.commit()
    db.close()

    cfg = _cfg(url)
    command.stamp(cfg, "c4d5e6f7a8b9")  # previous head, as the old _sync_alembic did
    command.upgrade(cfg, "head")

    db2 = Session()
    try:
        assert db2.query(m.Product).filter_by(barcode="6269990000099").count() == 1
        assert "product_bank" in inspect(eng).get_table_names()
        assert "experiments" in inspect(eng).get_table_names()
        cols = {c["name"] for c in inspect(eng).get_columns("sms_messages")}
        assert "next_retry_at" in cols
    finally:
        db2.close()


def test_strict_reconcile_raises_on_failure(monkeypatch):
    """The legacy bridge must fail loudly, never boot on a half schema."""
    from app import database as dbmod

    def _boom(*a, **k):
        raise RuntimeError("boom")
    monkeypatch.setattr(dbmod, "_add_column_ddl", _boom)
    # force at least one "missing column" by pointing at a table the live test
    # DB lacks — simplest honest trigger: a model table dropped from a scratch DB
    d = tempfile.mkdtemp(prefix="mig37strict_")
    url = f"sqlite:///{d}/strict.db"
    eng = create_engine(url)
    dbmod.Base.metadata.create_all(eng)
    with eng.begin() as c:
        c.execute(text("ALTER TABLE products DROP COLUMN gallery"))
    monkeypatch.setattr(dbmod, "engine", eng)
    with pytest.raises(dbmod.MigrationError):
        dbmod._reconcile_schema(strict=True)
