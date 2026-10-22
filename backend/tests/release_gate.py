# -*- coding: utf-8 -*-
"""Release-artifact gate (audit 2026-10, finding R-1).

Why this exists
---------------
Several tests assert that ``releases/`` contains a build **of the current
version** (``RasaSystemMobile-<ver>.apk``, ``RasaSystemDesktopUI-<ver>.zip``,
``RasaSystem-Windows-Portable-<ver>.zip``). That is the right assertion for a
release machine, but a fresh clone / CI runner has no binaries at all, so the
whole suite went red for a reason unrelated to the code under test.

This helper keeps the gate where it protects people and removes the noise where
it does not:

* artifact present  → the test runs exactly as before;
* artifact missing  → ``SKIP`` locally, but a hard ``FAIL`` when
  ``RASA_REQUIRE_RELEASE_ARTIFACTS=1`` (set this in the release pipeline).

STATUS AT THE TIME OF THE AUDIT (1.0.525): the Android APK for 1.0.525 exists,
the **Windows** artifacts stop at 1.0.520 — five builds behind the source. That
gap is reported as a finding, not papered over: run the suite with
``RASA_REQUIRE_RELEASE_ARTIFACTS=1`` to see it fail.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest


def _release_gate_enabled() -> bool:
    return os.environ.get("RASA_REQUIRE_RELEASE_ARTIFACTS", "").strip().lower() in (
        "1", "true", "yes", "on")


def require_artifact(path: Path) -> Path:
    """Return ``path`` if it exists; skip (or fail in release mode) otherwise."""
    if path.exists():
        return path
    if _release_gate_enabled():
        pytest.fail(f"release artifact missing (RASA_REQUIRE_RELEASE_ARTIFACTS=1): {path}")
    pytest.skip(f"release artifact not built in this checkout: {path.name}")
    return path  # pragma: no cover - pytest.skip raises
