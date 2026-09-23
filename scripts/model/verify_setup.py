#!/usr/bin/env python3
"""v4.2 — verify that a built Windows Setup.exe REALLY contains the model.

Why this exists: the owner built the installer and got a 56 MB Setup.exe —
the ~1 GB model was not inside it. apksigner/aapt2-style "the build ran fine"
checks cannot see that; only the artifact can. This script reads the payload
the installer was supposed to embed (``installer/windows/model_payload.iss``
+ ``model/*/seed.json``) and checks the produced Setup.exe against it:

  1. model_payload.iss must exist and contain at least one model [Files] entry;
  2. the GGUF it references must exist on disk;
  3. the Setup.exe must be at least ``MIN_FACTOR`` × the GGUF size (Inno's LZMA
     compresses quantized weights by only a few percent, so 0.8× is a very safe
     floor — a missing model shows up as ~56 MB against an ~850 MB floor);
  4. the Setup.exe must look like an Inno Setup executable.

Usage (also wired into builder-lib.ps1 after ISCC):
    python scripts/model/verify_setup.py <Setup.exe> [--installer-dir DIR]

Exit 0 with a Persian summary; exit 1 naming exactly what is wrong.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
#: quantized GGUF weights barely compress — 0.8× is a generous floor
MIN_FACTOR = 0.8
#: below this the file cannot possibly contain app + model
ABSOLUTE_FLOOR_MB = 60
INNO_MARKER = b"Inno Setup Setup Data"


def payload_models(installer_dir: Path) -> list[dict]:
    """Parse model_payload.iss + seed.json into the list of embedded models."""
    iss = installer_dir / "model_payload.iss"
    if not iss.exists():
        return []
    text = iss.read_text(encoding="utf-8-sig", errors="replace")
    models = []
    for match in re.finditer(
            r'Source:\s*"model\\([^"\\]+)\\([^"]+\.gguf)"', text):
        model_id, file_name = match.group(1), match.group(2)
        gguf = installer_dir / "model" / model_id / file_name
        seed = installer_dir / "model" / model_id / "seed.json"
        try:
            manifest = json.loads(seed.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            manifest = {}
        models.append({"model_id": model_id, "file": file_name, "gguf": gguf,
                       "size": gguf.stat().st_size if gguf.exists() else 0,
                       "sha256": manifest.get("sha256")})
    return models


def verify(setup: Path, installer_dir: Path) -> tuple[bool, list[str], dict]:
    problems: list[str] = []
    info: dict = {"setup": str(setup), "size": 0, "models": []}
    if not setup.exists():
        return False, [f"فایل نصب پیدا نشد: {setup}"], info
    info["size"] = setup.stat().st_size

    head = setup.read_bytes()[: max(len(INNO_MARKER) + 4, 4096)] if setup.stat().st_size else b""
    # Inno markers live near the end of the file for some versions; scan the tail too
    tail = b""
    with open(setup, "rb") as fh:
        fh.seek(0, 2)
        end = fh.tell()
        fh.seek(max(0, end - 4096))
        tail = fh.read(4096)
    if INNO_MARKER not in head and INNO_MARKER not in tail:
        problems.append("فایل Setup.exe نشانگر Inno Setup را ندارد — این فایل نصب معتبر نیست")

    models = payload_models(installer_dir)
    if not models:
        problems.append(
            "model_payload.iss وجود ندارد یا مدلی داخل آن نیست — مدل هرگز برای جاسازی آماده نشد "
            "(scripts/model/prepare_windows_installer.py باید قبل از Inno Setup اجرا شود)")
        return False, problems, info

    total = 0
    for m in models:
        if m["size"] <= 0:
            problems.append(f"فایل مدل پیدا نشد: {m['gguf']}")
            continue
        total += m["size"]
        info["models"].append({"model_id": m["model_id"], "bytes": m["size"],
                               "sha256": (m["sha256"] or "")[:16] + "…"})
    if total <= 0:
        return False, problems, info

    floor = int(total * MIN_FACTOR)
    if info["size"] < floor:
        problems.append(
            f"حجم فایل نصب {info['size'] / 1e6:,.0f} مگابایت است ولی مدلِ داخلش باید حداقل "
            f"{floor / 1e6:,.0f} مگابایت باشد — مدل داخل فایل نصب نیست")
    if info["size"] < ABSOLUTE_FLOOR_MB * 1e6:
        problems.append(f"فایل نصب از {ABSOLUTE_FLOOR_MB} مگابایت هم کوچک‌تر است")
    return (not problems), problems, info


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify the model is inside the Windows Setup.exe (v4.2)")
    parser.add_argument("setup", help="path to the built Setup.exe")
    parser.add_argument("--installer-dir", default=str(ROOT / "installer" / "windows"),
                        help="installer/windows directory (where model_payload.iss lives)")
    args = parser.parse_args(argv)
    ok, problems, info = verify(Path(args.setup), Path(args.installer_dir))
    print(f"فایل نصب : {info['setup']} ({info['size'] / 1e6:,.1f} مگابایت)")
    for m in info.get("models", []):
        print(f"مدل داخل : {m['model_id']} — {m['bytes'] / 1e6:,.0f} مگابایت (sha256 {m['sha256']})")
    if ok:
        print("PASS: مدل هوش محلی واقعاً داخل فایل نصب است.")
        return 0
    for p in problems:
        print(f"FAIL: {p}", file=sys.stderr)
    print("\nاین Setup.exe بدون مدل است و ساخته‌شدنش نباید اعلام می‌شد. دوباره بیلد بگیرید و اگر "
          "دانلود مدل شکست خورده بود، اول اینترنت را بررسی کنید (دانلود نیمه‌کاره از همان‌جا ادامه می‌یابد).",
          file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
