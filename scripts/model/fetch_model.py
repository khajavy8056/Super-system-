#!/usr/bin/env python3
"""Fetch (and verify) a Business Brain model — v4.0 §36/§37.

The model file never ships inside the repository: this script downloads it from
the **official** Qwen GGUF repository recorded in the Model Registry, verifies it
against the published sha256, and only then puts it in the models directory the
Model Manager reads. A mismatch deletes the file and refuses to continue.

Typical use on a shop PC (Windows or Linux):

    python scripts/model/fetch_model.py --list
    python scripts/model/fetch_model.py                 # the model this device should run
    python scripts/model/fetch_model.py --model qwen2.5-1.5b-instruct-q3_k_m
    python scripts/model/fetch_model.py --verify <path-to-gguf>
    python scripts/model/fetch_model.py --record        # pin the verified digest for this build

``--record`` writes the digest the download actually produced into
``app/services/business_brain/model_digests.json``. That sidecar can only ever
*replace* a digest with another 64-hex value — it can never remove the
requirement to verify, and it never turns an unverified file into a trusted one.

Nothing here is required for the brain to work: without a model the product runs
in deterministic mode and says so.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.database import SessionLocal, init_db  # noqa: E402
from app.services.business_brain import device_profile, model_registry  # noqa: E402
from app.services.business_brain.model_manager import ModelManager, sha256_file  # noqa: E402


def _mb(value: int) -> str:
    return f"{value / (1024 * 1024):,.0f} MB"


def cmd_list() -> int:
    prof = device_profile.profile()
    print(f"device: {device_profile.summary_line(prof)}")
    print(f"recommended: {device_profile.choose_model(prof).model_id}  "
          f"(context {device_profile.context_for(prof)})")
    print(f"size cap: {_mb(model_registry.MAX_FILE_BYTES)} per file\n")
    for spec in model_registry.all_models():
        fits = model_registry.fits(spec, ram_mb=prof.ram_total_mb, disk_free_mb=prof.disk_free_mb)
        print(f"- {spec.model_id}  [{spec.tier}]  {_mb(spec.file_size_bytes)}")
        print(f"    {spec.family} {spec.parameters} · {spec.quantization} · ctx {spec.context_default}"
              f" · min RAM {spec.min_ram_mb} MB · {'fits' if fits else 'DOES NOT FIT this device'}")
        print(f"    sha256 {spec.sha256}")
        print(f"    {spec.source_url}")
    if model_registry.FORBIDDEN:
        print("\nrefused on purpose:")
        for item in model_registry.FORBIDDEN:
            print(f"- {item['model_id']}: {item['reason']}")
    problems = model_registry.validate_registry()
    if problems:
        print("\nREGISTRY PROBLEMS:")
        for problem in problems:
            print(f"- {problem}")
        return 1
    return 0


def cmd_fetch(model_id: str | None, record: bool, force: bool) -> int:
    init_db()
    db = SessionLocal()
    try:
        manager = ModelManager(db)
        spec = model_registry.get(model_id) if model_id else device_profile.choose_model()
        if spec is None:
            print(f"unknown model: {model_id}", file=sys.stderr)
            return 2
        print(f"fetching {spec.model_id} ({_mb(spec.file_size_bytes)}) …")

        def progress(done: int, total: int) -> None:
            total = total or spec.file_size_bytes
            print(f"\r  {done / (1024 * 1024):,.0f} / {total / (1024 * 1024):,.0f} MB", end="",
                  flush=True)

        result = manager.download(spec.model_id, progress=progress, force=force)
        print()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if not result.get("ok"):
            return 1
        if record:
            path = Path(result["path"])
            digest = sha256_file(path)
            if digest != result["sha256"]:
                print("the file changed since verification — refusing to record", file=sys.stderr)
                return 1
            target = model_registry.record_digest(spec.model_id, digest)
            print(f"recorded {digest} for {spec.model_id} → {target}")
        print("next: install and activate it from the admin UI "
              "(POST /api/brain/model/download then /api/brain/model/benchmark)")
        return 0
    finally:
        db.close()


def cmd_verify(path: str, model_id: str | None) -> int:
    target = Path(path)
    if not target.exists():
        print(f"file not found: {target}", file=sys.stderr)
        return 2
    digest = sha256_file(target)
    size = target.stat().st_size
    print(f"{target}\n  size   {size:,} bytes ({_mb(size)})\n  sha256 {digest}")
    if size > model_registry.MAX_FILE_BYTES:
        print("REFUSED: file is larger than the 2 GB cap", file=sys.stderr)
        return 1
    spec = model_registry.get(model_id) if model_id else None
    if spec is None and model_id is None:
        spec = next((s for s in model_registry.all_models() if s.file_name == target.name), None)
    if spec is None:
        print("no registry entry matches this file name; pass --model", file=sys.stderr)
        return 1
    if spec.sha256 and digest != spec.sha256:
        print(f"MISMATCH: registry expects {spec.sha256}", file=sys.stderr)
        return 1
    print(f"verified against the registry entry {spec.model_id}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Business Brain model fetcher (v4.0)")
    parser.add_argument("--model", help="registry model id (default: the one this device should run)")
    parser.add_argument("--record", action="store_true",
                        help="pin the verified sha256 into model_digests.json")
    parser.add_argument("--verify", metavar="PATH", help="hash a local .gguf against the registry")
    parser.add_argument("--force", action="store_true",
                        help="re-download even if a verified copy already exists")
    parser.add_argument("--list", action="store_true", help="show the registry and device fit")
    args = parser.parse_args(argv)

    if args.list:
        return cmd_list()
    if args.verify:
        return cmd_verify(args.verify, args.model)
    return cmd_fetch(args.model, args.record, args.force)


if __name__ == "__main__":
    raise SystemExit(main())
