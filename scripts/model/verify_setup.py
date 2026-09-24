#!/usr/bin/env python3
"""v4.2.1 — verify that a built Windows Setup.exe REALLY contains the model.

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
  4. the Setup.exe must be a PE executable carrying the Inno Setup signature.

Where the Inno signature lives (checked against the official Inno Setup 6.7.3
source, Projects/Src/Shared.Struct.pas + Compiler.SetupCompiler.pas):
``SetupID: TSetupID = 'Inno Setup Setup Data (6.7.0)'`` is a 64-byte record
written at the START of the embedded setup-0 block — i.e. right AFTER the
Inno stub PE image, several hundred KiB into the file, NOT at the end of the
file. v4.2.0 searched the last 4 KiB, found nothing, and wrongly destroyed a
perfect 1,153.8 MB Setup.exe after 8 minutes of ISCC compression. Never again:
we scan the first 4 MiB (the stub is well under 2 MiB) and exit codes are
separated:

  exit 0 — the model is inside; ship it.
  exit 1 — the MODEL is missing (payload manifest absent / GGUF missing /
           Setup.exe below the size floor). The builder deletes the setup.
  exit 2 — structural suspicion only (no PE header / no Inno signature) while
           the payload itself looked fine. The builder FAILS but KEEPS the
           file for inspection instead of deleting the owner's 8-minute build.

Usage (also wired into builder-lib.ps1 after ISCC):
    python scripts/model/verify_setup.py <Setup.exe> [--installer-dir DIR]
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
#: the stub PE is < 2 MiB, so the setup-0 signature is inside the first 4 MiB
HEAD_SCAN = 4 * 1024 * 1024
#: exact-case prefix of the Pascal constant in Inno's Shared.Struct.pas
#: (5.3.7+ and 6.x all match; the version inside the parentheses varies)
INNO_MARKER = b"Inno Setup Setup Data ("


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


def _looks_like_inno_setup(setup: Path) -> bool:
    """True when the file is a PE carrying the Inno signature record.

    Reads at most HEAD_SCAN bytes — never the whole (potentially > 1 GB) file;
    v4.2.0 loaded the entire Setup.exe into RAM for the head check.
    """
    try:
        with open(setup, "rb") as fh:
            head = fh.read(HEAD_SCAN)
    except OSError:
        return False
    if len(head) < 2 or head[:2] != b"MZ":
        return False
    return INNO_MARKER in head


def verify(setup: Path, installer_dir: Path) -> tuple[bool, list[str], dict, int]:
    """Returns (ok, problems, info, exit_code) — see the module docstring."""
    problems: list[str] = []
    info: dict = {"setup": str(setup), "size": 0, "models": []}
    if not setup.exists():
        return False, [f"فایل نصب پیدا نشد: {setup}"], info, 1
    info["size"] = setup.stat().st_size

    models = payload_models(installer_dir)
    if not models:
        problems.append(
            "model_payload.iss وجود ندارد یا مدلی داخل آن نیست — مدل هرگز برای جاسازی آماده نشد "
            "(scripts/model/prepare_windows_installer.py باید قبل از Inno Setup اجرا شود)")
        return False, problems, info, 1

    total = 0
    for m in models:
        if m["size"] <= 0:
            problems.append(f"فایل مدل پیدا نشد: {m['gguf']}")
            continue
        total += m["size"]
        info["models"].append({"model_id": m["model_id"], "bytes": m["size"],
                               "sha256": (m["sha256"] or "")[:16] + "…"})
    if total <= 0:
        return False, problems, info, 1

    floor = int(total * MIN_FACTOR)
    if info["size"] < floor or info["size"] < ABSOLUTE_FLOOR_MB * 1e6:
        problems.append(
            f"حجم فایل نصب {info['size'] / 1e6:,.0f} مگابایت است ولی مدلِ داخلش باید حداقل "
            f"{floor / 1e6:,.0f} مگابایت باشد — مدل داخل فایل نصب نیست")
        return False, problems, info, 1

    # v4.3.3 — the ENGINE must not be half-shipped: if llama-server.exe was
    # prepared, its DLL prerequisites must all be present (llama.dll,
    # ggml-base.dll, libcurl-x64.dll…) and model_payload.iss must carry the
    # runtime\* line that packs them. A half engine pops DLL errors at every
    # launch of the brain's autostart (the owner's exact report).
    runtime_dir = installer_dir / "runtime"
    if (runtime_dir / "llama-server.exe").exists():
        sys.path.insert(0, str(Path(__file__).resolve().parent))   # sibling import
        import verify_engine  # noqa: PLC0415 — sibling module (scripts/model)
        eng_ok, eng_problems, _eng = verify_engine.verify(runtime_dir)
        if not eng_ok:
            problems.extend(eng_problems)
            return False, problems, info, 1
        try:
            manifest = json.loads((runtime_dir / "engine.json").read_text(encoding="utf-8"))
            if manifest.get("complete") is not True:
                problems.append("engine.json موتور را کامل علامت نزده — بیلد دوباره گرفته شود")
                return False, problems, info, 1
        except (OSError, ValueError):
            problems.append("engine.json موتور خوانده نشد")
            return False, problems, info, 1
        iss_text = (installer_dir / "model_payload.iss").read_text(
            encoding="utf-8-sig", errors="replace") if (installer_dir / "model_payload.iss").exists() else ""
        if "runtime" + chr(92) + "*" not in iss_text:      # runtime\* in the .iss
            problems.append("model_payload.iss خط بسته‌بندی runtime را ندارد — DLLهای موتور "
                            "وارد نصب‌کننده نمی‌شوند")
            return False, problems, info, 1

    # payload looks right — now the structure check (v4.2.1: keep, don't delete)
    if not _looks_like_inno_setup(setup):
        problems.append(
            "فایل Setup.exe نشانگر Inno Setup را در ابتدای فایل ندارد — احتمالاً خروجی ISCC "
            "کامل نیست؛ فایل برای بررسی حفظ شد و حذف نمی‌شود")
        return False, problems, info, 2

    return True, problems, info, 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify the model is inside the Windows Setup.exe (v4.2.1)")
    parser.add_argument("setup", help="path to the built Setup.exe")
    parser.add_argument("--installer-dir", default=str(ROOT / "installer" / "windows"),
                        help="installer/windows directory (where model_payload.iss lives)")
    args = parser.parse_args(argv)
    ok, problems, info, code = verify(Path(args.setup), Path(args.installer_dir))
    print(f"فایل نصب : {info['setup']} ({info['size'] / 1e6:,.1f} مگابایت)")
    for m in info.get("models", []):
        print(f"مدل داخل : {m['model_id']} — {m['bytes'] / 1e6:,.0f} مگابایت (sha256 {m['sha256']})")
    if ok:
        print("PASS: مدل هوش محلی واقعاً داخل فایل نصب است.")
        return 0
    for p in problems:
        print(f"FAIL: {p}", file=sys.stderr)
    if code == 1:
        print("\nاین Setup.exe بدون مدل است و ساخته‌شدنش نباید اعلام می‌شد. دوباره بیلد بگیرید و اگر "
              "دانلود مدل شکست خورده بود، اول اینترنت را بررسی کنید (دانلود نیمه‌کاره از همان‌جا ادامه می‌یابد).",
              file=sys.stderr)
    else:
        print("\nمدل داخل فایل به نظر می‌رسد ولی ساختار فایل نصب مشکوک است — فایل حذف نشد؛ خروجی "
              "بالا را بررسی کنید.", file=sys.stderr)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
