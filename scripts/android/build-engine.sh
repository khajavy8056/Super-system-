#!/usr/bin/env bash
# Build the on-device inference engine (llama.cpp "llama-server") for Android —
# v4.1.1: BOTH arm64-v8a AND armeabi-v7a.
#
# WHY THIS EXISTS: the phone must run the SAME engine the PC runs. The Windows
# installer bundles the official llama.cpp release binary (win-x64); upstream
# publishes NO Android binaries, so we cross-compile the SAME pinned tag from
# source. No Android NDK is needed (and this build environment has no access
# to dl.google.com anyway): zig (the `ziglang` wheel on PyPI) compiles fully
# STATIC binaries Android executes from the app's nativeLibraryDir.
#
# Outputs (build-apk.sh packs them into the APK automatically):
#   mobile-android/app/src/main/jniLibs/arm64-v8a/libllamaserver.so
#   mobile-android/app/src/main/jniLibs/armeabi-v7a/libllamaserver.so
#
# armeabi-v7a matters for INSTALLABILITY: an APK that ships only arm64-v8a
# cannot install at all on a 32-bit phone (INSTALL_FAILED_NO_MATCHING_ABIS) —
# exactly the "برنامه نصب نشد" the owner hit. The v7a engine targets
# cortex-a7 (ARMv7-A + NEON + VFPv3-D16, the armeabi-v7a baseline); on a
# 32-bit phone it usually cannot run the model for RAM reasons (min 3584 MB)
# but the APP installs and the brain keeps working paired with the PC.
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
OUTROOT="${OUTROOT:-$ROOT/mobile-android/app/src/main/jniLibs}"
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

# (target, zig cpu flags, cmake processor, out abi dir) — the two Android ABIs.
# NOTE v7a uses the HARD-FLOAT musl target: zig's ARM32 backend cannot compile
# NEON intrinsics under soft/softfp ("Do not know how to split the result of
# this operator", verified 2026-09-23), and a fully-static binary carries its
# own ABI — hard-float code runs on every ARMv7 device (VFPv3-D16 is part of
# the armeabi-v7a baseline). NEON is used; the handful of NEON-less ARMv7
# SoCs (e.g. Tegra 2, 2011) cannot run the engine — the app still installs
# and the brain keeps working paired with the PC.
BUILDS=(
  "aarch64-linux-musl|-mcpu=generic|aarch64|arm64-v8a"
  "arm-linux-musleabihf|-mcpu=cortex_a7|arm|armeabi-v7a"
)

for spec in "${BUILDS[@]}"; do
  IFS='|' read -r TARGET CPUFLAGS PROC ABI <<< "$spec"
  echo "== build $ABI (zig target $TARGET, $CPUFLAGS)"
  WR="$WORK/$ABI"; mkdir -p "$WR"
  printf '#!/bin/sh\nexec %q -m ziglang cc -target %q %s -static "$@"\n' "$PY" "$TARGET" "$CPUFLAGS" > "$WR/cc"
  printf '#!/bin/sh\nexec %q -m ziglang c++ -target %q %s -static "$@"\n' "$PY" "$TARGET" "$CPUFLAGS" > "$WR/cxx"
  chmod +x "$WR/cc" "$WR/cxx"
  cat > "$WR/toolchain.cmake" <<EOF
set(CMAKE_SYSTEM_NAME Linux)
set(CMAKE_SYSTEM_PROCESSOR $PROC)
set(CMAKE_C_COMPILER $WR/cc)
set(CMAKE_CXX_COMPILER $WR/cxx)
set(CMAKE_TRY_COMPILE_TARGET_TYPE STATIC_LIBRARY)
EOF
  export PATH="$VENV/bin:$PATH"
  BUILD="$WR/build"; mkdir -p "$BUILD"; cd "$BUILD"
  cmake "$WORK/src" -G Ninja \
    -DCMAKE_TOOLCHAIN_FILE="$WR/toolchain.cmake" \
    -DCMAKE_BUILD_TYPE=Release -DBUILD_SHARED_LIBS=OFF \
    -DGGML_NATIVE=OFF -DGGML_OPENMP=OFF -DGGML_BACKEND_DL=OFF \
    -DLLAMA_CURL=OFF -DLLAMA_BUILD_TESTS=OFF -DLLAMA_BUILD_EXAMPLES=OFF \
    -DLLAMA_BUILD_TOOLS=ON -DLLAMA_BUILD_SERVER=ON -DLLAMA_BUILD_COMMON=ON \
    -DLLAMA_BUILD_NUMBER=6283 -DLLAMA_BUILD_COMMIT="$TAG" \
    -DCMAKE_C_FLAGS="-O2" -DCMAKE_CXX_FLAGS="-O2" \
    -DCMAKE_EXE_LINKER_FLAGS="-s"
  ninja llama-server
  [ -f "$BUILD/bin/llama-server" ] || { echo "llama-server ($ABI) was not produced"; exit 1; }
  "$PY" - "$BUILD/bin/llama-server" "$ABI" <<'EOF'
import struct, sys
path, abi = sys.argv[1], sys.argv[2]
data = open(path, 'rb').read()
assert data[:4] == b'\x7fELF', f"{abi}: not an ELF"
is64 = data[4] == 2
machine = struct.unpack('<H', data[18:20])[0]
want = (183, True) if abi == 'arm64-v8a' else (40, False)
assert machine == want[0], f"{abi}: wrong ELF machine {machine} (wanted {want[0]})"
assert is64 == want[1], f"{abi}: wrong ELF class ({'64' if is64 else '32'}-bit)"
if is64:
    phoff = struct.unpack('<Q', data[0x20:0x28])[0]
    phentsize = struct.unpack('<H', data[0x36:0x38])[0]
    phnum = struct.unpack('<H', data[0x38:0x3a])[0]
else:
    phoff = struct.unpack('<I', data[0x1c:0x20])[0]
    phentsize = struct.unpack('<H', data[0x2a:0x2c])[0]
    phnum = struct.unpack('<H', data[0x2c:0x2e])[0]
types = {struct.unpack('<I', data[phoff + i*phentsize: phoff + i*phentsize + 4])[0] for i in range(phnum)}
assert 3 not in types, f"{abi}: PT_INTERP present — dynamic binary will NOT run on Android"
assert 2 not in types, f"{abi}: PT_DYNAMIC present — not a static binary"
print(f"OK {abi}: static ELF ({'64' if is64 else '32'}-bit, machine {machine}), {len(data)/1e6:.1f} MB")
EOF
  mkdir -p "$OUTDIR"
  cp "$BUILD/bin/llama-server" "$OUTDIR/libllamaserver.so"
  chmod 644 "$OUTDIR/libllamaserver.so"
  echo "   → $OUTDIR/libllamaserver.so"
done

echo "OK — both ABIs built. next: scripts/android/build-apk.sh packs them automatically"
