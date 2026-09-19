"""§80–82 — initial product database, imported with ZERO stock.

v3.5: this module is now a thin compatibility shim. The default bank moved to
:mod:`app.services.default_catalog` because it is no longer a small generic
seed list — it is the full 13 570-line Iranian supermarket catalogue built from
the Excel sheets in ``docs/`` (name + exact GTIN + category tree + up to three
direct picture links). The old names (``import_csv``, ``bundled_summary``,
``BUNDLED``, ``COLUMNS``) are kept so the setup router, the CSV-upload endpoint
and existing tests keep working unchanged.

Two things deliberately went away with v3.5:

* the background picture hunt (OpenFoodFacts / Wikimedia / DuckDuckGo) — the
  bank ships its own pictures, so there is nothing left to look up;
* the EAN-13 «restricted circulation» placeholder codes (``2099…``) — every line
  now carries the real manufacturer GTIN from the source sheets.

Import is still idempotent and still creates Product rows only (no
ProductBatch), so stock is 0 until the first receipt.
"""
from __future__ import annotations

from .default_catalog import (  # noqa: F401  — re-exported for backwards compatibility
    BUNDLED,
    CHUNK,
    COLUMNS,
    bundled_path,
    bundled_summary,
    import_csv,
)

__all__ = ["BUNDLED", "CHUNK", "COLUMNS", "bundled_path", "bundled_summary", "import_csv"]
