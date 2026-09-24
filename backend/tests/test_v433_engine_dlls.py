"""v4.3.3 — Windows engine DLL prerequisites, locked down as tests.

Owner round 11: the shop PC showed «llama.dll was not found»,
«ggml-base.dll was not found», «libcurl-x64.dll was not found» at launch.

Root cause: the official llama.cpp Windows build is a DYNAMIC build and
``prepare_engine`` extracted exactly ONE file (llama-server.exe) from the
official archive — its DLLs were thrown away. The fix: extract the exe AND
every DLL, then verify the ACTUAL PE import graph (pure-stdlib parser), and
never ship a half engine. Android needs nothing: its engines are static ELFs
(test-pinned since 4.1.0).
"""
from __future__ import annotations

import json
import struct
import sys
import types
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "scripts" / "model"))

ANDROID = ROOT / "mobile-android" / "app" / "src" / "main"


# ---------------------------------------------------------------- PE helpers
def make_pe(path: Path, imports: tuple[str, ...] = ("kernel32.dll",)) -> Path:
    """A minimal-but-parseable PE32+ with exactly the given import names."""
    sec_rva, raw_ptr = 0x1000, 0x400
    n = len(imports)
    # layout inside the section: descriptors (n+1)*20, then name strings
    names = b"".join(name.encode() + b"\x00" for name in imports)
    sec_size = (n + 1) * 20 + len(names)
    sec = bytearray(sec_size)
    off = 0
    name_rva = sec_rva + (n + 1) * 20
    for i, name in enumerate(imports):
        struct.pack_into("<IIIII", sec, off, sec_rva + sec_size + 8, 0, 0,
                         name_rva, 0)                      # OFT/TS/FC/Name/IAT
        off += 20
        name_rva += len(name.encode()) + 1
    # names start AFTER the (n+1) descriptors — the all-zero terminator at
    # n*20..(n+1)*20 must stay zero or the parser walks into the strings
    sec[(n + 1) * 20:(n + 1) * 20 + len(names)] = names

    opt_size = 112 + 16 * 8                                 # PE32+ + 16 data dirs
    dos = bytearray(0x40)
    dos[:2] = b"MZ"
    struct.pack_into("<I", dos, 0x3C, 0x40)
    coff = struct.pack("<HHIIIHH", 0x8664, 1, 0, 0, 0, opt_size, 0x22)
    opt = bytearray(opt_size)
    struct.pack_into("<H", opt, 0, 0x20B)                   # PE32+ magic
    # data directory 1 (imports) → sec_rva
    struct.pack_into("<II", opt, 112 + 8, sec_rva, (n + 1) * 20)
    sectab = struct.pack("<8sIIIIIIHHI", b".text\0\0\0", sec_size, sec_rva,
                         sec_size, raw_ptr, 0, 0, 0, 0, 0x60000020)
    out = bytes(dos) + b"PE\x00\x00" + coff + bytes(opt) + sectab
    out = out.ljust(raw_ptr, b"\x00") + bytes(sec)
    path.write_bytes(out)
    return path


def runtime_with(tmp_path: Path, dlls: tuple[str, ...], where: Path | None = None) -> Path:
    rt = where or (tmp_path / "runtime")
    rt.mkdir(parents=True, exist_ok=True)
    make_pe(rt / "llama-server.exe", ("kernel32.dll", "ws2_32.dll") + dlls)
    if "llama.dll" in dlls:
        make_pe(rt / "llama.dll", ("ggml-base.dll",))
    if "ggml-base.dll" in dlls:
        make_pe(rt / "ggml-base.dll", ("kernel32.dll",))
    if "libcurl-x64.dll" in dlls:
        make_pe(rt / "libcurl-x64.dll", ("ws2_32.dll", "kernel32.dll"))
    if "ggml-cpu.dll" in dlls:
        make_pe(rt / "ggml-cpu.dll", ("ggml-base.dll",))
    return rt


# ---------------------------------------------------------------- the parser
def test_import_table_reads_the_real_dependencies():
    import verify_engine
    pe = Path("/tmp/_t/engine.exe")
    pe.parent.mkdir(parents=True, exist_ok=True)
    make_pe(pe, ("kernel32.dll", "llama.dll", "ggml-base.dll"))
    assert verify_engine.import_table(pe) == {"kernel32.dll", "llama.dll", "ggml-base.dll"}


def test_verify_engine_passes_when_every_dll_is_bundled(tmp_path):
    import verify_engine
    rt = runtime_with(tmp_path, ("llama.dll", "ggml-base.dll", "libcurl-x64.dll"))
    ok, problems, report = verify_engine.verify(rt)
    assert ok, problems
    assert report["files"]["llama-server.exe"]["imports"]["llama.dll"] == "bundled"
    assert report["files"]["llama-server.exe"]["imports"]["kernel32.dll"] == "system"


