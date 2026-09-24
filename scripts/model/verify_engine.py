#!/usr/bin/env python3
"""v4.3.3 — verify the Windows engine's DLL prerequisites REALLY exist.

Why: the owner's shop PC showed «llama.dll was not found», «ggml-base.dll was
not found», «libcurl-x64.dll was not found» at launch. The official llama.cpp
Windows build is a DYNAMIC build: llama-server.exe imports llama.dll,
ggml-base.dll, ggml-cpu.dll, libcurl-x64.dll… — and the installer had shipped
only the exe (``prepare_engine`` extracted exactly one file from the archive).

This module reads the ACTUAL import table of every PE file in the runtime dir
(pure stdlib — no Windows needed, so the sandbox can verify a Windows payload)
and checks every imported DLL is either bundled next to the exe or a Windows
system DLL. Recursively: a bundled llama.dll's own imports are checked too.

Usage:
    python scripts/model/verify_engine.py installer/windows/runtime
Exit 0 = every prerequisite is satisfied; exit 1 = a Persian list of gaps.
"""
from __future__ import annotations

import sys
from pathlib import Path

#: DLLs the Windows OS itself provides (loader resolves them before our check
#: could ever matter). Anything NOT on this list must be BUNDLED — except the
#: Microsoft VC++ runtime family, which is treated as "system" too (see below).
#:
#: v4.5.0 — the owner's real build log tripped over three of these:
#:   • wldap32.dll  — WinLDAP, a System32 component since forever; imported
#:     by the bundled libcurl-x64.dll (LDAP:// support inside curl).
#:   • psapi.dll    — Process Status API, System32 since XP; imported by the
#:     engine's memory-report paths.
#:   • msvcp140_codecvt_ids.dll — same VC++ 2015+ redistributable family as
#:     msvcp140/vcruntime140 (already allowed): msvcp140.dll delay-loads it
#:     for C++ codecvt locale facets, which llama-server never touches.
#: All three are Microsoft components, never llama.cpp build outputs —
#: demanding them "bundled" would mean repacking Windows itself.
SYSTEM_DLLS = {
    "kernel32", "user32", "gdi32", "shell32", "advapi32", "ws2_32", "wsock32",
    "ntdll", "msvcrt", "ucrtbase", "vcruntime140", "vcruntime140_1",
    "msvcp140", "msvcr120", "msvcr110", "msvcr100", "ole32", "oleaut32",
    "comctl32", "comdlg32", "shlwapi", "dbghelp", "bcrypt", "crypt32",
    "secur32", "userenv", "mswsock", "iphlpapi", "winmm", "setupapi",
    "version", "dwmapi", "uxtheme", "powrprof", "wininet", "winhttp",
    "normaliz", "rpcrt4", "sechost", "imm32", "combase", "win32u",
    "profapi", "cryptbase", "sspicli", "nsi", "cfgmgr32", "dbgcore",
    # v4.5.0: OS DLLs the official engine build imports (owner's log)
    "psapi", "wldap32", "ncrypt", "dnsapi", "wintrust",
    # v4.5.0: the rest of the VC++ 2015+ redistributable family
    # (msvcp140/vcruntime140 were already here; codecvt_ids was the gap)
    "msvcp140_2", "msvcp140_atomic_wait", "msvcp140_codecvt_ids",
    "concrt140", "vcomp140",
}
SYSTEM_PREFIXES = ("api-ms-win-", "ext-ms-")


