# RELEASE AUDIT — 4.3.3 «DLLهای موتور»

**Date:** 2026-09-24 · **Verdict: PASS for release.** Full suite **771 passed / 1 skipped** (+12 new v4.3.3 tests).

---

## 1. The owner's Windows errors, root-caused

| Error on the shop PC | Why | Fix |
|---|---|---|
| `llama.dll was not found` | llama.cpp's official Windows build is DYNAMIC: llama-server.exe imports llama.dll, ggml-base.dll, ggml-cpu.dll, libcurl-x64.dll… — but `prepare_engine` extracted exactly ONE file (`wanted = ("llama-server.exe",)`) from the official archive. The DLLs were discarded before they ever reached the installer. | Extract the exe AND every `*.dll` from the official archive into `installer/windows/runtime/` (Inno already packs `runtime\*`). |
| «بررسی کن که اگر dll دیگه هم نیاز باشه درست کنی» | A fixed list of DLL names would be a guess. | `scripts/model/verify_engine.py`: a pure-stdlib PE parser reads the ACTUAL import table (directories 1 + 13, delay-loads included) of llama-server.exe AND every bundled DLL (recursive), and requires each dependency to be bundled or a Windows system DLL. Nothing can be missed again — the import table is the ground truth. |
| his machine already has the broken engine cached | the old `engine.json` marker short-circuited the engine step | markers without `"complete": true` (or failing re-verification) force a RE-FETCH of the official archive on the next build |

Failsafe behaviours, all test-pinned:
- a payload that is still incomplete after extraction → **the build FAILS** (exit 1 + Persian list) — a half engine pops DLL dialogs at every brain autostart;
- a failed engine download deletes the partial zip (Inno packs `runtime\*` wholesale — nothing half-shipped), and the build continues model-only, honestly;
- `verify_setup.py` re-checks the engine inside the FINAL pipeline: import graph pass + `complete: true` + the `runtime\*` line present.

## 2. Android — verified, needs nothing

The owner asked to make sure Android has no such prerequisite problem. Proof (test-pinned since 4.1.0, re-asserted this round in `test_v433_engine_dlls.py`): both shipped engines (`lib/arm64-v8a`, `lib/armeabi-v7a`) are **fully static ELFs** — no `PT_INTERP` (no dynamic loader) and no `PT_DYNAMIC` (no shared-library imports whatsoever). A Windows-style missing-DLL failure is impossible on Android by construction; the engine's only runtime dependencies are the Linux kernel syscalls.

## 3. Changed files

- `scripts/model/verify_engine.py` — NEW: PE import-table parser + recursive verifier + CLI.
- `scripts/model/prepare_windows_installer.py` — `prepare_engine` rewritten (extract exe + all DLLs, verify, `complete: true` manifest with per-file bytes+sha256, old-marker re-fetch, partial cleanup).
- `scripts/model/verify_setup.py` — engine completeness cross-check on the built pipeline.
- `backend/tests/test_v433_engine_dlls.py` — NEW (12 tests; includes a synthetic-PE builder that exercises the parser for real).
- `backend/tests/test_v432_engine_ram.py` — version test made version-agnostic.
- Versions: 4.3.3 / setup.iss 4.3.3 / Android versionCode 40303.
- `releases/android/SupermarketMobile-4.3.3.apk` (+ `.sha256`, `.idsig`) — Android code unchanged this round; version-consistent build, preflight PASS, same cert.

## 4. What the owner must do

Rebuild the Windows installer ONCE from this tree. The engine step will detect his cached incomplete engine, re-download the official archive (tens of MB, resume-capable), extract the full DLL set, verify the import graph, and only then let ISCC pack `runtime\*`. The resulting Setup.exe installs a brain that starts without any DLL dialog.
