# RELEASE AUDIT — 4.3.1 «پایداری»

**Date:** 2026-09-24 · **Verdict: PASS for release.** Full suite **750 passed / 1 skipped** (+14 new v4.3.1 tests).

---

## 1. The owner's reports → root causes → fixes

| Report | Root cause | Fix |
|---|---|---|
| Android: model downloads + verifies, but the ENGINE never starts («مدل در حال بارگذاریه و کار نمی‌کنه») | ① start() always used the *recommended* model — if the user had fetched the other one, the engine refused; ② a llama-server that outlived the app still owned port 8081 → every new start spawned a duplicate that failed to bind; ③ the output drain discarded the engine's output → failures had no reason, slow loads looked dead | `readySpec()` (run whichever model is READY), ADOPT an already-healthy server on the port, keep the last 25 output lines (`tail()`), show them on the FAILED card, 240 s load window with live «…ثانیه — آخرین پیام موتور» progress notes |
| A touched/corrupt model must not re-download; stop/resume must exist | autoSetup only checked the recommended model's state | `anyState()` gate: auto-download ONLY on a truly fresh install; CORRUPT card = explicit manual «دریافت مجدد (فقط با خواست شما)» + a note that it never repeats automatically; PAUSED downloads quietly continue on Wi-Fi at app open |
| Windows: a «لوما سرور» window appeared after install («نمی‌دونم چیه») | llama-server.exe (the engine that executes the model) was spawned WITHOUT `CREATE_NO_WINDOW` → a black console on the shop PC | `CREATE_NO_WINDOW` on Windows — the engine is an internal component and is now invisible; behaviour unchanged |
| Windows chat stuck on «در حال بررسی داده‌های فروشگاه…» forever | LLM call timeout was 180 s (a slow shop CPU generating 512 tokens looks like a hang); a mid-load server (health 503 «loading model») caused a duplicate spawn | timeout 180 → 75 s then honest deterministic fallback (MODEL_FAILED); a loading server is WAITED FOR, not duplicated |
| `Cannot set properties of null (setting 'innerHTML')` killed pages | uncaught render errors left half-rendered dead pages | display-error shield: window error + unhandledrejection caught, logged, reported once/min in Persian; the app stays usable |
| The boot loading must prepare everything — no page loading after entry | data was fetched only when each view opened | warmup during the boot loading: the six REAL view endpoints fetched in parallel, served one-shot from the warm cache (`api()` consults it for GET) |
| The model must introduce itself + name its creator | no identity anywhere | instant deterministic identity answer (no model wait) naming **محمد صدیق خواجوی** and «مغز فروشگاه سوپری‌من»; the same identity baked into BOTH system prompts (PC + phone) |

**Honest note:** the four attached screenshots could not be viewed in this environment (no image capability) — the fixes above are grounded in the owner's written descriptions and the code paths they point at. If any on-screen error from the photos remains, its TEXT is enough to fix it immediately.

## 2. Verification highlights

- Identity answer through the REAL API (`/api/brain/chat`): mode=deterministic, ~instant, names سوپری‌من + محمد صدیق خواجوی (live check on the demo server).
- `_health_status()` unit-tested against llama-server's real 503-loading contract (HTTPError faked at the urlopen boundary).
- APK 4.3.1 compiled (ecj), dex contains readySpec/pushTail/anyState, preflight PASS, versionCode 40301, same certificate.

## 3. Changed files

`backend/app/services/business_brain/runtime.py` (CREATE_NO_WINDOW, _health_status, 75 s, adopt-loading, 240 s) · `planner.py` (_identity_answer + fast path) · `prompts.py` (identity block) · `frontend/app.js` (warmup + warm cache + display-error shield) · `BrainEngine.java` (adopt, tail, 240 s, progress notes, identity) · `BrainModel.java` (readySpec, anyState, auto-resume, no-auto-repeat) · `BrainScreens.java` (readySpec start, FAILED tail card, CORRUPT manual retry, engine note) · `backend/tests/test_v431_reliability.py` (14 tests) · versions 4.3.1/40301 · `releases/android/SupermarketMobile-4.3.1.apk`.
