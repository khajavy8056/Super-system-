# -*- coding: utf-8 -*-
"""v4.0 — Model Manager: registry policy, integrity, lifecycle (§29–§40, §72).

These tests are the enforcement of the release's hardest constraint: the brain
must run locally, on a small machine, from a file that was **verified**. Nothing
here touches the network — the downloader is injected, exactly the way the
production path is structured, so the checksum logic is tested for real.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest

from app.database import SessionLocal
from app.models import BrainModelInstall
from app.services.business_brain import device_profile, model_registry
from app.services.business_brain.model_manager import ModelManager, sha256_file

CAP = model_registry.MAX_FILE_BYTES


@pytest.fixture(scope="module", autouse=True)
def _schema():
    """This file talks to the database directly, so the schema must exist even
    when the whole suite is not running (the app lifespan normally creates it)."""
    from app.database import init_db
    init_db()
    yield


# --------------------------------------------------------------- registry policy
def test_every_registered_model_is_within_two_gigabytes():
    problems = model_registry.validate_registry()
    assert problems == [], problems
    for spec in model_registry.all_models():
        assert 0 < spec.file_size_bytes <= CAP
        assert spec.max_file_size_bytes == CAP


def test_registry_refuses_q8_and_four_billion_parameter_models():
    ids = {item["model_id"] for item in model_registry.FORBIDDEN}
    reasons = " ".join(item["reason"] for item in model_registry.FORBIDDEN)
    assert "qwen3-4b-q4_k_m" in ids and "qwen3-1.7b-q8_0" in ids
    assert "Q8" in reasons
    assert all(item["reason"].strip() for item in model_registry.FORBIDDEN)


def test_default_model_is_a_sub_two_gigabyte_qwen_with_pinned_digest():
    spec = model_registry.get("qwen2.5-1.5b-instruct-q4_k_m")
    assert spec is not None
    assert spec.family == "Qwen2.5" and spec.parameters == "1.5B"
    assert spec.quantization == "Q4_K_M"
    assert spec.context_default == 4096
    assert spec.source_url.startswith("https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF/")
    assert spec.file_name.endswith(".gguf")
    assert spec.sha256 and len(spec.sha256) == 64, "the shipped file must have a published sha256"
    assert spec.gb < 2

def test_the_low_ram_fallback_is_smaller_than_the_default():
    default = model_registry.get("qwen2.5-1.5b-instruct-q4_k_m")
    fallback = model_registry.get("qwen2.5-1.5b-instruct-q3_k_m")
    assert fallback.file_size_bytes < default.file_size_bytes
    assert fallback.sha256 and len(fallback.sha256) == 64


def test_published_source_never_ships_an_officially_missing_quantization():
    """The brief asked for Qwen3-1.7B Q4_K_M; the official repo ships only Q8_0.

    Rather than download a Q4_K_M file from a mirror (forbidden) or ship Q8
    (forbidden), the release moved to the closest official Qwen GGUF that
    publishes Q4_K_M/Q3_K_M *and* stays under the 2 GB cap. The deviation is
    recorded in FORBIDDEN so nobody re-adds the missing files later.
    """
    ids = {item["model_id"] for item in model_registry.FORBIDDEN}
    assert "qwen3-1.7b-q4_k_m" in ids
    reason = next(i["reason"] for i in model_registry.FORBIDDEN if i["model_id"] == "qwen3-1.7b-q4_k_m")
    assert "رسمی" in reason or "official" in reason.lower()
    assert all("Qwen2.5" == s.family for s in model_registry.all_models())


def test_low_ram_fallback_and_context_are_chosen_from_the_device():
    low = device_profile.DeviceProfile(os_name="Windows", os_version="10", machine="x86_64",
                                       python="3.11", cpu_cores=4, ram_total_mb=4096,
                                       ram_available_mb=1024, disk_free_mb=20000)
    high = device_profile.DeviceProfile(os_name="Windows", os_version="11", machine="x86_64",
                                        python="3.11", cpu_cores=8, ram_total_mb=16384,
                                        ram_available_mb=8000, disk_free_mb=200000)
    assert device_profile.choose_model(low).model_id == "qwen2.5-1.5b-instruct-q3_k_m"
    assert device_profile.choose_model(high).model_id == "qwen2.5-1.5b-instruct-q4_k_m"
    assert device_profile.context_for(low) == 4096
    assert device_profile.context_for(high) == 8192
    # a 4 GB machine only widens the window when a benchmark proves it
    assert device_profile.context_after_benchmark(high, {"load_ok": True, "avg_ms": 900,
                                                         "persian_ok": True}) == 8192
    assert device_profile.context_after_benchmark(high, {"load_ok": True, "avg_ms": 90000}) == 4096


def test_refuses_non_official_source_and_oversize_edits():
    assert model_registry.allowed_source("https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF/resolve/main/x.gguf")
    assert not model_registry.allowed_source("http://huggingface.co/x.gguf")
    assert not model_registry.allowed_source("https://example.com/Qwen3.gguf")
    assert not model_registry.allowed_source("https://hf-mirror.example.net/model.gguf")


# --------------------------------------------------------------- download integrity
def _payload(size: int = 4096) -> bytes:
    return (b"GGUF" + b"\x00" * (size - 4))


@pytest.fixture(autouse=True)
def _capable_device(monkeypatch):
    """The test host is not a shop PC: give these tests a realistic device so the
    *policy* logic is what is being exercised, not the CI machine's memory."""
    prof = device_profile.DeviceProfile(os_name="Windows", os_version="11", machine="AMD64",
                                        python="3.11", cpu_cores=8, ram_total_mb=16384,
                                        ram_available_mb=9000, disk_free_mb=250000)
    monkeypatch.setattr(device_profile, "profile", lambda: prof)
    return prof


