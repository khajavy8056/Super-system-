#!/usr/bin/env bash
# Build the on-device inference engine (llama.cpp "llama-server") for Android
# arm64-v8a — v4.1.
#
# WHY THIS EXISTS: the phone must run the SAME engine the PC runs. The Windows
# installer bundles the official llama.cpp release binary (win-x64); upstream
# publishes NO Android binaries, so we cross-compile the SAME pinned tag from
# source. No Android NDK is needed (and this build environment has no access
# to dl.google.com anyway): zig (the `ziglang` wheel on PyPI) compiles a fully
# STATIC aarch64-linux-musl binary, which Android executes fine from the app's
# nativeLibraryDir when it ships as lib/arm64-v8a/libllamaserver.so.
#
# Output: mobile-android/app/src/main/jniLibs/arm64-v8a/libllamaserver.so
# build-apk.sh packs it into the APK automatically.
#
# Requirements: bash, curl, and a python venv with `ziglang`, `cmake`, `ninja`
# (all on PyPI: pip install ziglang cmake ninja). Network: codeload.github.com
# for the llama.cpp source tarball.
#
# Reproducibility: the source tarball is content-pinned by sha256 below; the
# engine tag must match scripts/model/prepare_windows_installer.py LLAMA_TAG
# (enforced by backend/tests/test_v41_android_parity.py).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
VENV="${VENV:-$ROOT/backend/.venv}"
TAG="${TAG:-b6283}"
TARBALL_SHA256="${TARBALL_SHA256:-52b5c15c419aa3e39936e25bfab46fbd9597940eba4df3d345090530f75c3ab2}"
OUT="${OUT:-$ROOT/mobile-android/app/src/main/jniLibs/arm64-v8a/libllamaserver.so}"
WORK="${WORK:-$(mktemp -d)}"
trap 'rm -rf "$WORK"' EXIT

PY="$VENV/bin/python"; [ -x "$PY" ] || { echo "venv python not found: $PY (create it and: pip install ziglang cmake ninja)"; exit 1; }
"$PY" -m ziglang version >/dev/null 2>&1 || { echo "pip install ziglang into $VENV first"; exit 1; }
command -v curl >/dev/null || { echo "curl is required"; exit 1; }

echo "== 1/4 source (llama.cpp $TAG, official GitHub tarball)"
TARBALL="$WORK/llama.cpp-$TAG.tar.gz"
curl -sL -o "$TARBALL" "https://codeload.github.com/ggml-org/llama.cpp/tar.gz/refs/tags/$TAG"
echo "$TARBALL_SHA256  $TARBALL" | sha256sum -c -
mkdir -p "$WORK/src" && tar xzf "$TARBALL" -C "$WORK/src" --strip-components=1

echo "== 2/4 zig cross wrappers (aarch64-linux-musl, fully static)"
printf '#!/bin/sh\nexec %q -m ziglang cc -target aarch64-linux-musl -static "$@"\n' "$PY" > "$WORK/zig-cc"
printf '#!/bin/sh\nexec %q -m ziglang c++ -target aarch64-linux-musl -static "$@"\n' "$PY" > "$WORK/zig-cxx"
chmod +x "$WORK/zig-cc" "$WORK/zig-cxx"
cat > "$WORK/toolchain.cmake" <<EOF
set(CMAKE_SYSTEM_NAME Linux)
set(CMAKE_SYSTEM_PROCESSOR aarch64)
set(CMAKE_C_COMPILER $WORK/zig-cc)
set(CMAKE_CXX_COMPILER $WORK/zig-cxx)
set(CMAKE_TRY_COMPILE_TARGET_TYPE STATIC_LIBRARY)
EOF

echo "== 3/4 build llama-server (Release, static, no OpenMP/no curl)"
export PATH="$VENV/bin:$PATH"
BUILD="$WORK/build"; mkdir -p "$BUILD"; cd "$BUILD"
cmake "$WORK/src" -G Ninja \
  -DCMAKE_TOOLCHAIN_FILE="$WORK/toolchain.cmake" \
  -DCMAKE_BUILD_TYPE=Release -DBUILD_SHARED_LIBS=OFF \
  -DGGML_NATIVE=OFF -DGGML_OPENMP=OFF -DGGML_BACKEND_DL=OFF \
  -DLLAMA_CURL=OFF -DLLAMA_BUILD_TESTS=OFF -DLLAMA_BUILD_EXAMPLES=OFF \
  -DLLAMA_BUILD_TOOLS=ON -DLLAMA_BUILD_SERVER=ON -DLLAMA_BUILD_COMMON=ON \
  -DLLAMA_BUILD_NUMBER=6283 -DLLAMA_BUILD_COMMIT="$TAG" \
  -DCMAKE_C_FLAGS="-O2" -DCMAKE_CXX_FLAGS="-O2" \
  -DCMAKE_EXE_LINKER_FLAGS="-s"
ninja llama-server
[ -f "$BUILD/bin/llama-server" ] || { echo "llama-server was not produced"; exit 1; }

echo "== 4/4 verify (static aarch64 ELF — no interpreter, no dynamic section)"
"$PY" - "$BUILD/bin/llama-server" <<'EOF'
import struct, sys
data = open(sys.argv[1], 'rb').read()
assert data[:4] == b'\x7fELF' and data[4] == 2, "not a 64-bit ELF"
assert struct.unpack('<H', data[18:20])[0] == 183, "not aarch64"
phoff = struct.unpack('<Q', data[0x20:0x28])[0]
phentsize = struct.unpack('<H', data[0x36:0x38])[0]
phnum = struct.unpack('<H', data[0x38:0x3a])[0]
types = {struct.unpack('<I', data[phoff + i*phentsize: phoff + i*phentsize + 4])[0] for i in range(phnum)}
assert 3 not in types, "PT_INTERP present — dynamic binary will NOT run on Android"
assert 2 not in types, "PT_DYNAMIC present — not a static binary"
print(f"OK: static aarch64 ELF, {len(data)/1e6:.1f} MB")
EOF

mkdir -p "$(dirname "$OUT")"
cp "$BUILD/bin/llama-server" "$OUT"
chmod 644 "$OUT"
echo "OK → $OUT ($(du -h "$OUT" | cut -f1))"
echo "next: scripts/android/build-apk.sh packs it into the APK automatically"
