# RELEASE AUDIT — 4.2.1

**Date:** 2026-09-23 · **Verdict: PASS for release.** Full suite **729 passed / 1 skipped** (+16 v4.2 layout tests reworked, +14 new v4.2.1 tests).

---

## 1. The owner's failed Windows build — what actually happened

His build was **correct**: PyInstaller 53.7 MB → model downloaded + sha256-verified (1,117 MB, `6a1a2eb6…`) → ISCC embedded it → **Setup.exe = 1,153.8 MB**. Then MY v4.2.0 verifier destroyed it:

| What failed | Why | The fix |
|---|---|---|
| «فایل Setup.exe نشانگر Inno Setup را ندارد» | `verify_setup.py` searched head[:4096] + tail[-4096]. The official Inno 6.7.3 source (`Shared.Struct.pas` `SetupID = 'Inno Setup Setup Data (6.7.0)'`, a 64-byte record written by `Compiler.SetupCompiler.pas` at the **start of the embedded setup-0 block**, i.e. after the ~700 KB stub PE) puts the signature ~700 KB into the file — outside both windows | scan the **first 4 MiB**, exact-case prefix `Inno Setup Setup Data (` (checked against the real `is-6_7_3` source); MZ header check; **never read the whole file** (v4.2.0 loaded the 1.1 GB file into RAM for the head check) |
| the Setup.exe was **deleted** | the catch block deleted on any verifier failure | **exit-code split**: exit 1 = model truly missing (payload/size floor) → delete; exit 2 = structural suspicion → FAIL but **KEEP** the file. `Invoke-Native` records `$Script:LastNativeExitCode`; the catch only deletes on 1 |
| console dead for the whole ~1 GB download | `Invoke-Native` captures output and prints at step end; non-tty milestones were every 30 s | `-Stream` switch (live `Write-Host` per line) used by the model step; milestone cadence 30 s → **5% / 8 s** |

**Ground-truth evidence:** the signature location was verified against the official Inno Setup 6.7.3 source (fetched from `jrsoftware/issrc`, tag `is-6_7_3`), not guessed. `test_verify_setup_real_inno_layout_passes` reproduces the owner's exact layout (MZ stub + signature at 700 KB + model body) and must PASS.

**What the owner must do:** rebuild once from this tree. The model he already downloaded is kept and re-verified (`already prepared`) — the 1 GB download does NOT repeat; ISCC re-compresses (~8 min) and the verifier now passes.

## 2. The other requests

| Request | Delivered |
|---|---|
| Android download: no progress line; must continue with app closed | `BrainModelService` — foreground service (dataSync, same anchor pattern as InstallService) keeps the process alive after the app is closed/swiped; live status-bar notification with MB + % («می‌توانید برنامه را ببندید»); in-tab progress bar fixed (the single-listener overwrite bug — the 2nd model card killed the 1st card's updates); resume-from-byte unchanged |
| Name the model «مدل تخصصی سوپری‌من», light = «لایت» | `display_name` in the Model Registry (q4_k_m = مدل تخصصی سوپری‌من, q3_k_m = سوپری‌من لایت) + `active_name` in status; Windows brain page + settings KPI + Android cards/notifications/toasts all use the brand; technical ids no longer shown as names |
| A proper icon for the model | generated icon (navy/cobalt/gold, app palette): `res/drawable/ic_model.png` (Android: model cards, chat header, assistant avatar) + `frontend/icons/model-192.png` / `model-512.png` (web: chat header, bubbles, model card) |
| Chat must improve (Android + Windows) | Android: messenger bubbles (user gradient right / brain card + avatar left), Persian-digit timestamps, role labels, animated typing dots. Windows: `.brain-bubble` had **no CSS at all** — full messenger styling + typing-dot keyframes + rounded composer |
| Windows single-colour → Android theme | both `styles.css` and `theme-pro.css` palettes now equal the Android `Ui.java` palette (dark: `#030B1D/#091733/#304780`, cobalt `#2563EB` → violet `#9654FF`, teal `#14B8B0`, gold `#FFC65A`; light equivalents) |

## 3. Test matrix (this round)

`test_v42_model_presence.py` (reworked, 16): real-Inno-layout PASS (the owner's exact case), 56/59 MB modelless → exit 1, missing payload → exit 1, markerless-but-payload-ok → **exit 2 (file kept)**, CLI exit codes, builder wiring (delete only on 1), autostart, cloud-UI absence, versions.

`test_v421_polish.py` (new, 14): registry display names + active_name exposure, Android brand (no tech-id titles), foreground service exists + registered (`dataSync`) + progress notification, listener-overwrite fix, icon shipped on both platforms, Android icon/typing usage, web chat CSS + ≥3 icon references, Android palette hexes in both CSS files, builder `-Stream`/`LastNativeExitCode`/keep-message, 5%/8 s milestone cadence, version pins (4.2.1 / 40201).

## 4. Changed files

- `scripts/model/verify_setup.py` — correct signature window, chunked reads, exit-code split.
- `installer/windows/builder-lib.ps1` — `-Stream`, `$Script:LastNativeExitCode`, delete-only-on-exit-1, live model step (BOM + CRLF preserved).
- `backend/app/services/business_brain/download_manager.py` — dense milestones when piped.
- `backend/app/services/business_brain/model_registry.py` — `display_name` field + `display_name()` helper.
- `backend/app/services/business_brain/model_manager.py` — `active_name` in status.
- `mobile-android/.../BrainModelService.java` — NEW foreground download anchor + progress notification.
- `mobile-android/.../BrainModel.java` — branded labels, named listeners, notification ticks, service start/stop.
- `mobile-android/.../BrainScreens.java` — branded model cards + icon, fixed listener, upgraded chat (bubbles/avatar/timestamps/typing dots), chat header.
- `mobile-android/app/src/main/AndroidManifest.xml` — service entry.
- `mobile-android/app/src/main/res/drawable/ic_model.png` — NEW icon (also `frontend/icons/model-192.png`, `model-512.png`).
- `frontend/brain.js`, `frontend/insights.js`, `frontend/styles.css`, `frontend/theme-pro.css` — branding, chat upgrade, Android palette.
- `backend/tests/test_v42_model_presence.py`, `backend/tests/test_v421_polish.py`.
- Versions: backend 4.2.1, setup.iss 4.2.1, Android versionCode **40201**.
- `releases/android/SupermarketMobile-4.2.1.apk` (+ `.sha256`, `.idsig`) — 9,668,191 B, 21 entries, both ABIs, preflight PASS, same signing certificate.

## 5. Honest remaining

- No physical Android device / no Windows box in this sandbox (unchanged): the Java compiles with the same ecj toolchain that ships the APK; the Inno signature fix is grounded in the official source, and the verifier logic is tested against that layout.
- The Windows Setup.exe must be rebuilt by the owner ONCE from this tree (~10 min, no re-download of the model). A 1,153.8 MB result is expected and will now pass verification.
