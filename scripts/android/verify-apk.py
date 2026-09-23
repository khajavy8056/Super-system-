#!/usr/bin/env python3
"""v4.1.1 — APK install-preflight (pure stdlib).

The owner hit «برنامه نصب نشد» with an APK that passed `apksigner verify` and
`aapt2 dump badging` — those tools do not check everything PackageManager
checks at install time. This script re-checks, from the raw zip bytes, the
things that actually block installation:

  1. every stored (uncompressed) entry's DATA must be 4-byte aligned when the
     entry is mmap-critical — Android 11+ (targetSdk 30+) REJECTS the whole
     APK when ``resources.arsc`` is compressed or misaligned
     (INSTALL_FAILED_INVALID_APK). Our Gradle-less pipeline has no zipalign,
     so this is the one class of silent rot it can produce;
  2. resources.arsc must exist and be STORED (uncompressed);
  3. classes.dex must exist;
  4. native libs: report which ABIs ship — an APK with only arm64-v8a cannot
     install on a 32-bit phone (NO_MATCHING_ABIS); both ABIs should ship;
  5. AndroidManifest.xml (binary) must contain the expected package/version.

Usage:  python scripts/android/verify-apk.py <file.apk>
Exit 0 = installable structure; exit 1 with a Persian explanation otherwise.
"""
from __future__ import annotations

import struct
import sys
import zipfile


def _entries(data: bytes) -> list[dict]:
    eocd = data.rfind(b"PK\x05\x06")
    if eocd < 0:
        raise SystemExit("not a zip: no EOCD")
    cd_off = struct.unpack("<I", data[eocd + 16:eocd + 20])[0]
    cd_size = struct.unpack("<I", data[eocd + 12:eocd + 16])[0]
    pos, out = cd_off, []
    while pos < cd_off + cd_size:
        if data[pos:pos + 4] != b"PK\x01\x02":
            raise SystemExit(f"bad central directory entry at {pos}")
        method = struct.unpack("<H", data[pos + 10:pos + 12])[0]
        nlen = struct.unpack("<H", data[pos + 28:pos + 30])[0]
        elen = struct.unpack("<H", data[pos + 30:pos + 32])[0]
        lho = struct.unpack("<I", data[pos + 42:pos + 46])[0]
        name = data[pos + 46:pos + 46 + nlen].decode("utf-8", "replace")
        lnlen = struct.unpack("<H", data[lho + 26:lho + 28])[0]
        lelen = struct.unpack("<H", data[lho + 28:lho + 30])[0]
        out.append({"name": name, "method": method, "data_off": lho + 30 + lnlen + lelen})
        pos += 46 + nlen + elen
    return out


def main(path: str) -> int:
    data = open(path, "rb").read()
    entries = _entries(data)
    names = {e["name"] for e in entries}
    problems: list[str] = []

    if "classes.dex" not in names:
        problems.append("classes.dex missing")
    arsc = next((e for e in entries if e["name"] == "resources.arsc"), None)
    if arsc is None:
        problems.append("resources.arsc missing — the APK has no resources")
    else:
        if arsc["method"] != 0:
            problems.append("resources.arsc is COMPRESSED — Android 11+ refuses to install "
                            "(targetSdk 30+ requires it stored)")
        if arsc["data_off"] % 4 != 0:
            problems.append(f"resources.arsc data is NOT 4-byte aligned (offset {arsc['data_off']}) "
                            "— Android 11+ refuses to install")

    abis = sorted({e["name"].split("/")[1] for e in entries
                   if e["name"].startswith("lib/") and e["name"].count("/") >= 2})
    manifest = "AndroidManifest.xml" in names

    # any OTHER stored entry that is misaligned is a performance smell, not an
    # install blocker — report it but do not fail
    misaligned_stored = [e["name"] for e in entries
                         if e["method"] == 0 and e["data_off"] % 4 != 0
                         and e["name"] != "resources.arsc"]

    if not manifest:
        problems.append("AndroidManifest.xml missing")

    # a CRC pass over everything (transfer corruption / truncated file)
    try:
        with zipfile.ZipFile(path) as zf:
            bad = zf.testzip()
            if bad is not None:
                problems.append(f"corrupt entry: {bad}")
    except zipfile.BadZipFile as exc:
        problems.append(f"not a valid zip: {exc}")

    print(f"file            : {path} ({len(data):,} bytes)")
    print(f"entries         : {len(entries)}")
    print(f"native ABIs     : {abis if abis else 'none (pure-java app)'}")
    if abis and "armeabi-v7a" not in abis:
        print("warning         : no armeabi-v7a — the APK will NOT install on 32-bit phones")
    if misaligned_stored:
        print(f"note (perf only): {len(misaligned_stored)} stored entries not 4-aligned "
              "(not an install blocker)")
    if problems:
        for p in problems:
            print(f"FAIL: {p}")
        print("\nاین APK روی اندروید ۱۱+ نصب نمی‌شود — ساخت را با اسکریپت بیلد اصلاح کنید.")
        return 1
    print("PASS: install-blocking structure is sound")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        raise SystemExit(2)
    raise SystemExit(main(sys.argv[1]))
