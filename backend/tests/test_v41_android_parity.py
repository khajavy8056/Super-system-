# -*- coding: utf-8 -*-
"""v4.1 — Android/PC parity: ONE system, ONE model — enforced, not promised.

The owner's rule (2026-09-23): when the phone is paired with the PC they are a
single system — the models must be the same file, not a PC brain and a separate
Android brain; only in standalone mode is the phone fully independent, and even
then it runs the SAME model through the SAME engine.

This test file mechanically locks that parity:
  1. every model pin in BrainModel.java (id, file, urls, sha256, size, min RAM)
     must equal the backend Model Registry — byte for byte;
  2. the on-device engine tag in BrainEngine.java must equal the tag the Windows
     installer bundles (same llama.cpp version everywhere);
  3. the engine binary shipped in the repo must be a static aarch64 ELF
     (a dynamic binary would simply not run on Android);
  4. the APK must actually package the engine and request native-lib extraction;
  5. the local-mode system prompt must keep the product's core rules
     (no invented numbers, the وضعیت/دلیل/پیشنهاد/اقدام بعدی shape) and must
     say honestly that standalone mode has no live shop data.
"""
from __future__ import annotations

import re
import struct
from pathlib import Path

from app.services.business_brain import model_registry

REPO = Path(__file__).resolve().parents[2]
JAVA = REPO / "mobile-android" / "app" / "src" / "main" / "java" / "ir" / "khajavy" / "supermarket"
ENGINE_SO = (REPO / "mobile-android" / "app" / "src" / "main" / "jniLibs" /
             "arm64-v8a" / "libllamaserver.so")

SPEC_RE = re.compile(
    r'new Spec\("([^"]+)",\s*"([^"]+)",\s*"([^"]+)",\s*"([^"]+)",\s*"([0-9a-f]{64})",\s*(\d+)L,\s*(\d+)\)',
    re.S)


def _java_specs() -> dict[str, dict]:
    text = (JAVA / "BrainModel.java").read_text(encoding="utf-8")
    block = re.search(r"MODELS\s*=\s*\{(.*?)\n\s*\};", text, re.S)
    assert block, "BrainModel.MODELS not found"
    specs = {}
    for model_id, file, url, alt_url, sha, size, ram in SPEC_RE.findall(block.group(1)):
        specs[model_id] = {"file": file, "url": url, "alt_url": alt_url,
                           "sha256": sha, "bytes": int(size), "min_ram_mb": int(ram)}
    return specs


# --------------------------------------------------------------------- models
def test_android_pins_exactly_the_registry():
    java = _java_specs()
    registry = model_registry.all_models()
    assert java, "BrainModel.MODELS is empty"
    assert set(java) == {s.model_id for s in registry}, \
        f"Android model ids diverged from the registry: {set(java) ^ {s.model_id for s in registry}}"
    for spec in registry:
        pin = java[spec.model_id]
        assert pin["file"] == spec.file_name
        assert pin["url"] == spec.source_url, f"{spec.model_id}: primary source diverged"
        assert pin["alt_url"] == spec.alt_source_urls[0], \
            f"{spec.model_id}: official fallback source diverged"
        assert pin["sha256"] == spec.sha256, f"{spec.model_id}: sha256 pin diverged — TWO models!"
        assert pin["bytes"] == spec.file_size_bytes
        assert pin["min_ram_mb"] == spec.min_ram_mb
    assert model_registry.validate_registry() == []


def test_android_downloads_only_from_official_sources():
    for pin in _java_specs().values():
        for url in (pin["url"], pin["alt_url"]):
            assert url.startswith("https://")
            host = url.split("//", 1)[-1].split("/", 1)[0]
            assert host in ("huggingface.co", "modelscope.cn"), \
                f"unofficial source in the Android app: {host}"


def test_android_recommends_the_low_ram_tier():
    text = (JAVA / "BrainModel.java").read_text(encoding="utf-8")
    low = model_registry.by_tier("low-ram")
    assert low is not None
    assert f"recommended() {{ return MODELS[1]; }}" in text
    ids = list(_java_specs())
    assert ids[1] == low.model_id, "the phone must recommend the light tier first"


# --------------------------------------------------------------------- engine
def test_engine_tag_matches_the_windows_installer():
    java = (JAVA / "BrainEngine.java").read_text(encoding="utf-8")
    prep = (REPO / "scripts" / "model" / "prepare_windows_installer.py").read_text(encoding="utf-8")
    java_tag = re.search(r'ENGINE_TAG\s*=\s*"([^"]+)"', java).group(1)
    win_tag = re.search(r'LLAMA_TAG\s*=\s*"([^"]+)"', prep).group(1)
    assert java_tag == win_tag, \
        f"engine versions diverged: phone runs llama.cpp {java_tag}, Windows ships {win_tag}"


def test_engine_binary_is_a_static_aarch64_elf():
    assert ENGINE_SO.exists(), (
        "libllamaserver.so is missing — run scripts/android/build-engine.sh; the APK "
        "must ship the on-device engine (owner request 2026-09-23)")
    data = ENGINE_SO.read_bytes()
    assert data[:4] == b"\x7fELF" and data[4] == 2, "not a 64-bit ELF"
    assert struct.unpack("<H", data[18:20])[0] == 183, "not aarch64 — wrong ABI!"
    phoff = struct.unpack("<Q", data[0x20:0x28])[0]
    phentsize = struct.unpack("<H", data[0x36:0x38])[0]
    phnum = struct.unpack("<H", data[0x38:0x3a])[0]
    types = {struct.unpack("<I", data[phoff + i * phentsize: phoff + i * phentsize + 4])[0]
             for i in range(phnum)}
    assert 3 not in types, "PT_INTERP present — the binary is dynamic and will not run on Android"
    assert 2 not in types, "PT_DYNAMIC present — not a static binary"
    assert len(data) < 80 * 1024 * 1024, "engine binary is unexpectedly large"


def test_apk_actually_packages_the_engine():
    build = (REPO / "scripts" / "android" / "build-apk.sh").read_text(encoding="utf-8")
    assert "jniLibs" in build, "build-apk.sh must pack app/src/main/jniLibs into lib/<abi>/"
    assert 'lib/$ABI' in build, "the engine .so must land in lib/<abi>/ inside the APK"
    manifest = (REPO / "mobile-android" / "app" / "src" / "main" / "AndroidManifest.xml").read_text(
        encoding="utf-8")
    assert 'android:extractNativeLibs="true"' in manifest, \
        "without extractNativeLibs the engine is never extracted and can never run"


def test_local_mode_prompt_keeps_the_products_rules_and_honesty():
    java = (JAVA / "BrainEngine.java").read_text(encoding="utf-8")
    assert "قواعد قطعی" in java
    for section in ("وضعیت", "دلیل", "پیشنهاد", "اقدام بعدی"):
        assert section in java, f"the local prompt lost its {section} section"
    assert "هیچ عددی از خودت نساز" in java, "the no-invented-numbers rule is gone"
    assert "حالت محلی گوشی" in java and "دسترسی نداری" in java, \
        "the local mode must say honestly that it has no live shop data"