def test_verify_engine_recurses_into_bundled_dlls(tmp_path):
    """llama.dll imports ggml-base.dll — removing it must be caught through
    the recursion, not just from the exe's own table."""
    import verify_engine
    rt = runtime_with(tmp_path, ("llama.dll", "ggml-base.dll", "libcurl-x64.dll"))
    (rt / "ggml-base.dll").unlink()
    ok, problems, _ = verify_engine.verify(rt)
    assert not ok
    assert any("ggml-base.dll" in p for p in problems)


def test_verify_engine_cli(tmp_path, capsys):
    import verify_engine
    rt = runtime_with(tmp_path, ("llama.dll", "ggml-base.dll"))
    assert verify_engine.main([str(rt)]) == 0
    assert "PASS" in capsys.readouterr().out


# ---------------------------------------------------------------- prepare_engine
def _fake_fetch(zip_files: dict[str, bytes]):
    calls = []

    def fetch(urls, dest, **kw):
        calls.append((urls, Path(dest)))
        with zipfile.ZipFile(dest, "w") as zf:
            for name, blob in zip_files.items():
                zf.writestr(name, blob)
    return types.SimpleNamespace(fetch=fetch, DownloadError=Exception), calls


def _pe_bytes(imports: tuple[str, ...]) -> bytes:
    import tempfile
    f = Path(tempfile.mkstemp(suffix=".bin")[1])
    make_pe(f, imports)
    return f.read_bytes()


def test_prepare_engine_extracts_exe_and_every_dll(tmp_path, monkeypatch):
    import prepare_windows_installer as piw
    blob = {
        "llama-server.exe": _pe_bytes(("kernel32.dll", "llama.dll", "ggml-base.dll", "libcurl-x64.dll")),
        "llama.dll": _pe_bytes(("ggml-base.dll",)),
        "ggml-base.dll": _pe_bytes(("kernel32.dll",)),
        "ggml-cpu.dll": _pe_bytes(("ggml-base.dll",)),
        "libcurl-x64.dll": _pe_bytes(("ws2_32.dll",)),
        "README.txt": b"not a binary - must NOT be extracted",
    }
    fake, calls = _fake_fetch(blob)
    monkeypatch.setattr(piw, "download_manager", fake)
    assert piw.prepare_engine(tmp_path) == 0
    rt = tmp_path / "runtime"
    names = {p.name for p in rt.iterdir()}
    assert "llama-server.exe" in names and "llama.dll" in names
    assert "ggml-base.dll" in names and "ggml-cpu.dll" in names and "libcurl-x64.dll" in names
    assert "README.txt" not in names                            # only exe + DLLs
    assert not (rt / piw.LLAMA_ASSET).exists()                  # zip never ships
    manifest = json.loads((rt / "engine.json").read_text(encoding="utf-8"))
    assert manifest["complete"] is True
    assert {f["name"] for f in manifest["files"]} == {
        "llama-server.exe", "llama.dll", "ggml-base.dll", "ggml-cpu.dll", "libcurl-x64.dll"}
    for entry in manifest["files"]:
        assert entry["bytes"] == (rt / entry["name"]).stat().st_size
        assert len(entry["sha256"]) == 64


def test_prepare_engine_redoes_an_incomplete_old_marker(tmp_path, monkeypatch):
    """The owner's machine has a v4.2-era engine.json (exe only). Re-running
    the build must DETECT it and re-fetch — not short-circuit."""
    import prepare_windows_installer as piw
    rt = tmp_path / "runtime"
    rt.mkdir(parents=True)
    make_pe(rt / "llama-server.exe", ("kernel32.dll",))        # old, incomplete
    (rt / "engine.json").write_text(json.dumps({"tag": piw.LLAMA_TAG}), encoding="utf-8")
    fake, calls = _fake_fetch({
        "llama-server.exe": _pe_bytes(("kernel32.dll", "llama.dll")),
        "llama.dll": _pe_bytes(("kernel32.dll",)),
    })
    monkeypatch.setattr(piw, "download_manager", fake)
    assert piw.prepare_engine(tmp_path) == 0
    assert len(calls) == 1                                      # it re-fetched
    assert (rt / "llama.dll").exists()
    assert json.loads((rt / "engine.json").read_text(encoding="utf-8"))["complete"] is True


def test_prepare_engine_fails_rather_than_shipping_a_half_engine(tmp_path, monkeypatch):
    """An archive whose exe needs DLLs that are NOT in it → exit 1 (the build
    must fail loudly; a half engine pops DLL dialogs on every launch)."""
    import prepare_windows_installer as piw
    fake, _ = _fake_fetch({"llama-server.exe": _pe_bytes(("kernel32.dll", "llama.dll"))})
    monkeypatch.setattr(piw, "download_manager", fake)
    assert piw.prepare_engine(tmp_path) == 1
    assert not (tmp_path / "runtime" / "engine.json").exists()  # no complete marker