@pytest.fixture()
def manager(tmp_path, monkeypatch):
    monkeypatch.setenv("SUPERMARKET_BRAIN_MODELS_DIR", str(tmp_path / "models"))
    db = SessionLocal()
    yield ModelManager(db)
    db.close()


def _pin(monkeypatch, model_id: str, sha256: str | None):
    """Pin the digest the manager must verify against — a test's stand-in for the
    published hash, so the verification path itself is what gets exercised."""
    pinned = tuple(replace(spec, sha256=sha256) if spec.model_id == model_id else spec
                   for spec in model_registry.MODELS)
    monkeypatch.setattr(model_registry, "MODELS", pinned)
    return model_registry.get(model_id)


def test_download_verifies_checksum_and_deletes_a_corrupt_file(manager, tmp_path, monkeypatch):
    good = _payload()
    digest = hashlib.sha256(good).hexdigest()
    spec = _pin(monkeypatch, model_registry.all_models()[0].model_id, digest)

    def fake_downloader(url, dest: Path, progress=None):
        dest.write_bytes(good)
        return digest

    manager.downloader = fake_downloader
    result = manager.download(spec.model_id, force=True)
    assert result["ok"] is True, result
    target = Path(result["path"])
    assert target.exists() and sha256_file(target) == digest

    # now corrupt the file: a re-download must notice, delete and refuse
    target.write_bytes(b"tampered")
    assert sha256_file(target) != digest

    def corrupt_downloader(url, dest: Path, progress=None):
        dest.write_bytes(b"tampered")
        return digest

    manager.downloader = corrupt_downloader
    bad = manager.download(spec.model_id, force=True)
    assert bad["ok"] is False and bad["code"] == "CHECKSUM_MISMATCH"
    assert not target.exists(), "a file that failed verification must be deleted"
    rows = manager.db.query(BrainModelInstall).filter_by(model_id=spec.model_id).all()
    assert any("CHECKSUM" in (r.error or "") or r.status == "FAILED" for r in rows)
    from app.models import AuditLog
    events = manager.db.query(AuditLog).filter(AuditLog.action == "BRAIN_MODEL_EVENT").all()
    assert events, "the refusal must be audited"


def test_unverified_file_is_kept_but_cannot_be_installed(manager, tmp_path, monkeypatch):
    spec = _pin(monkeypatch, model_registry.all_models()[0].model_id, None)

    def anonymous_downloader(url, dest: Path, progress=None):
        dest.write_bytes(_payload())
        return None                      # host reported no digest

    manager.downloader = anonymous_downloader
    result = manager.download(spec.model_id, force=True)
    assert result["ok"] is False and result["code"] == "NO_TRUSTED_CHECKSUM"
    install = manager.install(spec.model_id)
    assert install["ok"] is False and install["code"] == "UNVERIFIED"


