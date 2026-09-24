#!/usr/bin/env python3
"""Prepare the local AI model payload for the Windows installer — v4.0.

The owner asked for a Windows installer that ships the model *inside* it, so a
shop PC has a working local Business Brain on first launch with no download.
This script builds that payload honestly:

    python scripts/model/prepare_windows_installer.py                 # default model
    python scripts/model/prepare_windows_installer.py --model qwen2.5-1.5b-instruct-q3_k_m
    python scripts/model/prepare_windows_installer.py --from-file /path/model.gguf
    python scripts/model/prepare_windows_installer.py --engine        # also bundle llama.cpp

What it does
------------
1. downloads the model from its **official** sources (Hugging Face first, then
   the official ModelScope fallback — or adopts ``--from-file``), through the
   v4.0.1 download manager: progress bar, parallel connections, resume after
   an interruption, and Internet Download Manager on Windows when installed
   (``--downloader auto`` is the default; ``builtin`` forces the built-in
   engine, ``idm`` forces IDM);
2. verifies sha256 against the Model Registry — a mismatch deletes the file and
   fails the build (an unverified model must never enter an installer);
3. writes it to ``installer/windows/model/<model_id>/<file>.gguf`` together with
   a ``seed.json`` manifest;
4. generates ``installer/windows/model_payload.iss`` — the Inno Setup fragment
   that installs the payload into ``%USERPROFILE%\\SupermarketSystem\\brain\\models``
   (the app's data dir; the backend adopts it on first launch);
5. with ``--engine``, fetches the official llama.cpp Windows build into
   ``installer/windows/runtime/`` so the brain can run fully offline.

An interrupted download keeps its partial file (``*.part.dl`` + control state):
run the script again and it resumes from where it stopped instead of
re-fetching ~1 GB.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.services.business_brain import download_manager, model_registry  # noqa: E402
from app.services.business_brain.download_manager import force_utf8_stdio  # noqa: E402

INSTALLER = ROOT / "installer" / "windows"
#: llama.cpp official Windows CPU build (release tag → asset name pattern)
LLAMA_TAG = "b6283"
LLAMA_ASSET = f"llama-{LLAMA_TAG}-bin-win-cpu-x64.zip"
LLAMA_URL = f"https://github.com/ggml-org/llama.cpp/releases/download/{LLAMA_TAG}/{LLAMA_ASSET}"


def sha256_file(path: Path, chunk: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            block = fh.read(chunk)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def prepare_model(model_id: str | None, from_file: str | None, out: Path,
                  downloader: str = "auto", connections: int = 4) -> int:
    spec = model_registry.get(model_id) if model_id else model_registry.default_model()
    if spec is None:
        print(f"unknown model: {model_id}", file=sys.stderr)
        return 2
    if not model_registry.allowed_source(spec.source_url, spec):
        print(f"REFUSED: {spec.source_url} is not an allowed official source", file=sys.stderr)
        return 1
    if not spec.within_cap():
        print(f"REFUSED: {spec.model_id} is over the 2 GB cap", file=sys.stderr)
        return 1

    target_dir = out / "model" / spec.model_id
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / spec.file_name

    if from_file:
        source = Path(from_file)
        if not source.exists():
            print(f"file not found: {source}", file=sys.stderr)
            return 2
        shutil.copyfile(source, target)
        print(f"adopted {source} ({target.stat().st_size:,} bytes)")
    elif target.exists() and sha256_file(target) == spec.sha256:
        print(f"already prepared: {target}")
    else:
        sources = model_registry.source_urls(spec)
        print(f"downloading {spec.model_id} — {spec.file_size_bytes / (1024 * 1024):,.0f} MB "
              f"from the official repositories ({len(sources)} source(s))")
        target.unlink(missing_ok=True)
        partial = target_dir / (spec.file_name + ".part")
        try:
            download_manager.fetch(sources, partial,
                                   expected_size=spec.file_size_bytes,
                                   expected_sha256=spec.sha256,
                                   downloader=downloader, connections=connections)
        except download_manager.DownloadError as exc:
            resumable = Path(str(partial) + ".dl").exists()
            print(f"DOWNLOAD FAILED: {exc}", file=sys.stderr)
            if resumable:
                print("the partial download was kept — run this script again and it "
                      "resumes from where it stopped", file=sys.stderr)
            else:
                print("check the internet connection and try again, or download the "
                      "GGUF manually and pass --from-file", file=sys.stderr)
            return 1
        except KeyboardInterrupt:
            print("\ninterrupted — the partial download is kept; run again to resume",
                  file=sys.stderr)
            return 130
        digest = sha256_file(partial)
        if digest != spec.sha256:
            print(f"CHECKSUM MISMATCH: expected {spec.sha256}, got {digest} — "
                  "the file is deleted and the build fails", file=sys.stderr)
            partial.unlink(missing_ok=True)
            return 1
        partial.replace(target)
        print(f"verified sha256 {spec.sha256}")

    digest = sha256_file(target)
    if digest != spec.sha256:
        print("the file changed during preparation — refusing", file=sys.stderr)
        target.unlink(missing_ok=True)
        return 1

    manifest = {
        "model_id": spec.model_id,
        "file": spec.file_name,
        "sha256": digest,
        "size_bytes": target.stat().st_size,
        "source_url": spec.source_url,
        "source": "installer",
        "prepared_at": datetime.now(timezone.utc).isoformat(),
        "prepared_by": "scripts/model/prepare_windows_installer.py",
    }
    (target_dir / "seed.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2),
                                          encoding="utf-8")
    print(f"seed.json written → {target_dir / 'seed.json'}")
    return 0


def _engine_files(runtime_dir: Path) -> list[Path]:
    return sorted(p for p in runtime_dir.iterdir() if p.suffix.lower() in (".exe", ".dll"))


def _engine_is_complete(runtime_dir: Path, marker: Path) -> bool:
    """v4.3.3 — an engine is complete only when the marker says so AND every
    import of every PE file resolves (bundled or a Windows system DLL).

    The v4.2-era marker shipped llama-server.exe WITHOUT its DLLs (llama.dll,
    ggml-base.dll, libcurl-x64.dll…) — the shop PC then failed with
    «llama.dll was not found». Old markers without "complete" force a re-fetch.
    """
    try:
        manifest = json.loads(marker.read_text(encoding="utf-8"))
        if manifest.get("complete") is not True:
            return False
        for entry in manifest.get("files", []):
            f = runtime_dir / entry["name"]
            if not f.exists() or f.stat().st_size != entry.get("bytes", -1):
                return False
    except (OSError, ValueError):
        return False
    sys.path.insert(0, str(Path(__file__).resolve().parent))   # sibling import
    import verify_engine  # noqa: PLC0415 — sibling module (scripts/model)
    ok, _problems, _report = verify_engine.verify(runtime_dir)
    return ok


def prepare_engine(out: Path, downloader: str = "auto", connections: int = 4) -> int:
    """Bundle the official llama.cpp Windows build next to the model.

    v4.3.3: the official build is DYNAMIC — llama-server.exe imports
    llama.dll, ggml-base.dll, ggml-cpu.dll, libcurl-x64.dll… — so we extract
    the exe AND every DLL from the official archive, then VERIFY the whole
    import graph (pure-stdlib PE parser). A half engine must never ship: the
    brain's autostart would pop DLL error dialogs on every launch.

    Optional but recommended: without an engine the adopted model stays
    INSTALLED and the brain answers deterministically (and says so).
    """
    runtime_dir = out / "runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    marker = runtime_dir / "engine.json"
    if marker.exists() and _engine_is_complete(runtime_dir, marker):
        print(f"engine already prepared and verified: {marker}")
        return 0
    if marker.exists():
        print("ENGINE INCOMPLETE (older build shipped llama-server.exe without its "
              "DLLs) — re-fetching the official archive…", file=sys.stderr)
    for stale in runtime_dir.iterdir():        # never build on a half payload
        if stale.is_file():
            stale.unlink(missing_ok=True)

    archive = runtime_dir / LLAMA_ASSET
    print(f"downloading llama.cpp {LLAMA_TAG} (official GitHub release)…")
    try:
        download_manager.fetch((LLAMA_URL,), archive,
                               downloader=downloader, connections=connections)
    except Exception as exc:  # noqa: BLE001 — an offline build can still ship the model
        archive.unlink(missing_ok=True)        # never leave a partial zip to be packed
        print(f"WARNING: engine fetch failed ({exc}); the installer will ship WITHOUT "
              "the engine — the brain will say so honestly on first launch")
        return 0
    try:
        digest = sha256_file(archive)
        extracted: list[Path] = []
        with zipfile.ZipFile(archive) as zf:
            for name in zf.namelist():
                base = Path(name).name
                # v4.3.3 — the exe AND every DLL it (or they) import
                if base == "llama-server.exe" or base.lower().endswith(".dll"):
                    destination = runtime_dir / base
                    with zf.open(name) as src, open(destination, "wb") as dst:
                        shutil.copyfileobj(src, dst)
                    extracted.append(destination)
        if not any(f.name == "llama-server.exe" for f in extracted):
            print(f"WARNING: {LLAMA_ASSET} contained no llama-server.exe; engine skipped",
                  file=sys.stderr)
            return 0
        # the actual import graph is the ONLY truth about prerequisites
        sys.path.insert(0, str(Path(__file__).resolve().parent))   # sibling import
        import verify_engine  # noqa: PLC0415 — sibling module (scripts/model)
        ok, problems, report = verify_engine.verify(runtime_dir)
        if not ok:
            for problem in problems:
                print(f"FAIL: {problem}", file=sys.stderr)
            print("موتور رسمی بعد از استخراج ناقص است — نصب‌کنندهٔ بدون موتورِ خراب ساخته "
                  "نمی‌شود؛ دوباره بیلد بگیرید (دانلود از همان‌جا ادامه می‌یابد).", file=sys.stderr)
            return 1
        files = [{"name": f.name, "bytes": f.stat().st_size, "sha256": sha256_file(f)}
                 for f in sorted(extracted)]
        marker.write_text(json.dumps({"tag": LLAMA_TAG, "asset": LLAMA_ASSET,
                                      "sha256": digest,
                                      "complete": True,
                                      "files": files,
                                      "source_url": LLAMA_URL,
                                      "prepared_at": datetime.now(timezone.utc).isoformat()},
                                     ensure_ascii=False, indent=2), encoding="utf-8")
        checked = sum(len(info["imports"]) for info in report["files"].values())
        print(f"engine ready → {runtime_dir} ({len(files)} فایل، "
              f"{checked} وابستگی DLL بررسی و تأیید شد)")
    except Exception as exc:  # noqa: BLE001 — a bad engine payload must not kill the build
        print(f"WARNING: engine payload failed ({exc}); the installer will ship WITHOUT "
              "the engine — the brain will say so honestly on first launch", file=sys.stderr)
        return 0
    finally:
        archive.unlink(missing_ok=True)          # the marker is the record, not the zip
    return 0


def write_iss_include(out: Path) -> int:
    """Generate the Inno [Files] fragment for whatever payload exists.

    The model goes to the app's DATA dir (``%USERPROFILE%\\SupermarketSystem``),
    not {app}: reinstalling/updating the program must never wipe the 1 GB model,
    and the backend looks for it there (SUPERMARKET_DATA_DIR).
    """
    lines = [
        "; AUTO-GENERATED by scripts/model/prepare_windows_installer.py — do not edit.",
        "; Installs the verified local AI model (and engine) into the user's data",
        "; directory so the Business Brain works on first launch, fully offline.",
        "; The app re-verifies sha256 at runtime and refuses anything it cannot trust.",
    ]
    out.mkdir(parents=True, exist_ok=True)
    model_root = out / "model"
    shipped = 0
    if model_root.exists():
        for manifest_path in sorted(model_root.glob("*/seed.json")):
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except ValueError:
                continue
            model_id = manifest["model_id"]
            file_name = manifest["file"]
            if not (manifest_path.parent / file_name).exists():
                continue
            lines.append(
                f'Source: "model\\{model_id}\\{file_name}"; '
                f'DestDir: "{{%USERPROFILE}}\\SupermarketSystem\\brain\\models\\{model_id}"; '
                f'Flags: ignoreversion uninsneveruninstall')
            lines.append(
                f'Source: "model\\{model_id}\\seed.json"; '
                f'DestDir: "{{%USERPROFILE}}\\SupermarketSystem\\brain\\models\\{model_id}"; '
                f'Flags: ignoreversion uninsneveruninstall skipifsourcedoesntexist')
            shipped += 1
    runtime = out / "runtime"
    if runtime.exists() and any(runtime.glob("*.exe")):
        lines.append('Source: "runtime\\*"; DestDir: "{%USERPROFILE}\\SupermarketSystem\\brain\\runtime"; '
                     'Flags: ignoreversion uninsneveruninstall skipifsourcedoesntexist')
    (out / "model_payload.iss").write_text("\r\n".join(lines) + "\r\n", encoding="utf-8")
    print(f"model_payload.iss written ({shipped} model(s), "
          f"engine={'yes' if runtime.exists() and any(runtime.glob('*.exe')) else 'no'}) → "
          f"{out / 'model_payload.iss'}")
    return shipped


def main(argv: list[str] | None = None) -> int:
    force_utf8_stdio()          # redirected Windows consoles must never crash on output
    parser = argparse.ArgumentParser(description="Windows installer model payload (v4.0)")
    parser.add_argument("--model", help="registry model id (default: the registry default)")
    parser.add_argument("--from-file", metavar="PATH",
                        help="adopt a locally downloaded .gguf instead of downloading")
    parser.add_argument("--engine", action="store_true",
                        help="also bundle the official llama.cpp Windows build")
    parser.add_argument("--out", default=str(INSTALLER), help="installer/windows directory")
    parser.add_argument("--skip-model", action="store_true",
                        help="only regenerate model_payload.iss (no payload checks)")
    parser.add_argument("--downloader", choices=("auto", "builtin", "idm"), default="auto",
                        help="download engine: auto = Internet Download Manager when "
                             "installed, else the built-in manager (progress bar, "
                             "parallel connections, resume); builtin = always built-in; "
                             "idm = require IDM")
    parser.add_argument("--connections", type=int, default=4,
                        help="parallel connections for the built-in downloader (1-16)")
    args = parser.parse_args(argv)
    out = Path(args.out)
    connections = max(1, min(16, args.connections))

    if not args.skip_model:
        code = prepare_model(args.model, args.from_file, out,
                             downloader=args.downloader, connections=connections)
        if code:
            return code
    if args.engine:
        code = prepare_engine(out, downloader=args.downloader, connections=connections)
        if code:
            return code
    shipped = write_iss_include(out)
    if not args.skip_model and shipped == 0:
        print("no verified model payload was written — refusing to continue",
              file=sys.stderr)
        return 1
    print("\nnext: the installer build (ISCC) picks this up automatically via "
          "#include \"model_payload.iss\" in setup.iss")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