def import_table(path: Path) -> set[str]:
    """Parse a PE file's import tables (directories 1 + 13) → set of DLL names
    (lowercase). Raises ValueError on anything that is not a parseable PE."""
    data = path.read_bytes()
    if len(data) < 0x40 or data[:2] != b"MZ":
        raise ValueError(f"{path.name}: not a PE file (no MZ header)")
    e_lfanew = int.from_bytes(data[0x3C:0x40], "little")
    if data[e_lfanew:e_lfanew + 4] != b"PE\x00\x00":
        raise ValueError(f"{path.name}: PE signature missing")

    coff = e_lfanew + 4
    num_sections = int.from_bytes(data[coff + 2:coff + 4], "little")
    opt_size = int.from_bytes(data[coff + 16:coff + 18], "little")
    opt = coff + 20
    magic = int.from_bytes(data[opt:opt + 2], "little")
    if magic == 0x20B:            # PE32+
        dd = opt + 112
    elif magic == 0x10B:          # PE32
        dd = opt + 96
    else:
        raise ValueError(f"{path.name}: unknown optional-header magic {magic:#x}")

    sections: list[tuple[int, int, int]] = []
    sec = opt + opt_size
    for i in range(num_sections):
        h = data[sec + i * 40: sec + (i + 1) * 40]
        v_size = int.from_bytes(h[8:12], "little")
        v_addr = int.from_bytes(h[12:16], "little")
        raw_ptr = int.from_bytes(h[20:24], "little")
        if v_size or raw_ptr:
            sections.append((v_addr, max(v_size, 1), raw_ptr))

    def rva2off(rva: int) -> int:
        for va, size, raw in sections:
            if va <= rva < va + size:
                return raw + (rva - va)
        raise ValueError(f"{path.name}: RVA {rva:#x} outside any section")

    def dlls_in_table(rva: int) -> set[str]:
        out: set[str] = set()
        off = rva2off(rva)
        while len(out) < 512:                      # sanity bound
            desc = data[off:off + 20]
            if len(desc) < 20:
                break
            oft = int.from_bytes(desc[0:4], "little")
            iat = int.from_bytes(desc[16:20], "little")
            name_rva = int.from_bytes(desc[12:16], "little")
            if oft == 0 and iat == 0 and name_rva == 0:
                break                               # end-of-array marker
            if name_rva:
                n = rva2off(name_rva)
                end = data.find(b"\x00", n)
                if end > n:
                    out.add(data[n:end].decode("ascii", "replace").lower())
            off += 20
        return out

    dlls: set[str] = set()
    for directory in (1, 13):                      # imports + delay-loads
        rva = int.from_bytes(data[dd + directory * 8: dd + directory * 8 + 4], "little")
        if rva:
            dlls |= dlls_in_table(rva)
    return dlls


def _is_system(name: str) -> bool:
    base = name.rsplit(".", 1)[0] if name.endswith(".dll") else name
    return base in SYSTEM_DLLS or any(base.startswith(p) for p in SYSTEM_PREFIXES)


def verify(runtime_dir: Path) -> tuple[bool, list[str], dict]:
    """Check every PE in the runtime dir: each import is bundled or system.

    Returns (ok, persian_problems, report). The report maps each file to its
    imports and marks which are bundled / system / missing.
    """
    problems: list[str] = []
    report: dict = {"runtime": str(runtime_dir), "files": {}}
    exe = runtime_dir / "llama-server.exe"
    if not exe.exists():
        return False, ["llama-server.exe در پوشهٔ موتور نیست"], report

    bundled = {p.name.lower() for p in runtime_dir.iterdir() if p.suffix.lower() == ".dll"}
    to_check: list[Path] = [exe] + sorted(runtime_dir.glob("*.dll"))
    for pe in to_check:
        try:
            imports = import_table(pe)
        except ValueError as exc:
            problems.append(f"فایل موتور قابل بررسی نیست — {exc}")
            continue
        info = {"imports": {}, "bundled": sorted(bundled)}
        for name in sorted(imports):
            if name in bundled:
                info["imports"][name] = "bundled"
            elif _is_system(name):
                info["imports"][name] = "system"
            else:
                info["imports"][name] = "MISSING"
                problems.append(
                    f"«{name}» برای اجرای llama-server لازم است ولی کنارش نیست — "
                    "باید داخل نصب‌کننده باشد")
        report["files"][pe.name] = info
    return (not problems), problems, report


def main(argv: list[str] | None = None) -> int:
    import argparse
    parser = argparse.ArgumentParser(description="Verify the Windows engine's DLL prerequisites (v4.3.3)")
    parser.add_argument("runtime_dir", help="installer/windows/runtime")
    args = parser.parse_args(argv)
    ok, problems, report = verify(Path(args.runtime_dir))
    for name, info in report.get("files", {}).items():
        print(f"{name}: {len(info['imports'])} وابستگی بررسی شد")
    if ok:
        print("PASS: همهٔ پیش‌نیازهای DLL موتور داخل نصب‌کننده هستند.")
        return 0
    for p in problems:
        print(f"FAIL: {p}", file=sys.stderr)
    print("موتور ناقص است و نباید وارد نصب‌کننده شود — دوباره بیلد بگیرید تا از مخزن رسمی "
          "دریافت و تأیید شود.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