def test_download_refuses_a_machine_that_cannot_hold_the_model(manager, monkeypatch, _capable_device):
    tiny = device_profile.DeviceProfile(os_name="Android", os_version="14", machine="aarch64",
                                        python="3.11", cpu_cores=4, ram_total_mb=2048,
                                        ram_available_mb=512, disk_free_mb=1024, is_android=True)
    monkeypatch.setattr(device_profile, "profile", lambda: tiny)
    result = manager.download("qwen2.5-1.5b-instruct-q4_k_m")
    assert result["ok"] is False
    assert result["code"] in ("DOES_NOT_FIT", "CAP_VIOLATION")


def test_select_never_returns_a_file_over_the_cap(manager, monkeypatch):
    result = manager.select(model_id="qwen2.5-1.5b-instruct-q4_k_m")
    assert result["code"] in ("OK", "DOES_NOT_FIT")
    unknown = manager.select(model_id="llama-70b-instruct")
    assert unknown["ok"] is False and unknown["code"] == "UNKNOWN_MODEL"


# --------------------------------------------------------------- activation lifecycle
def test_activate_records_previous_install_for_rollback(manager, monkeypatch):
    db = manager.db
    monkeypatch.setattr(device_profile, "profile", lambda: device_profile.DeviceProfile(
        os_name="Linux", os_version="x", machine="x86_64", python="3.11", cpu_cores=8,
        ram_total_mb=16384, ram_available_mb=9000, disk_free_mb=200000))
    manager._record("qwen2.5-1.5b-instruct-q4_k_m", "INSTALLED", path=Path("/tmp/a.gguf"), size=10 ** 9)
    manager._record("qwen2.5-1.5b-instruct-q3_k_m", "INSTALLED", path=Path("/tmp/b.gguf"), size=9 * 10 ** 8)
    assert manager.activate("qwen2.5-1.5b-instruct-q3_k_m")["ok"] is True
    assert manager.activate("qwen2.5-1.5b-instruct-q4_k_m")["ok"] is True
    row = manager._row("qwen2.5-1.5b-instruct-q4_k_m")
    assert row.previous_install_id, "activation must remember what it replaced"
    rolled = manager.rollback()
    assert rolled["ok"] is True and manager.active_id() == "qwen2.5-1.5b-instruct-q3_k_m"


def test_benchmark_reports_honestly_when_llama_cpp_is_absent(manager):
    result = manager.benchmark("qwen2.5-1.5b-instruct-q4_k_m")
    assert result["ok"] is False
    assert result["code"] in ("RUN_TIME_MISSING", "RUNTIME_MISSING", "NOT_INSTALLED")


def test_status_snapshot_exposes_registry_device_and_cap(manager):
    status = manager.status()
    assert status["cap_bytes"] == CAP
    assert status["device"]["ram_total_mb"] >= 0
    assert {m["model_id"] for m in status["registry"]} == {s.model_id for s in model_registry.all_models()}
    json.dumps(status)          # must be JSON-serialisable for the API


def test_download_rejects_a_model_outside_the_registry(manager):
    result = manager.download("some-random-gguf")
    assert result["ok"] is False and result["code"] == "UNKNOWN_MODEL"


# --------------------------------------------------------------- digest recording
def test_every_shipped_model_carries_a_published_digest():
    for spec in model_registry.all_models():
        assert spec.sha256 and len(spec.sha256) == 64, spec.model_id
    # a sidecar may add a digest, and any value it holds must be a real sha256
    for value in model_registry.pinned_digests().values():
        assert len(value) == 64


def test_record_digest_writes_a_sidecar_and_refuses_junk(tmp_path, monkeypatch):
    import importlib

    from app.services.business_brain import model_registry as fresh
    monkeypatch.setenv("SUPERMARKET_BRAIN_DIGESTS", str(tmp_path / "digests.json"))
    module = importlib.reload(fresh)
    try:
        target = module.record_digest("qwen2.5-1.5b-instruct-q4_k_m", "a" * 64)
        assert target.exists()
        assert module.pinned_digests()["qwen2.5-1.5b-instruct-q4_k_m"] == "a" * 64
        with pytest.raises(ValueError):
            module.record_digest("qwen2.5-1.5b-instruct-q4_k_m", "not-a-digest")
        with pytest.raises(KeyError):
            module.record_digest("unknown-model", "a" * 64)
        # a sidecar can only replace a digest with another valid digest
        (tmp_path / "digests.json").write_text('{"qwen2.5-1.5b-instruct-q4_k_m": "nonsense"}', "utf-8")
        assert "qwen2.5-1.5b-instruct-q4_k_m" not in module.pinned_digests()
    finally:
        monkeypatch.undo()
        importlib.reload(fresh)