def test_clean_engine_when_fetch_fails(tmp_path, monkeypatch):
    """No engine at all is an honest degradation — but a PARTIAL archive must
    never remain in runtime/ (Inno packs runtime\\* wholesale)."""
    import prepare_windows_installer as piw

    def boom(urls, dest, **kw):
        Path(dest).write_bytes(b"partial zip bytes")

    monkeypatch.setattr(piw, "download_manager",
                        types.SimpleNamespace(fetch=boom, DownloadError=Exception))
    # force the fetch to raise via DownloadError
    def raising(urls, dest, **kw):
        Path(dest).write_bytes(b"partial zip bytes")
        raise piw.download_manager.DownloadError("net down")
    monkeypatch.setattr(piw, "download_manager",
                        types.SimpleNamespace(fetch=raising, DownloadError=Exception))
    assert piw.prepare_engine(tmp_path) == 0                    # honest degradation
    assert not (tmp_path / "runtime" / piw.LLAMA_ASSET).exists()
    assert list((tmp_path / "runtime").iterdir()) == []         # nothing half-shipped


# ---------------------------------------------------------------- verify_setup cross-check
def _installer_dir_with_engine(tmp_path: Path) -> Path:
    ins = tmp_path / "installer" / "windows"
    mdl = ins / "model" / "test-model-q4"
    mdl.mkdir(parents=True)
    (mdl / "test-model-q4.gguf").write_bytes(b"\0" * 100_000_000)
    (mdl / "seed.json").write_text(json.dumps(
        {"model_id": "test-model-q4", "sha256": "a" * 64}), encoding="utf-8")
    rt = runtime_with(tmp_path, ("llama.dll", "ggml-base.dll", "libcurl-x64.dll"),
                      where=ins / "runtime")
    (ins / "model_payload.iss").write_text(
        '[Files]\nSource: "model\\test-model-q4\\test-model-q4.gguf"; DestDir: "x"\n'
        'Source: "runtime\\*"; DestDir: "y"\n', encoding="utf-8")
    return ins


def _setup_exe(tmp_path: Path, mb: float) -> Path:
    setup = tmp_path / "Setup.exe"
    blob = b"MZ" + b"x" * 700_000
    sig = (b"Inno Setup Setup Data (6.7.0)" + b"\x00" * 64)[:64]
    blob += sig + b"z" * max(0, int(mb * 1e6) - len(blob) - 64)
    setup.write_bytes(blob)
    return setup


def test_verify_setup_accepts_a_complete_engine(tmp_path):
    from scripts.model import verify_setup as vs
    import importlib
    ins = _installer_dir_with_engine(tmp_path)
    # engine.json lives inside runtime/
    (ins / "runtime" / "engine.json").write_text(
        json.dumps({"complete": True, "files": []}), encoding="utf-8")
    setup = _setup_exe(tmp_path, 103.0)
    ok, problems, _info, code = importlib.reload(vs).verify(setup, ins)
    assert ok, problems


def test_verify_setup_rejects_a_half_engine(tmp_path):
    import importlib
    from scripts.model import verify_setup as vs
    ins = _installer_dir_with_engine(tmp_path)
    (ins / "runtime" / "libcurl-x64.dll").unlink()              # the owner's bug
    (ins / "runtime" / "engine.json").write_text(
        json.dumps({"complete": True, "files": []}), encoding="utf-8")
    setup = _setup_exe(tmp_path, 103.0)
    ok, problems, _info, code = importlib.reload(vs).verify(setup, ins)
    assert not ok and code == 1
    assert any("libcurl-x64.dll" in p for p in problems)


# ---------------------------------------------------------------- Android needs nothing
def test_android_engine_has_no_dll_style_prerequisites():
    """The owner asked to make sure Android has no such prerequisite problem:
    both shipped engines are STATIC ELFs — no PT_INTERP (no loader) and no
    PT_DYNAMIC (no shared-library imports at all). Windows-style DLL errors
    are impossible on this side by construction."""
    for abi, machine in (("arm64-v8a", 183), ("armeabi-v7a", 40)):
        data = (ANDROID / "jniLibs" / abi / "libllamaserver.so").read_bytes()
        assert data[:4] == b"\x7fELF"
        is64 = data[4] == 2
        e_machine = int.from_bytes(data[18:20], "little")
        assert e_machine == machine, f"{abi}: wrong machine {e_machine}"
        phoff = int.from_bytes(data[0x20:0x28] if is64 else data[0x1C:0x20], "little")
        phentsize = int.from_bytes(data[0x36:0x38] if is64 else data[0x2A:0x2C], "little")
        phnum = int.from_bytes(data[0x3C:0x3E] if is64 else data[0x2C:0x2E], "little")
        types = {int.from_bytes(data[phoff + i * phentsize: phoff + i * phentsize + 4], "little")
                 for i in range(phnum)}
        assert 3 not in types, f"{abi}: PT_INTERP — needs a loader"
        assert 2 not in types, f"{abi}: PT_DYNAMIC — has shared-library imports"


# ---------------------------------------------------------------- versions
def test_versions_consistent():
    from app import __version__
    assert __version__ == "4.3.3"
    iss = (ROOT / "installer" / "windows" / "setup.iss").read_text(encoding="utf-8-sig")
    assert '#define MyAppVersion "4.3.3"' in iss
