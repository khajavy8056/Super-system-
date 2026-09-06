#!/usr/bin/env python3
"""Generate stub shared libraries for missing Qt runtime deps (headless sandbox).

On hosts without system Qt runtime libraries (libEGL, libnss, libasound, …) a
PySide6 WebEngine offscreen render fails to even import. This script derives —
from the *real* PySide6 libraries themselves — exactly which symbols/versions
are needed, then builds minimal stub .so files that satisfy the dynamic linker:

- for every Qt lib/plugin it runs ``objdump -p`` to read the "Version
  References" table (version tag → owning SONAME), and ``objdump -T`` for
  undefined symbols;
- symbols are routed to the stub whose SONAME owns the version tag (fallback:
  name-prefix rules); every verneed tag is defined even with no symbol refs
  (the loader checks the tag exists);
- stubs export the symbols returning 0 (NULL) so Chromium takes its graceful
  failure paths (no dbus/udev/GPU → software rendering continues);
- each stub is built with matching ``-soname`` and a version-script, otherwise
  ld.so aborts with "version not found" / assertion in dl-lookup.

Usage:
    python scripts/make_qt_stublibs.py /path/to/venv/lib/python3.11/site-packages/PySide6
    # → writes stub .so files to ./stublibs
    LD_LIBRARY_PATH=./stublibs QT_QPA_PLATFORM=offscreen python scripts/shoot.py …
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

TARGETS = [
    "libEGL.so.1", "libGL.so.1", "libasound.so.2", "libnspr4.so", "libnss3.so",
    "libnssutil3.so", "libplc4.so", "libplds4.so", "libsmime3.so",
    "libxkbcommon.so.0", "libxkbfile.so.1", "libgbm.so.1", "libXcomposite.so.1",
    "libXdamage.so.1", "libXfixes.so.3", "libXrandr.so.2", "libXtst.so.6",
    "libxcb-dri3.so.0", "libdbus-1.so.3", "libudev.so.1",
    # PySide 6.7 additionally links these (absent on minimal hosts)
    "libXi.so.6", "libXrender.so.1", "libdrm.so.2", "libxshmfence.so.1",
]
# fallback routing for UNversioned undefined symbols (by name prefix)
PREFIX = {
    "libEGL.so.1": ("egl", "EGL"),
    "libGL.so.1": ("glX", "GLX", "gl", "GL"),
    "libasound.so.2": ("snd_", "SND_"),
    "libnspr4.so": ("PR_", "PL_"),
    "libnss3.so": ("NSS", "CERT", "SECMOD", "PK11", "SEED", "HASHJ"),
    "libnssutil3.so": ("__NSS", "NSSUTIL"),
    "libplc4.so": ("PL_",),
    "libplds4.so": ("PL_",),
    "libsmime3.so": ("NSS", "SECITEM"),
    "libxkbcommon.so.0": ("xkb_", "xkb"),
    "libxkbfile.so.1": ("Xkb",),
    "libgbm.so.1": ("gbm_",),
    "libXcomposite.so.1": ("XComposite",),
    "libXdamage.so.1": ("XDamage",),
    "libXfixes.so.3": ("XFixes",),
    "libXrandr.so.2": ("XRR",),
    "libXtst.so.6": ("XTest",),
    "libxcb-dri3.so.0": ("xcb_dri3",),
    "libdbus-1.so.3": ("dbus_",),
    "libudev.so.1": ("udev_",),
    "libXi.so.6": ("XI", "XGetExtensionVersion", "XListInputDevices", "XFreeDeviceList",
                   "XOpenDevice", "XCloseDevice", "XSelectExtensionEvent", "XQueryDeviceState",
                   "XFreeDeviceState", "XGetDeviceButtonMapping"),
    "libXrender.so.1": ("XRender",),
    "libdrm.so.2": ("drm",),
    "libxshmfence.so.1": ("xshmfence_",),
}


def main() -> None:
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(2)
    pyside = Path(sys.argv[1])
    qt = pyside / "Qt" / "lib"
    if not qt.is_dir():
        sys.exit(f"no such dir: {qt}")

    qt_libs = sorted(set(
        list(qt.glob("*.so*"))
        + list((pyside / "Qt" / "plugins").glob("*/*.so*"))
        + list((pyside / "Qt" / "plugins").glob("*/*/*.so*"))
    ))

    # 1) version tag -> owning SONAME (from DT_VERNEED of every Qt lib/plugin)
    tag_owner: dict[str, str] = {}
    for q in qt_libs:
        out = subprocess.run(["objdump", "-p", str(q)], capture_output=True, text=True).stdout
        cur = None
        for line in out.splitlines():
            m = re.match(r"\s+required from (\S+):", line)
            if m:
                cur = m.group(1)
                continue
            toks = line.split()
            # tag lines look like:  0x08926450 0x00 73 NSS_3.30
            if cur and len(toks) == 4 and re.match(r"^0x[0-9a-f]+$", toks[0]) and not toks[3].startswith("0x"):
                tag_owner[toks[3]] = cur

    # 2) undefined symbols of every Qt lib/plugin
    ver_re = re.compile(r"^\(([A-Za-z0-9_.]+)\)$")
    need: dict[str, dict[str | None, set[str]]] = {k: {} for k in TARGETS}

    def add(lib: str, tag: str | None, sym: str) -> None:
        need[lib].setdefault(tag, set()).add(sym)

    for q in qt_libs:
        out = subprocess.run(["objdump", "-T", str(q)], capture_output=True, text=True).stdout
        for line in out.splitlines():
            parts = line.split()
            if len(parts) < 4 or "*UND*" not in parts:
                continue
            name = parts[-1].split("@")[0]
            tag = None
            m = ver_re.match(parts[-2])
            if m:
                tag = m.group(1)
            if tag and tag_owner.get(tag) in need:
                add(tag_owner[tag], tag, name)
                continue
            for libname, prefixes in PREFIX.items():
                if any(name.startswith(x) for x in prefixes):
                    add(libname, tag, name)
                    break

    # every verneed tag must exist in its owner even without symbol references
    for tag, owner in tag_owner.items():
        if owner in need:
            need[owner].setdefault(tag, set())

    # 3) build one stub per target
    outdir = Path(__file__).resolve().parent / "stublibs"
    outdir.mkdir(exist_ok=True)
    built = []
    for libname in TARGETS:
        versions = need[libname]
        if not versions:
            # still build it: other libs may carry a DT_NEEDED on this SONAME
            versions = {None: set()}
        src = outdir / ("st_" + libname.replace(".so.", "_").replace(".", "_"))
        with open(str(src) + ".c", "w") as f:
            for syms in versions.values():
                for s in sorted(syms):
                    f.write(f"void* {s}(void) {{ return 0; }}\n")
        with open(str(src) + ".map", "w") as f:
            for tag, syms in versions.items():
                body = "\n".join(f"  {s};" for s in sorted(syms)) or "  __stub_dummy_;"
                f.write(f"{tag or 'NOMATCH'} {{\n  global:\n{body}\n}};\n")
        r = subprocess.run(
            ["gcc", "-shared", "-fPIC", str(src) + ".c",
             f"-Wl,--version-script={src}.map", f"-Wl,-soname,{libname}",
             "-o", str(outdir / libname)],
            capture_output=True, text=True,
        )
        if r.returncode != 0:
            print(f"FAIL {libname}: {r.stderr[:200]}")
        else:
            built.append(libname)
        (Path(str(src) + ".c")).unlink(missing_ok=True)
        (Path(str(src) + ".map")).unlink(missing_ok=True)
    print(f"built {len(built)} stubs into {outdir}")
    print(f"usage: LD_LIBRARY_PATH={outdir} QT_QPA_PLATFORM=offscreen …")


if __name__ == "__main__":
    main()
