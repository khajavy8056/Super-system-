# RELEASE AUDIT — 4.3.2 «موتور اندروید روشن می‌شود»

**Date:** 2026-09-24 · **Verdict: PASS for release.** Full suite **760 passed / 1 skipped** (+7 new v4.3.2 tests).

---

## 1. The owner's report and what it uncovered

«همچنان در اندروید مدل کار نمیکنه و روشن نمیشه» (with two screenshots this environment cannot view — no image capability; deb.debian.org is blocked so tesseract cannot be installed either).

Code-level root-cause search (everything the screenshots could show was traced in source):

| Suspect | Verdict |
|---|---|
| network_security_config blocking cleartext to 127.0.0.1 | **eliminated** — `cleartextTrafficPermitted="true"` base config |
| engine refuses: wrong model spec / zombie port / no output (4.3.1 fixes) | fixed last round — this round's build was **not yet what he ran**, or the failure lies below |
| **RAM gate** | **THE BUG** — `start()` required `totalRamMb >= s.minRamMb` (q3_k_m = **3584 MB**, a PC-era number written so a "4 GB" Windows box reporting 3.8 GB still installs). The owner's phone (the 32-bit ARMv7 device from the 4.1.1 `INSTALL_FAILED_NO_MATCHING_ABIS` saga — typically 2-3 GB) was refused **before any attempt**. |

The phone's real requirement: model weights (mmap'd) + ~400 MB overhead → q3 ≈ **1281 MB**, q4 ≈ **1465 MB**. A 2 GB phone fits q3 with room to spare.

## 2. What changed

- `BrainEngine.neededRamMb/canRun/tightRam` — honest phone math; `start()` ATTEMPTS whenever it physically fits and refuses with real numbers only when impossible, always naming the alternative (the PC brain).
- **حالت اقتصادی رم**: tight RAM → launch with context 1024 (half), stated in Persian in the progress note.
- OOM-death message carries phone RAM + model size + advice + llama-server's last words.
- **«کپی گزارش موتور برای پشتیبانی»** on the FAILED card — clipboard copy of state/note/RAM/engine output, so any future failure can be pasted to support verbatim.

## 3. Verification

- RAM math test-pinned against the registry (1281/1465 vs the old 3584 gate).
- The old hard gate string and `fitsRam(c, s)` call are asserted ABSENT from `start()`.
- Economy context, notes, copy button — all test-pinned.
- APK 4.3.2 compiled (ecj), dex contains neededRamMb/tightRam, preflight PASS, versionCode 40302, same certificate (in-place update).
- Full suite **760 passed / 1 skipped**.

## 4. Honest remaining

- Still no physical Android device here: if the owner's phone reports ≥1281 MB total RAM (virtually any ARMv7 phone does), the engine will now genuinely attempt to start and either RUN or produce a copyable, numbered failure report. If it still fails, the copied report (one tap) replaces the screenshots entirely.
- On a true 2 GB phone, q3_k_m with context 1024 is tight but viable; if Android still kills it, the failure message now says exactly that and points to the paired-PC brain.
