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
1. downloads the model from its **official** source (or adopts ``--from-file``);
2. verifies sha256 against the Model Registry — a mismatch deletes the file and
   fails the build (an unverified model must never enter an installer);
3. writes it to ``installer/windows/model/<model_id>/<file>.gguf`` together with
   a ``seed.json`` manifest;
4. generates ``installer/windows/model_payload.iss`` — the Inno Setup fragment
   that installs the payload into ``%USERPROFILE%\\SupermarketSystem\\brain\\models``
   (the app's data dir; the backend adopts it on first launch);
5. with ``--engine``, fetches the official llama.cpp Windows build into
   ``installer/windows/runtime/`` so the brain can run fully offline.

Nothing here is required to *build* the installer without a model — but the
release pipeline calls this script and FAILS if the model cannot be verified, so
a shipped Setup.exe always contains a real, checksum-verified model.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import tempfile
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.services.business_brain import model_registry  # noqa: E402

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


def _download(url: str, dest: Path) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": "SupermarketBrain/4.0"})
    with urllib.request.urlopen(request, timeout=120) as response, open(dest, "wb") as fh:
        total = response.headers.get("Content-Length")
        total = int(total) if total and total.isdigit() else 0
        done = 0
        while True:
            block = response.read(1024 * 1024)
            if not block:
                break
            fh.write(block)
            done += len(block)
            if total:
                print(f"\r  {done / (1024 * 1024):,.0f} / {total / (1024 * 1024):,.0f} MB",
                      end="", flush=True)
    print()


def prepare_model(model_id: str | None, from_file: str | None, out: Path) -> int:
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
        print(f"downloading {spec.model_id} from the official repository…")
        target.unlink(missing_ok=True)
        with tempfile.NamedTemporaryFile(dir=target_dir, delete=False, suffix=".part") as tmp:
            partial = Path(tmp.name)
        try:
            _download(spec.source_url, partial)
            digest = sha256_file(partial)
            if digest != spec.sha256:
                print(f"CHECKSUM MISMATCH: expected {spec.sha256}, got {digest} — "
                      "the file is deleted and the build fails", file=sys.stderr)
                partial.unlink(missing_ok=True)
                return 1
            partial.replace(target)
        finally:
            partial.unlink(missing_ok=True)
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


def prepare_engine(out: Path) -> int:
    """Bundle the official llama.cpp Windows build next to the model.

    Optional but recommended: without an engine the adopted model stays
    INSTALLED and the brain answers deterministically (and says so).
    """
    runtime_dir = out / "runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    marker = runtime_dir / "engine.json"
    if marker.exists():
        print(f"engine already prepared: {marker}")
        return 0
    with tempfile.TemporaryDirectory() as tmp:
        archive = Path(tmp) / LLAMA_ASSET
        print(f"downloading llama.cpp {LLAMA_TAG} (official GitHub release)…")
        try:
            _download(LLAMA_URL, archive)
        except Exception as exc:  # noqa: BLE001 — an offline build can still ship the model
            print(f"WARNING: engine fetch failed ({exc}); the installer will ship WITHOUT "
                  "the engine — the brain will say so honestly on first launch")
            return 0
        digest = sha256_file(archive)
        wanted = ("llama-server.exe",)
        found: list[Path] = []
        with zipfile.ZipFile(archive) as zf:
            for name in zf.namelist():
                base = Path(name).name
                if base in wanted:
                    destination = runtime_dir / base
                    with zf.open(name) as src, open(destination, "wb") as dst:
                        shutil.copyfileobj(src, dst)
                    found.append(destination)
        if not found:
            print(f"WARNING: {LLAMA_ASSET} contained no llama-server.exe; engine skipped",
                  file=sys.stderr)
            return 0
        marker.write_text(json.dumps({"tag": LLAMA_TAG, "asset": LLAMA_ASSET,
                                      "sha256": digest,
                                      "files": [f.name for f in found],
                                      "source_url": LLAMA_URL,
                                      "prepared_at": datetime.now(timezone.utc).isoformat()},
                                     ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"engine ready → {runtime_dir}")
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
    parser = argparse.ArgumentParser(description="Windows installer model payload (v4.0)")
    parser.add_argument("--model", help="registry model id (default: the registry default)")
    parser.add_argument("--from-file", metavar="PATH",
                        help="adopt a locally downloaded .gguf instead of downloading")
    parser.add_argument("--engine", action="store_true",
                        help="also bundle the official llama.cpp Windows build")
    parser.add_argument("--out", default=str(INSTALLER), help="installer/windows directory")
    parser.add_argument("--skip-model", action="store_true",
                        help="only regenerate model_payload.iss (no payload checks)")
    args = parser.parse_args(argv)
    out = Path(args.out)

    if not args.skip_model:
        code = prepare_model(args.model, args.from_file, out)
        if code:
            return code
    if args.engine:
        code = prepare_engine(out)
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
