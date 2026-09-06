"""v1.2.5 regression: a database created by an older release (tables exist
but newer columns are missing, e.g. ``units.allow_decimal``) must be healed
in place on startup instead of crashing the installed app."""
from __future__ import annotations

from sqlalchemy import inspect, text

from app.database import Base, _reconcile_schema, engine
from app import models  # noqa: F401


def _drop_column(table: str, column: str) -> None:
    with engine.begin() as conn:
        conn.execute(text(f"ALTER TABLE {table} DROP COLUMN {column}"))


def test_missing_columns_are_added_back(client, auth_headers):
    # simulate an old schema: SQLite >= 3.35 supports DROP COLUMN
    for col in ("allow_decimal", "decimals"):
        _drop_column("units", col)
    assert "allow_decimal" not in {c["name"] for c in inspect(engine).get_columns("units")}

    added = _reconcile_schema()
    assert "units.allow_decimal" in added and "units.decimals" in added

    cols = {c["name"] for c in inspect(engine).get_columns("units")}
    assert {"allow_decimal", "decimals"} <= cols
    # idempotent
    assert _reconcile_schema() == []
    # the app works again
    assert client.get("/api/units", headers=auth_headers).status_code in (200, 404)
    assert client.get("/api/products", headers=auth_headers).status_code == 200


def test_live_schema_has_no_missing_model_columns():
    insp = inspect(engine)
    tables = set(insp.get_table_names())
    missing = [
        f"{t.name}.{c.name}"
        for t in Base.metadata.sorted_tables
        if t.name in tables
        for c in t.columns
        if c.name not in {x["name"] for x in insp.get_columns(t.name)}
    ]
    assert missing == []
