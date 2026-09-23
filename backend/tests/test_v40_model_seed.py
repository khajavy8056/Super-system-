# -*- coding: utf-8 -*-
"""v4.0 — the Windows installer ships the model; the app must adopt it honestly.

The installer drops ``<data>/brain/models/<model_id>/<file>.gguf`` next to a
``seed.json`` manifest. These tests prove the adoption contract:

* a verified seed becomes INSTALLED and (when nothing is active) is activated;
* adoption is idempotent and does not re-hash an unchanged 1 GB file;
* a tampered file is recorded UNVERIFIED and never activated;
* an unknown model id is ignored;
* ``download()`` never re-downloads an already-seeded model.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from app.models import BrainModelInstall
from app.services.business_brain import model_manager as mm
from _v40_seed import fresh_store


@pytest.fixture()
def seeded_shop(tmp_path, monkeypatch):
    """A shop whose brain models dir is a temp folder, with a fake registry."""
    db = fresh_store()
    models = tmp_path / "brain" / "models"
    models.mkdir(parents=True)
    monkeypatch.setenv("SUPERMARKET_BRAIN_MODELS_DIR", str(models))
    monkeypatch.setattr(mm.model_manager if hasattr(mm, "model_manager") else mm,
                        "models_root", lambda: models)

    payload = b"not a real gguf, but a real checksum" * 128
    digest = hashlib.sha256(payload).hexdigest()

    class _Spec:
        model_id = "test-model-q4"
        file_name = "test-model.gguf"
        sha256 = digest
        source_url = "https://example.org/official/test-model.gguf"
        source_host = "example.org"
        alt_source_urls = ()                     # v4.0.1: official fallback sources
        alt_source_hosts = ()
        file_size_bytes = len(payload)
        min_ram_mb = 0
        gb = 0.1

        @staticmethod
        def within_cap():
            return True

    monkeypatch.setattr(mm.model_registry, "all_models", lambda: [_Spec()])
    monkeypatch.setattr(mm.model_registry, "get", lambda mid: _Spec() if mid == _Spec.model_id else None)
    yield {"db": db, "models": models, "payload": payload, "digest": digest, "spec": _Spec}
    db.close()


def _write_seed(models: Path, spec, payload: bytes, *, digest: str | None = None,
                file_name: str | None = None) -> Path:
    folder = models / spec.model_id
    folder.mkdir(parents=True, exist_ok=True)
    name = file_name or spec.file_name
    (folder / name).write_bytes(payload)
    (folder / "seed.json").write_text(json.dumps({
        "model_id": spec.model_id, "file": name,
        "sha256": digest or hashlib.sha256(payload).hexdigest(),
        "size_bytes": len(payload), "source": "installer",
    }), encoding="utf-8")
    return folder / name


def test_a_verified_seed_is_adopted_and_activated(seeded_shop):
    _write_seed(seeded_shop["models"], seeded_shop["spec"], seeded_shop["payload"])
    manager = mm.ModelManager(seeded_shop["db"])
    report = manager.adopt_preinstalled()
    assert report and report[0]["ok"] is True, report
    assert report[0]["code"] == "ADOPTED"
    assert report[0]["activated"] is True

    row = seeded_shop["db"].query(BrainModelInstall).filter_by(model_id="test-model-q4").one()
    assert row.status == "ACTIVE"
    assert row.sha256 == seeded_shop["digest"]


def test_adoption_is_idempotent_and_does_not_rehash(seeded_shop, monkeypatch):
    target = _write_seed(seeded_shop["models"], seeded_shop["spec"], seeded_shop["payload"])
    manager = mm.ModelManager(seeded_shop["db"])
    assert manager.adopt_preinstalled()[0]["ok"] is True

    # a second run must not hash the file again (it is 1 GB in real life)
    calls = []
    real = mm.sha256_file

    def counting(path, *a, **kw):
        calls.append(str(path))
        return real(path, *a, **kw)

    monkeypatch.setattr(mm, "sha256_file", counting)
    assert manager.adopt_preinstalled() == []
    assert calls == [], "an unchanged seed must be skipped without re-hashing"
    assert seeded_shop["db"].query(BrainModelInstall).count() == 1
    assert target.exists(), "adoption must never delete the owner's file"


def test_a_tampered_seed_is_unverified_and_never_activated(seeded_shop):
    _write_seed(seeded_shop["models"], seeded_shop["spec"], b"tampered bytes" * 64)
    manager = mm.ModelManager(seeded_shop["db"])
    report = manager.adopt_preinstalled()
    assert report[0]["ok"] is False and report[0]["code"] == "CHECKSUM_MISMATCH", report

    row = seeded_shop["db"].query(BrainModelInstall).filter_by(model_id="test-model-q4").one()
    assert row.status == "UNVERIFIED"
    assert manager.active_id() == "", "a corrupt seed must never become the active model"


def test_a_manifest_without_its_file_is_reported_not_crashed(seeded_shop):
    folder = seeded_shop["models"] / seeded_shop["spec"].model_id
    folder.mkdir(parents=True)
    (folder / "seed.json").write_text(json.dumps(
        {"model_id": seeded_shop["spec"].model_id, "file": "missing.gguf",
         "sha256": "0" * 64}), encoding="utf-8")
    manager = mm.ModelManager(seeded_shop["db"])
    report = manager.adopt_preinstalled()
    assert report[0]["code"] == "FILE_MISSING"


def test_unknown_model_dirs_are_ignored(seeded_shop):
    folder = seeded_shop["models"] / "qwen3-4b-q4_k_m"
    folder.mkdir(parents=True)
    (folder / "seed.json").write_text("{}", encoding="utf-8")
    assert mm.ModelManager(seeded_shop["db"]).adopt_preinstalled() == []


def test_download_does_not_refetch_a_seeded_model(seeded_shop):
    _write_seed(seeded_shop["models"], seeded_shop["spec"], seeded_shop["payload"])
    manager = mm.ModelManager(seeded_shop["db"])

    def no_network(*a, **kw):  # any download attempt must fail loudly
        raise AssertionError("the seeded model must not be re-downloaded")

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(manager, "_fetch", no_network)
    try:
        out = manager.download("test-model-q4")
    finally:
        monkeypatch.undo()
    assert out["ok"] is True and out["code"] == "ALREADY_PRESENT", out
    assert out["sha256"] == seeded_shop["digest"]


def test_status_reports_the_installer_seed(seeded_shop):
    _write_seed(seeded_shop["models"], seeded_shop["spec"], seeded_shop["payload"])
    payload = mm.ModelManager(seeded_shop["db"]).status(include_registry=False)
    assert payload["installer_seeds"] and payload["installer_seeds"][0]["ok"] is True
    assert payload["active"] == "test-model-q4"
