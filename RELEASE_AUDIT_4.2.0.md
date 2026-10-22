# RELEASE AUDIT — 4.2.0 «مدل کجاست؟»

**Date:** 2026-09-23 · **Verdict: PASS for release.** Full suite **713 passed / 1 skipped** (was 699/1; +14 new v4.2 tests, zero regressions).

---

## 1. The owner's five complaints — root cause & fix

| # | Complaint (owner, Persian) | Root cause | Fix in 4.2.0 |
|---|---|---|---|
| 1 | «مغز فروشگاه در دسترس نیست» on Android | 3.8-era install on the shop PC: no model, no engine, and the backend never started the brain on its own | `_start_brain_autostart()` in `main.py`: daemon thread adopts the installer's preinstalled model and **warm-starts llama-server at app startup**; Android chat now sends `prefer_llm:true` |
| 2 | Windows Setup.exe is **56 MB** → model not embedded | The owner built from a **3.8-era tree** (the 4.0+ builder embeds the model). Enabler: the builder's only sanity check was `$mb -lt 10` — a modelless setup "passed" | `scripts/model/verify_setup.py` wired into `builder-lib.ps1` after ISCC: Setup.exe must be ≥ 0.8 × model size, contain the Inno marker, and the payload must exist. **A failing setup is deleted and the build fails** |
| 3 | Remove اتصال GPT/cloud settings — own internal model only | v3.5 روایت ابری panel still in تنظیمات | Panel removed; replaced by a **local-model status KPI** (`/brain/model/status`); the AI-advisor button routes to مغز فروشگاه. Test-enforced absence of OpenRouter/Groq/Gemini/Ollama/narrative_* |
| 4 | Wants the brain to actually work (full manager) | — (already built in 4.0–4.1) | 4.2 makes it **alive by default**; the deterministic pipeline + model refinement contract unchanged |
| 5 | Android should self-setup the model on first open | Model download was manual-only | `BrainModel.autoSetup()`: once per install, **only on unmetered (Wi-Fi) networks**, starts the recommended q3_k_m download with a toast; mobile data never auto-burns |

**«هیچ فرقی با ۳.۸ نکرد» — explanation given to the owner:** the 3.8 program he ran never had the model system. 4.0.0 added the brain + Windows model embedding; 4.1.0/4.1.1 put the engine on Android (both ABIs); **4.2.0 makes the model present and the brain alive with zero clicks.**

## 2. Changed files (4.2.0)

- `scripts/model/verify_setup.py` — NEW: Setup.exe model-presence verifier (CLI + importable `verify()`).
- `installer/windows/builder-lib.ps1` — runs the verifier after ISCC; deletes + fails on a modelless setup (BOM/CRLF preserved).
- `backend/app/main.py` — `_start_brain_autostart()` + call in lifespan (guarded, kill-switch `SUPERMARKET_BRAIN_AUTOSTART=0`).
- `backend/app/services/business_brain/brain.py` — status version dynamic (`__version__`), import added.
- `frontend/insights.js` — cloud-narrative settings gone; local-model KPI; advisor → مغز فروشگاه (node --check OK).
- `mobile-android/.../BrainModel.java` — `unmetered()` + `autoSetup()` (Wi-Fi-only, once per install).
- `mobile-android/.../BrainScreens.java` — `prefer_llm:true`; `autoSetup` hook in Center.load(); `renderStandalone()` when PC unreachable.
- `backend/tests/test_v42_model_presence.py` — NEW: 14 tests (see below).
- Versions: backend `__init__.py` 4.2.0 · `setup.iss` 4.2.0 · Android derives 4.2.0 / versionCode **40200** from the backend file.
- `releases/android/SupermarketMobile-4.2.0.apk` (+ `.sha256`, `.idsig`) — preflight PASS, both ABIs, same cert as 4.1.x.

## 3. Test matrix (test_v42_model_presence.py)

1. verify_setup **passes** with an embedded model (size ≈ model).
2. verify_setup **rejects 56 MB and 59 MB** modelless setups (the owner's exact case).
3. verify_setup rejects a **missing model_payload.iss**.
4. verify_setup rejects a **non-Inno file** (no marker).
5. verify_setup CLI exit codes (1 + no PASS on failure).
6. builder-lib.ps1 wires verify_setup and deletes a bad Setup.exe.
7–9. lifespan starts `_start_brain_autostart`; it adopts + warm-starts in a daemon thread; kill-switch returns instantly.
10. insights.js contains no cloud narrative keys/providers; contains `/brain/model/status`.
11. brain.status reports the real version, not hardcoded 4.0.0.
12–13. Android chat prefers the model; autoSetup/unmetered/renderStandalone wired.
14. Android version follows the backend single source of truth (40200).

## 4. Honest remaining (unchanged unless noted)

- **No physical Android device / no Windows box in this sandbox** — as in 4.1.x rounds. The Java compiles via the same ecj toolchain that produced the 4.1.1 APK; the Windows verifier runs on Linux (pure-stdlib logic, tested with synthetic Inno payloads).
- Windows Setup.exe itself must be rebuilt by the owner from **this** tree with `builder-lib.ps1` — it cannot silently ship a modelless setup anymore; expect ≈ app + ~1 GB.
- On Android, first-open auto-download needs Wi-Fi and ~1 GB free; q3_k_m (924 MB, recommended) is the default.
